"""V1 (harness-design.md mục 7.1): hàm so sánh và luật timeout trên bộ ca cố định. Chạy: python3 -m unittest tests.test_v1_compare"""
import os, stat, tempfile, unittest

from harness import observe as OB


def script(d, name, body):
    p = os.path.join(d, name); open(p, 'w').write('#!/bin/sh\n' + body + '\n')
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC); return p


class Exe(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def eq(self, a, b, timeout=2):
        return OB.compare_exe(script(self.d, 'c', a), script(self.d, 'r', b), [], '', timeout)

    def test_rnan(self):
        self.assertTrue(self.eq('echo -nan', 'echo NaN')[0])

    def test_stdout_diff(self):
        self.assertFalse(self.eq('echo 1', 'echo 2')[0])

    def test_exit_code(self):
        self.assertFalse(self.eq('exit 1', 'exit 2')[0])
        self.assertTrue(self.eq('exit 3', 'exit 3')[0])

    def test_same_signal(self):
        self.assertTrue(self.eq('kill -SEGV $$', 'kill -SEGV $$')[0])

    def test_diff_signal(self):
        self.assertFalse(self.eq('kill -SEGV $$', 'kill -ABRT $$')[0])

    def test_exit101_vs_sigabrt(self):
        eq, c, r, _ = self.eq('kill -ABRT $$', 'exit 101')
        self.assertFalse(eq); self.assertEqual((c['status'], c['sig']), ('signal', 6)); self.assertEqual((r['status'], r['rc']), ('exit', 101))

    def test_both_timeout(self):
        self.assertTrue(self.eq('sleep 5', 'sleep 5', timeout=1)[0])

    def test_one_sided_timeout_resolves(self):
        eq, c, r, info = self.eq('echo x', 'sleep 2; echo x', timeout=1)
        self.assertTrue(eq); self.assertTrue(info['timeout_rerun']); self.assertFalse(info['timeout_confirmed'])

    def test_one_sided_timeout_confirmed(self):
        eq, c, r, info = OB.compare_exe(script(self.d, 'c', 'echo x'), script(self.d, 'r', 'sleep 30'), [], '', 1)
        self.assertFalse(eq); self.assertTrue(info['timeout_confirmed'])

    def test_stderr_compared(self):                      # decision-log 2026-10-23 (exp 12): stderr vào phép so
        eq, c, r, info = self.eq('echo a; echo e1 >&2', 'echo a; echo e2 >&2')
        self.assertFalse(eq); self.assertEqual(info['channels'], ['stderr'])

    def test_stderr_silent_vs_message(self):
        self.assertFalse(self.eq('echo a', 'echo a; echo warn >&2')[0])

    def test_stderr_norm(self):                          # chuẩn hoá N: chữ thường, địa chỉ, pid, khoảng trắng cuối, dòng trống
        self.assertTrue(self.eq('echo "Error at 0x7ffd12 ==123==" >&2', 'printf "error at 0x55aa ==9==  \\n\\n" >&2')[0])

    def test_channels_multi(self):
        _, _, _, info = self.eq('echo a; exit 1', 'echo b; exit 2')
        self.assertEqual(info['channels'], ['status', 'stdout'])

    def test_stdin_bytes_utf8(self):
        from harness.vectors import u2b
        p = script(self.d, 'cat', 'cat')
        o = OB.run_exe(p, [], u2b('héllo ✓'), 2)
        self.assertEqual(o['out'], 'héllo ✓'.encode('utf-8'))


    def test_rundir_isolated(self):
        """File do lần chạy trước ghi không còn ở lần sau; chương trình không ghi vào thư mục làm việc của harness."""
        w = script(self.d, 'w', 'ls; echo x > junk.txt')
        o1 = OB.run_exe(w, [], '', 2); o2 = OB.run_exe(w, [], '', 2)
        self.assertEqual(o1['out'], b''); self.assertEqual(o2['out'], b'')
        self.assertFalse(os.path.exists('junk.txt'))


    def test_output_limit(self):
        """Chương trình in vô hạn: dừng ở giới hạn, giữ đúng cap byte, không giữ toàn bộ."""
        y = script(self.d, 'y', 'yes x')
        o = OB.run_exe(y, [], '', 10, cap=1 << 20)
        self.assertEqual(o['status'], 'output_limit'); self.assertEqual(len(o['out']), 1 << 20); self.assertLess(o['secs'], 5)

    def test_nt_speed_mismatch(self):
        """Luật NT: bên nhanh đạt giới hạn output, bên chậm timeout, prefix trùng: khớp."""
        fast = script(self.d, 'fast', 'i=0; while true; do echo $i; i=$((i+1)); done')
        slow = script(self.d, 'slow', 'i=0; while true; do echo $i; i=$((i+1)); sleep 0.01; done')
        a = OB.run_exe(fast, [], '', 2, cap=1 << 16); b = OB.run_exe(slow, [], '', 2, cap=1 << 16)
        self.assertEqual((a['status'], b['status']), ('output_limit', 'timeout'))
        self.assertTrue(OB.equal_exe(a, b))

    def test_nt_prefix_differs(self):
        a = OB.run_exe(script(self.d, 'p1', 'echo a; sleep 5'), [], '', 1); b = OB.run_exe(script(self.d, 'p2', 'echo b; sleep 5'), [], '', 1)
        self.assertEqual((a['status'], b['status']), ('timeout', 'timeout')); self.assertFalse(OB.equal_exe(a, b))

    def test_nt_vs_exit(self):
        eq, c, r, info = OB.compare_exe(script(self.d, 'c3', 'yes x'), script(self.d, 'r3', 'echo x'), [], '', 1)
        self.assertFalse(eq); self.assertTrue(info['timeout_confirmed'])

    def test_output_limit_both_sides(self):
        y1 = script(self.d, 'y1', 'yes x'); y2 = script(self.d, 'y2', 'yes z')
        a = OB.run_exe(y1, [], '', 10, cap=1 << 16); b = OB.run_exe(y1, [], '', 10, cap=1 << 16); c = OB.run_exe(y2, [], '', 10, cap=1 << 16)
        self.assertTrue(OB.equal_exe(a, b)); self.assertFalse(OB.equal_exe(a, c))

    def test_large_stdin_no_deadlock(self):
        """Ghi stdin lớn trong khi chương trình in nhiều: không treo."""
        cat = script(self.d, 'cat2', 'cat')
        o = OB.run_exe(cat, [], 'a' * (4 << 20), 10)
        self.assertEqual(o['status'], 'exit'); self.assertEqual(len(o['out']), 4 << 20)


class Mem(unittest.TestCase):
    """Trần bộ nhớ ảo mỗi lần chạy (decision-log 2026-10-23, OOM convert_pix_lib)."""
    @classmethod
    def setUpClass(cls):
        import shutil, subprocess
        cls.d = tempfile.mkdtemp(); cls.cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
        src = os.path.join(cls.d, 'm.c')
        open(src, 'w').write('#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n'
                             'int main(int c, char **v){ size_t n = (size_t)atol(v[1]) << 20; char *p = malloc(n);'
                             ' if(!p){ fprintf(stderr, "Cannot allocate memory\\n"); return 1; } memset(p, 1, n);'
                             ' printf("%d\\n", p[n-1]); return 0; }\n')
        cls.bin = os.path.join(cls.d, 'm')
        if cls.cc: subprocess.run([cls.cc, src, '-o', cls.bin], check=True)

    def setUp(self):
        if not self.cc: self.skipTest('không có trình biên dịch C')

    def test_over_limit(self):
        o = OB.run_exe(self.bin, ['3000'], '', 10, mem_limit=1 << 30)
        self.assertEqual(o['status'], 'mem_limit'); self.assertTrue(OB.is_nt(o))

    def test_under_limit(self):
        o = OB.run_exe(self.bin, ['100'], '', 10, mem_limit=1 << 30)
        self.assertEqual((o['status'], o['rc'], o['out']), ('exit', 0, b'1\n'))

    def test_argv0_same(self):                           # C và Rust nhận cùng argv[0] ("driver"), dù binary ở hai đường dẫn khác nhau
        import shutil, subprocess
        src = os.path.join(self.d, 'a.c'); open(src, 'w').write('#include <stdio.h>\nint main(int c, char **v){ fprintf(stderr, "usage: %s\\n", v[0]); return 1; }\n')
        b1, b2 = os.path.join(self.d, 'x1'), os.path.join(self.d, 'sub', 'x2'); os.makedirs(os.path.dirname(b2))
        subprocess.run([self.cc, src, '-o', b1], check=True); shutil.copy(b1, b2)
        eq, c, r, _ = OB.compare_exe(b1, b2, [], '', 5)
        self.assertTrue(eq); self.assertEqual(c['err'], b'usage: driver\n')

    def test_san_no_rlimit(self):                        # san=True: không đặt RLIMIT_AS
        o = OB.run_exe(self.bin, ['1100'], '', 20, mem_limit=1 << 30, san=True)
        self.assertEqual(o['status'], 'exit')


class Lib(unittest.TestCase):
    def test_float_tol(self):
        self.assertTrue(OB.float_tol_equal({'x': 1.0}, {'x': 1.0 + 1e-7}))
        self.assertFalse(OB.float_tol_equal({'x': 1.0}, {'x': 1.0 + 1e-5}))

    def test_nan_eq_nan(self):
        self.assertTrue(OB.float_tol_equal([float('nan')], [float('nan')]))

    def test_int_exact(self):
        self.assertFalse(OB.float_tol_equal({'n': 1}, {'n': 2}))

    def test_equal_lib_fields(self):
        a = dict(k1='reported', result='Pass', stdout='-nan\n', state_out={'v': [1.0, 2.0]})
        b = dict(k1='reported', result='Pass', stdout='nan\n', state_out={'v': [1.0, 2.0 + 1e-9]})
        self.assertTrue(OB.equal_lib(a, b))
        self.assertFalse(OB.equal_lib(a, dict(b, k1='infra')))

    def test_lib_stderr(self):
        a = dict(k1='reported', result='Pass', stdout='', stderr='bad size\n', state_out={'n': 1})
        self.assertFalse(OB.equal_lib(a, dict(a, stderr='')))
        self.assertEqual(OB.channels_lib(a, dict(a, stderr='')), ['stderr'])
        self.assertTrue(OB.equal_lib(a, dict(a, stderr='BAD SIZE  \n')))


if __name__ == '__main__':
    unittest.main()
