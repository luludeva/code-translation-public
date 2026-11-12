#!/usr/bin/env python3
"""Sinh writing/generated/tab-m-population.tex: Bảng 3.1 (tab:m-population), kích thước P0, P_acc, R0 tách theo giai đoạn
ghi trong trường `error` của result.json (build failed / test failed), và M, theo hệ, executable và library.
Chỉ dùng quyết định công bố, không dùng kết quả tái lập (định nghĩa: decision-log 2026-10-20 "Phễu §3.2").
Nguồn:
  - executable: experiments/02-harvest-repro/data/pub-decision-exe.tsv (sinh bằng scripts/extract_pub_error.py)
    và results/census-exe-ec2.jsonl (cờ pilot);
  - library: experiments/06-library-census/results/census-lib.jsonl (trường pub_passed, pub_error).
Kiểm partition P0 = P_acc ⊔ R0 ⊔ M và R0 = R0_build ⊔ R0_test cho từng hệ; script dừng nếu lệch.
Kiểm thêm tổng P_acc cộng pilot khớp số đỗ công bố trên 338 chương trình (card harvest-agentic-translate-results §3)."""
import collections as C, csv, json, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
EXE_DEC = f'{ROOT}/experiments/02-harvest-repro/data/pub-decision-exe.tsv'
EXE = f'{ROOT}/experiments/02-harvest-repro/results/census-exe-ec2.jsonl'
LIB = f'{ROOT}/experiments/06-library-census/results/census-lib.jsonl'
OUT = f'{ROOT}/writing/generated/tab-m-population.tex'
# Thứ tự và tên hiển thị theo §3.2 đoạn 1; nhóm rule-based / LLM-assisted theo Schesch & Ernst tr. 2
# (docs/literature/cards/04-integrate-after/schesch2026-agentic-c-to-rust.md dòng 24)
GROUPS = [('Agentic (ACTOR)', [('kiro', 'Kiro'), ('claude', 'Claude Code'), ('codex-gpt54', 'Codex (GPT-5.4)')]),
          ('Rule-based', [('c2rust', 'C2Rust'), ('laertes', 'Laertes')]),
          ('LLM-assisted', [('c2saferrust', 'C2SaferRust'), ('smartc2rust', 'SmartC2Rust')]),
          ('One-shot LLM', [('kimi', 'Kimi K2.5'), ('gpt-5.4', 'GPT-5.4'), ('gemini-3.1-pro-preview', 'Gemini 3.1 Pro')])]
PUBLISHED_PASS_338 = {'kiro': 325, 'claude': 319, 'codex-gpt54': 244, 'c2rust': 204, 'laertes': 201, 'c2saferrust': 154,
                      'smartc2rust': 40, 'gpt-5.4': 154, 'kimi': 118, 'gemini-3.1-pro-preview': 156}
COLS = ['P0', 'acc', 'build', 'test', 'M']


def tally():
    t = C.defaultdict(C.Counter); pilot_acc = C.Counter()
    pil = {(r['bundle'], r['tractor_case'], r['system']): r['pilot'] for r in map(json.loads, open(EXE))}
    exe = [(r['system'], pil[(r['bundle'], r['tractor_case'], r['system'])], r['source_dir'] == 'missing',
            r['passed'] == 'true', r['error']) for r in csv.DictReader(open(EXE_DEC), delimiter='\t')]
    lib = [(r['system'], r['pilot'], r.get('stage') == 'P0_missing_artifact', r.get('pub_passed') is True, r.get('pub_error'))
           for r in map(json.loads, open(LIB))]
    for kind, rows in (('exe', exe), ('lib', lib)):
        for s, pilot, missing, passed, err in rows:
            if pilot:
                pilot_acc[s] += passed and not missing; continue
            c = t[(kind, s)]; c['P0'] += 1
            if missing: c['M'] += 1
            elif passed: c['acc'] += 1
            elif err == 'build failed': c['build'] += 1
            elif err == 'test failed': c['test'] += 1
            else: raise SystemExit(f'error không nhận diện: {kind} {s} {err!r}')
    for (kind, s), c in t.items():
        assert c['P0'] == c['acc'] + c['build'] + c['test'] + c['M'], (kind, s, c)
    for s, v in PUBLISHED_PASS_338.items():
        got = t[('exe', s)]['acc'] + t[('lib', s)]['acc'] + pilot_acc[s]
        assert got == v, f'{s}: P_acc + pilot = {got}, công bố {v}'
    return t


def main():
    t = tally()
    tot = {k: C.Counter() for k in ('exe', 'lib')}
    lines = []
    for gi, (gname, systems) in enumerate(GROUPS):
        if gi: lines.append('\\addlinespace')
        lines.append(f'\\multicolumn{{11}}{{@{{}}l}}{{\\textit{{{gname}}}}} \\\\')
        for s, name in systems:
            cells = []
            for k in ('exe', 'lib'):
                c = t[(k, s)]; tot[k].update(c)
                cells += [str(c[x]) for x in COLS]
            lines.append(f'\\quad {name} & ' + ' & '.join(cells) + ' \\\\')
    total = [str(tot[k][x]) for k in ('exe', 'lib') for x in COLS]
    body = '\n'.join(lines)
    tex = f"""% SINH TU DONG boi scripts/gen-population-table.py. KHONG SUA TAY.
% Nguon: {os.path.relpath(EXE_DEC, ROOT)}; {os.path.relpath(LIB, ROOT)}
\\begin{{table}}[t]
\\centering
\\footnotesize
\\caption{{Study population by system, from the decisions recorded in the
HARVEST results repository. $P_0$: pairs of a non-pilot program and a system;
$P_{{\\mathit{{acc}}}}$: accepted translations; $R_0$: rejected translations,
split by the stage recorded in \\code{{result.json}}; $M$: pairs with no
released translation. The counts involve no execution.}}
\\label{{tab:m-population}}
\\setlength{{\\tabcolsep}}{{4pt}}
\\begin{{tabular}}{{@{{}}l rrrrr @{{\\hspace{{10pt}}}} rrrrr@{{}}}}
\\toprule
 & \\multicolumn{{5}}{{c}}{{Executable programs}} & \\multicolumn{{5}}{{c}}{{Libraries}} \\\\
\\cmidrule(lr){{2-6}} \\cmidrule(l){{7-11}}
 & & & \\multicolumn{{2}}{{c}}{{$R_0$}} & & & & \\multicolumn{{2}}{{c}}{{$R_0$}} & \\\\
\\cmidrule(lr){{4-5}} \\cmidrule(lr){{9-10}}
System & $P_0$ & $P_{{\\mathit{{acc}}}}$ & build & test & $M$ & $P_0$ & $P_{{\\mathit{{acc}}}}$ & build & test & $M$ \\\\
\\midrule
{body}
\\midrule
Total & {' & '.join(total)} \\\\
\\bottomrule
\\end{{tabular}}
\\end{{table}}
"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w').write(tex)
    print('Total exe', dict(tot['exe']), 'lib', dict(tot['lib']))


if __name__ == '__main__':
    main()
