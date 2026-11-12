"""D1 đến D6 của exp 25 (F5, bộ chạy RQ2), cài theo Le chọn 25/10 (experiments/25-f5-rq2-audit/README.md mục 4).

D1: library, runner không trả report (k1 'infra' sau thử lại, kể cả quá hạn chót, rc None) là lần chạy không quan sát được: không chạy lại
    gấp mười, vector run_unobserved. observe.lib_timeout không đổi (RQ1 xét k1 'infra' trước nó).
D2: c_unstable (C đổi quan sát, Rust khác C ở mọi lần) tách khỏi unstable_comparison (phép so đổi giữa các lần).
D3: `reason` cấp bản dịch là mã đầu tiên theo thứ tự xét cố định; `reasons` giữ đủ; không còn 'multiple'.
D4: invalid_input (executable, argv có NUL) và vector_unreadable giữ nguyên.
D5: observe._run_lib giữ state_debug; bản ghi RQ2 nén khi dài; phép so không đổi.
D6: metrics.ff_channels tách state thành state_float, state_other; bộ đếm vector trượt có C kết thúc bằng exit 101 hoặc signal.
Chạy: python3 -m unittest tests.test_d26_rq2"""
import json, os, stat, tempfile, textwrap, unittest

from harness import metrics as M
from harness import observe as OB
from harness import rq2
from harness.config import TIMEOUT_RERUN_FACTOR

T0 = 10


def exe(status='exit', out=b'', err=b'', rc=0):
    return dict(status=status, rc=rc if status == 'exit' else None, sig=11 if status == 'signal' else None, to=status == 'timeout',
                out=out, err=err, secs=0.01)


def lib(result='VectorComparisonFailed', k1='reported', state=None, stdout='', stderr='', rc=0):
    return dict(k1=k1, result=result, rc=rc, state_out={'x': 1.0} if state is None else state, stdout=stdout, stderr=stderr, secs=0.01)


# Dạng _run_lib trả về khi runner quá hạn chót (deadline = timeout * 6 + 30): không có report, rc None.
DEADLINE = dict(rc=None, secs=90.0, k1='infra', infra_msg='runner process timeout')
NO_REPORT = dict(rc=1, secs=0.1, k1='infra', infra_msg='crash')


class Fake:
    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def __call__(self, t):
        self.calls.append(t); return self.fn(t, len(self.calls))


def san(status='no_report'):
    return lambda co: dict(status=status, markers=[], attempts=1)


def roundtrip(d):
    return json.loads(json.dumps(d, ensure_ascii=False, sort_keys=True))


def examine(c, r, kind='lib', st='no_report'):
    fc, fr = Fake(c), Fake(r)
    d, _ = rq2.examine_vector(fc, fr, san(st), kind, T0, san_sink=[])
    return d, fc, fr


class D1RunnerNoReport(unittest.TestCase):
    def test_deadline_not_budget_no_rerun(self):
        # Trước D1: Rust quá hạn chót ở timeout thường (lib_timeout đúng vì rc None), trả lời ở timeout gấp mười, khớp C -> 'agrees'.
        d, fc, fr = examine(lambda t, k: lib(), lambda t, k: dict(DEADLINE) if t == T0 else lib())
        self.assertEqual((d['outcome'], d['reason']), ('incomplete', 'run_unobserved'))
        self.assertEqual((fc.calls, fr.calls), ([T0] * rq2.REPS, [T0] * rq2.REPS))       # không có lần gấp TIMEOUT_RERUN_FACTOR
        self.assertTrue(all(not e['reran'] and e['unobserved'] for e in d['obs']['runs']))
        self.assertEqual(d['runs'][0]['channels'], ['run_unobserved'])
        self.assertEqual(rq2.recompute_vector(roundtrip(d), 'lib'), ('incomplete', 'run_unobserved'))

    def test_c_side_and_no_rc(self):
        for bad in (DEADLINE, NO_REPORT):
            d, fc, _ = examine(lambda t, k: dict(bad), lambda t, k: lib('Timeout'))
            self.assertEqual(d['reason'], 'run_unobserved'); self.assertNotIn(T0 * TIMEOUT_RERUN_FACTOR, fc.calls)

    def test_one_rep_unobserved_is_enough(self):
        d, _, _ = examine(lambda t, k: lib(), lambda t, k: dict(DEADLINE) if k == 2 else lib(state={'x': 2.0}))
        self.assertEqual(d['reason'], 'run_unobserved')
        self.assertEqual([e['reran'] for e in d['obs']['runs']], [False] * rq2.REPS)

    def test_real_budget_still_reruns(self):
        # Timeout của runner (có report) vẫn là vượt ngân sách một bên: chạy lại gấp mười như trước.
        d, fc, _ = examine(lambda t, k: lib(), lambda t, k: lib('Timeout', rc=0) if t == T0 else lib())
        self.assertEqual((d['outcome'], fc.calls.count(T0 * TIMEOUT_RERUN_FACTOR)), ('agrees', rq2.REPS))

    def test_rerun_unobserved(self):
        # Lần chạy lại gấp mười không có report: lần dùng để quyết định không quan sát được (như trước D1).
        d, _, _ = examine(lambda t, k: lib(), lambda t, k: lib('Timeout') if t == T0 else dict(DEADLINE))
        self.assertEqual(d['reason'], 'run_unobserved')

    def test_lib_timeout_unchanged(self):
        # Không đổi observe.lib_timeout (RQ1, checks dùng chung); RQ1 xét k1 'infra' trước hàm này (rq1.py nhánh library).
        self.assertTrue(OB.lib_timeout(DEADLINE)); self.assertFalse(OB.lib_timeout(NO_REPORT))

    def test_executable_unaffected(self):
        d, fc, _ = examine(lambda t, k: exe(out=b'1'), lambda t, k: exe('timeout') if t == T0 else exe(out=b'1'), kind='exe')
        self.assertEqual((d['outcome'], fc.calls.count(T0 * TIMEOUT_RERUN_FACTOR)), ('agrees', rq2.REPS))


class D2CUnstable(unittest.TestCase):
    def test_split(self):
        c_var = lambda t, k: exe(out=b'%d' % k)
        self.assertEqual(examine(c_var, lambda t, k: exe(out=b'x'), 'exe')[0]['reason'], 'c_unstable')
        # C ổn định, phép so đổi giữa các lần
        self.assertEqual(examine(lambda t, k: exe(out=b'1'), lambda t, k: exe(out=b'1' if k % 2 else b'2'), 'exe')[0]['reason'],
                         'unstable_comparison')
        # C đổi, Rust lúc khớp lúc khác: phép so đổi, không phải c_unstable
        self.assertEqual(examine(c_var, lambda t, k: exe(out=b'2'), 'exe')[0]['reason'], 'unstable_comparison')
        # C đổi, Rust đổi theo, khớp ở mọi lần: không phải không phân xử được
        self.assertEqual(examine(c_var, c_var, 'exe')[0]['outcome'], 'agrees')

    def test_inconclusive_and_library(self):
        d = examine(lambda t, k: exe(out=b'%d' % k), lambda t, k: exe(out=b'x'), 'exe', 'inconclusive')[0]
        self.assertEqual((d['reason'], d['c_stable']), ('c_unstable', False))
        d = examine(lambda t, k: lib(state={'x': float(k)}), lambda t, k: lib(state={'x': -1.0}))[0]
        self.assertEqual(d['reason'], 'c_unstable')

    def test_codes_registered(self):
        self.assertIn('c_unstable', rq2.VECTOR_REASONS['not_adjudicable'])
        self.assertIn('c_unstable', rq2.TRANSLATION_REASONS['not_adjudicable'])


class D3PrimaryReason(unittest.TestCase):
    def test_no_multiple(self):
        for codes in rq2.TRANSLATION_REASONS.values(): self.assertNotIn('multiple', codes)

    def test_order_constant_matches_vector_precedence(self):
        # Mỗi bước: điều kiện của mã đứng trước và mọi mã sau cùng đúng; vector_outcome trả mã đứng trước (thứ tự xét).
        bad, inf = lib(k1='invalid_input', result=None, state={}), dict(DEADLINE)
        ok, tmo = lib(), lib('Timeout')
        V = lambda runs, s, cause=None: rq2.vector_outcome([(c, r, False) for c, r in runs], s, 'lib', cause)[1]
        self.assertEqual(V([(bad, inf), (tmo, tmo), (ok, ok)], 'ub'), 'invalid_input')
        self.assertEqual(V([(ok, inf), (tmo, tmo), (ok, ok)], 'infra', 'c_san_build_failed'), 'run_unobserved')
        self.assertEqual(V([(tmo, tmo), (ok, ok), (ok, ok)], 'infra', 'c_san_build_failed'), 'san_build_failed')
        self.assertEqual(V([(tmo, tmo), (ok, ok), (ok, ok)], 'infra'), 'san_infra')
        self.assertEqual(V([(tmo, tmo), (ok, ok), (ok, ok)], 'ub'), 'ub_in_c')
        x2 = lib(state={'x': 2.0}); x3 = lib(state={'x': 3.0})
        self.assertEqual(V([(tmo, tmo), (ok, x2), (x3, x2)], 'inconclusive'), 'both_budget')
        self.assertEqual(V([(ok, x2)] * 3, 'inconclusive'), 'sanitizer_inconclusive')
        self.assertEqual(V([(ok, x2), (x3, x2), (ok, x2)], 'inconclusive'), 'c_unstable')
        self.assertEqual(V([(ok, x2), (ok, ok), (ok, x2)], 'no_report'), 'unstable_comparison')
        self.assertEqual(rq2.VECTOR_REASON_ORDER,
                         ('vector_unreadable', 'invalid_input', 'run_unobserved', 'san_build_failed', 'san_infra', 'ub_in_c',
                          'both_budget', 'sanitizer_inconclusive', 'c_unstable', 'unstable_comparison'))

    def test_translation_priority(self):
        P = rq2.primary_reason
        self.assertEqual(P('not_adjudicable', ['unstable_comparison', 'both_budget', 'ub_in_c']), 'ub_in_c')
        self.assertEqual(P('not_adjudicable', ['unstable_comparison', 'c_unstable']), 'c_unstable')
        self.assertEqual(P('not_adjudicable', ['sanitizer_inconclusive', 'both_budget']), 'both_budget')
        self.assertEqual(P('not_re_examined', ['incomplete_harness_run:san_infra', 'incomplete_harness_run:vector_unreadable']),
                         'incomplete_harness_run:vector_unreadable')
        self.assertEqual(P('not_re_examined', ['incomplete_harness_run:san_infra', 'incomplete_harness_run:run_unobserved']),
                         'incomplete_harness_run:run_unobserved')
        self.assertEqual(P('not_re_examined', ['incomplete_harness_run']), 'incomplete_harness_run')    # mã trước F5: giữ nguyên
        self.assertIsNone(P('behavioral_agreement', []))

    def test_record_keeps_all_reasons(self):
        o, rs = rq2.translation_outcome([('not_adjudicable', 'unstable_comparison'), ('not_adjudicable', 'ub_in_c'), ('agrees', None)])
        rec = rq2._done({}, o, rs)
        self.assertEqual((rec['reason'], rec['reasons']), ('ub_in_c', ['ub_in_c', 'unstable_comparison']))

    def test_summary_recomputes_multiple(self):
        recs = [dict(outcome='not_adjudicable', reasons=['both_budget', 'ub_in_c'], reason='multiple', vectors=[]),
                dict(outcome='not_adjudicable', reasons=['c_unstable', 'unstable_comparison'], vectors=[]),
                dict(outcome='not_re_examined', reasons=['incomplete_harness_run:san_infra', 'incomplete_harness_run:invalid_input'],
                     vectors=[])]
        S = M.summarize_rq2(recs)
        self.assertEqual(S['translation_reason'], {'not_adjudicable:ub_in_c': 1, 'not_adjudicable:c_unstable': 1,
                                                   'not_re_examined:incomplete_harness_run:invalid_input': 1})
        self.assertEqual(S['not_adjudicable_reasons'], {'both_budget': 1, 'ub_in_c': 1, 'c_unstable': 1, 'unstable_comparison': 1})


class D4Unchanged(unittest.TestCase):
    def test_codes(self):
        bad = lambda t, k: exe('invalid_input', err=b'embedded null byte')
        self.assertEqual(examine(bad, bad, 'exe')[0]['reason'], 'invalid_input')
        v = rq2.unreadable_vector('1.json', dict(orig={}))
        self.assertEqual((v['outcome'], v['reason']), ('incomplete', 'vector_unreadable'))


FAKE_RUNNER = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    a = sys.argv[1:]
    json.dump({'v0': {'result': 'VectorComparisonFailed'}}, open(a[a.index('--output') + 1], 'w'))
    line = dict(note='v0', state_out={'o': None, 'x': None}, stdout='', stderr='', state_debug=os.environ['DBG'])
    open(os.environ['CANDO2_STATE_DUMP'], 'a').write(json.dumps(line) + '\\n')
''')


class D5StateDebug(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix='d26-')
        cls.runner = os.path.join(cls.d, 'fake_runner'); open(cls.runner, 'w').write(FAKE_RUNNER)
        os.chmod(cls.runner, os.stat(cls.runner).st_mode | stat.S_IEXEC)
        cls.vec = os.path.join(cls.d, 'v.json'); json.dump({'lib_state_in': {}, 'lib_state_out': {}}, open(cls.vec, 'w'))

    def run1(self, dbg):
        return OB.run_lib(self.runner, self.d, self.vec, 10, False, os.path.join(self.d, 'x.dump'), extra_env=dict(DBG=dbg))

    def test_run_lib_keeps_state_debug(self):
        # Optional None và trường đơn lẻ NaN cùng là null trong state_out; chuỗi Debug phân biệt được.
        a, b = self.run1('S { o: None, x: NaN }'), self.run1('S { o: Some(NaN), x: NaN }')
        self.assertEqual((a['state_debug'], a['state_nonfinite']), ('S { o: None, x: NaN }', ['NaN']))
        self.assertEqual(a['state_out'], b['state_out'])
        self.assertNotEqual(a['state_nonfinite'], b['state_nonfinite'])        # phép so hiện hành (không đổi D)

    def test_comparison_ignores_state_debug(self):
        a, b = lib(), lib()
        a['state_debug'], b['state_debug'] = 'S { o: None }', 'S { o: Some(0.0) }'
        self.assertTrue(OB.equal_lib(a, b)); self.assertTrue(OB.equal_lib(a, b, completed_same=True))

    def test_rq2_record_inline_or_blob(self):
        short, long_ = 'S { x: 1.0 }', 'S { v: [' + '1.0, ' * 2000 + '] }'
        for dbg, blobbed in ((short, False), (long_, True)):
            o = dict(lib(), state_debug=dbg)
            e = roundtrip(rq2.enc_obs(o, 'lib'))
            self.assertEqual(isinstance(e['state_debug'], dict), blobbed)
            self.assertEqual(rq2.dec_obs(e, 'lib')['state_debug'], dbg)

    def test_examine_vector_keeps_and_recomputes(self):
        dbg = 'S { v: [' + '2.5, ' * 2000 + '] }'
        d, _, _ = examine(lambda t, k: dict(lib(), state_debug=dbg), lambda t, k: dict(lib(state={'x': 2.0}), state_debug=dbg))
        d = roundtrip(d)
        self.assertEqual(rq2.dec_obs(d['obs']['runs'][0]['first']['c'], 'lib')['state_debug'], dbg)
        self.assertEqual(rq2.recompute_vector(d, 'lib'), (d['outcome'], d['reason']))


def sm(exp, got):
    return f'Library State Mismatch. Expected:\n{json.dumps(exp)}\nGot:\n{json.dumps(got)}'


class D6Channels(unittest.TestCase):
    def ff(self, *orig):
        return M.ff_channels([dict(orig=o) for o in orig])

    def test_state_split(self):
        self.assertEqual(M.state_channel(dict(diff=sm({'t': {'a': 1, 'f': 0.5}}, {'t': {'a': 1, 'f': 0.5000001}}))), 'state_float')
        self.assertEqual(M.state_channel(dict(diff=sm({'a': 1, 'f': 0.5}, {'a': 2, 'f': 0.6}))), 'state_other')       # có số nguyên
        self.assertEqual(M.state_channel(dict(diff=sm({'v': [1.0, 2.0]}, {'v': [1.0, 2.5]}))), 'state_float')
        self.assertEqual(M.state_channel(dict(diff=sm({'v': [1.0]}, {'v': [1.0, 2.0]}))), 'state_other')               # cấu trúc
        self.assertEqual(M.state_channel(dict(diff=sm({'f': None}, {'f': 1.5}))), 'state_other')                        # null
        self.assertEqual(M.state_channel(dict(diff=sm({'b': True}, {'b': False}))), 'state_other')

    def test_truncated_diff_uses_full_or_falls_back(self):
        full = sm({'v': [0.1] * 100}, {'v': [0.1] * 99 + [0.2]})
        self.assertEqual(M.state_channel(dict(diff=full[:300])), 'state')                     # bản ghi trước D6: không giải mã được
        self.assertEqual(M.state_channel(dict(diff=full[:300], state_diff=full)), 'state_float')
        o = rq2._orig(dict(result='VectorComparisonFailed', diff=full))
        self.assertEqual((len(o['diff']), o['state_diff']), (300, full))
        self.assertNotIn('state_diff', rq2._orig(dict(result='VectorComparisonFailed', diff='Stdout diff: x')))

    def test_ff_channels(self):
        f = dict(result='VectorComparisonFailed', diff=sm({'f': 1.0}, {'f': 1.1}))
        g = dict(result='VectorComparisonFailed', diff=sm({'i': 1}, {'i': 2}))
        self.assertEqual(self.ff(f, dict(diff='Stderr diff: x')), 'state_float+stderr')
        self.assertEqual(self.ff(f, g), 'state_float+state_other')
        self.assertEqual(self.ff(dict(result='Panic', diff='')), 'result:Panic')

    def test_c_termination_counter(self):
        run = lambda st, rc=None: dict(c_status=st, c_rc=rc, r_status='exit', r_rc=0, reran=False, channels=[])
        lrun = lambda res: dict(c_result=['reported', res], r_result=['reported', 'Pass'], reran=False, channels=[])
        recs = [dict(outcome='behavioral_agreement', vectors=[dict(runs=[run('exit', 101)] * 3), dict(runs=[run('signal')] * 3),
                                                              dict(runs=[run('exit', 1)] * 3)]),
                dict(outcome='behavioral_disagreement', vectors=[dict(runs=[run('signal'), run('exit', 101), run('signal')])]),
                dict(outcome='not_re_examined', vectors=[dict(runs=[], outcome='incomplete', reason='vector_unreadable')]),
                dict(outcome='behavioral_agreement', vectors=[dict(runs=[lrun('SegmentationFault')] * 3), dict(runs=[lrun('Panic')] * 3),
                                                              dict(runs=[lrun('VectorComparisonFailed')] * 3)])]
        S = M.summarize_rq2(recs)
        self.assertEqual(S['c_term_vectors'], dict(n_vectors=7, any=5, exit_101=3, signal=3))
        self.assertEqual(S['c_term_vectors_ff'], dict(n_vectors=6, any=4, exit_101=2, signal=2))


if __name__ == '__main__':
    unittest.main()
