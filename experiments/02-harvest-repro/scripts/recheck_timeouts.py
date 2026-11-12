#!/usr/bin/env python3
"""Kiểm lại 55 cặp executable hao hụt P_acc → P_rep chỉ vì Timeout (census A2.2, `results/funnel-exe.tsv`,
cột acc_repfail_timeout_only), theo cùng thủ tục đã dùng cho library (job `recheck-loss`, Le chọn 20/10):
  - chạy tuần tự, một cặp một lúc (census chạy 2 worker song song, timeout có thể do tranh tài nguyên);
  - timeout TO giây mỗi vector (mặc định 120, mặc định TRACTOR) ngay từ đầu, lặp REPS lần (mặc định 3);
  - chỉ build và chạy phía Rust: oracle gốc so với kỳ vọng ghi trong vector, không cần binary C.
Danh sách cặp: công bố đỗ, không pilot, mọi vector không Pass/Skip đều là Timeout.
Đầu ra: $OUT/recheck-timeout-exe.jsonl, mỗi cặp một dòng, kèm `stable` (3 lần cho cùng kết quả) và `ours_passed`."""
import glob, json, os, shutil, subprocess, time
HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.environ['CORPUS']; B = os.environ['B']; OUT = os.environ['OUT']
RUNNER = os.environ.get('RUNNER', f'{CORPUS}/cando2/target/release/cando_binrunner')
REPS, TO = int(os.environ.get('REPS', '3')), int(os.environ.get('TO', '120'))
PILOT = {('B02_organic', 'qmath'), ('B02_synthetic', 'tu_linkage'), ('B02_synthetic', 'static_vars_fpts')}


def sh(cmd, cwd=None, env=None, timeout=3600):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 'timeout', ''


def targets():
    rows = [json.loads(l) for l in open(os.path.join(HERE, '..', 'results', 'census-exe.jsonl'))]
    return [r for r in rows if r.get('pub_passed') and (r['bundle'], r['tractor_case']) not in PILOT
            and r.get('results') and set(r['results']) - {'Pass', 'Skip'} == {'Timeout'}]


def recheck(r):
    b, tc, hc, s = r['bundle'], r['tractor_case'], r['harvest_case'], r['system']
    base = f'{CORPUS}/harvest/Test-Corpus/{s}/{b}/{hc}'
    src = f'{base}/verified' if os.path.isdir(f'{base}/verified') else f'{base}/translated'
    rec = dict(bundle=b, tractor_case=tc, harvest_case=hc, system=s, census_results=r['results'])
    wd = f'{B}/src/{s}/{b}/{hc}'; shutil.rmtree(wd, ignore_errors=True); os.makedirs(os.path.dirname(wd), exist_ok=True)
    shutil.copytree(src, wd, ignore=shutil.ignore_patterns('target', 'logs'))
    feat = any('#![feature' in open(f, errors='ignore').read() for f in glob.glob(f'{wd}/**/*.rs', recursive=True))
    env = dict(os.environ, RUSTC_BOOTSTRAP='1') if feat else dict(os.environ)
    rec['rustc_bootstrap'] = feat
    td = f'{B}/rust/{s}/{b}/{hc}'; shutil.rmtree(td, ignore_errors=True)
    t0 = time.time(); rc, log = sh(['cargo', 'build', '--release', '--target-dir', td], cwd=wd, env=env)
    rec['build_secs'] = round(time.time() - t0, 1); shutil.rmtree(wd, ignore_errors=True)
    if rc != 0:
        rec.update(build_ok=False, build_log_tail=log[-1500:]); return rec
    bins = [p for p in glob.glob(f'{td}/release/*') if os.path.isfile(p) and os.access(p, os.X_OK) and not p.endswith('.d')]
    binp = f'{td}/release/driver' if f'{td}/release/driver' in bins else (bins[0] if len(bins) == 1 else None)
    if not binp:
        rec.update(build_ok=False, build_log_tail='no unique binary: ' + ','.join(map(os.path.basename, bins))); return rec
    rec['build_ok'] = True
    troot = f'{CORPUS}/tractor/Public-Tests/{b}/{tc}'
    rec['reps'] = []
    for k in range(REPS):
        rep = f'{OUT}/reports/{s}/{b}/{tc}.rep{k}.json'; os.makedirs(os.path.dirname(rep), exist_ok=True)
        t0 = time.time()
        rc, log = sh([RUNNER, '-l', 'quiet', '-t', troot, '--timeout', str(TO), '-o', rep, 'bin', '-n', binp], timeout=6 * 3600)
        one = dict(secs=round(time.time() - t0, 1), runner_rc=rc, runner_log_tail=(log or '')[-800:])
        if os.path.exists(rep):
            d = json.load(open(rep))
            one['results'] = {v: d[v]['result'] for v in sorted(d)}
            one['diffs'] = {v: d[v].get('diff', '')[:600] for v in sorted(d) if d[v]['result'] not in ('Pass', 'Skip')}
        rec['reps'].append(one)
    outs = [json.dumps(x.get('results'), sort_keys=True) for x in rec['reps']]
    rec['stable'] = len(set(outs)) == 1
    rec['ours_passed'] = all(x.get('results') and all(v in ('Pass', 'Skip') for v in x['results'].values()) for x in rec['reps'])
    shutil.rmtree(td, ignore_errors=True)
    return rec


def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(B, exist_ok=True)
    tg = targets(); print(len(tg), 'cặp', flush=True)
    with open(f'{OUT}/recheck-timeout-exe.jsonl', 'w') as f:
        for r in tg:
            rec = recheck(r)
            f.write(json.dumps(rec, ensure_ascii=False) + '\n'); f.flush()
            print(r['system'], r['tractor_case'], rec.get('build_ok'), rec.get('ours_passed'), rec.get('stable'),
                  [x.get('secs') for x in rec.get('reps', [])], flush=True)


if __name__ == '__main__':
    main()
