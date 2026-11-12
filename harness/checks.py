"""Bộ kiểm chặn trước lượt chính (harness-design.md mục 7.1).

V5: replay vector gốc trên mọi cặp P_rep qua O(p, x). Đạt khi mọi cặp khớp C trên mọi vector; mỗi ca lệch phải được giải thích
    trước lượt chính (lỗi harness, hoặc cách so của TRACTOR lỏng hơn, vd regex stdout, không so stderr).
V6: negative control C với C theo case: 30 input x 5 lần trên mọi case của lượt chính. Đạt khi 0 input không ổn định.
    Input executable: tầng MS v2 seed 0 (như nghiệm thu v2); library: StateGen v2 seed 0. Không chạm bản Rust."""
import json, os, traceback

from . import build as BD
from . import observe as OB
from .config import T, TIMEOUT_RERUN_FACTOR
from .gen import cdict, stategen_v2
from .gen.libtypes import parse_runner
from .gen.v2_exe import gen_inputs_v2
from .record import obs_exe
from .vectors import exe_seeds, lib_seeds

V6_INPUTS, V6_REPS = 30, 5


def _cdict(B, bundle, case):
    try:
        return cdict.extract(f'{T}/{bundle}/{case}', f'{B}/cdict/{bundle}/{case}'), None
    except Exception as e:
        return dict(values=[], strings=[], n_files=0), f'cdict lỗi: {e}'[:500]


# ---------------- V6 ----------------
def _exe_timeout(bundle, case, timeout):
    """Timeout theo case như RQ1 (decision-log 2026-10-25 "Timeout theo case cho các kiểm và RQ2"; cài 2026-10-26): max(timeout gốc,
    ceil(C_TIME_FACTOR x thời gian C lớn nhất)). Chỉ executable; library giữ timeout truyền vào."""
    from .rq1 import case_timeout          # nhập trễ: rq1 nhập checks
    return case_timeout(bundle, case, timeout)


def v6_exe_case(B, bundle, case, timeout):
    base, timeout = timeout, _exe_timeout(bundle, case, timeout)
    rec = dict(key=f'{bundle}/{case}', check='V6', kind='exe', bundle=bundle, case=case, timeout=timeout, timeout_base=base)
    c = BD.build_c_exe(B, bundle, case)
    rec['c_build'] = {k: c.get(k) for k in ('ok', 'preset', 'sha256', 'log')}
    if not c['ok']: rec['status'] = 'c_build_failed'; return rec
    seeds = exe_seeds(f'{T}/{bundle}/{case}')
    if not seeds: rec['status'] = 'no_seed_vectors'; return rec
    cd, err = _cdict(B, bundle, case); rec['cdict_error'] = err
    ins = gen_inputs_v2(seeds, 'MS', V6_INPUTS, 0, cd)
    rec.update(n_inputs=len(ins), reps=V6_REPS, unstable=[])
    cs = None                              # build C-san chỉ khi có input không ổn định đầu tiên
    for i, (argv, stdin, src) in enumerate(ins):
        runs = [OB.run_exe(c['bin'], argv, stdin, timeout) for _ in range(V6_REPS)]
        if not all(OB.equal_exe(runs[0], r) for r in runs[1:]):
            if cs is None:
                cs = BD.build_c_exe(B, bundle, case, san=True)
                rec['c_san_build'] = {k: cs.get(k) for k in ('ok', 'preset', 'sha256', 'log')}
            rec['unstable'].append(dict(idx=i, source=src, argv=argv, stdin=stdin[-4000:], runs=[obs_exe(r) for r in runs],
                                        c_san=_v6_san_exe(cs, argv, stdin, timeout, runs)))
    rec['n_unstable'] = len(rec['unstable']); rec['c_san_counts'] = _san_counts(rec['unstable']); rec['status'] = 'done'
    return rec


# C-san trên input không ổn định (Le chọn 26/10; exp 28 câu hỏi 2): mỗi input không ổn định chạy C-san một lần qua đúng hàm của RQ1
# (rq1._exe_san, rq1.lib_san: cùng cờ, cùng env sanitizer, timeout gấp SAN_TIMEOUT_FACTOR trên timeout của case, cùng classify_san và
# luật thử lại khi 'infra'), để bằng chứng mã C-UB của V6 lấy trên cùng máy, cùng commit đo. Input ổn định không chạy thêm gì; phép kiểm
# ổn định, số lần chạy, input và timeout không đổi. Trường `c_san` của mỗi input không ổn định: dict trả về của hàm RQ1 (status, markers,
# attempts, cùng san_run_status, err_tail ở executable hoặc san_result, san_k1 ở library); ngoại lệ ghi status 'error' để không mất bản
# ghi ổn định của case. c_status (exe) và c_obs (lib) cho classify_san: một lần chạy C thường có chết nếu có, nếu không thì lần đầu,
# vì RQ1 chỉ có một quan sát C còn V6 có V6_REPS quan sát và C-san chết không diagnostic chỉ là 'infra' khi C thường không chết.
def _v6_san_exe(cs, argv, stdin, timeout, runs):
    from .rq1 import _exe_san              # nhập trễ: rq1 nhập checks
    st = 'signal' if any(r['status'] == 'signal' for r in runs) else runs[0]['status']
    try:
        return _exe_san(cs, argv, stdin, timeout, None, st)
    except Exception:
        return dict(status='error', markers=[], attempts=None, error=traceback.format_exc()[-1500:])


def _v6_san_lib(rb, csroot, p, timeout, preload, runs):
    from .rq1 import LIB_CRASH, SAN_TIMEOUT_FACTOR, lib_san   # nhập trễ: rq1 nhập checks
    co = next((r for r in runs if r.get('result') in LIB_CRASH), runs[0])
    try:
        return lib_san(rb, csroot, p, timeout * SAN_TIMEOUT_FACTOR, f'{p}.v6.Csan.dump', preload, co)
    except Exception:
        return dict(status='error', markers=[], attempts=None, error=traceback.format_exc()[-1500:])


def _san_counts(unstable):
    out = {}
    for u in unstable:
        k = (u.get('c_san') or {}).get('status'); out[k] = out.get(k, 0) + 1
    return out


def _lib_inputs(B, info, n, seed, include_vectors=False):
    """Như accept_lib.case_inputs (phần v2): ghi mỗi input thành file vector; giữ stdin, env của seed.
    include_vectors=True (RQ1, sửa 2026-10-23, Le chọn): thêm chính state của các vector (không mang has_ub) làm input, nguồn 'vector',
    như executable luôn chạy chính vector; bộ sinh đã loại các state trùng vector nên không có input trùng."""
    bundle, case = info['bundle'], info['case']
    troot = f'{T}/{bundle}/{case}'
    parsed = parse_runner(open(f'{troot}/runner/src/main.rs').read())
    seeds = lib_seeds(troot)
    states = [s['vec']['lib_state_in'] for s in seeds]
    cd, err = _cdict(B, bundle, case)
    gen = stategen_v2.generate(parsed, states, cd, n, seed)   # không có vector: sinh từ kiểu (decision-log 2026-10-14, Le giữ 25/10)
    vdir = f'{B}/vec/{bundle}/{case}/s{seed}-n{n}'; os.makedirs(vdir, exist_ok=True)
    files = []
    if include_vectors:
        for k, sv in enumerate(seeds):
            v = dict(lib_state_in=sv['vec']['lib_state_in'], lib_state_out={}, note=f'v{k}')
            for f in ('stdin', 'env'):
                if sv['vec'].get(f) is not None: v[f] = sv['vec'][f]
            p = f'{vdir}/v{k}.json'; json.dump(v, open(p, 'w')); files.append((p, 'vector'))
    for k, x in enumerate(gen):
        sv = seeds[x['seed_index']]['vec'] if x['seed_index'] is not None else {}
        v = dict(lib_state_in=x['state'], lib_state_out={}, note=f'i{k}')
        for f in ('stdin', 'env'):
            if sv.get(f) is not None: v[f] = sv[f]
        p = f'{vdir}/i{k}.json'; json.dump(v, open(p, 'w')); files.append((p, x['source']))
    return files, err, len(seeds)


def v6_lib_case(B, bundle, case, timeout):
    rec = dict(key=f'{bundle}/{case}', check='V6', kind='lib', bundle=bundle, case=case)
    info = BD.build_lib_case(B, bundle, case)
    rec['build'] = {k: info.get(k) for k in ('runner_ok', 'c_ok', 'c_sha256', 'preset', 'runner_log', 'c_log')}
    if not (info['runner_ok'] and info['c_ok']): rec['status'] = 'c_build_failed'; return rec
    files, err, nseeds = _lib_inputs(B, info, V6_INPUTS, 0)
    rec.update(cdict_error=err, n_seed_vectors=nseeds, n_inputs=len(files), reps=V6_REPS, unstable=[])
    if not files: rec['status'] = 'no_generated_inputs'; return rec
    root = BD.lib_root(B, info, 'c')
    san = None                             # (csroot, preload), chỉ dựng khi có input không ổn định đầu tiên, như rq1.rq1_lib_case
    for p, src in files:
        runs = [OB.run_lib_retry(info['runner_bin'], root, p, timeout, False, f'{p}.v6.{k}.dump') for k in range(V6_REPS)]
        if not all(OB.equal_lib(runs[0], r) for r in runs[1:]):
            if san is None:
                san = (BD.lib_root(B, info, 'c-san') if info.get('c-san_ok') else None, BD.asan_preload())
                rec['c_san_build_ok'] = bool(info.get('c-san_ok'))
            rec['unstable'].append(dict(input=os.path.basename(p), source=src, runs=runs,
                                        c_san=_v6_san_lib(info['runner_bin'], san[0], p, timeout, san[1], runs)))
    rec['n_unstable'] = len(rec['unstable']); rec['c_san_counts'] = _san_counts(rec['unstable']); rec['status'] = 'done'
    return rec


# ---------------- V5 ----------------
def v5_exe_case(B, bundle, case, pairs, timeout):
    """pairs: các dòng P_rep của case. Trả về danh sách bản ghi, mỗi cặp một bản ghi."""
    base, timeout = timeout, _exe_timeout(bundle, case, timeout)
    out = []
    c = BD.build_c_exe(B, bundle, case)
    seeds = exe_seeds(f'{T}/{bundle}/{case}')
    c_obs = {}
    for p in pairs:
        rec = dict(key=f'{bundle}/{case}/{p["system"]}', check='V5', kind='exe', bundle=bundle, case=case, system=p['system'],
                   timeout=timeout, timeout_base=base,
                   via=p['via'], c_build={k: c.get(k) for k in ('ok', 'preset', 'sha256', 'log')}, n_vectors=len(seeds))
        if not c['ok']: rec['status'] = 'c_build_failed'; out.append(rec); continue
        r = BD.build_rust_exe(B, p['system'], bundle, case, p['harvest_case'])
        rec['rust_build'] = {k: r.get(k) for k in ('ok', 'sha256', 'rustc_bootstrap', 'source_dir', 'log')}
        if not r['ok']: rec['status'] = 'rust_build_failed'; out.append(rec); continue
        rec['vectors'] = []
        for s in seeds:
            env = s.get('env')
            if s['name'] not in c_obs: c_obs[s['name']] = OB.run_exe(c['bin'], s['argv'], s['stdin'], timeout, env)
            eq, co, ro, info = OB.compare_exe(c['bin'], r['bin'], s['argv'], s['stdin'], timeout, c_obs[s['name']], env)
            v = dict(vector=s['name'], equal=eq, **info, c_status=co['status'], r_status=ro['status'])
            if not eq: v.update(c=obs_exe(co), r=obs_exe(ro), stdout_expect=s['vec'].get('stdout'), rc_expect=s['vec'].get('rc'))
            rec['vectors'].append(v)
        rec['n_mismatch'] = sum(not v['equal'] for v in rec['vectors']); rec['status'] = 'done'
        out.append(rec)
    return out


def v5_lib_case(B, bundle, case, pairs, timeout):
    out = []
    info = BD.build_lib_case(B, bundle, case)
    seeds = lib_seeds(f'{T}/{bundle}/{case}')
    ok_c = info['runner_ok'] and info['c_ok']
    croot = BD.lib_root(B, info, 'c') if ok_c else None
    c_obs = {}
    for p in pairs:
        rec = dict(key=f'{bundle}/{case}/{p["system"]}', check='V5', kind='lib', bundle=bundle, case=case, system=p['system'],
                   via=p['via'], no_input=p.get('no_input'), n_vectors=len(seeds),
                   build={k: info.get(k) for k in ('runner_ok', 'c_ok', 'c_sha256', 'preset', 'runner_log', 'c_log')})
        if not ok_c: rec['status'] = 'c_build_failed'; out.append(rec); continue
        r = BD.build_rust_lib(B, p['system'], bundle, case, p['harvest_case'], info['library'])
        rec['rust_build'] = {k: r.get(k) for k in ('ok', 'sha256', 'so_alias', 'rustc_bootstrap', 'source_dir', 'log')}
        if not r['ok']: rec['status'] = 'rust_build_failed'; out.append(rec); continue
        rroot = BD.lib_root(B, info, 'rust', r['dir'], tag=f'rust-{p["system"]}')
        rec['vectors'] = []
        dd = f'{B}/dumps/{bundle}/{case}'; os.makedirs(dd, exist_ok=True)
        for s in seeds:
            f = s['path']; n = s['file']
            if n not in c_obs: c_obs[n] = OB.run_lib_retry(info['runner_bin'], croot, f, timeout, False, f'{dd}/{n}.C.dump')
            co = c_obs[n]
            ro = OB.run_lib_retry(info['runner_bin'], rroot, f, timeout, True, f'{dd}/{n}.{p["system"]}.dump')
            eq = OB.equal_lib(co, ro); v = dict(vector=n, timeout_rerun=False, timeout_confirmed=False)
            # D1 cho V5 (Le chọn 26/10, như RQ2): một bên không quan sát được (k1 'infra') không chạy lại gấp mười; vector ghi
            # unobserved, equal None, không tính là lệch.
            if co.get('k1') == 'infra' or ro.get('k1') == 'infra':
                v.update(equal=None, unobserved=True, c_result=co.get('result'), r_result=ro.get('result'))
                rec['vectors'].append(v); continue
            if not eq and (OB.lib_timeout(co) != OB.lib_timeout(ro)):
                v['timeout_rerun'] = True
                co2 = OB.run_lib_retry(info['runner_bin'], croot, f, timeout * TIMEOUT_RERUN_FACTOR, False, f'{dd}/{n}.C.re.dump')
                ro = OB.run_lib_retry(info['runner_bin'], rroot, f, timeout * TIMEOUT_RERUN_FACTOR, True, f'{dd}/{n}.{p["system"]}.re.dump')
                v['timeout_confirmed'] = OB.lib_timeout(co2) != OB.lib_timeout(ro)
                eq = OB.equal_lib(co2, ro); co = co2
            v.update(equal=eq, c_result=co.get('result'), r_result=ro.get('result'))
            if not eq: v.update(c=OB.rec_obs(co), r=OB.rec_obs(ro), expect_out=s['vec'].get('lib_state_out'), channels=OB.channels_lib(co, ro))
            rec['vectors'].append(v)
        rec['n_mismatch'] = sum(v['equal'] is False for v in rec['vectors'])
        rec['n_unobserved'] = sum(bool(v.get('unobserved')) for v in rec['vectors']); rec['status'] = 'done'
        out.append(rec)
    return out


def safe(fn, *a):
    """Bọc lỗi hạ tầng: một case lỗi không làm dừng cả shard; lỗi thành bản ghi status=harness_error."""
    try:
        return fn(*a)
    except Exception:
        return dict(status='harness_error', error=traceback.format_exc()[-3000:])
