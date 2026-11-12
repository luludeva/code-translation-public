#!/usr/bin/env python3
"""exp 36: dựng corpus phủ cho một lượt held-out. Mọi mục của CORPUS là symlink, trừ đường tới test_vectors/ của case đích: thư mục thật,
chứa symlink tới mọi file của test_vectors/ gốc trừ các vector bị giữ lại. Không sửa corpus gốc.
  python3 experiments/36-heldout/scripts/overlay.py PLAN UNIT CORPUS DEST"""
import json, os, sys


def mirror(src, dst, skip):
    os.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(src)):
        if name in skip: continue
        os.symlink(os.path.join(src, name), os.path.join(dst, name))


def main(plan, unit, corpus, dest):
    u = next(x for x in json.load(open(plan))['units'] if x['unit'] == unit)
    if os.path.exists(dest): raise SystemExit(f'{dest} đã có')
    corpus = os.path.abspath(corpus)
    case_rel = ['tractor', 'Public-Tests', u['bundle'], u['case']]
    cur_src, cur_dst = corpus, dest
    for part in case_rel:
        mirror(cur_src, cur_dst, {part})
        cur_src, cur_dst = os.path.join(cur_src, part), os.path.join(cur_dst, part)
    mirror(cur_src, cur_dst, {'test_vectors'})
    tv_src, tv_dst = os.path.join(cur_src, 'test_vectors'), os.path.join(cur_dst, 'test_vectors')
    have = set(os.listdir(tv_src)); w = set(u['withheld'])
    missing = sorted(w - have)
    if missing: raise SystemExit(f'vector bị giữ lại không có trong corpus: {missing}')
    mirror(tv_src, tv_dst, w)
    kept = sorted(f for f in os.listdir(tv_dst) if f.endswith('.json'))
    print(json.dumps(dict(unit=unit, case=f"{u['bundle']}/{u['case']}", withheld=len(w), kept_json=len(kept), kept=kept)))


if __name__ == '__main__':
    main(*sys.argv[1:5])
