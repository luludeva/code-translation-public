#!/usr/bin/env python3
"""Trích quyết định công bố (`passed`, `error`) của mọi cặp executable từ result.json của HARVEST (commit pin trong
results/corpus-pin.txt), cùng quy tắc chọn thư mục với census.py: `verified/` nếu có, ngược lại `translated/`.
Census executable không lưu trường `error`; census library có (`pub_error`). Bảng 3.1 cần tách R0 theo giai đoạn.
Chạy (cần clone HARVEST, xem ci/setup-corpus.sh):
  CORPUS=~/corpus python3 experiments/02-harvest-repro/scripts/extract_pub_error.py
Ghi data/pub-decision-exe.tsv; mỗi cặp trong census-exe-ec2.jsonl một dòng, cặp thiếu bản dịch ghi `missing`."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
H = os.path.join(os.environ.get('CORPUS', os.path.expanduser('~/corpus')), 'harvest', 'Test-Corpus')
CENSUS = os.path.join(HERE, '..', 'results', 'census-exe-ec2.jsonl')
OUT = os.path.join(HERE, '..', 'data', 'pub-decision-exe.tsv')


def main():
    rows = [json.loads(l) for l in open(CENSUS)]
    with open(OUT, 'w') as f:
        f.write('bundle\ttractor_case\tharvest_case\tsystem\tsource_dir\tpassed\terror\n')
        for r in rows:
            base = os.path.join(H, r['system'], r['bundle'], r['harvest_case'])
            if r.get('stage') == 'P0_missing_artifact':
                f.write(f"{r['bundle']}\t{r['tractor_case']}\t{r['harvest_case']}\t{r['system']}\tmissing\t\t\n"); continue
            src = 'verified' if os.path.isdir(os.path.join(base, 'verified')) else 'translated'
            pj = json.load(open(os.path.join(base, src, 'result.json')))
            assert pj.get('passed') is r['pub_passed'], (r['system'], r['tractor_case'])
            assert src == r['source_dir'], (r['system'], r['tractor_case'])
            f.write(f"{r['bundle']}\t{r['tractor_case']}\t{r['harvest_case']}\t{r['system']}\t{src}\t"
                    f"{str(pj['passed']).lower()}\t{pj.get('error') or ''}\n")


if __name__ == '__main__':
    main()
