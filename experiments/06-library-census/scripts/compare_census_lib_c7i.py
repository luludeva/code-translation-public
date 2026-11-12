#!/usr/bin/env python3
"""Đối chiếu census library gốc (EC2 m7i-flex.large, 2 worker; results/census-lib.jsonl, recheck-loss.jsonl) với census chạy lại
trên c7i.2xlarge (tuần tự, build mới; results/census-lib-c7i.jsonl, recheck-loss-c7i.jsonl; job census-lib-c7i, nguồn b8ce982).
Phễu tính bằng harness/pairs.p_rep (cùng quy tắc cho hai bản): census đỗ (mọi vector Pass/Skip, gồm đỗ với 0 vector) hoặc kiểm lại
đỗ 3/3 (alias .so, 120 giây). Phân loại tái lập như compare_census_ec2.py của exp 02.
Chạy: python3 experiments/06-library-census/scripts/compare_census_lib_c7i.py > experiments/06-library-census/results/census-lib-c7i-compare.txt"""
import collections as C, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, ROOT)
from harness.pairs import p_rep   # noqa: E402

R = os.path.join(HERE, '..', 'results')
POP = ['pilot', 'pub_passed', 'pub_error', 'stage', 'pub_vectors_failed', 'source_dir', 'harvest_case', 'no_input', 'rustc_bootstrap']


def load(f): return [json.loads(l) for l in open(os.path.join(R, f))]
def key(r): return r['bundle'], r['tractor_case'], r['system']


def cat(r):
    if r.get('stage') == 'P0_missing_artifact': return 'M'
    if not r.get('build_ok'): return 'build_fail'
    res = r.get('results')
    if res is None: return 'no_results'
    bad = set(res) - {'Pass', 'Skip'}
    if res and not bad: return 'pass'
    if bad == {'Timeout'}: return 'timeout_only'
    if bad: return 'fail:' + '+'.join(sorted(bad))
    return 'pass_0_vectors' if r.get('vectors') == 0 else 'no_results'


def main():
    old, new = load('census-lib.jsonl'), load('census-lib-c7i.jsonl')
    ro, rn = load('recheck-loss.jsonl'), load('recheck-loss-c7i.jsonl')
    O, N = {key(r): r for r in old}, {key(r): r for r in new}
    print(f'Cặp: gốc {len(O)}, c7i {len(N)}, cùng tập: {set(O) == set(N)}')
    common = set(O) & set(N)
    print('Trường population lệch:', {f: sum(O[k].get(f) != N[k].get(f) for k in common) for f in POP})
    co, cn = json.load(open(os.path.join(R, 'census-lib-c-side.json'))), json.load(open(os.path.join(R, 'census-lib-c-side-c7i.json')))
    diff_c = [k for k in co if (co[k] or {}).get('c_results') != (cn.get(k) or {}).get('c_results')]
    print('Phía C: case', len(co), len(cn), '| c_results khác:', diff_c[:10])
    main_k = [k for k in common if not O[k]['pilot'] and O[k].get('stage') != 'P0_missing_artifact']
    for side, acc in (('accepted', True), ('rejected', False)):
        ks = [k for k in main_k if O[k]['pub_passed'] is acc]
        print(f'\n== {side} (n={len(ks)})')
        print('  gốc:', dict(sorted(C.Counter(cat(O[k]) for k in ks).items())))
        print('  c7i:', dict(sorted(C.Counter(cat(N[k]) for k in ks).items())))
        for (a, b), n in sorted(C.Counter((cat(O[k]), cat(N[k])) for k in ks).items()):
            if a != b: print(f'  đổi {a} -> {b}: {n}')
        for k in ks:
            if cat(O[k]) != cat(N[k]): print('    ', k, O[k].get('results'), '->', N[k].get('results'))
        same = [k for k in ks if cat(O[k]) == cat(N[k]) and O[k].get('results') != N[k].get('results')]
        print('  cùng nhóm nhưng khác kết quả cấp vector:', len(same), same[:10])
    po, pn = p_rep(old, ro), p_rep(new, rn)
    ko, kn = {key(r) for r in po}, {key(r) for r in pn}
    for name, P, rc in (('gốc', po, ro), ('c7i', pn, rn)):
        ni = sum(r['no_input'] for r in P)
        print(f'\n== P_rep {name}: {len(P)} ({len(P) - ni} không tính {ni} cặp không input); qua kiểm lại {sum(r["via"] == "recheck" for r in P)}; '
              f'kiểm lại {len(rc)} cặp: {dict(C.Counter((r.get("ours_passed"), r.get("stable"), bool(r.get("so_alias"))) for r in rc))}')
    print('Chỉ có trong P_rep gốc:', sorted(ko - kn)); print('Chỉ có trong P_rep c7i:', sorted(kn - ko))
    acc = [k for k in main_k if O[k]['pub_passed'] and not O[k].get('no_input')]
    loss = [k for k in acc if k not in kn]
    print(f'\n== Hao hụt accepted (không tính library không input) trên c7i: {len(loss)}')
    for k in sorted(loss):
        r = {x[0:3] == k and x for x in []} if False else None
        rr = next((x for x in rn if key(x) == k), None)
        print('   ', k, cat(N[k]), N[k].get('results'), '| kiểm lại:', None if rr is None else (rr.get('ours_passed'), rr.get('stable'), rr.get('so_alias'),
              [x.get('results') for x in rr.get('reps', [])][:1]))


if __name__ == '__main__':
    main()
