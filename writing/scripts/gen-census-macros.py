#!/usr/bin/env python3
"""Sinh writing/generated/census-numbers.tex: kích thước population cho Ch3 §3.2 (P0, M, pilot, library không input).
Mọi con số §3.2 lấy từ đây, không gõ tay. Nguồn mặc định:
  - executable: experiments/02-harvest-repro/results/census-exe-ec2.jsonl (EC2, job census-exe-ec2). Census cũ (Cowork cloud,
    census-exe.jsonl) giữ để đối chiếu; trường population hai bản khớp 1090/1090 (results/census-ec2-compare.txt).
  - library: experiments/06-library-census/results/census-lib.jsonl (EC2).
Định nghĩa (decision-log 2026-10-20, phễu §3.2 sau hai vòng review): P0 = mọi cặp (chương trình không pilot, hệ);
M = cặp trong P0 không có bản dịch (stage P0_missing_artifact); library không input vẫn thuộc P0.
Nhóm "đỗ mà không vector nào được chấm" (decision-log 2026-10-21; mở rộng 2026-10-22): công bố đỗ, build được, kết quả tái lập chỉ gồm
Skip hoặc rỗng; tính lại từ trường `results`, không dùng trường dẫn xuất `ours_passed`."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
EXE = os.environ.get('EXE_CENSUS', f'{ROOT}/experiments/02-harvest-repro/results/census-exe-ec2.jsonl')
LIB = os.environ.get('LIB_CENSUS', f'{ROOT}/experiments/06-library-census/results/census-lib3.jsonl')   # census lần ba (lượt chính), từ 4/11
OUT = f'{ROOT}/writing/generated/census-numbers.tex'
QMATH = f'{ROOT}/experiments/02-harvest-repro/results/qmath.claude.report.json'


def load(p):
    return [json.loads(l) for l in open(p)]


def main():
    e, l = load(EXE), load(LIB)
    case = lambda r: (r['bundle'], r['tractor_case'])
    e_all, l_all = {case(r) for r in e}, {case(r) for r in l}
    e_pilot, l_pilot = {case(r) for r in e if r['pilot']}, {case(r) for r in l if r['pilot']}
    e0 = [r for r in e if not r['pilot']]
    l0 = [r for r in l if not r['pilot']]
    miss = lambda rs: sum(r.get('stage') == 'P0_missing_artifact' for r in rs)
    p01 = lambda rs: len({case(r) for r in rs if r['bundle'] == 'P01_sphincs_plus'})
    unjudged = lambda r: r.get('pub_passed') is True and r.get('build_ok') and set(r.get('results') or {}) <= {'Skip'}
    novec = lambda rs: sum(unjudged(r) and not r.get('results') for r in rs)        # không có vector chạy được
    allskip = lambda rs: sum(unjudged(r) and bool(r.get('results')) for r in rs)    # mọi vector bị bỏ qua vì has_ub
    # kiểm partition P0 = P_acc ⊔ R0 ⊔ M
    for name, rs in (('exe', e0), ('lib', l0)):
        rel = [r for r in rs if r.get('stage') != 'P0_missing_artifact']
        assert all(isinstance(r.get('pub_passed'), bool) for r in rel), f'{name}: có bản dịch thiếu quyết định'
    m = {
        'nExeCases': len(e_all), 'nLibCases': len(l_all), 'nCorpusCases': len(e_all) + len(l_all),
        'nExePilot': len(e_pilot), 'nLibPilot': len(l_pilot),
        'nExePrimary': len(e_all - e_pilot), 'nLibPrimary': len(l_all - l_pilot),
        'nExePzero': len(e0), 'nLibPzero': len(l0),
        'nKimiMissingExe': miss(e0), 'nKimiMissingLib': miss(l0),
        'nNoInputLib': len({case(r) for r in l0 if r['no_input']}),
        'nExePzeroP': p01(e0), 'nLibPzeroP': p01(l0),
        'nNoVecExe': novec(e0), 'nNoVecLib': novec(l0), 'nAllSkipExe': allskip(e0), 'nAllSkipLib': allskip(l0),
        'qmathVectors': len(json.load(open(QMATH))),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        f.write('% SINH TU DONG boi scripts/gen-census-macros.py. KHONG SUA TAY.\n')
        f.write(f'% Nguon executable: {os.path.relpath(EXE, ROOT)}\n% Nguon library: {os.path.relpath(LIB, ROOT)}\n')
        for k, v in m.items():
            f.write(f'\\providecommand{{\\{k}}}{{}}\\renewcommand{{\\{k}}}{{{v}}}\n')
    print(json.dumps(m), file=sys.stderr)


if __name__ == '__main__':
    main()
