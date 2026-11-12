"""V2: bộ sinh tất định (sinh hai lần cùng tham số cho cùng hash) và parity với bản trong thí nghiệm (V7 phần sinh input).
Cần corpus TRACTOR ở $CORPUS (case pilot) và clang (cdict). Chạy: python3 -m unittest tests.test_v2_gen"""
import hashlib, importlib.util, json, os, sys, tempfile, unittest

from harness.config import REPO, T
from harness.gen import cdict, stategen_v2
from harness.gen.libtypes import parse_runner
from harness.gen.v2_exe import gen_inputs_v2
from harness.vectors import exe_seeds, lib_seeds

EXE = [('B02_organic', 'qmath'), ('B02_synthetic', 'tu_linkage'), ('B02_synthetic', 'static_vars_fpts')]
LIB = [('B02_organic', 'aabb_lib'), ('B01_synthetic', '029_strcspn_lib'), ('P01_sphincs_plus', '055_blake_128f_s_gen_message_random_lib')]


def h(x): return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_exp(name, path):
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def avail(b, c): return os.path.isdir(f'{T}/{b}/{c}')


class Gen(unittest.TestCase):
    def test_exe_deterministic_and_parity(self):
        old = load_exp('harness_v2_exe_old', f'{REPO}/experiments/08-harness-v2/scripts/harness_v2_exe.py')
        v0 = load_exp('diffharness_v0_old', f'{REPO}/experiments/04-coverage-pilot/scripts/diffharness_v0.py')
        for b, c in EXE:
            if not avail(b, c): self.skipTest(f'thiếu {b}/{c}')
            troot = f'{T}/{b}/{c}'
            cd = cdict.extract(troot, tempfile.mkdtemp())
            seeds = exe_seeds(troot)
            for layer in ('M', 'MS'):
                x1 = gen_inputs_v2(seeds, layer, 300, 0, cd); x2 = gen_inputs_v2(seeds, layer, 300, 0, cd)
                self.assertEqual(h(x1), h(x2))
                ascii_only = all(all(ord(ch) < 128 for ch in s['stdin'] + ''.join(s['argv'])) for s in seeds)
                if ascii_only and layer == 'M':   # seed ASCII: tầng M giống hệt bản thí nghiệm; MS có seed riêng từ 25/10 (LAYER_RNG_OFFSET)
                    ref = old.gen_inputs_v2(v0.load_vectors(troot), layer, 300, 0, cd)
                    self.assertEqual(h(x1), h(ref), f'{c} {layer}')

    def test_lib_deterministic(self):
        for b, c in LIB:
            if not avail(b, c): self.skipTest(f'thiếu {b}/{c}')
            troot = f'{T}/{b}/{c}'
            parsed = parse_runner(open(f'{troot}/runner/src/main.rs').read())
            states = [s['vec']['lib_state_in'] for s in lib_seeds(troot)]
            cd = cdict.extract(troot, tempfile.mkdtemp())
            self.assertEqual(h(stategen_v2.generate(parsed, states, cd, 100, 0)), h(stategen_v2.generate(parsed, states, cd, 100, 0)))


if __name__ == '__main__':
    unittest.main()
