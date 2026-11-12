"""Phân tích phụ L3 (amendment 2026-11-01, nhãn post-freeze, KHÔNG phải kết quả chính). File mới theo luật kế thừa tag.

Luật L3: tính lại D/P_test khi một bản dịch thuộc P_test nếu đủ các seed CÓ BẢN GHI (ít nhất một), thay cho luật chính (đủ mọi seed 0,1,2).
"Có bản ghi" theo L2: (case, seed) có bản ghi khác harness_error sau gộp main_merge_v2 (bản gộp đã bỏ bản ghi harness_error).

Cách tính: không viết lại logic đo. Với mỗi case, tập seed yêu cầu là tập seed có bản ghi của case đó; nhóm các case theo tập seed này
và gọi nguyên harness.metrics.rq1_translations cho từng nhóm (seeds = tập seed của nhóm, expected lọc theo case của nhóm), rồi gộp và tóm
tắt bằng harness.metrics.summarize_rq1. Case không có bản ghi nào giữ seed 0,1,2 và rơi vào missing_record như luật chính. Mọi luật khác
(thứ tự mã rời P_test, A1 san_infra, case không đọc input chỉ đòi INSENSITIVE_SEED, tập S, B/N/U) là của metrics.py.

Dùng: python3 -m harness.secondary_l3 --rq1 DIR --kind exe|lib [--expect p_rep] [--seeds 0,1,2] --out FILE.json
DIR là thư mục gộp của một kind (rq1-<kind>.jsonl, div/), như $W/merged-<kind> trong ci/jobs/metrics-main-v2.sh."""
import argparse, collections, json, os, sys

from . import metrics as HM


def run(rq1_dir, kind, seeds, expect=None):
    cases, divs, caps = HM.load_rq1(rq1_dir, kind)
    exp = None
    if expect == 'p_rep':
        from .pairs import prep_pairs; exp = prep_pairs(kind)
    elif expect == 'pilot':
        from .rq1 import pilot_pairs; exp = pilot_pairs(kind)
    have = collections.defaultdict(set)
    for r in cases:
        if r.get('status') != 'harness_error': have[(r['bundle'], r['case'])].add(r['seed'])
    exp_cases = {(e['bundle'], e.get('tractor_case', e.get('case'))) for e in exp} if exp is not None else set()
    group = {}
    for bc in set(have) | exp_cases:
        s = tuple(sd for sd in seeds if sd in have.get(bc, ()))
        group[bc] = s or tuple(seeds)
    T = HM.Translations(); unattr = collections.Counter(); n_exp = 0
    by_seedset = collections.defaultdict(set)
    for bc, s in group.items(): by_seedset[s].add(bc)
    for s, bcs in sorted(by_seedset.items()):
        sub_cases = [r for r in cases if (r['bundle'], r['case']) in bcs]
        sub_exp = None if exp is None else [e for e in exp if (e['bundle'], e.get('tractor_case', e.get('case'))) in bcs]
        t = HM.rq1_translations(sub_cases, divs, caps, list(s), sub_exp)
        T.update(t)
        unattr.update((t.meta or {}).get('unattributed_case_records') or {})
        n_exp += (t.meta or {}).get('expected') or 0
    T.meta = dict(unattributed_case_records=dict(unattr), expected=None if exp is None else n_exp)
    res = HM.summarize_rq1(T, kind)
    res['l3'] = dict(rule='amendment 2026-11-01 L3 (post-freeze, phân tích phụ)',
                     seedsets={','.join(map(str, s)) or '-': len(v) for s, v in sorted(by_seedset.items())},
                     cases_reduced=sorted(f'{b}/{c}:{",".join(map(str, s))}' for (b, c), s in group.items() if s != tuple(seeds)))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness.secondary_l3')
    ap.add_argument('--rq1', required=True); ap.add_argument('--kind', choices=['exe', 'lib'], required=True)
    ap.add_argument('--expect', choices=['pilot', 'p_rep']); ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    res = run(a.rq1, a.kind, [int(x) for x in a.seeds.split(',')], a.expect)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    with open(a.out, 'w') as f: json.dump(res, f, indent=1, ensure_ascii=False, sort_keys=True)
    print(f'Đã ghi {a.out}: seedsets {res["l3"]["seedsets"]}', file=sys.stderr)


if __name__ == '__main__':
    main()
