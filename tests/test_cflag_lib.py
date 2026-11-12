"""Regression test cho cờ C crash của library (`c_flag`, sửa F2 ngày 24/10, decision-log 2026-10-24 F2): divergence library mang c_flag khi bản
C kết thúc SegmentationFault, Panic hoặc UnknownFailure và sanitizer phía C không báo; dùng cho SA-1. Không cần corpus.
Chạy: python3 -m unittest tests.test_cflag_lib"""
import gzip, json, os, tempfile, unittest
from unittest import mock

from harness import rq1


def obs(result, out='x'):
    return dict(k1='reported', result=result, state_out={'v': 1}, stdout=out, stderr='', san_flag=False)


class CFlagLib(unittest.TestCase):
    def run_case(self, c_result, san_status):
        d = tempfile.mkdtemp(); vec = f'{d}/v0.json'; json.dump(dict(lib_state_in={'a': 1}, lib_state_out={}), open(vec, 'w'))
        div = f'{d}/out/div/B01_x__c__s0.jsonl'; os.makedirs(os.path.dirname(div))
        def rl(rb, root, p, timeout, rust, dump, **k):
            return obs('Pass', 'r') if rust else obs(c_result, 'c')
        with mock.patch.object(rq1.BD, 'build_lib_case', return_value=dict(runner_ok=True, c_ok=True, library='x', runner_bin='/rb')), \
             mock.patch.object(rq1.BD, 'build_rust_lib', return_value=dict(ok=True, dir='/r')), \
             mock.patch.object(rq1.BD, 'lib_root', return_value='/root'), mock.patch.object(rq1.BD, 'asan_preload', return_value=None), \
             mock.patch.object(rq1, '_lib_inputs', return_value=([(vec, 'vector')], None, 1)), \
             mock.patch.object(rq1, '_rl', side_effect=rl), \
             mock.patch.object(rq1, 'lib_san', return_value=dict(status=san_status, markers=[], attempts=1)):
            r = rq1.rq1_lib_case(d, 'B01_x', 'c', [dict(system='a', harvest_case='c')], 0, dict(n_inputs=1), 10, div, 't')
        self.assertEqual(r['status'], 'done')
        return [json.loads(l) for l in open(div)]

    def test_crash_without_ub_sets_flag(self):
        for res in ('SegmentationFault', 'Panic', 'UnknownFailure'):
            ds = self.run_case(res, 'no_report')
            self.assertEqual(len(ds), 1); self.assertTrue(ds[0]['c_flag'], res); self.assertTrue(ds[0]['retained'])

    def test_no_flag_when_ub_or_no_crash(self):
        self.assertFalse(self.run_case('SegmentationFault', 'ub')[0]['c_flag'])
        self.assertFalse(self.run_case('VectorComparisonFailed', 'no_report')[0]['c_flag'])


if __name__ == '__main__':
    unittest.main()
