"""Phân tích độ nhạy trần output (decision-log 2026-10-23, R29; sửa cùng ngày): input mà hai bên cùng chạm trần và prefix trùng
(nhánh khớp) vẫn phải được chạy lại với trần lớn hơn, để phân tích có thể thêm divergence chứ không chỉ bớt."""
import os, shutil, subprocess, tempfile, unittest

from harness import observe as OB
from harness import rq1

SRC = r'''#include <stdio.h>
int main(void){ for (int i = 0; i < 300000; i++) fputs("aaaaaaa\n", stdout); fputs("%s\n", stdout); return 0; }
'''


class CapSensExe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
        cls.d = tempfile.mkdtemp(); cls.bins = {}
        if not cls.cc: return
        for name, tail in (('c', 'END'), ('same', 'END'), ('diff', 'DIFF')):   # 2,4 MB giống nhau, khác ở dòng cuối
            src = os.path.join(cls.d, f'{name}.c'); open(src, 'w').write(SRC.replace('%s', tail))
            cls.bins[name] = os.path.join(cls.d, name); subprocess.run([cls.cc, src, '-o', cls.bins[name]], check=True)
        cls.old = OB.OUTPUT_CAP; OB.OUTPUT_CAP = 1 << 20                   # trần 1 MiB: hai bên đều chạm; trần x8 = 8 MiB: không chạm

    @classmethod
    def tearDownClass(cls):
        if cls.cc: OB.OUTPUT_CAP = cls.old

    def setUp(self):
        if not self.cc: self.skipTest('không có trình biên dịch C')

    def test_match_branch_hides_difference_at_primary_cap(self):
        eq, c1, r1, _ = OB.compare_exe(self.bins['c'], self.bins['diff'], [], '', 10)
        self.assertTrue(eq)                                               # prefix chung trùng: khớp ở trần chính
        self.assertTrue(rq1.cap_hit_exe(c1, r1))

    def test_larger_cap_reveals_difference(self):
        info, c8, r8 = rq1.cap_sens_exe(self.bins['c'], self.bins['diff'], [], '', 10, None)
        self.assertEqual((info['c_status'], info['r_status']), ('exit', 'exit'))
        self.assertFalse(info['equal'])
        self.assertEqual(OB.channels_exe(c8, r8), ['stdout'])
        self.assertTrue(rq1.cap_sens_stable_exe(self.bins['c'], self.bins['diff'], [], '', 10, None, c8, r8))

    def test_negative_control_identical_programs(self):
        info, _, _ = rq1.cap_sens_exe(self.bins['c'], self.bins['same'], [], '', 10, None)
        self.assertTrue(info['equal'])


if __name__ == '__main__':
    unittest.main()
