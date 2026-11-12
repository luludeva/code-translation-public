#!/usr/bin/env python3
"""exp 36: ba kiểm tra SAU KHI có kết quả held-out (ngoài protocol README, không đổi số chính k/11, k/6). Sơ bộ, chưa kiểm tay.
  (1) độ bền: chỉ seed có bản ghi 'done' (bỏ seed harness_error) và bỏ divergence chỉ khác ở stderr;
  (2) đối chứng: các hệ P_rep (evaluation gốc chấm đỗ) trên cùng case và cùng input, lấy từ lượt đầu bị bỏ (run_local.sh, không commit);
  (3) tu_linkage: gpt-5.4 và gemini-3.1-pro-preview cho cùng tập divergence; build lại độc lập hai crate từ corpus, chạy lại input mẫu.
  python3 experiments/36-heldout/scripts/posthoc_checks.py PLAN OUT OUT_V1 CORPUS SCRATCH > results/posthoc-checks.txt"""
import base64, gzip, json, os, random, subprocess, sys

sys.path.insert(0, os.getcwd())
from harness import metrics as HM  # noqa: E402

GEN = lambda d: HM.retained(d) and d.get('source') not in ('seed', 'vector')
dec = lambda b: gzip.decompress(base64.b64decode(b['gz64'])) if isinstance(b, dict) else (b.encode() if isinstance(b, str) else b'')


def robust(P, out):
    print('## (1) độ bền: seed done, bỏ divergence chỉ ở stderr')
    k = 0
    for u in P['units']:
        cases, divs, _ = HM.load_rq1(f"{out}/{u['unit']}", u['kind'])
        done = sorted(r['seed'] for r in cases if r['status'] == 'done')
        err = sorted(r['seed'] for r in cases if r['status'] != 'done')
        for s in u['systems']:
            g = [d for sd in done for d in divs.get((u['bundle'], u['case'], s, sd), []) if GEN(d)]
            ns = [d for d in g if d.get('channels') != ['stderr']]
            per = {sd: sum(1 for d in ns if d['seed'] == sd) for sd in done}
            k += bool(ns)
            print(f"{u['unit']} {s} seed_done={done} seed_khac={err} gen_retained={len(g)} khong_chi_stderr={len(ns)} theo_seed={per}")
    print(f'phat_hien_ban_ben={k}/{sum(len(u["systems"]) for u in P["units"])}')


def control(P, v1):
    print('## (2) đối chứng: hệ P_rep trên cùng case, cùng input (lượt đầu bị bỏ)')
    for u in P['units']:
        cases, divs, _ = HM.load_rq1(f"{v1}/{u['unit']}", u['kind'])
        st = {r['seed']: r['status'] for r in cases}
        ps = sorted({s for r in cases for s in (r.get('pair_status') or {})})
        c = {s: sum(1 for sd in (0, 1, 2) for d in divs.get((u['bundle'], u['case'], s, sd), []) if GEN(d)) for s in ps}
        print(f"{u['unit']} {u['bundle']}/{u['case']} seed={st} gen_retained_P_rep={c}")


def tu_linkage(P, out, corpus, scratch, n=8):
    print('## (3) tu_linkage: build lại độc lập, chạy lại input mẫu')
    u = next(x for x in P['units'] if x['case'] == 'tu_linkage'); a, b = u['systems']
    cases, divs, _ = HM.load_rq1(f"{out}/{u['unit']}", u['kind'])
    obs = lambda s: {(d['seed'], d['idx']): (d['r_out'], d['r_err'], d['r_rc'], d['r_status']) for (_, _, x, _), v in divs.items() if x == s for d in v}
    A, B = obs(a), obs(b)
    print(f'{a}={len(A)} {b}={len(B)} cung_khoa={A.keys() == B.keys()} quan_sat_Rust_trung={sum(A[x] == B.get(x) for x in A)}')
    bins = {}
    for s in (a, b):
        src = f"{corpus}/harvest/Test-Corpus/{s}/{u['bundle']}/{u['case']}/translated"; dst = f'{scratch}/{s}'
        subprocess.run(['cp', '-r', src, dst], check=True)
        subprocess.run(['cargo', 'build', '-q', '--release'], cwd=dst, check=True, env=dict(os.environ, RUSTUP_TOOLCHAIN='stable'))
        bins[s] = f'{dst}/target/release/driver'
    random.seed(1)
    for d in random.sample([d for (_, _, x, _), v in divs.items() if x == a for d in v], n):
        argv = [dec(x) for x in d['argv']]; stdin = dec(d.get('stdin'))
        o = [subprocess.run([bins[s]] + argv, input=stdin, capture_output=True, timeout=10) for s in (a, b)]
        same = (o[0].stdout, o[0].stderr, o[0].returncode) == (o[1].stdout, o[1].stderr, o[1].returncode)
        rec = o[0].stdout == dec(d['r_out']) and o[0].stderr == dec(d['r_err'])
        print(f"seed={d['seed']} idx={d['idx']} channels={d['channels']} hai_ban_giong={same} khop_ban_ghi={rec}")


if __name__ == '__main__':
    plan, out, v1, corpus, scratch = sys.argv[1:6]
    P = json.load(open(plan))
    print('# exp 36 kiểm tra sau kết quả (ngoài protocol; sơ bộ, chưa kiểm tay)')
    robust(P, out); control(P, v1); tu_linkage(P, out, corpus, scratch)
