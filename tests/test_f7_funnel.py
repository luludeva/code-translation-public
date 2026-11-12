"""F7 (kế hoạch Chương 3, tính số liệu): survivorship trong bước tính số liệu. Mọi bản dịch của danh sách cặp đầu vào có mặt trong kết quả
metrics với P_test hoặc một mã rời P_test (c_build_failed, harness_error, missing_record); bộ đếm cấp bản dịch cho nhóm inconclusive;
div_stderr_only cho library; đếm trần output một phía. Bản ghi giả như tests/test_metrics.py, không cần corpus.
Chạy: python3 -m unittest tests.test_f7_funnel"""
import collections, json, os, tempfile, unittest
from unittest import mock

from harness import metrics as M
from harness import rq1
try:
    from tests.test_metrics import build, case, div
except ImportError:          # chạy bằng discover -s tests (thư mục tests là gốc import)
    from test_metrics import build, case, div


def lobs(result, out='x', err='', state=None):
    return dict(k1='reported', result=result, state_out=state or {'v': 1}, stdout=out, stderr=err, san_flag=False)


class CaseLevelLeave(unittest.TestCase):
    """Điểm 1: case C build lỗi và harness_error thành mã rời P_test, không biến mất."""

    def test_exe_c_build_failed_records_pair_status(self):
        pairs = [dict(system='a', harvest_case='c'), dict(system='b', harvest_case='c')]
        with mock.patch.object(rq1.BD, 'build_c_exe', return_value=dict(ok=False)), \
             mock.patch.object(rq1.BD, 'build_rust_exe', return_value=dict(ok=True)):
            r = rq1.rq1_exe_case('/b', 'B01_x', 'c', pairs, 0, dict(budget=1, afl_execs=0), 10, '/tmp/none/div/x.jsonl', 't')
        self.assertEqual(r['status'], 'c_build_failed'); self.assertEqual(r['pair_status'], {'a': 'c_build_failed', 'b': 'c_build_failed'})
        T = M.rq1_translations([dict(r, seed=s) for s in (0, 1, 2)], {}, {}, [0, 1, 2])
        self.assertEqual({k[2]: t['status'] for k, t in T.items()}, {'a': 'c_build_failed', 'b': 'c_build_failed'})
        S = M.summarize_rq1(T, 'exe')['by_group']['all']
        self.assertEqual((S['n_translations'], S['P_test'], S['leave']['c_build_failed']), (2, 0, 2)); self.assertTrue(S['funnel_ok'])

    def test_lib_c_build_failed_records_pair_status(self):
        with mock.patch.object(rq1.BD, 'build_lib_case', return_value=dict(runner_ok=False, c_ok=True)):
            r = rq1.rq1_lib_case('/b', 'B01_x', 'c', [dict(system='a', harvest_case='c')], 0, dict(n_inputs=1), 10, '/tmp/n/div/x.jsonl', 't')
        self.assertEqual((r['status'], r['pair_status']), ('c_build_failed', {'a': 'c_build_failed'}))

    def test_load_rq1_keeps_case_level_records(self):
        out = tempfile.mkdtemp(); recs = [dict(key='B01_x/c/s0', bundle='B01_x', case='c', seed=0, status='c_build_failed',
                                               pair_status={'a': 'c_build_failed'}),
                                          dict(key='B01_x/d/s0#error', bundle='B01_x', case='d', seed=0, status='harness_error'),
                                          dict(key='B01_x/e/s1', bundle='B01_x', case='e', seed=1, status='insensitive_other_seed')]
        open(f'{out}/rq1-exe.jsonl', 'w').write(''.join(json.dumps(r) + '\n' for r in recs))
        cases, _, _ = M.load_rq1(out, 'exe')
        self.assertEqual(sorted(r['status'] for r in cases), ['c_build_failed', 'harness_error'])

    def test_harness_error_resolved_by_rerun(self):
        err = dict(bundle='B01_x', case='c', seed=1, status='harness_error', pair_status={'a': 'harness_error'})
        T = build([case(0, {'a': 'P_test'}), err, case(1, {'a': 'P_test'}), case(2, {'a': 'P_test'})], [])
        self.assertEqual(T[('B01_x', 'c', 'a')]['status'], 'P_test')                  # bản chạy lại thành công thắng
        T = build([case(0, {'a': 'P_test'}), err, case(2, {'a': 'P_test'})], [])
        self.assertEqual(T[('B01_x', 'c', 'a')]['status'], 'harness_error')            # chưa chạy lại: rời P_test, không thành missing_seed

    def test_old_records_without_pair_status(self):
        old_exe = dict(bundle='B01_x', case='c', seed=0, status='c_build_failed', rust_build={'a': {'ok': True}, 'b': {'ok': False}})
        old_err = dict(bundle='B01_x', case='d', seed=0, status='harness_error')
        T = M.rq1_translations([old_exe, old_err], {}, {}, [0])
        self.assertEqual({k[1:]: t['status'] for k, t in T.items()}, {('c', 'a'): 'c_build_failed', ('c', 'b'): 'c_build_failed'})
        self.assertEqual(M.summarize_rq1(T, 'exe')['unattributed_case_records'], {'harness_error': 1})   # không gắn được: vẫn báo
        T = M.rq1_translations([old_exe, old_err], {}, {}, [0], expected=[('B01_x', 'd', 'x'), ('B01_x', 'd', 'y')])
        self.assertEqual(T[('B01_x', 'd', 'x')]['status'], 'harness_error'); self.assertEqual(T.meta['unattributed_case_records'], {})

    def test_leave_order(self):
        cs = [dict(bundle='B01_x', case='c', seed=0, status='c_build_failed', pair_status={'a': 'c_build_failed'}),
              case(1, {'a': 'rust_build_failed', 'b': 'rust_build_failed', 'c': 'P_test'}),
              dict(bundle='B01_x', case='c', seed=2, status='harness_error', pair_status={'b': 'harness_error', 'c': 'harness_error'})]
        st = {k[2]: t['status'] for k, t in build(cs, []).items()}
        self.assertEqual(st, {'a': 'c_build_failed', 'b': 'rust_build_failed', 'c': 'harness_error'})
        self.assertEqual(M.LEAVE_ORDER.index('no_input_fields'), 0)
        self.assertLess(M.LEAVE_ORDER.index('c_build_failed'), M.LEAVE_ORDER.index('rust_build_failed'))
        self.assertLess(M.LEAVE_ORDER.index('rust_build_failed'), M.LEAVE_ORDER.index('harness_error'))


class ExpectedPairs(unittest.TestCase):
    """Điểm 1: danh sách cặp mong đợi; bản dịch không có bản ghi nào mang mã missing_record."""

    def test_missing_record_and_funnel(self):
        exp = [dict(bundle='B01_x', tractor_case='c', system=s) for s in 'ab'] + [dict(bundle='B02_y', tractor_case='z', system='a')]
        cs = [case(s, {'a': 'P_test', 'q': 'P_test'}) for s in (0, 1, 2)]
        T = M.rq1_translations(cs, {}, {}, [0, 1, 2], expected=exp)
        st = {k: t['status'] for k, t in T.items()}
        self.assertEqual(st[('B01_x', 'c', 'b')], 'missing_record'); self.assertEqual(st[('B02_y', 'z', 'a')], 'missing_record')
        self.assertTrue(T[('B01_x', 'c', 'q')]['unexpected']); self.assertFalse(T[('B01_x', 'c', 'a')]['unexpected'])
        R = M.summarize_rq1(T, 'exe'); S = R['by_group']['all']
        self.assertEqual(R['expected'], 3)
        # D26 (Le quyết 25/10): bản 'q' ngoài danh sách không vào mẫu số, chỉ đếm ở n_unexpected (trước: n_translations 4, P_test 2)
        self.assertEqual((S['n_translations'], S['P_test'], S['leave']['missing_record'], S['n_unexpected']), (3, 1, 2, 1))
        self.assertTrue(S['funnel_ok']); self.assertEqual(R['by_group']['B02']['leave']['missing_record'], 1)

    def test_unknown_status_is_counted(self):
        S = M.summarize_rq1(build([case(s, {'a': 'weird'}) for s in (0, 1, 2)], []), 'exe')['by_group']['all']
        self.assertEqual(S['leave_other'], {'weird': 1}); self.assertTrue(S['funnel_ok'])


class Inconclusive(unittest.TestCase):
    """Điểm 2: bộ đếm cấp bản dịch cho nhóm inconclusive (decision-log 2026-10-23 khuya, finding 8)."""

    def test_group(self):
        cs = [case(s, {x: 'P_test' for x in 'abcde'}) for s in (0, 1, 2)]
        ds = [div('a', 0, san='inconclusive'),                                        # chỉ inconclusive: thuộc nhóm
              div('b', 0, san='inconclusive'), div('b', 1),                           # có divergence giữ lại: thuộc D, không thuộc nhóm
              div('c', 0, san='inconclusive', stable=False),                          # inconclusive không ổn định: không thuộc nhóm
              div('d', 2, san='inconclusive'), div('d', 0, stable=False)]             # trộn với không ổn định: thuộc nhóm
        T = {k[2]: t for k, t in build(cs, ds).items()}
        self.assertEqual({x: T[x]['inconclusive_only'] for x in 'abcde'}, dict(a=True, b=False, c=False, d=True, e=False))
        self.assertTrue(T['b']['inconclusive_any']); self.assertEqual(T['d']['n_div_inconclusive'], 1)
        S = M.summarize_rq1(build(cs, ds), 'exe')['by_group']['all']
        self.assertEqual((S['inconclusive_only'], S['inconclusive_any'], S['inconclusive_and_unstable_only'], S['D_all'],
                          S['D_with_inconclusive']), (2, 3, 1, 1, 3))


class StderrOnly(unittest.TestCase):
    """Điểm 3: div_stderr_only của library được đếm trong rq1_lib_case và đưa lên summary cho cả hai loại."""

    def run_lib(self, c, r):
        d = tempfile.mkdtemp(); vec = f'{d}/v0.json'; json.dump(dict(lib_state_in={'a': 1}, lib_state_out={}), open(vec, 'w'))
        div_p = f'{d}/out/div/B01_x__c__s0.jsonl'; os.makedirs(os.path.dirname(div_p))
        with mock.patch.object(rq1.BD, 'build_lib_case', return_value=dict(runner_ok=True, c_ok=True, library='x', runner_bin='/rb')), \
             mock.patch.object(rq1.BD, 'build_rust_lib', return_value=dict(ok=True, dir='/r')), \
             mock.patch.object(rq1.BD, 'lib_root', return_value='/root'), mock.patch.object(rq1.BD, 'asan_preload', return_value=None), \
             mock.patch.object(rq1, '_lib_inputs', return_value=([(vec, 'vector')], None, 1)), \
             mock.patch.object(rq1, '_rl', side_effect=lambda rb, root, p, t, rust, dump, **k: dict(r if rust else c)), \
             mock.patch.object(rq1, 'lib_san', return_value=dict(status='no_report', markers=[], attempts=1)):
            rec = rq1.rq1_lib_case(d, 'B01_x', 'c', [dict(system='a', harvest_case='c')], 0, dict(n_inputs=1), 10, div_p, 't')
        with open(div_p) as f: return rec, [json.loads(l) for l in f]

    def test_lib_counts_stderr_only(self):
        rec, ds = self.run_lib(lobs('Pass', err='e1'), lobs('Pass', err='e2'))
        self.assertEqual(rec['counts']['a']['div_stderr_only'], 1); self.assertEqual(ds[0]['channels'], ['stderr'])
        T = M.rq1_translations([dict(rec, seed=s) for s in (0, 1, 2)], {('B01_x', 'c', 'a', 0): [dict(ds[0], kind='lib')]}, {}, [0, 1, 2])
        S = M.summarize_rq1(T, 'lib')['by_group']['all']
        self.assertEqual((S['div_stderr_only'], S['n_stderr_only_retained'], S['D_all'], S['D_stderr_only'], S['no_stderr']), (3, 1, 1, 1, 0))

    def test_exe_summary(self):
        cs = [dict(case(s, {'a': 'P_test', 'b': 'P_test'}), counts={'a': {'div_stderr_only': 1}}) for s in (0, 1, 2)]
        S = M.summarize_rq1(build(cs, [div('a', 0, channels=('stderr',)), div('b', 0, channels=('stdout', 'stderr'))]), 'exe')['by_group']['all']
        self.assertEqual((S['div_stderr_only'], S['n_stderr_only_retained'], S['D_stderr_only'], S['D_all']), (3, 1, 1, 2))


class OneSidedCap(unittest.TestCase):
    """Điểm 4: số input một bên chạm trần output, bên kia không, theo bản dịch (gồm nhánh khớp theo luật NT)."""

    def test_obs_note_exe(self):
        cnt = collections.Counter()
        o = lambda st: dict(status=st)
        rq1.obs_note(cnt, 'exe', o('output_limit'), o('timeout'), True)          # hai bên NT, khớp theo prefix: một phía ở nhánh khớp
        rq1.obs_note(cnt, 'exe', o('exit'), o('output_limit'), False)
        rq1.obs_note(cnt, 'exe', o('output_limit'), o('output_limit'), True)
        rq1.obs_note(cnt, 'exe', o('exit'), o('exit'), True)
        self.assertEqual((cnt['cap_c_only'], cnt['cap_r_only'], cnt['cap_both'], cnt['cap_one_side_match']), (1, 1, 1, 1))

    def test_lib_case_match_branch(self):
        rec, ds = StderrOnly.run_lib(self, lobs('OutputLimit'), lobs('Timeout'))
        c = rec['counts']['a']
        self.assertEqual((c['match'], c['cap_c_only'], c['cap_one_side_match'], c['cap_hit_match']), (1, 1, 1, 1)); self.assertEqual(ds, [])

    def test_summary_translations(self):
        cs = [dict(case(s, {'a': 'P_test', 'b': 'P_test', 'c': 'P_test'}),
                   counts={'a': {'cap_c_only': 1}, 'b': {'cap_both': 2}, 'c': {'cap_r_only': s, 'cap_one_side_match': s}}) for s in (0, 1, 2)]
        S = M.summarize_rq1(build(cs, []), 'exe')['by_group']['all']
        self.assertEqual((S['cap_c_only'], S['cap_r_only'], S['cap_both'], S['cap_one_side_match'], S['cap_one_side_translations']),
                         (3, 3, 6, 3, 2))


if __name__ == '__main__':
    unittest.main()
