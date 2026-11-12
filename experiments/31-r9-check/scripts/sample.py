#!/usr/bin/env python3
"""R9/R18: chọn mẫu theo experiments/31-r9-check/README.md (đăng ký trước). Chạy từ gốc repo:
  python3 experiments/31-r9-check/scripts/sample.py --merged-exe DIR --merged-lib DIR --out experiments/31-r9-check/results
DIR là thư mục gộp main_merge_v2 của S₀ (rq1-<kind>.jsonl, div/). P_rep library: đặt HARNESS_P_REP_LIB_CENSUS, HARNESS_P_REP_LIB_RECHECK
như ci/main-run-env.sh (census-lib3). Đọc div theo luồng (không nạp hết vào RAM): mỗi (bản dịch, seed) chỉ giữ một divergence giữ lại làm
đại diện cho rq1_translations (đủ cho trạng thái và in_S); hai lượt: lượt 1 tính D, lượt 2 reservoir chọn divergence cho mục được chọn."""
import argparse, collections, glob, hashlib, json, os, random, sys

sys.path.insert(0, os.getcwd())
from harness import metrics as HM
from harness.pairs import prep_pairs

SEED = 20261102
N_PER_KIND = 30
FULL = 'c2rust'


def div_files(d):
    out = []
    for f in sorted(glob.glob(f'{d}/div/*.jsonl') + glob.glob(f'{d}/div/*.jsonl.gz')):
        n = f[:-3] if f.endswith('.gz') else f
        if n.endswith(('.memlimit.jsonl', '.exact.jsonl', '.capsens.jsonl')): continue
        out.append(f)
    return out


def stream(d, kind):
    for f in div_files(d):
        with HM.open_text(f) as h:
            for l in h:
                if not l.strip(): continue
                r = json.loads(l)
                if r.get('kind') == kind: yield r


def compute_D(d, kind, seeds):
    cases = [r for r in HM._jsonl(f'{d}/rq1-{kind}.jsonl') if r.get('status') in ('done', *HM.CASE_LEVEL)]
    rep = {}
    for r in stream(d, kind):
        if HM.retained(r):
            k = (r['bundle'], r['case'], r['system'], r['seed'])
            if k not in rep: rep[k] = r
    divs = collections.defaultdict(list)
    for k, v in rep.items(): divs[k].append(v)
    T = HM.rq1_translations(cases, divs, {}, seeds, prep_pairs(kind))
    D = sorted(k for k, t in T.items() if t['status'] == 'P_test' and not t.get('unexpected') and t.get('in_S'))
    P = sum(1 for t in T.values() if t['status'] == 'P_test' and not t.get('unexpected'))
    need = {k: [sd for sd in seeds if (*k, sd) in rep] for k in D}
    return D, P, need


def allocate(D, n):
    by = collections.defaultdict(list)
    for k in D: by[k[2]].append(k)
    sysd = {s: len(v) for s, v in by.items() if s != FULL}
    tot = sum(sysd.values()); n = min(n, tot)
    base = {s: max(1, int(n * c / tot)) for s, c in sysd.items()}
    rem = sorted(sysd, key=lambda s: -(n * sysd[s] / tot - int(n * sysd[s] / tot)))
    i = 0
    while sum(base.values()) < n:
        s = rem[i % len(rem)]
        if base[s] < sysd[s]: base[s] += 1
        i += 1
    while sum(base.values()) > n:
        s = max(base, key=lambda x: base[x]); base[s] -= 1
    return by, base


def tkey(k): return '/'.join(map(str, k))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--merged-exe', required=True); ap.add_argument('--merged-lib', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    seeds = [0, 1, 2]
    expected_D = json.load(open('experiments/30-main-s0/results/metrics.json'))
    log = []
    picks = []
    for kind, d in (('exe', a.merged_exe), ('lib', a.merged_lib)):
        D, P, _ = compute_D(d, kind, seeds)
        want = expected_D[f'rq1_{kind}']['by_group']['all']
        log.append(dict(kind=kind, D=len(D), P_test=P, metrics_D=want['D_all'], metrics_P_test=want['P_test'],
                        match=len(D) == want['D_all'] and P == want['P_test']))
        if not log[-1]['match']:
            json.dump(log, open(f'{a.out}/count-check.json', 'w'), indent=1); raise SystemExit(f'kiểm đếm lệch: {log[-1]}')
        by, alloc = allocate(D, N_PER_KIND)
        rng = random.Random(f'{SEED}/{kind}')
        for s in sorted(alloc):
            for k in sorted(rng.sample(sorted(by[s]), alloc[s])): picks.append(dict(kind=kind, t=k, part='R9', per_seed=False))
        for k in sorted(by.get(FULL, [])): picks.append(dict(kind=kind, t=k, part='R18', per_seed=True))
    json.dump(log, open(f'{a.out}/count-check.json', 'w'), indent=1)
    # lượt 2: reservoir chọn divergence
    chosen = {}
    for kind, d in (('exe', a.merged_exe), ('lib', a.merged_lib)):
        want = {tuple(p['t']): p for p in picks if p['kind'] == kind}
        seen = collections.Counter()
        for r in stream(d, kind):
            if not HM.retained(r): continue
            k = (r['bundle'], r['case'], r['system'])
            if k not in want: continue
            slot = (k, r['seed']) if want[k]['per_seed'] else (k,)
            seen[slot] += 1
            rng = random.Random(f'{SEED}/{tkey(slot)}/{seen[slot]}')
            if seen[slot] == 1 or rng.random() < 1.0 / seen[slot]:
                g, code = HM.bnu_rule(r)
                chosen[slot] = dict(kind=kind, part=want[k]['part'], slot=tkey(slot), div=r, script_rule=code, script_group=g)
    items = sorted(chosen.values(), key=lambda x: (x['kind'], x['part'], x['slot']))
    with open(f'{a.out}/items.jsonl', 'w') as f:
        for i, it in enumerate(items):
            it['id'] = f'{it["kind"]}-{i:03d}'; f.write(json.dumps(dict(id=it['id'], kind=it['kind'], part=it['part'], div=it['div']), ensure_ascii=False) + '\n')
    with open(f'{a.out}/key.jsonl', 'w') as f:
        for it in items: f.write(json.dumps(dict(id=it['id'], slot=it['slot'], script_rule=it['script_rule'], script_group=it['script_group'])) + '\n')
    print(json.dumps(dict(count_check=log, n_items=len(items), by_part=collections.Counter((i['kind'], i['part']) for i in items).most_common()),
                     default=str, ensure_ascii=False))


if __name__ == '__main__':
    main()
