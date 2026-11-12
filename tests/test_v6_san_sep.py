"""V6 ghi trạng thái C-san cho mỗi input không ổn định, và metrics báo tách RQ1 theo mã nguyên nhân V6 (Le chọn 26/10).
Phần 1: harness/checks.py v6_exe_case, v6_lib_case chạy C-san một lần qua rq1._exe_san, rq1.lib_san chỉ trên input không ổn định.
Phần 2: harness/metrics.py load_v6_causes, summarize_rq1(..., v6_causes), CLI --v6-causes. Không cần corpus.
Chạy: python3 -m unittest tests.test_v6_san_sep"""
import contextlib, io, json, os, tempfile, unittest
from unittest import mock

from harness import checks as CK
from harness import metrics as M
from harness import rq1

OK = dict(status='exit', rc=0, sig=None, out=b'1\n', err=b'')


def exe_run(unstable_argv):
    """run_exe giả: input có argv[0] == unstable_argv in ra số lần gọi (không ổn định); input khác luôn in '1'. Lần chạy C-san (san=True)
    trả về không báo. Ghi mọi lần gọi vào `calls`."""
    calls, n = [], [0]
    def f(b, argv, stdin, t, env=None, **k):
        calls.append(dict(bin=b, argv=argv, timeout=t, env=env, san=k.get('san', False)))
        if k.get('san'): return dict(OK, out=b'')
        if argv and argv[0] == unstable_argv:
            n[0] += 1; return dict(OK, out=f'{n[0]}\n'.encode())
        return dict(OK)
    return f, calls


class V6ExeSan(unittest.TestCase):
    def run_case(self, run, san=None, ins=((['u'], 'in-u', 'random'), (['s'], 'in-s', 'random'))):
        builds = []
        def build(B, bundle, case, san=False):
            builds.append(san); return dict(ok=True, bin='/c-san' if san else '/c', preset=None, sha256='h', log='')
        ps = [mock.patch.object(CK.BD, 'build_c_exe', side_effect=build),
              mock.patch.object(CK, 'exe_seeds', return_value=[dict(argv=[], stdin='')]),
              mock.patch.object(CK, '_cdict', return_value=({}, None)),
              mock.patch.object(CK, 'gen_inputs_v2', return_value=list(ins)),
              mock.patch.object(CK.OB, 'run_exe', side_effect=run)]
        if san is not None: ps.append(mock.patch.object(rq1, '_exe_san', side_effect=san))
        with contextlib.ExitStack() as st:
            for p in ps: st.enter_context(p)
            return CK.v6_exe_case('/b', 'B01_x', 'c', 10), builds

    def test_only_unstable_gets_c_san_via_rq1(self):
        run, calls = exe_run('u'); seen = []
        san = lambda *a: seen.append(a) or dict(status='ub', markers=['AddressSanitizer'], attempts=1)
        r, builds = self.run_case(run, san)
        self.assertEqual(r['n_unstable'], 1)
        u = r['unstable'][0]
        self.assertEqual(u['idx'], 0)
        self.assertEqual(u['c_san'], dict(status='ub', markers=['AddressSanitizer'], attempts=1))
        self.assertEqual(r['c_san_counts'], {'ub': 1})
        self.assertEqual(builds, [False, True])                       # C-san build một lần, khi có input không ổn định
        self.assertTrue(r['c_san_build']['ok'])
        self.assertEqual(len(seen), 1)                                # một lần mỗi input không ổn định
        cs, argv, stdin, to, env, c_status = seen[0]
        self.assertEqual((cs['bin'], argv, stdin, to, env, c_status), ('/c-san', ['u'], 'in-u', r['timeout'], None, 'exit'))
        self.assertEqual(len(calls), 2 * CK.V6_REPS)                  # không thêm lần chạy C thường nào

    def test_stable_case_unchanged(self):
        run, calls = exe_run('none')
        r, builds = self.run_case(run, lambda *a: self.fail('C-san không được chạy trên input ổn định'))
        self.assertEqual(r['n_unstable'], 0); self.assertEqual(builds, [False]); self.assertNotIn('c_san_build', r)
        self.assertEqual(r['c_san_counts'], {}); self.assertEqual(len(calls), 2 * CK.V6_REPS)

    def test_real_exe_san_uses_rq1_budget_and_env(self):
        run, calls = exe_run('u')
        r, _ = self.run_case(run)
        sc = [c for c in calls if c['san']]
        self.assertEqual(len(sc), 1)
        self.assertEqual(sc[0]['bin'], '/c-san')
        self.assertEqual(sc[0]['timeout'], r['timeout'] * rq1.SAN_TIMEOUT_FACTOR)
        self.assertEqual(sc[0]['env'], dict(rq1.EXE_SAN_ENV))
        self.assertEqual(r['unstable'][0]['c_san']['status'], 'no_report'); self.assertEqual(r['unstable'][0]['c_san']['attempts'], 1)
        self.assertEqual(len(calls), 2 * CK.V6_REPS + 1)

    def test_c_status_signal_when_any_rep_crashes(self):
        n = [0]
        def run(b, argv, stdin, t, env=None, **k):
            n[0] += 1
            return dict(OK, status='signal', rc=None, sig=11, out=b'') if n[0] == 3 else dict(OK)
        seen = []
        r, _ = self.run_case(run, lambda *a: seen.append(a) or dict(status='no_report', markers=[], attempts=1),
                             ins=((['u'], '', 'random'),))
        self.assertEqual(r['n_unstable'], 1); self.assertEqual(seen[0][5], 'signal')

    def test_san_exception_recorded(self):
        run, _ = exe_run('u')
        def boom(*a): raise RuntimeError('x')
        r, _ = self.run_case(run, boom)
        self.assertEqual(r['unstable'][0]['c_san']['status'], 'error'); self.assertIn('RuntimeError', r['unstable'][0]['c_san']['error'])
        self.assertEqual(r['status'], 'done'); self.assertEqual(r['c_san_counts'], {'error': 1})


class V6LibSan(unittest.TestCase):
    def run_case(self, san=None, csan_ok=True, crash_rep=None):
        info = {'runner_ok': True, 'c_ok': True, 'c-san_ok': csan_ok, 'runner_bin': '/rb', 'bundle': 'B01_x', 'case': 'c_lib'}
        n = {}                                 # số lần chạy C thường theo file vector
        def run(rb, root, p, t, rust, dump, *a, **k):
            i = n[p] = n.get(p, 0) + 1
            if p.endswith('u.json'):
                if crash_rep == i: return dict(k1='reported', result='SegmentationFault')
                return dict(k1='reported', result='Pass', state=i)
            return dict(k1='reported', result='Pass', state=0)
        ps = [mock.patch.object(CK.BD, 'build_lib_case', return_value=info),
              mock.patch.object(CK, '_lib_inputs', return_value=([('/v/u.json', 'random'), ('/v/s.json', 'random')], None, 1)),
              mock.patch.object(CK.BD, 'lib_root', side_effect=lambda B, info, kind, *a, **k: f'/root/{kind}'),
              mock.patch.object(CK.BD, 'asan_preload', return_value='/pre.so'),
              mock.patch.object(CK.OB, 'run_lib_retry', side_effect=run),
              mock.patch.object(CK.OB, 'equal_lib', side_effect=lambda a, b, **k: a == b)]
        if san is not None: ps.append(mock.patch.object(rq1, 'lib_san', side_effect=san))
        with contextlib.ExitStack() as st:
            for p in ps: st.enter_context(p)
            return CK.v6_lib_case('/b', 'B01_x', 'c_lib', 10), n

    def test_only_unstable_gets_c_san_via_rq1(self):
        seen = []
        r, n = self.run_case(lambda *a: seen.append(a) or dict(status='no_report', markers=[], attempts=1, san_result='Pass'))
        self.assertEqual(r['n_unstable'], 1); self.assertEqual(r['unstable'][0]['input'], 'u.json')
        self.assertEqual(r['unstable'][0]['c_san']['status'], 'no_report'); self.assertEqual(r['c_san_counts'], {'no_report': 1})
        self.assertTrue(r['c_san_build_ok'])
        self.assertEqual(len(seen), 1)
        rb, csroot, p, to, dump, preload, co = seen[0]
        self.assertEqual((rb, csroot, p, to, preload), ('/rb', '/root/c-san', '/v/u.json', 10 * rq1.SAN_TIMEOUT_FACTOR, '/pre.so'))
        self.assertEqual(dump, '/v/u.json.v6.Csan.dump'); self.assertEqual(co['state'], 1)
        self.assertEqual(n, {'/v/u.json': CK.V6_REPS, '/v/s.json': CK.V6_REPS})   # không thêm lần chạy C thường

    def test_crashed_rep_passed_as_c_obs(self):
        seen = []
        r, _ = self.run_case(lambda *a: seen.append(a) or dict(status='no_report', markers=[], attempts=1), crash_rep=4)
        self.assertEqual(seen[0][6]['result'], 'SegmentationFault')

    def test_csan_build_failed_is_infra_through_rq1(self):
        r, _ = self.run_case(csan_ok=False)
        self.assertFalse(r['c_san_build_ok'])
        self.assertEqual(r['unstable'][0]['c_san'], dict(status='infra', markers=[], attempts=0, cause='c_san_build_failed'))


# ---------------- metrics ----------------
def mcase(seed, statuses, bundle, name):
    return dict(bundle=bundle, case=name, seed=seed, status='done', pair_status=statuses, gen=dict(n_by_layer={'M': 1, 'MS': 1, 'A': 1}))


def mdiv(system, seed, bundle, name):
    from harness.record import blob
    return dict(kind='exe', bundle=bundle, case=name, system=system, seed=seed, stable=True, san='no_report', c_flag=False, c_ub=False,
                channels=['stdout'], c_rc=0, r_rc=0, c_to=False, r_to=False, c_out=blob(b'1\n'), r_out=blob(b'2\n'),
                c_err=blob(b''), r_err=blob(b''))


def translations():
    cs, ds = [], []
    for sd in (0, 1, 2):
        cs += [mcase(sd, {'a': 'P_test', 'b': 'P_test'}, 'P01_x', 'slow'),          # NEAR-TO: tách
               mcase(sd, {'a': 'P_test', 'b': 'rust_build_failed'}, 'B01_x', 'uninit'),   # C-UNINIT: tách
               mcase(sd, {'a': 'P_test', 'b': 'P_test'}, 'B01_x', 'ub'),            # C-UB: không tách
               mcase(sd, {'a': 'P_test', 'b': 'P_test'}, 'B01_x', 'plain')]         # không có mã
    ds = [mdiv('a', 0, 'P01_x', 'slow'), mdiv('b', 1, 'B01_x', 'uninit'), mdiv('a', 0, 'B01_x', 'uninit'), mdiv('b', 2, 'B01_x', 'plain')]
    D = {}
    for d in ds: D.setdefault((d['bundle'], d['case'], d['system'], d['seed']), []).append(d)
    return cs, D


CAUSES = [dict(kind='exe', bundle='P01_x', case='slow', code='NEAR-TO'), dict(kind='exe', bundle='B01_x', case='uninit', code='C-UNINIT'),
          dict(kind='exe', bundle='B01_x', case='ub', code='C-UB'), dict(kind='lib', bundle='B01_x', case='plain', code='UNEXPLAINED'),
          dict(kind='exe', bundle='B02_y', case='typo', code='C-SRC')]


class V6Separation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = self.tmp.name
        self.cs, self.D = translations()
        self.T = M.rq1_translations(self.cs, self.D, {}, [0, 1, 2])

    def tearDown(self): self.tmp.cleanup()

    def write(self, rows, name='c.jsonl'):
        p = os.path.join(self.d, name)
        with open(p, 'w') as f:
            for r in rows: f.write((r if isinstance(r, str) else json.dumps(r)) + '\n')
        return p

    def test_backward_compatible(self):
        a = M.summarize_rq1(self.T, 'exe'); b = M.summarize_rq1(self.T, 'exe', None)
        self.assertNotIn('v6_separation', a); self.assertEqual(a, b)
        c = M.summarize_rq1(self.T, 'exe', M.load_v6_causes(self.write(CAUSES)))
        self.assertEqual(c['by_group'], a['by_group'])                # số "all" không đổi khi có file

    def test_split_counts(self):
        s = M.summarize_rq1(self.T, 'exe', M.load_v6_causes(self.write(CAUSES)))['v6_separation']
        self.assertEqual(s['codes_separated'], ['C-UNINIT', 'C-SRC', 'NEAR-TO', 'UNEXPLAINED'])
        self.assertEqual(s['separated_cases'], ['B01_x/uninit:C-UNINIT', 'P01_x/slow:NEAR-TO'])
        self.assertEqual(s['unmatched'], ['B02_y/typo:C-SRC'])         # dòng lib không tính cho exe; case không có bản dịch hiện ở đây
        g = s['by_group']['all']
        self.assertTrue(g['split_ok'])
        self.assertEqual((g['separated']['n_translations'], g['separated']['P_test'], g['separated']['D_all']), (4, 3, 2))
        self.assertEqual(g['separated']['leave']['rust_build_failed'], 1)
        self.assertEqual((g['rest']['n_translations'], g['rest']['P_test'], g['rest']['D_all']), (4, 4, 1))
        self.assertEqual(g['by_code'], {'NEAR-TO': 2, 'C-UNINIT': 2, 'C-UB': 2})
        b01 = s['by_group']['B01']
        self.assertEqual((b01['separated']['n_translations'], b01['rest']['n_translations']), (2, 4))
        sa = g['by_system']['a']
        self.assertEqual((sa['all']['P_test'], sa['separated']['P_test'], sa['rest']['P_test']), (4, 2, 2))
        self.assertEqual((sa['all']['D_all'], sa['separated']['D_all'], sa['rest']['D_all']), (2, 2, 0))
        sb = g['by_system']['b']
        self.assertEqual((sb['separated']['n_translations'], sb['separated']['P_test'], sb['separated']['D_all']), (2, 1, 0))
        self.assertEqual(sb['rest']['D_all'], 1)
        self.assertTrue(all(x['funnel_ok'] for x in sb.values()))

    def test_lib_kind_uses_lib_rows_only(self):
        s = M.summarize_rq1(self.T, 'lib', M.load_v6_causes(self.write(CAUSES)))['v6_separation']
        self.assertEqual(s['separated_cases'], ['B01_x/plain:UNEXPLAINED']); self.assertEqual(s['n_cases_in_file'], 1)

    def test_load_errors(self):
        for rows in ([dict(kind='exe', bundle='b', case='c', code='C-UNINIT?')], [dict(kind='exe', bundle='b', case='c')],
                     [dict(kind='x', bundle='b', case='c', code='C-UB')],
                     [dict(kind='exe', bundle='b', case='c', code='C-UB'), dict(kind='exe', bundle='b', case='c', code='NEAR-TO')]):
            with self.assertRaises(ValueError): M.load_v6_causes(self.write(rows))
        same = [dict(kind='exe', bundle='b', case='c', code='C-UB')] * 2
        self.assertEqual(M.load_v6_causes(self.write(same + [''])), {('exe', 'b', 'c'): 'C-UB'})

    def test_cli(self):
        out = os.path.join(self.d, 'rq1'); os.makedirs(f'{out}/div')
        with open(f'{out}/rq1-exe.jsonl', 'w') as f:
            for c in self.cs: f.write(json.dumps(dict(c, kind='exe')) + '\n')
        with open(f'{out}/div/x.jsonl', 'w') as f:
            for v in self.D.values():
                for d in v: f.write(json.dumps(d) + '\n')
        def run(*extra):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf): M.main(['--rq1', out, *extra])
            return json.loads(buf.getvalue())
        plain = run(); sep = run('--v6-causes', self.write(CAUSES))
        self.assertNotIn('v6_separation', plain['rq1_exe'])
        self.assertEqual(sep['rq1_exe']['by_group'], plain['rq1_exe']['by_group'])
        self.assertEqual(sep['rq1_exe']['v6_separation']['by_group']['all']['separated']['n_translations'], 4)


if __name__ == '__main__':
    unittest.main()
