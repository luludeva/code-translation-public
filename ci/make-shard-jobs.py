#!/usr/bin/env python3
"""Chuẩn bị lượt chính RQ1 trên nhiều máy (rà soát kỹ thuật 2026-10-23, C5; ci/MULTI-RUNNER.md).

Chia case của P_rep thành N shard cân tải rồi sinh N script job `ci/jobs/rq1-main-<kind>-<i>of<N>.sh`, mỗi script chạy harness.rq1 với
danh sách case tường minh (--cases), đủ 3 seed, ngân sách đã chốt (memo W6). Mọi bản dịch của một case nằm trên cùng một máy, nên phía C
của case chạy một lần và mọi hệ được so trên cùng máy (MULTI-RUNNER.md).

Cân tải: tham lam theo chi phí giảm dần (LPT). Chi phí một case = số bản dịch P_rep của case nhân (1 + tổng run_secs của census cho case
đó). Đây là ước lượng thô; khi có số đo thời gian sau sửa (exp 14, Việc 7), thay bằng số đo theo case.
Lượt chính còn khoá tới Protocol Freeze: harness.rq1 từ chối chạy khi thiếu --pilot, nên script sinh ra chưa chạy được.

Cách dùng: python3 ci/make-shard-jobs.py --kind exe|lib --n 3 [--dry-run]"""
import argparse, collections, os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from harness import pairs as PR                                       # noqa: E402

BUDGET = dict(exe='--budget 30000 --afl-execs 100000', lib='--n-inputs 2000')   # memo W6, R5
TEMPLATE = '''#!/usr/bin/env bash
# Lượt chính RQ1, {kind}, shard {i}/{n} (sinh bởi ci/make-shard-jobs.py; {ncase} case, {npair} bản dịch, chi phí ước lượng {cost:.0f}).
set -euo pipefail
ROOT="$PWD"; OUT="$ROOT/ci-out/rq1-main-{kind}-{i}of{n}"; mkdir -p "$OUT"
export CORPUS=$HOME/corpus HARNESS_BUILD=$HOME/build/rq1-main RUSTUP_TOOLCHAIN=1.97.0 AFL_SKIP_CPUFREQ=1 AFL_NO_AFFINITY=1
export TRACTOR_PATHS="Public-Tests/B01_organic Public-Tests/B01_synthetic Public-Tests/B02_organic Public-Tests/B02_synthetic Public-Tests/P00_perlin_noise Public-Tests/P01_sphincs_plus"
HP=""; for s in kiro claude codex-gpt54 c2rust laertes c2saferrust smartc2rust gpt-5.4 kimi gemini-3.1-pro-preview; do HP="$HP /Test-Corpus/$s/"; done
export HARVEST_PATHS="$HP"
avail=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
[ "$avail" -ge 15 ] || {{ echo "Chỉ còn ${{avail}} GiB trống, dừng job"; exit 3; }}
source ci/disk-guard.sh
bash ci/setup-corpus.sh
dpkg -s libclang-rt-18-dev >/dev/null 2>&1 || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q libclang-rt-18-dev >/dev/null || true
{{ rustc --version; clang --version | head -1; afl-fuzz -h 2>&1 | grep -m1 -o 'afl-fuzz++[0-9.a-z]*' || true; nproc; uname -srm
  echo "harness $(git rev-parse HEAD)"; }} > "$OUT/env.txt"
trap 'dg_stop' EXIT
source ci/mem-cgroup.sh
python3 -m harness.rq1 --kind {kind} --tag main --out "$OUT" --seeds 0,1,2 --workers 6 --timeout 10 {budget} \\
  --cases {cases}
bash ci/auto-shutdown.sh
'''


def case_costs(kind):
    ps = PR.prep_pairs(kind)
    cost, npair = collections.Counter(), collections.Counter()
    for p in ps:
        k = (p['bundle'], p['tractor_case']); npair[k] += 1; cost[k] += p.get('run_secs') or 0
    return {k: npair[k] * (1 + cost[k]) for k in npair}, npair


def lpt(costs, n):
    bins = [[0.0, []] for _ in range(n)]
    for k, c in sorted(costs.items(), key=lambda x: (-x[1], x[0])):
        b = min(bins, key=lambda b: b[0]); b[0] += c; b[1].append(k)
    return bins


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--kind', choices=['exe', 'lib'], required=True)
    ap.add_argument('--n', type=int, required=True); ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    costs, npair = case_costs(a.kind)
    bins = lpt(costs, a.n)
    for i, (c, ks) in enumerate(bins, 1):
        name = f'ci/jobs/rq1-main-{a.kind}-{i}of{a.n}.sh'
        print(f'{name}: {len(ks)} case, {sum(npair[k] for k in ks)} bản dịch, chi phí {c:.0f} ({100 * c / sum(costs.values()):.1f}%)')
        if a.dry_run: continue
        open(name, 'w').write(TEMPLATE.format(kind=a.kind, i=i, n=a.n, ncase=len(ks), npair=sum(npair[k] for k in ks), cost=c,
                                              budget=BUDGET[a.kind], cases=','.join(f'{b}/{c}' for b, c in sorted(ks))))


if __name__ == '__main__':
    main()
