#!/usr/bin/env python3
"""Đếm vector TRACTOR dùng cơ chế so filesystem (cổng A3.3, mục 1.4; reporting-rules R24 đề xuất).

Một vector được tính là dùng filesystem nếu có ít nhất một trong các dấu hiệu theo schema TRACTOR
(card tractor-public-test-corpus, okhravi2026-tractor-benchmark tr.6-7):
  - file `file_changes*` nằm trong thư mục vector hoặc cạnh file vector;
  - khoá `file_changes` hoặc `setup` trong JSON của vector;
  - thư mục `resources/` trong case.
Nhóm Examples dùng làm kiểm tra dương tính (có `filesystem_example_lib`).

Cách dùng: python3 -I scan_file_changes.py <thư mục checkout TRACTOR @37960ee> > results/file-changes-scan.txt
"""
import json, os, subprocess, sys

GROUPS = ['B01_organic', 'B01_synthetic', 'B02_organic', 'B02_synthetic', 'P00_perlin_noise', 'P01_sphincs_plus', 'Examples']


def scan_group(root, g):
    base = os.path.join(root, 'Public-Tests', g)
    cases = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
    n_vec = n_key = n_setup = n_tar = n_res = 0
    hit_cases = set()
    for c in cases:
        cdir = os.path.join(base, c)
        for dp, dns, fns in os.walk(cdir, followlinks=False):
            if os.path.basename(dp) == 'resources':
                n_res += 1; hit_cases.add(c)
            if 'test_vectors' not in os.path.relpath(dp, cdir).split(os.sep):
                continue
            for fn in fns:
                p = os.path.join(dp, fn)
                if fn.startswith('file_changes'):
                    n_tar += 1; hit_cases.add(c)
                if fn.endswith('.json'):
                    n_vec += 1
                    try:
                        j = json.load(open(p))
                    except Exception:
                        continue
                    if isinstance(j, dict):
                        if 'file_changes' in j:
                            n_key += 1; hit_cases.add(c)
                        if 'setup' in j:
                            n_setup += 1; hit_cases.add(c)
    return dict(group=g, cases=len(cases), vector_json=n_vec, key_file_changes=n_key, key_setup=n_setup,
                file_changes_files=n_tar, resources_dirs=n_res, cases_with_any=len(hit_cases))


def main():
    root = sys.argv[1]
    head = subprocess.run(['git', '-C', root, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    print(f'# TRACTOR PUBLIC-Test-Corpus @ {head}')
    cols = ['group', 'cases', 'vector_json', 'key_file_changes', 'key_setup', 'file_changes_files', 'resources_dirs', 'cases_with_any']
    print('\t'.join(cols))
    for g in GROUPS:
        r = scan_group(root, g)
        print('\t'.join(str(r[k]) for k in cols))


if __name__ == '__main__':
    main()
