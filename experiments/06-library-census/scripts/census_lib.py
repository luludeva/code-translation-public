#!/usr/bin/env python3
"""Census library (mốc 1 của checkpoint library, decision-log 2026-10-14): tái lập verdict TRACTOR cho mọi cặp (library, hệ).

Cùng quy ước với census executable (exp 02, `census.py`):
  - nguồn Rust: `verified/` nếu có, ngược lại `translated/`; `RUSTC_BOOTSTRAP=1` khi source có `#![feature`;
  - lượt nhanh timeout 10 giây; cặp công bố đỗ mà có vector không Pass thì chạy lại với 120 giây (mặc định TRACTOR).
Riêng library: runner crate của từng case (macro `harness!`) build một lần, dùng chung cho C và các hệ; C build theo preset
khi case có `CMakePresets.json`. cando2 dùng bản có patch xuất output của exp 05; patch không hoạt động khi không đặt
`CANDO2_STATE_DUMP`, nên verdict giống cando2 gốc.
Ghi mỗi cặp một dòng JSON vào census-lib.jsonl; chạy lại thì bỏ qua cặp đã có."""
import collections, csv, glob, json, os, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '05-library-spike', 'scripts'))
import spike_lib as S
from libtypes import parse_runner

CORPUS = S.CORPUS; B = os.environ['B']; OUT = os.environ['OUT']
T = f'{CORPUS}/tractor/Public-Tests'; H = f'{CORPUS}/harvest/Test-Corpus'
MAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '02-harvest-repro', 'data', 'case-name-map.tsv')
SYSTEMS = ['kiro', 'claude', 'codex-gpt54', 'c2rust', 'laertes', 'c2saferrust', 'smartc2rust', 'gpt-5.4', 'kimi', 'gemini-3.1-pro-preview']
PILOT = {os.path.basename(p) for p in S.SAMPLE}
NO_INPUT = {'001_helloworld_lib', '013_poor_quality_addition_lib', '014_dead_code_lib', 'parse_uname_lib'}
TIMEOUT, TIMEOUT_FULL = 10, 120


def sh(cmd, cwd=None, env=None, timeout=1800):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-3000:]
    except subprocess.TimeoutExpired:
        return 'timeout', ''


def tally(rep):
    r = json.load(open(rep)); return dict(collections.Counter(v['result'] for v in r.values())), len(r)


def prepare_case(b, tc):
    """Runner crate + C build + root C. Trả về dict thông tin case."""
    troot = f'{T}/{b}/{tc}'; info = dict(bundle=b, case=tc)
    parsed = parse_runner(open(f'{troot}/runner/src/main.rs').read())
    info['library'] = parsed.get('library') or tc
    rdir = f'{B}/runners/{tc}'; shutil.rmtree(rdir, ignore_errors=True)
    shutil.copytree(f'{troot}/runner', rdir, ignore=shutil.ignore_patterns('target', 'fuzz'))
    toml = open(f'{rdir}/Cargo.toml').read().replace('path = "../../../../tools/cando2"', f'path = "{B}/cando2-dump"')
    if '[workspace]' not in toml: toml += '\n[workspace]\n'
    open(f'{rdir}/Cargo.toml', 'w').write(toml)
    if os.path.exists(f'{B}/cando2-dump/Cargo.lock'): shutil.copy(f'{B}/cando2-dump/Cargo.lock', f'{rdir}/Cargo.lock')
    pkg = re.search(r'name\s*=\s*"([^"]+)"', toml).group(1)
    rc, log = sh(['cargo', 'build', '--release', '-q', '--target-dir', f'{B}/runner-target'], cwd=rdir)
    info['runner_ok'] = rc == 0; info['runner_bin'] = f'{B}/runner-target/release/{pkg}'
    if rc != 0: info['runner_log'] = log[-1500:]
    cb = f'{B}/c/{b}/{tc}'
    if not os.path.exists(f'{cb}/lib{info["library"]}.so'):
        shutil.rmtree(cb, ignore_errors=True)
        preset = S.configure_preset(troot)
        cfg = (['cmake', '-S', troot, '--preset', preset, '-B', cb] if preset
               else ['cmake', '-S', f'{troot}/test_case', '-B', cb, '-G', 'Ninja']) + ['-DCMAKE_C_COMPILER=clang']
        rc1, l1 = sh(cfg); rc2, l2 = sh(['cmake', '--build', cb]) if rc1 == 0 else (1, '')
        if rc1 or rc2: info['c_log'] = (l1 + l2)[-1500:]
    info['c_so'] = os.path.exists(f'{cb}/lib{info["library"]}.so')
    root = f'{B}/roots/C/{b}/{tc}'; shutil.rmtree(root, ignore_errors=True); os.makedirs(os.path.dirname(root), exist_ok=True); os.makedirs(root)
    os.symlink(f'{troot}/test_case', f'{root}/test_case'); os.symlink(f'{troot}/test_vectors', f'{root}/test_vectors'); os.symlink(cb, f'{root}/build-ninja')
    info['n_vectors'] = len([f for f in glob.glob(f'{troot}/test_vectors/*.json') if open(f).read().strip()])
    if info['runner_ok'] and info['c_so']:
        rep = f'{OUT}/reports/C/{b}/{tc}.json'; os.makedirs(os.path.dirname(rep), exist_ok=True)
        sh([info['runner_bin'], '-l', 'quiet', '-t', root, '--timeout', str(TIMEOUT), '-o', rep, 'lib'], timeout=3600)
        info['c_results'] = tally(rep)[0] if os.path.exists(rep) else None
    return info


def one(info, row, s):
    b, tc, hc = row['bundle'], row['tractor_case'], row['harvest_case']
    base = f'{H}/{s}/{b}/{hc}'
    src = f'{base}/verified' if os.path.isdir(f'{base}/verified') else f'{base}/translated'
    rec = dict(bundle=b, tractor_case=tc, harvest_case=hc, system=s, pilot=tc in PILOT, no_input=tc in NO_INPUT,
               n_vectors=info['n_vectors'], source_dir=os.path.basename(src))
    if not os.path.exists(f'{src}/result.json'):
        rec.update(stage='P0_missing_artifact'); return rec
    pj = json.load(open(f'{src}/result.json'))
    rec.update(pub_passed=bool(pj.get('passed')), pub_vectors_failed=pj.get('vectors_failed'), pub_error=pj.get('error'))
    if not (info['runner_ok'] and info['c_so']):
        rec.update(stage='harness_case_fail'); return rec
    wd = f'{B}/src/{s}/{b}/{hc}'; shutil.rmtree(wd, ignore_errors=True); os.makedirs(os.path.dirname(wd), exist_ok=True)
    shutil.copytree(src, wd, ignore=shutil.ignore_patterns('target', 'logs'))
    feat = any('#![feature' in open(f, errors='ignore').read() for f in glob.glob(f'{wd}/**/*.rs', recursive=True))
    env = dict(os.environ, RUSTC_BOOTSTRAP='1') if feat else dict(os.environ)
    rec['rustc_bootstrap'] = feat
    td = f'{B}/rust/{s}/{b}/{hc}'
    t0 = time.time(); rc, log = sh(['cargo', 'build', '--release', '--target-dir', f'{td}/target'], cwd=wd, env=env); rec['build_secs'] = round(time.time() - t0, 1)
    shutil.rmtree(wd, ignore_errors=True)
    so = f'{td}/target/release/lib{info["library"]}.so'
    if rc != 0:
        rec.update(build_ok=False, build_log_tail=log[-1500:]); shutil.rmtree(td, ignore_errors=True); return rec
    if not os.path.exists(so):
        rec.update(build_ok=False, build_log_tail='no lib%s.so; found: %s' % (info['library'], ','.join(os.path.basename(x) for x in glob.glob(f'{td}/target/release/*.so'))))
        shutil.rmtree(td, ignore_errors=True); return rec
    rec['build_ok'] = True
    root = f'{B}/roots/{s}/{b}/{tc}'; shutil.rmtree(root, ignore_errors=True); os.makedirs(os.path.dirname(root), exist_ok=True); os.makedirs(root)
    troot = f'{T}/{b}/{tc}'
    os.symlink(f'{troot}/test_case', f'{root}/test_case'); os.symlink(f'{troot}/test_vectors', f'{root}/test_vectors')
    os.symlink(f'{B}/c/{b}/{tc}', f'{root}/build-ninja'); os.symlink(td, f'{root}/translated_rust')
    rep = f'{OUT}/reports/{s}/{b}/{tc}.json'; os.makedirs(os.path.dirname(rep), exist_ok=True)
    t0 = time.time(); sh([info['runner_bin'], '-l', 'quiet', '-t', root, '--rust', '--timeout', str(TIMEOUT), '-o', rep, 'lib'], timeout=3600)
    rec['run_secs'] = round(time.time() - t0, 1); rec['timeout_used'] = TIMEOUT
    if not os.path.exists(rep):
        rec.update(run_ok=False); shutil.rmtree(td, ignore_errors=True); return rec
    counts, n = tally(rep)
    if rec['pub_passed'] and any(k not in ('Pass', 'Skip') for k in counts):
        sh([info['runner_bin'], '-l', 'quiet', '-t', root, '--rust', '--timeout', str(TIMEOUT_FULL), '-o', rep, 'lib'], timeout=4 * 3600)
        counts, n = tally(rep); rec['timeout_used'] = TIMEOUT_FULL
    rec.update(run_ok=True, vectors=n, results=counts, ours_passed=all(k in ('Pass', 'Skip') for k in counts))
    shutil.rmtree(td, ignore_errors=True)
    return rec


def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(B, exist_ok=True)
    S.B = B; S.setup_cando2()
    rows = [r for r in csv.DictReader(open(MAP), delimiter='\t') if r['kind'] == 'lib' and r['bundle'] != 'Examples']
    outf = f'{OUT}/census-lib.jsonl'; done = set()
    if os.path.exists(outf):
        for l in open(outf): d = json.loads(l); done.add((d['bundle'], d['tractor_case'], d['system']))
    cinfo = {}
    cpath = f'{OUT}/census-lib-c-side.json'
    for r in rows:
        cinfo[(r['bundle'], r['tractor_case'])] = prepare_case(r['bundle'], r['tractor_case'])
        print('C', r['tractor_case'], cinfo[(r['bundle'], r['tractor_case'])].get('c_results'), flush=True)
    json.dump({f'{k[0]}/{k[1]}': v for k, v in cinfo.items()}, open(cpath, 'w'), indent=1)
    jobs = [(cinfo[(r['bundle'], r['tractor_case'])], r, s) for r in rows for s in SYSTEMS if (r['bundle'], r['tractor_case'], s) not in done]
    print(len(jobs), 'pairs', flush=True)
    with ThreadPoolExecutor(int(os.environ.get('WORKERS', '2'))) as ex, open(outf, 'a') as f:
        for fut in as_completed([ex.submit(one, *a) for a in jobs]):
            rec = fut.result(); f.write(json.dumps(rec) + '\n'); f.flush()
            print(rec['system'], rec['tractor_case'], rec.get('build_ok'), rec.get('ours_passed'), flush=True)


if __name__ == '__main__':
    main()
