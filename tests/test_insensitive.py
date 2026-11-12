"""Executable không đọc input (harness/insensitive.py, decision-log 2026-10-24)."""
import os, subprocess, tempfile, unittest

from harness import insensitive as II


def build(src):
    d = tempfile.mkdtemp(prefix='ii-'); os.makedirs(f'{d}/src')
    open(f'{d}/src/main.c', 'w').write(src); b = f'{d}/prog'
    subprocess.run(['gcc', f'{d}/src/main.c', '-o', b], check=True, capture_output=True)
    return b, d


class Criterion(unittest.TestCase):
    def test_no_input(self):
        b, d = build('#include <stdio.h>\nint main(void) { /* argv */ puts("x"); return 0; }\n')
        ok, ev = II.check(b, d); self.assertTrue(ok, ev)

    def test_empty_parens(self):
        b, d = build('#include <stdio.h>\nint main() { puts("x"); return 0; }\n')
        self.assertTrue(II.check(b, d)[0])

    def test_reads_stdin(self):
        b, d = build('#include <stdio.h>\nint main(void) { char s[8]; if (fgets(s, 8, stdin)) puts(s); return 0; }\n')
        ok, ev = II.check(b, d); self.assertFalse(ok); self.assertIn('fgets', ev['input_syms'])

    def test_scanf(self):
        b, d = build('#include <stdio.h>\nint main(void) { int x; return scanf("%d", &x); }\n')
        self.assertFalse(II.check(b, d)[0])

    def test_argv(self):
        b, d = build('#include <stdio.h>\nint main(int argc, char **argv) { puts(argc > 1 ? argv[1] : "x"); return 0; }\n')
        ok, ev = II.check(b, d); self.assertFalse(ok); self.assertEqual(ev['input_syms'], [])

    def test_getenv(self):
        b, d = build('#include <stdio.h>\n#include <stdlib.h>\nint main(void) { puts(getenv("HOME")); return 0; }\n')
        self.assertFalse(II.check(b, d)[0])

    def test_open_file(self):
        b, d = build('#include <stdio.h>\nint main(void) { FILE *f = fopen("/dev/urandom", "r"); return f == 0; }\n')
        self.assertFalse(II.check(b, d)[0])

    def test_static_binary_not_flagged(self):
        d = tempfile.mkdtemp(); os.makedirs(f'{d}/src'); open(f'{d}/src/m.c', 'w').write('int main(void) { return 0; }\n')
        b = f'{d}/p'
        if subprocess.run(['gcc', '-static', f'{d}/src/m.c', '-o', b], capture_output=True).returncode: self.skipTest('không có libc tĩnh')
        self.assertFalse(II.check(b, d)[0])

    def test_main_in_comment_or_string_ignored(self):
        b, d = build('#include <stdio.h>\n/* int main(int argc, char **argv) { } */\nint main(void) { puts("main(int argc) {"); return 0; }\n')
        self.assertTrue(II.check(b, d)[0])


if __name__ == '__main__':
    unittest.main()
