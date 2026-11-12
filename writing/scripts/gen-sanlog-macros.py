#!/usr/bin/env python3
"""Sinh writing/generated/sanlog-numbers.tex: số của B0 (job rq2-san-log, exp 37), lượt bổ sung C-san dừng ở B0 nhánh (c) ngày
2026-11-08. Nguồn: experiments/37-rq2-san-supp/results/b0/b0-markers.json (sinh bằng scripts/b0_extract.py từ marker đã nộp).
Cùng quy ước với gen-sanbound-macros.py: \\rqSet{<tên>}{<giá trị>}, số đếm có hậu tố Num, tỉ lệ có Num, Den. Thiếu nguồn hoặc kiểm đối
chiếu hỏng thì ??. Không sửa tay file sinh ra. Họ \\rqSanSupp* (sansupp-numbers.tex) không được sinh vì lượt đã dừng.
Dùng: python3 writing/scripts/gen-sanlog-macros.py [--in ...b0-markers.json] [--out writing/generated/sanlog-numbers.tex]"""
import argparse, hashlib, json, os, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
IN = f'{ROOT}/experiments/37-rq2-san-supp/results/b0/b0-markers.json'
OUT = f'{ROOT}/writing/generated/sanlog-numbers.tex'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--in', dest='src', default=IN); ap.add_argument('--out', default=OUT); a = ap.parse_args()
    try:
        raw = open(a.src, 'rb').read(); S = json.loads(raw)['summary']; sha = hashlib.sha256(raw).hexdigest()
        ok = all(S['checks'].values())
    except (OSError, ValueError, KeyError):
        S, sha, ok = {}, '?', False
    g = (lambda k: S.get(k)) if ok else (lambda k: None)
    M = [('rqSanLogMarkerNum', g('markers_san')), ('rqSanLogSanFailNum', g('san_ok_false')), ('rqSanLogCOkNum', g('c_ok_true')),
         ('rqSanLogSigNum', g('sig')), ('rqSanLogSigDen', g('target_cases')),
         ('rqSanLogLibNum', g('sig_lib')), ('rqSanLogLibDen', g('target_cases')),
         ('rqSanLogLibMissNum', g('sig_no_lib')), ('rqSanLogLibMissDetNum', g('sig_no_lib_det_only')), ('rqSanLogNinjaStopNum', g('ninja_stopped')),
         ('rqSanLogCapChars', g('log_cap'))]
    try:
        head = subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() or '?'
    except OSError:
        head = '?'
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write('% SINH TU DONG boi writing/scripts/gen-sanlog-macros.py. KHONG SUA TAY.\n')
        f.write(f"% Repo commit: {head}. Nguon: experiments/37-rq2-san-supp/results/b0/b0-markers.json (sha256 {sha}); "
                f"results/rq2-san-log {S.get('ref', '?')}. B0 exp 37, post hoc, dung o nhanh (c).\n")
        f.write('\\providecommand{\\rqSet}[2]{\\expandafter\\def\\csname #1\\endcsname{#2}}\n')
        for n, v in M:
            f.write(f"\\rqSet{{{n}}}{{{'??' if v is None else v}}}\n")
    print(f'{len(M)} macro, {sum(v is None for _, v in M)} ??')


if __name__ == '__main__':
    main()
