"""Kiểm recompute_supp.py và writing/scripts/gen-sansupp-macros.py trên bản ghi bổ sung GIẢ LẬP (synthetic): bản ghi dựng bằng chính
harness.rq2_san_supp.supp_key với hàm sanitizer giả (không build, không thực thi gì), mỗi bản ghi mang synthetic=true.
Chạy từ thư mục exp 37:
  SUPP_RQ2_EXE=<rq2-exe.jsonl> [SUPP_REPO=<repo>] [SUPP_KEYS=<keys.txt>] [SUPP_BOUND=<bound-exe.json>] [SUPP_GEN=<gen-sansupp-macros.py>]
  [RQ2_SAN_SUPP_SRC=<thư mục chứa rq2_san_supp.py>] python3 -m unittest scripts/test_recompute_supp.py -v
SUPP_REQUIRE_DATA=1: thiếu dữ liệu thì test THẤT BẠI thay vì bỏ qua (review L10).
Lớp CIEvidence dựng thư mục kết quả CI giả lập (smoke, full: complete.json, attempt.json, run/manifest.json, gate, builds.json) và một
remote git thật có các lần nộp B0 (results/rq2-san-log, results-failed/rq2-san-log-<run>) để kiểm bằng chứng CI; lớp CIRealLayout dựng hai thư mục đó bằng chính `run` của module (supp_key thật, sanitizer giả, không có trường synthetic), scan và
sup_complete của ci/rq2-san-supp-lib.sh, rồi chạy recompute không có --allow-synthetic (review R2-06)."""
import collections, contextlib, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('SUPP_REPO') or os.path.join(HERE, '..', '..', '..'))
RQ2_EXE = os.environ.get('SUPP_RQ2_EXE')
KEYS = os.environ.get('SUPP_KEYS') or f'{REPO}/experiments/37-rq2-san-supp/data/keys.txt'
BOUND = os.environ.get('SUPP_BOUND') or f'{REPO}/experiments/38-rq2-san-bound/results/bound-exe.json'
GEN = os.environ.get('SUPP_GEN') or f'{REPO}/writing/scripts/gen-sansupp-macros.py'
HAVE = all(p and os.path.exists(p) for p in (RQ2_EXE, KEYS, BOUND))
REQUIRE = os.environ.get('SUPP_REQUIRE_DATA') == '1'
IID, COMMIT = 'i-0synthetic', 'c' * 40


def needs(cond, msg):
    if cond: return lambda x: x
    if not REQUIRE: return unittest.skip(msg)

    def deco(x):
        if isinstance(x, type):
            def setUpClass(c): raise AssertionError(f'SUPP_REQUIRE_DATA=1 mà thiếu dữ liệu: {msg}')
            x.setUpClass = classmethod(setUpClass); return x

        def f(self): self.fail(f'SUPP_REQUIRE_DATA=1 mà thiếu dữ liệu: {msg}')
        return f
    return deco


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


R = load('recompute_supp', os.path.join(HERE, 'recompute_supp.py'))


def fake_san(status, cause=None):
    def f(cs, argv, stdin, timeout, env, c_status=None, sink=None):
        n = 3 if status == 'infra' else 1
        if cause == 'c_san_build_failed': return dict(status='infra', markers=[], attempts=0, cause=cause)
        for k in range(1, n + 1):
            if sink is not None: sink.append(dict(attempt=k, san_status='clean', markers=[], status=status,
                                                  obs=dict(status='exit', rc=0, sig=None, secs=0.1, out=b'', err=b'synthetic')))
        return dict(status=status, markers=['runtime error:'] if status == 'ub' else [], attempts=n, san_run_status='exit', err_tail='')
    return f


class Synth:
    """Bản ghi bổ sung giả lập cho 36 key: status_of(key) -> trạng thái sanitizer giả ('build_failed' = build PIC vẫn lỗi)."""
    def __init__(self, tc):
        self.tc = tc
        _, self.SUPP = R.load_harness(REPO)
        from harness import build as BD, config as CF
        self.BD, self.CF = BD, CF
        self.keys = [l.strip() for l in open(KEYS) if l.strip()]
        self.s0, _ = self.SUPP.load_s0(RQ2_EXE, self.keys)
        self.d = tempfile.mkdtemp(prefix='synth-'); tc.addCleanup(shutil.rmtree, self.d, True)
        for k, r in self.s0.items():
            p = f'{self.d}/T/{r["bundle"]}/{r["case"]}/test_vectors'; os.makedirs(p)
            json.dump(dict(argv=[], stdin='', env=None), open(f'{p}/test.json', 'w'))
            wd = f'{self.d}/B/c-san/{r["bundle"]}/{r["case"]}'; os.makedirs(f'{wd}/build-ninja', exist_ok=True)
            open(f'{wd}.build.json', 'w').write('{}')
            open(f'{wd}/build-ninja/driver', 'w').write(r['case']); open(f'{wd}/build-ninja/libsphincs_core.so', 'w').write(r['case'] + 'so')

    def records(self, status_of):
        out = []
        self.SUPP.install_pic()
        try:
            for k in self.keys:
                st = status_of(k)
                cs = dict(ok=st != 'build_failed', bin='/nonexistent/driver', sha256='0' * 64, preset='test', secs=0)
                fn = fake_san('infra', 'c_san_build_failed') if st == 'build_failed' else fake_san(st)
                ctx = dict(try_no=1, amendment_commit=COMMIT, instance_id=IID, module_sha256=self.SUPP.module_sha())
                with mock.patch.object(self.BD, 'build_c_exe', return_value=cs):
                    r = self.SUPP.supp_key(f'{self.d}/B', self.s0[k], san_fn=fn, troot=f'{self.d}/T', ctx=ctx)
                r['synthetic'] = True
                out.append(r)
        finally:
            self.BD.SAN_FLAGS_EXE = self.CF.SAN_FLAGS_EXE
        return out

    def write(self, recs, name='supp-synthetic.jsonl'):
        p = f'{self.d}/{name}'
        with open(p, 'w') as f:
            for r in recs: f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
        return p

    def ci_dirs(self, recs, workers=6, iid=IID, attempt=1, full_iid=None, full_machine=None):
        """Thư mục kết quả CI giả lập theo bố cục job ghi (ci-out/<job> của nhánh results/): smoke (complete.json, attempt.json, gate,
        build/builds.json, run/) và full (complete.json, attempt.json, run/). full_iid: instance của job đầy đủ (mặc định iid; bản ghi
        của job đầy đủ mang instance đó); full_machine: đè trường máy trong manifest job đầy đủ."""
        root = tempfile.mkdtemp(prefix='ci-', dir=self.d)
        cases = [k.split('/')[-1] for k in self.keys]
        sm, fu = f'{root}/smoke', f'{root}/full'
        for d in (sm, fu):
            os.makedirs(f'{d}/run')
            open(f'{d}/{self.SUPP.COMPLETE}', 'w').write('{}'); json.dump(dict(attempt=attempt), open(f'{d}/{self.SUPP.ATTEMPT}', 'w'))
        os.makedirs(f'{sm}/gate'); os.makedirs(f'{sm}/build')
        json.dump(dict(ok=True, conditions=dict(s_orig=True, s_pic=True, s_cache=True, s_ninja=True, s_clang=True),
                       per_case={c: {} for c in cases}), open(f'{sm}/gate/smoke-gate.json', 'w'))
        builds = {c: dict(ok=True, sha256='0' * 64, files=self.SUPP.tree_hashes(f'{self.d}/B/c-san/P01_sphincs_plus/{c}')) for c in cases}
        json.dump(dict(builds=builds), open(f'{sm}/build/builds.json', 'w'))
        full_iid = full_iid or iid
        req = dict(instance_type=self.SUPP.ENV_REQ['instance_type'], ami_id=self.SUPP.ENV_REQ['ami_id'])
        for d, w, i, mk in ((sm, 6, iid, {}), (fu, workers, full_iid, full_machine or {})):
            m = dict(machine=dict(instance_id=None), params=dict(workers=w, gates=dict(env=dict(ok=True, machine=dict(req, instance_id=i, **mk)),
                                                                                  amendment=dict(commit=COMMIT))))
            json.dump(m, open(f'{d}/run/manifest.json', 'w'))
        first = {self.keys[0]}
        for d, part, i in ((sm, [r for r in recs if self.SUPP.base_key(r['key']) in first], iid),
                           (fu, [r for r in recs if self.SUPP.base_key(r['key']) not in first], full_iid)):
            with open(f'{d}/run/{self.SUPP.OUT_NAME}', 'w') as f:
                for r in part: f.write(json.dumps(dict(r, supp=dict(r.get('supp') or {}, instance_id=i)), sort_keys=True) + '\n')
        return sm, fu

    def b0_remote(self, branches=('a',)):
        """Remote git thật (bare) và một clone: mỗi phần tử của branches là một lần nộp B0 (đầu tiên ở results/rq2-san-log, sau đó ở
        results-failed/rq2-san-log-<i>, như guard Publish đẩy khi lần sau thiếu lịch sử). Trả đường dẫn clone (--b0-repo)."""
        d = tempfile.mkdtemp(prefix='b0-', dir=self.d); o, w, c = f'{d}/o.git', f'{d}/w', f'{d}/c'
        g = lambda cwd, *a: subprocess.run(['git', '-C', cwd, '-c', 'user.name=t', '-c', 'user.email=t@t', *a], check=True, capture_output=True)
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', o], check=True); g(d, 'init', '-q', '-b', 'main', w)
        concl = dict(a='TRÙNG x', c='CHƯA TRÙNG HOÀN TOÀN')
        for i, br in enumerate(branches):
            os.makedirs(f'{w}/ci-out/rq2-san-log', exist_ok=True)
            summ = f'B0 lần {i}\nmáy: instance_id={self.SUPP.B0_INSTANCE} (nguồn: IMDSv2)\nKẾT LUẬN: {concl[br]}\n'
            open(f'{w}/ci-out/rq2-san-log/summary.txt', 'w').write(summ)
            g(w, 'add', '-A'); g(w, 'commit', '-q', '-m', f'b0 {i}')
            g(w, 'push', '-q', '-f', o, 'HEAD:refs/heads/' + ('results/rq2-san-log' if i == 0 else f'results-failed/rq2-san-log-{i}'))
        g(d, 'clone', '-q', o, c)
        return c

    def recompute_ci(self, sm, fu, out='supp-exe-ci-synthetic.json', gate='none', synthetic=True, b0=None):
        o = f'{self.d}/{out}'
        b0 = b0 or getattr(self, '_b0', None) or self.b0_remote(); self._b0 = getattr(self, '_b0', None) or b0
        with contextlib.redirect_stdout(io.StringIO()) as so:
            rc = R.main(['--s0', RQ2_EXE, '--smoke-dir', sm, '--full-dir', fu, '--gate-dir', gate, '--b0-repo', b0, '--repo', REPO,
                         '--keys', KEYS, '--bound', BOUND, '--out', o] + (['--allow-synthetic'] if synthetic else []))
        self.last_stdout = so.getvalue()
        return rc, json.load(open(o)), o

    def recompute(self, recs, out='supp-exe-synthetic.json', extra=()):
        paths = [self.write(recs)] if recs is not None else []
        o = f'{self.d}/{out}'
        with contextlib.redirect_stdout(io.StringIO()):
            rc = R.main(['--s0', RQ2_EXE, '--supp', *paths, *extra, '--repo', REPO, '--keys', KEYS, '--bound', BOUND, '--out', o,
                         '--allow-synthetic'])
        return rc, json.load(open(o)), o


def mix(n_ub=0, n_inc=0, n_infra=0, n_bf=0):
    """Gán trạng thái theo thứ tự key: n_ub ub, n_inc inconclusive, n_infra infra, n_bf build lỗi, còn lại no_report."""
    seq = ['ub'] * n_ub + ['inconclusive'] * n_inc + ['infra'] * n_infra + ['build_failed'] * n_bf
    return lambda keys: (lambda k: seq[keys.index(k)] if keys.index(k) < len(seq) else 'no_report')


@needs(HAVE, 'đặt SUPP_RQ2_EXE (và SUPP_KEYS, SUPP_BOUND nếu chưa có trong repo)')
class Recompute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = {}

    def setUp(self):
        self.S = Synth(self)

    def run_mix(self, **kw):
        recs = self.S.records(mix(**kw)(self.S.keys))
        return self.S.recompute(recs)

    def test_no_change_reproduces_s0(self):
        """Build PIC vẫn lỗi ở cả 36 (đường _exe_san của build lỗi): mọi số trùng S₀, k = 36."""
        rc, d, _ = self.run_mix(n_bf=36)
        self.assertEqual(rc, 0, d['failed']); self.assertTrue(d['ok'])
        s = d['supp36']; self.assertEqual((s['k'], s['k_NA'], s['k_NR']), (36, 0, 36))
        self.assertEqual(d['rq3']['supp'], d['rq3']['s0'])
        self.assertEqual(d['rq2']['supp'], d['rq2']['s0'])
        c, a = d['rq3']['supp']['codex-gpt54'], d['rq3']['supp']['_all']
        self.assertEqual((c['L_R'], c['upper_num'], a['upper_num']), (36, 90, 419))
        self.assertEqual((d['rq2']['supp']['_all']['R_test'], d['rq2']['supp']['codex-gpt54']['R_test']), (92, 7))
        self.assertEqual(d['contains_codex'], 'contain')
        self.assertTrue(d['synthetic'])

    def test_all_no_report(self):
        rc, d, _ = self.run_mix()
        self.assertEqual(rc, 0, d['failed'])
        s = d['supp36']; self.assertEqual((s['k'], s['n_disagreement']), (0, 36))
        c, a = d['rq3']['supp']['codex-gpt54'], d['rq3']['supp']['_all']
        self.assertEqual((c['upper_num'], c['P0'], c['lower_num'], c['width_num']), (54, 106, 45, 9))
        self.assertEqual((a['upper_num'], a['P0'], a['lower_num']), (383, 1060, 300))
        self.assertEqual((d['rq2']['supp']['_all']['A'], d['rq2']['supp']['_all']['R_test'], d['rq2']['supp']['codex-gpt54']['R_test']),
                         (128, 128, 43))
        self.assertEqual(d['contains_codex'], 'do not contain')
        self.assertIn('do not contain', d['sentence'])

    def test_mixed(self):
        rc, d, _ = self.run_mix(n_ub=10, n_inc=5, n_infra=3)
        self.assertEqual(rc, 0, d['failed'])
        s = d['supp36']; self.assertEqual((s['k'], s['k_NA'], s['k_NR']), (18, 15, 3))
        self.assertEqual(s['by_reason'], {'behavioral_disagreement:None': 18, 'not_adjudicable:sanitizer_inconclusive': 5,
                                          'not_adjudicable:ub_in_c': 10, 'not_re_examined:incomplete_harness_run:san_infra': 3})
        c = d['rq3']['supp']['codex-gpt54']
        self.assertEqual((c['A'], c['F'], c['L_R'], c['upper_num'], c['width_num']), (7 + 18, 0, 18, 72, 27))
        self.assertEqual(d['rq3']['supp']['_all']['upper_num'], 383 + 18)
        q = d['rq2']['supp']
        self.assertEqual((q['_all']['R_test'], q['codex-gpt54']['R_test'], q['_all']['not_adjudicable']), (125, 40, 15))
        self.assertEqual(d['contains_codex'], 'contain')
        self.assertEqual(len(s['keys_by_group']['not_adjudicable:ub_in_c']), 10)

    def test_boundary_k8_k9(self):
        rc, d8, _ = self.run_mix(n_ub=8); self.assertEqual(rc, 0, d8['failed'])
        rc, d9, _ = self.run_mix(n_inc=4, n_infra=5); self.assertEqual(rc, 0, d9['failed'])
        self.assertEqual((d8['supp36']['k'], d8['contains_codex'], d8['rq3']['supp']['codex-gpt54']['upper_num']), (8, 'do not contain', 62))
        self.assertEqual((d9['supp36']['k'], d9['contains_codex'], d9['rq3']['supp']['codex-gpt54']['upper_num']), (9, 'contain', 63))

    def test_stop_missing_duplicate_extra(self):
        recs = self.S.records(mix()(self.S.keys))
        rc, d, _ = self.S.recompute(recs[1:])
        self.assertEqual(rc, 1); self.assertTrue(d['stopped']); self.assertEqual(d['merge']['missing'], self.S.keys[:1])
        rc, d, _ = self.S.recompute(recs + recs[:1]); self.assertEqual(rc, 1); self.assertEqual(d['merge']['duplicate'], self.S.keys[:1])
        x = dict(recs[0], key='codex-gpt54/P01_sphincs_plus/999_x')
        rc, d, _ = self.S.recompute(recs + [x]); self.assertEqual(rc, 1); self.assertEqual(d['merge']['extra'], [x['key']])

    def test_harness_error_twice_keeps_s0(self):
        """Le chốt 5/11 (review L8): giữ bản ghi S₀, outcome not_re_examined (tính vào k), mã lý do riêng supp_harness_error."""
        recs = self.S.records(mix()(self.S.keys))
        k = self.S.keys[3]
        err = [dict(key=f'{k}#error', status='harness_error', reason='harness_error', synthetic=True,
                    supp=dict(try_no=i, utc_end='2026-11-06T00:00:00Z')) for i in (1, 2)]
        rc, d, _ = self.S.recompute([r for r in recs if r['key'] != k] + err)
        self.assertEqual(rc, 0, d['failed'])
        self.assertEqual((d['supp36']['k'], d['supp36']['k_NR']), (1, 1)); self.assertEqual(d['merge']['kept_s0_after_two_errors'], [k])
        self.assertEqual(d['supp36']['by_reason'], {'behavioral_disagreement:None': 35, 'not_re_examined:supp_harness_error': 1})
        self.assertNotIn('not_re_examined:incomplete_harness_run:san_build_failed', d['supp36']['by_reason'])
        self.assertEqual(d['attrition_rrun']['supp']['_all']['not_re_examined:supp_harness_error'], 1)
        self.assertEqual(d['attrition_rrun']['supp']['_all']['not_re_examined:incomplete_harness_run:san_build_failed'], 0)
        self.assertEqual(d['attrition_rrun']['s0']['_all']['not_re_examined:incomplete_harness_run:san_build_failed'], 36)
        rc, d, _ = self.S.recompute([r for r in recs if r['key'] != k] + err[:1])          # một lỗi, chưa chạy lại: thiếu key
        self.assertEqual(rc, 1); self.assertEqual(d['merge']['missing'], [k]); self.assertTrue(d['stopped'])
        rc, d, _ = self.S.recompute(recs + err)                                                # bản ghi kết quả sau hai lần hỏng
        self.assertEqual(rc, 1); self.assertEqual(d['merge']['over_tries'], [k]); self.assertTrue(d['stopped'])
        rc, d, _ = self.S.recompute([r for r in recs if r['key'] != k] + err + err[:1])      # ba lần thử
        self.assertEqual(rc, 1); self.assertEqual(d['merge']['over_tries'], [k])

    def test_tampered_records_fail(self):
        recs = self.S.records(mix()(self.S.keys))
        for mut in ('runs', 'outcome', 'flags', 'input'):
            rs = json.loads(json.dumps(recs)); r = rs[5]; v = r['vectors'][0]
            if mut == 'runs': v['obs']['runs'][0]['first']['c']['rc'] = 1
            elif mut == 'outcome': r['outcome'] = 'behavioral_agreement'; r['reasons'] = []
            elif mut == 'flags': r['supp']['san_flags_exe'] = r['supp']['san_flags_exe'][:-1]
            elif mut == 'input': v['input']['stdin']['sha256'] = '0' * 64
            rc, d, _ = self.S.recompute(rs)
            self.assertEqual(rc, 1, mut); self.assertIn(r['key'], d['merge']['record_errors'], mut)
            self.assertTrue(d['stopped'], mut)                                      # Le chốt vòng 4 (R3-05): mọi kiểm hỏng là lượt đã dừng

    def test_late_record_is_stopped(self):
        """Le chốt vòng 3 (D3c): bản ghi xong từ hạn chót trở đi (đúng giây hạn chót cũng tính) làm lượt dừng: gói A, không macro."""
        recs = self.S.records(mix()(self.S.keys))
        rs = json.loads(json.dumps(recs)); rs[5]['supp']['utc_end'] = '2026-11-10T05:00:00Z'
        rc, d, _ = self.S.recompute(rs)
        self.assertEqual(rc, 1); self.assertTrue(d['stopped']); self.assertEqual(d['merge']['late'], [rs[5]['key']])
        self.assertIn('gói A', d['stopped_note'])

    def test_synthetic_guards(self):
        recs = self.S.records(mix()(self.S.keys)); p = self.S.write(recs)
        base = ['--s0', RQ2_EXE, '--supp', p, '--repo', REPO, '--keys', KEYS, '--bound', BOUND]
        # review L6: bỏ trường synthetic không giúp đi qua: --supp không có bằng chứng CI bị từ chối khi không có --allow-synthetic
        p2 = self.S.write([{k: v for k, v in r.items() if k != 'synthetic'} for r in recs], 'nosyn.jsonl')
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit): R.main(['--s0', RQ2_EXE, '--supp', p2, '--repo', REPO, '--keys', KEYS, '--bound', BOUND,
                                                        '--out', f'{self.S.d}/nosyn.json'])
            with self.assertRaises(SystemExit): R.main(base + ['--out', f'{self.S.d}/x-synthetic.json'])          # thiếu --allow-synthetic
            with self.assertRaises(SystemExit): R.main(base + ['--out', f'{self.S.d}/supp-exe.json', '--allow-synthetic'])
            with self.assertRaises(SystemExit): R.main(base + ['--out', f'{self.S.d}/results/supp-synthetic.json', '--allow-synthetic'])

    def test_bad_bound_crosscheck_fails(self):
        recs = self.S.records(mix(n_ub=2)(self.S.keys))
        b = json.load(open(BOUND)); b['rq3']['tables']['codex-gpt54']['rows'][2]['upper_num'] += 1
        bp = f'{self.S.d}/bound-bad.json'; json.dump(b, open(bp, 'w'))
        p = self.S.write(recs); o = f'{self.S.d}/bad-synthetic.json'
        with contextlib.redirect_stdout(io.StringIO()):
            rc = R.main(['--s0', RQ2_EXE, '--supp', p, '--repo', REPO, '--keys', KEYS, '--bound', bp, '--out', o, '--allow-synthetic'])
        self.assertEqual(rc, 1)
        d = json.load(open(o)); self.assertTrue(any('bound-exe.json' in w for w in d['failed'])); self.assertTrue(d['stopped'])
        self.assertIn('gói A', d['stopped_note'])

    @needs(os.path.exists(GEN), 'đặt SUPP_GEN tới gen-sansupp-macros.py')
    def test_macros(self):
        GM = load('gen_sansupp', GEN)
        rc, d, o = self.run_mix(n_ub=10, n_inc=5, n_infra=3)
        tex = f'{self.S.d}/sansupp-numbers-SYNTHETIC.tex'
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(GM.main(['--in', o, '--out', tex]), 0)
        t = open(tex).read()
        self.assertTrue(t.startswith('% *** DU LIEU GIA LAP (SYNTHETIC)'))
        m = dict(l[len('\\rqSet{'):-1].split('}{') for l in t.splitlines() if l.startswith('\\rqSet{'))
        self.assertIn(f'sha256 {R.sha_file(o)}', t.splitlines()[2])                                   # review N9
        self.assertNotIn('rqSanSuppADisagreeExeAllCodexNum', m)                                           # Le chốt 5/11: đổi tên
        self.assertEqual(m['rqSanSuppAExeAllCodexNum'], str(7 + 18))
        want = dict(rqSanSuppNExeAllCodexNum='36', rqSanSuppKExeAllCodexNum='18', rqSanSuppKNotAdjExeAllCodexNum='15',
                    rqSanSuppKNotReexExeAllCodexNum='3', rqSanSuppDisagreeOfSuppExeAllCodexNum='18',
                    rqSanSuppReasonNotReexSuppHarnessErrorExeAllCodexNum='0',
                    rqSanSuppRrunSZeroNotReexSanBuildFailedExeAllNum='36', rqSanSuppRrunSuppNotReexSanBuildFailedExeAllNum='0',
                    rqSanSuppRrunSZeroDisagreeExeAllNum='92', rqSanSuppRrunSuppDisagreeExeAllNum='110',
                    rqSanSuppRrunSuppNotAdjUbInCExeAllCodexNum='10', rqSanSuppRrunSuppNotReexSanInfraExeAllCodexNum='3',
                    rqSanSuppRrunSZeroDisagreeExeAllCodexNum='7', rqSanSuppRrunSuppHarnessErrorExeAllNum='0',
                    rqSanSuppFFExeAllNum='0', rqSanSuppFFExeAllDen='125', rqSanSuppFFExeAllPct='0.0',
                    rqSanSuppFFExeAllCodexNum='0', rqSanSuppFFExeAllCodexDen='40', rqSanSuppLrExeAllCodexNum='18', rqSanSuppLrExeAllNum='18',
                    rqSanSuppSRHiExeAllCodexNum='72', rqSanSuppSRHiExeAllCodexDen='106', rqSanSuppSRHiExeAllCodexPct='67.9',
                    rqSanSuppSRHiExeAllNum='401', rqSanSuppSRHiExeAllDen='1060', rqSanSuppWidthExeAllCodexNum='27',
                    rqSanSuppContainsExeAllCodex='contain', rqSanSuppReasonNotAdjUbInCExeAllCodexNum='10',
                    rqSanSuppReasonNotReexSanInfraExeAllCodexNum='3', rqSanSuppReasonAgreeExeAllCodexNum='0')
        for k, v in want.items(): self.assertEqual(m.get(k), v, k)
        self.assertNotIn('??', m.values())
        kt = open(f'{self.S.d}/sansupp-numbers-SYNTHETIC-keys.tex').read()                              # review L7: danh sách key phụ lục
        self.assertTrue(kt.startswith('% *** DU LIEU GIA LAP (SYNTHETIC)'))
        self.assertIn('\\paragraph{not\\_adjudicable:ub\\_in\\_c} (10)', kt)
        self.assertEqual(kt.count('\\texttt{'), 36)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit): GM.main(['--in', o, '--out', f'{self.S.d}/sansupp-numbers.tex'])
            with self.assertRaises(SystemExit): GM.main(['--in', o, '--out', os.path.join(GM.ROOT, 'writing', 'generated', 'x-synthetic.tex')])
        bad = dict(d, ok=False); bp = f'{self.S.d}/bad-synthetic.json'; json.dump(bad, open(bp, 'w'))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(GM.main(['--in', bp, '--out', f'{self.S.d}/y-synthetic.tex']), 1)
        self.assertFalse(os.path.exists(f'{self.S.d}/y-synthetic.tex'))



@needs(HAVE, 'đặt SUPP_RQ2_EXE (và SUPP_KEYS, SUPP_BOUND nếu chưa có trong repo)')
class CIEvidence(unittest.TestCase):
    """Recompute đọc thư mục kết quả CI và tính lượt là đã dừng (D3b) khi có STOP.txt, job chưa hoàn tất, quá hai lần thử, cổng chưa đạt,
    khác máy, khác số worker, driver hay .so khác builds.json của job smoke."""
    def setUp(self):
        self.S = Synth(self)
        self.recs = self.S.records(mix(n_ub=3)(self.S.keys))

    def stopped(self, sm, fu, gate='none', what=None, b0=None):
        rc, d, _ = self.S.recompute_ci(sm, fu, gate=gate, b0=b0)
        self.assertEqual(rc, 1); self.assertTrue(d['stopped'], d['failed']); self.assertIn('DỪNG', self.S.last_stdout)
        if what: self.assertTrue(any(what in f for f in d['failed']), (what, d['failed']))
        return d

    def test_ok(self):
        sm, fu = self.S.ci_dirs(self.recs)
        rc, d, _ = self.S.recompute_ci(sm, fu)
        self.assertEqual(rc, 0, d['failed']); self.assertEqual(d['supp36']['k'], 3); self.assertFalse(d['stopped'])
        self.assertEqual(d['provenance']['ci']['instance_ids'], [IID]); self.assertEqual(d['provenance']['ci']['gate_dir'], 'none')
        sm, fu = self.S.ci_dirs(self.recs, attempt=2)
        rc, d, _ = self.S.recompute_ci(sm, fu); self.assertEqual(rc, 0); self.assertEqual(d['provenance']['ci']['attempts'], dict(smoke=2, full=2))

    def test_stop_file_anywhere(self):
        for where in ('smoke', 'full', 'gate'):
            sm, fu = self.S.ci_dirs(self.recs); gate = 'none'
            if where == 'gate': gate = tempfile.mkdtemp(dir=self.S.d); open(f'{gate}/STOP.txt', 'w').write('x')
            else: open(f'{sm if where == "smoke" else fu}/STOP.txt', 'w').write('x')
            self.stopped(sm, fu, gate, 'STOP.txt')

    def test_gate_dir_required(self):
        """review R2-15: --gate-dir bắt buộc (thư mục, hoặc none sau khi ls-remote không thấy nhánh gate)."""
        sm, fu = self.S.ci_dirs(self.recs)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                R.main(['--s0', RQ2_EXE, '--smoke-dir', sm, '--full-dir', fu, '--repo', REPO, '--keys', KEYS, '--bound', BOUND,
                        '--out', f'{self.S.d}/x-synthetic.json', '--allow-synthetic'])
        self.stopped(sm, fu, f'{self.S.d}/khong-co-gate', 'thư mục')

    def test_incomplete_or_third_attempt(self):
        """D1: job không có complete.json, là lần nộp noop, hoặc ghi lần thử thứ ba: lượt đã dừng (D3b), dù không có STOP.txt."""
        sm, fu = self.S.ci_dirs(self.recs); os.remove(f'{fu}/complete.json'); self.stopped(sm, fu, what='hoàn tất')
        sm, fu = self.S.ci_dirs(self.recs); open(f'{sm}/noop.txt', 'w').write('x'); self.stopped(sm, fu, what='hoàn tất')
        sm, fu = self.S.ci_dirs(self.recs, attempt=3); self.stopped(sm, fu, what='lần thử')
        sm, fu = self.S.ci_dirs(self.recs); os.remove(f'{sm}/attempt.json'); self.stopped(sm, fu, what='lần thử')

    def test_gate_not_ok(self):
        sm, fu = self.S.ci_dirs(self.recs)
        g = json.load(open(f'{sm}/gate/smoke-gate.json')); g['ok'] = False; json.dump(g, open(f'{sm}/gate/smoke-gate.json', 'w'))
        self.stopped(sm, fu, what='cổng')

    def test_instance_and_workers(self):
        sm, fu = self.S.ci_dirs(self.recs, workers=2); self.stopped(sm, fu, what='worker')
        sm, fu = self.S.ci_dirs(self.recs)
        m = json.load(open(f'{fu}/run/manifest.json')); m['params']['gates']['env']['machine']['instance_id'] = None
        json.dump(m, open(f'{fu}/run/manifest.json', 'w')); self.stopped(sm, fu, what='instance id')
        sm, fu = self.S.ci_dirs(self.recs); os.remove(f'{sm}/run/manifest.json'); self.stopped(sm, fu, what='manifest')

    def test_other_instance_same_type_and_ami(self):
        """Le chốt 2026-11-06: job đầy đủ trên instance khác job smoke, cùng loại máy và AMI: đạt, provenance và stdout công bố."""
        sm, fu = self.S.ci_dirs(self.recs, full_iid='i-0other')
        rc, d, _ = self.S.recompute_ci(sm, fu)
        self.assertEqual(rc, 0, d['failed']); self.assertFalse(d['stopped'])
        inst = d['provenance']['ci']['instance']
        self.assertEqual((inst['smoke'], inst['full'], inst['differ']), (IID, 'i-0other', True)); self.assertIn('notes', inst['note'])
        self.assertEqual(d['provenance']['ci']['instance_ids'], sorted([IID, 'i-0other']))
        self.assertIn('KHÁC NHAU', [l for l in self.S.last_stdout.splitlines() if l.startswith('instance:')][0])
        sm, fu = self.S.ci_dirs(self.recs)
        rc, d, _ = self.S.recompute_ci(sm, fu); self.assertFalse(d['provenance']['ci']['instance']['differ'])
        self.assertNotIn('KHÁC NHAU', [l for l in self.S.last_stdout.splitlines() if l.startswith('instance:')][0])

    def test_other_type_or_ami_is_stopped(self):
        """Loại máy, AMI lệch mục 7 hay cổng môi trường không đạt ở manifest một job: một kiểm của mục 8 hỏng, lượt đã dừng (mục 10)."""
        for mk in (dict(instance_type='m7i-flex.large'), dict(ami_id='ami-0other'), dict(instance_type=None)):
            for fi in (None, 'i-0other'):
                sm, fu = self.S.ci_dirs(self.recs, full_iid=fi, full_machine=mk); self.stopped(sm, fu, what='loại máy')
        sm, fu = self.S.ci_dirs(self.recs)
        m = json.load(open(f'{sm}/run/manifest.json')); m['params']['gates']['env']['ok'] = False
        json.dump(m, open(f'{sm}/run/manifest.json', 'w')); self.stopped(sm, fu, what='cổng môi trường')

    def test_record_instance_matches_its_job(self):
        """Bản ghi của job đầy đủ mang instance id khác manifest job đầy đủ: lượt đã dừng."""
        sm, fu = self.S.ci_dirs(self.recs, full_iid='i-0other')
        m = json.load(open(f'{fu}/run/manifest.json')); m['params']['gates']['env']['machine']['instance_id'] = 'i-0third'
        json.dump(m, open(f'{fu}/run/manifest.json', 'w')); self.stopped(sm, fu, what='bản ghi của một job')

    def test_driver_or_so_mismatch(self):
        for field in ('sha256', 'files'):
            sm, fu = self.S.ci_dirs(self.recs)
            b = json.load(open(f'{sm}/build/builds.json')); c = self.S.keys[4].split('/')[-1]
            if field == 'sha256': b['builds'][c]['sha256'] = '1' * 64
            else: b['builds'][c]['files']['build-ninja/libsphincs_core.so'] = '2' * 64
            json.dump(b, open(f'{sm}/build/builds.json', 'w'))
            self.stopped(sm, fu, what='builds.json')

    def test_b0_c_anywhere(self):
        """Le chốt vòng 4 (R3-02, R3-07): một lần B0 nhánh (c) ở results-failed/rq2-san-log-<run> làm lượt dừng; ls-remote lỗi thì thoát lỗi."""
        sm, fu = self.S.ci_dirs(self.recs)
        rc, d, _ = self.S.recompute_ci(sm, fu, b0=self.S.b0_remote(('a', 'a')))
        self.assertEqual(rc, 0, d['failed']); self.assertEqual(len(d['provenance']['b0']['refs']), 2)
        self.stopped(sm, fu, what='nhánh (c)', b0=self.S.b0_remote(('a', 'c')))
        bad = self.S.b0_remote(); subprocess.run(['git', '-C', bad, 'remote', 'set-url', 'origin', f'{self.S.d}/khong-co.git'], check=True)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit): self.S.recompute_ci(sm, fu, out='b0-bad-synthetic.json', b0=bad)
        self.assertFalse(os.path.exists(f'{self.S.d}/b0-bad-synthetic.json'))
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                R.main(['--s0', RQ2_EXE, '--smoke-dir', sm, '--full-dir', fu, '--gate-dir', 'none', '--repo', REPO, '--keys', KEYS,
                        '--bound', BOUND, '--out', f'{self.S.d}/x-synthetic.json', '--allow-synthetic'])

    def test_module_sha(self):
        """Le chốt vòng 4 (R3-08): bản ghi của job đầy đủ trộn hai sha module (hoặc thiếu sha) là lượt đã dừng; smoke khác đầy đủ thì báo."""
        recs = json.loads(json.dumps(self.recs)); recs[7]['supp']['module_sha256'] = 'f' * 64
        sm, fu = self.S.ci_dirs(recs); self.stopped(sm, fu, what='sha256 module')
        recs = json.loads(json.dumps(self.recs)); del recs[7]['supp']['module_sha256']
        sm, fu = self.S.ci_dirs(recs); self.stopped(sm, fu, what='sha256 module')
        recs = json.loads(json.dumps(self.recs)); recs[0]['supp']['module_sha256'] = 'e' * 64          # key smoke chạy module khác
        sm, fu = self.S.ci_dirs(recs)
        rc, d, _ = self.S.recompute_ci(sm, fu)
        self.assertEqual(rc, 0, d['failed']); self.assertTrue(d['provenance']['ci']['module_sha256']['smoke_full_differ'])
        self.assertIn('KHÁC NHAU', self.S.last_stdout)

    def test_supp_and_dirs_exclusive(self):
        sm, fu = self.S.ci_dirs(self.recs)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                R.main(['--s0', RQ2_EXE, '--smoke-dir', sm, '--gate-dir', 'none', '--repo', REPO, '--keys', KEYS, '--bound', BOUND,
                        '--out', f'{self.S.d}/x.json'])


LIB_SH = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'ci', 'rq2-san-supp-lib.sh'))


@needs(HAVE and os.path.exists(LIB_SH), 'đặt SUPP_RQ2_EXE; cần ci/rq2-san-supp-lib.sh')
class CIRealLayout(unittest.TestCase):
    """review R2-06: đường CI của recompute trên bản ghi không phải synthetic, dựng bằng `run` thật của module (supp_key thật, sanitizer giả,
    executor đồng bộ), `scan` (attempt.json) và sup_complete của lib shell, đúng bố cục ci-out/<job> mà job ghi; recompute chạy không có
    --allow-synthetic."""
    def setUp(self):
        self.S = Synth(self)
        self.SUPP, self.BD, self.CF = self.S.SUPP, self.S.BD, self.S.CF
        from harness import rq1 as R1
        self.R1 = R1

    def job_dir(self, mode, status_of):
        SUPP, keys = self.SUPP, self.S.keys
        job = SUPP.JOBS[mode]; out = f'{self.S.d}/ci/{job}'; os.makedirs(out, exist_ok=True)
        cases = [k.split('/')[-1] for k in keys]
        gate_json = f'{self.S.d}/ci/{SUPP.JOBS["smoke"]}/gate/smoke-gate.json'          # job đầy đủ dùng cổng của job smoke
        sel = keys[:1] if mode == 'smoke' else keys[1:]
        if mode == 'smoke':
            os.makedirs(f'{out}/gate'); os.makedirs(f'{out}/build')
            json.dump(dict(ok=True, conditions=dict(s_orig=True, s_pic=True, s_cache=True, s_ninja=True, s_clang=True),
                           per_case={c: {} for c in cases}), open(gate_json, 'w'))
            builds = {c: dict(ok=True, sha256='0' * 64, files=SUPP.tree_hashes(f'{self.S.d}/B/c-san/P01_sphincs_plus/{c}')) for c in cases}
            json.dump(dict(builds=builds), open(f'{out}/build/builds.json', 'w'))
        keysf = f'{self.S.d}/keys.txt'; shutil.copyfile(KEYS, keysf)
        g = dict(ok=True, failed=[], keys=dict(ok=True, keys=keys), amendment=dict(ok=True, commit=COMMIT),
                 env=dict(ok=True, machine=dict(instance_id=IID, instance_type=SUPP.ENV_REQ['instance_type'], ami_id=SUPP.ENV_REQ['ami_id'])))
        cs = dict(ok=True, bin='/nonexistent/driver', sha256='0' * 64, preset='test', secs=0)

        seen = []

        def san(cs_, argv, stdin, timeout, env, c_status=None, sink=None):   # executor đồng bộ: lần gọi thứ i là key thứ i của sel
            k = sel[len(seen)]; seen.append(k)
            self.assertEqual(timeout, self.S.s0[k]['timeout'])
            return fake_san(status_of(k))(cs_, argv, stdin, timeout, env, c_status, sink)

        class Ex:
            def __init__(self, *a, **kw): kw.get('initializer') and kw['initializer']()
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def submit(self, fn, *a):
                from concurrent.futures import Future
                f = Future(); f.set_result(fn(*a)); return f
        mf = lambda o, p: json.dump(dict(machine=dict(instance_id=None), params=p), open(f'{o}/manifest.json', 'w'))
        argv = ['run', '--s0', RQ2_EXE, '--keys', keysf, '--build-root', f'{self.S.d}/B', '--gate-json', gate_json,
                '--out', f'{out}/run', f'--{mode}']
        try:
            with mock.patch.object(SUPP, 'preflight', return_value=g), mock.patch.object(SUPP, 'manifest', side_effect=mf), \
                 mock.patch.object(SUPP, 'ProcessPoolExecutor', Ex), mock.patch.object(self.BD, 'build_c_exe', return_value=cs), \
                 mock.patch.object(self.R1, '_exe_san', side_effect=san), mock.patch.object(self.CF, 'T', f'{self.S.d}/T'), \
                 contextlib.redirect_stdout(io.StringIO()):
                SUPP.main(argv)
                with mock.patch.object(SUPP, 'scan_remote', return_value=[]):
                    SUPP.main(['scan', '--mode', mode, '--out', out, '--declared-attempt', '1'])
        finally:
            self.BD.SAN_FLAGS_EXE = self.CF.SAN_FLAGS_EXE
        p = subprocess.run(['bash', '-c', f'source "{LIB_SH}"; sup_complete "{out}" {mode} {job} 1'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return out

    def test_real_layout_not_synthetic(self):
        st = mix(n_ub=4, n_inc=2)(self.S.keys)
        sm, fu = self.job_dir('smoke', st), self.job_dir('full', st)
        self.assertEqual(sorted(os.listdir(sm)), ['attempt.json', 'build', 'complete.json', 'gate', 'run'])
        recs = [json.loads(l) for d in (sm, fu) for l in open(f'{d}/run/{self.SUPP.OUT_NAME}')]
        self.assertEqual(len(recs), 36); self.assertFalse(any('synthetic' in r for r in recs))
        rc, d, o = self.S.recompute_ci(sm, fu, out='supp-exe-real-layout.json', synthetic=False)
        self.assertEqual(rc, 0, d['failed']); self.assertFalse(d['synthetic']); self.assertFalse(d['stopped'])
        self.assertEqual((d['supp36']['k'], d['supp36']['k_NA']), (6, 6))
        self.assertEqual(d['provenance']['ci']['attempts'], dict(smoke=1, full=1))


if __name__ == '__main__':
    unittest.main()
