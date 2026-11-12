"""Bước tính số liệu (harness/metrics.py): phần luật S cấp bản dịch của V1 (unstable_only, SA-1, SA-2) và các phân tích độ nhạy."""
import unittest

from harness import metrics as M
from harness.record import blob


def case(seed, statuses, layers=('M', 'MS', 'A'), bundle='B01_x', name='c'):
    return dict(bundle=bundle, case=name, seed=seed, status='done', pair_status=statuses, gen=dict(n_by_layer={l: 1 for l in layers}))


def div(system, seed, stable=True, san='no_report', c_flag=False, c_ub=False, channels=('stdout',), out=(b'1\n', b'2\n'),
        cap=None, bundle='B01_x', name='c'):
    d = dict(kind='exe', bundle=bundle, case=name, system=system, seed=seed, stable=stable, san=san, c_flag=c_flag, c_ub=c_ub,
             channels=list(channels), c_rc=0, r_rc=0, c_to=False, r_to=False, c_out=blob(out[0]), r_out=blob(out[1]),
             c_err=blob(b''), r_err=blob(b''))
    if cap is not None: d['cap_sens'] = dict(equal=cap)
    return d


def build(cases, divs, caps=(), seeds=(0, 1, 2)):
    D, C = {}, {}
    for d in divs: D.setdefault((d['bundle'], d['case'], d['system'], d['seed']), []).append(d)
    for d in caps: C.setdefault((d['bundle'], d['case'], d['system'], d['seed']), []).append(d)
    return M.rq1_translations(cases, D, C, list(seeds))


class PTest(unittest.TestCase):
    def test_all_seeds_required_and_leave_priority(self):
        cs = [case(0, {'a': 'P_test', 'b': 'P_test', 'c': 'san_infra'}), case(1, {'a': 'P_test', 'b': 'incomplete', 'c': 'P_test'}),
              case(2, {'a': 'P_test', 'c': 'rust_build_failed'})]
        T = build(cs, [])
        st = {k[2]: t['status'] for k, t in T.items()}
        self.assertEqual(st, {'a': 'P_test', 'b': 'incomplete', 'c': 'rust_build_failed'})

    def test_missing_seed(self):
        T = build([case(0, {'a': 'P_test'}), case(1, {'a': 'P_test'})], [])
        self.assertEqual(T[('B01_x', 'c', 'a')]['status'], 'missing_seed')


class SRules(unittest.TestCase):
    def setUp(self):
        self.cs = [case(s, {x: 'P_test' for x in 'abcdefg'}) for s in (0, 1, 2)]

    def T(self, divs, caps=()):
        return {k[2]: t for k, t in build(self.cs, divs, caps).items()}

    def test_union_over_seeds(self):
        T = self.T([div('a', 0), div('a', 2)])
        self.assertTrue(T['a']['in_S']); self.assertEqual(T['a']['n_seeds_detect'], 2); self.assertFalse(T['b']['in_S'])

    def test_unstable_only_and_sa2(self):
        T = self.T([div('a', 0, stable=False), div('b', 0, stable=False, c_ub=True), div('c', 0, stable=True, san='ub')])
        self.assertTrue(T['a']['unstable_only']); self.assertTrue(T['a']['SA2']); self.assertFalse(T['a']['in_S'])
        self.assertTrue(T['b']['unstable_only']); self.assertFalse(T['b']['SA2'])        # mọi divergence bị loại theo R15
        self.assertFalse(T['c']['in_S']); self.assertFalse(T['c']['unstable_only'])     # ổn định nhưng UB: không vào S

    def test_sa1(self):
        T = self.T([div('a', 0, c_flag=True), div('b', 0, c_flag=True), div('b', 1)])
        self.assertTrue(T['a']['in_S']); self.assertFalse(T['a']['SA1'])                 # mọi divergence giữ lại mang cờ
        self.assertTrue(T['b']['SA1'])                                                   # còn một divergence không cờ

    def test_no_stderr(self):
        T = self.T([div('a', 0, channels=('stderr',)), div('b', 0, channels=('stderr',)), div('b', 0, channels=('stdout', 'stderr'))])
        self.assertFalse(T['a']['no_stderr']); self.assertTrue(T['b']['no_stderr'])

    def test_cap8(self):
        T = self.T([div('a', 0, cap=True), div('b', 0, cap=False)], caps=[div('c', 0), div('d', 0, stable=False)])
        self.assertFalse(T['a']['cap8']); self.assertTrue(T['b']['cap8']); self.assertTrue(T['c']['cap8']); self.assertFalse(T['d']['cap8'])

    def test_bnu_band(self):
        T = self.T([div('a', 0, out=(b'a  \n', b'a\n')), div('b', 0, out=(b'1\n', b'2\n')), div('c', 0, out=(b'x\nmenu\n', b'x\n'))])
        self.assertEqual((T['a']['NB_L'], T['a']['NB_U']), (False, False))           # B1
        self.assertEqual((T['b']['NB_L'], T['b']['NB_U']), (True, True))             # N3
        self.assertEqual((T['c']['NB_L'], T['c']['NB_U']), (False, True))            # U-residual

    def test_summary_denominators(self):
        S = M.summarize_rq1({k: t for k, t in build(self.cs, [div('a', 0)]).items()}, 'exe')['by_group']['all']
        self.assertEqual((S['P_test'], S['D_all'], S['P_complete'], S['D_complete']), (7, 1, 7, 1))

    def test_incomplete_layers(self):
        cs = [case(s, {'a': 'P_test'}, layers=('M', 'MS')) for s in (0, 1, 2)]
        T = build(cs, [div('a', 0)])
        self.assertFalse(T[('B01_x', 'c', 'a')]['complete_layers'])


class RQ2Summary(unittest.TestCase):
    def test_rff_parts(self):
        v = lambda diff: dict(orig=dict(diff=diff, result='VectorComparisonFailed'))
        recs = [dict(outcome='behavioral_agreement', vectors=[v('Stderr diff: x')]),
                dict(outcome='behavioral_agreement', vectors=[v('Stdout diff: x'), v('Stderr diff: y')]),
                dict(outcome='behavioral_disagreement', vectors=[]), dict(outcome='not_adjudicable', reasons=['ub_in_c'], vectors=[]),
                dict(outcome='not_re_examined', reasons=['incomplete_harness_run'], vectors=[])]
        S = M.summarize_rq2(recs)
        self.assertEqual((S['F'], S['A'], S['not_adjudicable'], S['R_test'], S['not_re_examined']), (2, 1, 1, 4, 1))
        self.assertEqual(S['ff_channels'], {'stderr': 1, 'stderr+stdout': 1})


if __name__ == '__main__':
    unittest.main()


class SanInfraAcrossSeeds(unittest.TestCase):
    """A1 (Le chọn 24/10): san_infra gộp qua ba seed."""
    def test_retained_in_other_seed_keeps_p_test(self):
        cs = [case(0, {'a': 'san_infra', 'b': 'san_infra'}), case(1, {'a': 'P_test', 'b': 'P_test'}), case(2, {'a': 'P_test', 'b': 'P_test'})]
        T = {k[2]: t for k, t in build(cs, [div('a', 1)]).items()}
        self.assertEqual(T['a']['status'], 'P_test'); self.assertTrue(T['a']['in_S'])
        self.assertEqual(T['b']['status'], 'san_infra')                                 # không seed nào có divergence giữ lại

    def test_other_leave_reasons_still_win(self):
        cs = [case(0, {'a': 'san_infra'}), case(1, {'a': 'incomplete'}), case(2, {'a': 'P_test'})]
        T = build(cs, [div('a', 2)])
        self.assertEqual(T[('B01_x', 'c', 'a')]['status'], 'incomplete')
