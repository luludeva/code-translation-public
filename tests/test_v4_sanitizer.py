"""V4: C-san (cờ của harness) báo ở ca UB, không báo ở ca sạch. Cần clang. Chạy: python3 -m unittest tests.test_v4_sanitizer
Sửa 2026-10-26 (Le chọn, hàng đợi master plan dòng 24): kiểm qua rq1._exe_san (san_status, classify_san) như RQ1, giữ thêm kiểm
observe.san_flag."""
import os, subprocess, tempfile, unittest

from harness import observe as OB
from harness import rq1

PROGS = dict(
    signed_overflow=('#include <limits.h>\n#include <stdio.h>\nint main(int c,char**v){int x=INT_MAX; x+=c; printf("%d\\n",x); return 0;}', True),
    oob_read=('#include <stdio.h>\n#include <stdlib.h>\nint main(int c,char**v){int *a=malloc(4*sizeof(int)); a[0]=1; printf("%d\\n",a[c+3]); free(a); return 0;}', True),
    clean=('#include <stdio.h>\nint main(void){int a[4]={1,2,3,4}; printf("%d\\n",a[3]); return 0;}', False))
FLAGS = ['-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-g']


class San(unittest.TestCase):
    def test_programs(self):
        d = tempfile.mkdtemp()
        for name, (src, ub) in PROGS.items():
            c = os.path.join(d, name + '.c'); b = os.path.join(d, name); open(c, 'w').write(src)
            subprocess.run(['clang'] + FLAGS + [c, '-o', b], check=True, capture_output=True)
            o = OB.run_exe(b, [], '', 10, env={'ASAN_OPTIONS': 'detect_leaks=0'})
            self.assertEqual(OB.san_flag(o['err']), ub, (name, o['err'][-300:]))
            r = rq1._exe_san(dict(ok=True, bin=b), [], '', 10, None, o['status'])        # đường RQ1 dùng
            self.assertEqual(r['status'], 'ub' if ub else 'no_report', (name, r))


if __name__ == '__main__':
    unittest.main()
