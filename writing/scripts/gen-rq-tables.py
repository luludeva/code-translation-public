#!/usr/bin/env python3
"""Sinh thân bảng (tabular, booktabs, như tab-m-population.tex) cho các bảng chính Chương 4 mà §3.6 hứa: writing/generated/tab-rq1-*.tex,
tab-bnu-*.tex, tab-rq2-*.tex, tab-rq3-*.tex. Chỉ thân bảng: môi trường table, caption và label do phiên viết đặt quanh lệnh \\input.

Ô bảng KHÔNG chứa số: mọi ô là macro của writing/generated/rq-numbers.tex (gen-rq-macros.py), nên số liệu chỉ có một nguồn và bảng
không cần sinh lại khi số đổi. Ngoại lệ: tab-rq2-channels.tex có một dòng mỗi tổ hợp kênh có trong dữ liệu, nên cần cùng --in với
gen-rq-macros.py; không có dữ liệu thì bảng có một dòng ??. Preamble phải \\input rq-numbers.tex trước các bảng.

Dùng: python3 writing/scripts/gen-rq-tables.py [--in <thư mục>] [--outdir <dir>] [--prefix rq] [--pilot]"""
import argparse, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('gen_rq_macros', f'{HERE}/gen-rq-macros.py')
G = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(G)
ROOT = G.ROOT
OUTDIR = f'{ROOT}/writing/generated'
# Nhóm hệ và tên hiển thị như Bảng 3.1 (gen-population-table.py)
SYS_GROUPS = [('Agentic (ACTOR)', [('kiro', 'Kiro'), ('claude', 'Claude Code'), ('codex-gpt54', 'Codex (GPT-5.4)')]),
              ('Rule-based', [('c2rust', 'C2Rust'), ('laertes', 'Laertes')]),
              ('LLM-assisted', [('c2saferrust', 'C2SaferRust'), ('smartc2rust', 'SmartC2Rust')]),
              ('One-shot LLM', [('kimi', 'Kimi K2.5'), ('gpt-5.4', 'GPT-5.4'), ('gemini-3.1-pro-preview', 'Gemini 3.1 Pro')])]
SHORT = {'kiro': 'Kiro', 'claude': 'Claude', 'codex-gpt54': 'Codex', 'c2rust': 'C2Rust', 'laertes': 'Laertes', 'c2saferrust': 'C2SR',
         'smartc2rust': 'SC2R', 'kimi': 'Kimi', 'gpt-5.4': 'GPT', 'gemini-3.1-pro-preview': 'Gemini'}
GROUP_NAME = {'B01': 'B01', 'B02': 'B02', 'P00': 'P00', 'P01': 'P01', 'all': 'All'}
KIND_NAME = dict(exe='Executable programs', lib='Libraries')
HEAD = '% SINH TU DONG boi writing/scripts/gen-rq-tables.py. KHONG SUA TAY. O bang la macro cua generated/rq-numbers.tex.\n'
PCT = r'\%'


class T:
    def __init__(self, prefix): self.p = prefix

    def m(self, fam, kind, field, g='all', s=None):
        return f'\\{self.p}{fam}{G.KIND_TOK[kind]}{G.GROUP_TOK[g]}{G.SYS_TOK[s] if s else ""}{field}'


def tabular(cols, header, body, note=''):
    """Thân bảng booktabs; header, body: danh sách dòng LaTeX (không kèm \\\\ ở header nếu đã có)."""
    return (HEAD + (f'% {note}\n' if note else '') + f'\\begin{{tabular}}{{{cols}}}\n\\toprule\n' + '\n'.join(header) +
            '\n\\midrule\n' + '\n'.join(body) + '\n\\bottomrule\n\\end{tabular}\n')


def sys_rows(cells_fn, ncols, total_fn):
    """Dòng theo nhóm hệ như Bảng 3.1, rồi dòng Total."""
    out = []
    for gi, (gname, systems) in enumerate(SYS_GROUPS):
        if gi: out.append('\\addlinespace')
        out.append(f'\\multicolumn{{{ncols}}}{{@{{}}l}}{{\\textit{{{gname}}}}} \\\\')
        for s, name in systems:
            out.append(f'\\quad {name} & ' + ' & '.join(cells_fn(s)) + ' \\\\')
    out += ['\\midrule', 'Total & ' + ' & '.join(total_fn()) + ' \\\\']
    return out


def tab_rq1_fp(t, kind):
    """RQ1 theo hệ: P_acc, P_test, D, r_FP; phân bố số seed phát hiện (R19); hai nhóm ngoài D (§3.6); khoảng chặn (R2)."""
    def cells(s):
        return [t.m('Pacc', kind, 'Num', s=s), t.m('Ptest', kind, 'Num', s=s), t.m('FP', kind, 'Num', s=s), t.m('FP', kind, 'Pct', s=s),
                *(t.m(f'SeedDet{w}', kind, 'Num', s=s) for w in ('One', 'Two', 'Three')),
                t.m('UnstableOnly', kind, 'Num', s=s), t.m('InconclOnly', kind, 'Num', s=s),
                t.m('FPBoundLo', kind, 'Pct', s=s), t.m('FPBoundHi', kind, 'Pct', s=s)]
    hdr = [' & & & & & \\multicolumn{3}{c}{Seeds detecting} & & & \\multicolumn{2}{c}{Bounds (' + PCT + ')} \\\\',
           '\\cmidrule(lr){6-8} \\cmidrule(l){11-12}',
           f'System & $P_{{\\mathit{{acc}}}}$ & $P_{{\\mathit{{test}}}}$ & $D$ & $r_{{\\mathit{{FP}}}}$ ({PCT}) & 1 & 2 & 3 & Unst. & Inc. & '
           f'$D/P_{{\\mathit{{acc}}}}$ & $(D{{+}}L_P)/P_{{\\mathit{{acc}}}}$ \\\\']
    return tabular('@{}l rrrr rrr rr rr@{}', hdr, sys_rows(cells, 12, lambda: cells(None)),
                   f'RQ1 {kind}: Unst. = moi divergence khong on dinh; Inc. = sanitizer inconclusive (overlap: macro InconclUnstable)')


def tab_rq1_groups(t):
    """RQ1 theo nhóm (R20), executable trước library: r_FP, biến thiên theo seed (R4, R5), dải B/N/U (R13)."""
    body = []
    for ki, kind in enumerate(G.KINDS):
        if ki: body.append('\\addlinespace')
        body.append(f'\\multicolumn{{7}}{{@{{}}l}}{{\\textit{{{KIND_NAME[kind]}}}}} \\\\')
        for g in G.GROUPS[1:] + ('all',):
            body.append(f'\\quad {GROUP_NAME[g]} & ' + ' & '.join(
                [t.m('Ptest', kind, 'Num', g), t.m('FP', kind, 'Num', g), t.m('FP', kind, 'Pct', g)] +
                [t.m('NBLo', kind, 'Num', g), t.m('NBHi', kind, 'Num', g),
                 f"{t.m('NBLo', kind, 'Pct', g)}--{t.m('NBHi', kind, 'Pct', g)}"]) + ' \\\\')
    hdr = [' & & & & \\multicolumn{3}{c}{Non-benign} \\\\',
           '\\cmidrule(l){5-7}',
           f'Group & $P_{{\\mathit{{test}}}}$ & $D$ & $r_{{\\mathit{{FP}}}}$ ({PCT}) & $\\mathit{{NB}}^L$ & $\\mathit{{NB}}^U$ & range ({PCT}) \\\\']
    # MR-17, C7 (Le chốt 10/11, Q-S1): bỏ ba cột r_FP theo seed, vì mẫu số P_test của từng seed khác nhau nhiều (seed chưa xong do cắt ngân
    # sách) nên các cột không so được; mức phụ thuộc seed báo bằng SeedDet* (số seed phát hiện) ở văn.
    return tabular('@{}l rrr rrr@{}', hdr, body, 'Bo cot theo seed (MR-17, Q-S1); hang All cua group la moi nhom')


def tab_rq1_attrition(t, kind):
    """Phễu đường chấp nhận theo hệ: P_acc -> P_rep (nguyên nhân §3.2) -> P_test (mã rời của metrics); L_P (§3.6)."""
    leave = getattr(G, '_leave_codes', G.LEAVE_CODES_FALLBACK)
    rows = [('$P_{\\mathit{acc}}$', 'Pacc', 'Num')]
    rows += [(f'\\quad {x.replace("_", " ")}', f'PreRep{G.tok(x)}', 'Num') for x in G.PRE_REP_CAUSES]
    rows += [('$P_{\\mathit{rep}}$', 'Prep', 'Num')]
    rows += [(f'\\quad \\code{{{x.replace("_", chr(92) + "_")}}}', f'Leave{G.tok(x)}', 'Num') for x in leave] + [('\\quad other', 'LeaveOther', 'Num')]
    rows += [('$P_{\\mathit{test}}$', 'Ptest', 'Num'), ('$L_P$', 'Lp', 'Num')]
    systems = [s for _, ss in SYS_GROUPS for s, _ in ss]
    body = [f'{lab} & ' + ' & '.join([t.m(f, kind, fld, s=s) for s in systems] + [t.m(f, kind, fld)]) + ' \\\\' for lab, f, fld in rows]
    hdr = ['Stage or cause & ' + ' & '.join(SHORT[s] for s in systems) + ' & Total \\\\']
    return tabular('@{}l ' + 'r' * (len(systems) + 1) + '@{}', hdr, body,
                   f'{kind}: nguyen nhan truoc P_rep la dinh nghia cua gen-rq-macros.py (Q-A1); \\code can macro cua preamble')


ROB = [('Primary measure', 'FP', 'EL'), ('1 C crash without sanitizer report', 'RobCCrash', 'EL'),
       ('2 Unstable divergences', 'RobUnstable', 'EL'), ('3 Complete input layers', 'RobComplete', 'E'),
       ('4 Exact floating-point comparison', 'RobExact', 'L'), ('5 Floating-point criterion of the original oracle', 'RobOrigFloat', 'L'),
       ('6 Without standard error', 'RobNoStderr', 'EL'), ('7 Larger output limit', 'RobCapEight', 'EL'),
       ('8 Inconclusive sanitizer checks', 'RobInconcl', 'EL')]


def _ndp(t, fam, kind, g='all'):
    return [t.m(fam, kind, 'Num', g), t.m(fam, kind, 'Den', g), t.m(fam, kind, 'Pct', g)]


# Hai phân tích số thực của library: analysis-lib.json ghi computable false (bản ghi RQ1 không đủ để tính D), nên bảng in
# "not computable" thay ba ô ?? (brief kỹ thuật 2026-11-10, MR-16); không có analysis-lib.json thì giữ macro (ô hiện ??).
NOT_COMPUTABLE = {'RobExact': 'exact', 'RobOrigFloat': 'orig_float'}


def _not_computable(D, fam):
    sec = (((D.analysis.get('lib') or {}).get('sections') or {}).get('rq1_rob_float') or {}).get('all', {}).get('_all', {})
    return fam in NOT_COMPUTABLE and (sec.get(NOT_COMPUTABLE[fam]) or {}).get('computable') is False


def tab_rq1_robust(t, D=None):
    """Tám robustness analyses RQ1 (§3.6), mỗi dòng tử số, mẫu số, tỉ lệ; ô không áp dụng là n/a; ô không tính được là not computable."""
    na = ['\\multicolumn{3}{c}{n/a}']; nc = ['\\multicolumn{3}{c}{not computable}']
    body = []
    for lab, fam, ks in ROB:
        cells = []
        for kind, k in (('exe', 'E'), ('lib', 'L')):
            if not (ks == 'EL' or ks == k): cells += na
            elif kind == 'lib' and D is not None and _not_computable(D, fam): cells += nc
            else: cells += _ndp(t, fam, kind)
        body.append(f'{lab} & ' + ' & '.join(cells) + ' \\\\')
    hdr = [' & \\multicolumn{3}{c}{Executable programs} & \\multicolumn{3}{c}{Libraries} \\\\',
           '\\cmidrule(lr){2-4} \\cmidrule(l){5-7}', f'Analysis & $D$ & Den. & {PCT} & $D$ & Den. & {PCT} \\\\']
    return tabular('@{}l rrr rrr@{}', hdr, body, 'Phan tich 4, 5: harness.analysis, ban ghi RQ1 khong du de tinh D nen in not computable (Q-R1, MR-16); '
                   'thanh phan tinh duoc: macro RobOrigFloatRemovedDiv, RobOrigFloatAllRemoved')


def tab_bnu_range(t):
    """Dải B/N/U theo hệ (R13): NB^L, NB^U trên P_test."""
    def cells(s):
        out = []
        for kind in G.KINDS:
            out += [t.m('Ptest', kind, 'Num', s=s), t.m('NBLo', kind, 'Num', s=s), t.m('NBHi', kind, 'Num', s=s),
                    f"{t.m('NBLo', kind, 'Pct', s=s)}--{t.m('NBHi', kind, 'Pct', s=s)}"]
        return out
    hdr = [' & \\multicolumn{4}{c}{Executable programs} & \\multicolumn{4}{c}{Libraries} \\\\',
           '\\cmidrule(lr){2-5} \\cmidrule(l){6-9}',
           'System & $P_{\\mathit{test}}$ & $\\mathit{NB}^L$ & $\\mathit{NB}^U$ & range (' + PCT + ') & $P_{\\mathit{test}}$ & '
           '$\\mathit{NB}^L$ & $\\mathit{NB}^U$ & range (' + PCT + ') \\\\']
    return tabular('@{}l rrrr rrrr@{}', hdr, sys_rows(cells, 9, lambda: cells(None)))


def tab_bnu_rules(t, rules):
    """Divergence giữ lại và bản dịch theo mã luật B/N/U (luật khớp đầu tiên thắng; R13)."""
    body = []
    for gi, grp in enumerate('BNU'):
        rs = [r for r in rules if r[0] == grp]
        if not rs: continue
        if gi: body.append('\\addlinespace')
        for r in rs:
            body.append(f'\\code{{{r}}} & ' + ' & '.join(
                c for kind in G.KINDS for c in (t.m(f'BnuDiv{G.tok(r)}', kind, 'Num'), t.m(f'BnuTrans{G.tok(r)}', kind, 'Num'))) + ' \\\\')
    r0 = G.tok(rules[0]) if rules else 'None'
    body += ['\\midrule', 'Total & ' + ' & '.join(c for kind in G.KINDS for c in
                                                   (t.m(f'BnuDiv{r0}', kind, 'Den'), t.m(f'BnuTrans{r0}', kind, 'Den'))) + ' \\\\']
    hdr = [' & \\multicolumn{2}{c}{Executable programs} & \\multicolumn{2}{c}{Libraries} \\\\',
           '\\cmidrule(lr){2-3} \\cmidrule(l){4-5}', 'Rule & Divergences & Translations & Divergences & Translations \\\\']
    return tabular('@{}l rr rr@{}', hdr, body,
                   'Total: divergence giu lai (n_div_retained) va D; mot ban dich co the co nhieu ma luat nen cot Translations khong cong lai bang D')


def tab_rq2_ff(t):
    """RQ2 theo hệ (R14): R_0^test, R_test, A, F, không phân xử được, r_FF."""
    def cells(s):
        out = []
        for kind in G.KINDS:
            out += [t.m('RZeroTest', kind, 'Num', s=s), t.m('FF', kind, 'Den', s=s), t.m('FFDisagree', kind, 'Num', s=s),
                    t.m('FF', kind, 'Num', s=s), t.m('FFNotAdj', kind, 'Num', s=s), t.m('FF', kind, 'Pct', s=s)]
        return out
    lab = ['$R_0^{\\mathit{test}}$', '$R_{\\mathit{test}}$', '$A$', '$F$', 'N.adj.', '$r_{\\mathit{FF}}$ (' + PCT + ')']
    hdr = [' & \\multicolumn{6}{c}{Executable programs} & \\multicolumn{6}{c}{Libraries} \\\\',
           '\\cmidrule(lr){2-7} \\cmidrule(l){8-13}', 'System & ' + ' & '.join(lab + lab) + ' \\\\']
    return tabular('@{}l rrrrrr rrrrrr@{}', hdr, sys_rows(cells, 13, lambda: cells(None)))


# H6 (Le chốt 10/11): nhãn đọc được cho mã lý do của harness.rq2 trong bảng chính; bảng ánh xạ nhãn sang mã (tab-rq2-reason-map.tex) cho
# Phụ lục C. Nghĩa theo docstring và vector_outcome của harness/rq2.py ở bc82907. Mã không có trong bảng thì in mã (\code) như trước.
REASON_LABEL = {
    'ub_in_c': 'C sanitizer reports undefined behavior',
    'both_budget': 'Both sides exceed the budget',
    'sanitizer_inconclusive': 'Sanitizer check inconclusive',
    'c_unstable': 'C observation varies across runs',
    'unstable_comparison': 'Comparison result varies across runs',
    'no_failing_vector': 'Recorded report lists no failing vector',
    'report_missing': 'Recorded report not found',
    'timeout_only_rule_pending': 'Failing vectors fail only through timeouts',
    'build_failed_in_harness': 'C or Rust build fails in the harness',
    'incomplete_harness_run:vector_unreadable': 'Incomplete run: vector file empty',
    'incomplete_harness_run:invalid_input': 'Incomplete run: vector outside the runner input domain',
    'incomplete_harness_run:run_unobserved': 'Incomplete run: runner wrote no report',
    'incomplete_harness_run:san_build_failed': 'Incomplete run: C sanitizer build failed',
    'incomplete_harness_run:san_infra': 'Incomplete run: sanitizer infrastructure fault',
}


def _reason_label(r):
    return REASON_LABEL.get(r) or f'\\code{{{r.replace("_", chr(92) + "_")}}}'


def tab_rq2_reason_map(rq2_reasons):
    """Phụ lục C: nhãn đọc được của bảng RQ2 và mã nội bộ tương ứng (H6)."""
    body = []
    for o, name in (('not_adjudicable', 'Not adjudicable'), ('not_re_examined', 'Not re-examined, in $R_{\\mathit{run}}$')):
        for r in rq2_reasons[o]:
            body.append(f'{name} & {_reason_label(r)} & \\code{{{r.replace("_", chr(92) + "_")}}} \\\\')
    return tabular('@{}lll@{}', ['Outcome & Label & Code \\\\'], body, 'Anh xa nhan doc duoc sang ma harness.rq2 (H6)')


def tab_rq2_outcomes(t, rq2_reasons):
    """Mỗi bản bị từ chối ở bước test nhận đúng một kết quả (Bảng 3.3); cột tổng là R_0^test."""
    def row(lab, fam, fld='Num'):
        return f'{lab} & ' + ' & '.join(t.m(fam, kind, fld) for kind in G.KINDS) + ' \\\\'
    body = [row('Behavioral disagreement ($A$)', 'FFDisagree'), row('Behavioral agreement ($F$)', 'FF'),
            row('Not adjudicable', 'FFNotAdj')]
    body += [row(f'\\quad {_reason_label(r)}', f'FFReasonNotAdjudicable{G.tok(r)}') for r in rq2_reasons['not_adjudicable']]
    body += [row('Non-reproduced decision', 'RZeroTestRNonrep'), row('Not re-examined, before $R_{\\mathit{run}}$: no build', 'RZeroTestRNobuild'),
             row('Not re-examined, before $R_{\\mathit{run}}$: other', 'RZeroTestROther'), row('Not re-examined, in $R_{\\mathit{run}}$', 'FFNotReex')]
    body += [row(f'\\quad {_reason_label(r)}', f'FFReasonNotReExamined{G.tok(r)}') for r in rq2_reasons['not_re_examined']]
    body += [row('Harness error', 'FFHarnessError'), '\\midrule', row('$R_0^{\\mathit{test}}$', 'RZeroTest'),
             row('$L_R$', 'Lr')]
    return tabular('@{}l rr@{}', ['Outcome & Executable programs & Libraries \\\\'], body,
                   'Kiem: tong cac dong khong thut le bang R_0^test (non-reproduced va not re-examined truoc R_run tu census, Q-F1)')


def tab_rq2_channels(t, combos):
    """Chấm trượt oan theo tổ hợp kênh mà quyết định gốc và đồng thuận khác nhau (§3.6, R14): mỗi tổ hợp một dòng."""
    if combos:
        body = [f'\\code{{{cb.replace("_", chr(92) + "_")}}} & ' + ' & '.join(t.m(f'FFCombo{G.tok(cb)}', kind, 'Num') for kind in G.KINDS) + ' \\\\'
                for cb in combos]
    else:
        body = ['?? & ?? & ?? \\\\']
    body += ['\\midrule', 'Total ($F$) & ' + ' & '.join(t.m('FF', kind, 'Num') for kind in G.KINDS) + ' \\\\']
    return tabular('@{}l rr@{}', ['Components & Executable programs & Libraries \\\\'], body,
                   'Dong theo du lieu: sinh lai bang voi cung --in sau khi so doi')


def tab_rq2_robust(t):
    na = ['\\multicolumn{3}{c}{n/a}']
    body = []
    for lab, fam, ks in (('Primary measure', 'FF', 'EL'), ('Without standard error', 'RobFFNoStderr', 'EL'),
                         ('Exact floating-point comparison', 'RobFFExact', 'L'),
                         ('Floating-point criterion of the original oracle', 'RobFFOrigFloat', 'L')):
        cells = []
        for kind, k in (('exe', 'E'), ('lib', 'L')):
            cells += _ndp(t, fam, kind) if (ks == 'EL' or ks == k) else na
        body.append(f'{lab} & ' + ' & '.join(cells) + ' \\\\')
    hdr = [' & \\multicolumn{3}{c}{Executable programs} & \\multicolumn{3}{c}{Libraries} \\\\',
           '\\cmidrule(lr){2-4} \\cmidrule(l){5-7}', f'Analysis & $F$ & $|R_{{\\mathit{{test}}}}|$ & {PCT} & $F$ & $|R_{{\\mathit{{test}}}}|$ & {PCT} \\\\']
    return tabular('@{}l rrr rrr@{}', hdr, body, 'Ba phan tich RQ2: harness.analysis (analysis-K.json), ban ghi khong co obs thi ??; '
                   'ban doi thanh not adjudicable, not re-examined: macro RobFF<phan tich>NotAdj, NotReex (Q-R3)')


def tab_rq1_inputs(t, layers):
    """Divergence theo tầng input (R24) và input ngoài miền theo tầng (§3.6 Reporting), executable trước library (harness.analysis)."""
    body = []
    for ki, kind in enumerate(G.KINDS):
        if ki: body.append('\\addlinespace')
        body.append(f'\\multicolumn{{9}}{{@{{}}l}}{{\\textit{{{KIND_NAME[kind]}}}}} \\\\')
        for lay, ks in layers:
            if kind not in ks: continue
            tk = G.tok(lay)
            body.append(f'\\quad \\code{{{lay}}} & ' + ' & '.join(
                [t.m(f'DivLayer{tk}', kind, 'Num'), t.m(f'DivLayer{tk}', kind, 'Den'), t.m(f'DivLayer{tk}', kind, 'Pct'),
                 t.m(f'DivInputsLayer{tk}', kind, 'Num'), t.m(f'DivInputsLayer{tk}', kind, 'Den'), t.m(f'DivTransLayer{tk}', kind, 'Num'),
                 t.m(f'OutOfDomain{tk}', kind, 'Num'), t.m(f'OutOfDomain{tk}', kind, 'Den')]) + ' \\\\')
    hdr = [' & \\multicolumn{3}{c}{Retained divergences} & \\multicolumn{2}{c}{Distinct inputs} & & \\multicolumn{2}{c}{Out of domain} \\\\',
           '\\cmidrule(lr){2-4} \\cmidrule(lr){5-6} \\cmidrule(l){8-9}',
           f'Layer & Div. & Obs. & {PCT} & Div. & Inputs & $D$ & Inputs & Generated \\\\']
    return tabular('@{}l rrr rr r rr@{}', hdr, body,
                   'Don vi: (input, ban dich, seed) tren P_test; input phan biet (case, seed, idx); ngoai mien tren input sinh ra (Q-G1)')


def tab_rq3(t):
    """RQ3 theo hệ: s, cận dưới, cận trên, độ rộng (§3.6; R16)."""
    def cells(s):
        out = []
        for kind in G.KINDS:
            out += [t.m('Pzero', kind, 'Num', s=s), t.m('Pacc', kind, 'Num', s=s), t.m('SR', kind, 'Pct', s=s),
                    t.m('SRLo', kind, 'Pct', s=s), t.m('SRHi', kind, 'Pct', s=s), t.m('SRWidth', kind, 'Pct', s=s)]
        return out
    lab = ['$P_0$', '$P_{\\mathit{acc}}$', '$s$', 'lower', 'upper', 'width']
    hdr = [' & \\multicolumn{6}{c}{Executable programs (' + PCT + ' of $P_0$)} & \\multicolumn{6}{c}{Libraries (' + PCT + ' of $P_0$)} \\\\',
           '\\cmidrule(lr){2-7} \\cmidrule(l){8-13}', 'System & ' + ' & '.join(lab + lab) + ' \\\\']
    return tabular('@{}l rrrrrr rrrrrr@{}', hdr, sys_rows(cells, 13, lambda: cells(None)),
                   'R16: caption phai nhac gia dinh "build fail giu la fail" va M tinh la khong chap nhan')


def tab_rq1_term(t, statuses):
    """Số input theo trạng thái kết thúc mỗi phía (R28), mọi nhóm."""
    body = []
    for ki, kind in enumerate(G.KINDS):
        if ki: body.append('\\addlinespace')
        body.append(f'\\multicolumn{{5}}{{@{{}}l}}{{\\textit{{{KIND_NAME[kind]}}}}} \\\\')
        for st in statuses[kind]:
            body.append(f'\\quad \\code{{{st.replace("_", chr(92) + "_")}}} & ' + ' & '.join(
                [t.m(f'TermC{G.tok(st)}', kind, 'Num'), t.m(f'TermC{G.tok(st)}', kind, 'Pct'),
                 t.m(f'TermR{G.tok(st)}', kind, 'Num'), t.m(f'TermR{G.tok(st)}', kind, 'Pct')]) + ' \\\\')
        body.append('\\quad Total & ' + ' & '.join([t.m('TermTotalC', kind, 'Num'), '', t.m('TermTotalR', kind, 'Num'), '']) + ' \\\\')
    hdr = [' & \\multicolumn{2}{c}{C} & \\multicolumn{2}{c}{Rust} \\\\', '\\cmidrule(lr){2-3} \\cmidrule(l){4-5}',
           f'Status & Inputs & {PCT} & Inputs & {PCT} \\\\']
    return tabular('@{}l rr rr@{}', hdr, body, 'Don vi: input x ban dich trong P_test, cong qua seed (Q-T1)')


def tab_rq1_ub(t):
    """Thực thi bị loại theo R15 (R22, thu hẹp): trên divergence, theo nhóm."""
    body = []
    pairs = [('UbDiv', 'div'), ('UbDivStable', 'stable'), ('UbInputs', 'inputs'), ('UbTrans', 'trans')]
    for ki, kind in enumerate(G.KINDS):
        if ki: body.append('\\addlinespace')
        body.append(f'\\multicolumn{{5}}{{@{{}}l}}{{\\textit{{{KIND_NAME[kind]}}}}} \\\\')
        for g in G.GROUPS[1:] + ('all',):
            body.append(f'\\quad {GROUP_NAME[g]} & ' + ' & '.join(f"{t.m(f, kind, 'Num', g)}/{t.m(f, kind, 'Den', g)}" for f, _ in pairs) + ' \\\\')
    hdr = ['Group & Divergences & Stable divergences & Distinct inputs & Translations \\\\']
    return tabular('@{}l rrrr@{}', hdr, body, 'UB theo C-san tren divergence / tat ca divergence (R22 thu hep, Q-U1)')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gen-rq-tables.py')
    ap.add_argument('--in', dest='indir'); ap.add_argument('--outdir', default=OUTDIR); ap.add_argument('--harness-root', default=ROOT)
    ap.add_argument('--prefix', default='rq'); ap.add_argument('--pilot', action='store_true')
    a = ap.parse_args(argv)
    gen_dir = os.path.realpath(f'{ROOT}/writing/generated')
    if a.pilot and (os.path.realpath(a.outdir) + os.sep).startswith(gen_dir + os.sep):
        raise SystemExit('bảng pilot không được ghi vào writing/generated/ (R6); dùng --outdir ở scratchpad')
    D, fams_by_kind, _, hroot = G.prepare(a)
    HM, HP, HQ = G.load_harness(hroot)
    G._leave_codes = tuple(getattr(HM, 'LEAVE_ORDER', G.LEAVE_CODES_FALLBACK))
    rq2r = {o: rs for o, rs in HQ.TRANSLATION_REASONS.items() if rs != (None,)}
    statuses = {k: [f.name[len('TermC'):] for f in fams_by_kind[k] if f.name.startswith('TermC') and not f.name.startswith('TermTotal')]
                for k in G.KINDS}
    # tên trạng thái gốc (không tok) để hiển thị: lấy lại từ danh sách cố định + mã động
    raw = {k: [st for st in (G.EXE_STATUS if k == 'exe' else G.LIB_STATUS)] for k in G.KINDS}
    for k in G.KINDS:
        known = {G.tok(x) for x in raw[k]}
        raw[k] += [x for x in statuses[k] if x not in known]
    t = T(a.prefix)
    out = {'tab-rq1-fp-exe.tex': tab_rq1_fp(t, 'exe'), 'tab-rq1-fp-lib.tex': tab_rq1_fp(t, 'lib'),
           'tab-rq1-groups.tex': tab_rq1_groups(t), 'tab-rq1-attrition-exe.tex': tab_rq1_attrition(t, 'exe'),
           'tab-rq1-attrition-lib.tex': tab_rq1_attrition(t, 'lib'), 'tab-rq1-robust.tex': tab_rq1_robust(t, D),
           'tab-rq1-term.tex': tab_rq1_term(t, raw), 'tab-rq1-ub.tex': tab_rq1_ub(t),
           'tab-bnu-range.tex': tab_bnu_range(t), 'tab-bnu-rules.tex': tab_bnu_rules(t, G.bnu_rule_list(hroot)),
           'tab-rq2-ff.tex': tab_rq2_ff(t), 'tab-rq2-outcomes.tex': tab_rq2_outcomes(t, rq2r),
           'tab-rq2-channels.tex': tab_rq2_channels(t, G.ff_combos(D)), 'tab-rq2-robust.tex': tab_rq2_robust(t),
           'tab-rq3-bounds.tex': tab_rq3(t), 'tab-rq2-reason-map.tex': tab_rq2_reason_map(rq2r), 'tab-rq1-inputs.tex': tab_rq1_inputs(t, G.an_consts(hroot)['layers'])}
    os.makedirs(a.outdir, exist_ok=True)
    for name, tex in out.items():
        open(f'{a.outdir}/{name}', 'w').write(tex)
    print(f'Đã ghi {len(out)} bảng vào {a.outdir}', file=sys.stderr)
    return out


if __name__ == '__main__':
    main()
