#!/usr/bin/env python3
"""Kiểm tín hiệu "vectors_failed giữ chỗ" (W5) trên toàn bộ cặp bị từ chối ở bước test, executable và library, không pilot.
So `vectors_failed` công bố (result.json của HARVEST `38352c2`) với số vector không Pass/Skip khi tái lập dưới TRACTOR `37960ee` trên EC2
c7i (census-exe-ec2.jsonl, census-lib-c7i.jsonl). Ba dạng result.json (sửa 2026-10-22, sau khi đọc thô mẫu 12 file):
  có chi tiết: danh sách `failures` khác rỗng, mỗi vector trượt một dòng;
  giữ chỗ dạng 1: có failure mang lý do chứa "no vector-level detail";
  giữ chỗ dạng 2: không có trường `failures` (hoặc rỗng) mà `vectors_failed` khác 0 (chỉ gặp ở codex-gpt54).
Cần clone HARVEST (CORPUS). Chạy: CORPUS=~/corpus python3 experiments/02-harvest-repro/scripts/check_vectors_failed.py"""
import collections, json, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
H = os.path.join(os.environ.get('CORPUS', os.path.expanduser('~/corpus')), 'harvest', 'Test-Corpus')
SRC = dict(exe='experiments/02-harvest-repro/results/census-exe-ec2.jsonl', lib='experiments/06-library-census/results/census-lib-c7i.jsonl')


def main():
    for kind, f in SRC.items():
        rows = [json.loads(l) for l in open(os.path.join(ROOT, f))]
        rej = [r for r in rows if not r['pilot'] and r.get('pub_passed') is False]
        cnt, examples = collections.Counter(), collections.defaultdict(list)
        for r in rej:
            base = os.path.join(H, r['system'], r['bundle'], r['harvest_case'])
            pj = json.load(open(os.path.join(base, r['source_dir'], 'result.json')))
            if pj.get('error') != 'test failed': continue
            fl = pj.get('failures') or []
            ph1 = any('no vector-level detail' in str(x.get('reason', '')) for x in fl)
            form = 'giữ chỗ dạng 1' if ph1 else ('giữ chỗ dạng 2' if not fl else 'có chi tiết')
            nfail_list = len(pj.get('failures') or [])
            if not r.get('build_ok') or r.get('results') is None:
                cat = 'không build khi tái lập'
            else:
                rep = sum(v for k, v in r['results'].items() if k not in ('Pass', 'Skip'))
                pub = pj.get('vectors_failed')
                cat = ('tái lập đỗ' if rep == 0 else 'khớp' if rep == pub else 'công bố < tái lập' if pub < rep else 'công bố > tái lập')
            key = (form, cat)
            cnt[key] += 1
            if len(examples[key]) < 3: examples[key].append(f"{r['system']}/{r['tractor_case']} công bố {pj.get('vectors_failed')} (danh sách {nfail_list}), tái lập {r.get('results')}")
        print(f'== {kind}: bị từ chối ở bước test {sum(cnt.values())}')
        for k, n in sorted(cnt.items()):
            print(f'   {n:4d}  {k[0]:15s} {k[1]}')
            for e in examples[k]: print('          vd', e)


if __name__ == '__main__':
    main()
