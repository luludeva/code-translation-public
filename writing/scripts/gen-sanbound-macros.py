#!/usr/bin/env python3
"""Sinh writing/generated/sanbound-numbers.tex: số của exp 38 (cận tất định cho các bản RQ2 executable not_re_examined vì bản C-san không
build được; post hoc, Le chấp nhận không kiểm tay ngày 2026-11-12). Cùng quy ước với gen-robust-macros.py: \\rqSet{<tên>}{<giá trị>}, số đếm có hậu tố Num,
tỉ lệ có Num, Den, Pct (một chữ số thập phân). Thiếu nguồn thì ??. Không sửa tay file sinh ra. Phân tích phụ, không thay số chính
(rq-numbers.tex). k theo amendment 2026-11-05 §9: số bản trong tập không kết thúc là behavioral_disagreement (not_adjudicable hoặc vẫn
not_re_examined). Lượt C-san bổ sung (exp 37) dùng họ macro riêng (\\rqSanSupp*, sansupp-numbers.tex), không sinh ở đây.
Dùng: python3 writing/scripts/gen-sanbound-macros.py [--in experiments/38-rq2-san-bound/results/bound-exe.json]
      [--out writing/generated/sanbound-numbers.tex]"""
import argparse, json, os, re, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
IN = f'{ROOT}/experiments/38-rq2-san-bound/results/bound-exe.json'
OUT = f'{ROOT}/writing/generated/sanbound-numbers.tex'
SYS_TOK = {'codex-gpt54': 'Codex', '_all': ''}
SCEN_TOK = dict(no_report='NoReport', ub='Ub', inconclusive='Inconcl')
OUT_TOK = dict(behavioral_disagreement='Disagree', behavioral_agreement='Agree', not_adjudicable='NotAdj', not_re_examined='NotReex')



def pct(n, d): return '??' if n is None or d is None else ('n/a' if d == 0 else f'{100 * n / d:.1f}')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--in', dest='src', default=IN); ap.add_argument('--out', default=OUT); a = ap.parse_args()
    try:
        with open(a.src) as f: d = json.load(f)
    except (OSError, ValueError): d = None
    M = []

    def put(name, v): M.append((name, '??' if v is None else v))

    def rate(name, n, dd): put(f'{name}Num', n); put(f'{name}Den', dd); put(f'{name}Pct', pct(n, dd))

    g = (lambda *p: _dig(d, p))
    n = g('targets', 'n')
    put('rqSanBoundExeNNum', n)
    rate('rqSanBoundReproVecExe', None if d is None else g('validation', 'vectors_recomputed') - g('validation', 'vector_mismatches'),
         g('validation', 'vectors_recomputed'))
    rate('rqSanBoundReproTransExe', None if d is None else g('validation', 'translations_recomputed') - g('validation', 'translation_mismatches'),
         g('validation', 'translations_recomputed'))
    for s, st in SCEN_TOK.items():
        for o, ot in OUT_TOK.items():
            rate(f'rqSanBound{st}{ot}Exe', None if d is None else (g('scenarios', s, 'translation_outcomes') or {}).get(o, 0), n)
    put('rqSanBoundFMaxExeNum', None if d is None else max(g('F_per_scenario', s) for s in SCEN_TOK))
    # A nhỏ nhất, lớn nhất trên R_run executable qua ba kịch bản: chỉ số đếm. Ch3 không định nghĩa tỉ lệ A/|R_run| (r_FF dùng R_test),
    # nên không sinh Den, Pct.
    put('rqSanBoundALoExeNum', g('A_range_R_run', 'min')); put('rqSanBoundAHiExeNum', g('A_range_R_run', 'max'))
    nv = g('evidence', 'n_vectors')
    rate('rqSanBoundCExpectedExe', g('evidence', 'c_stdout_equals_expected'), nv)
    rate('rqSanBoundRGotExe', g('evidence', 'rust_stdout_equals_published_got'), nv)
    put('rqSanBoundRepsExeNum', g('evidence', 'n_reps'))
    for sy, tk in SYS_TOK.items():
        t = g('rq3', 'tables', sy)
        rows = (t or {}).get('rows') or []
        k0 = rows[0] if rows else {}
        rate(f'rqSanBoundSRHiKZeroExeAll{tk}', k0.get('upper_num'), k0.get('den'))
        put(f'rqSanBoundKBelowExeAll{tk}Num', None if t is None else ('n/a' if t['k_max_upper_below_sr'] is None else t['k_max_upper_below_sr']))
        put(f'rqSanBoundKMaxExeAll{tk}Num', None if t is None else t['n_targets'])
    bad = [x for x, _ in M if not re.fullmatch(r'[A-Za-z]+', x)]
    if bad: raise SystemExit(f'tên macro không hợp lệ: {bad}')
    rev = subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() or '?'
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w') as f:
        f.write('% SINH TU DONG boi writing/scripts/gen-sanbound-macros.py. KHONG SUA TAY.\n')
        f.write(f'% Repo commit: {rev}. Nguon: experiments/38-rq2-san-bound/results/bound-exe.json. Phan tich post hoc, Le chap nhan khong kiem tay 2026-11-12; '
                'khong thay so chinh (rq-numbers.tex).\n')
        f.write('\\providecommand{\\rqSet}[2]{\\expandafter\\def\\csname #1\\endcsname{#2}}\n')
        for x, v in M: f.write(f'\\rqSet{{{x}}}{{{v}}}\n')
    print(f'Đã ghi {a.out}: {len(M)} macro, {sum(v == "??" for _, v in M)} ??')


def _dig(d, path):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur: return None
        cur = cur[p]
    return cur


if __name__ == '__main__':
    main()
