#!/usr/bin/env python3
"""exp 36 (README.md): lập danh sách lượt chạy held-out từ RQ2 pilot (exp 15). Tất định; ghi results/plan.json. Chạy từ gốc repo:
  python3 experiments/36-heldout/scripts/plan.py > experiments/36-heldout/results/plan.json"""
import collections, json

SRC = 'experiments/15-rq2-pilot-trial/results/rq2-{}.jsonl'


def main():
    units = collections.OrderedDict()
    for kind in ('exe', 'lib'):
        for l in open(SRC.format(kind)):
            if not l.strip(): continue
            r = json.loads(l)
            if r.get('outcome') != 'behavioral_disagreement': continue
            w = tuple(sorted(v['vector'] for v in r['vectors'] if v.get('outcome') == 'supports_rejection'))
            k = (kind, r['bundle'], r['case'], w)
            units.setdefault(k, []).append(r['system'])
    out = [dict(unit=f'u{i:02d}', kind=k[0], bundle=k[1], case=k[2], withheld=list(k[3]), systems=sorted(s))
           for i, (k, s) in enumerate(units.items())]
    print(json.dumps(dict(source=[SRC.format('exe'), SRC.format('lib')], n_translations=sum(len(u['systems']) for u in out),
                          units=out), indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
