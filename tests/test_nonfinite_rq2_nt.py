"""Hai test bổ sung sau merge bản sửa oracle (phiên kỹ thuật 2026-10-23, Việc 1).

(a) Giá trị không hữu hạn đi hết đường đọc file dump tới phép so: một runner giả ghi report và file dump theo đúng định dạng bản vá
    runner v2 (state_out mang null ở chỗ NaN, inf, -inf; state_debug mang định dạng Debug của Rust). Test đi qua observe.run_lib (bộ
    khởi chạy, đọc report, đọc dump, nonfinite_tokens) rồi observe.channels_lib, không gọi thẳng hàm so.
(b) RQ2, luật NT 2026-10-22: một bên vượt ngân sách thì chạy lại hai bên với timeout gấp TIMEOUT_RERUN_FACTOR; sau khi chạy lại mà bên
    Rust vẫn vượt ngân sách, C dừng bình thường và ổn định, sanitizer phía C không báo, thì vector ủng hộ việc từ chối.
"""
import json, os, stat, tempfile, textwrap, unittest

from harness import observe as OB
from harness import rq2
from harness.config import TIMEOUT_RERUN_FACTOR

FAKE_RUNNER = textwrap.dedent('''\
    #!/usr/bin/env python3
    # Runner giả: nhận cùng tham số với runner TRACTOR, ghi report và một dòng dump như bản vá state-dump v2.
    import json, os, sys
    a = sys.argv[1:]
    rep = a[a.index('--output') + 1]
    json.dump({'v0': {'result': 'VectorComparisonFailed'}}, open(rep, 'w'))
    line = dict(note='v0', state_out=json.loads(os.environ['FAKE_STATE_OUT']), state_debug=os.environ['FAKE_STATE_DEBUG'],
                stdout='', stderr='')
    open(os.environ['CANDO2_STATE_DUMP'], 'a').write(json.dumps(line) + '\\n')
''')


class NonfiniteThroughDump(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix='nonfinite-')
        cls.runner = os.path.join(cls.d, 'fake_runner')
        open(cls.runner, 'w').write(FAKE_RUNNER)
        os.chmod(cls.runner, os.stat(cls.runner).st_mode | stat.S_IEXEC)
        cls.vec = os.path.join(cls.d, 'v.json'); json.dump({'lib_state_in': {}, 'lib_state_out': {}}, open(cls.vec, 'w'))

    def run_side(self, name, debug, state_out=None):
        # serde_json ghi NaN, inf, -inf thành null; hai bên vì thế có cùng state_out.
        env = dict(FAKE_STATE_OUT=json.dumps(state_out or {'v': None, 'w': [1.0, None]}), FAKE_STATE_DEBUG=debug)
        o = OB.run_lib(self.runner, self.d, self.vec, 10, name == 'R', os.path.join(self.d, f'{name}.dump'), extra_env=env)
        self.assertEqual(o.get('k1'), 'reported', o)
        return o

    def test_nan_vs_inf_is_state_divergence(self):
        c = self.run_side('C', 'S { v: NaN, w: [1.0, inf] }')
        r = self.run_side('R', 'S { v: inf, w: [1.0, NaN] }')
        self.assertEqual(c['state_out'], r['state_out'])                     # dump JSON không phân biệt được
        self.assertEqual(c['state_nonfinite'], ['NaN', 'inf'])
        self.assertEqual(r['state_nonfinite'], ['inf', 'NaN'])
        self.assertEqual(OB.channels_lib(c, r), ['state'])
        self.assertFalse(OB.equal_lib(c, r))

    def test_sign_of_infinity(self):
        c = self.run_side('C', 'S { v: -inf, w: [1.0, inf] }')
        r = self.run_side('R', 'S { v: inf, w: [1.0, inf] }')
        self.assertEqual(OB.channels_lib(c, r), ['state'])

    def test_same_nonfinite_values_match(self):
        c = self.run_side('C', 'S { v: NaN, w: [1.0, -inf] }')
        r = self.run_side('R', 'S { v: NaN, w: [1.0, -inf] }')
        self.assertTrue(OB.equal_lib(c, r))

    def test_dump_files_removed(self):
        self.run_side('C', 'S { v: NaN, w: [1.0, inf] }')
        self.assertFalse(os.path.exists(os.path.join(self.d, 'C.dump')))


def exe(status='exit', out=b''):
    return dict(status=status, rc=0 if status == 'exit' else None, sig=None, to=status == 'timeout', out=out, err=b'')


class RQ2StillOverBudgetAfterRerun(unittest.TestCase):
    """Luật NT 2026-10-22 ở RQ2: chạy lại gấp mười mà một bên vẫn vượt ngân sách thì kết quả là supports_rejection."""

    def setUp(self):
        self.calls = []

    def rc(self, t):
        self.calls.append(('C', t)); return exe(out=b'42\n')

    def rr(self, t):
        self.calls.append(('R', t)); return exe('timeout')               # Rust không dừng ở cả timeout thường và timeout gấp mười

    def test_supports_rejection(self):
        runs = rq2.observe_vector(self.rc, self.rr, 10, 'exe')
        self.assertTrue(all(reran for _, _, reran in runs))                  # lần nào cũng chạy lại vì đúng một bên vượt ngân sách
        self.assertEqual(sum(1 for side, t in self.calls if t == 10 * TIMEOUT_RERUN_FACTOR), 2 * rq2.REPS)
        self.assertTrue(all(r['status'] == 'timeout' and c['status'] == 'exit' for c, r, _ in runs))
        self.assertEqual(rq2.vector_outcome(runs, 'no_report', 'exe'), ('supports_rejection', None))
        self.assertEqual(rq2.translation_outcome([rq2.vector_outcome(runs, 'no_report', 'exe')])[0], 'behavioral_disagreement')

    def test_library_same_rule(self):
        lc = lambda t: dict(k1='reported', result='VectorComparisonFailed', rc=0, state_out={'x': 1.0}, stdout='', stderr='')
        lr = lambda t: dict(k1='reported', result='Timeout', rc=0)
        runs = rq2.observe_vector(lc, lr, 10, 'lib')
        self.assertTrue(all(reran for _, _, reran in runs))
        self.assertEqual(rq2.vector_outcome(runs, 'no_report', 'lib'), ('supports_rejection', None))


if __name__ == '__main__':
    unittest.main()
