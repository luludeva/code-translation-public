#!/usr/bin/env python3
"""Gộp ba lượt nhãn R9/R18 theo README.md: đồng thuận khi ba nhãn trùng ở q1, q2, q3; liệt kê mục bất đồng (Le xử), 10 mục đồng thuận ngẫu
nhiên (seed 20261103, Le kiểm), mọi mục R18; so q2 với mã của script (key.jsonl). Chưa tính tỉ lệ cuối: cần nhãn cuối sau khi Le xử.
Dùng: python3 experiments/31-r9-check/scripts/aggregate.py PASS1 PASS2 PASS3 --results experiments/31-r9-check/results"""
import argparse, collections, json, random


def load(p): return {r['id']: r for r in (json.loads(l) for l in open(p) if l.strip())}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('passes', nargs=3); ap.add_argument('--results', required=True)
    a = ap.parse_args()
    P = [load(p) for p in a.passes]
    key = load(f'{a.results}/key.jsonl')
    items = {r['id']: r for r in (json.loads(l) for l in open(f'{a.results}/items.jsonl'))}
    assert all(set(p) == set(key) for p in P), 'thiếu mục ở một lượt'
    rows = []
    for i in sorted(key):
        labs = [(p[i]['q1'], p[i]['q2'], p[i]['q3']) for p in P]
        agree = len(set(labs)) == 1
        rows.append(dict(id=i, kind=items[i]['kind'], part=items[i]['part'], slot=key[i]['slot'], agree=agree,
                         labels=[dict(q1=l[0], q2=l[1], q3=l[2], why=p[i].get('why')) for l, p in zip(labs, P)],
                         script_rule=key[i]['script_rule'],
                         q2_majority=collections.Counter(l[1] for l in labs).most_common(1)[0]))
    cons = [r['id'] for r in rows if r['agree'] and r['part'] == 'R9']
    spot = sorted(random.Random(20261103).sample(cons, min(10, len(cons))))
    for r in rows:
        r['to_le'] = (not r['agree']) or r['part'] == 'R18' or r['id'] in spot
        r['reason'] = 'R18' if r['part'] == 'R18' else ('bất đồng' if not r['agree'] else ('kiểm ngẫu nhiên' if r['id'] in spot else ''))
    with open(f'{a.results}/labels-merged.jsonl', 'w') as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    summ = dict(n=len(rows), agree=sum(r['agree'] for r in rows), disagree=sum(not r['agree'] for r in rows),
                spot=spot, to_le=sum(r['to_le'] for r in rows),
                q2_vs_script_on_agreed=dict(collections.Counter(r['labels'][0]['q2'] == r['script_rule'] for r in rows if r['agree'])))
    json.dump(summ, open(f'{a.results}/labels-summary.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(summ, ensure_ascii=False))


if __name__ == '__main__':
    main()
