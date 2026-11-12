"""F3 (Le chọn 25/10, exp 20): timeout theo case từ thời gian C đo trước; case executable không đọc input chỉ chạy ở một seed.
Không cần corpus. Chạy: python3 -m unittest tests.test_f3_timeout_once"""
import unittest
from unittest import mock

from harness import metrics as M
from harness import rq1
from harness.config import INSENSITIVE_SEED


class CaseTimeout(unittest.TestCase):
    def test_rule(self):
        with mock.patch.dict(rq1.C_TIME, {'P/slow': 47.06, 'P/fast': 0.002}, clear=True):
            self.assertEqual(rq1.case_timeout('P', 'slow', 10), 142)       # ceil(3 × 47,06)
            self.assertEqual(rq1.case_timeout('P', 'fast', 10), 10)
            self.assertEqual(rq1.case_timeout('P', 'missing', 10), 10)
            self.assertEqual(rq1.case_timeout('P', 'fast', 30), 30)

    def test_table_from_exp20(self):
        self.assertGreaterEqual(len(rq1.C_TIME), 100)
        self.assertEqual(max(rq1.C_TIME, key=rq1.C_TIME.get).split('/')[0], 'P01_sphincs_plus')


class InsensitiveOnce(unittest.TestCase):
    def run_case(self, seed):
        ok = dict(ok=True, bin='/x', sha256='h', preset=None)
        with mock.patch.object(rq1.BD, 'build_c_exe', return_value=ok), \
             mock.patch.object(rq1.BD, 'build_rust_exe', return_value=dict(ok=True, sha256='r')), \
             mock.patch.object(rq1.insensitive, 'check', return_value=(True, {})), \
             mock.patch.object(rq1, 'gen_exe', side_effect=AssertionError('không được sinh input')):
            return rq1.rq1_exe_case('/b', 'P01_x', 'c', [dict(system='a', harvest_case='c')], seed, {}, 10, '/nonexistent', 't')

    def test_other_seed_not_run(self):
        r = self.run_case(INSENSITIVE_SEED + 1)
        self.assertEqual(r['status'], 'insensitive_other_seed'); self.assertTrue(r['input_insensitive'])

    def test_metrics_need_only_insensitive_seed(self):
        rec = dict(bundle='P01_x', case='c', seed=INSENSITIVE_SEED, status='done', input_insensitive=True, pair_status={'a': 'P_test'},
                   gen=dict(n_by_layer={'S': 1}))
        T = M.rq1_translations([rec], {}, {}, [0, 1, 2])
        t = T[('P01_x', 'c', 'a')]
        self.assertEqual(t['status'], 'P_test'); self.assertTrue(t['input_insensitive']); self.assertFalse(t['complete_layers'])
        rec2 = dict(rec, input_insensitive=False)
        self.assertEqual(M.rq1_translations([rec2], {}, {}, [0, 1, 2])[('P01_x', 'c', 'a')]['status'], 'missing_seed')


if __name__ == '__main__':
    unittest.main()
