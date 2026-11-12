#!/usr/bin/env python3
"""Nhãn cuối R9/R18 và tỉ lệ theo README.md. Nhãn cuối = nhãn đồng thuận của ba lượt, ghi đè theo quyết định của Le
(results/le-decisions.json). Tỉ lệ chỉ trên phần R9 (30 mỗi kind); R18 báo riêng. Wilson CI 95%.
Dùng: python3 experiments/31-r9-check/scripts/final.py experiments/31-r9-check/results"""
import collections, json, math, sys


def wilson(k, n, z=1.959964):
    if n == 0: return None
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 4), round((c + h) / d, 4)]


def main(R):
    rows = [json.loads(l) for l in open(f'{R}/labels-merged.jsonl')]
    dec = json.load(open(f'{R}/le-decisions.json'))
    final = []
    for r in rows:
        l = r['labels']
        base = dict(q1=l[0]['q1'], q2=collections.Counter(x['q2'] for x in l).most_common(1)[0][0], q3=l[0]['q3']) if r['agree'] else None
        if r['id'] in dec['override']: base = dict(base or {}, **dec['override'][r['id']])
        if base is None: raise SystemExit(f'mục bất đồng chưa có quyết định của Le: {r["id"]}')
        final.append(dict(id=r['id'], kind=r['kind'], part=r['part'], slot=r['slot'], script_rule=r['script_rule'], **base))
    with open(f'{R}/labels-final.jsonl', 'w') as f:
        for x in final: f.write(json.dumps(x, ensure_ascii=False) + '\n')
    out = {}
    for part in ('R9', 'R18'):
        for kind in ('exe', 'lib'):
            xs = [x for x in final if x['part'] == part and x['kind'] == kind]
            unc = [x['id'] for x in xs if x['q1'] == 'unclear' or x['q3'] == 'unclear']
            det = [x for x in xs if x['id'] not in unc]
            false_div = [x['id'] for x in det if x['q1'] == 'no' or x['q3'] == 'yes']
            bnu_wrong = [x['id'] for x in det if x['q2'] != x['script_rule']]
            out[f'{part}-{kind}'] = dict(n=len(xs), unclear=unc, n_determinate=len(det),
                                         false_div=dict(k=len(false_div), ids=false_div, wilson95=wilson(len(false_div), len(det))),
                                         bnu_wrong=dict(k=len(bnu_wrong), ids=bnu_wrong, wilson95=wilson(len(bnu_wrong), len(det))))
    out['le_decisions'] = dec
    json.dump(out, open(f'{R}/r9-final.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({k: (v if k == 'le_decisions' else dict(n=v['n'], unclear=len(v['unclear']), fd=v['false_div'], bnu=v['bnu_wrong']))
                      for k, v in out.items() if k != 'le_decisions'}, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1])
