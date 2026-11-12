"""Chép nguyên văn hàm `covered_lines`, `sites_cov` từ `experiments/08-harness-v2/scripts/accept_exe.py` (xem `VENDOR-mutants.md`).

Coverage executable của exp 08: build bản dịch gốc với `-C instrument-coverage` (luôn `RUSTC_BOOTSTRAP=1`, như nguồn), chạy driver trên
mọi vector gốc (`gen.v1.run`, timeout 5 giây), đọc lcov. `sites_cov`: `mutants_v1.sites_of` (xáo theo seed trên MỌI vị trí) rồi mới lọc
dòng được chạy; library thì lọc trước rồi xáo (`mutants_lib.sites_of`). Giữ nguyên hai thứ tự để bộ seed 1 sinh lại đúng.
Biến module `B`, `H`, `HCASE`, `MUT_SEED` do `harness.mutants` gán (nguồn đọc từ môi trường và hằng của script)."""
import glob, os, shutil, subprocess

from . import mutants_v1 as MV
from .v1 import run
from .mutants_lib import TOOLS

B = H = None
HCASE = {}
MUT_SEED = 1


def covered_lines(sys_, case, seeds):
    if os.environ.get('V2_NO_COV'):   # chỉ dùng khi chạy thử cục bộ không có llvm-tools khớp rustc: coi mọi dòng là được chạy
        s0 = f'{B}/src/{sys_}/{case}'
        return {(os.path.relpath(f, s0), i + 1) for f in glob.glob(f'{s0}/src/*.rs') for i in range(len(open(f, errors='ignore').read().split(chr(10))))}, ''
    src = f'{H}/{sys_}/{HCASE[case]}/verified'
    if not os.path.isdir(src): src = f'{H}/{sys_}/{HCASE[case]}/translated'
    wd = f'{B}/v2cov/{sys_}/{case}'; shutil.rmtree(wd, ignore_errors=True)
    shutil.copytree(src, wd, ignore=shutil.ignore_patterns('target', 'logs'))
    env = dict(os.environ, RUSTFLAGS='-C instrument-coverage', RUSTC_BOOTSTRAP='1')
    p = subprocess.run(['cargo', 'build', '--release', '-q', '--target-dir', f'{wd}/target'], cwd=wd, env=env, capture_output=True, text=True)
    if p.returncode: return None, 'build: ' + p.stderr[-500:]
    prof = f'{wd}/prof'; os.makedirs(prof, exist_ok=True)
    old = os.environ.get('LLVM_PROFILE_FILE'); os.environ['LLVM_PROFILE_FILE'] = f'{prof}/p-%m.profraw'
    for s in seeds: run(f'{wd}/target/release/driver', s['argv'], s['stdin'], 5)
    if old is None: os.environ.pop('LLVM_PROFILE_FILE', None)
    else: os.environ['LLVM_PROFILE_FILE'] = old
    raws = glob.glob(f'{prof}/*.profraw')
    if not raws: return None, 'không có profraw'
    subprocess.run([f'{TOOLS}/llvm-profdata', 'merge', '-sparse', *raws, '-o', f'{wd}/m.profdata'], check=True)
    lcov = subprocess.run([f'{TOOLS}/llvm-cov', 'export', '-format=lcov', f'-instr-profile={wd}/m.profdata', f'{wd}/target/release/driver'],
                          capture_output=True, text=True).stdout
    cov, cur = set(), None
    for line in lcov.splitlines():
        if line.startswith('SF:'): cur = os.path.relpath(line[3:], wd)
        elif line.startswith('DA:') and cur:
            ln, c = line[3:].split(',')[:2]
            if int(c) > 0: cov.add((cur, int(ln)))
    return cov, ''


def sites_cov(src, covered):
    """mutants_v1.sites_of, chỉ giữ dòng được chạy, xáo theo MUT_SEED."""
    MV.SEED = MUT_SEED
    sites = MV.sites_of(src)   # đã xáo bằng Random(MV.SEED)
    return [s for s in sites if (s[0], s[1] + 1) in covered]
