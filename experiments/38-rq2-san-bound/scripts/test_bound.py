"""Kiểm cho exp 38 (bound.py). Chạy từ thư mục exp 38:
  BOUND_RQ2_EXE=<rq2-exe.jsonl> BOUND_REPO=<repo> python3 -m unittest scripts/test_bound.py -v
Mặc định BOUND_REPO là gốc repo chứa thư mục exp này; BOUND_RQ2_EXE bắt buộc (bản ghi RQ2 không commit ở nhánh chính)."""
import collections, importlib.util, json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('BOUND_REPO') or os.path.join(HERE, '..', '..', '..'))
RQ2_EXE = os.environ.get('BOUND_RQ2_EXE')

spec = importlib.util.spec_from_file_location('bound', os.path.join(HERE, 'bound.py'))
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)


@unittest.skipUnless(RQ2_EXE and os.path.exists(RQ2_EXE), 'đặt BOUND_RQ2_EXE tới rq2-exe.jsonl')
class TestBound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rq2 = B.load_rq2(REPO)
        with open(RQ2_EXE) as f: cls.recs = [json.loads(l) for l in f]
        cls.targets = [r for r in cls.recs if B.is_target(r)]

    def test_recompute_matches_stored(self):
        v = B.validate(self.rq2, self.recs)
        self.assertEqual(v['vector_mismatches'], 0, v['vector_mismatch_list'])
        self.assertEqual(v['translation_mismatches'], 0, v['translation_mismatch_list'])
        self.assertEqual(v['translations_recomputed'] + v['translations_without_vectors'], len(self.recs))

    def test_targets_are_san_build_failed_only(self):
        self.assertTrue(self.targets)
        for r in self.targets:
            inc = [x for x in r['vectors'] if x['outcome'] == 'incomplete']
            self.assertTrue(inc and all(B.is_sbf(x) for x in inc), r['key'])
            self.assertTrue(all(x.get('san_cause') == 'c_san_build_failed' for x in inc), r['key'])

    def test_F_zero_every_scenario(self):
        sc, _, _ = B.scenarios(self.rq2, self.recs, self.targets)
        for s in B.SCENARIOS + B.EXTRA:
            self.assertEqual(sc[s]['F_targets'], 0, s)
            self.assertEqual(sc[s]['F_R_run'], 0, s)

    def test_no_behavioral_agreement(self):
        for r in self.targets:
            for s in B.SCENARIOS + B.EXTRA:
                o, _, _ = B.outcome_under(self.rq2, r, s)
                self.assertNotEqual(o, 'behavioral_agreement', (r['key'], s))

    def test_scenario_partition(self):
        """Mỗi kịch bản dồn cả tập vào đúng một outcome (dữ liệu hiện tại); cờ cho người đọc nếu dữ liệu đổi."""
        sc, _, _ = B.scenarios(self.rq2, self.recs, self.targets)
        n = len(self.targets)
        self.assertEqual(sc['no_report']['translation_outcomes'], {'behavioral_disagreement': n})
        self.assertEqual(sc['ub']['translation_outcomes'], {'not_adjudicable': n})
        self.assertEqual(sc['inconclusive']['translation_outcomes'], {'not_adjudicable': n})

    def test_rq3_k_full_reproduces_s0(self):
        t = B.rq3(self.rq2, REPO, f'{REPO}/experiments/30-main-s0/results', self.recs, self.targets)
        self.assertTrue(all(c['ok'] for c in t['checks']), [c for c in t['checks'] if not c['ok']])
        for sy, tab in t['tables'].items():
            self.assertTrue(tab['k36_reproduces_base'], sy)
            # k (amendment §9) gồm not_adjudicable và not_re_examined: ub, inconclusive, infra cho cùng A, F ở mọi k
            self.assertTrue(all(x['ub_vs_inconclusive_same'] and x['ub_vs_infra_same_AF'] for x in tab['rows']), sy)
            ups = [x['upper_num'] for x in tab['rows']]
            self.assertEqual(ups, list(range(ups[0], ups[0] + len(ups))), sy)   # mỗi bản chuyển từ A sang L_R cộng 1 vào cận trên


if __name__ == '__main__':
    unittest.main()
