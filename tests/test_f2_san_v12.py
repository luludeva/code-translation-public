"""F2 sau rà §3.3 v12 (Le chọn 25/10, K1/M3/M4/m9): phân loại báo cáo sanitizer theo dòng tiêu đề, phân biệt hoa thường, UB xét trước
bộ nhớ; library giải mã report JSON một dòng của runner trước khi phân loại.
  - Unit: chuỗi dựng theo định dạng thật (clang 18, libasan của GCC, report của runner TRACTOR theo Serialize của TestOutcome).
  - Thật: chương trình C nhỏ biên dịch bằng clang với cờ C-san của harness (config.SAN_FLAGS_EXE), chạy qua observe.run_exe(san=True) với
    EXE_SAN_ENV, phân loại bằng rq1.san_status và rq1._exe_san. Một ca GCC (M4) nếu gcc link được ASan. Thiếu công cụ thì bỏ qua.
  - Library: runner giả ghi report JSON một dòng (dump trống như khi tiến trình con chết), đi qua rq1.lib_san.
Chạy: python3 -m unittest tests.test_f2_san_v12"""
import json, os, shutil, stat, subprocess, tempfile, textwrap, unittest

from harness import build as BD
from harness import observe as OB
from harness import rq1
from harness.config import SAN_FLAGS_EXE

# Báo cáo dựng theo định dạng clang 18 (đối chiếu đầu ra thật của các chương trình ở lớp RealClang).
HBO = ('=================================================================\n'
       '==7==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502000000015 at pc 0x5561 bp 0x7fff sp 0x7fff\n'
       'WRITE of size 1 at 0x502000000015 thread T0\n'
       '    #0 0x556140de38d4 in f /src/x.c:3:14\n\n'
       'SUMMARY: AddressSanitizer: heap-buffer-overflow /src/x.c:3:14 in f\n==7==ABORTING\n')
TOO_BIG_GCC = ('=================================================================\n'
               '==9==ERROR: AddressSanitizer: requested allocation size 0x100000000000 (0x100000001000 after adjustments for alignment, '
               'red zones etc.) exceeds maximum supported size of 0x10000000000 (thread T0)\n'
               '    #0 0x7fa4116fd9c7 in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:69\n'
               '    #1 0x560f518e03da in main /src/big.c:3\n\n'
               '==9==HINT: if you don\'t care about these errors you may set allocator_may_return_null=1\n'
               'SUMMARY: AddressSanitizer: allocation-size-too-big ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:69 in malloc\n'
               '==9==ABORTING\n')
OOM = ('==5==ERROR: AddressSanitizer: out of memory: allocator is trying to allocate 0x8000000000 bytes\n\n'
       '==5==HINT: if you don\'t care about these errors you may set allocator_may_return_null=1\n'
       'SUMMARY: AddressSanitizer: out-of-memory (/b/big+0xc6193) (BuildId: bfa8) in malloc\n==5==ABORTING\n')
RSS = '==4==AddressSanitizer: hard rss limit exhausted (256Mb vs 436Mb)\n==4==Process memory map follows:\n\t0x00007fff7000-0x00008fff7000\t\n'
UBSAN = ("x.c:3:64: runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'\n"
         'SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior x.c:3:64 \n')
PROGRAM_TEXT = 'error: out of memory\nRuntime error: bad token\nhand sanitizer stock: 3\nbuilt with AddressSanitizer support\n'


def runner_report(stdout, stderr, result='UnknownFailure'):
    """Report của runner TRACTOR: JSON một dòng, output nằm trong chuỗi đã escape (cando2 runner.rs, Serialize của TestOutcome)."""
    v = dict(result=result, output=dict(stdout=stdout, stderr=stderr))
    if result == 'UnknownFailure': v = dict(result=result, wait_status=256, output=v['output'])
    return json.dumps({'/corpus/test_vectors/1.json': v})


def st(x): return rq1.san_status(x)[0]


def write(p, s):
    with open(p, 'w') as f: f.write(s)


class Unit(unittest.TestCase):
    def test_k1_report_one_line(self):
        d = tempfile.mkdtemp(prefix='f2-k1-'); p = os.path.join(d, 'r.json')
        rep = runner_report('error: out of memory\n', 'error: out of memory\n' + HBO)
        self.assertEqual(rep.count('\n'), 0)                     # một dòng: lý do phải giải mã trước khi phân loại theo dòng
        write(p, rep)
        self.assertEqual(rq1.san_status(rq1.lib_san_streams(p, {})), ('ub', ['AddressSanitizer']))
        for stderr, want in ((OOM, 'mem_limit'), (TOO_BIG_GCC, 'mem_limit'), (PROGRAM_TEXT, 'no_report'), (UBSAN + OOM, 'ub')):
            write(p, runner_report(PROGRAM_TEXT, stderr))
            self.assertEqual(st(rq1.lib_san_streams(p, {})), want, stderr[:60])

    def test_k1_dump_and_infra_msg_streams(self):
        so = dict(stdout='out of memory\n', stderr='error: out of memory\n' + HBO)
        self.assertEqual(st(rq1.lib_san_streams(None, so)), 'ub')
        self.assertEqual(st(rq1.lib_san_streams('/nonexistent.json', dict(infra_msg=OOM))), 'mem_limit')

    def test_k1_bad_report_ignored(self):
        p = os.path.join(tempfile.mkdtemp(prefix='f2-bad-'), 'r.json'); write(p, '{"v": {"output": {"stderr": "==1==ERR')
        self.assertEqual(rq1.lib_san_streams(p, {}), [])

    def test_m3_program_text_not_ub(self):
        for t in (b'Runtime error: x\n', b'hand sanitizer stock: 3\n', b'built with AddressSanitizer support\n',
                  b'addresssanitizer: heap-buffer-overflow\n', b'ERROR: addresssanitizer: SEGV\n', PROGRAM_TEXT.encode()):
            self.assertEqual(rq1.san_status(t), ('no_report', []), t)

    def test_m4_gcc_frame_path_is_memory(self):
        self.assertEqual(st(TOO_BIG_GCC.encode()), 'mem_limit')
        self.assertEqual(st(OOM.encode()), 'mem_limit')
        self.assertEqual(st(RSS.encode()), 'mem_limit')          # dạng thật không có 'ERROR:' và không có SUMMARY

    def test_ub_kinds(self):
        self.assertEqual(rq1.san_status(HBO.encode()), ('ub', ['AddressSanitizer']))
        self.assertEqual(rq1.san_status(UBSAN.encode()), ('ub', ['runtime error:', 'UndefinedBehaviorSanitizer']))
        self.assertEqual(st(b'AddressSanitizer:DEADLYSIGNAL\n==1==ERROR: AddressSanitizer: SEGV on unknown address 0x0\n'), 'ub')
        self.assertEqual(st(b'==1==ERROR: AddressSanitizer: stack-buffer-overflow on address\n'), 'ub')
        self.assertEqual(st(b'==1==ERROR: UndefinedBehaviorSanitizer: SEGV on unknown address\n'), 'ub')
        self.assertEqual(st((UBSAN + OOM).encode()), 'ub')        # UB xét trước bộ nhớ
        self.assertEqual(st((PROGRAM_TEXT + HBO).encode()), 'ub')  # chương trình in "out of memory" rồi ASan báo UB
        self.assertEqual(st(b'==1==ERROR: LeakSanitizer: detected memory leaks\n'), 'no_report')

    def test_m9_markers_match_status(self):
        for t in (HBO, TOO_BIG_GCC, OOM, RSS, UBSAN, PROGRAM_TEXT, UBSAN + OOM, PROGRAM_TEXT + HBO, ''):
            s, mk = rq1.san_status(t.encode())
            self.assertEqual(s == 'ub', bool(mk), (t[:60], s, mk))
            self.assertTrue(set(mk) <= {m.decode() for m in rq1.SAN_UB_MARKERS})


def _clang_ok():
    return bool(shutil.which('clang')) and bool(BD.asan_preload())


SAN_CFLAGS = [f for x in SAN_FLAGS_EXE if x.startswith('-DCMAKE_C_FLAGS=') for f in x.split('=', 1)[1].split()]
PROGS = dict(
    hbo_after_oom_text=r'''#include <stdio.h>
#include <stdlib.h>
int main(int c, char **v) { fputs("error: out of memory\n", stderr); fflush(stderr);
  char *p = malloc(4); volatile int i = 3 + c; p[i] = 1; printf("%d\n", p[i]); return 0; }''',
    too_big=r'''#include <stdio.h>
#include <stdlib.h>
int main(int c, char **v) { size_t n = (size_t)1 << 44; char *p = malloc(n); printf("%p\n", (void *)p); return p == 0; }''',
    oom=r'''#include <stdio.h>
#include <stdlib.h>
int main(int c, char **v) { size_t n = (size_t)1 << 39; char *p = malloc(n);
  for (size_t i = 0; p && i < n; i += 4096) p[i] = 1; printf("%p\n", (void *)p); return p == 0; }''',
    rss=r'''#include <stdlib.h>
#include <string.h>
int main(void) { for (;;) { char *p = malloc(64 << 20); if (!p) return 2; memset(p, 1, 64 << 20); } }''',
    signed_overflow=r'''#include <limits.h>
#include <stdio.h>
int main(int c, char **v) { int x = INT_MAX - 1 + c; x += 1; printf("%d\n", x); return 0; }''',
    program_text=r'''#include <stdio.h>
int main(void) { fputs("error: out of memory\nRuntime error: bad token\nhand sanitizer stock: 3\n", stderr); puts("ok"); return 1; }''')


@unittest.skipUnless(_clang_ok(), 'cần clang và runtime ASan (libclang-rt)')
class RealClang(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix='f2-clang-'); cls.bin = {}
        for name, src in PROGS.items():
            c = os.path.join(cls.d, name + '.c'); b = os.path.join(cls.d, name)
            with open(c, 'w') as f: f.write(src)
            subprocess.run(['clang'] + SAN_CFLAGS + [c, '-o', b], check=True, capture_output=True)
            cls.bin[name] = b

    def run1(self, name, env=None):
        o = OB.run_exe(self.bin[name], [], '', 30, dict(env or rq1.EXE_SAN_ENV), san=True)
        return o, rq1.san_status(o['err'])

    def check(self, name, want, env=None):
        o, (s, mk) = self.run1(name, env)
        self.assertEqual(s, want, (name, o['status'], o['err'][-600:]))
        self.assertEqual(s == 'ub', bool(mk))
        return o, mk

    def test_heap_buffer_overflow_after_program_oom_text(self):
        o, mk = self.check('hbo_after_oom_text', 'ub')
        self.assertIn(b'error: out of memory', o['err']); self.assertEqual(mk, ['AddressSanitizer'])

    def test_allocation_size_too_big(self):
        o, _ = self.check('too_big', 'mem_limit')
        self.assertIn(b'allocation-size-too-big', o['err'])

    def test_out_of_memory(self):
        # malloc 512 GiB: ASan báo out-of-memory khi mmap thất bại, hoặc chạm hard_rss_limit_mb khi mmap thành công (tuỳ overcommit của
        # máy); cả hai là báo cáo bộ nhớ.
        self.check('oom', 'mem_limit')

    def test_hard_rss_limit(self):
        env = dict(rq1.EXE_SAN_ENV, ASAN_OPTIONS=rq1.EXE_SAN_ENV['ASAN_OPTIONS'].replace(
            f'hard_rss_limit_mb={rq1.SAN_RSS_MB}', 'hard_rss_limit_mb=128'))
        self.assertIn('hard_rss_limit_mb=128', env['ASAN_OPTIONS'])
        o, _ = self.check('rss', 'mem_limit', env)
        self.assertIn(b'hard rss limit exhausted', o['err'])

    def test_signed_overflow(self):
        _, mk = self.check('signed_overflow', 'ub')
        self.assertIn('runtime error:', mk)

    def test_program_text_only(self):
        o, _ = self.check('program_text', 'no_report')
        self.assertEqual((o['status'], o['rc']), ('exit', 1))

    def test_exe_san_end_to_end(self):
        cs = lambda n: dict(ok=True, bin=self.bin[n])
        self.assertEqual(rq1._exe_san(cs('hbo_after_oom_text'), [], '', 10, None)['status'], 'ub')
        self.assertEqual(rq1._exe_san(cs('too_big'), [], '', 10, None)['status'], 'inconclusive')
        r = rq1._exe_san(cs('program_text'), [], '', 10, None)
        self.assertEqual((r['status'], r['markers']), ('no_report', []))


def _gcc_asan_ok():
    if not shutil.which('gcc'): return False
    d = tempfile.mkdtemp(prefix='f2-gcc-probe-'); c = os.path.join(d, 'p.c')
    with open(c, 'w') as f: f.write('int main(void){return 0;}\n')
    return subprocess.run(['gcc', '-fsanitize=address', c, '-o', os.path.join(d, 'p')], capture_output=True).returncode == 0


@unittest.skipUnless(_gcc_asan_ok(), 'cần gcc link được libasan')
class RealGccM4(unittest.TestCase):
    def test_gcc_allocation_size_too_big_is_memory(self):
        d = tempfile.mkdtemp(prefix='f2-gcc-'); c = os.path.join(d, 'big.c'); b = os.path.join(d, 'big')
        with open(c, 'w') as f: f.write(PROGS['too_big'])
        subprocess.run(['gcc', '-fsanitize=address,undefined', '-g', c, '-o', b], check=True, capture_output=True)
        o = OB.run_exe(b, [], '', 30, dict(rq1.EXE_SAN_ENV), san=True)
        self.assertIn(b'allocation-size-too-big', o['err'])
        self.assertEqual(rq1.san_status(o['err']), ('mem_limit', []), o['err'][-600:])


FAKE_RUNNER = textwrap.dedent('''\
    #!/usr/bin/env python3
    # Runner giả: cùng tham số với runner TRACTOR; ghi report JSON một dòng như cando2 (Serialize của TestOutcome). Không ghi dump, như khi
    # tiến trình con chết vì sanitizer dừng chương trình.
    import json, os, sys
    a = sys.argv[1:]
    v = dict(result=os.environ['FAKE_RESULT'], output=dict(stdout=os.environ['FAKE_STDOUT'], stderr=open(os.environ['FAKE_STDERR']).read()))
    if v['result'] == 'UnknownFailure': v['wait_status'] = 256
    with open(a[a.index('--output') + 1], 'w') as f: f.write(json.dumps({a[a.index('--vectors') + 1]: v}))
''')


class LibSanFakeRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix='f2-lib-')
        cls.runner = os.path.join(cls.d, 'fake_runner')
        with open(cls.runner, 'w') as f: f.write(FAKE_RUNNER)
        os.chmod(cls.runner, os.stat(cls.runner).st_mode | stat.S_IEXEC)
        cls.vec = os.path.join(cls.d, 'v.json')
        with open(cls.vec, 'w') as f: json.dump({'lib_state_in': {}, 'lib_state_out': {}}, f)
        cls.n = 0

    def san(self, stdout, stderr, result='UnknownFailure'):
        type(self).n += 1
        ef = os.path.join(self.d, f'err{self.n}.txt')
        with open(ef, 'w') as f: f.write(stderr)
        env = dict(FAKE_RESULT=result, FAKE_STDOUT=stdout, FAKE_STDERR=ef)
        dump = os.path.join(self.d, f'x{self.n}.dump')
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)        # lib_san truyền LIB_SAN_ENV cố định; runner giả đọc biến của tiến trình cha
        try:
            r = rq1.lib_san(self.runner, self.d, self.vec, 10, dump, None)
        finally:
            for k, v in old.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
        self.assertFalse(os.path.exists(dump + '.report.json'))
        return r

    def test_k1_program_oom_text_plus_hbo_is_ub(self):
        r = self.san('error: out of memory\n', 'error: out of memory\n' + HBO)
        self.assertEqual((r['status'], r['markers'], r['san_result']), ('ub', ['AddressSanitizer'], 'UnknownFailure'))

    def test_memory_report_is_inconclusive(self):
        for err in (TOO_BIG_GCC, OOM, RSS):
            r = self.san('', err)
            self.assertEqual((r['status'], r['markers']), ('inconclusive', []), err[:60])

    def test_program_text_is_no_report(self):
        r = self.san(PROGRAM_TEXT, PROGRAM_TEXT, result='Pass')
        self.assertEqual((r['status'], r['markers']), ('no_report', []))

    def test_ubsan_report(self):
        r = self.san('', UBSAN)
        self.assertEqual((r['status'], r['markers']), ('ub', ['runtime error:', 'UndefinedBehaviorSanitizer']))

    @unittest.skipUnless(_clang_ok(), 'cần clang và runtime ASan (libclang-rt)')
    def test_real_clang_stderr_in_report(self):
        # stderr thật của chương trình clang (in "error: out of memory" rồi heap-buffer-overflow), bọc vào report một dòng.
        d = tempfile.mkdtemp(prefix='f2-lib-real-'); c = os.path.join(d, 'h.c'); b = os.path.join(d, 'h')
        with open(c, 'w') as f: f.write(PROGS['hbo_after_oom_text'])
        subprocess.run(['clang'] + SAN_CFLAGS + [c, '-o', b], check=True, capture_output=True)
        o = OB.run_exe(b, [], '', 30, dict(rq1.EXE_SAN_ENV), san=True)
        r = self.san('', o['err'].decode('utf-8', 'replace'))
        self.assertEqual((r['status'], r['markers']), ('ub', ['AddressSanitizer']))


class LibStderrOnly(unittest.TestCase):
    """Le chọn 25/10: library chỉ xét stderr của lời gọi, như executable; dạng tiêu đề sanitizer do chương trình in ra stdout không tính."""
    def test_stdout_ignored(self):
        import json as _j, tempfile as _t
        d = _t.mkdtemp(); rp = f'{d}/r.json'
        _j.dump({'v0': {'result': 'Pass', 'output': {'stdout': '==1==ERROR: AddressSanitizer: heap-buffer-overflow\n', 'stderr': ''}}},
                open(rp, 'w'))
        st = rq1.lib_san_streams(rp, dict(stdout='SUMMARY: AddressSanitizer: SEGV\n', stderr=''))
        self.assertEqual(rq1.san_status(st)[0], 'no_report')
        _j.dump({'v0': {'result': 'Pass', 'output': {'stdout': '', 'stderr': '==1==ERROR: AddressSanitizer: heap-buffer-overflow\n'}}},
                open(rp, 'w'))
        self.assertEqual(rq1.san_status(rq1.lib_san_streams(rp, {}))[0], 'ub')


if __name__ == '__main__':
    unittest.main()
