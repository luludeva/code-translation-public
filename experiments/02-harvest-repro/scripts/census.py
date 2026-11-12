#!/usr/bin/env python3
"""A2.2 census: build + chạy oracle gốc (cando_binrunner, TRACTOR @37960ee) cho mọi cặp (executable, hệ).
Ghi mỗi cặp một dòng JSON vào results/census-exe.jsonl; chạy lại thì bỏ qua cặp đã có (resume)."""
import csv, json, os, shutil, subprocess, sys, time, glob, collections
from concurrent.futures import ThreadPoolExecutor
CORPUS = os.environ.get('CORPUS', '/home/claude/corpus')
EXP = os.environ.get('EXP', '/home/claude/exp02')
BUILD = os.environ.get('BUILD', f'{EXP}/.build/census')
RUNNER = f'{CORPUS}/tractor/target/release/cando_binrunner'
OUT = f'{EXP}/results/census-exe.jsonl'
TIMEOUT = 10          # lượt nhanh; cặp published-pass có vector không Pass được chạy lại với 120 s (mặc định TRACTOR)
TIMEOUT_FULL = 120
SYSTEMS = ['kiro', 'claude', 'codex-gpt54', 'c2rust', 'laertes', 'c2saferrust', 'smartc2rust', 'gpt-5.4', 'kimi', 'gemini-3.1-pro-preview']
PILOT = {('B02_organic', 'qmath'), ('B02_synthetic', 'tu_linkage'), ('B02_synthetic', 'static_vars_fpts')}
ENV = dict(os.environ, RUSTUP_TOOLCHAIN='stable')

def sh(cmd, cwd=None, env=None, timeout=900):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env or ENV, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 'timeout', ''

def tally(report):
    r = json.load(open(report))
    return dict(collections.Counter(v['result'] for v in r.values())), len(r)

def build_c(b, tc):
    troot = f'{CORPUS}/tractor/Public-Tests/{b}/{tc}'
    cb = f'{BUILD}/c/{b}/{tc}'
    if not os.path.exists(f'{cb}/driver'):
        rc1, log1 = sh(['cmake', '-S', f'{troot}/test_case', '-B', cb, '-G', 'Ninja', '-DCMAKE_C_COMPILER=clang'])
        rc2, log2 = sh(['cmake', '--build', cb]) if rc1 == 0 else (rc1, '')
        if rc2 != 0: return None, (log1 + log2)[-1500:]
    rep = f'{BUILD}/c/{b}/{tc}.report.json'
    if not os.path.exists(rep):
        sh([RUNNER, '-l', 'quiet', '-t', troot, '--timeout', str(TIMEOUT), '-o', rep, 'bin', '-n', f'{cb}/driver'], timeout=7200)
    return (tally(rep) if os.path.exists(rep) else None), ''

def one(row, s):
    b, tc, hc = row['bundle'], row['tractor_case'], row['harvest_case']
    base = f'{CORPUS}/harvest/Test-Corpus/{s}/{b}/{hc}'
    src = f'{base}/verified' if os.path.isdir(f'{base}/verified') else f'{base}/translated'
    rec = dict(bundle=b, tractor_case=tc, harvest_case=hc, system=s, pilot=(b, tc) in PILOT, source_dir=os.path.basename(src))
    pub = f'{src}/result.json'
    if not os.path.exists(pub):
        rec.update(stage='P0_missing_artifact'); return rec
    pj = json.load(open(pub))
    rec.update(pub_passed=bool(pj.get('passed')), pub_vectors_failed=pj.get('vectors_failed'),
               pub_placeholder=any('no vector-level detail' in str(f.get('reason', '')) for f in pj.get('failures') or []))
    wd = f'{BUILD}/src/{s}/{b}/{hc}'
    shutil.rmtree(wd, ignore_errors=True); os.makedirs(os.path.dirname(wd), exist_ok=True)
    shutil.copytree(src, wd, ignore=shutil.ignore_patterns('target', 'logs'))
    uses_feature = any('#![feature' in open(f, errors='ignore').read() for f in glob.glob(f'{wd}/**/*.rs', recursive=True))
    env = dict(ENV, RUSTC_BOOTSTRAP='1') if uses_feature else ENV
    rec['rustc_bootstrap'] = uses_feature
    td = f'{BUILD}/rust/{s}/{b}/{hc}'
    t0 = time.time(); rc, log = sh(['cargo', 'build', '--release', '--target-dir', td], cwd=wd, env=env); rec['build_secs'] = round(time.time() - t0, 1)
    shutil.rmtree(wd, ignore_errors=True)
    if rc != 0:
        rec.update(build_ok=False, build_log_tail=log[-1500:]); return rec
    bins = [p for p in glob.glob(f'{td}/release/*') if os.path.isfile(p) and os.access(p, os.X_OK) and not p.endswith('.d')]
    binp = f'{td}/release/driver' if f'{td}/release/driver' in bins else (bins[0] if len(bins) == 1 else None)
    if not binp:
        rec.update(build_ok=False, build_log_tail='no unique binary: ' + ','.join(map(os.path.basename, bins))); return rec
    rec['build_ok'] = True
    troot = f'{CORPUS}/tractor/Public-Tests/{b}/{tc}'
    rep = f'{EXP}/results/census-reports/{s}/{b}/{tc}.report.json'
    os.makedirs(os.path.dirname(rep), exist_ok=True)
    t0 = time.time(); sh([RUNNER, '-l', 'quiet', '-t', troot, '--timeout', str(TIMEOUT), '-o', rep, 'bin', '-n', binp], timeout=3600); rec['run_secs'] = round(time.time() - t0, 1)
    shutil.rmtree(td, ignore_errors=True)
    if not os.path.exists(rep):
        rec.update(run_ok=False); return rec
    counts, n = tally(rep)
    rec['timeout_used'] = TIMEOUT
    if rec.get('pub_passed') and any(k not in ('Pass', 'Skip') for k in counts):
        sh([RUNNER, '-l', 'quiet', '-t', troot, '--timeout', str(TIMEOUT_FULL), '-o', rep, 'bin', '-n', binp], timeout=4 * 3600)
        counts, n = tally(rep); rec['timeout_used'] = TIMEOUT_FULL
    rec.update(run_ok=True, vectors=n, results=counts, ours_passed=all(k in ('Pass', 'Skip') for k in counts))
    return rec

def main():
    rows = [r for r in csv.DictReader(open(f'{EXP}/data/case-name-map.tsv'), delimiter='\t') if r['kind'] == 'exe']
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT): d = json.loads(l); done.add((d['bundle'], d['tractor_case'], d['system']))
    # phía C trước (oracle phải pass trên chính C)
    cres = {}
    for r in rows:
        cres[(r['bundle'], r['tractor_case'])] = build_c(r['bundle'], r['tractor_case'])
    json.dump({f'{k[0]}/{k[1]}': {'tally': v[0], 'err': v[1]} for k, v in cres.items()}, open(f'{EXP}/results/census-c-side.json', 'w'), indent=1)
    jobs = [(r, s) for r in rows for s in SYSTEMS if (r['bundle'], r['tractor_case'], s) not in done]
    print(f'{len(jobs)} pairs to run', flush=True)
    from concurrent.futures import as_completed
    with ThreadPoolExecutor(int(os.environ.get('WORKERS', '2'))) as ex, open(OUT, 'a') as f:
        for fut in as_completed([ex.submit(one, *a) for a in jobs]):
            rec = fut.result()
            f.write(json.dumps(rec) + '\n'); f.flush()
            print(rec['system'], rec['tractor_case'], rec.get('build_ok'), rec.get('ours_passed'), flush=True)
main()
