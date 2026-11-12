#!/usr/bin/env python3
"""exp 32 B1 (README.md, mục B1): kiểm chéo compiler phía C trên input divergence của D. Chạy trên máy đo (cần corpus, build như
`harness.sweep cc`), từ gốc repo:
  python3 experiments/32-robustness-s0/scripts/b1.py --merged-exe DIR --merged-lib DIR --out OUT [--k 10] [--workers 6] [--timeout 10]
        [--limit-cases N]   (N: chạy thử N case mỗi kind)
Bước 1 (đọc luồng, như exp 31): tính D bằng metrics.rq1_translations; với mỗi (bản dịch, seed) chọn đều ngẫu nhiên tối đa K divergence giữ
lại (reservoir, seed 20261104); gom (case, seed, idx). Bước 2: mỗi case dựng bản C clang của harness và bản C gcc (`controls`), lấy dòng
input từ inputs/<case>__s<seed>.inputs.jsonl.gz của bản gộp theo idx, gọi judge như `sweep.cc_case` (gcc ở vị trí phía Rust). Input C
không ổn định qua compiler: verdict 'div' và stable. Bước 3: cấp bản dịch theo README."""
import argparse, collections, importlib.util, json, os, random, sys, time

sys.path.insert(0, os.getcwd())
from harness import metrics as HM, rq1, sweep as SW, controls as CT, build as BD
from harness.record import Store

_s = importlib.util.spec_from_file_location('s31', 'experiments/31-r9-check/scripts/sample.py')
S31 = importlib.util.module_from_spec(_s); _s.loader.exec_module(S31)
SEED = 20261104


def select(d, kind, K):
    D, P, _ = S31.compute_D(d, kind, [0, 1, 2]); Dset = set(D)
    seen = collections.Counter(); pick = collections.defaultdict(list)
    for r in S31.stream(d, kind):
        if not HM.retained(r): continue
        k = (r['bundle'], r['case'], r['system'])
        if k not in Dset: continue
        slot = (k, r['seed']); seen[slot] += 1; n = seen[slot]; item = (r['seed'], r['idx'])
        if len(pick[slot]) < K: pick[slot].append(item)
        else:
            j = random.Random(f'{SEED}/{S31.tkey(slot)}/{n}').randrange(n)
            if j < K: pick[slot][j] = item
    return D, P, pick


def b1_case(t):
    """Như sweep.cc_case nhưng dòng input là các idx đã chọn từ inputs của bản gộp S₀."""
    T0 = time.time(); kind = t['kind']; ck = f"{t['bundle']}/{t['case']}"
    rec = dict(key=ck, kind=kind, bundle=t['bundle'], case=t['case'], wanted=len(t['want']))
    rows = []
    for sd, idxs in sorted(t['want'].items()):
        p = f"{t['merged']}/inputs/{t['bundle']}__{t['case']}__s{sd}.inputs.jsonl.gz"
        if not os.path.exists(p): rec.setdefault('missing_inputs_file', []).append(sd); continue
        allr, _ = SW.read_inputs(p); byi = {r['i']: r for r in allr}
        for i in sorted(idxs):
            if i in byi: rows.append((sd, byi[i]))
            else: rec.setdefault('missing_idx', []).append([sd, i])
    side = SW.SIDES[kind](t)
    reason = side.prepare(orig=False)
    if reason: rec.update(status='excluded', excluded_reason=reason); return rec
    B = t['B']; res = {}
    try:
        if kind == 'exe':
            g = CT.build_c_gcc_exe(B, t['bundle'], t['case'])
            if not g.get('ok'): rec.update(status='excluded', excluded_reason='gcc_build_failed'); return rec
            side.orig_target = g['bin']
        else:
            g = CT.build_c_gcc_lib(B, side.info)
            if not g.get('ok'): rec.update(status='excluded', excluded_reason='gcc_build_failed'); return rec
            side.orig_target = CT.gcc_lib_root(B, side.info, g)
        rec['gcc_sha256'] = g.get('sha256')
        for sd, row in rows:
            st, cache = side.c_obs(row)
            if st != 'ok': res[f'{sd}/{row["i"]}'] = dict(status=st); continue
            j = side.judge(side.orig_target, 'gcc', row, cache)
            res[f'{sd}/{row["i"]}'] = dict(status='ok', verdict=j['verdict'], stable=j.get('stable'), channels=j.get('channels'),
                                           san=(j.get('san') or {}).get('status'),
                                           c_unstable=j['verdict'] == 'div' and bool(j.get('stable')))
    finally:
        side.cleanup()
    rec.update(status='done', inputs=res, secs=round(time.time() - T0, 2))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--merged-exe', required=True); ap.add_argument('--merged-lib', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--k', type=int, default=10); ap.add_argument('--workers', type=int, default=6); ap.add_argument('--timeout', type=int, default=10)
    ap.add_argument('--limit-cases', type=int)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/b1'))
    summary = {}
    for kind, d in (('exe', a.merged_exe), ('lib', a.merged_lib)):
        D, P, pick = select(d, kind, a.k)
        want = collections.defaultdict(lambda: collections.defaultdict(set))
        for (k, sd), items in pick.items():
            for s2, i in items: want[(k[0], k[1])][s2].add(i)
        cases = sorted(want)[:a.limit_cases] if a.limit_cases else sorted(want)
        json.dump(dict(D=[list(k) for k in D], P_test=P, pick={f'{S31.tkey(s)}': v for s, v in pick.items()}),
                  open(f'{a.out}/b1-select-{kind}.json', 'w'), ensure_ascii=False)
        store = Store(f'{a.out}/b1-{kind}.jsonl')
        if kind == 'lib': BD.setup_cando2(B)
        tasks = [dict(kind=kind, bundle=b, case=c, system=None, hcase=None, B=B, timeout=a.timeout, run_tag='b1', merged=d,
                      want={sd: sorted(v) for sd, v in want[(b, c)].items()}) for b, c in cases if not store.has(f'{b}/{c}')]

        def sink(t, r):
            if r.get('status') == 'harness_error': r.update(key=f"{t['bundle']}/{t['case']}#error", kind=t['kind'])
            store.put(r); print(r['key'], r.get('status'), r.get('excluded_reason', ''), flush=True)
        SW.run_tasks(b1_case, tasks, a.workers, sink)
        # cấp bản dịch
        recs = {r['key']: r for r in (json.loads(l) for l in open(f'{a.out}/b1-{kind}.jsonl')) if not r['key'].endswith('#error')}
        keep, leave, unchecked = [], [], []
        for k in D:
            if a.limit_cases and (k[0], k[1]) not in cases: continue
            r = recs.get(f'{k[0]}/{k[1]}')
            items = [it for sd in (0, 1, 2) for it in pick.get((k, sd), [])]
            obs = [(r or {}).get('inputs', {}).get(f'{s2}/{i}') for s2, i in items]
            ok = [o for o in obs if o and o.get('status') == 'ok']
            if not r or r.get('status') != 'done' or not ok: unchecked.append(list(k))
            elif any(not o['c_unstable'] for o in ok): keep.append(list(k))
            else: leave.append(list(k))
        summary[kind] = dict(D=len(D), P_test=P, checked=len(keep) + len(leave), D_B1=len(keep) + len(unchecked), leave_all_c_unstable=leave,
                             n_leave=len(leave), unchecked=unchecked, n_unchecked=len(unchecked), limit_cases=a.limit_cases,
                             n_inputs=sum(len(r.get('inputs', {})) for r in recs.values()),
                             n_inputs_c_unstable=sum(1 for r in recs.values() for o in r.get('inputs', {}).values() if o.get('c_unstable')))
    json.dump(summary, open(f'{a.out}/b1-summary.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({k: {x: y for x, y in v.items() if x not in ('leave_all_c_unstable', 'unchecked')} for k, v in summary.items()}))


if __name__ == '__main__':
    main()
