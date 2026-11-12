"""Hồi quy cho lỗi đọc báo cáo sanitizer phía library của harness/rq1.py (decision-log 2026-10-22).
Ca thật: encode_base64_lib với `size` lớn hơn độ dài `src`; ASan báo heap-buffer-overflow, báo cáo nằm trong file report của runner.
Cần corpus TRACTOR (CORPUS) và libclang-rt; thiếu thì bỏ qua."""
import json, os, tempfile, unittest

from harness import build as BD
from harness import rq1
from harness.config import T

CASE = ('B02_organic', 'encode_base64_lib')


@unittest.skipUnless(os.path.isdir(f'{T}/{CASE[0]}/{CASE[1]}') and BD.asan_preload(), 'cần corpus TRACTOR và libclang-rt')
class LibSan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = os.environ.get('HARNESS_BUILD', os.path.join(tempfile.gettempdir(), 'harness-test-build'))
        cls.info = BD.build_lib_case(cls.B, *CASE)
        assert cls.info['runner_ok'] and cls.info['c-san_ok'], cls.info
        cls.root = BD.lib_root(cls.B, cls.info, 'c-san')
        cls.d = tempfile.mkdtemp()

    def san(self, state):
        p = os.path.join(self.d, f'v{abs(hash(json.dumps(state)))}.json')
        json.dump(dict(lib_state_in=state, lib_state_out={}), open(p, 'w'))
        return rq1.lib_san(self.info['runner_bin'], self.root, p, 30, p + '.dump', BD.asan_preload())

    def test_overread_reported(self):
        s = self.san({'returns': '', 'size': 4, 'src': [65, 43, 66]})
        self.assertEqual(s['status'], 'ub'); self.assertIn('AddressSanitizer', s['markers'])

    def test_consistent_input_clean(self):
        self.assertEqual(self.san({'returns': '', 'size': 3, 'src': [65, 43, 66]})['status'], 'no_report')


if __name__ == '__main__':
    unittest.main()
