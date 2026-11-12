#!/usr/bin/env python3
"""Dữ liệu 2 của exp 12: các vector bị từ chối mà runner báo kênh lệch đầu tiên là stderr (fail-channels.txt), đọc trước Protocol Freeze
với sự đồng ý của Le (22/10). Lấy stderr thực tế của Rust từ báo cáo runner và stderr kỳ vọng từ file vector (kỳ vọng là output của C).
Xếp nhóm bằng đúng luật của classify.py. Đầu ra: results/rq2-stderr-vectors.jsonl."""
import glob, json, os, sys, tarfile, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
from classify import group   # noqa: E402
from harness.config import T  # noqa: E402

SRC = dict(exe=('experiments/02-harvest-repro/results/census-exe-ec2.jsonl', 'experiments/02-harvest-repro/results/census-exe-ec2-reports.tar.gz'),
           lib=('experiments/06-library-census/results/census-lib-c7i.jsonl', 'experiments/06-library-census/results/census-lib-c7i-reports.tar.gz'))
out = []
tmp = tempfile.mkdtemp()
for kind, (census, tgz) in SRC.items():
    rows = {(r['system'], r['bundle'], r['tractor_case']): r for r in map(json.loads, open(os.path.join(ROOT, census)))
            if r.get('pub_passed') is False and not r['pilot'] and r.get('build_ok')}
    d = os.path.join(tmp, kind); os.makedirs(d)
    with tarfile.open(os.path.join(ROOT, tgz)) as t: t.extractall(d, filter='data')
    for f in glob.glob(f'{d}/**/*.json', recursive=True):
        p = f.split('/'); key = (p[-3], p[-2], os.path.basename(f).split('.')[0])
        if key not in rows: continue
        for v, o in json.load(open(f)).items():
            if o.get('result') != 'VectorComparisonFailed' or not str(o.get('diff', '')).startswith('Stderr diff'): continue
            vf = os.path.join(T, key[1], key[2], 'test_vectors', os.path.basename(v))
            vec = json.load(open(vf)) if os.path.exists(vf) else {}
            exp = vec.get('stderr'); exp_pat = exp.get('pattern') if isinstance(exp, dict) else exp
            is_re = exp.get('is_regex') if isinstance(exp, dict) else None
            got = ((o.get('output') or {}).get('stderr')) or (o.get('common_out') or {}).get('stderr') or ''
            r = dict(kind=kind, system=key[0], bundle=key[1], case=key[2], vector=os.path.basename(v), c_err=exp_pat or '', r_err=got,
                     expect_is_regex=is_re, diff=str(o.get('diff'))[:600], c_bin='', r_bin='')
            g, c, x = group(r); r.update(group=g, c_norm=c[:500], r_norm=x[:500])
            out.append(r)
with open(os.path.join(ROOT, 'experiments/12-stderr-audit/results/rq2-stderr-vectors.jsonl'), 'w') as fo:
    for r in sorted(out, key=lambda r: (r['kind'], r['case'], r['system'], r['vector'])): fo.write(json.dumps(r, ensure_ascii=False) + '\n')
for r in out: print(r['kind'], r['system'], r['case'], r['vector'], r['group'], 'regex' if r['expect_is_regex'] else '', '| C:', repr(r['c_norm'][:120]), '| R:', repr(r['r_norm'][:120]))
