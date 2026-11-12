"""Nguồn P_rep library đổi được bằng biến môi trường (Q9 (a), luật kế thừa tag 2026-10-26); manifest ghi nguồn và sha256.
Chạy: python3 -m unittest tests.test_p_rep_source"""
import importlib, os, subprocess, sys, tempfile, unittest

from harness import pairs as PR
from harness.config import REPO


class Source(unittest.TestCase):
    def test_default_unchanged(self):
        self.assertTrue(PR.DEFAULT['lib']['census'].endswith('experiments/06-library-census/results/census-lib.jsonl'))
        i = PR.source_info('lib')
        self.assertEqual(len(i['census']['sha256']), 64)

    def test_env_override_in_fresh_process(self):
        f = tempfile.mktemp(suffix='.jsonl'); open(f, 'w').write('')
        code = 'from harness import pairs as P; print(P.DEFAULT["lib"]["census"]); print(P.DEFAULT["exe"]["census"])'
        out = subprocess.run([sys.executable, '-c', code], cwd=REPO, capture_output=True, text=True,
                             env=dict(os.environ, HARNESS_P_REP_LIB_CENSUS=f)).stdout.split()
        self.assertEqual(out[0], f); self.assertTrue(out[1].endswith('census-exe-ec2.jsonl'))


if __name__ == '__main__':
    unittest.main()
