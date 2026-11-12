#!/usr/bin/env bash
# Experiment 02: tái lập pass/fail per-vector của HARVEST results trên TRACTOR Public-Tests.
# Oracle: cando_binrunner của chính TRACTOR (tools/cando2), chạy ngoài container.
# Build C theo cờ của orchestrator TRACTOR (clang, không sanitizer); Rust: cargo build --release.
set -u
CORPUS=${CORPUS:-/home/claude/corpus}
OUT=${OUT:-/home/claude/exp02/results}
BUILD=${BUILD:-/home/claude/exp02/.build}
RUNNER=$CORPUS/tractor/target/release/cando_binrunner
TIMEOUT=120
CASES="B02_organic/qmath B02_synthetic/tu_linkage B02_synthetic/static-vars-fpts"
SYSTEMS="kiro claude c2rust"
export RUSTUP_TOOLCHAIN=stable
mkdir -p "$OUT" "$BUILD"
for c in $CASES; do
  tc=$(echo "$c" | tr - _); case_name=$(basename "$c"); troot=$CORPUS/tractor/Public-Tests/$tc
  # Phía C
  cb=$BUILD/c/$case_name
  if cmake -S "$troot/test_case" -B "$cb" -G Ninja -DCMAKE_C_COMPILER=clang >"$OUT/$case_name.c.build.txt" 2>&1 \
     && cmake --build "$cb" >>"$OUT/$case_name.c.build.txt" 2>&1; then
    "$RUNNER" -l quiet -t "$troot" --timeout $TIMEOUT -o "$OUT/$case_name.C.report.json" bin -n "$cb/driver" >"$OUT/$case_name.C.run.txt" 2>&1
    echo "$case_name C run_exit=$?"
  else echo "$case_name C BUILD_FAIL"; fi
  # Phía Rust, từng hệ
  for s in $SYSTEMS; do
    src=$CORPUS/harvest/Test-Corpus/$s/$c/verified; [ -d "$src" ] || src=$CORPUS/harvest/Test-Corpus/$s/$c/translated
    td=$BUILD/rust/$s/$case_name
    # Build trên bản copy ngoài git clone: cargo duyệt excludes của git và lỗi trên sparse checkout
    wd=$BUILD/src/$s/$case_name; rm -rf "$wd"; mkdir -p "$(dirname "$wd")"; cp -r "$src" "$wd"
    # c2rust sinh #![feature(raw_ref_op)] (đã stable từ 1.82); stable toolchain từ chối attribute này.
    # RUSTC_BOOTSTRAP=1 chỉ cho phép attribute, không đổi ngữ nghĩa. Chỉ bật cho c2rust, ghi vào deviations.
    boot=0; [ "$s" = c2rust ] && boot=1
    if (cd "$wd" && $( [ $boot = 1 ] && echo "env RUSTC_BOOTSTRAP=1" ) cargo build --release --target-dir "$td") >"$OUT/$case_name.$s.build.txt" 2>&1; then
      bin=$(find "$td/release" -maxdepth 1 -type f -name driver | head -1)
      "$RUNNER" -l quiet -t "$troot" --timeout $TIMEOUT -o "$OUT/$case_name.$s.report.json" bin -n "$bin" >"$OUT/$case_name.$s.run.txt" 2>&1
      echo "$case_name $s($(basename $src)) run_exit=$?"
    else echo "$case_name $s BUILD_FAIL"; fi
  done
done
