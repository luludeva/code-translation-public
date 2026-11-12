#!/usr/bin/env python3
"""Sinh writing/generated/review-numbers.tex: số đếm theo review GPT lượt 1 và các kiểm chạy bù (brief kỹ thuật 2026-11-10). Mọi số post hoc
(văn đánh dấu †), Le chấp nhận không kiểm tay ngày 2026-11-12; không đổi số chính. Quy ước \\rqSet như gen-robust-macros.py; thiếu nguồn hoặc kiểm chéo hỏng thì ??.

Nguồn (file đã commit):
  - experiments/40-review-counts/results/counts.json:
      MR-01 rqAgreeCUnstableVec<K>{Num,Den,Pct} (vector agrees có C không ổn định, theo cờ c_stable; kiểm chéo quan sát C qua các lần chạy
      phải khớp cờ, không thì ??), rqAgreeCUnstableFTrans<K>{Num,Den};
      MR-04 rqResOnlyDiv<K>{Num,Den,Pct} (divergence giữ lại của D chỉ do trần bộ nhớ một phía hoặc SIGXFSZ), rqResMemOneSideDiv<K>Num,
      rqResXfszDiv<K>Num, rqResOnlyTrans<K>{Num,Den,Pct} (bản dịch D mà mọi divergence giữ lại như vậy), rqResAnyTrans<K>Num.
      Kiểm chéo: Den của MR-04 bằng mẫu số rqBnuDivNOneStatus<K>AllDen (số divergence giữ lại của S₀) và |D| bằng rqFP<K>AllNum.
  - experiments/39-prereg-backfill/results/v3c-{exe,lib}.json: rqVThreeC<K>{Units,Retained,Viol}Num, rqVThreeCLibNoDivFileNum.
Dùng: python3 writing/scripts/gen-review-macros.py [--out writing/generated/review-numbers.tex]"""
import argparse, json, os, re, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = f'{ROOT}/writing/generated/review-numbers.tex'
CNT = f'{ROOT}/experiments/40-review-counts/results/counts.json'
V3C = f'{ROOT}/experiments/39-prereg-backfill/results/v3c-{{}}.json'
RQ = f'{ROOT}/writing/generated/rq-numbers.tex'
KIND = dict(exe='Exe', lib='Lib')


def load(p):
    try:
        with open(p) as f: return json.load(f)
    except (OSError, ValueError): return None


def rq_value(name):
    try: m = re.search(r'\\rqSet\{' + name + r'\}\{([^}]*)\}', open(RQ).read())
    except OSError: return None
    return int(m.group(1)) if m and m.group(1).isdigit() else None


def pct(n, d): return '??' if n is None or d is None else ('n/a' if d == 0 else f'{100 * n / d:.1f}')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=OUT); a = ap.parse_args()
    M = []

    def put(name, v): M.append((name, '??' if v is None else v))

    def rate(name, n, d): put(f'{name}Num', n); put(f'{name}Den', d); put(f'{name}Pct', pct(n, d))

    c = load(CNT) or {}
    for kd, tok in KIND.items():
        m1 = (c.get('mr01') or {}).get(kd) or {}
        ok1 = bool(m1) and m1.get('flag_crosscheck_mismatch') == 0
        rate(f'rqAgreeCUnstableVec{tok}', m1.get('c_unstable_flag') if ok1 else None, m1.get('agrees_vectors') if ok1 else None)
        put(f'rqAgreeCUnstableFTrans{tok}Num', m1.get('F_affected') if ok1 else None)
        put(f'rqAgreeCUnstableFTrans{tok}Den', m1.get('F_translations') if ok1 else None)
        m4 = (c.get('mr04') or {}).get(kd) or {}
        ok4 = (bool(m4) and not m4.get('D_without_retained') and m4.get('retained_div') == rq_value(f'rqBnuDivNOneStatus{tok}AllDen')
               and m4.get('D') == rq_value(f'rqFP{tok}AllNum'))
        g = (lambda k: m4.get(k) if ok4 else None)
        rate(f'rqResOnlyDiv{tok}', g('resource_div'), g('retained_div'))
        put(f'rqResMemOneSideDiv{tok}Num', g('mem_one_side_div')); put(f'rqResXfszDiv{tok}Num', g('sigxfsz_div'))
        rate(f'rqResOnlyTrans{tok}', g('translations_resource_only'), g('D'))
        put(f'rqResAnyTrans{tok}Num', g('translations_any_resource'))
        v = load(V3C.format(kd)) or {}
        t = v.get('totals') or {}
        put(f'rqVThreeC{tok}UnitsNum', v.get('units_case_seed')); put(f'rqVThreeC{tok}RetainedNum', t.get('retained') if v else None)
        put(f'rqVThreeC{tok}ViolNum', v.get('violations'))
        if kd == 'lib': put('rqVThreeCLibNoDivFileNum', t.get('no_div_file', 0) if v else None)
    bad = [x for x, _ in M if not re.fullmatch(r'[A-Za-z]+', x)]
    if bad: raise SystemExit(f'tên macro không hợp lệ: {bad}')
    rev = subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() or '?'
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w') as f:
        f.write('% SINH TU DONG boi writing/scripts/gen-review-macros.py. KHONG SUA TAY.\n')
        f.write(f'% Repo commit: {rev}. Nguon: experiments/40-review-counts/results/counts.json, experiments/39-prereg-backfill/results/'
                'v3c-{exe,lib}.json. Post hoc, Le chap nhan khong kiem tay 2026-11-12; khong thay so chinh.\n')
        f.write('\\providecommand{\\rqSet}[2]{\\expandafter\\def\\csname #1\\endcsname{#2}}\n')
        for x, val in M: f.write(f'\\rqSet{{{x}}}{{{val}}}\n')
    print(f'Đã ghi {a.out}: {len(M)} macro, {sum(val == "??" for _, val in M)} ??')


if __name__ == '__main__':
    main()
