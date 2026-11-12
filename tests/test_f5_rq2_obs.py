"""F5 (bộ chạy RQ2, 2026-10-25): bản ghi giữ quan sát đầy đủ của mọi lần chạy, và mã lý do tách cho vector không có kết quả.

(1) Bản ghi `obs` của examine_vector: mọi lần chạy C và Rust ở cả REPS lần, quan sát lần đầu và lần chạy lại gấp mười, các lần thử
    sanitizer; output qua record.blob như RQ1. Tính lại kết quả chỉ từ bản ghi (recompute_vector) cho đúng kết quả đã ghi, sau một vòng
    tuần tự hoá JSON như Store.put.
(2) Mỗi kết quả cấp vector khác supports_rejection, agrees mang đúng một mã thuộc VECTOR_REASONS; mỗi kết quả cấp bản dịch khác hai
    kết quả phân xử được mang đúng một mã `reason` thuộc TRANSLATION_REASONS. Lỗi runner, sanitizer không build, sanitizer lỗi hạ tầng,
    runner từ chối vector và vector rỗng có mã riêng.
"""
import itertools, json, unittest
from unittest import mock

from harness import metrics as M
from harness import observe as OB
from harness import rq1, rq2
from harness.config import TIMEOUT_RERUN_FACTOR

T0 = 10


def exe(status='exit', out=b'', err=b'', rc=0):
    return dict(status=status, rc=rc if status == 'exit' else None, sig=None, to=status == 'timeout', out=out, err=err, secs=0.01)


def lib(result='VectorComparisonFailed', k1='reported', state=None, stdout='', stderr='', nonfinite=None):
    o = dict(k1=k1, result=result, rc=0, state_out={'x': 1.0} if state is None else state, stdout=stdout, stderr=stderr, secs=0.01)
    if nonfinite is not None: o['state_nonfinite'] = nonfinite
    return o


class Fake:
    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def __call__(self, t):
        self.calls.append(t); return self.fn(t, len(self.calls))


def san(status='no_report', cause=None, sink_obs=None):
    """san_fn giả: ghi một lần thử vào sink như rq1._exe_san (tham số sink)."""
    sink = []
    def f(co):
        if sink_obs is not None: sink.append(dict(attempt=1, san_status='no_report', markers=[], status=status, obs=sink_obs))
        d = dict(status=status, markers=[], attempts=1)
        if cause: d['cause'] = cause
        return d
    return f, sink


def roundtrip(d):
    return json.loads(json.dumps(d, ensure_ascii=False, sort_keys=True))


class FullObservations(unittest.TestCase):
    def test_exe_every_run_and_rerun_kept(self):
        # Rust vượt ngân sách ở timeout thường, dừng ở timeout gấp mười: mọi lần đều chạy lại; quan sát lần đầu vẫn có trong bản ghi.
        rc = Fake(lambda t, k: exe(out=b'7\n', err=b'c-err %d\n' % k))
        rr = Fake(lambda t, k: exe('timeout', out=b'partial') if t == T0 else exe(out=b'7\n', err=b'c-err %d\n' % k))
        sf, sink = san(sink_obs=exe(err=b'san stderr\n'))
        d, _ = rq2.examine_vector(rc, rr, sf, 'exe', T0, san_sink=sink)
        d = roundtrip(d)
        runs = d['obs']['runs']
        self.assertEqual(len(runs), rq2.REPS)
        for e in runs:
            self.assertTrue(e['reran'])
            self.assertEqual((e['first']['timeout'], e['rerun']['timeout']), (T0, T0 * TIMEOUT_RERUN_FACTOR))
            self.assertEqual(e['first']['r']['status'], 'timeout')
            self.assertEqual(rq2.dec_obs(e['first']['r'], 'exe')['out'], b'partial')
            self.assertEqual(rq2.dec_obs(e['rerun']['c'], 'exe')['out'], b'7\n')
            self.assertIn('sha256', e['rerun']['c']['err'])
        self.assertEqual(len(rc.calls), 2 * rq2.REPS)                                # mọi lần gọi đều có trong bản ghi
        self.assertEqual(rq2.dec_obs(d['obs']['san']['attempts'][0]['obs'], 'exe')['err'], b'san stderr\n')
        self.assertEqual(d['obs']['san']['result']['status'], 'no_report')

    def test_lib_fields_for_reanalysis(self):
        # decision-log 2026-10-23 (ghi 2026-10-25): result, state_out, giá trị không hữu hạn, stdout, stderr của từng lần chạy.
        c = Fake(lambda t, k: lib(state={'x': 1.0, 'v': None}, stdout='out ✓', stderr=f'e{k}', nonfinite=['NaN']))
        r = Fake(lambda t, k: lib(state={'x': 1.0000001, 'v': None}, stdout='out ✓', stderr=f'e{k}', nonfinite=['inf']))
        sf, sink = san()
        d, _ = rq2.examine_vector(c, r, sf, 'lib', T0, san_sink=sink)
        d = roundtrip(d)
        for k, e in enumerate(d['obs']['runs'], 1):
            self.assertIsNone(e['rerun'])
            co, ro = rq2.dec_obs(e['first']['c'], 'lib'), rq2.dec_obs(e['first']['r'], 'lib')
            self.assertEqual((co['result'], co['k1'], co['state_out'], co['state_nonfinite'], co['stdout'], co['stderr']),
                             ('VectorComparisonFailed', 'reported', {'x': 1.0, 'v': None}, ['NaN'], 'out ✓', f'e{k}'))
            self.assertEqual(ro['state_out']['x'], 1.0000001)                          # giá trị gốc, để so chính xác khi tính lại
            self.assertEqual(ro['state_nonfinite'], ['inf'])

    def test_lib_none_stream_roundtrip(self):
        o = dict(k1='reported', result='Timeout', rc=None, stdout=None)
        self.assertEqual(rq2.dec_obs(roundtrip(rq2.enc_obs(o, 'lib')), 'lib'), o)

    def test_recompute_matches_recorded(self):
        """Tính lại từ bản ghi (sau JSON) cho cùng (outcome, reason) trên một lưới tình huống, cả hai loại."""
        exe_sides = [lambda t, k: exe(out=b'1\n'), lambda t, k: exe(out=b'2\n'), lambda t, k: exe(out=b'%d' % k),
                     lambda t, k: exe('timeout', out=b'1\n'), lambda t, k: exe('timeout') if t == T0 else exe(out=b'1\n'),
                     lambda t, k: exe('invalid_input'), lambda t, k: exe('signal'), lambda t, k: exe(err=b'x')]
        lib_sides = [lambda t, k: lib(), lambda t, k: lib(state={'x': 2.0}), lambda t, k: lib('Timeout'),
                     lambda t, k: lib(k1='infra', result=None), lambda t, k: lib(k1='invalid_input', result=None, state={}),
                     lambda t, k: lib(stderr=str(k % 2)), lambda t, k: lib('MemLimit') if t == T0 else lib()]
        n = 0
        for kind, sides in (('exe', exe_sides), ('lib', lib_sides)):
            for fc, fr in itertools.product(sides, sides):
                for st in ('no_report', 'inconclusive', 'ub', 'infra'):
                    sf, sink = san(st)
                    d, _ = rq2.examine_vector(Fake(fc), Fake(fr), sf, kind, T0, san_sink=sink)
                    self.assertEqual(rq2.recompute_vector(roundtrip(d), kind), (d['outcome'], d['reason']))
                    n += 1
        self.assertEqual(n, (len(exe_sides) ** 2 + len(lib_sides) ** 2) * 4)


class SanitizerSink(unittest.TestCase):
    def test_exe_san_records_each_attempt(self):
        # C-san chết không có báo cáo, C thường không chết: lỗi hạ tầng, thử SAN_ATTEMPTS lần; mỗi lần có trong sink.
        so = dict(status='signal', rc=None, sig=11, to=False, out=b'', err=b'', secs=0.0)
        sink = []
        with mock.patch.object(OB, 'run_exe', return_value=so):
            s = rq1._exe_san(dict(ok=True, bin='/bin/true'), [], b'', 1, None, 'exit', sink=sink)
        self.assertEqual((s['status'], s['attempts'], len(sink)), ('infra', rq1.SAN_ATTEMPTS, rq1.SAN_ATTEMPTS))
        self.assertEqual(sink[0]['obs']['sig'], 11)

    def test_exe_san_default_unchanged(self):
        so = dict(status='exit', rc=0, sig=None, to=False, out=b'', err=b'', secs=0.0)
        with mock.patch.object(OB, 'run_exe', return_value=so):
            self.assertEqual(rq1._exe_san(dict(ok=True, bin='/bin/true'), [], b'', 1, None, 'exit')['status'], 'no_report')

    def test_lib_san_records_streams(self):
        so = dict(k1='reported', result='Pass', rc=0, state_out={}, stdout='', stderr='hello\n')
        sink = []
        with mock.patch.object(OB, 'run_lib', return_value=so):
            s = rq1.lib_san('/bin/true', '/nonexistent', '/nonexistent.json', 1, '/nonexistent.dump', None, None, sink=sink)
        self.assertEqual(s['status'], 'no_report'); self.assertEqual(len(sink), 1)
        self.assertEqual(sink[0]['streams'], ['hello\n'])
        enc = roundtrip(rq2._enc_san_attempt(sink[0], 'lib'))
        self.assertEqual(rq2.dec_obs(enc['obs'], 'lib')['stderr'], 'hello\n')


class ReasonCodes(unittest.TestCase):
    def outcome(self, c, r, st='no_report', kind='exe', cause=None):
        sf, sink = san(st, cause)
        d, _ = rq2.examine_vector(Fake(c), Fake(r), sf, kind, T0, san_sink=sink)
        return d

    def test_incomplete_codes_split(self):
        ok = lambda t, k: lib()
        self.assertEqual(self.outcome(lambda t, k: lib(k1='infra', result=None), ok, kind='lib')['reason'], 'run_unobserved')
        self.assertEqual(self.outcome(ok, ok, 'infra', 'lib')['reason'], 'san_infra')
        self.assertEqual(self.outcome(ok, ok, 'infra', 'lib', 'c_san_build_failed')['reason'], 'san_build_failed')
        bad = lambda t, k: lib(k1='invalid_input', result=None, state={})
        self.assertEqual(self.outcome(bad, bad, kind='lib')['reason'], 'invalid_input')
        e = lambda t, k: exe(out=b'1')
        self.assertEqual(self.outcome(e, e, 'infra', cause='c_san_build_failed')['reason'], 'san_build_failed')

    def test_exe_unexecutable_argv_not_agreement(self):
        # observe.run_exe trả 'invalid_input' khi argv có byte NUL: hai bên bằng nhau nhưng không chạy; trước F5 thành 'agrees'.
        bad = lambda t, k: exe('invalid_input', err=b'embedded null byte')
        d = self.outcome(bad, bad)
        self.assertEqual((d['outcome'], d['reason']), ('incomplete', 'invalid_input'))
        o = OB.run_exe('/bin/true', ['a\x00b'], '', 5)                 # chuỗi byte như vectors.u2b
        self.assertEqual(o['status'], 'invalid_input')

    def test_every_vector_result_has_one_code(self):
        sides = [lambda t, k: exe(out=b'1\n'), lambda t, k: exe(out=b'2\n'), lambda t, k: exe(out=b'%d' % k),
                 lambda t, k: exe('timeout'), lambda t, k: exe('invalid_input'),
                 lambda t, k: exe(out=b'1\n' if k % 2 else b'2\n')]     # D2: phép so đổi giữa các lần khi C ổn định
        seen = set()
        for fc, fr in itertools.product(sides, sides):
            for st, cause in (('no_report', None), ('inconclusive', None), ('ub', None), ('infra', None), ('infra', 'c_san_build_failed')):
                d = self.outcome(fc, fr, st, cause=cause)
                self.assertIn(d['reason'], rq2.VECTOR_REASONS[d['outcome']])
                self.assertIsInstance(d['reason'], (str, type(None)))
                seen.add((d['outcome'], d['reason']))
        self.assertTrue({('incomplete', 'invalid_input'), ('incomplete', 'san_infra'), ('incomplete', 'san_build_failed'),
                         ('not_adjudicable', 'ub_in_c'), ('not_adjudicable', 'both_budget'), ('not_adjudicable', 'c_unstable'),
                         ('not_adjudicable', 'sanitizer_inconclusive'), ('not_adjudicable', 'unstable_comparison'),
                         ('supports_rejection', None), ('agrees', None)} <= seen)

    def test_sanitizer_inconclusive_direction_recorded(self):
        d = self.outcome(lambda t, k: exe(out=b'1'), lambda t, k: exe(out=b'2'), 'inconclusive')
        self.assertEqual((d['reason'], d['would_be']), ('sanitizer_inconclusive', 'supports_rejection'))
        d = self.outcome(lambda t, k: exe(out=b'1'), lambda t, k: exe(out=b'1'), 'inconclusive')
        self.assertEqual(d['would_be'], 'agrees')

    def test_c_unstable_detail(self):
        d = self.outcome(lambda t, k: exe(out=b'%d' % k), lambda t, k: exe(out=b'x'))
        self.assertEqual((d['reason'], d['c_stable']), ('c_unstable', False))           # D2 (Le chọn 25/10)

    def test_translation_codes(self):
        T, P = rq2.translation_outcome, rq2.primary_reason
        cases = {
            (('incomplete', 'san_infra'), ('agrees', None)): ('not_re_examined', 'incomplete_harness_run:san_infra'),
            (('incomplete', 'run_unobserved'),): ('not_re_examined', 'incomplete_harness_run:run_unobserved'),
            (('incomplete', 'invalid_input'), ('incomplete', 'san_infra')): ('not_re_examined', 'incomplete_harness_run:invalid_input'),
            (('incomplete', 'san_infra'), ('supports_rejection', None)): ('behavioral_disagreement', None),
            (('not_adjudicable', 'ub_in_c'), ('agrees', None)): ('not_adjudicable', 'ub_in_c'),
            (('not_adjudicable', 'ub_in_c'), ('not_adjudicable', 'both_budget')): ('not_adjudicable', 'ub_in_c'),   # D3: thứ tự xét
            (('agrees', None),): ('behavioral_agreement', None),
            (): ('not_re_examined', 'no_failing_vector'),
        }
        for vs, exp in cases.items():
            o, rs = T(list(vs))
            self.assertEqual((o, P(o, rs)), exp, vs)
            self.assertIn(P(o, rs), rq2.TRANSLATION_REASONS[o])

    def test_unreadable_vector(self):
        row = dict(orig={})
        v = rq2.unreadable_vector('1.json', row)
        self.assertEqual((v['outcome'], v['reason']), ('incomplete', 'vector_unreadable'))
        self.assertEqual(rq2.recompute_vector(v, 'exe'), ('incomplete', 'vector_unreadable'))
        self.assertEqual(rq2.translation_outcome([('incomplete', 'vector_unreadable')])[1],
                         ['incomplete_harness_run:vector_unreadable'])

    def test_pre_run_records_carry_reason(self):
        row = dict(system='s', bundle='B01_x', tractor_case='c', harvest_case='c', v_f=[], timeout_only=False, report_found=True,
                   orig={})
        out = rq2.rq2_pair('/nonexistent', 'lib', row, T0)
        self.assertEqual((out['outcome'], out['reason']), ('not_re_examined', 'no_failing_vector'))
        out = rq2.rq2_pair('/nonexistent', 'lib', dict(row, timeout_only=True), T0)
        self.assertEqual(out['reason'], 'timeout_only_rule_pending')
        err = rq2.rq2_case('/nonexistent', 'lib', [dict(row, v_f=['1.json'])], T0)[0]
        self.assertEqual((err['status'], err['reason']), ('harness_error', 'harness_error'))

    def test_summary_one_code_per_translation(self):
        recs = [dict(outcome='behavioral_disagreement', reasons=[], vectors=[dict(outcome='supports_rejection', reason=None)]),
                dict(outcome='not_adjudicable', reasons=['ub_in_c', 'both_budget'], reason='multiple', vectors=[]),
                dict(outcome='not_adjudicable', reasons=['ub_in_c'], vectors=[]),                     # bản ghi trước F5: suy từ reasons
                dict(outcome='not_re_examined', reasons=['incomplete_harness_run:san_infra'], reason='incomplete_harness_run:san_infra',
                     vectors=[dict(outcome='incomplete', reason='san_infra'), dict(outcome='agrees', reason=None)]),
                dict(status='harness_error', reason='harness_error')]
        S = M.summarize_rq2(recs)
        self.assertEqual(S['translation_reason'], {'not_adjudicable:ub_in_c': 2,                     # D3: 'multiple' tính lại
                                                   'not_re_examined:incomplete_harness_run:san_infra': 1, 'harness_error:harness_error': 1})
        self.assertEqual(sum(S['translation_reason'].values()), S['not_adjudicable'] + S['not_re_examined'] + S['harness_error'])
        self.assertEqual(S['vector_reasons'], {'supports_rejection:None': 1, 'incomplete:san_infra': 1, 'agrees:None': 1})


if __name__ == '__main__':
    unittest.main()
