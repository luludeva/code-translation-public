"""Hồi quy cho sự cố hết đĩa EC2 22/10 20:28 UTC (decision-log 2026-10-23): chương trình đo không được để lại core dump, và
observe.run_lib không được để lại file dump, report sau khi đọc. rq1.lib_san vẫn đọc được report (tests.test_rq1_san)."""
import glob, json, os, resource, shutil, subprocess, tempfile, time, unittest

from harness import build as BD
from harness import observe as OB
from harness.config import T


class NoCore(unittest.TestCase):
    """Giả lập máy cho phép core dump (giới hạn mềm không giới hạn, core_pattern là file trong thư mục làm việc)."""
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(); cls.cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
        src = os.path.join(cls.d, 'a.c')
        open(src, 'w').write('#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\nint main(void){ size_t n = 64 << 20;'
                             ' char *p = malloc(n); memset(p, 1, n); printf("%d\\n", p[7]); fflush(stdout); abort(); }\n')
        cls.bin = os.path.join(cls.d, 'a')
        if cls.cc: subprocess.run([cls.cc, src, '-o', cls.bin], check=True)
        cls.old = resource.getrlimit(resource.RLIMIT_CORE)
        try: resource.setrlimit(resource.RLIMIT_CORE, (cls.old[1], cls.old[1]))
        except ValueError: pass
        cls.pattern = open('/proc/sys/kernel/core_pattern').read().strip()

    @classmethod
    def tearDownClass(cls):
        resource.setrlimit(resource.RLIMIT_CORE, cls.old)

    def setUp(self):
        if not self.cc: self.skipTest('không có trình biên dịch C')

    def cores(self, d):
        return [f for f in os.listdir(d) if f.startswith('core')]

    def test_control_core_written(self):
        """Đối chứng: chạy thẳng, không qua harness, thì máy này có ghi core. Nếu không ghi được thì ca dưới không chứng minh gì."""
        w = tempfile.mkdtemp()
        subprocess.run([self.bin], cwd=w, capture_output=True)
        if self.pattern.startswith('|') or not self.cores(w):
            self.skipTest(f'máy này không ghi core vào thư mục làm việc (core_pattern={self.pattern!r})')

    def test_harness_no_core(self):
        w = tempfile.mkdtemp(); subprocess.run([self.bin], cwd=w, capture_output=True)
        if self.pattern.startswith('|') or not self.cores(w): self.skipTest('như đối chứng')
        o = OB.run_exe(self.bin, [], '', 10, mem_limit=0)
        self.assertEqual((o['status'], o['sig']), ('signal', 6))
        rd = os.path.join(os.environ.get('HARNESS_RUNDIR', tempfile.gettempdir()), f'harness-run-{os.getpid()}')
        self.assertEqual(self.cores(rd), [])
        o2 = OB.run_exe(self.bin, [], '', 10)            # có trần bộ nhớ, như lượt đo thật
        self.assertEqual(self.cores(rd), []); self.assertEqual(o2['out'], o['out'])


CASE = ('B02_organic', 'encode_base64_lib')


@unittest.skipUnless(os.path.isdir(f'{T}/{CASE[0]}/{CASE[1]}'), 'cần corpus TRACTOR')
class DumpRemoved(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = os.environ.get('HARNESS_BUILD', os.path.join(tempfile.gettempdir(), 'harness-test-build'))
        cls.info = BD.build_lib_case(cls.B, *CASE)
        assert cls.info['runner_ok'] and cls.info['c_ok'], cls.info
        cls.root = BD.lib_root(cls.B, cls.info, 'c')
        cls.d = tempfile.mkdtemp()

    def test_files_removed_result_kept(self):
        p = os.path.join(self.d, 'v.json')
        json.dump(dict(lib_state_in={'returns': '', 'size': 3, 'src': [65, 43, 66]}, lib_state_out={}), open(p, 'w'))
        r = OB.run_lib(self.info['runner_bin'], self.root, p, 30, False, p + '.dump')
        self.assertEqual(r['k1'], 'reported'); self.assertIn('state_out', r)
        self.assertEqual(glob.glob(p + '.dump*'), [])

    def test_keep_files(self):
        p = os.path.join(self.d, 'k.json')
        json.dump(dict(lib_state_in={'returns': '', 'size': 3, 'src': [65, 43, 66]}, lib_state_out={}), open(p, 'w'))
        OB.run_lib(self.info['runner_bin'], self.root, p, 30, False, p + '.dump', keep_files=True)
        self.assertTrue(os.path.exists(p + '.dump.report.json'))


class LibNT(unittest.TestCase):
    """Hai bên cùng vượt ngân sách, khác loại, là cùng lớp (Le chốt 2026-10-23)."""
    def test_merge(self):
        a, b = dict(k1='reported', result='Timeout'), dict(k1='reported', result='OutputLimit', output_limit=True)
        self.assertEqual(OB.channels_lib(a, b), []); self.assertTrue(OB.equal_lib(a, b))
        self.assertEqual(OB.channels_lib(a, dict(k1='infra', rc=None)), [])     # runner không trả lời trong hạn

    def test_one_side(self):
        a, b = dict(k1='reported', result='Timeout'), dict(k1='reported', result='Pass', state_out={'x': 1}, stdout='', stderr='')
        self.assertIn('status', OB.channels_lib(a, b))


def _orphans():
    out = subprocess.run(['ps', '-eo', 'pid=,ppid=,args='], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if 'runner-target/release/' in l and l.split()[1] == '1']


@unittest.skipUnless(os.path.isdir(f'{T}/B01_synthetic/018_stack_buffer_overflow_loop1_lib'), 'cần corpus TRACTOR')
class RunnerChildren(unittest.TestCase):
    """Runner TRACTOR không dừng tiến trình con khi Timeout và ghi stdout của nó vào file tạm không giới hạn (sự cố EC2 22/10).
    Ca thật lấy từ máy đo: 018_stack_buffer_overflow_loop1_lib (lặp vô hạn) và 006_static_alias_lib input i2 (in vô hạn)."""
    @classmethod
    def setUpClass(cls):
        from harness import checks as CK
        cls.B = os.environ.get('HARNESS_BUILD', os.path.join(tempfile.gettempdir(), 'harness-test-build'))
        cls.cases = {}
        for bundle, case in (('B01_synthetic', '018_stack_buffer_overflow_loop1_lib'), ('B01_synthetic', '006_static_alias_lib')):
            info = BD.build_lib_case(cls.B, bundle, case)
            files, _, _ = CK._lib_inputs(cls.B, info, 30, 0)
            cls.cases[case] = (info, BD.lib_root(cls.B, info, 'c'), [p for p, _ in files])

    def test_no_orphan_after_timeout(self):
        info, root, files = self.cases['018_stack_buffer_overflow_loop1_lib']
        before = len(_orphans())
        res = [OB.run_lib(info['runner_bin'], root, p, 10, False, p + '.o.dump').get('result') for p in files]
        self.assertIn('Timeout', res)
        time.sleep(1); self.assertEqual(len(_orphans()), before)

    def test_output_limit_live(self):
        info, root, files = self.cases['006_static_alias_lib']
        t0 = time.time(); r = OB.run_lib(info['runner_bin'], root, files[2], 10, False, files[2] + '.o.dump')
        self.assertEqual(r['result'], 'OutputLimit'); self.assertTrue(OB.lib_timeout(r))
        self.assertLess(time.time() - t0, 10)


if __name__ == '__main__':
    unittest.main()
