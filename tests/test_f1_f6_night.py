"""Hai sửa đêm 25/10 (Le chọn, rà F6): luật NT đối xứng (observe.nt_cut, F1) và bnu dùng đúng điểm cắt đó; RQ1 coi Pass và
VectorComparisonFailed của library là cùng kết quả (observe.channels_lib completed_same, F1, F6), RQ2 giữ như cũ.
Chạy: python3 -m unittest tests.test_f1_f6_night"""
import importlib.util, unittest

from harness import observe as OB
from harness import rq1
from harness.config import REPO

_s = importlib.util.spec_from_file_location('bnu_v0', f'{REPO}/experiments/09-bnu-rules/scripts/bnu_v0.py')
BNU = importlib.util.module_from_spec(_s); _s.loader.exec_module(BNU)


def nt(out): return dict(status='timeout', rc=None, sig=None, out=out, err=b'')


class NtSymmetric(unittest.TestCase):
    CASES = [(b'x\nAB\nZZZ', b'x\nACDDDD'), (b'ab\ncd', b'ab\ncdef\n'), (b'ab\nX1', b'ab\nY2\n'), (b'1.0-nan', b'1.0nan'),
             (b'a\nb\nc\n', b'a\nb\nd\n'), (b'', b'abc\n')]

    def test_swap_invariant(self):
        for a, b in self.CASES:
            self.assertEqual(OB.nt_prefix(nt(a), nt(b))[0], OB.nt_prefix(nt(b), nt(a))[0], (a, b))

    def test_examples(self):
        self.assertFalse(OB.nt_prefix(nt(b'x\nAB\nZZZ'), nt(b'x\nACDDDD'))[0])     # khác nhau trong cửa sổ chung: divergence
        self.assertTrue(OB.nt_prefix(nt(b'ab\ncd'), nt(b'ab\ncdef\n'))[0])         # khác chỉ ở dòng dở dang: khớp
        self.assertEqual(OB.nt_prefix(nt(b'1.0-nan'), nt(b'1.0nan')), (True, 0))

    def test_bnu_follows_oracle(self):
        for a, b in self.CASES:
            eq = OB.nt_prefix(nt(a), nt(b))[0]
            g, rule = BNU.classify_exe(None, None, True, True, a.decode(), b.decode(), False)
            self.assertEqual(g == 'not_S', eq, (a, b, g, rule))


class PassVcf(unittest.TestCase):
    def o(self, result, out='', err=''):
        return dict(k1='reported', result=result, state_out={'v': 1}, stdout=out, stderr=err)

    def test_rq1_ignores_pass_vcf(self):
        c, r = self.o('Pass'), self.o('VectorComparisonFailed', err='   \n')     # stderr toàn khoảng trắng: bằng nhau sau N
        self.assertTrue(rq1._eq_lib(c, r))
        self.assertEqual(rq1._ch_lib(self.o('Pass'), self.o('VectorComparisonFailed', err='warn\n')), ['stderr'])
        self.assertIn('status', rq1._ch_lib(self.o('Pass'), self.o('SegmentationFault')))

    def test_rq2_and_checks_unchanged(self):
        self.assertFalse(OB.equal_lib(self.o('Pass'), self.o('VectorComparisonFailed')))

    def test_bnu_no_status_channel(self):
        g, rule = BNU.classify_lib(self.o('Pass'), self.o('VectorComparisonFailed', err='warn\n'), False)
        self.assertNotEqual(rule, 'N1-status')


if __name__ == '__main__':
    unittest.main()
