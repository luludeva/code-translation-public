"""F1 (Le chọn 25/10, master plan Hàng đợi): trần output library kiểm cả sau khi lời gọi kết thúc. Runner giả kết thúc ngay và ghi dump
có stdout hoặc stderr dài; đi qua observe.run_lib (bộ khởi chạy, report, dump). Chạy: python3 -m unittest tests.test_f1_output_cap"""
import json, os, stat, tempfile, textwrap, unittest

from harness import observe as OB

FAKE_RUNNER = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    a = sys.argv[1:]
    json.dump({'v0': {'result': 'Pass'}}, open(a[a.index('--output') + 1], 'w'))
    line = dict(note='v0', state_out={}, stdout='x' * int(os.environ['N_OUT']), stderr='e' * int(os.environ['N_ERR']))
    open(os.environ['CANDO2_STATE_DUMP'], 'a').write(json.dumps(line) + '\\n')
''')


class OutputCapAfterCall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix='outcap-')
        cls.runner = os.path.join(cls.d, 'fake_runner'); open(cls.runner, 'w').write(FAKE_RUNNER)
        os.chmod(cls.runner, os.stat(cls.runner).st_mode | stat.S_IEXEC)
        cls.vec = os.path.join(cls.d, 'v.json'); json.dump({'lib_state_in': {}, 'lib_state_out': {}}, open(cls.vec, 'w'))

    def run1(self, n_out, n_err, cap=1000):
        return OB.run_lib(self.runner, self.d, self.vec, 10, False, os.path.join(self.d, 'x.dump'),
                          extra_env=dict(N_OUT=str(n_out), N_ERR=str(n_err)), cap=cap)

    def test_stdout_over_cap_is_output_limit(self):
        o = self.run1(1500, 0)
        self.assertEqual((o['result'], o.get('output_limit'), o.get('out_bytes')), ('OutputLimit', True, 1500))
        self.assertTrue(OB.lib_timeout(o))                                          # vượt ngân sách theo luật NT

    def test_stderr_over_cap_is_output_limit(self):
        self.assertEqual(self.run1(10, 1001)['result'], 'OutputLimit')

    def test_under_cap_unchanged(self):
        o = self.run1(1000, 999)
        self.assertEqual(o['result'], 'Pass'); self.assertNotIn('output_limit', o)


if __name__ == '__main__':
    unittest.main()
