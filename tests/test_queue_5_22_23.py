"""Ba việc theo hàng đợi master plan (Le chọn 26/10). Không cần corpus.
  dòng 5 (F3): case executable không đọc input ghi thêm ký hiệu đọc input mà binary Rust của từng bản dịch nhập; metrics báo số kèm mẫu số.
  dòng 22 (F7): R22 thu hẹp, số divergence mà C-san báo UB trên số divergence (và trên divergence ổn định), theo cặp và theo nhóm.
  dòng 23 (F6, F7): mã luật B/N/U giữ ở cấp bản dịch và đếm theo mã luật trong summary.
Chạy: python3 -m unittest tests.test_queue_5_22_23"""
import os, shutil, subprocess, tempfile, unittest
from unittest import mock

from harness import insensitive as II
from harness import metrics as M
from harness import rq1
from harness.config import INSENSITIVE_SEED
from harness.record import blob


def case(seed, statuses, bundle='B01_x', name='c', **kw):
    return dict(bundle=bundle, case=name, seed=seed, status='done', pair_status=statuses,
                gen=dict(n_by_layer={'M': 1, 'MS': 1, 'A': 1}), **kw)


def div(system, seed, idx, stable=True, san='no_report', out=(b'1\n', b'2\n'), bundle='B01_x', name='c', c_rc=0, r_rc=0):
    return dict(kind='exe', bundle=bundle, case=name, system=system, seed=seed, idx=idx, stable=stable, san=san, c_ub=san == 'ub',
                retained=stable and san == 'no_report', c_flag=False, channels=['stdout'], c_rc=c_rc, r_rc=r_rc, c_to=False,
                r_to=False, c_out=blob(out[0]), r_out=blob(out[1]), c_err=blob(b''), r_err=blob(b''))


def build(cases, divs, seeds=(0, 1, 2)):
    D = {}
    for d in divs: D.setdefault((d['bundle'], d['case'], d['system'], d['seed']), []).append(d)
    return M.rq1_translations(cases, D, {}, list(seeds))


# ---------------- dòng 5 ----------------
class RustInputSymsRecord(unittest.TestCase):
    def run_case(self, seed, rust_syms):
        ok = dict(ok=True, bin='/c', sha256='h', preset=None)
        rb = lambda B, s, b, c, h: dict(ok=s != 'z', bin=f'/r/{s}', sha256=s)
        with mock.patch.object(rq1.BD, 'build_c_exe', return_value=ok), \
             mock.patch.object(rq1.BD, 'build_rust_exe', side_effect=rb), \
             mock.patch.object(rq1.insensitive, 'check', return_value=(True, {})), \
             mock.patch.object(rq1.insensitive, 'dyn_syms', side_effect=lambda b: rust_syms[b]), \
             mock.patch.object(rq1.insensitive, 'rust_baseline', return_value=dict(syms=[], rustc='t')), \
             mock.patch.object(rq1, 'gen_exe', side_effect=AssertionError('chỉ kiểm phần ghi trước khi sinh input')):
            pairs = [dict(system=s, harvest_case='c') for s in ('a', 'b', 'z')]
            return rq1.rq1_exe_case('/b', 'P01_x', 'c', pairs, seed, {}, 10, '/nonexistent', 't')

    def test_recorded_per_system(self):
        syms = {'/r/a': {'read', 'puts', 'getenv'}, '/r/b': None}
        r = self.run_case(INSENSITIVE_SEED + 1, syms)          # dừng trước khi sinh input, bản ghi đã có trường
        self.assertEqual(r['status'], 'insensitive_other_seed')
        self.assertEqual(r['rust_input_syms'], {'a': ['getenv', 'read'], 'b': None})   # z build lỗi: không có khoá

    def test_input_layers_unchanged(self):
        """Không đổi tầng input: gen_exe vẫn nhận insensitive=True như trước."""
        seen = {}
        def gen(*a, **k): seen.update(k); raise StopIteration
        ok = dict(ok=True, bin='/c', sha256='h', preset=None)
        with mock.patch.object(rq1.BD, 'build_c_exe', return_value=ok), \
             mock.patch.object(rq1.BD, 'build_rust_exe', return_value=dict(ok=True, bin='/r/a', sha256='r')), \
             mock.patch.object(rq1.insensitive, 'check', return_value=(True, {})), \
             mock.patch.object(rq1.insensitive, 'dyn_syms', return_value={'read'}), \
             mock.patch.object(rq1, 'gen_exe', side_effect=gen), self.assertRaises(StopIteration):
            rq1.rq1_exe_case('/b', 'P01_x', 'c', [dict(system='a', harvest_case='c')], INSENSITIVE_SEED, {}, 10, '/nonexistent', 't')
        self.assertEqual(seen, dict(insensitive=True))

    def test_not_recorded_when_sensitive(self):
        ok = dict(ok=True, bin='/c', sha256='h', preset=None)
        with mock.patch.object(rq1.BD, 'build_c_exe', return_value=ok), \
             mock.patch.object(rq1.BD, 'build_rust_exe', return_value=dict(ok=True, bin='/r/a', sha256='r')), \
             mock.patch.object(rq1.insensitive, 'check', return_value=(False, {})), \
             mock.patch.object(rq1.insensitive, 'dyn_syms', side_effect=AssertionError('không kiểm khi case đọc input')), \
             mock.patch.object(rq1, 'gen_exe', side_effect=StopIteration), self.assertRaises(StopIteration):
            rq1.rq1_exe_case('/b', 'P01_x', 'c', [dict(system='a', harvest_case='c')], 0, {}, 10, '/nonexistent', 't')

    @unittest.skipUnless(shutil.which('gcc') and shutil.which('nm'), 'cần gcc và nm')
    def test_input_syms_real_binary(self):
        d = tempfile.mkdtemp(prefix='q5-')
        with open(f'{d}/m.c', 'w') as f:
            f.write('#include <stdio.h>\nint main(void){char s[8]; if (fgets(s,8,stdin)) puts(s); return 0;}\n')
        subprocess.run(['gcc', f'{d}/m.c', '-o', f'{d}/dyn'], check=True, capture_output=True)
        self.assertIn('fgets', II.input_syms(f'{d}/dyn'))
        if subprocess.run(['gcc', '-static', f'{d}/m.c', '-o', f'{d}/st'], capture_output=True).returncode == 0:
            self.assertIsNone(II.input_syms(f'{d}/st'))       # binary tĩnh: không kiểm được


    @unittest.skipUnless(shutil.which('rustc') and shutil.which('nm'), 'cần rustc và nm')
    def test_rust_baseline_subtracted(self):
        """Le chọn 26/10 (dòng 5): trừ tập nền của runtime Rust. Std nhập sẵn read, getenv... nên binary Rust không đọc input ra rỗng;
        giới hạn: đọc stdin qua std cũng chỉ dùng read nên không phát hiện được (số là cận dưới); gọi libc qua FFI thì phát hiện."""
        II._RUST_BASE.clear()
        base = II.rust_baseline()
        self.assertTrue(base['syms']); self.assertIn('read', base['syms']); self.assertTrue(base['rustc'])
        d = tempfile.mkdtemp(prefix='q5r-')
        progs = dict(h='fn main() { println!("x"); }\n',
                     s='fn main() { let mut l = String::new(); std::io::stdin().read_line(&mut l).unwrap(); print!("{}", l); }\n',
                     f='extern "C" { fn getchar() -> i32; }\nfn main() { let c = unsafe { getchar() }; println!("{}", c); }\n')
        out = {}
        for k, src in progs.items():
            with open(f'{d}/{k}.rs', 'w') as fh: fh.write(src)
            subprocess.run(['rustc', '-O', f'{d}/{k}.rs', '-o', f'{d}/{k}'], check=True, capture_output=True)
            out[k] = II.input_syms(f'{d}/{k}')
        self.assertEqual(out['h'], []); self.assertEqual(out['s'], [])      # cận dưới: đọc stdin qua std không thấy
        self.assertIn('getchar', out['f'])


class RustInputSymsMetrics(unittest.TestCase):
    def test_counts_with_denominator(self):
        rs = {'a': ['getenv', 'read'], 'b': [], 'c': None}      # d: không có khoá (bản ghi thiếu)
        cs = [case(INSENSITIVE_SEED, {s: 'P_test' for s in 'abcd'}, bundle='P01_x', input_insensitive=True, rust_input_syms=rs),
              case(0, {'a': 'P_test'}, bundle='P01_y')]       # case đọc input: ngoài mẫu số
        T = build(cs, [])
        self.assertEqual(T[('P01_x', 'c', 'a')]['rust_input_syms'], ['getenv', 'read'])
        self.assertNotIn('rust_input_syms', T[('P01_y', 'c', 'a')])
        S = M.summarize_rq1(T, 'exe')['by_group']['all']
        self.assertEqual(S['P_test_insensitive'], 4)
        self.assertEqual(S['insensitive_rust'], dict(n=4, with_input_syms=1, without_input_syms=1, unchecked=1, not_recorded=1,
                                                     sym_translations={'getenv': 1, 'read': 1}))

    def test_old_record_not_recorded(self):
        cs = [case(INSENSITIVE_SEED, {'a': 'P_test'}, bundle='P01_x', input_insensitive=True)]
        S = M.summarize_rq1(build(cs, []), 'exe')['by_group']['all']
        self.assertEqual(S['insensitive_rust']['not_recorded'], 1)

    def test_verdict_unchanged(self):
        """Ký hiệu Rust chỉ được báo: in_S, P_test giữ nguyên."""
        cs = [case(INSENSITIVE_SEED, {'a': 'P_test'}, bundle='P01_x', input_insensitive=True, rust_input_syms={'a': ['read']})]
        T = build(cs, [div('a', INSENSITIVE_SEED, 0, bundle='P01_x')])
        t = T[('P01_x', 'c', 'a')]
        self.assertEqual((t['status'], t['in_S']), ('P_test', True))


# ---------------- dòng 22 ----------------
class UbR22(unittest.TestCase):
    def setUp(self):
        self.cs = [case(s, {'a': 'P_test', 'b': 'P_test', 'c': 'P_test'}) for s in (0, 1, 2)] + \
                  [case(s, {'a': 'P_test'}, bundle='P00_y') for s in (0, 1, 2)]
        self.divs = [div('a', 0, 0, san='ub'), div('a', 0, 1, stable=False, san='ub'), div('a', 1, 2), div('a', 2, 3, stable=False),
                     div('b', 0, 0, san='ub'), div('b', 0, 4, san='inconclusive'),
                     div('a', 0, 0, san='ub', bundle='P00_y')]

    def test_pair_level(self):
        T = build(self.cs, self.divs)
        a = T[('B01_x', 'c', 'a')]
        self.assertEqual({k: a[k] for k in M.UB_KEYS}, dict(n_div_all=4, n_div_ub=2, n_div_stable=2, n_div_stable_ub=1))
        self.assertEqual({k: T[('B01_x', 'c', 'c')][k] for k in M.UB_KEYS}, dict.fromkeys(M.UB_KEYS, 0))

    def test_group_level_and_distinct_inputs(self):
        S = M.summarize_rq1(build(self.cs, self.divs), 'exe')['by_group']
        b = S['B01']['ub_R22']
        self.assertEqual(b, dict(n_div_all=6, n_div_ub=3, n_div_stable=4, n_div_stable_ub=2, translations_with_div=2,
                                 translations_with_ub=2,
                                 # input (seed 0, idx 0) UB chung cho a và b: một input phân biệt
                                 inputs_div=5, inputs_ub=2, inputs_div_stable=3, inputs_stable_ub=1))
        al = S['all']['ub_R22']
        self.assertEqual((al['n_div_all'], al['n_div_ub'], al['inputs_ub']), (7, 4, 3))
        self.assertEqual(S['all']['ub_R22_by_pair']['P00_y/c/a'], dict(n_div_all=1, n_div_ub=1, n_div_stable=1, n_div_stable_ub=1))
        self.assertNotIn('B01_x/c/c', S['all']['ub_R22_by_pair'])           # cặp không có divergence: không liệt kê
        self.assertNotIn('ub_R22_by_pair', S['B01'])

    def test_lib_old_record_c_ub_only(self):
        d = dict(kind='lib', bundle='B01_x', case='c', system='a', seed=0, idx=0, stable=True, c_ub=True)   # bản ghi cũ: không có san
        T = build([case(s, {'a': 'P_test'}) for s in (0, 1, 2)], [d])
        S = M.summarize_rq1(T, 'lib')['by_group']['all']['ub_R22']
        self.assertEqual((S['n_div_ub'], S['n_div_stable_ub'], S['n_div_all']), (1, 1, 1))

    def test_s_unchanged(self):
        """UB không vào S như trước (R15)."""
        T = build(self.cs, self.divs)
        self.assertFalse(T[('P00_y', 'c', 'a')]['in_S']); self.assertFalse(T[('B01_x', 'c', 'b')]['in_S'])
        self.assertTrue(T[('B01_x', 'c', 'a')]['in_S'])


# ---------------- dòng 23 ----------------
class BnuRuleIds(unittest.TestCase):
    def test_rule_ids_kept_and_counted(self):
        cs = [case(s, {'a': 'P_test', 'b': 'P_test'}) for s in (0, 1, 2)] + [case(s, {'a': 'P_test'}, bundle='P01_y') for s in (0, 1, 2)]
        divs = [div('a', 0, 0, out=(b'a  \n', b'a\n')),                 # B1-whitespace
                div('a', 1, 1, out=(b'0.406993\n', b'0.406994\n')),     # B2-numeric
                div('a', 2, 2, out=(b'2\n', b'3\n')),                   # N3-line
                div('b', 0, 0, out=(b'2\n', b'3\n')),                   # N3-line
                div('b', 1, 3, out=(b'x\n', b'x\n'), r_rc=1),           # N1-status
                div('b', 2, 4, stable=False, out=(b'2\n', b'3\n')),     # không giữ lại: không đếm
                div('a', 0, 0, out=(b'x\nmenu\n', b'x\n'), bundle='P01_y')]   # U-residual
        T = build(cs, divs)
        self.assertEqual(T[('B01_x', 'c', 'a')]['bnu_rules'], {'B1-whitespace': 1, 'B2-numeric': 1, 'N3-line': 1})
        self.assertEqual(T[('B01_x', 'c', 'b')]['bnu_rules'], {'N3-line': 1, 'N1-status': 1})
        S = M.summarize_rq1(T, 'exe')['by_group']
        self.assertEqual(S['B01']['bnu_rule_div'], {'B1-whitespace': 1, 'B2-numeric': 1, 'N3-line': 2, 'N1-status': 1})
        self.assertEqual(S['B01']['bnu_rule_translations'], {'B1-whitespace': 1, 'B2-numeric': 1, 'N3-line': 2, 'N1-status': 1})
        self.assertEqual(S['B01']['n_div_retained'], sum(S['B01']['bnu_rule_div'].values()))
        self.assertEqual(S['P01']['bnu_rule_div'], {'U-residual': 1})
        self.assertEqual(S['all']['bnu_rule_div']['N3-line'], 2)
        self.assertEqual(S['all']['bnu_rule_translations']['U-residual'], 1)
        # band NB_L, NB_U không đổi: vẫn từ nhóm của mã luật
        self.assertEqual((S['all']['NB_L'], S['all']['NB_U']), (2, 3))

    def test_bnu_group_matches_rule(self):
        d = div('a', 0, 0, out=(b'2\n', b'3\n'))
        self.assertEqual(M.bnu_rule(d), ('N', 'N3-line')); self.assertEqual(M.bnu_group(d), 'N')

    def test_nt_prefix_rule_id(self):
        d = dict(div('a', 0, 0, out=(b'1\n2\n', b'1\n2\n')), c_to=True, r_to=True, c_rc=None, r_rc=None)
        self.assertEqual(M.bnu_rule(d)[1], 'NT-prefix')


if __name__ == '__main__':
    unittest.main()
