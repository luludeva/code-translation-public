#!/usr/bin/env python3
"""So kết quả cando_binrunner (results/*.report.json) với result.json đã công bố trong HARVEST."""
import json, glob, os, collections
CORPUS = os.environ.get('CORPUS', '/home/claude/corpus')
CASES = [('B02_organic', 'qmath'), ('B02_synthetic', 'tu_linkage'), ('B02_synthetic', 'static-vars-fpts')]
rows = ['case\tsystem\tsource_dir\tvectors\tours_pass\tours_fail\tours_case\tpub_case\tpub_vectors_failed\tpub_placeholder\tcase_match']
for b, c in CASES:
    r = json.load(open(f'results/{c}.C.report.json'))
    k = collections.Counter(v['result'] for v in r.values())
    rows.append(f"{c}\tC(oracle)\ttractor/test_case\t{len(r)}\t{k['Pass']}\t{len(r)-k['Pass']}\t{'P' if k['Pass']==len(r) else 'F'}\t-\t-\t-\t-")
    for s in ['kiro', 'claude', 'c2rust']:
        d = 'verified' if os.path.isdir(f'{CORPUS}/harvest/Test-Corpus/{s}/{b}/{c}/verified') else 'translated'
        pub = json.load(open(f'{CORPUS}/harvest/Test-Corpus/{s}/{b}/{c}/{d}/result.json'))
        r = json.load(open(f'results/{c}.{s}.report.json'))
        k = collections.Counter(v['result'] for v in r.values())
        ours = 'P' if k['Pass'] == len(r) else 'F'
        pubc = 'P' if pub['passed'] else 'F'
        ph = any('no vector-level detail' in str(f.get('reason', '')) for f in pub.get('failures') or [])
        rows.append(f"{c}\t{s}\t{d}\t{len(r)}\t{k['Pass']}\t{len(r)-k['Pass']}\t{ours}\t{pubc}\t{pub['vectors_failed']}\t{'yes' if ph else 'no'}\t{'yes' if ours==pubc else 'NO'}")
open('results/summary.tsv', 'w').write('\n'.join(rows) + '\n')
print('\n'.join(rows))
