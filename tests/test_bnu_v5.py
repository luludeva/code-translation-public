"""bnu-v5 (Le chọn 25/10 tối, ba lệch nhẹ của rà F6, experiments/24-f6-bnu-audit/README.md mục 4 điểm 4 và 5):
B2 so hai token số nguyên chính xác; hai bên cùng NT mà oracle khớp mang mã luật NT-prefix; nhánh R15-UB là phòng vệ.
Chạy: python3 -m unittest tests.test_bnu_v5"""
import importlib.util, itertools, unittest

from harness import observe as OB
from harness import metrics, record, rq1
from harness.config import REPO

_s = importlib.util.spec_from_file_location('bnu_v0', f'{REPO}/experiments/09-bnu-rules/scripts/bnu_v0.py')
BNU = importlib.util.module_from_spec(_s); _s.loader.exec_module(BNU)


def exe(c_out, r_out, c_to=False, r_to=False, c_ub=False, c_err='', r_err=''):
    return BNU.classify_exe(None if c_to else 0, None if r_to else 0, c_to, r_to, c_out, r_out, c_ub, False, c_err, r_err)


def lib(c_out, r_out):
    o = lambda s: dict(k1='reported', result='Pass', stdout=s, stderr='')
    return BNU.classify_lib(o(c_out), o(r_out))


class Version(unittest.TestCase):
    def test_version_and_self_test(self):
        self.assertEqual(BNU.RULES_VERSION, 'bnu-v5')
        self.assertEqual(BNU.self_test(), 32)


class IntegerTokensExact(unittest.TestCase):
    """Điểm 1: hai token số nguyên chỉ tương đương khi bằng nhau (§3.5 p5); token số thực giữ sai số như bnu-v4."""
    def test_large_integers_differ(self):
        self.assertFalse(BNU.num_equiv('9007199254740993', '9007199254740992'))   # bằng nhau dưới float (2^53 + 1)
        self.assertFalse(BNU.num_equiv('1' * 400, '1' * 399 + '2'))                # float tràn thành inf ở cả hai
        self.assertFalse(BNU.num_equiv('1' * 5000, '1' * 4999 + '2'))              # vượt giới hạn chữ số của int(): không lỗi
        self.assertFalse(BNU.num_equiv('2', '3'))
        self.assertFalse(BNU.num_equiv('-1', '1'))

    def test_equal_integers_spelled_differently(self):
        for a, b in [('007', '7'), ('-0', '0'), ('+0', '-0'), ('+5', '5'), ('00', '0'), ('1' * 5000, '+' + '1' * 5000)]:
            self.assertTrue(BNU.num_equiv(a, b), (a, b))

    def test_real_tokens_unchanged(self):
        for a, b, want in [('0.406993', '0.406994', True), ('0.813987', '0.894282', False), ('-0.000000', '0.000000', True),
                           ('3', '3.0', True), ('1e3', '1000', True), ('1.0000001e5', '1.0000002e5', True), ('inf', '-inf', False),
                           ('9007199254740993.0', '9007199254740992.0', True)]:
            self.assertEqual(BNU.num_equiv(a, b), want, (a, b))

    def test_group_exe_and_lib(self):
        self.assertEqual(exe('9007199254740993\n', '9007199254740992\n'), ('N', 'N3-line'))
        self.assertEqual(lib('9007199254740993\n', '9007199254740992\n'), ('N', 'N3-line'))
        self.assertEqual(exe('n=007\n', 'n=7\n'), ('B', 'B2-numeric'))
        self.assertEqual(exe('9007199254740993\n', '9007199254740992\n', c_to=True, r_to=True), ('N', 'N3-line'))

    def test_only_integer_pairs_change(self):
        """So với bnu-v4 (float): kết quả num_equiv chỉ đổi ở cặp hai token số nguyên khác nhau mà float coi là bằng."""
        toks = ['0', '-0', '007', '7', '3', '3.0', '1e3', '1000', '0.406993', '0.406994', 'inf', '-inf',
                '9007199254740992', '9007199254740993', '1.5', '1.50', '+2', '2']
        for a, b in itertools.product(toks, repeat=2):
            both_int = BNU.decimals(a) == 0 and BNU.decimals(b) == 0
            v4 = a == b or (float(a) == float(b) if both_int else BNU.num_equiv(a, b))
            if BNU.num_equiv(a, b) != v4:
                self.assertTrue(both_int and float(a) == float(b) and not BNU.int_equal(a, b), (a, b))


class NtPrefixRuleCode(unittest.TestCase):
    """Điểm 2: hai bên cùng NT, oracle khớp: mã luật NT-prefix (nhóm vẫn not_S, theo oracle)."""
    CASES = [(b'1\n2\n3\n4', b'1\n2\n'), (b'x\n', b'x\nmenu\n'), (b'ab\ncd', b'ab\ncdef\n'), (b'1.0-nan', b'1.0nan'), (b'', b'abc\n')]

    def test_rule_code(self):
        for a, b in self.CASES:
            self.assertTrue(OB.nt_prefix(dict(out=a), dict(out=b))[0], (a, b))
            self.assertEqual(exe(a.decode(), b.decode(), True, True), ('not_S', 'NT-prefix'), (a, b))

    def test_r_nan_kept_for_terminated(self):
        self.assertEqual(exe('-nan\n', 'NaN\n'), ('not_S', 'R-NaN'))
        self.assertEqual(exe('a\n', 'a\n', c_err='Err 0x1f\n', r_err='err 0xaa  \n'), ('not_S', 'R-NaN'))

    def test_nt_divergence_unchanged(self):
        self.assertEqual(exe('x\nAB\nZZZ', 'x\nACDDDD', True, True)[0], 'N')


class R15Defensive(unittest.TestCase):
    """Điểm 3: nhánh R15-UB giữ nguyên (phòng vệ); từ metrics nó không chạy vì divergence giữ lại không bao giờ mang c_ub."""
    def test_branches_kept(self):
        self.assertEqual(exe('a\n', 'b\n', c_ub=True), ('not_S', 'R15-UB'))
        self.assertEqual(exe('a\n', 'a\n', c_ub=True, r_err='x\n'), ('not_S', 'R15-UB'))
        self.assertEqual(exe('a\nX\n', 'a\nY\n', True, True, c_ub=True), ('not_S', 'R15-UB'))
        o = lambda s: dict(k1='reported', result='Pass', stdout=s, stderr='')
        self.assertEqual(BNU.classify_lib(o('a'), o('b'), True), ('not_S', 'R15-UB'))

    def test_retained_never_ub(self):
        for st in ('no_report', 'ub', 'inconclusive', 'infra'):
            for stable in (True, False):
                ret = rq1.san_counts({'div_stable_noub': 0, 'div_stable_san_inconclusive': 0, 'div_stable_san_infra': 0}, stable, st)
                self.assertFalse(ret and st == 'ub', (st, stable))
                self.assertFalse(metrics.retained(dict(stable=stable, san=st)) and st == 'ub', (st, stable))

    def test_metrics_path(self):
        d = dict(kind='exe', c_rc=0, r_rc=0, c_to=False, r_to=False, c_ub=False, retained=True,
                 c_out=record.blob(b'9007199254740993\n'), r_out=record.blob(b'9007199254740992\n'),
                 c_err=record.blob(b''), r_err=record.blob(b''))
        self.assertEqual(metrics.bnu_group(d), 'N')


if __name__ == '__main__':
    unittest.main()
