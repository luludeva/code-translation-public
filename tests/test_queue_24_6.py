"""Hai sửa theo hàng đợi master plan (Le chọn 26/10): dòng 24, classify_san xét UB trước vượt ngân sách; dòng 6, runner C-san library vượt
hạn chót của tiến trình ra 'inconclusive' như executable (trước đó 'infra'). Không cần corpus.
Chạy: python3 -m unittest tests.test_queue_24_6"""
import unittest
from unittest import mock

from harness import rq1

UB = b'x.c:3:5: runtime error: signed integer overflow\n'


class ClassifyOrder(unittest.TestCase):
    def test_ub_before_budget(self):
        self.assertEqual(rq1.classify_san('ub', [], True, False, False), 'ub')
        self.assertEqual(rq1.classify_san('no_report', [], True, False, False), 'inconclusive')
        self.assertEqual(rq1.classify_san('mem_limit', [], False, False, False), 'inconclusive')

    def test_exe_ub_then_timeout_is_ub(self):
        so = dict(status='timeout', rc=None, sig=None, out=b'', err=UB)
        with mock.patch.object(rq1.OB, 'run_exe', return_value=so):
            self.assertEqual(rq1._exe_san(dict(ok=True, bin='/x'), [], '', 10, None, 'exit')['status'], 'ub')


class LibDeadline(unittest.TestCase):
    def run_san(self, so):
        with mock.patch.object(rq1.OB, 'run_lib', return_value=so), mock.patch.object(rq1, 'lib_san_streams', return_value=[]):
            return rq1.lib_san('/rb', '/cs', '/v.json', 10, '/tmp/none.dump', None, dict(result='Pass'))

    def test_deadline_is_inconclusive_no_retry(self):
        so = dict(k1='infra', rc=None, infra_msg=rq1.RUNNER_DEADLINE_MSG, secs=90)
        r = self.run_san(so)
        self.assertEqual((r['status'], r['attempts']), ('inconclusive', 1))

    def test_other_infra_still_infra_with_retries(self):
        r = self.run_san(dict(k1='infra', rc=1, infra_msg='runner crashed'))
        self.assertEqual((r['status'], r['attempts']), ('infra', rq1.SAN_ATTEMPTS))

    def test_deadline_with_ub_report_is_ub(self):
        so = dict(k1='infra', rc=None, infra_msg=rq1.RUNNER_DEADLINE_MSG)
        with mock.patch.object(rq1.OB, 'run_lib', return_value=so), mock.patch.object(rq1, 'lib_san_streams', return_value=[UB]):
            self.assertEqual(rq1.lib_san('/rb', '/cs', '/v.json', 10, '/tmp/none.dump', None, {})['status'], 'ub')


if __name__ == '__main__':
    unittest.main()
