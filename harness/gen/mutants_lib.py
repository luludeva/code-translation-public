"""Chép nguyên văn từ `experiments/07-library-controls/scripts/mutants_lib.py` (xem `VENDOR-mutants.md`).

Chỉ lấy hằng OPS, LIT, TOOLS và hàm `sites_of` (lọc coverage), `vec_fails`, `coverage`; bỏ phần import exp 05, `main`.
Khác nguồn (ngoài các khối chép):
  - `make_root` của nguồn dựng thư mục gốc kiểu exp 05 (`B/c/<case>`, `S.SYSTEMS`); thay bằng hàm cùng chữ ký gọi `build.lib_root`
    với tag = tên gốc (`cov-<hệ>`), thông tin case lấy từ `_INFO[tp]` (do `harness.mutants` gán, kết quả `build.build_lib_case`).
  - `TOOLS` bọc try: máy không có rustc vẫn import được (giá trị như nguồn khi có rustc).
  - `B` là biến module do `harness.mutants` gán (nguồn lấy `spike_lib.B`). `SEED` như nguồn, `harness.mutants` đặt trước mỗi lần gọi."""
import glob, json, os, random, re, shutil, subprocess

B = None
SEED = 0
_INFO = {}
OPS = [(r' < ', ' <= '), (r' > ', ' >= '), (r' == ', ' != '), (r' != ', ' == '), (r' && ', ' || '), (r' \+ ', ' - '), (r' - ', ' + ')]
LIT = re.compile(r'(?<![\w.])(\d+)(?=(i32|u32|usize|i64|u64|u8|i8)?\b)')
try:
    TOOLS = subprocess.run(['rustc', '--print', 'sysroot'], capture_output=True, text=True).stdout.strip() + '/lib/rustlib/x86_64-unknown-linux-gnu/bin'
except FileNotFoundError:          # máy không có rustc (VM của Le): module vẫn import được
    TOOLS = ''


def sites_of(src, covered):
    sites = []
    for f in sorted(glob.glob(f'{src}/src/**/*.rs', recursive=True)):
        rel = os.path.relpath(f, src)
        for i, line in enumerate(open(f, errors='ignore')):
            if (rel, i + 1) not in covered: continue
            s = line.strip()
            if not s or s.startswith(('//', '#', 'use ', 'extern', 'pub use', 'mod ')) or 'static' in s and '[' in s: continue
            if '"' not in line:
                for pat, rep in OPS:
                    for m in re.finditer(pat, line): sites.append((rel, i, m.start(), m.end(), rep, pat))
            for m in LIT.finditer(line):
                if 'fn ' in s or '"' in line or "'" in line or '[' in line[:m.start()][-3:]: continue
                sites.append((rel, i, m.start(1), m.end(1), str(int(m.group(1)) + 1), 'lit+1'))
    rng = random.Random(SEED); rng.shuffle(sites); return sites


def make_root(name, case, tp, rust_dir):
    """Thay `make_root` của nguồn: thư mục gốc runner qua `build.lib_root` (tag = name, mỗi tag một thư mục)."""
    from ..build import lib_root
    return lib_root(B, _INFO[tp], 'c', rust_dir, tag=name)


def vec_fails(runner_bin, root, out):
    subprocess.run([runner_bin, '-l', 'quiet', '-t', root, '--rust', '--timeout', '10', '-o', out, 'lib'], capture_output=True, timeout=1800)
    if not os.path.exists(out): return None
    return sorted(k for k, v in json.load(open(out)).items() if v['result'] not in ('Pass', 'Skip'))


def coverage(sys_, case, tp, src, info, env):
    if os.environ.get('MUT_NO_COV'):   # chỉ để thử pipeline trên máy không có llvm-tools; coi mọi dòng là được chạy
        return {(os.path.relpath(f, src), i + 1) for f in glob.glob(f'{src}/src/**/*.rs', recursive=True)
                for i in range(len(open(f, errors='ignore').read().split(chr(10))))}, ''
    wd = f'{B}/mut-cov/{sys_}/{case}'; shutil.rmtree(wd, ignore_errors=True)
    shutil.copytree(src, wd, ignore=shutil.ignore_patterns('target', 'logs', 'c_src'))
    e = dict(env, RUSTFLAGS='-C instrument-coverage')
    p = subprocess.run(['cargo', 'build', '--release', '-q', '--target-dir', f'{wd}/target'], cwd=wd, env=e, capture_output=True, text=True)
    so = f'{wd}/target/release/lib{info["library"]}.so'
    if p.returncode or not os.path.exists(so): return None, 'build: ' + p.stderr[-500:]
    root = make_root(f'cov-{sys_}', case, tp, wd)
    prof = f'{wd}/prof'; os.makedirs(prof, exist_ok=True)
    subprocess.run([info['runner_bin'], '-l', 'quiet', '-t', root, '--rust', '--timeout', '10', 'lib'],
                   env=dict(os.environ, LLVM_PROFILE_FILE=f'{prof}/p-%p.profraw'), capture_output=True, timeout=1800)
    raws = glob.glob(f'{prof}/*.profraw')
    if not raws: return None, 'không có profraw'
    subprocess.run([f'{TOOLS}/llvm-profdata', 'merge', '-sparse', *raws, '-o', f'{wd}/m.profdata'], check=True)
    lcov = subprocess.run([f'{TOOLS}/llvm-cov', 'export', '-format=lcov', f'-instr-profile={wd}/m.profdata', so], capture_output=True, text=True).stdout
    covered, cur = set(), None
    for line in lcov.splitlines():
        if line.startswith('SF:'): cur = os.path.relpath(line[3:], wd)
        elif line.startswith('DA:') and cur:
            ln, c = line[3:].split(',')[:2]
            if int(c) > 0: covered.add((cur, int(ln)))
    return covered, ''
