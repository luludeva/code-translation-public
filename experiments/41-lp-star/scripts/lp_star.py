#!/usr/bin/env python3
"""Exp 41: acceptance trong L_P đã có retained divergence trên các seed hoàn tất (L_P \\ L_P*), theo hệ.

Không viết lại logic đo: với mỗi case thiếu seed, gọi nguyên harness.metrics.rq1_translations với tập seed có bản ghi của case đó, như
harness/secondary_l3.py (L3). Chỉ nhóm "seed missing" có bằng chứng được ghi: case "record missing" không có bản ghi nào, và bản library
"incomplete" không có divergence được lưu, nên hai nhóm này giữ trong L_P*.

Dùng (từ gốc repo, sau scripts/fetch.sh DIR):
  python3 experiments/41-lp-star/scripts/lp_star.py DIR
Ghi results/lp-star-exe.json, results/lp-star-lib.json; kiểm tổng khớp L3 (experiments/30-main-s0/results/l3-*.json)."""
import collections, json, os, shutil, sys

sys.path.insert(0, os.getcwd())
from harness import metrics as HM          # noqa: E402
from harness.pairs import prep_pairs       # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE_CASES = {('B01_synthetic', '012_uninit_int_ptr'), ('B01_synthetic', '017_signed_length_confusion'),
             ('B02_synthetic', 'pointer_comparison_ascii_art'), ('P00_perlin_noise', '001_perlin_noise')}
LIB_CASES = {'008_long_run_lib', '021_complex_goto_lib', '032_comma_operator_lib', 'arr_push_lib', 'hm_geti_lib', 'pow43_lib',
             '004_nineality_sieve_lib', '006_static_alias_lib', 'sh_geti_lib'}


def merged(src, kind, shards, keep):
    """Gộp bản ghi các shard cho các case cần: bản ghi khác harness_error được ưu tiên (luật L2 của main_merge_v2)."""
    dst = os.path.join(src, f'merged-{kind}'); shutil.rmtree(dst, ignore_errors=True); os.makedirs(f'{dst}/div')
    rows = {}
    for sh in shards:
        for line in open(f'{src}/{sh}/rq1-{kind}.jsonl'):
            r = json.loads(line)
            if not keep(r): continue
            k = (r['bundle'], r['case'], r['seed'])
            if k in rows and rows[k].get('status') != 'harness_error': continue
            rows[k] = r
        for f in os.listdir(f'{src}/{sh}/div'): shutil.copy(f'{src}/{sh}/div/{f}', f'{dst}/div/{f}')
    with open(f'{dst}/rq1-{kind}.jsonl', 'w') as h:
        for r in rows.values(): h.write(json.dumps(r) + '\n')
    return dst


def run(d, kind, keep):
    cases, divs, caps = HM.load_rq1(d, kind)
    cases = [r for r in cases if keep(r)]
    have = collections.defaultdict(set)
    for r in cases:
        if r.get('status') != 'harness_error': have[(r['bundle'], r['case'])].add(r['seed'])
    exp = [e for e in prep_pairs(kind) if (e['bundle'], e.get('tractor_case', e.get('case'))) in have]
    out = []
    for bc in sorted(have):
        sub_e = [e for e in exp if (e['bundle'], e.get('tractor_case', e.get('case'))) == bc]
        T = HM.rq1_translations([r for r in cases if (r['bundle'], r['case']) == bc], divs, caps, sorted(have[bc]), sub_e)
        for t in T.values():
            out.append(dict(bundle=bc[0], case=bc[1], system=t['system'], seeds=sorted(have[bc]), status=t['status'],
                            retained=bool(t['in_S'])))
    return out


def main():
    src = sys.argv[1]
    exe = run(merged(src, 'exe', ['rq1-main-exe-1of2'], lambda r: (r['bundle'], r['case']) in EXE_CASES), 'exe',
              lambda r: (r['bundle'], r['case']) in EXE_CASES)
    lib = run(merged(src, 'lib', ['rq1-main-lib-1of2', 'rq1-main-lib-2of2'], lambda r: r['case'] in LIB_CASES), 'lib',
              lambda r: r['case'] in LIB_CASES)
    for kind, rows in (('exe', exe), ('lib', lib)):
        l3 = json.load(open(f'experiments/30-main-s0/results/l3-{kind}.json'))['by_group']['all']
        main_s = json.load(open('experiments/30-main-s0/results/summary.json'))['metrics'][f'rq1_{kind}']['by_group']['all']
        n_missing_seed = l3['P_test'] - main_s['P_test']
        assert len(rows) == n_missing_seed, (kind, len(rows), n_missing_seed)
        assert all(r['status'] == 'P_test' for r in rows), kind
        n_ret = sum(r['retained'] for r in rows)
        assert n_ret == l3['D_all'] - main_s['D_all'], (kind, n_ret, l3['D_all'], main_s['D_all'])
        print(f'{kind}: {len(rows)} bản thiếu seed, {n_ret} có retained divergence (khớp L3: {l3["D_all"]} - {main_s["D_all"]})', file=sys.stderr)
        json.dump(dict(rule='exp 41 (Le duyệt 12/11): L_P \\ L_P* = acceptance thiếu seed có retained divergence trên seed hoàn tất',
                       translations=rows, retained_by_system=dict(collections.Counter(r['system'] for r in rows if r['retained']))),
                  open(f'{HERE}/results/lp-star-{kind}.json', 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
