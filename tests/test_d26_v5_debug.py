"""Hai lựa chọn của Le 26/10 sau đợt d26: state_debug chỉ giữ ở RQ2 (record RQ1 và V5 bỏ trường này, giữ state_nonfinite); D1 áp cho V5
(runner library không trả report thì không chạy lại gấp mười, vector unobserved, không tính là lệch). Không cần corpus.
Chạy: python3 -m unittest tests.test_d26_v5_debug"""
import json, os, tempfile, unittest
from unittest import mock

from harness import checks as CK
from harness import observe as OB


class RecObs(unittest.TestCase):
    def test_drops_state_debug_only(self):
        o = dict(k1='reported', result='Pass', state_out={'x': None}, state_nonfinite=['NaN'], state_debug='S { x: NaN }')
        r = OB.rec_obs(o)
        self.assertNotIn('state_debug', r); self.assertEqual(r['state_nonfinite'], ['NaN']); self.assertIn('state_debug', o)
        self.assertIsNone(OB.rec_obs(None))


class V5Unobserved(unittest.TestCase):
    def run_v5(self, c_obs, r_obs):
        d = tempfile.mkdtemp(); vec = f'{d}/test01.json'; json.dump({'lib_state_in': {}, 'lib_state_out': {}}, open(vec, 'w'))
        calls = []
        def rl(rb, root, f, timeout, rust, dump):
            calls.append(timeout); return dict(r_obs if rust else c_obs)
        info = dict(runner_ok=True, c_ok=True, library='x', runner_bin='/bin/true')
        with mock.patch.object(CK.BD, 'build_lib_case', return_value=info), \
             mock.patch.object(CK.BD, 'build_rust_lib', return_value=dict(ok=True, dir=d)), \
             mock.patch.object(CK.BD, 'lib_root', return_value=d), \
             mock.patch.object(CK, 'lib_seeds', return_value=[dict(path=vec, file='test01.json', vec={})]), \
             mock.patch.object(CK.OB, 'run_lib_retry', side_effect=rl):
            out = CK.v5_lib_case(d, 'B01_x', 'c', [dict(system='a', via='v', harvest_case='c')], 10)
        return out[0], calls

    def test_infra_not_rerun_not_mismatch(self):
        rec, calls = self.run_v5(dict(k1='reported', result='Pass', rc=0, state_out={}), dict(k1='infra', result=None, rc=None))
        self.assertEqual(calls, [10, 10])                                 # không có lượt gấp mười
        v = rec['vectors'][0]
        self.assertTrue(v['unobserved']); self.assertIsNone(v['equal'])
        self.assertEqual((rec['n_mismatch'], rec['n_unobserved']), (0, 1))

    def test_mismatch_record_has_no_state_debug(self):
        c = dict(k1='reported', result='Pass', rc=0, state_out={'x': 1}, state_debug='S { x: 1 }')
        r = dict(k1='reported', result='VectorComparisonFailed', rc=0, state_out={'x': 2}, state_debug='S { x: 2 }')
        rec, _ = self.run_v5(c, r)
        v = rec['vectors'][0]
        self.assertFalse(v['equal']); self.assertNotIn('state_debug', v['c']); self.assertNotIn('state_debug', v['r'])
        self.assertEqual(rec['n_mismatch'], 1)


if __name__ == '__main__':
    unittest.main()
