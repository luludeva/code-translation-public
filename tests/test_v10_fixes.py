"""Ba sửa sau rà §3.3 v10 (Le chọn 25/10, decision-log cùng ngày): prefix khi không có dòng hoàn chỉnh (F1), dấu hiệu bộ nhớ chỉ từ sanitizer
và trình cấp phát, UB xét trước (F2), bản dịch không có input quan sát rời P_test với mã 'no_inputs' (F3, F7).
Chạy: python3 -m unittest tests.test_v10_fixes"""
import os, shutil, subprocess, tempfile, unittest
from unittest import mock

from harness import metrics as M
from harness import observe as OB
from harness import rq1


def nt(out): return dict(status='timeout', rc=None, sig=None, out=out, err=b'')


class NtPrefix(unittest.TestCase):
    def test_no_complete_line_is_empty_match(self):
        self.assertEqual(OB.nt_prefix(nt(b'1.0-nan'), nt(b'1.0nan')), (True, 0))
        self.assertEqual(OB.nt_prefix(nt(b'abc'), nt(b'abd')), (True, 0))

    def test_complete_lines_compared_partial_dropped(self):
        self.assertEqual(OB.nt_prefix(nt(b'ab\ncd'), nt(b'ab\nce')), (True, 3))
        self.assertEqual(OB.nt_prefix(nt(b'ab\nx'), nt(b'ac\ny')), (False, 3))

    def test_counter(self):
        import collections
        cnt = collections.Counter()
        rq1.obs_note(cnt, 'exe', nt(b'a'), nt(b'b'), True, info=dict(nt_prefix_bytes=0))
        rq1.obs_note(cnt, 'exe', nt(b'a\n'), nt(b'a\n'), True, info=dict(nt_prefix_bytes=2))
        self.assertEqual((cnt['both_nt_match'], cnt['both_nt_prefix_zero'], cnt['both_nt_prefix_bytes']), (2, 1, 2))


class SanStatus(unittest.TestCase):
    def test_ub_before_memory(self):
        r = b'x.c:3:5: runtime error: signed integer overflow\n==1==ERROR: AddressSanitizer: out of memory: allocator is trying to allocate\n'
        self.assertEqual(rq1.san_status(r)[0], 'ub')

    def test_asan_memory_reports(self):
        for r in (b'==1==ERROR: AddressSanitizer: requested allocation size 0x1 exceeds maximum supported size\n'
                  b'SUMMARY: AddressSanitizer: allocation-size-too-big\n',
                  b'==1==ERROR: AddressSanitizer: hard rss limit exhausted (2048Mb vs 2049Mb)\n',
                  b'==1==ERROR: AddressSanitizer: out of memory: allocator is trying to allocate 0x100 bytes\n'
                  b'SUMMARY: AddressSanitizer: out-of-memory\n'):
            self.assertEqual(rq1.san_status(r)[0], 'mem_limit', r)

    def test_program_printed_text_ignored(self):
        self.assertEqual(rq1.san_status(b'error: out of memory\nallocation failed\n')[0], 'no_report')

    def test_other_asan_is_ub(self):
        self.assertEqual(rq1.san_status(b'==1==ERROR: AddressSanitizer: heap-buffer-overflow on address\n')[0], 'ub')
        self.assertEqual(rq1.san_status(b'AddressSanitizer:DEADLYSIGNAL\n==1==ERROR: AddressSanitizer: SEGV on unknown address\n')[0], 'ub')


class MemMarkers(unittest.TestCase):
    def test_allocator_only(self):
        self.assertEqual(OB.MEM_MARKERS, (b'memory allocation of', b'cannot allocate memory'))

    @unittest.skipUnless(shutil.which('cc'), 'cần trình biên dịch C')
    def test_program_printing_out_of_memory_is_not_mem_limit(self):
        d = tempfile.mkdtemp()
        open(f'{d}/m.c', 'w').write('#include <stdio.h>\nint main(void){fputs("out of memory\\n", stderr); return 1;}\n')
        subprocess.run(['cc', '-o', f'{d}/m', f'{d}/m.c'], check=True)
        o = OB.run_exe(f'{d}/m', [], '', 10)
        self.assertEqual((o['status'], o['rc']), ('exit', 1))


class NoInputs(unittest.TestCase):
    def test_pair_status(self):
        self.assertEqual(rq1.pair_status(dict(observed=0), 0), 'no_inputs')
        self.assertEqual(rq1.pair_status(dict(rust_build_failed=1), 0), 'rust_build_failed')
        self.assertEqual(rq1.pair_status(dict(observed=3), 3), 'P_test')

    def test_lib_case_without_inputs_is_recorded(self):
        info = dict(runner_ok=True, c_ok=True, library='x')
        with mock.patch.object(rq1.BD, 'build_lib_case', return_value=info), \
             mock.patch.object(rq1.BD, 'build_rust_lib', side_effect=[dict(ok=True), dict(ok=False)]), \
             mock.patch.object(rq1, '_lib_inputs', return_value=([], None, 0)), \
             mock.patch.object(rq1, 'write_inputs', return_value=dict(n=0)):
            r = rq1.rq1_lib_case('/b', 'B01_x', 'c', [dict(system='a', harvest_case='c'), dict(system='b', harvest_case='c')],
                                 0, dict(n_inputs=10), 10, '/tmp/none/div/x.jsonl', 't')
        self.assertEqual(r['status'], 'done'); self.assertEqual(r['pair_status'], {'a': 'no_inputs', 'b': 'rust_build_failed'})
        T = M.rq1_translations([dict(r, seed=s) for s in (0, 1, 2)], {}, {}, [0, 1, 2])
        self.assertEqual(T[('B01_x', 'c', 'a')]['status'], 'no_inputs')
        self.assertEqual(M.summarize_rq1(T, 'lib')['by_group']['all']['leave']['no_inputs'], 1)


if __name__ == '__main__':
    unittest.main()
