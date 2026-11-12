#!/usr/bin/env python3
"""Sinh writing/generated/v3-numbers.tex: các số dẫn xuất mà bản v3 (writing/v3/) dùng cho RQ3 và Chương 5.
Trước 12/11 các số này được tính ngay trong LaTeX (\\numexpr, \\fpeval); script này thay cho cách đó để mọi con số đi qua file sinh.

Đầu vào là hai file macro đã sinh, không đọc lại dữ liệu thí nghiệm:
  - generated/rq-numbers.tex       (gen-rq-macros.py): P0, P_acc, L_P, L_R, khoảng RQ3 theo công thức gốc, nguyên nhân hao hụt
  - generated/sanbound-numbers.tex (gen-sanbound-macros.py, exp 38): cận trên khi 36 bản RQ2 executable không thể thành F
  - generated/census-numbers.tex   (gen-census-macros.py): số case và số cặp theo loại, để tính cột Total của Bảng 3.1
  - experiments/41-lp-star/results/lp-star-{exe,lib}.json (exp 41): acceptance thiếu seed đã có retained divergence (L_P \\ L_P*), theo hệ

Định nghĩa (decision-log 2026-11-12, "RQ3: đầu trên chặt L_R* là khoảng chính"; văn ở v3/03-methodology.tex mục 3.4.4):
  L_R*  = L_R trừ các quyết định từ chối đã có vector trượt khác C ở mọi lượt (executable: rqSanBoundKMaxExeAllNum; library: 0)
  E_P   = acceptance trong L_P đã có retained divergence trên seed hoàn tất (exp 41); L_P* = L_P - E_P
  s_up  = (|P_acc| - D - E_P + F + L_R*) / |P0|; điểm xuất phát: executable rqSanBoundSRHiKZero*, library rqSRHi*; rồi trừ E_P theo hệ
  open  = L_P* + L_R*           (quyết định còn mở, tử số của độ rộng khoảng)
  loss  = L_P + L_R             (quyết định không có kết quả, tổng của bảng nguyên nhân)
  width = 100 * open / |P0|
  decrease_min = 100 * (|P_acc| - s_up_num) / |P0|;  decrease_max = 100 * (|P_acc| - s_low_num) / |P0|
  unfinished = thiếu seed + thiếu record ở nhánh chấp nhận
Chạy: python3 writing/scripts/gen-v3-macros.py   (từ gốc repo hoặc từ writing/)"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, '..', 'generated')
OUT = os.path.join(GEN, 'v3-numbers.tex')
SYSTEMS = ['', 'Kiro', 'Claude', 'Codex', 'CTwoRust', 'Laertes', 'CTwoSaferRust', 'SmartCTwoRust', 'Kimi', 'GptFive', 'Gemini']
HARVEST = {'Kiro': 'kiro', 'Claude': 'claude', 'Codex': 'codex-gpt54', 'CTwoRust': 'c2rust', 'Laertes': 'laertes',
           'CTwoSaferRust': 'c2saferrust', 'SmartCTwoRust': 'smartc2rust', 'Kimi': 'kimi', 'GptFive': 'gpt-5.4',
           'Gemini': 'gemini-3.1-pro-preview'}
EXP41 = os.path.join(HERE, '..', '..', 'experiments', '41-lp-star', 'results')


def load(name):
    d = {}
    for m in re.finditer(r'\\rqSet\{(\w+)\}\{([^}]*)\}', open(os.path.join(GEN, name), encoding='utf-8').read()):
        d[m.group(1)] = m.group(2)
    return d


def pct(num, den):
    return f'{100.0 * num / den:.1f}'


def main():
    rq, sb = load('rq-numbers.tex'), load('sanbound-numbers.tex')
    I = lambda k: int(rq[k])
    out = {}
    # đầu trên chặt theo hệ: mặc định bằng công thức gốc; executable của codex-gpt54 và tổng executable lấy từ exp 38
    for kind in ('Exe', 'Lib'):
        for s in SYSTEMS:
            out[f'rqSRUp{kind}All{s}Pct'] = rq[f'rqSRHi{kind}All{s}Pct']
            out[f'rqSRUp{kind}All{s}Num'] = rq[f'rqSRHi{kind}All{s}Num']
    for s in ('', 'Codex'):
        out[f'rqSRUpExeAll{s}Pct'] = sb[f'rqSanBoundSRHiKZeroExeAll{s}Pct']
        out[f'rqSRUpExeAll{s}Num'] = sb[f'rqSanBoundSRHiKZeroExeAll{s}Num']
    excluded = {'Exe': int(sb['rqSanBoundKMaxExeAllNum']), 'Lib': 0}
    # exp 41: trừ E_P theo hệ khỏi đầu trên; giữ đầu trên khi bỏ chặt L_R* (cho câu 'nếu tính các rejection SPHINCS+')
    ep = {}
    for kind in ('Exe', 'Lib'):
        by = json.load(open(os.path.join(EXP41, f'lp-star-{kind.lower()}.json'), encoding='utf-8'))['retained_by_system']
        assert set(by) <= set(HARVEST.values()), by
        ep[kind] = {s: by.get(HARVEST[s], 0) for s in SYSTEMS if s}
        ep[kind][''] = sum(by.values())
        for s in SYSTEMS:
            p0s = I(f'rqPzero{kind}All{s}Num')
            num = int(out[f'rqSRUp{kind}All{s}Num']) - ep[kind][s]
            out[f'rqSRUp{kind}All{s}Num'] = str(num)
            out[f'rqSRUp{kind}All{s}Pct'] = pct(num, p0s)
            out[f'rqSRUp{kind}All{s}Den'] = str(p0s)
            if kind == 'Exe' and s in ('', 'Codex'):
                # đầu trên khi tính cả các rejection có vector khác C như có thể unsupported (bỏ chặt L_R*, giữ E_P)
                loose = int(rq[f'rqSRHi{kind}All{s}Num']) - ep[kind][s]
                out[f'rqSRUpNoLrStar{kind}All{s}Num'] = str(loose)
                out[f'rqSRUpNoLrStar{kind}All{s}Pct'] = pct(loose, p0s)
        out[f'rqLpStarRet{kind}AllNum'] = str(ep[kind][''])
    for kind in ('Exe', 'Lib'):
        p0, pacc, lp, lr = I(f'rqPzero{kind}AllNum'), I(f'rqPacc{kind}AllNum'), I(f'rqLp{kind}AllNum'), I(f'rqLr{kind}AllNum')
        up, lo = int(out[f'rqSRUp{kind}AllNum']), I(f'rqSRLo{kind}AllNum')
        opened = lp - ep[kind][''] + lr - excluded[kind]
        out[f'rqLpStar{kind}AllNum'] = str(lp - ep[kind][''])
        d, pacc_ = I(f'rqFP{kind}AllNum'), I(f'rqPacc{kind}AllNum')
        out[f'rqFPBoundLoTight{kind}AllNum'] = str(d + ep[kind][''])
        out[f'rqFPBoundLoTight{kind}AllDen'] = str(pacc_)
        out[f'rqFPBoundLoTight{kind}AllPct'] = pct(d + ep[kind][''], pacc_)
        out[f'rqLossTotal{kind}AllNum'] = str(lp + lr)
        out[f'rqOpen{kind}AllNum'] = str(opened)
        out[f'rqLrStar{kind}AllNum'] = str(lr - excluded[kind])
        out[f'rqSRWidthTight{kind}AllPct'] = pct(opened, p0)
        out[f'rqSRDecrMin{kind}AllPct'] = pct(pacc - up, p0)
        out[f'rqSRDecrMax{kind}AllPct'] = pct(pacc - lo, p0)
        out[f'rqUnfinished{kind}AllNum'] = str(I(f'rqLeaveMissingSeed{kind}AllNum') + I(f'rqLeaveMissingRecord{kind}AllNum'))
        out[f'rqUnfinishedOpen{kind}AllNum'] = str(int(out[f'rqUnfinished{kind}AllNum']) - ep[kind][''])
        assert ep[kind][''] <= I(f'rqLeaveMissingSeed{kind}AllNum'), kind
        # kiểm nhất quán: độ rộng tính từ số đếm phải bằng hiệu hai đầu khoảng (số đếm), và đầu trên không vượt công thức gốc
        assert up - lo == opened, (kind, up, lo, opened)
        assert up <= I(f'rqSRHi{kind}AllNum'), kind
    assert int(out['rqOpenLibAllNum']) == I('rqLpLibAllNum') + I('rqLrLibAllNum') - ep['Lib'][''], 'library: L_R* = L_R'
    # RQ1 executable: tách nhóm case không đọc input (chỉ phát lại vector gốc; rqInsens* của gen-rq-macros.py, decision-log 2026-10-24)
    ptest, d, ins_p, ins_d = I('rqPtestExeAllNum'), I('rqFPExeAllNum'), I('rqInsensExeAllDen'), I('rqInsensExeAllNum')
    out['rqInsensPtestExeAllNum'] = str(ins_p)
    out['rqInsensDExeAllNum'] = str(ins_d)
    out['rqSensFPExeAllNum'] = str(d - ins_d)
    out['rqSensFPExeAllDen'] = str(ptest - ins_p)
    out['rqSensFPExeAllPct'] = pct(d - ins_d, ptest - ins_p)
    # Phụ lục A, mục gán nhãn có hỗ trợ của model: số mục và số mục ba lượt cùng nhãn, đọc thẳng từ file nhãn của từng exp
    X = os.path.join(HERE, '..', '..', 'experiments')
    def merged(*fs):
        rows = [json.loads(l) for f in fs for l in open(os.path.join(X, f), encoding='utf-8')]
        return len(rows), sum(bool(r.get('agree')) for r in rows)
    lab = {'Insp': merged('31-r9-check/results/labels-merged.jsonl', '32-robustness-s0/results/r9ext/labels-merged.jsonl'),
           'RqTwo': merged('34-rq2-check/results/labels-merged.jsonl')}
    b3 = json.load(open(os.path.join(X, '32-robustness-s0/results/b3/merged.json'), encoding='utf-8'))
    lab['Theme'] = (len(b3), sum(bool(x['agree']) for x in b3))
    P = [{(r['kind'], r['path'], r['bundle'], r['case'], r['system']): r['group']
          for r in map(json.loads, open(os.path.join(X, f'33-nonrep-evidence/results/labels/pass-{i}.jsonl'), encoding='utf-8'))}
         for i in (1, 2, 3)]
    assert all(set(p) == set(P[0]) for p in P)
    lab['Nonrep'] = (len(P[0]), sum(len({p[k] for p in P}) == 1 for k in P[0]))
    for k, (n, a) in lab.items():
        out[f'rqLab{k}N'] = str(n); out[f'rqLab{k}Agree'] = str(a)
    # cột Total của Bảng 3.1 (v3/03-methodology.tex): tổng executable và library
    cen = dict(re.findall(r'\\renewcommand\{\\(\w+)\}\{([^}]*)\}', open(os.path.join(GEN, 'census-numbers.tex'), encoding='utf-8').read()))
    for name, e, l in (('nTotalPilot', 'nExePilot', 'nLibPilot'), ('nTotalPrimary', 'nExePrimary', 'nLibPrimary'),
                       ('nTotalPzero', 'nExePzero', 'nLibPzero'), ('nTotalKimiMissing', 'nKimiMissingExe', 'nKimiMissingLib')):
        out[name] = str(int(cen[e]) + int(cen[l]))
    assert int(cen['nExeCases']) + int(cen['nLibCases']) == int(cen['nCorpusCases'])
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=HERE, capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = '??'
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('% SINH TU DONG boi writing/scripts/gen-v3-macros.py. KHONG SUA TAY.\n')
        f.write(f'% Repo commit: {commit}. Nguon: generated/rq-numbers.tex, generated/sanbound-numbers.tex (exp 38), generated/census-numbers.tex, experiments/41-lp-star/results (exp 41).\n')
        f.write('% Dinh nghia: decision-log 2026-11-12 (dau tren chat L_R*, L_P*); v3/03-methodology.tex muc ve khoang RQ3.\n')
        f.write('\\providecommand{\\rqSet}[2]{\\expandafter\\def\\csname #1\\endcsname{#2}}\n')
        for k, v in out.items():
            f.write(f'\\rqSet{{{k}}}{{{v}}}\n')
    print(f'{len(out)} macro -> {os.path.relpath(OUT)}', file=sys.stderr)
    for k in ('rqSRUpExeAllPct', 'rqSRUpExeAllCodexPct', 'rqOpenExeAllNum', 'rqOpenLibAllNum', 'rqSRWidthTightExeAllPct',
              'rqSRDecrMinExeAllPct', 'rqSRDecrMaxExeAllPct', 'rqSRDecrMinLibAllPct', 'rqSRDecrMaxLibAllPct', 'rqUnfinishedExeAllNum'):
        print(f'  {k} = {out[k]}', file=sys.stderr)


if __name__ == '__main__':
    main()
