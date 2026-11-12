"""harness.mutants (kế hoạch A3, A7 mục 2.3, 2.6, 3.2, 3.3): vị trí đột biến, toán tử, seed, bỏ vị trí trùng bộ cũ, định dạng danh tính,
kiểm danh tính với exp 08. Không cần corpus; ca build bằng cargo bỏ qua khi máy không có cargo.
Chạy: python3 -m unittest tests.test_mutants"""
import contextlib, inspect, io, json, os, random, shutil, tempfile, unittest
from unittest import mock

from harness import mutants as M
from harness.config import NO_INPUT_LIB, REPO
from harness.gen import mutants_cov_exe as AE
from harness.gen import mutants_lib as ML
from harness.gen import mutants_v1 as MV

SRC_MAIN = '''use std::io;
// a < b chỉ là comment
mod util;
fn add(a: i32, b: i32) -> i32 { a + b }
static T: [u8; 3] = [1, 2, 3];
fn main() {
    let x = 3;
    if x > 2 && x != 7 {
        println!("x < 10");
    }
    let y = x - 1 + 40u32 as i32;
    let c = 'a';
    let z = v[0] == 5;
}
'''
SRC_UTIL = '''pub fn f(n: usize) -> usize {
    if n == 0 { 1 } else { n - 1 }
}
'''


def make_crate(root, nested=False, feature=False):
    os.makedirs(f'{root}/src/sub' if nested else f'{root}/src', exist_ok=True)
    open(f'{root}/src/main.rs', 'w').write(('#![feature(core_intrinsics)]\n' if feature else '') + SRC_MAIN)
    open(f'{root}/src/util.rs', 'w').write(SRC_UTIL)
    if nested: open(f'{root}/src/sub/deep.rs', 'w').write('pub fn g(a: i32) -> bool { a < 3 }\nlet q = a + 9;\n')
    return root


def keyset(sites): return sorted(sites)


class Vendored(unittest.TestCase):
    """Khối chép phải trùng nguyên văn nguồn thí nghiệm (VENDOR-mutants.md)."""
    SRC = {MV: 'experiments/04-coverage-pilot/scripts/mutants_v1.py', ML: 'experiments/07-library-controls/scripts/mutants_lib.py',
           AE: 'experiments/08-harness-v2/scripts/accept_exe.py'}
    FNS = {MV: ('sites_of', 'vec_fails'), ML: ('sites_of', 'vec_fails', 'coverage'), AE: ('covered_lines', 'sites_cov')}

    def test_functions_verbatim(self):
        for mod, path in self.SRC.items():
            orig = open(f'{REPO}/{path}').read()
            for fn in self.FNS[mod]:
                self.assertIn(inspect.getsource(getattr(mod, fn)), orig, f'{mod.__name__}.{fn} khác nguồn {path}')

    def test_constants_verbatim(self):
        for mod in (MV, ML):
            orig = open(f'{REPO}/{self.SRC[mod]}').read()
            src = inspect.getsource(mod)
            for name in ('OPS = ', 'LIT = '):
                line = next(l for l in src.split('\n') if l.startswith(name))
                self.assertIn(line + '\n', orig)
        tools = next(l for l in inspect.getsource(ML).split('\n') if 'TOOLS = subprocess' in l).strip()
        self.assertIn(tools, open(f'{REPO}/{self.SRC[ML]}').read())


class Sites(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp)

    def test_exe_sites_and_filters(self):
        wd = make_crate(f'{self.tmp}/c', nested=True)
        rows = [M.site_row(wd, s) for s in M.ordered_sites('exe', wd, M.all_lines(wd, 'exe'), 1)]
        got = {(r['file'], r['line'], r['op'], r['after']) for r in rows}
        self.assertIn(('src/main.rs', 8, ' > ', 'if x >= 2 && x != 7 {'), got)
        self.assertIn(('src/main.rs', 8, ' && ', 'if x > 2 || x != 7 {'), got)
        self.assertIn(('src/main.rs', 8, ' != ', 'if x > 2 && x == 7 {'), got)
        self.assertIn(('src/main.rs', 8, 'lit+1', 'if x > 3 && x != 7 {'), got)
        self.assertIn(('src/main.rs', 11, 'lit+1', 'let y = x - 1 + 41u32 as i32;'), got)
        self.assertIn(('src/main.rs', 11, ' \\+ ', 'let y = x - 1 - 40u32 as i32;'), got)
        self.assertIn(('src/util.rs', 2, ' == ', 'if n != 0 { 1 } else { n - 1 }'), got)
        lines = {(r['file'], r['line']) for r in rows}
        for ln in (1, 2, 3, 5, 9):          # use, comment, mod, static mảng, dòng có chuỗi
            self.assertNotIn(('src/main.rs', ln), lines)
        self.assertNotIn(('src/main.rs', 12), lines)                     # ký tự '
        self.assertFalse([r for r in rows if r['line'] == 4 and r['op'] == 'lit+1'])   # dòng fn: không đổi hằng
        self.assertIn(('src/main.rs', 4, ' \\+ ', 'fn add(a: i32, b: i32) -> i32 { a - b }'), got)
        self.assertFalse([r for r in rows if r['line'] == 13 and r['op'] == 'lit+1' and '[1]' in r['after']])   # chỉ số mảng
        self.assertFalse([r for r in rows if r['file'].startswith('src/sub/')])   # exe: chỉ src/*.rs

    def test_lib_recursive_and_coverage_filter(self):
        wd = make_crate(f'{self.tmp}/c', nested=True)
        allc = M.all_lines(wd, 'lib')
        rows = [M.site_row(wd, s) for s in M.ordered_sites('lib', wd, allc, 1)]
        self.assertTrue([r for r in rows if r['file'] == 'src/sub/deep.rs'])
        cov = {('src/util.rs', 2)}
        rows = [M.site_row(wd, s) for s in M.ordered_sites('lib', wd, cov, 1)]
        self.assertTrue(rows); self.assertEqual({(r['file'], r['line']) for r in rows}, cov)

    def test_col_is_match_offset(self):
        wd = make_crate(f'{self.tmp}/c')
        for s in M.ordered_sites('exe', wd, M.all_lines(wd, 'exe'), 1):
            r = M.site_row(wd, s); line = open(f'{wd}/{r["file"]}').read().split('\n')[r['line'] - 1]
            self.assertEqual((line[:r['col']] + r['rep'] + line[r['end']:]).strip()[:160], r['after'])
            if r['op'] != 'lit+1': self.assertRegex(line[r['col']:r['end']], r['op'])
            else: self.assertEqual(int(line[r['col']:r['end']]) + 1, int(r['rep']))

    def test_apply_and_restore(self):
        wd = make_crate(f'{self.tmp}/c'); before = open(f'{wd}/src/main.rs').read()
        s = next(x for x in M.ordered_sites('exe', wd, M.all_lines(wd, 'exe'), 1) if x[5] == ' && ')
        r = M.site_row(wd, s)
        path, text = M.apply_site(wd, s)
        self.assertEqual(open(path).read().split('\n')[s[1]].strip(), r['after'])
        self.assertEqual(text, before)
        open(path, 'w').write(text); self.assertEqual(open(path).read(), before)


class Seeds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp)
        self.wd = make_crate(f'{self.tmp}/c', nested=True)

    def test_deterministic_and_seed_dependent(self):
        for kind in ('exe', 'lib'):
            cov = M.all_lines(self.wd, kind)
            a, b = M.ordered_sites(kind, self.wd, cov, 2), M.ordered_sites(kind, self.wd, cov, 2)
            self.assertEqual(a, b)
            self.assertNotEqual(a, M.ordered_sites(kind, self.wd, cov, 1))
            self.assertEqual(sorted(a), sorted(M.ordered_sites(kind, self.wd, cov, 1)))

    def test_module_seed_restored(self):
        MV.SEED, ML.SEED, AE.MUT_SEED = 0, 0, 1
        M.ordered_sites('exe', self.wd, M.all_lines(self.wd, 'exe'), 7); M.ordered_sites('lib', self.wd, M.all_lines(self.wd, 'lib'), 7)
        self.assertEqual((MV.SEED, ML.SEED, AE.MUT_SEED), (0, 0, 1))

    def test_exe_shuffle_then_filter_lib_filter_then_shuffle(self):
        """Thứ tự exp 08: exe xáo mọi vị trí rồi lọc coverage; lib lọc rồi xáo. Hai cách cho thứ tự khác nhau trên cùng tập lọc."""
        allc = M.all_lines(self.wd, 'exe'); cov = {k for k in allc if k[1] % 2 == 0}
        full = M.ordered_sites('exe', self.wd, allc, 1)
        self.assertEqual(M.ordered_sites('exe', self.wd, cov, 1), [s for s in full if (s[0], s[1] + 1) in cov])
        lib = M.ordered_sites('lib', self.wd, cov, 1)
        perm = M._lib_perm(len(lib), 1)
        with mock.patch.object(random.Random, 'shuffle', lambda self, x: None):     # thứ tự duyệt trước khi xáo
            src_order = M.ordered_sites('lib', self.wd, cov, 1)
        self.assertEqual(lib, [src_order[perm[j]] for j in range(len(lib))])
        self.assertNotEqual(lib, [s for s in M.ordered_sites('lib', self.wd, allc, 1) if (s[0], s[1] + 1) in cov])


class Prior(unittest.TestCase):
    def test_prior_keys_loaded(self):
        k08 = M.prior_keys('exe', ('seed1',))
        d = json.load(open(M.EXP08['exe']))
        m0 = d['pairs'][0]['mutants'][0]
        self.assertIn(M.site_key(d['pairs'][0]['system'], d['pairs'][0]['case'], m0), k08)
        n08 = sum(len(p['mutants']) for p in d['pairs'])
        self.assertLessEqual(len(k08), n08); self.assertGreater(len(k08), 0)
        k0 = M.prior_keys('exe', ('seed0',)); self.assertTrue(k0)
        self.assertTrue({k[0] for k in k0} <= set(M.TUNING_SYSTEMS))
        self.assertTrue(M.prior_keys('lib', ('seed0',))); self.assertEqual(M.prior_keys('lib', ()), set())

    def test_drop_prior(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        wd = make_crate(f'{tmp}/c')
        rows = [M.site_row(wd, s) for s in M.ordered_sites('exe', wd, M.all_lines(wd, 'exe'), 2)]
        old = {M.site_key('sysA', 'case1', r) for r in rows[:3]}          # bộ cũ chứa 3 vị trí đầu
        keep, n = M.drop_prior('sysA', 'case1', rows, old)
        self.assertEqual(n, 3); self.assertEqual(keep, rows[3:])
        keep, n = M.drop_prior('sysB', 'case1', rows, old)                  # hệ khác: nguồn khác, không trùng
        self.assertEqual(n, 0)

    def test_gen_pair_dry_run_excludes_prior(self):
        """gen --dry-run --no-coverage trên crate tổng hợp: bỏ đúng vị trí của bộ cũ, giữ thứ tự, không build."""
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        src = make_crate(f'{tmp}/harvest/sysA/B/case1/translated'); open(f'{src}/Cargo.toml', 'w').write('[package]\nname="x"\n')
        p = dict(system='sysA', bundle='B', case='case1', hcase='case1')
        base = dict(name='a3-seed2', kind='exe', seed=2, n=12, B=f'{tmp}/b', Bm=f'{tmp}/b/mutants', T=f'{tmp}/t', H=f'{tmp}/harvest',
                    dry_run=True, no_coverage=True)
        with mock.patch.object(M.BD, 'rust_src', lambda s, b, h: f'{tmp}/harvest/{s}/{b}/{h}/translated'):
            r0 = M.gen_pair(dict(base, keys=set()), p)
            old = {M.site_key('sysA', 'case1', s) for s in r0['sites'][::2]}
            r1 = M.gen_pair(dict(base, keys=old), p)
        self.assertEqual(r1['n_sites_excluded_prior'], len(r0['sites'][::2]))
        self.assertEqual(r1['sites'], r0['sites'][1::2])
        self.assertFalse(os.path.exists(f'{tmp}/b/mutants/a3-seed2/exe/sysA/B/case1/target'))


class Pairs(unittest.TestCase):
    def test_a3_pairs(self):
        for kind in ('exe', 'lib'):
            ps = M.set_pairs('a3-seed2', kind)
            self.assertTrue(ps)
            self.assertFalse({p['system'] for p in ps} & set(M.TUNING_SYSTEMS))
            self.assertFalse({p['case'] for p in ps} & NO_INPUT_LIB)
            self.assertEqual(len({(p['bundle'], p['case'], p['system']) for p in ps}), len(ps))
            sub = M.set_pairs('a3-seed2', kind, ['codex-gpt54'])
            self.assertTrue(sub); self.assertEqual({p['system'] for p in sub}, {'codex-gpt54'})

    def test_a7_pairs_as_exp08(self):
        for kind, n in (('exe', 9), ('lib', 23)):
            ps = M.set_pairs('a7-seed1', kind)
            self.assertEqual(len(ps), n)
            self.assertEqual({p['system'] for p in ps}, set(M.TUNING_SYSTEMS))
        self.assertIn(dict(system='kiro', bundle='B02_synthetic', case='static_vars_fpts', hcase='static-vars-fpts'),
                      M.set_pairs('a7-seed1', 'exe'))

    def test_sets(self):
        self.assertEqual(M.SETS['a7-seed1'], dict(seed=1, n=12, pairs='exp08', exclude=()))
        self.assertEqual(M.SETS['a3-seed2']['seed'], 2); self.assertEqual(M.SETS['a3-seed2']['n'], 12)
        self.assertEqual(set(M.SETS['a3-seed2']['exclude']), {'seed0', 'seed1'})

    def test_cli_pairs(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): M.main(['pairs', '--set', 'a3-seed2', '--kind', 'exe'])
        d = json.loads(buf.getvalue()); self.assertEqual(d['seed'], 2); self.assertEqual(d['n_pairs'], len(d['pairs']))


class Identity(unittest.TestCase):
    def rec(self):
        return dict(key='a3-seed2/exe/B/c/sysA', set='a3-seed2', kind='exe', system='sysA', bundle='B', case='c',
                    mutants=[dict(id=0, file='src/main.rs', line=3, col=5, end=8, op=' < ', rep=' <= ', before='a < b', after='a <= b',
                                  built=True, sha256='ab' * 32, killed_by_vectors=False),
                             dict(id=1, file='src/main.rs', line=4, col=2, end=3, op='lit+1', rep='2', before='1', after='2', built=False)])

    def test_identity_format(self):
        rows = M.identity_rows([self.rec()])
        self.assertEqual(len(rows), 2)
        for r in rows: self.assertEqual(set(r), set(M.IDENTITY_FIELDS) | {'key'})
        self.assertEqual(rows[0]['sha256'], 'ab' * 32); self.assertIsNone(rows[1]['sha256'])
        self.assertEqual(rows[1]['key'], 'a3-seed2/exe/B/c/sysA/m1')
        self.assertEqual([r['id'] for r in rows], [0, 1])

    def _exp08(self, tmp, pairs):
        f = f'{tmp}/accept.json'; json.dump(dict(pairs=pairs), open(f, 'w')); return f

    def test_check_identity(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        r = self.rec(); r['case'] = 'c'
        e = [dict(system='sysA', case='c', mutants=[{k: m[k] for k in M.ID5 + ('built',)} for m in r['mutants']])]
        with mock.patch.dict(M.EXP08, exe=self._exp08(tmp, e)):
            self.assertEqual(M.check_identity('exe', [r])[0]['status'], 'identical')
            r2 = json.loads(json.dumps(r)); r2['mutants'][1]['built'] = True
            self.assertEqual(M.check_identity('exe', [r2])[0]['status'], 'mismatch')
            self.assertEqual(M.check_identity('exe', [])[0]['status'], 'missing')

    def test_check_sites_offline(self):
        """Tái tạo kiểu exp 08 trên crate tổng hợp với coverage giả; danh sách vị trí không coverage phải 'consistent' (exe, lib),
        sai seed thì 'inconsistent'."""
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        wd = make_crate(f'{tmp}/c', nested=True)
        for kind in ('exe', 'lib'):
            allc = M.all_lines(wd, kind); cov = {k for k in allc if k[1] in (4, 8, 11, 13, 2)}
            chosen = [M.site_row(wd, s) for s in M.ordered_sites(kind, wd, cov, 1)]
            e = [dict(system='sysA', case='c', n_sites=len(chosen), mutants=[{k: m[k] for k in M.ID5} for m in chosen[:4]])]
            for seed, want in ((1, 'consistent'), (0, 'inconsistent')):
                sites = M.ordered_sites(kind, wd, allc, seed)
                perm = M._lib_perm(len(sites), seed)
                rows = [dict(M.site_row(wd, s), **({'src_idx': perm[j]} if kind == 'lib' else {})) for j, s in enumerate(sites)]
                with mock.patch.dict(M.EXP08, {kind: self._exp08(tmp, e)}):
                    got = M.check_sites(kind, [dict(system='sysA', case='c', coverage='none', sites=rows)], seed)[0]
                self.assertEqual(got['status'], want, (kind, seed, got))
            with mock.patch.dict(M.EXP08, {kind: self._exp08(tmp, e)}):      # có coverage: phải bằng đầu danh sách
                rows = [M.site_row(wd, s) for s in M.ordered_sites(kind, wd, cov, 1)]
                self.assertEqual(M.check_sites(kind, [dict(system='sysA', case='c', coverage='lcov', sites=rows)])[0]['status'], 'identical')


@unittest.skipUnless(shutil.which('cargo'), 'cần cargo')
class BuildMutant(unittest.TestCase):
    def test_build_sha_and_no_stale_artifact(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        src = f'{tmp}/src'; os.makedirs(f'{src}/src')
        open(f'{src}/Cargo.toml', 'w').write('[package]\nname = "driver"\nversion = "0.1.0"\nedition = "2021"\n')
        open(f'{src}/src/main.rs', 'w').write('fn main() {\n    let x = 1 + 2;\n    println!("{}", x);\n}\n')
        pdir = f'{tmp}/p'
        b0 = M.build_mutant('exe', f'{tmp}/B', src, pdir, 0)
        self.assertTrue(b0['built'], b0); self.assertFalse(b0['rustc_bootstrap'])
        self.assertEqual(len(b0['sha256']), 64); self.assertTrue(os.path.exists(f'{pdir}/m0/driver'))
        open(f'{src}/src/main.rs', 'w').write('fn main() {\n    let x = 1 + ;\n}\n')       # mutant không build được
        b1 = M.build_mutant('exe', f'{tmp}/B', src, pdir, 1)
        self.assertFalse(b1['built']); self.assertNotIn('sha256', b1)
        self.assertFalse(os.path.exists(f'{pdir}/m1'))
        self.assertFalse(os.path.exists(f'{pdir}/target/release/driver'))   # không còn binary của mutant trước

    def test_gen_pair_exe_loop(self):
        """Vòng sinh (không dry-run) với build thật, coverage và vector giả: dừng khi đủ n mutant build được, id đánh theo thứ tự thử
        (gồm mutant hỏng build), file nguồn được khôi phục, mỗi mutant build được có sha256 và thư mục riêng."""
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        src = f'{tmp}/harvest/sysA/B/case1/translated'; os.makedirs(f'{src}/src')
        open(f'{src}/Cargo.toml', 'w').write('[package]\nname = "driver"\nversion = "0.1.0"\nedition = "2021"\n')
        body = ('fn main() {\n    let v: [i32; 2] = [4, 5];\n    let a = v[0] + v[1];\n    let b = a * 2 - 7;\n    let c = b == 9 && a < 8;\n'
                '    if c { println!("{}", a - 1); }\n}\n')
        open(f'{src}/src/main.rs', 'w').write(body)
        p = dict(system='sysA', bundle='B', case='case1', hcase='case1')
        ctx = dict(name='a3-seed2', kind='exe', seed=2, n=3, keys=set(), B=f'{tmp}/b', Bm=f'{tmp}/b/mutants', T=f'{tmp}/t',
                   H=f'{tmp}/harvest', dry_run=False, no_coverage=False)
        cov = {('src/main.rs', i) for i in range(1, 8)}
        calls = []

        def vec(binp, troot, out):
            calls.append(binp); return ['1.json'] if len(calls) % 2 == 0 else []
        with mock.patch.object(M.BD, 'rust_src', lambda s, b, h: src), \
                mock.patch.object(M.BD, 'build_rust_exe', lambda *a: dict(ok=True, bin='/bin/true', sha256='0' * 64)), \
                mock.patch.object(M.MV, 'vec_fails', vec), mock.patch.object(M.AE, 'covered_lines', lambda *a: (cov, '')), \
                mock.patch.object(M, 'load_vectors', lambda t: []):
            r = M.gen_pair(ctx, p)
        built = [m for m in r['mutants'] if m['built']]
        self.assertEqual(len(built), 3, r)
        self.assertEqual([m['id'] for m in r['mutants']], list(range(len(r['mutants']))))
        self.assertEqual(r['base_vector_fails'], [])
        order = [M.site_row(f'{tmp}/b/mutants/a3-seed2/exe/sysA/B/case1/src', s)
                 for s in M.ordered_sites('exe', f'{tmp}/b/mutants/a3-seed2/exe/sysA/B/case1/src', cov, 2)]
        self.assertEqual([(m['file'], m['line'], m['col'], m['op']) for m in r['mutants']],
                         [(o['file'], o['line'], o['col'], o['op']) for o in order[:len(r['mutants'])]])
        self.assertEqual(open(f'{tmp}/b/mutants/a3-seed2/exe/sysA/B/case1/src/src/main.rs').read(), body)
        for m in built:
            self.assertEqual(len(m['sha256']), 64); self.assertTrue(os.path.exists(m['artifact']))
            self.assertIn(m['killed_by_vectors'], (True, False))
        self.assertEqual(len({m['artifact'] for m in built}), 3)
        rows = M.identity_rows([r]); self.assertEqual(len(rows), len(r['mutants']))


if __name__ == '__main__':
    unittest.main()
