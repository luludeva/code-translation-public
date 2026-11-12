#!/usr/bin/env python3
"""Sinh writing/generated/ax-numbers.tex và writing/generated/tab-ax2-dist.tex: AX-1, AX-2 đúng định nghĩa của
docs/amendment-2026-11-05-supplementary-analyses.md mục 3 và điều kiện báo cáo mục 5 (post-freeze, post hoc; văn đánh dấu †; sơ bộ, chưa
kiểm tay). Thay gen-dconc-macros.py (định nghĩa AX-2 tự đặt ngày 10/11, không theo amendment). Quy ước \\rqSet như gen-robust-macros.py;
thiếu nguồn hoặc kiểm chéo hỏng thì ??.

Nguồn (file đã commit):
  - experiments/40-review-counts/results/ax1-channels.json (AX-1): rqAxOneTrans<Kênh><K>{Num,Den,Pct} với kênh Status, Stdout, StderrOnly
    và State (chỉ library; amendment không liệt kê, báo riêng); rqAxOneDiv<Kênh><K>{Num,Den} (mức divergence, phụ).
  - experiments/40-review-counts/results/ptest-cases.json và experiments/32-robustness-s0/results/D-<kind>.jsonl (AX-2):
      AX-2a rqAxTwoCases<K>{Num,Den,Pct}: case có ít nhất một bản D trên case có ít nhất một bản P_test;
      AX-2b rqAxTwoTopFive<K>{Num,Den,Pct}: số bản D trong 5 case có nhiều nhất, chia |D|; bảng tab-ax2-dist.tex: số case theo số bản D;
      dòng F của AX-2b rqAxTwoFCases<K>{Num,Den,Pct}: case có ít nhất một bản F trên case có ít nhất một bản R_test;
      điều kiện mục 5 rqAxTwoCondCases<K>Num: số case có ít nhất 2 bản P_test (ngưỡng 20); chưa đạt thì mọi số AX-2 của loại đó là ??.
  Kiểm: |D| bằng rqFP<K>AllNum, |P_test| bằng rqPtest<K>AllNum, |R_test| bằng rqFF<K>AllDen, F bằng rqFF<K>AllNum (rq-numbers.tex).
Dùng: python3 writing/scripts/gen-ax-macros.py [--out writing/generated/ax-numbers.tex] [--tab writing/generated/tab-ax2-dist.tex]"""
import argparse, collections, json, os, re, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = f'{ROOT}/writing/generated/ax-numbers.tex'
TAB = f'{ROOT}/writing/generated/tab-ax2-dist.tex'
E40 = f'{ROOT}/experiments/40-review-counts/results'
DFILE = f'{ROOT}/experiments/32-robustness-s0/results/D-{{}}.jsonl'
RQ = f'{ROOT}/writing/generated/rq-numbers.tex'
KIND = dict(exe='Exe', lib='Lib')
CH = (('status', 'Status'), ('stdout', 'Stdout'), ('stderr_only', 'StderrOnly'), ('state', 'State'))
TOP, COND = 5, 20


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
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=OUT); ap.add_argument('--tab', default=TAB); a = ap.parse_args()
    M = []

    def put(name, v): M.append((name, '??' if v is None else v))

    def rate(name, n, d): put(f'{name}Num', n); put(f'{name}Den', d); put(f'{name}Pct', pct(n, d))

    ax1, pc = load(f'{E40}/ax1-channels.json') or {}, load(f'{E40}/ptest-cases.json') or {}
    dist = {}
    for kd, tok in KIND.items():
        o = ax1.get(kd) or {}
        ok1 = bool(o) and o.get('D') == rq_value(f'rqFP{tok}AllNum') and o.get('retained_div') == rq_value(f'rqBnuDivNOneStatus{tok}AllDen')
        for c, ct in CH:
            if kd == 'exe' and c == 'state': continue
            rate(f'rqAxOneTrans{ct}{tok}', (o.get('translations') or {}).get(c, 0) if ok1 else None, o.get('D') if ok1 else None)
            put(f'rqAxOneDiv{ct}{tok}Num', (o.get('divergences') or {}).get(c, 0) if ok1 else None)
            put(f'rqAxOneDiv{ct}{tok}Den', o.get('retained_div') if ok1 else None)
        p = pc.get(kd) or {}
        try: D = [tuple(json.loads(l)) for l in open(DFILE.format(kd)) if l.strip()]
        except (OSError, ValueError): D = None
        ok2 = (bool(p) and D is not None and len(D) == rq_value(f'rqFP{tok}AllNum') and p.get('P_test') == rq_value(f'rqPtest{tok}AllNum')
               and p.get('R_test') == rq_value(f'rqFF{tok}AllDen') and p.get('F') == rq_value(f'rqFF{tok}AllNum'))
        cond = sum(1 for v in (p.get('by_case') or {}).values() if len(v) >= 2) if ok2 else None
        put(f'rqAxTwoCondCases{tok}Num', cond)
        ok2 = ok2 and cond >= COND
        per = collections.Counter(f'{b}/{c}' for b, c, _ in D) if ok2 else collections.Counter()
        rate(f'rqAxTwoCases{tok}', len(per) if ok2 else None, p.get('cases') if ok2 else None)
        rate(f'rqAxTwoTopFive{tok}', sum(v for _, v in per.most_common(TOP)) if ok2 else None, len(D) if ok2 else None)
        rate(f'rqAxTwoFCases{tok}', p.get('F_cases') if ok2 else None, p.get('R_test_cases') if ok2 else None)
        dist[kd] = collections.Counter(per.values()) if ok2 else None
        if ok2: dist[kd][0] = p['cases'] - len(per)
    bad = [x for x, _ in M if not re.fullmatch(r'[A-Za-z]+', x)]
    if bad: raise SystemExit(f'tên macro không hợp lệ: {bad}')
    rev = subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() or '?'
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w') as f:
        f.write('% SINH TU DONG boi writing/scripts/gen-ax-macros.py. KHONG SUA TAY.\n')
        f.write(f'% Repo commit: {rev}. Nguon: experiments/40-review-counts/results/{{ax1-channels,ptest-cases}}.json, '
                'experiments/32-robustness-s0/results/D-{exe,lib}.jsonl. AX-1, AX-2 theo amendment 2026-11-05; post hoc, Le chap nhan khong kiem tay 2026-11-12.\n')
        f.write('\\providecommand{\\rqSet}[2]{\\expandafter\\def\\csname #1\\endcsname{#2}}\n')
        for x, v in M: f.write(f'\\rqSet{{{x}}}{{{v}}}\n')
    ns = sorted(set().union(*[set(v) for v in dist.values() if v])) if any(dist.values()) else []
    with open(a.tab, 'w') as f:
        f.write('% SINH TU DONG boi writing/scripts/gen-ax-macros.py. KHONG SUA TAY. AX-2b: so case co ung so ban dich D, tren case co ban '
                'P_test; post hoc, Le chap nhan khong kiem tay 2026-11-12.\n')
        f.write('\\begin{tabular}{@{}r rr@{}}\n\\toprule\nTranslations in $D$ per case & Executable programs & Libraries \\\\\n\\midrule\n')
        for n in ns: f.write(f'{n} & ' + ' & '.join(str(dist[k].get(n, 0)) if dist[k] is not None else '??' for k in KIND) + ' \\\\\n')
        if not ns: f.write('?? & ?? & ?? \\\\\n')
        f.write('\\bottomrule\n\\end{tabular}\n')
    print(f'Đã ghi {a.out}: {len(M)} macro, {sum(v == "??" for _, v in M)} ??; {a.tab}: {len(ns)} dòng')


if __name__ == '__main__':
    main()
