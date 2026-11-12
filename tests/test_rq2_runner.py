"""Phần chạy RQ2 (harness/rq2.py, Việc 6 ngày 2026-10-23): các ca biên qua examine_vector với runner giả, chọn R_run và V_f từ census
giả, vector library đã xoá output kỳ vọng."""
import io, json, os, tarfile, tempfile, unittest

from harness import rq2
from harness.config import TIMEOUT_RERUN_FACTOR

T0 = 10


def exe(status='exit', out=b'', err=b'', rc=0):
    return dict(status=status, rc=rc if status == 'exit' else None, sig=None, to=status == 'timeout', out=out, err=err)


def lib(result='VectorComparisonFailed', k1='reported', state=None, stdout='', stderr=''):
    return dict(k1=k1, result=result, rc=0, state_out={'x': 1.0} if state is None else state, stdout=stdout, stderr=stderr)


class Fake:
    """Runner giả theo timeout: fn(t, lần gọi thứ k) -> quan sát. Đếm lời gọi để kiểm có chạy lại hay không."""
    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def __call__(self, t):
        self.calls.append(t); return self.fn(t, len(self.calls))


def clean_san(calls):
    def f(co):
        calls.append(co); return dict(status='no_report', markers=[], attempts=1)
    return f


class EdgeCases(unittest.TestCase):
    def run_exe(self, c, r, san='no_report'):
        sc = []
        sf = clean_san(sc) if san == 'no_report' else (lambda co: sc.append(co) or dict(status=san, markers=[], attempts=1))
        d, runs = rq2.examine_vector(Fake(c), Fake(r), sf, 'exe', T0)
        self.assertEqual(len(sc), 1)                       # sanitizer chạy đúng một lần, trên mọi vector trượt
        return d

    def test_both_over_budget(self):
        d = self.run_exe(lambda t, k: exe('timeout'), lambda t, k: exe('output_limit'))
        self.assertEqual((d['outcome'], d['reason']), ('not_adjudicable', 'both_budget'))
        self.assertEqual(d['runs'][0]['channels'], ['both_budget'])

    def test_one_over_budget_then_agrees_after_rerun(self):
        r = Fake(lambda t, k: exe('timeout') if t == T0 else exe(out=b'7\n'))
        d, runs = rq2.examine_vector(Fake(lambda t, k: exe(out=b'7\n')), r, clean_san([]), 'exe', T0)
        self.assertEqual((d['outcome'], d['reason']), ('agrees', None))
        self.assertTrue(all(x['reran'] for x in d['runs']))
        self.assertEqual(r.calls.count(T0 * TIMEOUT_RERUN_FACTOR), rq2.REPS)

    def test_still_over_budget_after_rerun(self):
        d = self.run_exe(lambda t, k: exe(out=b'7\n'), lambda t, k: exe('timeout'))
        self.assertEqual((d['outcome'], d['reason']), ('supports_rejection', None))

    def test_output_differs(self):
        d = self.run_exe(lambda t, k: exe(out=b'7\n'), lambda t, k: exe(out=b'8\n'))
        self.assertEqual(d['outcome'], 'supports_rejection'); self.assertEqual(d['runs'][0]['channels'], ['stdout'])

    def test_stderr_only_difference_supports_rejection(self):
        d = self.run_exe(lambda t, k: exe(err=b'error: bad input\n', rc=1), lambda t, k: exe(err=b'', rc=1))
        self.assertEqual(d['outcome'], 'supports_rejection'); self.assertEqual(d['runs'][0]['channels'], ['stderr'])

    def test_unstable(self):
        d = self.run_exe(lambda t, k: exe(out=b'7\n'), lambda t, k: exe(out=b'8\n' if k % 2 else b'7\n'))
        self.assertEqual((d['outcome'], d['reason']), ('not_adjudicable', 'unstable_comparison'))

    def test_c_unstable_is_not_rejection(self):
        d = self.run_exe(lambda t, k: exe(out=str(k).encode()), lambda t, k: exe(out=b'x'))
        self.assertEqual((d['outcome'], d['reason']), ('not_adjudicable', 'c_unstable'))   # D2 (Le chọn 25/10): trước 'unstable_comparison'

    def test_ub_in_c(self):
        d = self.run_exe(lambda t, k: exe(out=b'7\n'), lambda t, k: exe(out=b'8\n'), san='ub')
        self.assertEqual((d['outcome'], d['reason']), ('not_adjudicable', 'ub_in_c'))

    def test_sanitizer_runs_even_when_sides_match(self):
        d = self.run_exe(lambda t, k: exe(out=b'7\n'), lambda t, k: exe(out=b'7\n'), san='inconclusive')
        self.assertEqual((d['outcome'], d['reason']), ('not_adjudicable', 'sanitizer_inconclusive'))

    def test_library_runner_error(self):
        d, _ = rq2.examine_vector(Fake(lambda t, k: lib(k1='infra', result=None)), Fake(lambda t, k: lib()), clean_san([]), 'lib', T0)
        self.assertEqual((d['outcome'], d['reason']), ('incomplete', 'run_unobserved'))      # F5: tách khỏi lỗi sanitizer (trước: 'infra')
        self.assertEqual(rq2.translation_outcome([(d['outcome'], d['reason'])])[0], 'not_re_examined')

    def test_library_invalid_input_both_sides_not_agreement(self):
        bad = lambda t, k: lib(k1='invalid_input', result=None, state={})
        d, _ = rq2.examine_vector(Fake(bad), Fake(bad), clean_san([]), 'lib', T0)
        self.assertEqual((d['outcome'], d['reason']), ('incomplete', 'invalid_input'))

    def test_library_both_budget_different_kinds(self):
        d, _ = rq2.examine_vector(Fake(lambda t, k: lib('Timeout')), Fake(lambda t, k: lib('MemLimit')), clean_san([]), 'lib', T0)
        self.assertEqual((d['outcome'], d['reason']), ('not_adjudicable', 'both_budget'))

    def test_library_state_differs(self):
        d, _ = rq2.examine_vector(Fake(lambda t, k: lib(state={'x': 1.0})), Fake(lambda t, k: lib(state={'x': 2.0})), clean_san([]),
                                  'lib', T0)
        self.assertEqual(d['outcome'], 'supports_rejection'); self.assertEqual(d['runs'][0]['channels'], ['state'])


class StripExpected(unittest.TestCase):
    def test_strip(self):
        v = dict(lib_state_in={'a': 1}, lib_state_out={'b': 2}, stdout='x', stderr={'pattern': 'y', 'is_regex': True}, stdin='s',
                 env={'K': 'V'})
        self.assertEqual(rq2.strip_expected(v), dict(lib_state_in={'a': 1}, lib_state_out={}, stdin='s', env={'K': 'V'}))


class Selection(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='rq2sel-')
        base = dict(bundle='B01_synthetic', harvest_case='c', pub_error='test failed', build_ok=True, ours_passed=False, pilot=False,
                    pub_passed=False)
        rows = [dict(base, system='a', tractor_case='c', results={'VectorComparisonFailed': 1, 'Pass': 1}),
                dict(base, system='b', tractor_case='c', ours_passed=True, results={'Pass': 2}),          # không tái lập: ngoài R_run
                dict(base, system='c', tractor_case='c', pub_error='build failed', results={'Pass': 2}),  # bị từ chối ở bước build
                dict(base, system='d', tractor_case='c', build_ok=False),                                # không build khi tái lập
                dict(base, system='e', tractor_case='c', pilot=True, results={'VectorComparisonFailed': 2}),
                dict(base, system='f', tractor_case='c', results={'Timeout': 1, 'Skip': 1}),
                dict(base, system='g', tractor_case='c', pub_passed=True)]
        self.census = os.path.join(self.d, 'census.jsonl')
        open(self.census, 'w').write(''.join(json.dumps(r) + '\n' for r in rows))
        reps = {'a': {'test_vectors/1.json': dict(result='Pass'), 'test_vectors/2.json': dict(result='VectorComparisonFailed',
                                                                                              diff='Stdout diff')},
                'f': {'test_vectors/1.json': dict(result='Timeout'), 'test_vectors/2.json': dict(result='Skip')}}
        self.tgz = os.path.join(self.d, 'rep.tar.gz')
        with tarfile.open(self.tgz, 'w:gz') as t:
            for s, rep in reps.items():
                b = json.dumps(rep).encode(); ti = tarfile.TarInfo(f'reports/{s}/B01_synthetic/c.json'); ti.size = len(b)
                t.addfile(ti, io.BytesIO(b))

    def test_r_run(self):
        rows = {r['system']: r for r in rq2.r_run('lib', census=self.census, reports=self.tgz)}
        self.assertEqual(sorted(rows), ['a', 'f'])
        self.assertEqual(rows['a']['v_f'], ['2.json']); self.assertEqual(rows['a']['orig']['2.json']['diff'], 'Stdout diff')
        self.assertFalse(rows['a']['timeout_only']); self.assertTrue(rows['f']['timeout_only'])
        self.assertEqual([r['system'] for r in rq2.r_run('lib', pilot=True, census=self.census, reports=self.tgz)], ['e'])

    def test_timeout_only_not_decided_silently(self):
        row = [r for r in rq2.r_run('lib', census=self.census, reports=self.tgz) if r['system'] == 'f'][0]
        out = rq2.rq2_pair('/nonexistent', 'lib', row, T0)
        self.assertEqual((out['outcome'], out['reasons']), ('not_re_examined', ['timeout_only_rule_pending']))

    def test_missing_report(self):
        row = [r for r in rq2.r_run('lib', pilot=True, census=self.census, reports=self.tgz)][0]
        self.assertEqual(rq2.rq2_pair('/nonexistent', 'lib', row, T0)['reasons'], ['report_missing'])


if __name__ == '__main__':
    unittest.main()
