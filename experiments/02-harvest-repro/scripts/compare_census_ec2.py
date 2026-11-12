#!/usr/bin/env python3
"""Đối chiếu census executable cũ (Cowork cloud, results/census-exe.jsonl) với census chạy lại trên EC2
(results/census-exe-ec2.jsonl, job census-exe-ec2, nguồn 559157f) và áp luật 3/3 đăng ký trước
(docs/proposal/prereg-2026-10-20-retry-rule.md) lên results/recheck-timeout-ec2.jsonl.

Quy ước tái lập đỗ: mọi vector Pass hoặc Skip (Skip = vector đánh dấu UB), như census.py dòng 79 và phễu cũ
(census-notes.md, P_rep 494). Trường `ours_passed` của census-exe.jsonl cũ ghi false cho 83 cặp chỉ có Pass và Skip;
script tính lại từ `results` thay vì đọc trường đó. Cặp chạy 0 vector (`008_long_run`) tách thành nhóm riêng
`pass_0_vectors`, không gộp vào `pass`.
Chạy: python3 experiments/02-harvest-repro/scripts/compare_census_ec2.py > experiments/02-harvest-repro/results/census-ec2-compare.txt"""
import collections as C, json, os

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results')
POP = ['pilot', 'pub_passed', 'stage', 'pub_vectors_failed', 'pub_placeholder', 'source_dir', 'harvest_case', 'rustc_bootstrap']


def load(f):
    return [json.loads(l) for l in open(os.path.join(R, f))]


def key(r):
    return r['bundle'], r['tractor_case'], r['system']


def cat(r):
    if r.get('stage') == 'P0_missing_artifact': return 'M'
    if not r.get('build_ok'): return 'build_fail'
    res = r.get('results') or {}
    bad = set(res) - {'Pass', 'Skip'}
    if res and not bad: return 'pass'
    if bad == {'Timeout'}: return 'timeout_only'
    if bad: return 'fail:' + '+'.join(sorted(bad))
    return 'pass_0_vectors' if r.get('run_ok') and r.get('vectors') == 0 else 'no_results'


def main():
    old, new = load('census-exe.jsonl'), load('census-exe-ec2.jsonl')
    O, N = {key(r): r for r in old}, {key(r): r for r in new}
    print(f'Cặp: cũ {len(O)}, EC2 {len(N)}, cùng tập: {set(O) == set(N)}')
    print('Trường population lệch (cũ so với EC2):', {f: sum(O[k].get(f) != N[k].get(f) for k in O) for f in POP})
    print('Cặp có ours_passed cũ khác kết quả tính lại từ results:',
          sum((cat(r) == 'pass') != bool(r.get('ours_passed')) for r in old if r.get('build_ok')))
    co, cn = json.load(open(os.path.join(R, 'census-c-side.json'))), json.load(open(os.path.join(R, 'census-c-side-ec2.json')))
    print('Phía C: case', len(co), len(cn), '| tally khác nhau:', [k for k in co if co[k].get('tally') != cn.get(k, {}).get('tally')])
    main_keys = [k for k in O if not O[k]['pilot'] and O[k].get('stage') != 'P0_missing_artifact']
    for side, acc in (('accepted', True), ('rejected', False)):
        ks = [k for k in main_keys if O[k]['pub_passed'] is acc]
        print(f'\n== {side} (n={len(ks)})')
        print('  cũ :', dict(sorted(C.Counter(cat(O[k]) for k in ks).items())))
        print('  EC2:', dict(sorted(C.Counter(cat(N[k]) for k in ks).items())))
        for (a, b), n in sorted(C.Counter((cat(O[k]), cat(N[k])) for k in ks).items()):
            if a != b: print(f'  đổi {a} -> {b}: {n}')
        same = [k for k in ks if cat(O[k]) == cat(N[k]) and O[k].get('results') != N[k].get('results')]
        print('  cùng nhóm nhưng khác kết quả cấp vector:', len(same))
    rc = {key(r): r for r in load('recheck-timeout-ec2.jsonl')}
    acc_to = [k for k in main_keys if O[k]['pub_passed'] and cat(N[k]) == 'timeout_only']
    print(f'\n== Luật 3/3 trên EC2: {len(acc_to)} cặp accepted chỉ trượt vì Timeout, {len(rc)} dòng chạy lại')
    assert set(acc_to) == set(rc), 'tập chạy lại lệch tập timeout'
    out = C.Counter()
    for k in acc_to:
        r = rc[k]
        out['3/3 pass' if r['ours_passed'] else ('3/3 trượt cùng tập vector' if r['stable'] else 'lẫn')] += 1
        if not r['ours_passed']: print('  không vào P_rep:', k, r['reps'][0].get('results'), 'stable', r['stable'])
    print(' ', dict(out))
    acc = [k for k in main_keys if O[k]['pub_passed']]
    ec = C.Counter(cat(N[k]) for k in acc)
    p_rep = ec['pass'] + out['3/3 pass']
    print(f'\n== Phễu accepted executable trên EC2: P_acc {len(acc)} -> P_rep {p_rep} có vector; '
          f"thêm {ec['pass_0_vectors']} cặp đỗ với 0 vector (008_long_run, vector duy nhất đổi tên .bak) chưa có quyết định "
          f"phía executable; nếu áp luật library 2026-10-14 thì P_rep {p_rep + ec['pass_0_vectors']}")
    print(f"  hao hụt: không build (không có bin target) {ec['build_fail']}, timeout {out['3/3 trượt cùng tập vector']}, "
          f"không ổn định {out['lẫn']}, output khác {sum(v for c, v in ec.items() if c.startswith('fail:'))}")
    for k in acc:
        if cat(N[k]).startswith('fail:'): print('   ', k, N[k]['results'])
    rej = [k for k in main_keys if not O[k]['pub_passed']]
    print(f"\n== Rejected executable trên EC2: {len(rej)}; tái lập ra đỗ: {sum(cat(N[k]) == 'pass' for k in rej)}")


if __name__ == '__main__':
    main()
