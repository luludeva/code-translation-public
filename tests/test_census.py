"""harness.census (Q8 (a), Le chọn 25/10): verdict phải khớp census_lib.py trên lần cũ.

Phát lại mọi bản ghi census library đã lưu (lần gốc m7i `census-lib.jsonl` + `reports.tar.gz`, lần c7i `census-lib-c7i.jsonl` +
`census-lib-c7i-reports.tar.gz`) qua hai đường, cùng một lớp quan sát giả lập dựng từ dữ liệu đã lưu:
  - code cũ: `census_lib.one` nguyên văn (import từ exp 06), `sh` thay bằng hàm giả: cargo tạo hoặc không tạo .so theo bản ghi, runner
    ghi report đã lưu ra đường dẫn `-o`;
  - code mới: `harness.census.census_pair`, `build.build_rust_lib`, `build.lib_root`, `observe.run_lib` thay bằng hàm giả cùng nguồn.
So mọi trường của bản ghi trừ trường thời gian, giữa cũ, mới và bản ghi đã lưu. Kiểm lại hao hụt (`recheck-loss.jsonl`,
`recheck-loss-c7i.jsonl`) phát lại tương tự qua `recheck_loss.recheck` và `census.recheck_pair`; đích kiểm lại so qua
`recheck_loss.targets`, `census_lib_c7i.targets` và `census.recheck_targets`; phía C so `census_lib.tally` với `census.tally`.

Giới hạn của phép phát lại: report đã lưu là report cuối; với 10 cặp chạy lại 120 giây (mỗi lần 5 cặp), report lần 10 giây không được
lưu nên lần 10 giây dùng lại report cuối (mọi report cuối của 10 cặp này đều có vector không Pass, nên điều kiện chạy lại vẫn được kiểm).
Quan sát build (cargo đỗ hay trượt, có .so đúng tên hay không) suy từ bản ghi, nên phần build chỉ kiểm việc ánh xạ, không kiểm cargo."""
import collections, contextlib, importlib, json, os, shutil, sys, tarfile, tempfile, unittest
from unittest import mock

from harness import build as BD
from harness import census as CE
from harness import observe as OB

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
R = f'{REPO}/experiments/06-library-census/results'


def lib_of(rec, log=None):
    """Tên library của case: lấy từ log 'no lib<library>.so; found: ...' khi có (vd cJSON_lib dùng cJSON), ngược lại tên case
    (chỉ xuất hiện trong log build, không ảnh hưởng verdict)."""
    log = log if log is not None else (rec.get('build_log_tail') or '')
    return log[6:log.index('.so; found: ')] if log.startswith('no lib') else rec['tractor_case']
TIME = {'build_secs', 'run_secs', 'secs', 'runner_rc', 'runner_log_tail', 'run_error', 'orphans_after', 'key', 'c_secs'}
RUNS = (('census-lib.jsonl', 'reports.tar.gz', 'recheck-loss.jsonl'),
        ('census-lib-c7i.jsonl', 'census-lib-c7i-reports.tar.gz', 'recheck-loss-c7i.jsonl'))


def _old_modules():
    """Import census_lib, recheck_loss, census_lib_c7i (cần biến môi trường B, OUT lúc import)."""
    d = f'{REPO}/experiments/06-library-census/scripts'
    old = {k: os.environ.get(k) for k in ('B', 'OUT')}
    os.environ.setdefault('B', tempfile.gettempdir()); os.environ.setdefault('OUT', tempfile.gettempdir())
    sys.path.insert(0, d)
    try:
        return [importlib.import_module(m) for m in ('census_lib', 'recheck_loss', 'census_lib_c7i')]
    finally:
        sys.path.remove(d)
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


CL, RL, C7 = _old_modules()


def load(f): return [json.loads(l) for l in open(f'{R}/{f}')]
def strip(x): return {k: v for k, v in x.items() if k not in TIME} if isinstance(x, dict) else x


def reports(tgz):
    """{(system, bundle, case): report} và {(bundle, case): report C}; bỏ report kiểm lại (*.repK.json)."""
    rust, c = {}, {}
    with tarfile.open(f'{R}/{tgz}') as t:
        for m in t.getmembers():
            if not m.isfile() or not m.name.endswith('.json'): continue
            p = m.name.split('/'); name = p[-1][:-5]
            if '.rep' in name: continue
            d = json.load(t.extractfile(m))
            if p[-3] == 'C': c[(p[-2], name)] = d
            else: rust[(p[-3], p[-2], name)] = d
    return rust, c


class Fake:
    """Một bản ghi đã lưu -> môi trường giả (cây H, T, B tạm) cho cả code cũ và code mới."""

    def __init__(self, d, rec, report):
        self.d, self.rec, self.report = d, rec, report
        self.H, self.T, self.B, self.OUT = (f'{d}/{x}' for x in ('H', 'T', 'B', 'OUT'))
        b, tc, hc, s = rec['bundle'], rec['tractor_case'], rec['harvest_case'], rec['system']
        self.src = f"{self.H}/{s}/{b}/{hc}/{rec['source_dir']}"
        os.makedirs(self.src)
        if rec.get('stage') != 'P0_missing_artifact':
            json.dump(dict(passed=rec['pub_passed'], vectors_failed=rec['pub_vectors_failed'], error=rec['pub_error']),
                      open(f'{self.src}/result.json', 'w'))
            open(f'{self.src}/lib.rs', 'w').write('#![feature(test)]\n' if rec['rustc_bootstrap'] else 'pub fn f() {}\n')
            open(f'{self.src}/Cargo.toml', 'w').write('[package]\nname = "x"\n')
        self.lib = lib_of(rec)
        tv = f'{self.T}/{b}/{tc}/test_vectors'; os.makedirs(tv)
        for v in (report or {}): open(f'{tv}/{v}', 'w').write('{"lib_state_in": {}}')
        self.timeouts = []
        log = rec.get('build_log_tail') or ''
        self.cargo_rc = 0 if rec.get('build_ok') or log.startswith('no lib') else 1
        self.so_names = ([f'lib{self.lib}.so'] if rec.get('build_ok') else
                         [x for x in log.split('found: ', 1)[1].split(',') if x] if log.startswith('no lib') else [])

    # ---- code cũ ----
    def sh(self, cmd, cwd=None, env=None, timeout=None):
        if cmd[0] == 'cargo':
            assert ('RUSTC_BOOTSTRAP' in env) == self.rec['rustc_bootstrap'] or env.get('RUSTC_BOOTSTRAP') is None
            rel = cmd[cmd.index('--target-dir') + 1] + '/release'; os.makedirs(rel, exist_ok=True)
            for n in self.so_names: open(f'{rel}/{n}', 'w').write('so')
            return self.cargo_rc, self.rec.get('build_log_tail') or ''
        assert cmd[0] == 'RUNNER' and '--rust' in cmd
        self.timeouts.append(int(cmd[cmd.index('--timeout') + 1]))
        if self.report is not None: json.dump(self.report, open(cmd[cmd.index('-o') + 1], 'w'))
        return 0, ''

    def old(self):
        info = dict(runner_ok=True, c_so=True, n_vectors=self.rec['n_vectors'], library=self.lib, runner_bin='RUNNER')
        with mock.patch.multiple(CL, H=self.H, T=self.T, B=self.B, OUT=self.OUT, sh=self.sh):
            return CL.one(info, self.rec, self.rec['system'])

    # ---- code mới ----
    def build_rust_lib(self, B, system, bundle, case, hcase, library):
        td = f'{B}/rust-lib/{system}/{bundle}/{case}'; os.makedirs(f'{td}/target/release', exist_ok=True)
        info = dict(system=system, rustc_bootstrap=self.rec['rustc_bootstrap'], secs=0.1, dir=td, source_dir=self.rec['source_dir'])
        if self.cargo_rc: return dict(info, ok=False, log=self.rec.get('build_log_tail') or '')
        if f'lib{library}.so' in self.so_names: return dict(info, ok=True, so=f'{td}/target/release/lib{library}.so')
        if len(self.so_names) == 1: return dict(info, ok=True, so_alias=f'{self.so_names[0]} -> lib{library}.so')
        return dict(info, ok=False, log='so: ' + ','.join(self.so_names))

    def run_lib(self, runner_bin, root, vec_path, timeout, rust, dump_path, keep_files=False, dump=True, mem_limit=None, **kw):
        assert keep_files and dump is False and mem_limit == 0 and rust
        self.timeouts.append(timeout)
        e = self.report[os.path.basename(vec_path)]
        json.dump({vec_path: e}, open(dump_path + '.report.json', 'w'))
        return dict(k1='reported', result=e['result'], rc=0)

    @contextlib.contextmanager
    def new_env(self):
        with mock.patch.object(BD, 'H', self.H), mock.patch.object(CE, 'T', self.T), \
                mock.patch.object(BD, 'build_rust_lib', self.build_rust_lib), \
                mock.patch.object(BD, 'lib_root', lambda B, info, kind, rust_dir=None, tag=None: f'{B}/roots/{tag}'), \
                mock.patch.object(OB, 'run_lib', self.run_lib), mock.patch.object(CE, 'orphans', lambda d, kill=True: []):
            yield

    def new(self):
        case = dict(n_vectors=self.rec['n_vectors'], runner_ok=True, c_so=True, library=self.lib, runner_bin='RUNNER')
        with self.new_env():
            return CE.census_pair(self.B, self.OUT, case, {}, self.rec, self.rec['system'])


class CensusVerdictReplay(unittest.TestCase):
    n_compared = collections.Counter()

    def test_census_old_new_saved_agree(self):
        for cf, tgz, _ in RUNS:
            rust, _c = reports(tgz)
            recs = load(cf); per_src = collections.Counter()
            for rec in recs:
                k = (rec['system'], rec['bundle'], rec['tractor_case'])
                rep = rust.get(k)
                self.assertEqual(rep is not None, bool(rec.get('run_ok')), k)    # mỗi cặp đã chạy có đúng một report cuối
                with self.subTest(run=cf, pair=k):
                    d = tempfile.mkdtemp(prefix='census-replay-')
                    try:
                        fo = Fake(f'{d}/old', rec, rep); old = fo.old()
                        fn = Fake(f'{d}/new', rec, rep); new = fn.new()
                    finally:
                        shutil.rmtree(d, ignore_errors=True)
                    self.assertEqual(strip(old), strip(rec), 'census_lib.one không tái lập bản ghi đã lưu')
                    new_v = {k2: v for k2, v in strip(new).items() if k2 != 'so_alias_found'}
                    self.assertEqual(new_v, strip(old))
                    if rep: self.assertEqual(sorted(set(fo.timeouts)), sorted(set(fn.timeouts)))   # 0 vector: bản mới không gọi runner
                    per_src[rec.get('stage') or ('run' if rec.get('run_ok') else 'build_fail')] += 1
            self.n_compared[cf] = len(recs)
            print(f'\n[census replay] {cf}: {sum(per_src.values())}/{len(recs)} bản ghi khớp (cũ = mới = đã lưu); {dict(per_src)}',
                  file=sys.stderr)
        self.assertEqual(sum(self.n_compared.values()), 2 * 2290)

    def test_c_side_tally(self):
        for cs, tgz in (('census-lib-c-side.json', 'reports.tar.gz'), ('census-lib-c-side-c7i.json', 'census-lib-c7i-reports.tar.gz')):
            saved = json.load(open(f'{R}/{cs}')); _r, c = reports(tgz); n = 0
            for key, info in saved.items():
                b, tc = key.split('/'); rep = c.get((b, tc))
                if rep is None:
                    self.assertIsNone(info.get('c_results')); continue
                with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f: json.dump(rep, f)
                try: old = CL.tally(f.name)
                finally: os.remove(f.name)
                self.assertEqual(old, CE.tally(rep)); self.assertEqual(CE.tally(rep)[0], info['c_results']); n += 1
            print(f'\n[census replay] {cs}: {n} case phía C khớp', file=sys.stderr)
            self.assertGreaterEqual(n, 228)

    def test_recheck_targets(self):
        census = load('census-lib.jsonl')
        key = lambda r: (r['bundle'], r['tractor_case'], r['system'])
        self.assertEqual([key(r) for r in RL.targets()], [key(r) for r in CE.recheck_targets(census)])
        with mock.patch.object(C7, 'NEW', f'{R}/census-lib-c7i.jsonl'):
            self.assertEqual([key(r) for r in C7.targets()], [key(r) for r in CE.recheck_targets(load('census-lib-c7i.jsonl'))])
        for cf, _, rf in RUNS:
            self.assertEqual({key(r) for r in CE.recheck_targets(load(cf))}, {key(r) for r in load(rf)})


class RecheckReplay(unittest.TestCase):
    def test_recheck_old_new_saved_agree(self):
        n = 0
        for cf, _, rf in RUNS:
            census = {(r['bundle'], r['tractor_case'], r['system']): r for r in load(cf)}
            for rr in load(rf):
                k = (rr['bundle'], rr['tractor_case'], rr['system']); r = census[k]
                with self.subTest(run=rf, pair=k):
                    old, new = self._both(r, rr)
                    self.assertEqual(self._v(old), self._v(rr), 'recheck_loss.recheck không tái lập bản ghi đã lưu')
                    self.assertEqual(self._v(new), self._v(old))
                    n += 1
        print(f'\n[census replay] kiểm lại: {n} bản ghi khớp (cũ = mới = đã lưu)', file=sys.stderr)
        self.assertEqual(n, 44)

    @staticmethod
    def _v(x):
        """Trường verdict của bản ghi kiểm lại."""
        return dict(build_ok=x.get('build_ok'), so_alias=x.get('so_alias'), stable=x.get('stable'), ours_passed=x.get('ours_passed'),
                    reps=[(y.get('results'), y.get('diffs')) for y in x.get('reps', [])], log=(x.get('build_log_tail') or '')[-200:],
                    census_results=x.get('census_results'), census_build=x.get('census_build'), c_results=x.get('c_results'))

    def _both(self, r, rr):
        reps = [dict(y.get('results') and {v: dict(result=res, diff=(y.get('diffs') or {}).get(v, ''))
                                           for v, res in y['results'].items()} or {}) if 'results' in y else None
                for y in rr.get('reps', [])]
        alias = (rr.get('so_alias') or '').split(' -> ')[0]
        log = rr.get('build_log_tail') or ''
        cargo_rc = 0 if rr.get('build_ok') or log.startswith('so: ') else 1
        so_names = [alias] if alias else [f"lib{lib_of(r, rr.get('census_build') or '')}.so"] if rr.get('build_ok') else \
            [x for x in log[4:].split(',') if x] if log.startswith('so: ') else []
        d = tempfile.mkdtemp(prefix='recheck-replay-')
        try:
            H, T = f'{d}/H', f'{d}/T'
            src = f"{H}/{r['system']}/{r['bundle']}/{r['harvest_case']}/{r['source_dir']}"; os.makedirs(src)
            open(f'{src}/lib.rs', 'w').write('pub fn f() {}\n')
            tv = f"{T}/{r['bundle']}/{r['tractor_case']}/test_vectors"; os.makedirs(tv)
            names = sorted({v for x in reps if x for v in x}) or [f'{i}.json' for i in range(1, r['n_vectors'] + 1)]
            for v in names: open(f'{tv}/{v}', 'w').write('{}')
            it = iter(reps)

            def sh(cmd, cwd=None, env=None, timeout=None):
                if cmd[0] == 'cargo':
                    rel = cmd[cmd.index('--target-dir') + 1] + '/release'; os.makedirs(rel, exist_ok=True)
                    for x in so_names: open(f'{rel}/{x}', 'w').write('so')
                    return cargo_rc, log
                assert int(cmd[cmd.index('--timeout') + 1]) == RL.TO
                rep = next(it)
                if rep is not None: json.dump(rep, open(cmd[cmd.index('-o') + 1], 'w'))
                return 0, ''

            lib = lib_of(r, rr.get('census_build') or '')
            info = dict(runner_ok=True, c_so=True, library=lib, runner_bin='RUNNER', c_results=rr.get('c_results'))
            with mock.patch.multiple(RL, H=H, T=T, B=f'{d}/oB', OUT=f'{d}/oOUT'), mock.patch.object(CL, 'sh', sh):
                old = RL.recheck(info, r); old['c_results'] = info['c_results']

            it2 = iter(reps); calls = collections.Counter()

            def build_rust_lib(B, system, bundle, case, hcase, library):
                td = f'{B}/rust-lib/{system}/{bundle}/{case}'
                base = dict(rustc_bootstrap=False, secs=0.1, dir=td)
                if cargo_rc: return dict(base, ok=False, log=log)
                if f'lib{library}.so' in so_names: return dict(base, ok=True)
                if len(so_names) == 1: return dict(base, ok=True, so_alias=f'{so_names[0]} -> lib{library}.so')
                return dict(base, ok=False, log='so: ' + ','.join(so_names))

            cur = {}

            def run_lib(runner_bin, root, vec_path, timeout, rust, dump_path, keep_files=False, dump=True, mem_limit=None, **kw):
                assert timeout == CE.TO and dump is False and mem_limit == 0
                if not calls['v']: cur['rep'] = next(it2)
                calls['v'] = (calls['v'] + 1) % len(vecs)
                rep = cur['rep']
                if rep is None: calls['v'] = 0; return dict(k1='infra', infra_msg='no report')
                e = rep[os.path.basename(vec_path)]
                json.dump({vec_path: e}, open(dump_path + '.report.json', 'w'))
                return dict(k1='reported', result=e['result'])

            vecs = CE.vector_files(f"{T}/{r['bundle']}/{r['tractor_case']}")
            case = dict(runner_ok=True, c_so=True, library=lib, runner_bin='RUNNER', c_results=rr.get('c_results'))
            with mock.patch.object(CE, 'T', T), mock.patch.object(BD, 'build_rust_lib', build_rust_lib), \
                    mock.patch.object(BD, 'lib_root', lambda B, info, kind, rust_dir=None, tag=None: f'{B}/roots/{tag}'), \
                    mock.patch.object(OB, 'run_lib', run_lib), mock.patch.object(CE, 'orphans', lambda d, kill=True: []):
                new = CE.recheck_pair(f'{d}/nB', f'{d}/nOUT', case, {}, r)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        return old, new


class PureVerdict(unittest.TestCase):
    """Ca biên của hàm thuần (tổng hợp, không có trong dữ liệu cũ)."""

    def test_zero_vectors_pass(self):
        self.assertEqual(CE.run_verdict(True, {}), dict(timeout_used=10, run_ok=True, vectors=0, results={}, ours_passed=True))

    def test_no_report(self):
        self.assertEqual(CE.run_verdict(True, None), dict(timeout_used=10, run_ok=False))

    def test_rejected_not_rerun(self):
        rv = CE.run_verdict(False, {'1.json': dict(result='Timeout')})
        self.assertEqual((rv['timeout_used'], rv['ours_passed']), (10, False))
        with self.assertRaises(ValueError): CE.run_verdict(False, {'1.json': dict(result='Timeout')}, {'1.json': dict(result='Pass')})

    def test_rerun_passes(self):
        rv = CE.run_verdict(True, {'1.json': dict(result='Timeout')}, {'1.json': dict(result='Pass')})
        self.assertEqual((rv['timeout_used'], rv['results'], rv['ours_passed']), (120, {'Pass': 1}, True))

    def test_rerun_no_report_keeps_fast(self):
        # quirk census_lib.py: lần 120 giây không ghi report thì đọc lại report lần 10 giây còn trên đĩa
        rv = CE.run_verdict(True, {'1.json': dict(result='Timeout')}, None)
        self.assertEqual((rv['timeout_used'], rv['results'], rv['run_ok']), (120, {'Timeout': 1}, True))

    def test_new_labels_not_pass(self):
        self.assertFalse(CE.passed({'OutputLimit': 1}))

    def test_recheck_zero_vector_not_pass(self):
        self.assertEqual(CE.recheck_verdict([dict(results={})] * 3), dict(stable=True, ours_passed=False))
        self.assertEqual(CE.recheck_verdict([dict(results={'1': 'Pass'}), dict(results={'1': 'Pass'}), {}]),
                         dict(stable=False, ours_passed=False))


if __name__ == '__main__':
    unittest.main()
