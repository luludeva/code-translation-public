"""harness.main_run (lượt chính RQ1, RQ2 và dryrun), harness.main_merge, ci/main_cost.py: guard tag freeze, mẫu phân tầng, chọn cặp,
manifest. Không cần corpus: hàm theo case, executor và metadata máy được thay bằng mock.
Chạy: python3 -m unittest tests.test_main_run"""
import collections, importlib.util, json, os, subprocess, tempfile, unittest
from concurrent.futures import Future
from unittest import mock

from harness import main_merge as MM
from harness import main_run as M
from harness import merge_shards as MS
from harness import pairs as PR
from harness import rq1 as R1
from harness import rq2 as R2
from harness.config import REPO

_spec = importlib.util.spec_from_file_location('main_cost', f'{REPO}/ci/main_cost.py')
MC = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(MC)


def git(repo, *a):
    p = subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', *a], capture_output=True, text=True)
    assert p.returncode == 0, (a, p.stderr)
    return p.stdout.strip()


class FakeEx:
    """Executor đồng bộ (mock không pickle được qua ProcessPoolExecutor)."""
    def __init__(self, *a, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def submit(self, fn, *a):
        f = Future(); f.set_result(fn(*a)); return f


class FreezeGuard(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='frz-')
        git(self.d, 'init', '-q'); os.makedirs(f'{self.d}/harness'); os.makedirs(f'{self.d}/ci')
        open(f'{self.d}/harness/a.py', 'w').write('x = 1\n'); open(f'{self.d}/ci/j.sh', 'w').write('echo\n')
        git(self.d, 'add', '.'); git(self.d, 'commit', '-q', '-m', 'c0'); git(self.d, 'tag', 'frz')

    def commit(self, msg='c'):
        git(self.d, 'add', '-A'); git(self.d, 'commit', '-q', '-m', msg)

    def test_no_tag(self):
        r = M.freeze_check(None, self.d); self.assertFalse(r['ok']); self.assertIn('không có tag', r['reason'])
        r = M.freeze_check('khong-co', self.d); self.assertFalse(r['ok']); self.assertIn('không tồn tại', r['reason'])

    def test_tag_at_head(self):
        r = M.freeze_check('frz', self.d)
        self.assertTrue(r['ok'], r); self.assertEqual(r['tag_commit'], r['head']); self.assertEqual(r['harness_diff'], [])

    def test_only_added_file_ok(self):
        open(f'{self.d}/harness/main_run.py', 'w').write('y = 2\n')
        open(f'{self.d}/ci/j.sh', 'w').write('echo sửa ci\n')            # ci/ không thuộc luật của harness/
        self.commit()
        r = M.freeze_check('frz', self.d)
        self.assertTrue(r['ok'], r); self.assertEqual(r['harness_added'], ['harness/main_run.py'])
        self.assertNotEqual(r['tag_commit'], r['head'])

    def test_modified_harness_file_refused(self):
        open(f'{self.d}/harness/new.py', 'w').write('n = 0\n'); open(f'{self.d}/harness/a.py', 'w').write('x = 2\n'); self.commit()
        r = M.freeze_check('frz', self.d)
        self.assertFalse(r['ok']); self.assertEqual(r['harness_not_added'], ['M\tharness/a.py'])

    def test_deleted_and_renamed_refused(self):
        git(self.d, 'mv', 'harness/a.py', 'harness/b.py'); self.commit()
        r = M.freeze_check('frz', self.d)
        self.assertFalse(r['ok']); self.assertIn('D\tharness/a.py', r['harness_not_added'])

    def test_uncommitted_change_refused(self):
        open(f'{self.d}/harness/a.py', 'w').write('x = 3\n')
        r = M.freeze_check('frz', self.d); self.assertFalse(r['ok']); self.assertIn('chưa commit', r['reason'])

    def test_tag_not_ancestor_refused(self):
        git(self.d, 'checkout', '-q', '-b', 'other'); open(f'{self.d}/harness/z.py', 'w').write('z\n'); self.commit()
        git(self.d, 'tag', '-f', 'frz2'); git(self.d, 'checkout', '-q', '-'); open(f'{self.d}/harness/w.py', 'w').write('w\n'); self.commit()
        r = M.freeze_check('frz2', self.d); self.assertFalse(r['ok']); self.assertIn('tổ tiên', r['reason'])

    def test_annotated_tag(self):
        git(self.d, 'tag', '-a', 'frz-a', '-m', 'freeze')
        self.assertTrue(M.freeze_check('frz-a', self.d)['ok'])

    def test_main_refuses_without_tag_or_bad_tag(self):
        with mock.patch.object(M, 'run_rq1') as run:
            with self.assertRaises(SystemExit) as e: M.main(['--kind', 'exe', '--out', '/tmp/x', '--level', 'x1'])
            self.assertIn('--freeze-tag', str(e.exception))
            bad = dict(ok=False, reason='harness/ có file đã có bị sửa')
            with mock.patch.object(M, 'freeze_check', return_value=bad), self.assertRaises(SystemExit) as e:
                M.main(['--kind', 'exe', '--out', '/tmp/x', '--level', 'x1', '--freeze-tag', 'T'])
            self.assertIn('Từ chối lượt chính', str(e.exception))
            run.assert_not_called()

    def test_main_mode_fixed_seeds_and_lib_env(self):
        ok = dict(ok=True, reason='ok', tag='T', tag_commit='c', head='h')
        with mock.patch.object(M, 'freeze_check', return_value=ok), mock.patch.object(M, 'run_rq1') as run:
            with self.assertRaises(SystemExit): M.main(['--kind', 'exe', '--out', '/tmp/x', '--freeze-tag', 'T', '--seeds', '0'])
            with mock.patch.dict(os.environ, {k: '' for k in M.LIB_ENV}), self.assertRaises(SystemExit) as e:
                M.main(['--kind', 'lib', '--out', '/tmp/x', '--freeze-tag', 'T', '--level', 'x1'])
            self.assertIn('census lần ba', str(e.exception))
            run.assert_not_called()
            M.main(['--kind', 'exe', '--out', '/tmp/x', '--freeze-tag', 'T', '--level', 'x1'])
            self.assertEqual(run.call_args[0][1], 'main')

    def test_dryrun_and_tag_exclusive(self):
        with self.assertRaises(SystemExit):
            M.build_parser().parse_args(['--kind', 'exe', '--freeze-tag', 'T', '--dryrun-sample', '0.1'])


class Sample(unittest.TestCase):
    def synthetic(self):
        return ([('B01_organic', f'o{i}') for i in range(30)] + [('B01_synthetic', f's{i}') for i in range(30)]
                + [('B02_synthetic', f'b{i}') for i in range(7)] + [('P00_perlin_noise', '001')] + [('P01_sphincs_plus', f'p{i}') for i in range(40)])

    def test_deterministic_and_order_free(self):
        cs = self.synthetic()
        a = M.stratified_sample(cs, 0.05, 0, 'exe'); b = M.stratified_sample(list(reversed(cs)), 0.05, 0, 'exe')
        self.assertEqual(a, b)
        self.assertNotEqual(M.stratified_sample(cs, 0.2, 1, 'exe')[0], M.stratified_sample(cs, 0.2, 2, 'exe')[0])
        self.assertNotEqual(M.stratified_sample(cs, 0.2, 1, 'exe')[0], M.stratified_sample(cs, 0.2, 1, 'lib')[0])

    def test_coverage(self):
        cs = self.synthetic()
        out, info = M.stratified_sample(cs, 0.05, 0, 'exe')
        self.assertEqual(set(info), {'B01', 'B02', 'P00', 'P01'})
        g = collections.Counter(M.group_of(b) for b, c in out)
        self.assertEqual(dict(g), {'B01': 3, 'B02': 1, 'P00': 1, 'P01': 2})
        self.assertTrue(set(out) <= set(cs))
        self.assertEqual(len(M.stratified_sample(cs, 1.0, 0, 'exe')[0]), len(cs))
        with self.assertRaises(ValueError): M.stratified_sample(cs, 0, 0, 'exe')

    def test_real_p_rep_exe(self):
        cs = PR.cases_of(PR.prep_pairs('exe'))
        out, info = M.stratified_sample(cs, 0.05, 0, 'exe')
        self.assertEqual({M.group_of(b) for b, c in cs}, {M.group_of(b) for b, c in out})
        self.assertTrue(all(v['n_sample'] >= 1 for v in info.values()))


class Theta(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(M.theta_of('exe', 'x10'), (dict(budget=30000, afl_execs=100000), 'x10'))
        self.assertEqual(M.theta_of('lib', 'x3'), (dict(n_inputs=600), 'x3'))
        self.assertEqual(M.theta_of('lib', None, n_inputs=200), (dict(n_inputs=200), 'x1'))
        self.assertEqual(M.theta_of('lib', None, n_inputs=123), (dict(n_inputs=123), 'custom'))
        self.assertEqual(M.theta_of('exe', 'x1', budget=3000), (dict(budget=3000, afl_execs=10000), 'x1'))

    def test_errors(self):
        for kw in (dict(kind='exe'), dict(kind='exe', budget=1), dict(kind='exe', level='x2'), dict(kind='exe', level='x1', budget=9),
                   dict(kind='lib', level='x1', budget=3000)):
            with self.assertRaises(SystemExit): M.theta_of(**kw)


class Run(unittest.TestCase):
    """Chạy run_rq1, run_rq2 với hàm theo case giả: kiểm cặp chuyển vào, khoá, manifest."""
    def setUp(self):
        self.calls = []
        def fake_safe(fn, B, bundle, case, pairs, seed, theta, timeout, div, tag):
            self.calls.append(dict(fn=fn, bundle=bundle, case=case, pairs=pairs, seed=seed, theta=theta, tag=tag, div=div))
            return dict(key=f'{bundle}/{case}/s{seed}', status='done', secs=1.0, kind='exe', bundle=bundle, case=case, seed=seed)
        self.p = [mock.patch.object(M, 'ProcessPoolExecutor', FakeEx), mock.patch.object(R1, '_safe', fake_safe),
                  mock.patch('harness.record.machine_info', return_value=dict(source='test')),
                  mock.patch.object(M.BD, 'setup_cando2', return_value=None)]
        for x in self.p: x.start()
        self.d = tempfile.mkdtemp(prefix='mr-')

    def tearDown(self):
        for x in self.p: x.stop()

    def test_pairs_equal_prep_pairs(self):
        for k in ('exe', 'lib'): self.assertEqual(M.main_pairs(k), PR.prep_pairs(k))

    def test_dryrun_rq1(self):
        out = f'{self.d}/rq1-dryrun'
        M.main(['--kind', 'exe', '--out', out, '--dryrun-sample', '0.05', '--sample-seed', '0', '--level', 'x1', '--workers', '2'])
        want, _ = M.stratified_sample(PR.cases_of(PR.prep_pairs('exe')), 0.05, 0, 'exe')
        by = collections.defaultdict(list)
        for p in PR.prep_pairs('exe'): by[(p['bundle'], p['tractor_case'])].append(p)
        self.assertEqual(sorted({(c['bundle'], c['case']) for c in self.calls}), want)
        self.assertEqual(sorted((c['bundle'], c['case'], c['seed']) for c in self.calls), sorted((b, c, s) for b, c in want for s in (0, 1, 2)))
        for c in self.calls:
            self.assertIs(c['fn'], R1.rq1_exe_case); self.assertEqual(c['pairs'], by[(c['bundle'], c['case'])])
            self.assertEqual(c['theta'], dict(budget=3000, afl_execs=10000)); self.assertEqual(c['tag'], 'dryrun')
        m = json.load(open(f'{out}/manifest.json')); p = m['params']
        self.assertEqual(p['tag'], 'dryrun'); self.assertIn('DRYRUN', p['DRYRUN']); self.assertEqual(p['main_run']['mode'], 'dryrun')
        self.assertIn('DRYRUN', p['main_run']['DRYRUN']); self.assertFalse(p['pilot'])
        self.assertEqual(p['main_run']['sample']['cases'], [f'{b}/{c}' for b, c in want])
        self.assertEqual(p['p_rep_source'], PR.source_info('exe')); self.assertIn('finished_utc', m)
        self.assertTrue(os.path.exists(f'{out}/DRYRUN.txt'))
        self.assertEqual(open(f'{out}/cases.txt').read().split(), [f'{b}/{c}' for b, c in want])
        self.assertEqual(len([l for l in open(f'{out}/rq1-exe.jsonl')]), 3 * len(want))
        n = len(self.calls); M.main(['--kind', 'exe', '--out', out, '--dryrun-sample', '0.05', '--level', 'x1'])   # chạy tiếp: không lặp
        self.assertEqual(len(self.calls), n)

    def test_main_rq1_manifest_and_cases(self):
        ok = dict(ok=True, reason='ok', tag='frz', tag_commit='abc', head='def', harness_added=['harness/main_run.py'])
        cs = PR.cases_of(PR.prep_pairs('exe'))[:2]; out = f'{self.d}/main-exe'
        with mock.patch.object(M, 'freeze_check', return_value=ok):
            M.main(['--kind', 'exe', '--out', out, '--freeze-tag', 'frz', '--level', 'x10', '--cases', ','.join(f'{b}/{c}' for b, c in cs)])
            with self.assertRaises(SystemExit):        # case ngoài P_rep
                M.main(['--kind', 'exe', '--out', out, '--freeze-tag', 'frz', '--level', 'x10', '--cases', 'B02_organic/qmath'])
            with self.assertRaises(SystemExit):        # cùng thư mục, nhãn mức khác
                M.main(['--kind', 'exe', '--out', out, '--freeze-tag', 'frz', '--level', 'x1'])
        p = json.load(open(f'{out}/manifest.json'))['params']
        self.assertEqual(p['tag'], 'main-x10'); self.assertEqual(p['seeds'], [0, 1, 2]); self.assertNotIn('DRYRUN', p)
        self.assertEqual(p['main_run']['freeze'], ok); self.assertEqual(p['main_run']['mode'], 'main')
        self.assertEqual(p['theta'], dict(budget=30000, afl_execs=100000)); self.assertEqual(p['n_cases'], 2)
        self.assertEqual(sorted({(c['bundle'], c['case']) for c in self.calls}), cs)

    def test_out_dir_guard(self):
        ok = dict(ok=True, reason='ok', tag='frz', tag_commit='abc', head='def')
        with self.assertRaises(SystemExit):
            M.main(['--kind', 'exe', '--out', f'{self.d}/plain', '--dryrun-sample', '0.05', '--level', 'x1'])
        with mock.patch.object(M, 'freeze_check', return_value=ok), self.assertRaises(SystemExit):
            M.main(['--kind', 'exe', '--out', f'{self.d}/x-dryrun', '--freeze-tag', 'frz', '--level', 'x1'])
        self.assertEqual(self.calls, [])

    def test_manifest_params_match_rq1_pilot(self):
        """Khoá manifest của main_run phủ khoá của rq1.main (pilot), giá trị SAME_PARAMS của merge_shards trùng khi cùng tham số."""
        pil = f'{self.d}/pilot'; out = f'{self.d}/run-dryrun'
        with mock.patch.object(R1, 'ProcessPoolExecutor', FakeEx):
            R1.main(['--pilot', '--kind', 'exe', '--out', pil, '--tag', 'x1', '--seeds', '0,1,2', '--workers', '6',
                     '--budget', '3000', '--afl-execs', '10000'])
        M.main(['--kind', 'exe', '--out', out, '--dryrun-sample', '0.05', '--level', 'x1'])
        a = json.load(open(f'{pil}/manifest.json'))['params']; b = json.load(open(f'{out}/manifest.json'))['params']
        self.assertEqual(set(a) - set(b), set())
        for k in MS.SAME_PARAMS: self.assertEqual(a[k], b[k], k)

    def test_rq2_dryrun_and_rows(self):
        self.assertEqual(M.rq2_rows('exe'), R2.r_run('exe', pilot=False))
        seen = []
        def fake_case(B, kind, rows, timeout):
            seen.extend(rows); return [dict(key=f'{r["system"]}/{r["bundle"]}/{r["tractor_case"]}', outcome='x') for r in rows]
        out = f'{self.d}/rq2-dryrun'
        with mock.patch.object(R2, 'rq2_case', fake_case):
            M.main(['--rq', '2', '--kind', 'exe', '--out', out, '--dryrun-sample', '0.05'])
        rows = R2.r_run('exe', pilot=False)
        want, _ = M.stratified_sample({(r['bundle'], r['tractor_case']) for r in rows}, 0.05, 0, 'exe')
        self.assertEqual(sorted(seen, key=lambda r: r['key'] if 'key' in r else (r['system'], r['bundle'], r['tractor_case'])),
                         sorted([r for r in rows if (r['bundle'], r['tractor_case']) in set(want)],
                                key=lambda r: r['key'] if 'key' in r else (r['system'], r['bundle'], r['tractor_case'])))
        p = json.load(open(f'{out}/manifest.json'))['params']
        self.assertEqual((p['cmd'], p['tag'], p['main_run']['mode']), ('rq2', 'dryrun', 'dryrun'))
        self.assertEqual(p['n_r_run_all'], len(rows))
        with self.assertRaises(SystemExit): M.main(['--rq', '2', '--kind', 'exe', '--out', out, '--dryrun-sample', '0.05', '--level', 'x1'])


class Merge(unittest.TestCase):
    def shard(self, d, mode, tag, tc='abc'):
        os.makedirs(d, exist_ok=True)
        json.dump(dict(params=dict(tag=tag, main_run=dict(mode=mode, freeze=dict(tag_commit=tc)))), open(f'{d}/manifest.json', 'w'))
        return d

    def test_mix_refused(self):
        t = tempfile.mkdtemp()
        a = self.shard(f'{t}/a', 'main', 'main-x10'); b = self.shard(f'{t}/b-dryrun', 'dryrun', 'dryrun')
        c = self.shard(f'{t}/c', 'main', 'main-x10', tc='zzz'); e = self.shard(f'{t}/e', 'main', 'main-x3')
        self.assertEqual(MM.check_shards('main', [a]), [])
        self.assertTrue(MM.check_shards('main', [a, b])); self.assertTrue(MM.check_shards('dryrun', [a]))
        self.assertTrue(MM.check_shards('main', [a, c])); self.assertTrue(MM.check_shards('main', [a, e]))
        self.assertTrue(MM.check_shards('main', [a], dict(tag='frz', tag_commit='other')))
        self.assertEqual(MM.check_shards('dryrun', [b]), [])


class Cost(unittest.TestCase):
    def test_lpt_and_extrapolate(self):
        bins = MC.lpt({('B01_x', str(i)): float(i) for i in range(1, 11)}, 2)
        self.assertEqual(sorted(len(b[1]) for b in bins), [5, 5]); self.assertEqual(sum(b[0] for b in bins), 55)
        self.assertLessEqual(abs(bins[0][0] - bins[1][0]), 1)
        st = dict(exe=dict(total_secs=dict(x1=10, x3=30, x10=100), par=dict(x1=2, x3=2, x10=2)))
        recs = {'exe': [dict(bundle='B01_s', case='a', secs=60), dict(bundle='P01_s', case='p', secs=36, input_insensitive=True)]}
        allc = {'exe': [('B01_s', 'a'), ('B01_s', 'b'), ('P01_s', 'p'), ('P01_s', 'q'), ('P01_s', 'r')]}
        r = MC.extrapolate(recs, allc, st, 'x1')['exe']['levels']
        self.assertAlmostEqual(r['x1']['worker_hours'], (60 * 2 + 36 * 3) / 3600, places=2)
        self.assertAlmostEqual(r['x10']['worker_hours'], (600 * 2 + 36 * 3) / 3600, places=2)


if __name__ == '__main__':
    unittest.main()
