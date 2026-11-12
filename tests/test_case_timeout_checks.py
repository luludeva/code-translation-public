"""Timeout theo case cho V5, V6 và RQ2 executable (decision-log 2026-10-25 "Timeout theo case cho các kiểm và RQ2"; cài 2026-10-26 sau
khi đối chiếu hàng đợi master plan phát hiện chưa cài). Library giữ timeout truyền vào. Không cần corpus.
Chạy: python3 -m unittest tests.test_case_timeout_checks"""
import unittest
from unittest import mock

from harness import checks as CK
from harness import rq1
from harness import rq2

SLOW = 'P01_x/slow'


class CaseTimeout(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.dict(rq1.C_TIME, {SLOW: 47.0}, clear=False); self.p.start()

    def tearDown(self): self.p.stop()

    def test_helper(self):
        self.assertEqual(CK._exe_timeout('P01_x', 'slow', 10), rq1.case_timeout('P01_x', 'slow', 10))
        self.assertGreater(CK._exe_timeout('P01_x', 'slow', 10), 10)
        self.assertEqual(CK._exe_timeout('B01_x', 'fast_not_in_table', 10), 10)

    def test_v6_exe_uses_case_timeout(self):
        seen = []
        with mock.patch.object(CK.BD, 'build_c_exe', return_value=dict(ok=True, bin='/bin/true')), \
             mock.patch.object(CK, 'exe_seeds', return_value=[dict(argv=[], stdin='')]), \
             mock.patch.object(CK, '_cdict', return_value=({}, None)), \
             mock.patch.object(CK, 'gen_inputs_v2', return_value=[([], '', 'random')]), \
             mock.patch.object(CK.OB, 'run_exe', side_effect=lambda b, a, i, t, *x, **k: seen.append(t) or
                               dict(status='exit', rc=0, sig=None, out=b'', err=b'')):
            r = CK.v6_exe_case('/b', 'P01_x', 'slow', 10)
        self.assertEqual((r['timeout'], r['timeout_base']), (rq1.case_timeout('P01_x', 'slow', 10), 10))
        self.assertEqual(set(seen), {r['timeout']})

    def test_v5_exe_record_has_case_timeout(self):
        with mock.patch.object(CK.BD, 'build_c_exe', return_value=dict(ok=False)), \
             mock.patch.object(CK, 'exe_seeds', return_value=[]):
            out = CK.v5_exe_case('/b', 'P01_x', 'slow', [dict(system='a', via='v')], 10)
        self.assertEqual(out[0]['timeout'], rq1.case_timeout('P01_x', 'slow', 10)); self.assertEqual(out[0]['timeout_base'], 10)

    def test_rq2_exe_record_has_case_timeout_lib_unchanged(self):
        row = dict(bundle='P01_x', tractor_case='slow', system='a', v_f=[], timeout_only=True, report_found=True)
        r = rq2.rq2_pair('/b', 'exe', row, 10)
        self.assertEqual((r['timeout'], r['timeout_base']), (rq1.case_timeout('P01_x', 'slow', 10), 10))
        r = rq2.rq2_pair('/b', 'lib', dict(row, tractor_case='slow'), 10)
        self.assertEqual((r['timeout'], r['timeout_base']), (10, 10))


if __name__ == '__main__':
    unittest.main()
