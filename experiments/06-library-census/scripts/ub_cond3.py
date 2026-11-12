#!/usr/bin/env python3
"""Điều kiện 3 của luật xác nhận UB ngầm (decision-log 2026-10-20 "Phễu §3.2"), đăng ký trước khi chạy.

Cùng binary C (một lần build .so), cùng vector, cùng thư mục làm việc, cùng hàm quan sát; chạy phía C qua runner TRACTOR
dưới ma trận môi trường bộ nhớ:
  ASLR bật / tắt (`setarch <arch> -R`) × MALLOC_PERTURB_ không đặt / khác 0 × allocator glibc / jemalloc (LD_PRELOAD),
  mỗi ô REPS lần. Ghi stdout, exit status, timeout, stderr, lệnh và cấu hình.
Hàm quan sát: state_out và stdout của vector (qua chế độ CANDO2_STATE_DUMP, như exp 05). stderr ghi lại, không tính.
Cấu hình không chạy được (runner không ra report) ghi `run_error`, không là bằng chứng.
Runner chạy mỗi vector trong tiến trình con (procspawn); môi trường và personality của setarch truyền xuống tiến trình con.
Script chỉ ghi dữ liệu và một bảng tóm tắt khác biệt; việc xếp nhóm theo luật ba điều kiện do Le duyệt sau."""
import glob, hashlib, itertools, json, os, platform, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import census_lib as CL   # noqa: E402

CASES = [('B02_synthetic', 'betagamma_lib')]
REPS, TO = int(os.environ.get('REPS', '3')), int(os.environ.get('TO', '120'))
PERTURB = os.environ.get('PERTURB_VALUE', '165')          # 0xA5, khác 0
OUT, B, T = CL.OUT, CL.B, CL.T


def jemalloc_path():
    c = sorted(glob.glob('/usr/lib/x86_64-linux-gnu/libjemalloc.so*') + glob.glob('/usr/lib/libjemalloc.so*'))
    return c[0] if c else None


def cells(jem):
    for aslr, pert, alloc in itertools.product(['on', 'off'], ['unset', PERTURB], ['glibc', 'jemalloc']):
        yield dict(aslr=aslr, malloc_perturb=pert, allocator=alloc, jemalloc=jem if alloc == 'jemalloc' else None)


def run(info, vec, cell, k):
    tc = info['case']; root = f'{B}/roots/C/{info["bundle"]}/{tc}'
    tag = f'aslr-{cell["aslr"]}.perturb-{cell["malloc_perturb"]}.{cell["allocator"]}.rep{k}'
    d = f'{OUT}/runs/{tc}/{os.path.basename(vec)}'; os.makedirs(d, exist_ok=True)
    rep, dump = f'{d}/{tag}.report.json', f'{d}/{tag}.dump'
    for f in (rep, dump):
        if os.path.exists(f): os.remove(f)
    cmd = [info['runner_bin'], '--log-level', 'quiet', '--test-root-dir', root, '--timeout', str(TO),
           '--vectors', vec, '--output', rep, 'lib']
    if cell['aslr'] == 'off': cmd = ['setarch', platform.machine(), '-R'] + cmd
    env = dict(os.environ, CANDO2_STATE_DUMP=dump); env.pop('MALLOC_PERTURB_', None); env.pop('LD_PRELOAD', None)
    if cell['malloc_perturb'] != 'unset': env['MALLOC_PERTURB_'] = cell['malloc_perturb']
    if cell['allocator'] == 'jemalloc':
        if not cell['jemalloc']: return dict(cell=tag, cmd=cmd, run_error='không tìm thấy libjemalloc')
        env['LD_PRELOAD'] = cell['jemalloc']
    rec = dict(case=tc, vector=os.path.basename(vec), cell=tag, aslr=cell['aslr'], malloc_perturb=cell['malloc_perturb'],
               allocator=cell['allocator'], rep=k, cmd=cmd,
               env={x: env[x] for x in ('MALLOC_PERTURB_', 'LD_PRELOAD') if x in env})
    try:
        p = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=TO * 6)
        rec.update(runner_rc=p.returncode, runner_out=(p.stdout + p.stderr)[-800:])
    except subprocess.TimeoutExpired:
        rec.update(runner_rc=None, runner_out='runner process timeout')
    if not os.path.exists(rep):
        rec['run_error'] = 'runner không ra report'; return rec
    r = list(json.load(open(rep)).values())[0]
    rec['result'] = r.get('result') if isinstance(r, dict) else str(r)
    lines = [json.loads(l) for l in open(dump) if l.strip()] if os.path.exists(dump) else []
    if lines:
        rec.update(state_out=lines[-1]['state_out'], stdout=lines[-1]['stdout'], stderr=lines[-1]['stderr'][:1500])
    else:
        rec['no_state_dump'] = True      # vd Timeout hoặc crash trước khi so state
    return rec


def env_checks(jem):
    """Kiểm cơ chế của ma trận trên tiến trình thường: setarch -R có tắt ASLR không, LD_PRELOAD có nạp jemalloc không."""
    def maps(pre, extra=None):
        e = dict(os.environ, **(extra or {}))
        try:
            return subprocess.run(pre + ['sh', '-c', 'grep -E "\\[heap\\]|\\[stack\\]|jemalloc" /proc/self/maps'],
                                  env=e, capture_output=True, text=True, timeout=30)
        except Exception as ex:
            return ex
    sa = ['setarch', platform.machine(), '-R']
    res = {'randomize_va_space': open('/proc/sys/kernel/randomize_va_space').read().strip(), 'jemalloc_path': jem}
    for name, pre, extra in [('aslr_on_1', [], None), ('aslr_on_2', [], None), ('aslr_off_1', sa, None), ('aslr_off_2', sa, None),
                             ('jemalloc', [], {'LD_PRELOAD': jem or ''})]:
        p = maps(pre, extra)
        res[name] = (p.stdout + p.stderr) if hasattr(p, 'stdout') else f'lỗi: {p}'
    return res


def obs(r):
    return json.dumps([r.get('result'), r.get('state_out'), r.get('stdout')], sort_keys=True)


def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(B, exist_ok=True)
    CL.S.B = B; CL.S.setup_cando2()
    jem = jemalloc_path()
    json.dump(env_checks(jem), open(f'{OUT}/env-checks.json', 'w'), ensure_ascii=False, indent=1)
    allrecs, summary = [], []
    with open(f'{OUT}/ub-cond3.jsonl', 'w') as f:
        for b, tc in CASES:
            info = CL.prepare_case(b, tc)
            so = f'{B}/c/{b}/{tc}/lib{info["library"]}.so'
            meta = dict(case=tc, runner_ok=info['runner_ok'], c_so=info['c_so'], c_results_census_style=info.get('c_results'),
                        so_sha256=hashlib.sha256(open(so, 'rb').read()).hexdigest() if info['c_so'] else None)
            f.write(json.dumps(dict(meta=meta), ensure_ascii=False) + '\n'); f.flush(); print(meta, flush=True)
            if not (info['runner_ok'] and info['c_so']): continue
            for vec in sorted(glob.glob(f'{T}/{b}/{tc}/test_vectors/*.json'), key=lambda p: int(os.path.basename(p).split('.')[0])):
                recs = []
                for cell in cells(jem):
                    for k in range(REPS):
                        r = run(info, vec, cell, k); recs.append(r)
                        f.write(json.dumps(r, ensure_ascii=False) + '\n'); f.flush()
                ok = [r for r in recs if 'run_error' not in r]
                by = {}
                for r in ok: by.setdefault(obs(r), []).append(r['cell'])
                summary.append(dict(case=tc, vector=os.path.basename(vec), runs=len(recs), run_errors=len(recs) - len(ok),
                                    distinct_observations=len(by), observations={o: sorted(c) for o, c in by.items()}))
                print(tc, os.path.basename(vec), 'runs', len(recs), 'errors', len(recs) - len(ok), 'distinct', len(by), flush=True)
    json.dump(summary, open(f'{OUT}/summary.json', 'w'), ensure_ascii=False, indent=1)
    with open(f'{OUT}/summary.txt', 'w') as g:
        g.write('Điều kiện 3, sơ bộ, chưa kiểm tay. distinct_observations > 1 nghĩa là (result, state_out, stdout) đổi giữa các lần chạy.\n')
        for s in summary:
            g.write(f"{s['case']} vector {s['vector']}: {s['runs']} lần, {s['run_errors']} lỗi chạy, {s['distinct_observations']} quan sát khác nhau\n")
            for o, cs in s['observations'].items():
                g.write(f"  {o}\n    ô: {', '.join(sorted(set(c.rsplit('.rep', 1)[0] for c in cs)))} ({len(cs)} lần)\n")


if __name__ == '__main__':
    main()
