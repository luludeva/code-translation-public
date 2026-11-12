#!/usr/bin/env python3
"""Điều kiện 3 của luật xác nhận UB ngầm (decision-log 2026-10-20 "Phễu §3.2") cho 3 cặp executable "output khác"
(gpt-5.4 và kimi trên generic_foreach; gemini trên pointer_comparison_ascii_art). Bản executable của
experiments/06-library-census/scripts/ub_cond3.py, cùng ma trận:
  ASLR bật / tắt (`setarch <arch> -R`) × MALLOC_PERTURB_ không đặt / khác 0 × allocator glibc / jemalloc (LD_PRELOAD), mỗi ô REPS lần.
Cùng binary C (build một lần, ghi sha256), cùng vector, cùng thư mục làm việc. Chạy qua cando_binrunner `bin` như census;
runner fork binary C nên môi trường và personality truyền xuống. Hàm quan sát: kết quả runner từng vector và phần diff khi
không Pass (runner so stdout và exit code với kỳ vọng). Cấu hình không ra report ghi `run_error`, không là bằng chứng.
Chỉ chạy phía C; không chạy bản Rust. Việc xếp nhóm theo ba điều kiện do Le duyệt sau."""
import collections, glob, hashlib, itertools, json, os, platform, subprocess

CORPUS = os.environ.get('CORPUS', os.path.expanduser('~/corpus'))
B, OUT = os.environ['B'], os.environ['OUT']
RUNNER = os.environ.get('RUNNER', f'{CORPUS}/cando2/target/release/cando_binrunner')
CASES = [('B02_synthetic', 'generic_foreach'), ('B02_synthetic', 'pointer_comparison_ascii_art')]
REPS, TO = int(os.environ.get('REPS', '3')), int(os.environ.get('TO', '120'))
PERTURB = os.environ.get('PERTURB_VALUE', '165')


def sh(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return p.returncode, (p.stdout + p.stderr)[-3000:]


def jemalloc_path():
    c = sorted(glob.glob('/usr/lib/x86_64-linux-gnu/libjemalloc.so*'))
    return c[0] if c else None


def build_c(b, tc):
    troot = f'{CORPUS}/tractor/Public-Tests/{b}/{tc}'; cb = f'{B}/c/{b}/{tc}'
    if not os.path.exists(f'{cb}/driver'):
        rc1, l1 = sh(['cmake', '-S', f'{troot}/test_case', '-B', cb, '-G', 'Ninja', '-DCMAKE_C_COMPILER=clang'])
        rc2, l2 = sh(['cmake', '--build', cb]) if rc1 == 0 else (rc1, '')
        if rc1 or rc2: return None, troot, (l1 + l2)[-1500:]
    return f'{cb}/driver', troot, ''


def run(drv, troot, tc, cell, k, jem):
    tag = f'aslr-{cell[0]}.perturb-{cell[1]}.{cell[2]}.rep{k}'
    rep = f'{OUT}/reports/{tc}/{tag}.json'; os.makedirs(os.path.dirname(rep), exist_ok=True)
    if os.path.exists(rep): os.remove(rep)
    cmd = [RUNNER, '-l', 'quiet', '-t', troot, '--timeout', str(TO), '-o', rep, 'bin', '-n', drv]
    if cell[0] == 'off': cmd = ['setarch', platform.machine(), '-R'] + cmd
    env = dict(os.environ); env.pop('MALLOC_PERTURB_', None); env.pop('LD_PRELOAD', None)
    if cell[1] != 'unset': env['MALLOC_PERTURB_'] = cell[1]
    rec = dict(case=tc, cell=tag, aslr=cell[0], malloc_perturb=cell[1], allocator=cell[2], rep=k, cmd=cmd)
    if cell[2] == 'jemalloc':
        if not jem: rec['run_error'] = 'không tìm thấy libjemalloc'; return rec
        env['LD_PRELOAD'] = jem
    rec['env'] = {x: env[x] for x in ('MALLOC_PERTURB_', 'LD_PRELOAD') if x in env}
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=TO * 400)
        rec.update(runner_rc=p.returncode, runner_out=(p.stdout + p.stderr)[-800:])
    except subprocess.TimeoutExpired:
        rec.update(runner_rc=None, runner_out='runner process timeout')
    if not os.path.exists(rep):
        rec['run_error'] = 'runner không ra report'; return rec
    d = json.load(open(rep))
    rec['results'] = {v: d[v]['result'] for v in sorted(d)}
    rec['diffs'] = {v: str(d[v].get('diff', ''))[:1500] for v in sorted(d) if d[v]['result'] not in ('Pass', 'Skip')}
    return rec


def main():
    os.makedirs(OUT, exist_ok=True)
    jem = jemalloc_path()
    sa = ['setarch', platform.machine(), '-R']
    chk = {'randomize_va_space': open('/proc/sys/kernel/randomize_va_space').read().strip(), 'jemalloc_path': jem}
    for name, pre, extra in [('aslr_on_1', [], {}), ('aslr_on_2', [], {}), ('aslr_off_1', sa, {}), ('aslr_off_2', sa, {}),
                             ('jemalloc', [], {'LD_PRELOAD': jem or ''})]:
        chk[name] = sh(pre + ['sh', '-c', 'grep -E "\\[heap\\]|\\[stack\\]|jemalloc" /proc/self/maps'], env=dict(os.environ, **extra))[1]
    json.dump(chk, open(f'{OUT}/env-checks.json', 'w'), ensure_ascii=False, indent=1)
    cells = list(itertools.product(['on', 'off'], ['unset', PERTURB], ['glibc', 'jemalloc']))
    if os.environ.get('SMOKE'): cells = cells[:1]     # thử script: 1 ô không cho biết gì về biến thiên giữa các ô
    summary = []
    with open(f'{OUT}/ub-cond3-exe.jsonl', 'w') as f:
        for b, tc in CASES:
            drv, troot, err = build_c(b, tc)
            meta = dict(case=tc, build_ok=drv is not None, build_log=err,
                        driver_sha256=hashlib.sha256(open(drv, 'rb').read()).hexdigest() if drv else None)
            f.write(json.dumps(dict(meta=meta), ensure_ascii=False) + '\n'); f.flush(); print(meta, flush=True)
            if not drv: continue
            recs = []
            for cell in cells:
                for k in range(REPS):
                    r = run(drv, troot, tc, cell, k, jem); recs.append(r)
                    f.write(json.dumps(r, ensure_ascii=False) + '\n'); f.flush()
                    print(tc, r['cell'], collections.Counter((r.get('results') or {}).values()), r.get('run_error', ''), flush=True)
            ok = [r for r in recs if 'run_error' not in r]
            vecs = sorted({v for r in ok for v in r['results']})
            varying = {}
            for v in vecs:
                obs = collections.defaultdict(list)
                for r in ok: obs[json.dumps([r['results'].get(v), r['diffs'].get(v)])].append(r['cell'])
                if len(obs) > 1: varying[v] = {o: sorted(c) for o, c in obs.items()}
            summary.append(dict(case=tc, runs=len(recs), run_errors=len(recs) - len(ok), vectors=len(vecs),
                                vectors_not_pass_any=sorted({v for r in ok for v, x in r['results'].items() if x not in ('Pass', 'Skip')}),
                                varying_vectors=varying))
    json.dump(summary, open(f'{OUT}/summary.json', 'w'), ensure_ascii=False, indent=1)
    with open(f'{OUT}/summary.txt', 'w') as g:
        g.write('Điều kiện 3 (executable), sơ bộ, chưa kiểm tay. Vector biến thiên = (result, diff) đổi giữa các lần chạy phía C.\n')
        for s in summary:
            g.write(f"{s['case']}: {s['runs']} lần, {s['run_errors']} lỗi chạy, {s['vectors']} vector, "
                    f"{len(s['vectors_not_pass_any'])} vector có lần không Pass, {len(s['varying_vectors'])} vector biến thiên\n")
            for v, o in s['varying_vectors'].items():
                g.write(f'  {v}: ' + ' | '.join(f'{k[:200]} @ {len(c)} lần' for k, c in o.items()) + '\n')


if __name__ == '__main__':
    main()
