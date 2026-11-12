#!/usr/bin/env python3
"""exp 34 (README.md): chọn mẫu R_test RQ2 và sinh phiếu bằng chứng cơ học. Chạy từ gốc repo:
  python3 experiments/34-rq2-check/scripts/sample.py RQ2_DIR experiments/34-rq2-check/results
RQ2_DIR chứa exe/rq2-exe.jsonl, lib/rq2-lib.jsonl (results/rq2-main b757f4d). Phiếu ẩn outcome, channels, orig của harness."""
import base64, collections, gzip, json, random, sys

SEED = 20261105; N = 30; LIMIT = 1500
R_TEST = ('behavioral_disagreement', 'behavioral_agreement', 'not_adjudicable')
DECIDING = ('supports_rejection', 'agrees')


def ub(b):
    if not isinstance(b, dict) or 'gz64' not in b: return b
    t = gzip.decompress(base64.b64decode(b['gz64'])).decode('latin-1')
    return dict(text=t if len(t) <= LIMIT else t[:LIMIT] + f'…[{LIMIT}/{len(t)} ký tự]', bytes=b.get('len'), truncated_by_harness=b.get('truncated'))


def clean(x):
    if isinstance(x, dict):
        if 'gz64' in x: return ub(x)
        return {k: clean(v) for k, v in x.items() if k not in ('channels', 'state_debug', 'outcome', 'orig')}
    if isinstance(x, list): return [clean(v) for v in x]
    return x


def allocate(keys, n, rng):
    by = collections.defaultdict(list)
    for r in keys: by[r['system']].append(r)
    tot = sum(len(v) for v in by.values()); n = min(n, tot)
    al = {s: max(1, int(n * len(v) / tot)) for s, v in by.items()}
    order = sorted(by, key=lambda s: -(n * len(by[s]) / tot - int(n * len(by[s]) / tot)))
    i = 0
    while sum(al.values()) < n:
        s = order[i % len(order)]
        if al[s] < len(by[s]): al[s] += 1
        i += 1
    while sum(al.values()) > n:
        s = max(al, key=lambda x: al[x]); al[s] -= 1
    out = []
    for s in sorted(al): out += rng.sample(sorted(by[s], key=lambda r: r['key']), al[s])
    return out


def main(src, out):
    items, key = [], []
    for kind in ('exe', 'lib'):
        recs = [json.loads(l) for l in open(f'{src}/{kind}/rq2-{kind}.jsonl') if l.strip()]
        rt = [r for r in recs if r.get('outcome') in R_TEST]
        rng = random.Random(f'{SEED}/{kind}')
        dis = [r for r in rt if r['outcome'] == 'behavioral_disagreement']
        pick = allocate(dis, N, rng) + [r for r in rt if r['outcome'] != 'behavioral_disagreement']
        for r in sorted(pick, key=lambda r: r['key']):
            vs = [v for v in r['vectors'] if v.get('outcome') in DECIDING]
            if not vs: continue
            v = random.Random(f'{SEED}/{r["key"]}').choice(vs)
            i = f'{kind}-{len(items):03d}'
            ev = dict(kind=kind, vector=v.get('vector'), input=clean(v.get('input')), c_stable=v.get('c_stable'), has_ub=v.get('has_ub'),
                      san=v.get('san'))
            if kind == 'exe':
                ev.update(c_out=ub(v.get('c_out')), c_err=ub(v.get('c_err')), r_out=ub(v.get('r_out')), r_err=ub(v.get('r_err')),
                          first_run=clean((v.get('runs') or [{}])[0]))
            else:
                ev.update(c_first=clean(v.get('c_first')), r_first=clean(v.get('r_first')))
            items.append(dict(id=i, evidence=ev))
            key.append(dict(id=i, key=r['key'], outcome=r['outcome'], vector_outcome=v.get('outcome'),
                            channels=(v.get('runs') or [{}])[0].get('channels'), frame=len(rt)))
    with open(f'{out}/key.jsonl', 'w') as f:
        for k in key: f.write(json.dumps(k) + '\n')
    with open(f'{out}/evidence.md', 'w', encoding='utf-8') as f:
        f.write('# Phiếu bằng chứng RQ2 (exp 34)\n\nMỗi mục: một vector của một bản dịch bị chấm trượt ở bước test. `c_*` phía C, `r_*` phía Rust.\n')
        for it in items: f.write(f"\n## {it['id']}\n\n```json\n{json.dumps(it['evidence'], ensure_ascii=False, indent=1)}\n```\n")
    print(json.dumps(collections.Counter((k['id'][:3], k['outcome']) for k in key).most_common()))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
