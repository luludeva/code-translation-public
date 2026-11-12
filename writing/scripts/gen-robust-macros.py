#!/usr/bin/env python3
"""Sinh writing/generated/robust-numbers.tex: số của các phân tích post-freeze trên S₀ (L3 exp 30; R9/R18 exp 31; B1, N1, R9 gộp, B3
exp 32; kiểm mẫu RQ2 exp 34). Cùng quy ước với gen-rq-macros.py: \\rqSet{<tên>}{<giá trị>}, đại lượng tỉ lệ có Num, Den, Pct (một chữ số thập phân), cận
Wilson 95% có Lo, Hi (phần trăm). Thiếu nguồn thì ??. Mọi số ở đây là phân tích phụ, báo cạnh kết quả chính; Le gỡ nhãn sơ bộ ngày 2026-11-12. Không sửa tay file sinh ra.
Dùng: python3 writing/scripts/gen-robust-macros.py [--out writing/generated/robust-numbers.tex]"""
import argparse, json, os, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = f'{ROOT}/writing/generated/robust-numbers.tex'
E30, E31, E32 = (f'{ROOT}/experiments/{d}/results' for d in ('30-main-s0', '31-r9-check', '32-robustness-s0'))
KT = dict(exe='Exe', lib='Lib')


def load(p):
    try: return json.load(open(p))
    except (OSError, ValueError): return None


def pct(n, d): return '??' if n is None or d is None else ('n/a' if d == 0 else f'{100 * n / d:.1f}')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=OUT); a = ap.parse_args()
    M = []

    def put(name, v): M.append((name, '??' if v is None else v))

    def rate(name, n, d): put(f'{name}Num', n); put(f'{name}Den', d); put(f'{name}Pct', pct(n, d))

    def wil(name, w):
        put(f'{name}Lo', None if not w else f'{100 * max(0, w[0]):.1f}'); put(f'{name}Hi', None if not w else f'{100 * w[1]:.1f}')

    srcs = []
    for k in ('exe', 'lib'):
        K = KT[k]
        l3 = load(f'{E30}/l3-{k}.json'); srcs.append(f'{E30}/l3-{k}.json')
        g = (l3 or {}).get('by_group', {}).get('all', {})
        rate(f'rqLThree{K}All', g.get('D_all'), g.get('P_test'))
        rate(f'rqLThreeNBLo{K}All', g.get('NB_L'), g.get('P_test')); rate(f'rqLThreeNBHi{K}All', g.get('NB_U'), g.get('P_test'))
        b1 = (load(f'{E32}/b1/b1-summary.json') or {}).get(k)
        rate(f'rqBOne{K}All', None if not b1 else b1['D_B1'], None if not b1 else b1['P_test'])
        put(f'rqBOneLeave{K}AllNum', None if not b1 else b1['n_leave']); put(f'rqBOneUnchecked{K}AllNum', None if not b1 else b1['n_unchecked'])
        rate(f'rqBOneInputs{K}All', None if not b1 else b1['n_inputs_c_unstable'], None if not b1 else b1['n_inputs'])
        b3 = (load(f'{E32}/b3/summary.json') or {}).get(k)
        for lab, tok in (('yes', 'Yes'), ('no', 'No'), ('unclear', 'Unclear')):
            put(f'rqBThreeD{tok}{K}AllNum', None if not b3 else b3['by_label'].get(lab, 0))
            put(f'rqBThreeCases{tok}{K}AllNum', None if not b3 else b3['cases_by_label'].get(lab, 0))
        rate(f'rqBThreeNotUb{K}All', None if not b3 else b3['by_label'].get('no', 0), None if not l3 else (load(f'{E30}/metrics.json') or {}).get(f'rq1_{k}', {}).get('by_group', {}).get('all', {}).get('P_test'))
        r9 = (load(f'{E32}/r9-pooled.json') or {}).get(k)
        put(f'rqRNine{K}N', None if not r9 else r9['n']); put(f'rqRNine{K}Unclear', None if not r9 else r9['n_unclear'])
        rate(f'rqRNineFalse{K}', None if not r9 else r9['false_div']['k'], None if not r9 else r9['n_det'])
        wil(f'rqRNineFalse{K}', None if not r9 else r9['false_div']['wilson95'])
        rate(f'rqRNineBnu{K}', None if not r9 else r9['bnu_wrong']['k'], None if not r9 else r9['n_det'])
        wil(f'rqRNineBnu{K}', None if not r9 else r9['bnu_wrong']['wilson95'])
        # Cận xấu nhất: mọi mục unclear coi là divergence giả, mẫu số là cả mẫu (Le chọn 3/11)
        rate(f'rqRNineWorst{K}', None if not r9 else r9['false_div']['k'] + r9['n_unclear'], None if not r9 else r9['n'])
        r18 = (load(f'{E31}/r9-final.json') or {}).get(f'R18-{k}')
        put(f'rqREighteen{K}N', None if not r18 else r18['n']); put(f'rqREighteenFalse{K}Num', None if not r18 else r18['false_div']['k'])
    for k in ('exe', 'lib'):
        K = KT[k]; q = (load(f'{ROOT}/experiments/34-rq2-check/results/rq2-check-final.json') or {}).get(k)
        put(f'rqRTwoCheck{K}N', None if not q else q['n']); put(f'rqRTwoCheck{K}Unclear', None if not q else len(q['unclear']))
        rate(f'rqRTwoCheckWrong{K}', None if not q else q['wrong']['k'], None if not q else q['n_det'])
        wil(f'rqRTwoCheckWrong{K}', None if not q else q['wrong']['wilson95'])
    n1 = (load(f'{E32}/n1-r9ext.json') or {}).get('N1')
    put('rqNOneLibAllOnlyNum', None if not n1 else n1['translations_only_both_fail'])
    rate('rqNOneLibAll', None if not n1 else n1['D_without'], None if not n1 else n1['P_test'])
    cp = load(f'{E30}/ctype-posthoc.json')   # RQ1 post-hoc bỏ case 027_ctype_ascii (decision-log 2026-10-29)
    for k in ('exe', 'lib'):
        K = KT[k]; x = (cp or {}).get(k) or {}; g = (x.get('groups') or {}).get('all', {}).get('without_case'); cpart = x.get('case_part')
        rate(f'rqCtypeOut{K}All', None if not g else g['D_all'], None if not g else g['P_test'])
        rate(f'rqCtypeOutNBLo{K}All', None if not g else g['NB_L'], None if not g else g['P_test'])
        rate(f'rqCtypeOutNBHi{K}All', None if not g else g['NB_U'], None if not g else g['P_test'])
        put(f'rqCtypeCaseD{K}Num', None if not cpart else cpart['D_all']); put(f'rqCtypeCasePtest{K}Num', None if not cpart else cpart['P_test'])
    rev = subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    with open(a.out, 'w') as f:
        f.write('% SINH TU DONG boi writing/scripts/gen-robust-macros.py. KHONG SUA TAY.\n')
        f.write(f'% Repo commit: {rev}. Phan tich post-freeze tren S0 (exp 30 L3, exp 30 ctype post-hoc, exp 31, exp 32, exp 34). L3, B1, N1: kiem tren mau (R9, RQ2); B3: nhan dien giai, Le chap nhan khong kiem tay 2026-11-12.\n')
        f.write('\\providecommand{\\rqSet}[2]{\\expandafter\\def\\csname #1\\endcsname{#2}}\n')
        for n, v in M: f.write(f'\\rqSet{{{n}}}{{{v}}}\n')
    print(f'Đã ghi {a.out}: {len(M)} macro, {sum(v == "??" for _, v in M)} ??')


if __name__ == '__main__':
    main()
