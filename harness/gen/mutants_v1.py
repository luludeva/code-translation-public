"""Chép nguyên văn từ `experiments/04-coverage-pilot/scripts/mutants_v1.py` (xem `VENDOR-mutants.md`).

Chỉ lấy hằng OPS, LIT và hàm `sites_of`, `vec_fails` (vị trí đột biến, toán tử, vector bắt); bỏ phần import thí nghiệm, `layer_inputs`, `main`.
Khác nguồn (ngoài các khối chép): `SEED` tách khỏi dòng `N, SEED, LAYER_BUDGET, TIMEOUT = 12, 0, 3000, 2`; `RUNNER` mặc định là bản
`ci/setup-corpus.sh` dựng (`$CORPUS/cando2/...`), biến môi trường RUNNER vẫn thắng như nguồn. Seed xáo vẫn là biến module như nguồn:
`harness.mutants` đặt `SEED` trước mỗi lần gọi (đúng cách `accept_exe.sites_cov` của exp 08 làm)."""
import glob, json, os, random, re, subprocess

RUNNER = os.environ.get('RUNNER', os.environ.get('CORPUS', os.path.expanduser('~/corpus')) + '/cando2/target/release/cando_binrunner')
SEED = 0
OPS = [(r' < ', ' <= '), (r' > ', ' >= '), (r' == ', ' != '), (r' != ', ' == '), (r' && ', ' || '), (r' \+ ', ' - '), (r' - ', ' + ')]
LIT = re.compile(r'(?<![\w.])(\d+)(?=(i32|u32|usize|i64|u64|u8|i8)?\b)')

def sites_of(src):
    sites = []
    for f in sorted(glob.glob(f'{src}/src/*.rs')):
        rel = os.path.relpath(f, src)
        for i, line in enumerate(open(f, errors='ignore')):
            s = line.strip()
            if not s or s.startswith(('//', '#', 'use ', 'extern', 'pub use', 'mod ')) or 'static' in s and '[' in s: continue
            for pat, rep in OPS:
                if '"' in line: continue
                for m in re.finditer(pat, line): sites.append((rel, i, m.start(), m.end(), rep, pat))
            for m in LIT.finditer(line):
                if 'fn ' in s or '"' in line or "'" in line or '[' in line[:m.start()][-3:]: continue
                sites.append((rel, i, m.start(1), m.end(1), str(int(m.group(1)) + 1), 'lit+1'))
    rng = random.Random(SEED); rng.shuffle(sites); return sites

def vec_fails(binp, troot, out):
    subprocess.run([RUNNER, '-l', 'quiet', '-t', troot, '--timeout', '10', '-o', out, 'bin', '-n', binp], capture_output=True)
    if not os.path.exists(out): return None
    return sorted(k for k, v in json.load(open(out)).items() if v['result'] not in ('Pass', 'Skip'))
