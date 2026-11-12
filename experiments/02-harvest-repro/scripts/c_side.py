#!/usr/bin/env python3
"""Kiểm tính hợp lệ của oracle trên chính C: build C đúng như orchestrator TRACTOR (dùng CMakePresets.json
nếu có, preset 'test'), chạy cando_binrunner trên vector; case nào C không pass vector của chính nó bị loại khỏi population."""
import csv, json, os, shutil, subprocess, glob, collections
CORPUS = '/home/claude/corpus'; EXP = '/home/claude/exp02'; B = f'{EXP}/.build/c-oracle'
RUNNER = f'{CORPUS}/tractor/target/release/cando_binrunner'
rows = [r for r in csv.DictReader(open(f'{EXP}/data/case-name-map.tsv'), delimiter='\t') if r['kind'] == 'exe']
out = {}
for r in rows:
    b, tc = r['bundle'], r['tractor_case']; troot = f'{CORPUS}/tractor/Public-Tests/{b}/{tc}'
    wd = f'{B}/{b}/{tc}'; shutil.rmtree(wd, ignore_errors=True); os.makedirs(wd)
    shutil.copytree(f'{troot}/test_case', f'{wd}/test_case')
    preset = os.path.exists(f'{troot}/CMakePresets.json')
    if preset:
        for f in ('CMakePresets.json', 'CMakeLists.txt'):
            if os.path.exists(f'{troot}/{f}'): shutil.copy(f'{troot}/{f}', wd)
        cfg = ['cmake', '-S', wd, '--preset', 'test', '-DCMAKE_C_COMPILER=clang']; bdir = f'{wd}/build-ninja'
    else:
        bdir = f'{wd}/build-ninja'; cfg = ['cmake', '-S', f'{wd}/test_case', '-B', bdir, '-G', 'Ninja', '-DCMAKE_C_COMPILER=clang']
    p1 = subprocess.run(cfg, capture_output=True, text=True)
    p2 = subprocess.run(['cmake', '--build', bdir], capture_output=True, text=True) if p1.returncode == 0 else p1
    drivers = [p for p in glob.glob(f'{bdir}/**/driver', recursive=True) if os.access(p, os.X_OK)]
    rec = dict(preset=preset, build_ok=p2.returncode == 0 and len(drivers) == 1)
    if rec['build_ok']:
        rep = f'{wd}.report.json'
        subprocess.run([RUNNER, '-l', 'quiet', '-t', troot, '--timeout', '120', '-o', rep, 'bin', '-n', drivers[0]], capture_output=True, timeout=7200)
        if os.path.exists(rep):
            c = collections.Counter(v['result'] for v in json.load(open(rep)).values()); rec['results'] = dict(c)
            rec['c_passes_own_vectors'] = all(k in ('Pass', 'Skip') for k in c)
    else:
        rec['err'] = ((p1.stdout + p1.stderr)[-600:] + (p2.stdout + p2.stderr)[-600:])
    out[f'{b}/{tc}'] = rec; print(b, tc, rec.get('c_passes_own_vectors'), flush=True)
json.dump(out, open(f'{EXP}/results/c-oracle-validity.json', 'w'), indent=1)
bad = {k: v for k, v in out.items() if not v.get('c_passes_own_vectors')}
print('cases', len(out), 'C fails own vectors or not built:', len(bad), list(bad)[:10])
