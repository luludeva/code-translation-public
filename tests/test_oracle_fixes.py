"""Hồi quy cho các sửa sau rà độc lập §3.3 v5 (2026-10-23): chuẩn hoá NaN, mã luồng panic; vô cực và NaN trong state library;
phân loại sanitizer phía C; lỗi hạ tầng của runner library; luật quyết định RQ2; vector library làm input RQ1."""
import json, os, shutil, subprocess, tempfile, unittest
from unittest import mock

from harness import checks, rq1, rq2
from harness import observe as OB


def exe(status='exit', rc=0, sig=None, out=b'', err=b''):
    return dict(status=status, rc=rc if status == 'exit' else None, sig=sig, to=status == 'timeout', out=out, err=err)


def lib(result='Pass', k1='reported', state=None, nonfinite=None, stdout='', stderr='', rc=0):
    o = dict(k1=k1, result=result, rc=rc, state_out=state if state is not None else {'x': 1.0}, stdout=stdout, stderr=stderr)
    if nonfinite is not None: o['state_nonfinite'] = nonfinite
    return o


class Normalization(unittest.TestCase):
    def test_nan_word_boundary(self):
        self.assertEqual(OB.norm(b'NaN -nan nan'), b'nan nan nan')
        self.assertEqual(OB.norm(b'NANCY nano banana'), b'NANCY nano banana')


    def test_panic_thread_id(self):
        a = b"thread 'main' (223) panicked at src/main.rs:1:5:\nindex out of bounds"
        b = b"thread 'main' (250) panicked at src/main.rs:1:5:\nindex out of bounds"
        self.assertEqual(OB.norm_err(a), OB.norm_err(b))
        self.assertTrue(OB.equal_exe(exe('exit', 101, err=a), exe('exit', 101, err=b)))

    @unittest.skipUnless(shutil.which('rustc'), 'cần rustc')
    def test_real_panic_stable_across_runs(self):
        d = tempfile.mkdtemp(); src = os.path.join(d, 'p.rs'); b = os.path.join(d, 'p')
        open(src, 'w').write('fn main(){ let v: Vec<i32> = vec![]; println!("{}", v[std::env::args().count() + 2]); }')
        subprocess.run(['rustc', '-O', src, '-o', b], check=True, capture_output=True)
        runs = [OB.run_exe(b, [], '', 10) for _ in range(3)]
        self.assertTrue(all(OB.equal_exe(runs[0], r) for r in runs[1:]))


class Floats(unittest.TestCase):
    def test_infinity_exact(self):
        inf = float('inf')
        self.assertFalse(OB.float_tol_equal(inf, 5.0))
        self.assertFalse(OB.float_tol_equal(inf, -inf))
        self.assertTrue(OB.float_tol_equal(inf, inf))
        self.assertTrue(OB.float_tol_equal(float('nan'), float('nan')))
        self.assertTrue(OB.float_tol_equal(1.0, 1.0 + 1e-9))

    def test_nonfinite_tokens(self):
        self.assertEqual(OB.nonfinite_tokens('S { a: NaN, b: -inf, c: [inf, 1.0], info: "x", inf_n: 2, d: None }'),
                         ['NaN', '-inf', 'inf'])

    def test_null_states_distinguished_by_debug(self):
        a = lib(state={'v': None}, nonfinite=['NaN']); b = lib(state={'v': None}, nonfinite=['inf'])
        self.assertEqual(OB.channels_lib(a, b), ['state'])
        self.assertTrue(OB.equal_lib(lib(state={'v': None}, nonfinite=['-inf']), lib(state={'v': None}, nonfinite=['-inf'])))


class Sanitizer(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(rq1.classify_san('ub', ['runtime error:'], False, False, False), 'ub')
        self.assertEqual(rq1.classify_san('mem_limit', [], False, False, False), 'inconclusive')
        self.assertEqual(rq1.classify_san('no_report', [], True, False, False), 'inconclusive')
        self.assertEqual(rq1.classify_san('no_report', [], False, True, False), 'infra')      # C-san chết, C thường không chết
        self.assertEqual(rq1.classify_san('no_report', [], False, True, True), 'no_report')   # cả hai cùng chết: chương trình tự abort
        self.assertEqual(rq1.classify_san('no_report', [], False, False, False), 'no_report')

    def test_exe_san_build_failed_is_infra(self):
        self.assertEqual(rq1._exe_san({'ok': False}, [], '', 10, None)['status'], 'infra')

    def test_counts_and_retained_agree(self):
        import collections
        c = collections.Counter()
        self.assertTrue(rq1.san_counts(c, True, 'no_report'))
        self.assertFalse(rq1.san_counts(c, True, 'inconclusive'))
        self.assertFalse(rq1.san_counts(c, True, 'infra'))
        self.assertFalse(rq1.san_counts(c, False, 'no_report'))
        self.assertEqual((c['div_stable_noub'], c['div_stable_san_inconclusive'], c['div_stable_san_infra']), (1, 1, 1))

    def test_pair_status(self):
        self.assertEqual(rq1.pair_status({'observed': 5}, 5), 'P_test')
        self.assertEqual(rq1.pair_status({'observed': 4, 'infra_inputs': 1}, 5), 'incomplete')
        self.assertEqual(rq1.pair_status({'observed': 5, 'div_stable_san_infra': 1}, 5), 'san_infra')
        self.assertEqual(rq1.pair_status({'observed': 5, 'div_stable_san_infra': 1, 'div_stable_noub': 1}, 5), 'P_test')
        self.assertEqual(rq1.pair_status({'rust_build_failed': 1}, 5), 'rust_build_failed')


class LibInfraRetry(unittest.TestCase):
    def test_retry_until_report(self):
        seq = iter([lib(k1='infra'), lib(k1='infra'), lib()])
        with mock.patch.object(OB, 'run_lib', side_effect=lambda *a, **k: next(seq)) as m:
            self.assertEqual(rq1._rl('rb', 'root', 'v', 10, False, 'd')['k1'], 'reported')
            self.assertEqual(m.call_count, 3)

    def test_gives_up_after_attempts(self):
        with mock.patch.object(OB, 'run_lib', return_value=lib(k1='infra')) as m:
            self.assertEqual(rq1._rl('rb', 'root', 'v', 10, False, 'd')['k1'], 'infra')
            self.assertEqual(m.call_count, rq1.LIB_INFRA_ATTEMPTS)


class RQ2Rules(unittest.TestCase):
    def runs(self, pairs):
        return [(c, r, False) for c, r in pairs]

    def test_supports_rejection(self):
        r = self.runs([(exe(out=b'1'), exe(out=b'2'))] * 3)
        self.assertEqual(rq2.vector_outcome(r, 'no_report', 'exe'), ('supports_rejection', None))

    def test_agrees_needs_clean_sanitizer(self):
        r = self.runs([(exe(out=b'1'), exe(out=b'1'))] * 3)
        self.assertEqual(rq2.vector_outcome(r, 'no_report', 'exe'), ('agrees', None))
        self.assertEqual(rq2.vector_outcome(r, 'inconclusive', 'exe'), ('not_adjudicable', 'sanitizer_inconclusive'))
        self.assertEqual(rq2.vector_outcome(r, 'ub', 'exe'), ('not_adjudicable', 'ub_in_c'))

    def test_both_budget_library_not_agreement(self):
        r = self.runs([(lib('Timeout'), lib('OutputLimit'))] * 3)
        self.assertTrue(OB.equal_lib(lib('Timeout'), lib('OutputLimit')))     # RQ1: cùng lớp
        self.assertEqual(rq2.vector_outcome(r, 'no_report', 'lib'), ('not_adjudicable', 'both_budget'))

    def test_both_budget_exe_not_agreement(self):
        r = self.runs([(exe('timeout', out=b'a\n'), exe('output_limit', out=b'a\n'))] * 3)
        self.assertEqual(rq2.vector_outcome(r, 'no_report', 'exe'), ('not_adjudicable', 'both_budget'))

    def test_unstable(self):
        r = self.runs([(exe(out=b'1'), exe(out=b'2')), (exe(out=b'1'), exe(out=b'1')), (exe(out=b'1'), exe(out=b'2'))])
        self.assertEqual(rq2.vector_outcome(r, 'no_report', 'exe'), ('not_adjudicable', 'unstable_comparison'))

    def test_infra_incomplete(self):
        r = self.runs([(lib(k1='infra'), lib())] * 3)
        self.assertEqual(rq2.vector_outcome(r, 'no_report', 'lib'), ('incomplete', 'run_unobserved'))   # F5: trước 'infra'

    def test_one_sided_budget_rerun(self):
        calls = []
        def rc(t): calls.append(('c', t)); return exe(out=b'1')
        def rr(t): calls.append(('r', t)); return exe('timeout') if t == 10 else exe(out=b'1')
        runs = rq2.observe_vector(rc, rr, 10, 'exe')
        self.assertTrue(all(reran for _, _, reran in runs))
        self.assertEqual(rq2.vector_outcome(runs, 'no_report', 'exe'), ('agrees', None))

    def test_translation_level(self):
        T = rq2.translation_outcome
        self.assertEqual(T([('agrees', None), ('supports_rejection', None)])[0], 'behavioral_disagreement')
        self.assertEqual(T([('agrees', None), ('agrees', None)])[0], 'behavioral_agreement')
        self.assertEqual(T([('agrees', None), ('incomplete', 'infra')])[0], 'not_re_examined')
        self.assertEqual(T([('agrees', None), ('not_adjudicable', 'both_budget')]), ('not_adjudicable', ['both_budget']))


class LibVectorInputs(unittest.TestCase):
    def test_vectors_included_first(self):
        seeds = [dict(vec=dict(lib_state_in={'a': 1}, stdin='x')), dict(vec=dict(lib_state_in={'a': 2}))]
        gen = [dict(state={'a': 3}, seed_index=0, source='random')]
        B = tempfile.mkdtemp()
        with mock.patch.object(checks, 'parse_runner', return_value={}), mock.patch.object(checks, 'lib_seeds', return_value=seeds), \
                mock.patch.object(checks, '_cdict', return_value=({}, None)), \
                mock.patch.object(checks.stategen_v2, 'generate', return_value=gen), \
                mock.patch('builtins.open', side_effect=lambda p, *a, **k: io_open(p, *a, **k)):
            files, err, n = checks._lib_inputs(B, dict(bundle='b', case='c'), 1, 0, include_vectors=True)
        self.assertEqual([s for _, s in files], ['vector', 'vector', 'random'])
        v0 = json.load(io_open(files[0][0]))
        self.assertEqual((v0['lib_state_in'], v0['stdin'], v0['lib_state_out']), ({'a': 1}, 'x', {}))


import builtins
_real_open = builtins.open


def io_open(p, *a, **k):
    if str(p).endswith('runner/src/main.rs'):
        import io
        return io.StringIO('')
    return _real_open(p, *a, **k)


if __name__ == '__main__':
    unittest.main()


from harness import build as BD
from harness.config import T as _T

_GK = ('B01_organic', 'gaussian_kernel_lib')


@unittest.skipUnless(os.path.isdir(f'{_T}/{_GK[0]}/{_GK[1]}'), 'cần corpus TRACTOR')
class LibRunnerV2(unittest.TestCase):
    """Bản vá runner v2 ghi state_debug; runner từ chối vector (số ngoài miền f32) là 'invalid_input', không phải lỗi hạ tầng."""
    @classmethod
    def setUpClass(cls):
        cls.B = os.environ.get('HARNESS_BUILD', os.path.join(tempfile.gettempdir(), 'harness-test-build'))
        cls.info = BD.build_lib_case(cls.B, *_GK)
        cls.root = BD.lib_root(cls.B, cls.info, 'c')
        cls.vec = json.load(open(sorted(f.path for f in os.scandir(f'{_T}/{_GK[0]}/{_GK[1]}/test_vectors')
                                        if f.name.endswith('.json'))[0]))

    def run_with(self, radius):
        w = dict(self.vec, lib_state_in=dict(self.vec['lib_state_in'], radius=radius), lib_state_out={})
        p = os.path.join(self.B, 'gk-test.json'); json.dump(w, open(p, 'w'))
        return OB.run_lib(self.info['runner_bin'], self.root, p, 10, False, os.path.join(self.B, 'gk-test.dump'))

    def test_state_debug_present(self):
        o = self.run_with(2.5)
        self.assertEqual(o['k1'], 'reported'); self.assertEqual(o['state_nonfinite'], [])

    def test_out_of_range_is_invalid_input(self):
        self.assertEqual(self.run_with(1e300)['k1'], 'invalid_input')
