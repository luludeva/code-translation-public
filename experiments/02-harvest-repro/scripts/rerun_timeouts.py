#!/usr/bin/env python3
"""Chạy lại tuần tự (1 worker, máy không tải) các cặp published-pass mà census ghi nhận Timeout, để tách timeout do tải máy."""
import json, os
src = open(os.path.join(os.path.dirname(__file__), 'census.py')).read().replace('\nmain()\n', '\n')
g = {'__name__': 'census_mod'}; exec(src, g)
recs = {}
for l in open('results/census-exe.jsonl'):
    r = json.loads(l); recs[(r['bundle'], r['tractor_case'], r['system'])] = r
todo = [r for r in recs.values() if r.get('pub_passed') and 'Timeout' in (r.get('results') or {})]
print(len(todo), 'pairs', flush=True)
g['TIMEOUT'] = 120
with open('results/census-rerun-timeouts.jsonl', 'w') as f:
    for r in todo:
        row = dict(bundle=r['bundle'], tractor_case=r['tractor_case'], harvest_case=r['harvest_case'], kind='exe')
        new = g['one'](row, r['system']); new['rerun_of_timeout'] = True
        f.write(json.dumps(new) + '\n'); f.flush()
        print(new['system'], new['tractor_case'], new.get('results'), flush=True)
