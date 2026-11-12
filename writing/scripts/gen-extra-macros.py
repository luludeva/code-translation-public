#!/usr/bin/env python3
"""Sinh writing/generated/extra-numbers.tex: các số Chương 3, 4 còn chờ macro (brief kỹ thuật 2026-11-10, MR-16; ô \\TODOnum).
Cùng quy ước với gen-robust-macros.py: \\rqSet{<tên>}{<giá trị>}, tỉ lệ có Num, Den, Pct (một chữ số thập phân), cận Wilson 95% có Lo,
Hi (phần trăm). Thiếu nguồn thì ??. Không sửa tay file sinh ra. Mọi số ở đây: Le chấp nhận không kiểm tay ngày 2026-11-12.

Họ macro và nguồn (file đã commit):
  - rqHeldOut*: held-out (exp 36, post hoc về thời điểm chạy). Số chính k/n và số phụ k/6 từ results/heldout-result.json (protocol
    README); seed mất do harness_error, độ bền (chỉ seed 'done', bỏ divergence chỉ ở stderr) và tỉ lệ trần (divergence giữ lại trên
    input sinh chia số input, chỉ seed 'done') từ results/per-seed.json. Kiểm chéo: số chính tính lại từ per-seed.json phải trùng
    heldout-result.json, lệch thì ??.
  - rqLibGap*: khe hở output của lời gọi library thất bại (exp 30, results/lib-fail-output-gap.json; cận trên, chưa trừ input UB).
  - pReproTimeoutFullSec, pReproRecheckReps: luật chạy lại khi tái lập (harness/census.py, experiments/02-harvest-repro/scripts/
    census.py, recheck_timeouts.py); mọi chỗ đọc phải cùng giá trị, lệch thì ??.
Dùng: python3 writing/scripts/gen-extra-macros.py [--out writing/generated/extra-numbers.tex]"""
import argparse, json, math, os, re, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = f'{ROOT}/writing/generated/extra-numbers.tex'
E36 = f'{ROOT}/experiments/36-heldout/results'
GAP = f'{ROOT}/experiments/30-main-s0/results/lib-fail-output-gap.json'
KIND = dict(exe='Exe', lib='Lib')


def load(p):
    try:
        with open(p) as f: return json.load(f)
    except (OSError, ValueError): return None


def pct(n, d): return '??' if n is None or d is None else ('n/a' if d == 0 else f'{100 * n / d:.1f}')


def wilson(k, n, z=1.96):
    if k is None or not n: return None, None
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return f'{100 * max(0.0, (c - h) / d):.1f}', f'{100 * min(1.0, (c + h) / d):.1f}'


def read_const(rel, pattern):
    try: t = open(f'{ROOT}/{rel}').read()
    except OSError: return [None]
    v = re.findall(pattern, t, re.M)
    return [int(x) for x in v] or [None]


def same(vals): return vals[0] if vals and None not in vals and len(set(vals)) == 1 else None


def heldout(put, rate):
    res, ps = load(f'{E36}/heldout-result.json'), load(f'{E36}/per-seed.json')
    rows = (ps or {}).get('rows') or []
    tr = {}
    for r in rows: tr.setdefault((r['unit'], r['system']), []).append(r)
    # số chính tính lại: phát hiện khi có divergence giữ lại trên input sinh ở bất kỳ seed nào (như evaluate.py)
    det = {k: any(r['gen_retained'] > 0 for r in v) for k, v in tr.items()}
    kind = {k: v[0]['kind'] for k, v in tr.items()}
    prim = (res or {}).get('primary') or {}
    for scope, tok in (('all', 'All'), ('exe', 'Exe'), ('lib', 'Lib')):
        p = prim.get(scope) or {}
        keys = [k for k in tr if scope == 'all' or kind[k] == scope]
        k_re, n_re = sum(det[k] for k in keys), len(keys)
        ok = res is not None and (p.get('k'), p.get('n')) == (k_re, n_re)
        k, n = (p.get('k'), p.get('n')) if ok else (None, None)
        rate(f'rqHeldOut{tok}', k, n)
        lo, hi = wilson(k, n); put(f'rqHeldOut{tok}Lo', lo); put(f'rqHeldOut{tok}Hi', hi)
    s = (res or {}).get('secondary_with_remaining_vectors') or {}
    rate('rqHeldOutKeptVec', s.get('k'), s.get('n'))
    lo, hi = wilson(s.get('k'), s.get('n')); put('rqHeldOutKeptVecLo', lo); put('rqHeldOutKeptVecHi', hi)
    units = sorted({r['unit'] for r in rows})
    put('rqHeldOutUnitsNum', len(units) if rows else None)
    for kd, tok in KIND.items():
        lost = {(r['unit'], r['seed']) for r in rows if r['kind'] == kd and r['status'] != 'done'}
        put(f'rqHeldOutSeedsLost{tok}Num', len(lost) if rows else None)
        put(f'rqHeldOutSeedsLostTrans{tok}Num', len({k for k in tr if kind[k] == kd and any(r['status'] != 'done' for r in tr[k])})
            if rows else None)
    # độ bền: chỉ seed done, bỏ divergence chỉ ở stderr; "mọi seed": phát hiện ở từng seed done
    rob = [k for k, v in tr.items() if any(r['status'] == 'done' and r['gen_retained_not_stderr_only'] > 0 for r in v)]
    every = [k for k, v in tr.items() if all(r['gen_retained_not_stderr_only'] > 0 for r in v if r['status'] == 'done')
             and any(r['status'] == 'done' for r in v)]
    rate('rqHeldOutRobustAll', len(rob) if rows else None, len(tr) if rows else None)
    rate('rqHeldOutEverySeedAll', len(every) if rows else None, len(tr) if rows else None)
    # tỉ lệ trần: theo bản dịch, divergence giữ lại trên input sinh / số input, chỉ seed done; báo nhỏ nhất, lớn nhất theo loại
    for kd, tok in KIND.items():
        sh = []
        for k, v in tr.items():
            if kind[k] != kd: continue
            d = [r for r in v if r['status'] == 'done']
            n = sum(r['n_inputs'] or 0 for r in d)
            if n: sh.append(sum(r['gen_retained'] for r in d) / n)
        put(f'rqHeldOutDivShareLo{tok}Pct', f'{100 * min(sh):.1f}' if sh else None)
        put(f'rqHeldOutDivShareHi{tok}Pct', f'{100 * max(sh):.1f}' if sh else None)


def libgap(put, rate):
    g = load(GAP); r1 = (g or {}).get('rq1') or {}
    up = r1.get('matched_both_fail_upper')
    rate('rqLibGapUpperLib', None if up is None else sum(up.values()), r1.get('match'))
    for x, tok in (('SegmentationFault', 'Segv'), ('UnknownFailure', 'Unknown'), ('Panic', 'Panic')):
        put(f'rqLibGap{tok}LibNum', None if up is None else up.get(x, 0))
    rq2 = None if g is None else g.get('rq2')
    put('rqLibGapRQTwoVecLibNum', None if rq2 is None else sum(v for v in rq2.values() if isinstance(v, int)))


def repro(put):
    to = (read_const('harness/census.py', r'^TIMEOUT, TIMEOUT_FULL = \d+, (\d+)') + read_const('harness/census.py', r'^REPS, TO = \d+, (\d+)')
          + read_const('experiments/02-harvest-repro/scripts/census.py', r'^TIMEOUT_FULL = (\d+)')
          + read_const('experiments/02-harvest-repro/scripts/recheck_timeouts.py', r"os\.environ\.get\('TO', '(\d+)'\)"))
    reps = (read_const('harness/census.py', r'^REPS, TO = (\d+), \d+')
            + read_const('experiments/02-harvest-repro/scripts/recheck_timeouts.py', r"os\.environ\.get\('REPS', '(\d+)'\)"))
    put('pReproTimeoutFullSec', same(to)); put('pReproRecheckReps', same(reps))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=OUT); a = ap.parse_args()
    M = []

    def put(name, v): M.append((name, '??' if v is None else v))

    def rate(name, n, d): put(f'{name}Num', n); put(f'{name}Den', d); put(f'{name}Pct', pct(n, d))

    heldout(put, rate); libgap(put, rate); repro(put)
    bad = [x for x, _ in M if not re.fullmatch(r'[A-Za-z]+', x)]
    if bad: raise SystemExit(f'tên macro không hợp lệ: {bad}')
    rev = subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() or '?'
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w') as f:
        f.write('% SINH TU DONG boi writing/scripts/gen-extra-macros.py. KHONG SUA TAY.\n')
        f.write(f'% Repo commit: {rev}. Nguon: experiments/36-heldout/results/{{heldout-result,per-seed}}.json, '
                'experiments/30-main-s0/results/lib-fail-output-gap.json, hang so harness/census.py va exp 02. Le chap nhan khong kiem tay 2026-11-12.\n')
        f.write('\\providecommand{\\rqSet}[2]{\\expandafter\\def\\csname #1\\endcsname{#2}}\n')
        for x, v in M: f.write(f'\\rqSet{{{x}}}{{{v}}}\n')
    print(f'Đã ghi {a.out}: {len(M)} macro, {sum(v == "??" for _, v in M)} ??')


if __name__ == '__main__':
    main()
