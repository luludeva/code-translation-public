#!/usr/bin/env python3
"""exp 40: AX-1 theo docs/amendment-2026-11-05-supplementary-analyses.md mục 3 (post hoc, sơ bộ, chưa kiểm tay).
Tử số: bản dịch thuộc D có ít nhất một divergence giữ lại ở kênh k; mẫu số: |D|; một bản có thể thuộc nhiều kênh. Kênh lấy từ trường
`channels` của divergence: `status` là trạng thái kết thúc; `stdout`; `stderr_only` là divergence có channels đúng bằng ['stderr'];
library có thêm `state` (trường state của runner, amendment không liệt kê, báo riêng). Divergence không có channels (executable: một phía
vượt ngân sách) đếm vào `none`. Mức divergence là phụ: số divergence giữ lại theo từng kênh.
Chọn bản ghi theo L5 như harness.main_merge_v2 (cài ở experiments/39-prereg-backfill/scripts/v3c.py). Kiểm: tổng divergence giữ lại của D
bằng rqBnuDivNOneStatus<K>AllDen (số của metrics); lệch thì dừng.
  python3 experiments/40-review-counts/scripts/ax1_channels.py > experiments/40-review-counts/results/ax1-channels.json"""
import collections, gzip, io, json, os, re, sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, f'{ROOT}/experiments/39-prereg-backfill/scripts')
import v3c as V  # noqa: E402

DFILE = f'{ROOT}/experiments/32-robustness-s0/results/D-{{}}.jsonl'
RQ = f'{ROOT}/writing/generated/rq-numbers.tex'


def chans(d):
    ch = d.get('channels')
    if not ch: return ['none']
    if ch == ['stderr']: return ['stderr_only']
    return [c for c in ch if c != 'stderr'] or ['stderr_only']


def unit(args):
    blobs, want = args
    per = collections.defaultdict(collections.Counter)
    if not blobs: return {}
    with gzip.open(io.BytesIO(b''.join(V.run('git', 'cat-file', 'blob', x) for x in blobs)), 'rb') as f:
        for l in f:
            if not l.strip(): continue
            d = V.loads(l)
            if d.get('system') not in want or not d.get('retained'): continue
            per[d['system']]['_retained'] += 1
            for c in chans(d): per[d['system']][c] += 1
    return {s: dict(v) for s, v in per.items()}


def main():
    out = {}
    for kind, tok in (('exe', 'Exe'), ('lib', 'Lib')):
        D = {tuple(json.loads(l)) for l in open(DFILE.format(kind)) if l.strip()}
        chosen, trees = {}, {}
        for job, cm in V.SHARDS[kind]:
            fc = V.full(cm); trees[job] = (fc, V.tree(fc, f'ci-out/{job}/div/'))
            for l in V.run('git', 'show', f'{fc}:ci-out/{job}/rq1-{kind}.jsonl').decode().splitlines():
                if not l.strip(): continue
                r = json.loads(l)
                if r.get('status') == 'harness_error': continue
                chosen.setdefault((r['bundle'], r['case'], r['seed']), (job, r))
        jobs, keys = [], []
        for (b, cs, sd), (job, r) in sorted(chosen.items()):
            want = {s for s, st in (r.get('pair_status') or {}).items() if st == 'P_test' and (b, cs, s) in D}
            if not want: continue
            fc, t = trees[job]; base = f'ci-out/{job}/div/{b}__{cs}__s{sd}.jsonl'
            blobs = ([t[base + '.gz']] if base + '.gz' in t else [t[p] for p in sorted(p for p in t if p.startswith(base + '.gz.part'))]
                     or [t[p] for p in sorted(p for p in t if p.startswith(base + '.part'))])
            jobs.append((blobs, want)); keys.append((b, cs))
        agg = collections.defaultdict(collections.Counter)
        with ProcessPoolExecutor(2) as ex:
            for (b, cs), per in zip(keys, ex.map(unit, jobs)):
                for s, v in per.items(): agg[(b, cs, s)].update(v)
        tot = sum(agg[k]['_retained'] for k in D)
        ref = re.search(r'\\rqSet\{rqBnuDivNOneStatus' + tok + r'AllDen\}\{(\d+)\}', open(RQ).read())
        if not ref or int(ref.group(1)) != tot: raise SystemExit(f'{kind}: tổng divergence giữ lại {tot} khác rq-numbers {ref and ref.group(1)}')
        names = sorted({c for k in D for c in agg[k] if c != '_retained'})
        out[kind] = dict(D=len(D), retained_div=tot,
                         translations={c: sum(1 for k in D if agg[k][c]) for c in names},
                         divergences={c: sum(agg[k][c] for k in D) for c in names})
    print(json.dumps(dict(rule='exp 40, AX-1 (amendment 2026-11-05 mục 3); post hoc, sơ bộ, chưa kiểm tay', **out), indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
