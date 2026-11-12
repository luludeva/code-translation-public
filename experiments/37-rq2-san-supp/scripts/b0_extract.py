#!/usr/bin/env python3
"""Trích kết quả B0 (job rq2-san-log) từ nhánh kết quả đã nộp thành file có thể commit, để sinh macro và kiểm tay.

Đọc thẳng 36 marker C-san (ci-out/rq2-san-log/c-san/*.build.json) ở một commit cố định của results/rq2-san-log, tự đếm lại chữ ký
và đối chiếu với summary.txt do B0 in ra. Không chạy binary nào, không đổi gì trên runner.
Ghi: experiments/37-rq2-san-supp/results/b0/b0-markers.json (số và từng case) và b0-markers.md (bảng đọc tay).
Dùng (từ gốc repo, sau `git fetch origin results/rq2-san-log`):
    python3 experiments/37-rq2-san-supp/scripts/b0_extract.py [--ref ac5a1c595403941e619c0495075bdb7202eaf8e1]"""
import argparse, json, os, re, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
REF = 'ac5a1c595403941e619c0495075bdb7202eaf8e1'   # results/rq2-san-log, B0 run 42451406530 (2026-11-08)
BASE = 'ci-out/rq2-san-log'
KEYS = f'{ROOT}/experiments/37-rq2-san-supp/data/keys.txt'
OUTD = f'{ROOT}/experiments/37-rq2-san-supp/results/b0'
SIG_PC32, SIG_FPIC, LIB = 'R_X86_64_PC32', 'recompile with -fPIC', 'libsphincs_core.so'
NOISE = 'Auto packing the repository'


def git(*a):
    return subprocess.run(['git', '-C', ROOT, *a], check=True, capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--ref', default=REF); a = ap.parse_args()
    keys = [l.split('\t')[0].strip() for l in open(KEYS, encoding='utf-8') if l.strip() and not l.startswith('#')]
    cases = sorted({k.split('/')[-1] if '/' in k else k for k in keys})
    names = git('ls-tree', '-r', '--name-only', a.ref, f'{BASE}/').split()
    rows = []
    for kind in ('c-san', 'c'):
        for n in sorted(x for x in names if x.startswith(f'{BASE}/{kind}/') and x.endswith('.build.json')):
            d = json.loads(git('show', f'{a.ref}:{n}'))
            log = d.get('log') or ''
            rows.append(dict(kind=kind, case=d.get('case'), bundle=d.get('bundle'), ok=d.get('ok'), log_chars=len(log),
                             pc32=SIG_PC32 in log, fpic=SIG_FPIC in log, lib=LIB in log,
                             failed=re.findall(r'FAILED: (\S+)', log), noise_lines=log.count(NOISE), tail=log[-200:]))
    san = [r for r in rows if r['kind'] == 'c-san']
    plain = [r for r in rows if r['kind'] == 'c']
    sig = [r for r in san if r['pc32'] and r['fpic']]
    full = [r for r in sig if r['lib']]
    miss = [r for r in sig if not r['lib']]
    S = dict(ref=a.ref, run_id='42451406530', markers_san=len(san), san_ok_false=sum(r['ok'] is False for r in san),
             markers_c=len(plain), c_ok_true=sum(r['ok'] is True for r in plain), sig=len(sig), sig_lib=len(full),
             sig_no_lib=len(miss), sig_no_lib_noise=sum(r['noise_lines'] > 0 for r in miss),
             sig_no_lib_det_only=sum(r['failed'] == ['libsphincs_core_det.so'] for r in miss),
             ninja_stopped=sum('ninja: build stopped' in r['tail'] for r in san),
             sig_no_lib_trunc=sum(r['log_chars'] >= 2000 for r in miss), log_cap=2000,
             target_cases=len(cases), target_with_san_marker=len({r['case'] for r in san} & set(cases)))
    # đối chiếu với summary.txt của B0
    summ = git('show', f'{a.ref}:{BASE}/summary.txt')
    m = re.search(r'"recompile with -fPIC": (\d+)/36 \(trong đó log nhắc libsphincs_core.so: (\d+)\)', summ)
    checks = dict(summary_sig=bool(m) and int(m.group(1)) == S['sig'], summary_lib=bool(m) and int(m.group(2)) == S['sig_lib'],
                  branch_c='nhánh (c)' in summ, machine='instance_id=i-01773fe09af1a559c' in summ,
                  all_targets=S['target_with_san_marker'] == S['target_cases'] == 36)
    S['checks'] = checks
    os.makedirs(OUTD, exist_ok=True)
    with open(f'{OUTD}/b0-markers.json', 'w', encoding='utf-8') as f:
        json.dump(dict(summary=S, cases=rows), f, ensure_ascii=False, indent=1)
    with open(f'{OUTD}/b0-markers.md', 'w', encoding='utf-8') as f:
        f.write(f'# B0: 36 marker C-san (ref {a.ref}, run 42451406530)\n\nSinh bởi `scripts/b0_extract.py`. Không sửa tay. '
                'Cột: có `R_X86_64_PC32`, có `recompile with -fPIC`, có `libsphincs_core.so`, các dòng `FAILED:`, số dòng '
                '"Auto packing" của git trong 2000 ký tự cuối.\n\n| Case | ok | PC32 | -fPIC | lib | FAILED | git noise |\n|---|---|---|---|---|---|---|\n')
        for r in san:
            f.write(f"| {r['case']} | {r['ok']} | {int(r['pc32'])} | {int(r['fpic'])} | {int(r['lib'])} | {', '.join(r['failed']) or '-'} | {r['noise_lines']} |\n")
        f.write('\n' + '\n'.join(f'- {k}: {v}' for k, v in S.items() if k != 'checks') + '\n')
        f.write('- đối chiếu: ' + ', '.join(f'{k}={v}' for k, v in checks.items()) + '\n')
    print(json.dumps(S, ensure_ascii=False))
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == '__main__':
    main()
