#!/usr/bin/env bash
# Regenerates every macro file that the thesis reads from the result files in this snapshot, then builds the thesis.
# writing/generated/setup-numbers.tex is not regenerated: its inputs are raw execution records that are not part of the snapshot.
set -euo pipefail
cd "$(dirname "$0")"
IN=$(mktemp -d)
cp experiments/30-main-s0/results/metrics.json experiments/30-main-s0/results/metrics-split.json "$IN"/
cp experiments/33-nonrep-evidence/results/analysis-exe.json experiments/33-nonrep-evidence/results/analysis-lib.json "$IN"/
python3 writing/scripts/gen-census-macros.py
python3 writing/scripts/gen-population-table.py
python3 writing/scripts/gen-method-macros.py --harness-root .
python3 writing/scripts/gen-rq-macros.py --in "$IN" --harness-root .
python3 writing/scripts/gen-rq-tables.py --in "$IN"
for g in robust review ax extra sanbound sanlog; do python3 "writing/scripts/gen-$g-macros.py"; done
python3 writing/scripts/gen-v3-macros.py
(cd writing && latexmk -xelatex -interaction=nonstopmode main.tex)
