#!/usr/bin/env python3
"""exp 39 A: V3-C chạy bù trên S₀ (README mục A; post hoc, †). Chỉ đọc bản ghi trên nhánh results, không đổi số đo.
  python3 experiments/39-prereg-backfill/scripts/v3c.py exe|lib [--workers 2] > experiments/39-prereg-backfill/results/v3c-<kind>.json"""
import argparse, base64, collections, gzip, io, json, os, subprocess, sys
from concurrent.futures import ProcessPoolExecutor

try:
    import orjson
    loads = orjson.loads
except ImportError:
    loads = json.loads

SHARDS = dict(exe=[('rq1-main-exe-1of2', '1fa636f'), ('rq1-main-exe-2of2', 'c867337'), ('rq1-main-exe-light', '40fedd1')],
              lib=[('rq1-main-lib-1of2', 'a980c52'), ('rq1-main-lib-2of2', '97f80c5'), ('rq1-main-lib-shgeti', 'c8c41a3'),
                   ('rq1-main-lib-2of2-light', 'e8f9704')])


def run(*a): return subprocess.run(a, capture_output=True, check=True).stdout


def full(c): return run('git', 'rev-parse', c).decode().strip()


def tree(c, prefix):
    out = {}
    for l in run('git', 'ls-tree', '-r', c, prefix).decode().splitlines():
        meta, path = l.split('\t'); out[path] = meta.split()[2]
    return out


def unblob(b):
    if not isinstance(b, dict): return None, False
    return gzip.decompress(base64.b64decode(b['gz64'])), bool(b.get('truncated'))


def in_domain_bytes(argv, stdin):
    """harness.rq1.in_domain trên bytes đã lưu (blob(to_bytes(.))): argv không chứa NUL; argv, stdin là UTF-8 hợp lệ."""
    try:
        for a in argv:
            if b'\x00' in a: return False
            a.decode('utf-8')
        stdin.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def san_status(d):
    s = d.get('san')
    return s.get('status') if isinstance(s, dict) else s


def unit(args):
    kind, b, cs, sd, blobs, sys_ok, exp_ret = args
    c = collections.Counter(); got = collections.Counter()
    if not blobs:
        c['no_div_file'] += 1
        if any(exp_ret.values()): c['integrity_retained_missing'] += sum(exp_ret.values())
        return c
    data = b''.join(run('git', 'cat-file', 'blob', x) for x in blobs)
    with gzip.open(io.BytesIO(data), 'rb') as f:
        for l in f:
            if not l.strip(): continue
            d = loads(l)
            if d.get('system') not in sys_ok: continue
            c['div'] += 1
            if not d.get('retained'): continue
            c['retained'] += 1; got[d['system']] += 1
            if san_status(d) != 'no_report': c['viol_san'] += 1
            if d.get('stable') is not True: c['viol_unstable'] += 1
            if kind == 'exe':
                av = [unblob(x) for x in d.get('argv') or []]; si = unblob(d.get('stdin'))
                if any(x[0] is None for x in av) or si[0] is None: c['unverifiable_missing'] += 1
                elif any(x[1] for x in av) or si[1]: c['unverifiable_truncated'] += 1
                elif not in_domain_bytes([x[0] for x in av], si[0]): c['viol_ood'] += 1
            else:
                if (d.get('c') or {}).get('k1') == 'invalid_input': c['viol_ood'] += 1
    # toàn vẹn (ngoài tiêu chí V3-C): số divergence giữ lại trong file so với bộ đếm div_stable_noub của bản ghi
    for s, n in exp_ret.items():
        if got[s] != n: c['integrity_retained_mismatch'] += abs(got[s] - n)
    return c


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('kind', choices=['exe', 'lib']); ap.add_argument('--workers', type=int, default=2)
    a = ap.parse_args()
    chosen, trees = {}, {}
    for job, cm in SHARDS[a.kind]:
        fc = full(cm); trees[job] = (fc, tree(fc, f'ci-out/{job}/div/'))
        for l in run('git', 'show', f'{fc}:ci-out/{job}/rq1-{a.kind}.jsonl').decode().splitlines():
            if not l.strip(): continue
            r = json.loads(l)
            if r.get('status') == 'harness_error': continue      # L5 như harness.main_merge_v2.build_views: bản ghi khác harness_error đầu tiên
            chosen.setdefault((r['bundle'], r['case'], r['seed']), (job, r))
    jobs = []
    for (b, cs, sd), (job, r) in sorted(chosen.items()):
        sys_ok = {s for s, st in (r.get('pair_status') or {}).items() if st == 'P_test'}
        if not sys_ok: continue
        fc, t = trees[job]; base = f'ci-out/{job}/div/{b}__{cs}__s{sd}.jsonl'
        blobs = ([t[base + '.gz']] if base + '.gz' in t else [t[p] for p in sorted(p for p in t if p.startswith(base + '.gz.part'))]
                 or [t[p] for p in sorted(p for p in t if p.startswith(base + '.part'))])
        exp_ret = {s: ((r.get('counts') or {}).get(s) or {}).get('div_stable_noub', 0) for s in sys_ok}
        jobs.append((a.kind, b, cs, sd, blobs, sys_ok, exp_ret))
    tot = collections.Counter(); per_case = {}
    with ProcessPoolExecutor(a.workers) as ex:
        for j, c in zip(jobs, ex.map(unit, jobs)):
            tot.update(c)
            if any(k.startswith(('viol', 'unverifiable', 'integrity', 'no_div')) for k in c): per_case[f'{j[1]}/{j[2]}/s{j[3]}'] = dict(c)
            print(f'{j[1]}/{j[2]}/s{j[3]} {dict(c)}', file=sys.stderr, flush=True)
    viol = sum(v for k, v in tot.items() if k.startswith('viol'))
    print(json.dumps(dict(rule='exp 39 A, V3-C chạy bù (README); post hoc, sơ bộ, chưa kiểm tay', kind=a.kind,
                          units_case_seed=len(jobs), totals=dict(tot), violations=viol, ok=viol == 0, units_with_findings=per_case,
                          sources=[f'{j}@{full(c)}' for j, c in SHARDS[a.kind]]), indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
