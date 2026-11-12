#!/usr/bin/env python3
"""exp 36: tính kết quả held-out theo README (đơn vị bản dịch). Đọc OUT/<unit>/ (đầu ra harness.rq1 --pilot) và results/plan.json.
Phát hiện: ít nhất một divergence giữ lại (harness.metrics.retained) của bản dịch đích, hợp qua ba seed, có source khác 'seed' và 'vector'.
Số chính k/11; số phụ k/6 trên bản dịch còn ít nhất một vector trong corpus phủ (README, Thay đổi 2026-11-05).
  python3 experiments/36-heldout/scripts/evaluate.py PLAN OUT > OUT/heldout-result.json"""
import collections, json, math, os, sys

sys.path.insert(0, os.getcwd())
from harness import metrics as HM  # noqa: E402

SEEDS = [0, 1, 2]
VECTOR_SOURCES = ('seed', 'vector')


def wilson(k, n, z=1.96):
    if n == 0: return None
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(max(0.0, (c - h) / d), 4), round(min(1.0, (c + h) / d), 4)]


def main(plan, out):
    P = json.load(open(plan)); rows = []
    for u in P['units']:
        d = f"{out}/{u['unit']}"; kind = u['kind']
        ov = json.load(open(f'{d}/overlay.json')) if os.path.exists(f'{d}/overlay.json') else {}
        cases, divs, caps = HM.load_rq1(d, kind) if os.path.exists(f'{d}/rq1-{kind}.jsonl') else ([], {}, {})
        T = HM.rq1_translations(cases, divs, caps, SEEDS)
        recs = {r['seed']: r for r in cases if (r['bundle'], r['case']) == (u['bundle'], u['case'])}
        n_inputs = sum((r.get('n_inputs') or 0) for r in recs.values())
        for s in u['systems']:
            alld = [x for sd in SEEDS for x in divs.get((u['bundle'], u['case'], s, sd), [])]
            ret = [x for x in alld if HM.retained(x)]
            new = [x for x in ret if x.get('source') not in VECTOR_SOURCES]
            t = T.get((u['bundle'], u['case'], s)) or {}
            rows.append(dict(unit=u['unit'], kind=kind, case=f"{u['bundle']}/{u['case']}", system=s, withheld=len(u['withheld']),
                             kept_vectors=ov.get('kept_json'), status=t.get('status'), seeds_with_record=sorted(recs),
                             n_inputs_case=n_inputs, n_div_all=len(alld), n_retained=len(ret), n_retained_generated=len(new),
                             sources_retained_generated=dict(collections.Counter(f"{x.get('layer')}/{x.get('source')}" for x in new)),
                             detected=bool(new)))
    def summ(rs):
        k = sum(r['detected'] for r in rs); n = len(rs)
        return dict(k=k, n=n, wilson95=wilson(k, n))
    with_seed = [r for r in rows if (r['kept_vectors'] or 0) > 0]
    res = dict(rule='README exp 36: phát hiện = >= 1 divergence giữ lại trên input nguồn khác seed/vector, hợp ba seed',
               primary=dict(all=summ(rows), exe=summ([r for r in rows if r['kind'] == 'exe']), lib=summ([r for r in rows if r['kind'] == 'lib'])),
               secondary_with_remaining_vectors=summ(with_seed), translations=rows)
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
