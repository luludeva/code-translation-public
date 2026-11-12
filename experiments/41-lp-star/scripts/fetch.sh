#!/usr/bin/env bash
# Tải đúng các file cần cho exp 41 từ các nhánh kết quả của lượt chính, qua GitHub API (không fetch cả nhánh, vì nhánh chứa hàng GB log).
# Dùng: bash experiments/41-lp-star/scripts/fetch.sh OUTDIR
# Commit của từng nhánh ghi ở results/provenance.txt; script dùng đúng commit đó.
set -euo pipefail
OUT=${1:?thiếu OUTDIR}
REPO=luludeva/code-translation
HERE=$(cd "$(dirname "$0")/.." && pwd)
EXE_CASES='012_uninit_int_ptr|017_signed_length_confusion|pointer_comparison_ascii_art|perlin_noise'
LIB_CASES='008_long_run_lib|021_complex_goto_lib|032_comma_operator_lib|arr_push_lib|hm_geti_lib|pow43_lib|004_nineality_sieve_lib|006_static_alias_lib|sh_geti_lib'
while read -r branch sha; do
  case $branch in
    *exe*) pat="(/div/.*($EXE_CASES))|rq1-exe.jsonl\$" ;;
    *) pat="(/div/.*($LIB_CASES)__)|rq1-lib.jsonl\$" ;;
  esac
  gh api "repos/$REPO/git/trees/$sha?recursive=1" \
    --jq ".tree[] | select(.type==\"blob\") | select(.path|test(\"$pat\")) | \"\(.sha) \(.path)\"" |
  while read -r bsha path; do
    dst="$OUT/$branch/${path#ci-out/$branch/}"; mkdir -p "$(dirname "$dst")"
    gh api "repos/$REPO/git/blobs/$bsha" -H "Accept: application/vnd.github.raw" > "$dst"
  done
done < "$HERE/results/provenance.txt"
