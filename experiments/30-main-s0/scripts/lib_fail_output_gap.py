#!/usr/bin/env python3
"""Định lượng khe hở output của lời gọi library thất bại (Le chọn 4/11, "định lượng rồi ghi log"). Chỉ đọc, không đổi số đo.

Khe hở: runner TRACTOR (37960ee, tools/cando2/src/runners/lib_runner.rs dòng 181-245; runner.rs dòng 31-61) ghi stdout, stderr của lời
gọi cho mọi kết cục, gồm Panic, SegmentationFault, UnknownFailure; harness/observe.py chỉ đọc stdout, stderr từ file dump, có khi lời
gọi hoàn tất. Hai phía cùng loại thất bại thì so bằng nhau dù output có thể khác: divergence có thể bị bỏ sót.

RQ1 (cận trên số input bị ảnh hưởng): với mỗi (case, seed) chọn theo L5 và mỗi hệ có pair_status P_test ở seed đó,
  input khớp mà C thất bại loại X = counts['c_status:X'] - số divergence có c.result = X (input khớp có cùng result hai phía; với loại
  thất bại, completed_same không gộp). Đếm theo X thuộc {SegmentationFault, UnknownFailure, Panic}.
RQ2: vector trượt mà hai phía cùng loại thất bại trong lần chạy đầu (c_first, r_first), theo outcome của vector.
Chạy từ gốc repo: python3 experiments/30-main-s0/scripts/lib_fail_output_gap.py > experiments/30-main-s0/results/lib-fail-output-gap.json"""
import collections, gzip, io, json, subprocess

SHARDS = [('rq1-main-lib-1of2', 'a980c52'), ('rq1-main-lib-2of2', '97f80c5'), ('rq1-main-lib-shgeti', 'c8c41a3'),
          ('rq1-main-lib-2of2-light', 'e8f9704')]
RQ2 = ('rq2-main', 'b757f4d')
FAIL = ('SegmentationFault', 'UnknownFailure', 'Panic')


def run(*a, **k): return subprocess.run(a, capture_output=True, check=True, **k).stdout


def full(c): return run('git', 'rev-parse', c).decode().strip()


def tree(c, prefix):
    out = {}
    for l in run('git', 'ls-tree', '-r', c, prefix).decode().splitlines():
        meta, path = l.split('\t'); out[path] = meta.split()[2]
    return out


def div_stream(blobs):
    data = b''.join(run('git', 'cat-file', 'blob', b) for b in blobs)
    with gzip.open(io.BytesIO(data), 'rt') as f:
        for l in f:
            if l.strip(): yield json.loads(l)


def main():
    chosen, trees = {}, {}
    for job, c in SHARDS:
        fc = full(c); trees[job] = (fc, tree(fc, f'ci-out/{job}/div/'))
        txt = run('git', 'show', f'{fc}:ci-out/{job}/rq1-lib.jsonl').decode()
        for l in txt.splitlines():
            if not l.strip(): continue
            r = json.loads(l)
            if r.get('status') == 'harness_error' or 'pair_status' not in r: continue
            chosen.setdefault((r['bundle'], r['case'], r['seed']), (job, r))
    tot = collections.Counter(); by_case = collections.defaultdict(collections.Counter); n_units = 0
    for (b, cs, sd), (job, r) in sorted(chosen.items()):
        sys_ok = {s for s, st in (r.get('pair_status') or {}).items() if st == 'P_test'}
        if not sys_ok: continue
        n_units += 1
        fc, t = trees[job]; base = f'ci-out/{job}/div/{b}__{cs}__s{sd}.jsonl.gz'
        blobs = [t[base]] if base in t else [t[p] for p in sorted(p for p in t if p.startswith(base + '.part'))]
        divc = collections.Counter()
        if blobs:
            for d in div_stream(blobs):
                if d.get('system') in sys_ok and (d.get('c') or {}).get('result') in FAIL: divc[(d['system'], d['c']['result'])] += 1
        for s in sys_ok:
            cnt = (r.get('counts') or {}).get(s) or {}
            for X in FAIL:
                m = cnt.get(f'c_status:{X}', 0) - divc[(s, X)]
                if m:
                    tot[X] += m; by_case[f'{b}/{cs}'][X] += m
            tot['observed'] += cnt.get('observed', 0); tot['match'] += cnt.get('match', 0)
    rq2 = collections.Counter(); fc = full(RQ2[1])
    for l in run('git', 'show', f'{fc}:ci-out/{RQ2[0]}/lib/rq2-lib.jsonl').decode().splitlines():
        if not l.strip(): continue
        rec = json.loads(l)
        for v in rec.get('vectors') or []:
            c, r_ = (v.get('c_first') or {}).get('result'), (v.get('r_first') or {}).get('result')
            if c in FAIL and c == r_: rq2[(rec.get('outcome'), v.get('outcome'), c)] += 1
    out = dict(rule=__doc__.split('\n')[0], rq1=dict(units_case_seed=n_units, matched_both_fail_upper=dict((k, tot[k]) for k in FAIL),
               observed=tot['observed'], match=tot['match'], by_case={k: dict(v) for k, v in sorted(by_case.items(), key=lambda x: -sum(x[1].values()))}),
               rq2={' | '.join(map(str, k)): v for k, v in sorted(rq2.items(), key=str)}, sources=[f'{j}@{full(c)}' for j, c in SHARDS + [RQ2]])
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
