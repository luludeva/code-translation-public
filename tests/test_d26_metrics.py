"""D26 (Le quyết đêm 25/10), bước tính số liệu và gộp shard:
  1. F4: bộ đếm độ nhạy trần output lên summary kèm mẫu số (cap_hit_match, cap_hit_div, cap_sens_infra_match, cap_sens_infra_div,
     cap_sens_timeout_rerun, cap_hit_total); tính trên P_test và theo nhóm corpus; bản ghi cũ thiếu trường thì bằng 0, có ghi ở GAPS.
  2. F7: bản dịch `unexpected` ra khỏi mẫu số và mọi tử số; n_unexpected báo cạnh, không vào funnel_ok.
  3. F7: merge_shards không chặn harness_error của (case, seed) đã chạy lại thành công; vẫn chặn khi đó là bản ghi duy nhất.
Bản ghi giả, không cần corpus. Chạy: python3 -m unittest tests.test_d26_metrics"""
import json, os, tempfile, unittest

from harness import merge_shards as MS
from harness import metrics as M
try:
    from tests.test_metrics import build, case, div
except ImportError:          # chạy bằng discover -s tests (thư mục tests là gốc import)
    from test_metrics import build, case, div

NEW = ('cap_hit_div', 'cap_sens_infra_match', 'cap_sens_infra_div', 'cap_sens_timeout_rerun')


def ccase(seed, statuses, counts, bundle='B01_x', name='c'):
    r = case(seed, statuses, bundle=bundle, name=name); r['counts'] = counts; return r


class CapSensSummary(unittest.TestCase):
    """Điểm 1."""

    def test_counters_on_summary_with_denominator(self):
        k = dict(cap_hit_match=3, cap_hit_div=2, cap_sens_infra_match=1, cap_sens_infra_div=1, cap_sens_timeout_rerun=2, cap_sens_new_div=1)
        cs = [ccase(s, {'a': 'P_test', 'b': 'P_test'}, {'a': k, 'b': dict(cap_hit_div=1)}) for s in (0, 1, 2)]
        cs += [ccase(s, {'a': 'P_test', 'r': 'rust_build_failed'}, {'a': dict(cap_hit_match=1, cap_sens_timeout_rerun=1),
                                                                    'r': dict(cap_hit_match=50, cap_sens_infra_match=50)},
                     bundle='B02_y', name='z') for s in (0, 1, 2)]
        S = M.summarize_rq1(build(cs, []), 'exe')['by_group']
        a, b1, b2 = S['all'], S['B01'], S['B02']
        # B01: a cộng qua ba seed (3 lần k), b có cap_hit_div 1 mỗi seed
        self.assertEqual((b1['cap_hit_match'], b1['cap_hit_div'], b1['cap_sens_infra_match'], b1['cap_sens_infra_div'],
                          b1['cap_sens_timeout_rerun'], b1['cap_sens_new_div'], b1['cap_hit_total']), (9, 9, 3, 3, 6, 3, 18))
        # B02: bản rời P_test (r) không vào tử số
        self.assertEqual((b2['P_test'], b2['cap_hit_match'], b2['cap_sens_infra_match'], b2['cap_sens_timeout_rerun'], b2['cap_hit_total']),
                         (1, 3, 0, 3, 3))
        self.assertEqual((a['P_test'], a['cap_hit_match'], a['cap_hit_div'], a['cap_hit_total'], a['cap_sens_timeout_rerun']),
                         (3, 12, 9, 21, 9))

    def test_old_records_zero_and_gap(self):
        cs = [ccase(s, {'a': 'P_test'}, {'a': dict(cap_hit_match=2, cap_sens_new_div=1)}) for s in (0, 1, 2)]
        R = M.summarize_rq1(build(cs, []), 'lib'); S = R['by_group']['all']
        self.assertEqual([S[x] for x in NEW], [0, 0, 0, 0]); self.assertEqual(S['cap_hit_total'], 6)
        self.assertTrue(any('F4' in g and all(x in g for x in NEW) for g in R['gaps']))
        cs = [case(s, {'a': 'P_test'}) for s in (0, 1, 2)]                      # không có counts
        S = M.summarize_rq1(build(cs, []), 'exe')['by_group']['all']
        self.assertEqual([S[x] for x in NEW + ('cap_hit_total',)], [0] * 5)


class UnexpectedOutsideFunnel(unittest.TestCase):
    """Điểm 2."""

    def test_unexpected_excluded_everywhere(self):
        exp = [dict(bundle='B01_x', tractor_case='c', system='a')]
        cs = [ccase(s, {'a': 'P_test', 'q': 'P_test', 'w': 'rust_build_failed'},
                    {'a': dict(cap_hit_match=1), 'q': dict(cap_hit_match=100, cap_hit_div=100)}) for s in (0, 1, 2)]
        D = {('B01_x', 'c', 'q', 0): [div('q', 0)], ('B01_x', 'c', 'a', 1): [div('a', 1, stable=False)]}
        T = M.rq1_translations(cs, D, {}, [0, 1, 2], expected=exp)
        self.assertTrue(T[('B01_x', 'c', 'q')]['unexpected']); self.assertTrue(T[('B01_x', 'c', 'w')]['unexpected'])
        S = M.summarize_rq1(T, 'exe')['by_group']['all']
        self.assertEqual((S['n_translations'], S['P_test'], S['n_unexpected']), (1, 1, 2))
        self.assertEqual(S['leave']['rust_build_failed'], 0)                   # bản unexpected rời P_test cũng không vào phễu
        self.assertEqual((S['D_all'], S['unstable_only'], S['cap_hit_match'], S['cap_hit_div']), (0, 1, 3, 0))
        self.assertTrue(S['funnel_ok'])

    def test_group_with_only_unexpected(self):
        exp = [dict(bundle='B01_x', tractor_case='c', system='a')]
        cs = [case(s, {'a': 'P_test'}) for s in (0, 1, 2)] + [case(s, {'q': 'P_test'}, bundle='B02_y', name='z') for s in (0, 1, 2)]
        S = M.summarize_rq1(M.rq1_translations(cs, {}, {}, [0, 1, 2], expected=exp), 'exe')['by_group']
        self.assertEqual((S['B02']['n_translations'], S['B02']['P_test'], S['B02']['n_unexpected']), (0, 0, 1))
        self.assertTrue(S['B02']['funnel_ok']); self.assertEqual((S['all']['n_translations'], S['all']['n_unexpected']), (1, 1))

    def test_no_expected_no_change(self):
        S = M.summarize_rq1(build([case(s, {'a': 'P_test', 'q': 'P_test'}) for s in (0, 1, 2)], []), 'exe')['by_group']['all']
        self.assertEqual((S['n_translations'], S['P_test'], S['n_unexpected']), (2, 2, 0))


def shard(root, name, recs):
    d = os.path.join(root, name); os.makedirs(f'{d}/div')
    json.dump(dict(repo_commit='abc', params=dict(kind='exe', seeds=[0, 1, 2], timeout=10)), open(f'{d}/manifest.json', 'w'))
    open(f'{d}/rq1-exe.jsonl', 'w').write(''.join(json.dumps(r) + '\n' for r in recs))
    return d


def ok(c, s): return dict(key=f'B/{c}/s{s}', bundle='B', case=c, seed=s, status='done')
def err(c, s): return dict(key=f'B/{c}/s{s}#error', bundle='B', case=c, seed=s, status='harness_error')


class MergeHarnessError(unittest.TestCase):
    """Điểm 3."""

    def setUp(self):
        self.r = tempfile.mkdtemp(); self.exp = os.path.join(self.r, 'cases.txt'); open(self.exp, 'w').write('B/a\nB/b\n')

    def test_resolved_in_other_shard_not_blocking(self):
        a = shard(self.r, 's1', [ok('a', s) for s in (0, 1, 2)] + [err('b', 1)])
        b = shard(self.r, 's2', [ok('b', s) for s in (0, 1, 2)])
        rep = MS.merge('exe', [a, b], os.path.join(self.r, 'out'), self.exp)
        self.assertTrue(rep['ok'], rep['problems'])
        self.assertEqual((rep['n_harness_error_resolved'], rep['harness_error_resolved']), (1, ['B/b/s1#error']))
        self.assertEqual(rep['n_records'], 7)                                   # bản ghi harness_error vẫn được gộp, metrics chọn bản chạy lại

    def test_resolved_same_shard_and_key_only_records(self):
        a = shard(self.r, 's1', [dict(key='B/a/s0#error', status='harness_error'), dict(key='B/a/s0', status='done')])
        rep = MS.merge('exe', [a], os.path.join(self.r, 'out'))
        self.assertTrue(rep['ok'], rep['problems']); self.assertEqual(rep['n_harness_error_resolved'], 1)

    def test_only_record_still_blocks(self):
        a = shard(self.r, 's1', [ok('a', s) for s in (0, 1, 2)] + [ok('b', 0), ok('b', 2), err('b', 1), err('a', 9)])
        rep = MS.merge('exe', [a], os.path.join(self.r, 'out'), self.exp)
        p = ' '.join(rep['problems'])
        self.assertFalse(rep['ok']); self.assertIn('harness_error B/b/s1#error', p); self.assertIn('thiếu 1', p)
        self.assertIn('harness_error B/a/s9#error', p)                          # seed khác của cùng case không tính là chạy lại
        self.assertEqual(rep['n_harness_error_resolved'], 0)


if __name__ == '__main__':
    unittest.main()
