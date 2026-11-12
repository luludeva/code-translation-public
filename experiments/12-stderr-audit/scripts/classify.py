#!/usr/bin/env python3
"""Xếp cặp stderr vào nhóm A, B, C theo luật đăng ký trước (README exp 12) và đếm tác động P1, P2, P3 trên pilot.
Đầu vào: results/pairs-*.jsonl, results/totals-*.json. Đầu ra: results/classified.jsonl, results/summary.md,
results/c-to-label.jsonl (nhóm C, chờ gán C1, C2 bằng tay)."""
import collections, json, os, re

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results')
ADDR = re.compile(r'0x[0-9a-f]+'); PID = re.compile(r'==\d+==')


def norm(s, bins):
    s = s.lower()
    for b in sorted(bins, key=len, reverse=True):
        if not b: continue
        s = s.replace(b.lower(), '<prog>')
    for b in bins:
        if b: s = s.replace(os.path.basename(b.rstrip('/')).lower(), '<prog>')
    s = ADDR.sub('<addr>', s); s = PID.sub('==<pid>==', s)
    lines = [l.rstrip() for l in s.split('\n')]
    return '\n'.join(l for l in lines if l)


def group(r):
    bins = [r.get('c_bin') or '', r.get('r_bin') or '']
    c, x = norm(r['c_err'], bins), norm(r['r_err'], bins)
    if c == x: return 'A', c, x
    if (c == '') != (x == ''): return 'B', c, x
    return 'C', c, x


def main():
    rows = []
    for k in ('exe', 'lib'):
        p = f'{OUT}/pairs-{k}.jsonl'
        if os.path.exists(p): rows += [json.loads(l) for l in open(p)]
    cnt = collections.Counter(); per = collections.defaultdict(collections.Counter)
    pair_hit = collections.defaultdict(set)   # (phương án) -> tập (case, system) có thêm divergence
    with open(f'{OUT}/classified.jsonl', 'w') as fo, open(f'{OUT}/c-to-label.jsonl', 'w') as fc:
        for r in rows:
            g, c, x = group(r); r['group'] = g; r['c_norm'] = c[:500]; r['r_norm'] = x[:500]
            cnt[g] += 1; per[(r['kind'], r['case'], r['system'])][g] += 1
            key = (r['kind'], r['case'], r['system'])
            pair_hit['P1'].add(key)
            if g != 'A': pair_hit['P2'].add(key)
            if g == 'B': pair_hit['P3'].add(key)
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
            if g == 'C': fc.write(json.dumps({k: r[k] for k in ('kind', 'case', 'system', 'idx', 'source', 'c_norm', 'r_norm')}, ensure_ascii=False) + '\n')
    pairs = set()
    for k in ('exe', 'lib'):
        p = f'{OUT}/totals-{k}.json'
        if os.path.exists(p):
            for cs, t in json.load(open(p)).items():
                for s in t:
                    if not s.startswith('_'): pairs.add((k, cs.split('/')[1], s))
    L = ['# Exp 12: kết quả phân loại cặp stderr trên pilot (tự động, nhóm A, B, C)', '',
         f'Cặp stderr khác nhau: {len(rows)}. Nhóm: ' + ', '.join(f'{g} {cnt[g]}' for g in 'ABC'), '',
         '| loại | case | hệ | A | B | C |', '|---|---|---|---|---|---|']
    for (k, c, s), v in sorted(per.items()): L.append(f'| {k} | {c} | {s} | {v["A"]} | {v["B"]} | {v["C"]} |')
    L += ['', f'Bản dịch pilot có quan sát bằng nhau: {len(pairs)}. Bản dịch có thêm ít nhất một divergence nếu so stderr:']
    for pn, lab in (('P1', 'so nguyên văn'), ('P2', 'so sau chuẩn hoá N'), ('P3', 'chỉ so có hay không có stderr')):
        L.append(f'- {pn} ({lab}): {len(pair_hit[pn])}/{len(pairs)}')
    open(f'{OUT}/summary.md', 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
