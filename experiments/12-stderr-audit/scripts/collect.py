#!/usr/bin/env python3
"""Thu cặp stderr (C, Rust) trên input pilot mà quan sát của oracle bằng nhau (README exp 12, dữ liệu 1).

Dùng đúng mã của harness: `harness.rq1.gen_exe` (lọc miền runner), `harness.checks._lib_inputs`, `observe.run_exe`, `observe.run_lib`,
`observe.equal_exe`, `observe.equal_lib`. Mức x1, seed 0. Bỏ input mà một bên vượt ngân sách (không có stderr đầy đủ để so).
Ghi: results/pairs-<kind>.jsonl (mỗi dòng một cặp stderr khác nhau) và results/totals-<kind>.json (số input quan sát bằng nhau theo cặp).
Chạy: CORPUS=... HARNESS_BUILD=... python3 experiments/12-stderr-audit/scripts/collect.py [--workers N]"""
import argparse, collections, json, os, sys, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, REPO)
from harness import build as BD, observe as OB, rq1   # noqa: E402
from harness.checks import _lib_inputs   # noqa: E402

OUT = os.path.join(REPO, 'experiments', '12-stderr-audit', 'results')
THETA_EXE = dict(budget=3000, afl_execs=10000); N_LIB = 200; SEED = 0; TIMEOUT = 10


def txt(b, n=4000):
    if isinstance(b, bytes): b = b.decode('utf-8', 'replace')
    return (b or '')[:n]


def exe_case(B, bundle, case, pairs):
    c = BD.build_c_exe(B, bundle, case)
    rust = {p['system']: BD.build_rust_exe(B, p['system'], bundle, case, p['harvest_case']) for p in pairs}
    X, _ = rq1.gen_exe(B, bundle, case, SEED, THETA_EXE, 'stderr-audit')
    tot = collections.defaultdict(collections.Counter); rows = []
    for i, (argv, stdin, src, layer, env) in enumerate(X):
        co = OB.run_exe(c['bin'], argv, stdin, TIMEOUT, env)
        if OB.is_nt(co): continue
        for s, r in rust.items():
            if not r['ok']: continue
            ro = OB.run_exe(r['bin'], argv, stdin, TIMEOUT, env)
            if OB.is_nt(ro) or not OB.equal_exe(co, ro): continue
            tot[s]['equal_obs'] += 1
            if co['err'] == ro['err']: continue
            tot[s]['err_diff'] += 1
            rows.append(dict(kind='exe', bundle=bundle, case=case, system=s, idx=i, source=src, layer=layer, status=co['status'],
                             rc=co['rc'], c_bin=c['bin'], r_bin=r['bin'], c_err=txt(co['err']), r_err=txt(ro['err']),
                             argv=[txt(a, 300) for a in argv], stdin=txt(stdin, 300)))
    return rows, {s: dict(v) for s, v in tot.items()}


def lib_case(B, bundle, case, pairs):
    info = BD.build_lib_case(B, bundle, case)
    if not (info['runner_ok'] and info['c_ok']): return [], {'_error': 'c_build_failed'}
    rust = {p['system']: BD.build_rust_lib(B, p['system'], bundle, case, p['harvest_case'], info['library']) for p in pairs}
    files, _, _ = _lib_inputs(B, info, N_LIB, SEED)
    croot = BD.lib_root(B, info, 'c')
    roots = {s: BD.lib_root(B, info, 'rust', r['dir'], tag=f'rust-{s}') for s, r in rust.items() if r['ok']}
    dd = f'{B}/dumps-stderr/{bundle}/{case}'; os.makedirs(dd, exist_ok=True)
    tot = collections.defaultdict(collections.Counter); rows = []
    for i, (p, src) in enumerate(files):
        n = os.path.basename(p)
        co = OB.run_lib(info['runner_bin'], croot, p, TIMEOUT, False, f'{dd}/{n}.C.dump')
        if OB.lib_timeout(co) or co.get('k1') != 'reported': continue
        for s, root in roots.items():
            ro = OB.run_lib(info['runner_bin'], root, p, TIMEOUT, True, f'{dd}/{n}.{s}.dump')
            if OB.lib_timeout(ro) or not OB.equal_lib(co, ro): continue
            tot[s]['equal_obs'] += 1
            if (co.get('stderr') or '') == (ro.get('stderr') or ''): continue
            tot[s]['err_diff'] += 1
            rows.append(dict(kind='lib', bundle=bundle, case=case, system=s, idx=i, source=src, result=co.get('result'),
                             c_bin=info['c_dir'], r_bin=rust[s]['dir'], c_err=txt(co.get('stderr')), r_err=txt(ro.get('stderr')),
                             input=json.load(open(p))['lib_state_in']))
    return rows, {s: dict(v) for s, v in tot.items()}


def safe(fn, *a):
    try: return fn(*a)
    except Exception: return [], {'_error': traceback.format_exc()[-2000:]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--workers', type=int, default=4); a = ap.parse_args()
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness'))
    os.makedirs(OUT, exist_ok=True)
    for kind, fn in (('exe', exe_case), ('lib', lib_case)):
        if kind == 'lib': BD.setup_cando2(B)
        by = collections.defaultdict(list)
        for r in rq1.pilot_pairs(kind): by[(r['bundle'], r['tractor_case'])].append(r)
        rows, totals = [], {}
        with ProcessPoolExecutor(a.workers) as ex:
            futs = {ex.submit(safe, fn, B, b, c, ps): (b, c) for (b, c), ps in sorted(by.items())}
            for f in as_completed(futs):
                b, c = futs[f]; rr, tt = f.result(); rows += rr; totals[f'{b}/{c}'] = tt
                print(kind, c, len(rr), tt, flush=True)
        with open(f'{OUT}/pairs-{kind}.jsonl', 'w') as fo:
            for r in sorted(rows, key=lambda r: (r['case'], r['system'], r['idx'])): fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        json.dump(totals, open(f'{OUT}/totals-{kind}.json', 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
