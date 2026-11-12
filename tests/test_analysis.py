"""harness/analysis.py: bảy nhóm số §3.6 mà metrics chưa tính, trên bản ghi tổng hợp nhỏ (không corpus, không chạy chương trình), và nối
vào writing/scripts/gen-rq-macros.py. Chạy: python3 -m unittest tests.test_analysis"""
import collections, gzip, importlib.util, io, json, math, os, struct, tempfile, unittest
from contextlib import redirect_stderr

from harness import analysis as AN
from harness import observe as OB
from harness import rq2 as HQ
from harness.record import blob

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, f'{ROOT}/writing/scripts/{fn}')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


G = _load('gen_rq_macros_an', 'gen-rq-macros.py')


def rj(p):
    with open(p) as f: return json.load(f)


def wjsonl(p, rows):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        for r in rows: f.write(json.dumps(r) + '\n')


# ------------------------------------------------------------------------------------------------------------------------------------
# bản ghi RQ1 tổng hợp
def exe_case(b, c, sd, lay, counts, ps, gen=None, ood=None, ins=False, status='done'):
    return dict(key=f'{b}/{c}/s{sd}', kind='exe', bundle=b, case=c, seed=sd, status=status, n_inputs=sum(lay.values()), input_insensitive=ins,
                gen=dict(n_by_layer=lay, n_gen_by_layer=gen or lay, n_out_of_domain=ood or {}), counts=counts, pair_status=ps)


def exe_div(b, c, sd, s, idx, layer, src, retained=True, stable=True, rerun=False, confirmed=False, r_to=False):
    return dict(key=f'{b}/{c}/s{sd}/{s}/{idx}', kind='exe', bundle=b, case=c, seed=sd, system=s, idx=idx, layer=layer, source=src,
                stable=stable, san='no_report', retained=retained, channels=['status'] if r_to else ['stdout'], timeout_rerun=rerun,
                timeout_confirmed=confirmed, c_to=False, r_to=r_to, c_rc=0, r_rc=None if r_to else 0, c_status='exit',
                r_status='timeout' if r_to else 'exit', c_out=blob(b'a\n'), r_out=blob(b'' if r_to else b'b\n'), c_err=blob(b''),
                r_err=blob(b''), c_ub=False, c_flag=False)


def obs_cnt(n): return dict(observed=n, match=n)


def exe_dir(d, inputs_files=True):
    A, B, C = ('B01_x', 'caseA'), ('B02_y', 'caseB'), ('B02_z', 'caseC')
    l0, l1 = dict(S=2, M=10, MS=5, A=3), dict(S=2, M=10, MS=6, A=2)
    cases = [exe_case(*A, 0, l0, dict(sysA=obs_cnt(20), sysB=obs_cnt(20)), dict(sysA='P_test', sysB='P_test'),
                      gen=dict(S=2, M=12, MS=5, A=4), ood=dict(M=2, A=1)),
             exe_case(*A, 1, l1, dict(sysA=obs_cnt(20), sysB=obs_cnt(15)), dict(sysA='P_test', sysB='incomplete')),
             exe_case(*B, 0, dict(S=4), dict(sysA=obs_cnt(4), sysC=dict(rust_build_failed=1)), dict(sysA='P_test', sysC='rust_build_failed'),
                      ins=True),
             dict(key='B02_z/caseC/s0', kind='exe', bundle='B02_z', case='caseC', seed=0, status='c_build_failed', pair_status=dict(sysA='c_build_failed')),
             dict(key='B02_z/caseC/s1', kind='exe', bundle='B02_z', case='caseC', seed=1, status='c_build_failed', pair_status=dict(sysA='c_build_failed'))]
    wjsonl(f'{d}/rq1-exe.jsonl', cases)
    wjsonl(f'{d}/div/B01_x__caseA__s0.jsonl', [exe_div(*A, 0, 'sysA', 3, 'M', 'random'), exe_div(*A, 0, 'sysA', 4, 'M', 'dict'),
                                               exe_div(*A, 0, 'sysA', 12, 'MS', 'random', retained=False, stable=False),
                                               exe_div(*A, 0, 'sysA', 18, 'A', 'afl', rerun=True, confirmed=True, r_to=True),
                                               exe_div(*A, 0, 'sysB', 5, 'M', 'random')])
    wjsonl(f'{d}/div/B01_x__caseA__s1.jsonl', [exe_div(*A, 1, 'sysA', 3, 'M', 'random')])
    wjsonl(f'{d}/div/B02_y__caseB__s0.jsonl', [exe_div(*B, 0, 'sysA', 1, 'S', 'seed')])
    if inputs_files:
        for sd, src in ((0, dict(seed=2, random=10, dict=3, syntax=2, afl=3)), (1, dict(seed=2, random=12, dict=2, syntax=2, afl=2))):
            p = f'{d}/inputs/B01_x__caseA__s{sd}.inputs.jsonl.gz'; os.makedirs(os.path.dirname(p), exist_ok=True)
            with gzip.open(p, 'wt') as f:
                i = 0
                for s, n in src.items():
                    for _ in range(n): f.write(json.dumps(dict(i=i, source=s)) + '\n'); i += 1
    expected = [('B01_x', 'caseA', 'sysA'), ('B01_x', 'caseA', 'sysB'), ('B02_y', 'caseB', 'sysA'), ('B02_y', 'caseB', 'sysC'),
                ('B02_z', 'caseC', 'sysA'), ('B02_y', 'caseB', 'sysD')]
    return expected


F64 = ('float', 'f64', 64)
FIELDS = dict(x=F64, arr=('vec', F64))


def lobs(state, nf=None, stdout='', stderr='', result='Pass', k1='reported'):
    return dict(k1=k1, result=result, rc=0, state_out=state, state_nonfinite=nf or [], stdout=stdout, stderr=stderr)


def lib_div(b, c, sd, s, idx, src, co, ro, ch):
    return dict(key=f'{b}/{c}/s{sd}/{s}/{idx}', kind='lib', bundle=b, case=c, seed=sd, system=s, idx=idx, source=src, c=co, r=ro, stable=True,
                san='no_report', retained=True, c_ub=False, c_flag=False, channels=ch, timeout_rerun=False, timeout_confirmed=False)


def lib_dir(d):
    b, c = 'B01_l', 'libA'
    rec = dict(key=f'{b}/{c}/s0', kind='lib', bundle=b, case=c, seed=0, status='done', n_inputs=10,
               n_by_source=dict(vector=2, random=6, dict=2), out_of_domain_by_source=dict(random=1),
               counts=dict(sysA=obs_cnt(9), sysB=obs_cnt(9)), pair_status=dict(sysA='P_test', sysB='P_test'))
    wjsonl(f'{d}/rq1-lib.jsonl', [rec])
    small = lambda x: dict(x=x, arr=[1.0])
    wjsonl(f'{d}/div/{b}__{c}__s0.jsonl', [
        lib_div(b, c, 0, 'sysA', 1, 'random', lobs(small(1e-3)), lobs(small(1.0005e-3)), ['state']),          # luật gốc: bằng (|d| <= 1e-6)
        lib_div(b, c, 0, 'sysA', 2, 'random', lobs(small(1.0), stdout='a'), lobs(small(1.0), stdout='b'), ['stdout']),
        lib_div(b, c, 0, 'sysA', 3, 'dict', lobs(dict(x=1.0, arr=[1e-3])), lobs(dict(x=1.0, arr=[1.0005e-3])), ['state']),   # mảng: chính xác
        lib_div(b, c, 0, 'sysB', 1, 'random', lobs(small(1e-3)), lobs(small(1.0005e-3)), ['state'])])


class RQ1Exe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); d = cls.tmp.name
        exp = exe_dir(d)
        cls.units, cls.cases, _ = AN.rq1_units(d, 'exe', [0, 1], exp)
        cls.d = d

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_div_by_layer_and_source(self):
        r = AN.div_by_input(self.units, 'exe')
        self.assertEqual((r['P_test'], r['D']), (2, 2))
        L = r['layers']
        self.assertEqual(L['M']['div_retained'], dict(num=3, den=20)); self.assertEqual(L['MS']['div_retained'], dict(num=0, den=11))
        self.assertEqual(L['MS']['div_all'], dict(num=1, den=11)); self.assertEqual(L['A']['div_retained'], dict(num=1, den=5))
        self.assertEqual(L['S']['div_retained'], dict(num=1, den=8)); self.assertEqual(L['generated']['div_retained'], dict(num=4, den=36))
        self.assertEqual(L['M']['inputs_retained'], dict(num=3, den=20)); self.assertEqual(L['S']['inputs_retained'], dict(num=1, den=8))
        self.assertEqual(L['M']['translations'], dict(num=1, den=2)); self.assertEqual(L['MS']['translations'], dict(num=0, den=2))
        # caseB không có file inputs: mẫu số theo nguồn null ở mọi nhóm có caseB; nhóm B01 có đủ
        self.assertIsNone(r['sources']['random']['div_retained']['den'])
        b01 = AN.div_by_input([u for u in self.units if u['bundle'] == 'B01_x'], 'exe')
        self.assertEqual(b01['sources']['random']['div_retained'], dict(num=2, den=22))
        self.assertEqual(b01['sources']['afl']['div_retained'], dict(num=1, den=5))

    def test_nt_one_side(self):
        r = AN.nt_one_side(self.units, 'exe')
        self.assertEqual(r['confirmed_retained'], dict(num=1, den=5)); self.assertEqual(r['confirmed_all'], dict(num=1, den=6))
        self.assertEqual(r['confirmed_retained_by_side']['r'], dict(num=1, den=1))
        self.assertEqual(r['translations_any'], dict(num=1, den=2)); self.assertEqual(r['translations_only'], dict(num=0, den=2))

    def test_nt_missing_field_is_null(self):
        u = [dict(x) for x in self.units]
        for x in u:
            if x['P_test']: x['divs'] = [{k: v for k, v in d.items() if k != 'timeout_confirmed'} for d in x['divs']]
        r = AN.nt_one_side(u, 'exe')
        self.assertIsNone(r['confirmed_retained']['num']); self.assertGreater(r['records_without_field'], 0)

    def test_attrition_inputs(self):
        r = AN.attrition_inputs(self.units)
        self.assertEqual((r['n_translations'], r['inputs_scheduled_known'], r['translations_inputs_unknown']), (6, 92, 1))
        c = r['codes']
        self.assertEqual(c['incomplete']['inputs_lost'], dict(num=5, den=92))
        self.assertEqual(c['rust_build_failed']['inputs_lost'], dict(num=4, den=92))
        self.assertEqual(c['missing_record']['inputs_lost'], dict(num=4, den=92))
        self.assertIsNone(c['c_build_failed']['inputs_lost']['num']); self.assertEqual(c['c_build_failed']['translations_inputs_unknown'], 1)
        self.assertEqual(c['P_test']['inputs_lost']['num'], 0); self.assertEqual(r['P_test_inputs_lost'], 0)
        self.assertEqual(sum(x['translations']['num'] for x in c.values()), 6)

    def test_insensitive_case_needs_one_seed(self):
        u = next(x for x in self.units if (x['case'], x['system']) == ('caseB', 'sysA'))
        self.assertEqual(u['need'], [0]); self.assertEqual(u['sched'], 4)

    def test_out_of_domain(self):
        r = AN.out_of_domain(self.cases, 'exe', [0, 1])['all']['_all']
        self.assertEqual(r['case_seeds'], 3)          # caseC không sinh input
        self.assertEqual(r['layers']['M'], dict(num=2, den=22)); self.assertEqual(r['layers']['A'], dict(num=1, den=6))
        self.assertEqual(r['layers']['generated'], dict(num=3, den=39)); self.assertEqual(r['layers']['S'], dict(num=0, den=8))
        self.assertNotIn('sysA', AN.out_of_domain(self.cases, 'exe', [0, 1])['all'])   # cấp case, chỉ theo nhóm

    def test_matches_metrics_funnel(self):
        from harness import metrics as HM
        cases, divs, caps = HM.load_rq1(self.d, 'exe')
        T = HM.rq1_translations(cases, divs, caps, [0, 1], exe_dir(self.d))
        s = HM.summarize_rq1(T, 'exe')['by_group']['all']
        r = AN.div_by_input(self.units, 'exe')
        self.assertEqual((s['P_test'], s['D_all'], s['n_div_retained']), (r['P_test'], r['D'], r['layers']['generated']['div_retained']['num']
                                                                          + r['layers']['S']['div_retained']['num']))
        self.assertEqual(AN.attrition_inputs(self.units)['n_translations'], s['n_translations'])


class RQ1Lib(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); lib_dir(self.tmp.name)
        self.units, self.cases, _ = AN.rq1_units(self.tmp.name, 'lib', [0])

    def tearDown(self): self.tmp.cleanup()

    def test_rob_float_components_and_D_is_null(self):
        r = AN.rq1_rob_float(self.units, lambda b, c: FIELDS)
        self.assertIsNone(r['exact']['D']['num']); self.assertIsNone(r['orig_float']['D']['num'])
        self.assertEqual(r['exact']['D']['den'], 2); self.assertFalse(r['orig_float']['computable'])
        self.assertEqual(r['orig_float']['removed_div'], dict(num=2, den=4))
        self.assertEqual(r['orig_float']['all_removed_translations'], dict(num=1, den=2))
        self.assertEqual(r['exact']['removed_div_by_comparison'], dict(num=0, den=4))

    def test_rob_float_without_types_is_null(self):
        r = AN.rq1_rob_float(self.units, lambda b, c: None)
        self.assertIsNone(r['orig_float']['removed_div']['num']); self.assertEqual(r['orig_float']['undecided_div'], 3)  # stdout: vẫn khác

    def test_lib_layers_subtract_out_of_domain(self):
        r = AN.div_by_input(self.units, 'lib')
        self.assertEqual(r['layers']['random']['div_retained'], dict(num=3, den=10))     # (6 - 1) x 2 bản dịch
        self.assertEqual(r['layers']['dict']['div_retained'], dict(num=1, den=4))
        self.assertEqual(r['layers']['generated']['div_retained'], dict(num=4, den=14))
        self.assertEqual(r['layers']['vector']['inputs_retained'], dict(num=0, den=2))
        o = AN.out_of_domain(self.cases, 'lib', [0])['all']['_all']['layers']
        self.assertEqual(o['random'], dict(num=1, den=6)); self.assertEqual(o['generated'], dict(num=1, den=8))


class FloatRules(unittest.TestCase):
    def test_approx_eq_matches_tractor_rule(self):
        self.assertTrue(AN.approx_eq(1e-3, 1.0005e-3, 64))         # |d| <= 1e-6
        self.assertFalse(AN.approx_eq(1e6, 1e6 + 0.5, 64))         # sai số tương đối 1e-6 thì bằng, oracle gốc thì khác
        self.assertTrue(OB.float_tol_equal(1e6, 1e6 + 0.5))
        self.assertTrue(AN.approx_eq(1e6, 1e6 + 1e-10, 64))        # trong epsilon máy tương đối
        nxt = struct.unpack('f', struct.pack('I', struct.unpack('I', struct.pack('f', 1000.0))[0] + 1))[0]
        self.assertTrue(AN.approx_eq(1000.0, nxt, 32)); self.assertFalse(AN.approx_eq(1000.0, nxt, 64))
        self.assertFalse(AN.approx_eq(float('nan'), float('nan'), 64))
        self.assertTrue(AN.approx_eq(math.inf, math.inf, 64)); self.assertFalse(AN.approx_eq(math.inf, -math.inf, 64))
        self.assertFalse(AN.approx_eq(math.inf, 1e308, 64))

    def test_state_orig(self):
        st = lambda **k: lobs(dict(dict(x=1.0, arr=[1.0]), **k))
        self.assertTrue(AN.state_orig(st(x=1e-3), st(x=1.0005e-3), FIELDS))
        self.assertFalse(AN.state_orig(st(arr=[1e-3]), st(arr=[1.0005e-3]), FIELDS))
        a, b = lobs(dict(x=None, arr=[1.0]), nf=['NaN']), lobs(dict(x=None, arr=[1.0]), nf=['NaN'])
        self.assertTrue(AN.state_tol(a, b)); self.assertFalse(AN.state_orig(a, b, FIELDS))     # NaN bằng NaN ở luật chính, khác ở luật gốc
        a, b = lobs(dict(x=None, arr=[1.0]), nf=['inf']), lobs(dict(x=None, arr=[1.0]), nf=['inf'])
        self.assertTrue(AN.state_orig(a, b, FIELDS))
        self.assertFalse(AN.state_orig(lobs(dict(x=None, arr=[1.0]), nf=['inf']), lobs(dict(x=None, arr=[1.0]), nf=['-inf']), FIELDS))
        with self.assertRaises(AN.Undecided): AN.state_orig(st(), st(), None)
        with self.assertRaises(AN.Undecided):
            AN.state_orig(lobs(dict(x=None, s='NaN'), nf=['NaN']), lobs(dict(x=None, s='NaN'), nf=['NaN']), dict(x=F64, s=('string',)))
        self.assertTrue(AN.state_exact(st(), st())); self.assertFalse(AN.state_exact(st(x=1.0), st(x=1.0 + 1e-12)))

    def test_lib_channels_equals_observe(self):
        base = [lobs(dict(x=1.0, arr=[1.0])), lobs(dict(x=1.0 + 1e-9, arr=[1.0])), lobs(dict(x=2.0, arr=[1.0])),
                lobs(dict(x=1.0, arr=[1.0]), stdout='o'), lobs(dict(x=1.0, arr=[1.0]), stderr='E\n'),
                lobs(dict(x=1.0, arr=[1.0]), result='VectorComparisonFailed'), lobs(None, result='Timeout'),
                lobs(dict(x=None, arr=[1.0]), nf=['NaN']), lobs(None, result='Panic'), dict(k1='infra', rc=None)]
        for a in base:
            for b in base:
                for cs in (False, True):
                    self.assertEqual(AN.lib_channels(a, b, AN.state_tol, cs), OB.channels_lib(a, b, cs), (a, b, cs))


# ------------------------------------------------------------------------------------------------------------------------------------
# RQ2
def eobs(out=b'x\n', err=b'', status='exit', rc=0):
    return dict(status=status, rc=rc, sig=None, out=out, err=err, secs=0.01)


def vec(c_list, r_list, kind, san='no_report', name='v1'):
    runs = [dict(rep=i, reran=False, first=dict(timeout=10, c=HQ.enc_obs(c, kind), r=HQ.enc_obs(r, kind)), rerun=None)
            for i, (c, r) in enumerate(zip(c_list, r_list))]
    v = dict(vector=name, obs=dict(runs=runs, san=dict(result=dict(status=san), attempts=[])), san=san, san_cause=None, runs=[{}] * len(runs))
    v['outcome'], v['reason'] = HQ.recompute_vector(v, kind)
    return v


def rec(vs, kind, b='B01_q', c='case1', s='sysA'):
    o, reasons = HQ.translation_outcome([(v['outcome'], v['reason']) for v in vs])
    return dict(key=f'{s}/{b}/{c}', kind=kind, bundle=b, case=c, system=s, outcome=o, reasons=reasons, vectors=vs)


class RQ2Rob(unittest.TestCase):
    def test_no_stderr_exe(self):
        v = vec([eobs(err=b'a')] * 3, [eobs(err=b'b')] * 3, 'exe')
        self.assertEqual(v['outcome'], 'supports_rejection')
        bad = vec([eobs(status='invalid_input')] * 3, [eobs(status='invalid_input')] * 3, 'exe', name='v2')
        recs = [rec([v], 'exe'), rec([vec([eobs(err=b'a')] * 3, [eobs(err=b'b')] * 3, 'exe'), bad], 'exe', s='sysB'),
                rec([v], 'exe', s='sysC'), rec([], 'exe', s='sysD')]
        recs[2]['vectors'] = [dict(recs[2]['vectors'][0], obs=None)]          # bản ghi trước F5: không có obs
        old = HQ._equal
        f = AN.rq2_rob(recs, 'exe')
        self.assertIs(HQ._equal, old)
        r = f(recs)
        self.assertEqual(r['R_test'], 3)                                      # sysD: not_re_examined, ngoài R_test
        self.assertEqual(r['primary_recompute'], dict(same=2, differs=0, uncomputable=1))
        ns = r['no_stderr']
        self.assertEqual(ns['uncomputable'], dict(no_obs=1)); self.assertIsNone(ns['F']['num']); self.assertFalse(ns['computable'])
        r2 = f(recs[:2])
        ns = r2['no_stderr']
        self.assertEqual(ns['F'], dict(num=1, den=2)); self.assertEqual(ns['not_re_examined'], dict(num=1, den=2))
        self.assertEqual(ns['transitions'], {'behavioral_disagreement->behavioral_agreement': 1,
                                             'behavioral_disagreement->not_re_examined': 1})
        self.assertEqual(ns['changed'], dict(num=2, den=2))

    def test_lib_exact_and_orig(self):
        tiny = lambda x: lobs(dict(x=x, arr=[1.0]))
        v1 = vec([tiny(1.0)] * 3, [tiny(1.0000001)] * 3, 'lib')                                    # sai số tương đối: khớp
        arr = lambda y: lobs(dict(x=1.0, arr=[y]))
        v2 = vec([arr(1.0)] * 3, [arr(1.0000001)] * 3, 'lib', name='v2')
        self.assertEqual((v1['outcome'], v2['outcome']), ('agrees', 'agrees'))
        recs = [rec([v1], 'lib'), rec([v2], 'lib', s='sysB')]
        f = AN.rq2_rob(recs, 'lib', lambda b, c: FIELDS)
        r = f(recs)
        self.assertEqual(r['F_primary'], 2)
        self.assertEqual(r['exact']['F'], dict(num=0, den=2)); self.assertEqual(r['exact']['A'], dict(num=2, den=2))
        self.assertEqual(r['orig_float']['F'], dict(num=1, den=2))           # trường đơn lẻ |d| <= 1e-6 khớp; mảng so chính xác
        self.assertEqual(r['no_stderr']['F'], dict(num=2, den=2))
        g = AN.by_gs(recs, f, lambda x: x['bundle'], lambda x: x['system'])
        self.assertEqual(g['B01']['sysB']['orig_float']['A'], dict(num=1, den=1))

    def test_lib_orig_undecided_and_restore(self):
        nan = lobs(dict(x=None, s='q'), nf=['NaN'])
        v = vec([nan] * 3, [nan] * 3, 'lib')
        recs = [rec([v], 'lib')]
        f = AN.rq2_rob(recs, 'lib', lambda b, c: dict(x=F64, s=('string',)))
        r = f(recs)
        self.assertEqual(r['orig_float']['uncomputable'], dict(ambiguous_nonfinite=1)); self.assertIsNone(r['orig_float']['F']['num'])
        f = AN.rq2_rob(recs, 'lib', lambda b, c: None)
        self.assertEqual(f(recs)['orig_float']['uncomputable'], dict(runner_types_unavailable=1))
        self.assertEqual(HQ._equal.__module__, 'harness.rq2')


# ------------------------------------------------------------------------------------------------------------------------------------
# non-reproduced decision
class NonRep(unittest.TestCase):
    def test_population_matches_gen_rq_macros_census(self):
        for pilot in (False, True):
            with redirect_stderr(io.StringIO()):
                cen, _ = G.census_counts(ROOT, pilot)
            for kind in ('exe', 'lib'):
                if cen.get(kind) is None: self.skipTest('thiếu census'); continue
                pop = AN.nonrep_population(kind, pilot=pilot)
                for (g, s), c in cen[kind].items():
                    sub = [p for p in pop if (g == 'all' or AN.group_of(p['bundle']) == g) and (s == '_all' or p['system'] == s)]
                    self.assertEqual(sum(p['path'] == 'accepted' for p in sub), c['pre_non_reproduced'], (kind, pilot, g, s))
                    self.assertEqual(sum(p['path'] == 'rejected' for p in sub), c['R_nonrep'], (kind, pilot, g, s))

    def test_groups_from_evidence(self):
        pop = [dict(bundle='B01_a', case='c1', system='s1', path='accepted'), dict(bundle='B01_a', case='c2', system='s1', path='accepted'),
               dict(bundle='B02_b', case='c3', system='s2', path='rejected')]
        with tempfile.TemporaryDirectory() as d:
            p = f'{d}/ev.jsonl'
            wjsonl(p, [dict(kind='exe', path='accepted', bundle='B01_a', case='c1', system='s1', group='translation', source='x.md:3'),
                       dict(kind='exe', path='rejected', bundle='B02_b', case='c3', system='s2', group='oracle_drift'),
                       dict(kind='lib', path='accepted', bundle='B09_z', case='c', system='s', group='unknown'),
                       dict(kind='exe', path='accepted', bundle='B05_q', case='c9', system='s9', group='unknown')])
            ev = AN.load_evidence(p, 'exe')
            f, unmatched = AN.nonrep_groups([dict(x) for x in pop], ev, 'missing')
            r = f([dict(x, group=ev.get((x['path'], x['bundle'], x['case'], x['system']), (None,))[0]) for x in pop])
            self.assertEqual(unmatched, ['accepted/B05_q/c9/s9'])
            self.assertFalse(r['accepted']['complete']); self.assertIsNone(r['accepted']['groups']['translation']['num'])
            self.assertEqual(r['accepted']['unclassified'], dict(num=1, den=2))
            self.assertTrue(r['rejected']['complete']); self.assertEqual(r['rejected']['groups']['oracle_drift'], dict(num=1, den=1))
            self.assertNotIn('translation', r['rejected']['groups'])
            f2, _ = AN.nonrep_groups(pop2 := [dict(x) for x in pop], ev, 'unknown')
            r2 = f2(pop2)
            self.assertEqual(r2['accepted']['groups']['translation'], dict(num=1, den=2)); self.assertEqual(r2['accepted']['groups']['unknown'], dict(num=1, den=2))
            f3, _ = AN.nonrep_groups(pop3 := [dict(x) for x in pop], None)
            self.assertIsNone(f3(pop3)['rejected']['groups']['unknown']['num'])
            wjsonl(p, [dict(kind='exe', path='rejected', bundle='B02_b', case='c3', system='s2', group='translation')])
            with self.assertRaises(ValueError): AN.load_evidence(p, 'exe')


# ------------------------------------------------------------------------------------------------------------------------------------
class CLI(unittest.TestCase):
    def test_cli_writes_json_and_guards_generated(self):
        with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
            exe_dir(f'{d}/rq1')
            AN.main(['--rq1', f'{d}/rq1', '--kind', 'exe', '--seeds', '0,1', '--out', f'{d}/a.json'])
            r = rj(f'{d}/a.json')
            self.assertEqual(r['kind'], 'exe'); self.assertFalse(r['meta']['pilot'])
            self.assertEqual(set(r['sections']) - {'nonrep_groups'}, {'div_by_input', 'out_of_domain', 'attrition_inputs', 'nt_one_side'})
            self.assertEqual(r['sections']['div_by_input']['B01']['sysA']['layers']['M']['div_retained'], dict(num=3, den=20))
            with self.assertRaises(SystemExit):
                AN.main(['--rq1', f'{d}/rq1', '--kind', 'exe', '--expect', 'pilot', '--out', f'{ROOT}/writing/generated/x.json'])
        self.assertFalse(os.path.exists(f'{ROOT}/writing/generated/x.json'))


class Macros(unittest.TestCase):
    """Nối vào gen-rq-macros.py: số của analysis-<kind>.json thành macro, ?? khi thiếu, bỏ khi lệch metrics."""
    FIX = f'{ROOT}/tests/fixtures/rq-macros'

    def doc(self, kind, delta=0):
        mt = rj(f'{self.FIX}/metrics.json')[f'rq1_{kind}']['by_group']
        L = {'M': dict(div_retained=dict(num=7, den=70), inputs_retained=dict(num=3, den=30), translations=dict(num=1, den=2))}
        sec = dict(div_by_input={g: {'_all': dict(P_test=v['P_test'] + delta, layers=L)} for g, v in mt.items()},
                   attrition_inputs={g: {'_all': dict(n_translations=v['n_translations'], translations_inputs_unknown=0)} for g, v in mt.items()},
                   nt_one_side={'all': {'_all': dict(confirmed_retained=dict(num=2, den=9))}})
        return dict(kind=kind, meta=dict(pilot=True), sections=sec)

    def run_macros(self, docs):
        with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
            for n in ('metrics.json', 'metrics-split.json'):
                with open(f'{d}/{n}', 'w') as f: json.dump(rj(f'{self.FIX}/{n}'), f)
            for k, v in docs.items():
                with open(f'{d}/analysis-{k}.json', 'w') as f: json.dump(v, f)
            D, fams, files, hroot = G.prepare(type('A', (), dict(indir=d, pilot=True, harness_root=ROOT, prefix='rq'))())
            return dict(G.build_macros(D, fams, 'rq')), D.warn

    def test_values_and_missing(self):
        m, warn = self.run_macros(dict(exe=self.doc('exe')))
        self.assertEqual(warn, [])
        self.assertEqual((m['rqDivLayerMExeAllNum'], m['rqDivLayerMExeAllDen'], m['rqDivLayerMExeAllPct']), ('7', '70', '10.0'))
        self.assertEqual(m['rqNtOneSideConfirmedExeAllNum'], '2')
        self.assertEqual(m['rqNtOneSideConfirmedExeBTwoNum'], '??')          # nhóm có trong metrics nhưng analysis không có mục
        self.assertEqual(m['rqDivLayerVectorLibAllNum'], '??')                # thiếu analysis-lib.json
        self.assertEqual(m['rqRobFFNoStderrExeAllNum'], '??'); self.assertEqual(m['rqRobExactLibAllNum'], '??')

    def test_mismatch_drops_rq1_sections(self):
        m, warn = self.run_macros(dict(exe=self.doc('exe', delta=1)))
        self.assertTrue(any('lệch metrics' in w for w in warn))
        self.assertEqual(m['rqDivLayerMExeAllNum'], '??')

    def test_pilot_analysis_requires_pilot_flag(self):
        with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
            with open(f'{d}/analysis-exe.json', 'w') as f: json.dump(self.doc('exe'), f)
            with self.assertRaises(SystemExit):
                G.prepare(type('A', (), dict(indir=d, pilot=False, harness_root=ROOT, prefix='rq'))())


if __name__ == '__main__':
    unittest.main()
