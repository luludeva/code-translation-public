#!/usr/bin/env bash
# exp 36: chạy held-out trên cloud container (README, Thay đổi 2026-11-05). Chạy lại được: harness.rq1 bỏ qua (case, seed) đã có bản ghi,
# unit có done.txt thì bỏ qua. Dùng: bash experiments/36-heldout/scripts/run_local.sh OUT
set -euo pipefail
ROOT="$PWD"; OUT=$(realpath -m "$1"); mkdir -p "$OUT"; PLAN="$ROOT/experiments/36-heldout/results/plan.json"; PROV="$OUT/provenance.txt"
REAL_CORPUS="${REAL_CORPUS:-$HOME/corpus}"
export RUSTUP_TOOLCHAIN=stable AFL_SKIP_CPUFREQ=1 AFL_NO_AFFINITY=1
{ echo "== $(date -u +%FT%TZ) harness $(git rev-parse HEAD) dirty=$(git status --porcelain harness | wc -l)"; rustc --version; clang --version | head -1
  afl-fuzz -h 2>&1 | grep -m1 -o 'afl-fuzz++[0-9.a-z]*' || true; nproc; uname -srm
  echo "tractor $(git -C "$REAL_CORPUS/tractor" rev-parse HEAD) harvest $(git -C "$REAL_CORPUS/harvest" rev-parse HEAD)"; } >> "$PROV"
budget() { python3 -c "
import sys
from harness.sweep import LEVELS
t = LEVELS['x10'][sys.argv[1]]
print(f'--budget {t[\"budget\"]} --afl-execs {t[\"afl_execs\"]}' if sys.argv[1] == 'exe' else f'--n-inputs {t[\"n_inputs\"]}')" "$1"; }
for u in $(python3 -c "import json; print(' '.join(x['unit'] for x in json.load(open('$PLAN'))['units']))"); do
  [ -f "$OUT/$u/done.txt" ] && continue
  read -r kind bc < <(python3 -c "import json; x=next(x for x in json.load(open('$PLAN'))['units'] if x['unit']=='$u'); print(x['kind'], x['bundle']+'/'+x['case'])")
  OV="$OUT/overlay/$u"; mkdir -p "$OUT/$u"
  [ -d "$OV" ] || python3 experiments/36-heldout/scripts/overlay.py "$PLAN" "$u" "$REAL_CORPUS" "$OV" > "$OUT/$u/overlay.json"
  echo "$(date -u +%T) $u $kind $bc $(head -c 200 "$OUT/$u/overlay.json")" | tee -a "$PROV"
  t0=$(date +%s)
  CORPUS="$OV" HARNESS_BUILD="$HOME/build/heldout/$u" python3 -m harness.rq1 --pilot --kind "$kind" --out "$OUT/$u" --tag x10 \
    --seeds 0,1,2 --workers 2 --timeout 10 $(budget "$kind") --cases "$bc" >> "$OUT/$u/rq1-output.txt" 2>&1 \
    || { echo "$u: harness.rq1 thoát khác 0" | tee -a "$PROV"; continue; }
  echo "$(date -u +%T) $u: $(( $(date +%s) - t0 )) giây" | tee -a "$PROV"; date -u +%FT%TZ > "$OUT/$u/done.txt"
  rm -rf "${HOME:?}/build/heldout/$u"
done
python3 experiments/36-heldout/scripts/evaluate.py "$PLAN" "$OUT" > "$OUT/heldout-result.json" && echo "EVALUATED" | tee -a "$PROV"
