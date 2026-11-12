#!/usr/bin/env python3
"""exp 37: tính lại số sau lượt bổ sung C-san (docs/amendment-2026-11-05-rq2-san-supp.md mục 8, 9; post hoc, quyết định sau khi đã xem số
S₀; số mới: sơ bộ, chưa kiểm tay). Script đăng ký trước, thay cho lượt harness.metrics đầy đủ; cùng cách của
experiments/38-rq2-san-bound/scripts/bound.py. Không chạy gì.

Đầu vào: bản ghi S₀ (sha256 ở mục 3), thư mục kết quả CI của job smoke và job đầy đủ (--smoke-dir, --full-dir: ci-out/<job> của lần nộp
hoàn tất của job đó, gồm complete.json, attempt.json, run/rq2-san-supp-exe.jsonl, run/manifest.json, gate/, build/builds.json), --gate-dir
(bắt buộc: ci-out/rq2-san-supp-gate, hoặc `none` khi `git ls-remote` cho thấy không có nhánh gate nào), --b0-repo (bắt buộc: clone có
remote origin của repo luận văn; đọc mọi lần nộp B0 ở results/rq2-san-log và results-failed/rq2-san-log-<run>), keys.txt (sha256),
census qua census_counts của writing/scripts/gen-rq-macros.py, experiments/30-main-s0/results/metrics-split.json (D, L_P, P_test theo hệ),
bound-exe.json của exp 38. --supp (danh sách jsonl, không có bằng chứng CI) chỉ dùng được với --allow-synthetic.
S₀ᵃ = S₀ thay đúng 36 bản ghi của keys.txt bằng bản ghi mới; key thiếu hoặc thừa thì lượt đã dừng. Key không có bản ghi kết quả mà có hai bản
ghi harness_error (hai lần thử trong job đầy đủ) giữ bản ghi S₀, outcome not_re_examined, mã lý do supp_harness_error (mục 7 bước 5, mục 9).
Kiểm. Mọi kiểm hỏng (bằng chứng CI hay không) là lượt đã dừng (Le chốt vòng 4): stopped, chỉ báo gói A, gen-sansupp-macros.py không sinh
macro; không sửa script sau khi thấy dữ liệu (không có điều kiện sửa nào được đăng ký). ls-remote hay fetch nhánh B0 lỗi thì script thoát lỗi,
không ghi kết quả (`fail`, chạy lại).
  - bằng chứng CI (mục 8): không có STOP.txt ở nhánh gate, smoke, đầy đủ; job smoke và job đầy đủ hoàn tất (complete.json, không noop.txt),
    tối đa hai lần thử; cổng smoke build đạt cho 36 case; manifest smoke và đầy đủ mỗi bản có instance id, cổng môi trường đạt, loại máy
    và AMI của mục 7 (instance của hai job được phép khác nhau, Le chốt 2026-11-06; khác thì provenance.ci.instance ghi và stdout báo, công
    bố ở notes), cùng commit amendment, job đầy đủ 6 worker; mọi bản ghi của một job mang instance id của manifest job đó; sha256 driver
    và .so của từng bản ghi trùng builds.json của job smoke; mọi bản ghi của job
    đầy đủ mang cùng một sha256 module (sha của smoke và đầy đủ được báo, khác nhau thì phải công bố ở notes); key thiếu, thừa, trùng, hoặc
    bản ghi xong từ hạn chót trở đi; lịch sử B0 (mọi lần nộp) không có lần chạy nhánh (c);
  - mỗi bản ghi mới: recompute_vector, translation_outcome cho lại outcome đã ghi; obs.runs, input trùng S₀ (không chạy lại C, Rust); cờ
    C-san là cờ đã freeze cộng đúng cờ PIC;
  - k = 36: cùng phép tính với 36 bản ghi S₀ thay cho bản ghi mới cho lại đúng số S₀ ở rq-numbers.tex (rqLrExeAllCodexNum,
    rqSRHiExeAllCodexNum, rqSRHiExeAllNum, rqFFExeAllDen, rqFFExeAllCodexDen; thêm SRLo, SRWidth, FF Num);
  - A, F, not_adjudicable, not_re_examined tính từ bản ghi S₀ trùng metrics-split;
  - kiểm chéo: A, F, L_R, cận trên, cận dưới trùng hàng k của bound-exe.json (codex-gpt54 và gộp mọi hệ).
Dùng: python3 recompute_supp.py --s0 rq2-exe.jsonl --smoke-dir D1 --full-dir D2 --gate-dir D0|none --b0-repo . [--keys K] [--repo R]
      [--bound B] [--out F]
      python3 recompute_supp.py --s0 rq2-exe.jsonl --supp a.jsonl [b.jsonl] --allow-synthetic --out x-synthetic.json   (test, demo)"""
import argparse, collections, contextlib, hashlib, importlib.util, io, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
SYSTEM = 'codex-gpt54'
SYS_ROWS = ((SYSTEM, 'Codex'), ('_all', ''))
OUTCOMES = ('behavioral_disagreement', 'behavioral_agreement', 'not_adjudicable', 'not_re_examined')
SUPP_HE = 'supp_harness_error'                    # mã lý do đăng ký ở amendment mục 9 (Le chốt 2026-11-05)
WORKERS = 6
# Số S₀ mà phép tính "không đổi" (k = 36) phải cho lại (amendment mục 8; thêm SRLo, SRWidth, FF Num)
S0_MACRO_CHECKS = (('Lr', 'L_R', 'Num'), ('SRHi', 'upper_num', 'Num'), ('SRLo', 'lower_num', 'Num'), ('SRWidth', 'width_num', 'Num'),
                   ('FF', 'R_test', 'Den'), ('FF', 'F', 'Num'))
STOPPED_NOTE = 'lượt bổ sung đã dừng (stopped): chỉ báo phân tích cận của gói A (exp 38), không sinh macro rqSanSupp* (amendment mục 10)'
SENTENCE = {'contain': 'In the supplementary run, the bounds of Codex (GPT-5.4) on executable programs contain its original success rate.',
            'do not contain': 'In the supplementary run, the bounds of Codex (GPT-5.4) on executable programs do not contain its original '
                              'success rate.'}


def sha_file(p):
    try:
        with open(p, 'rb') as f: return hashlib.sha256(f.read()).hexdigest()
    except OSError: return None


def git(repo, *a):
    try: return subprocess.run(['git', '-C', repo, *a], capture_output=True, text=True).stdout.strip() or None
    except OSError: return None


def load_harness(repo):
    sys.path.insert(0, repo)
    import harness
    src = os.environ.get('RQ2_SAN_SUPP_SRC')          # module chưa nằm trong harness/ của repo (kiểm trước commit)
    if src and src not in harness.__path__: harness.__path__.append(src)
    from harness import rq2, rq2_san_supp
    return rq2, rq2_san_supp


def rq_macros(path):
    out = {}
    try:
        for ln in open(path).read().splitlines():
            m = re.match(r'\\rqSet\{([A-Za-z]+)\}\{([^}]*)\}', ln)
            if m: out[m.group(1)] = m.group(2)
    except OSError: pass
    return out


def pct(n, d): return None if not d else round(100 * n / d, 1)


# ---------------------------------------------------------------- bản ghi
def check_record(R2, SUPP, r, s0r):
    """Lỗi của một bản ghi mới so với bản ghi S₀ cùng key (danh sách rỗng là đạt)."""
    bad = []
    vs, v0s = r.get('vectors') or [], s0r.get('vectors') or []
    if [v.get('vector') for v in vs] != [v.get('vector') for v in v0s]: return ['tập vector khác S₀']
    vos = []
    for v, v0 in zip(vs, v0s):
        got = tuple(R2.recompute_vector(v, 'exe'))
        if got != (v['outcome'], v['reason']): bad.append(f'{v["vector"]}: recompute_vector {got} khác ({v["outcome"]}, {v["reason"]})')
        vos.append(got)
        if json.dumps(v['obs']['runs'], sort_keys=True) != json.dumps(v0['obs']['runs'], sort_keys=True):
            bad.append(f'{v["vector"]}: obs.runs khác S₀')
        for k in ('input', 'runs', 'c_out', 'r_out', 'c_err', 'r_err', 'san_timeout'):
            if v.get(k) != v0.get(k): bad.append(f'{v["vector"]}: {k} khác S₀')
        if (v.get('san_attempts') or 0) != len(v['obs']['san']['attempts']): bad.append(f'{v["vector"]}: san_attempts lệch obs.san')
    o, rs = R2.translation_outcome(vos)
    if (o, sorted(rs)) != (r['outcome'], sorted(r.get('reasons') or [])): bad.append(f'translation_outcome {o} {rs} khác bản ghi')
    if r.get('reason') != R2.primary_reason(o, rs): bad.append('primary_reason lệch')
    sp = r.get('supp') or {}
    if sp.get('san_flags_exe') != SUPP.FROZEN_SAN_FLAGS_EXE + [SUPP.PIC_FLAG]: bad.append('cờ C-san khác cờ đã freeze cộng cờ PIC')
    for k in ('timeout', 'bundle', 'case', 'system'):
        if r.get(k) != s0r.get(k): bad.append(f'{k} khác S₀')
    return bad


def merge(R2, SUPP, s0, keys, supp_recs):
    """Bản ghi bổ sung theo key (dict), lỗi kiểm, thông tin dừng. Mỗi key tối đa hai lần thử (job đầy đủ chạy lại harness_error một lần trong
    cùng job). Bản ghi (kể cả harness_error) xong từ hạn chót trở đi làm lượt dừng (mục 10; cùng phép so với deadline_check)."""
    ok_recs = collections.defaultdict(list)
    errs = collections.Counter()
    for r in supp_recs:
        if r.get('status') == 'harness_error': errs[SUPP.base_key(r['key'])] += 1
        else: ok_recs[r['key']].append(r)
    extra = sorted((set(ok_recs) | {k for k, v in errs.items() if v}) - set(keys))
    dup = sorted(k for k, v in ok_recs.items() if len(v) > 1)
    missing = sorted(k for k in keys if k not in ok_recs and errs[k] < 2)
    kept = sorted(k for k in keys if k not in ok_recs and errs[k] == 2)        # hai lần hỏng: giữ bản ghi S₀ (not_re_examined)
    over = sorted(k for k in keys if errs[k] > 2 or (k in ok_recs and errs[k] >= 2))
    late = sorted(r['key'] for r in supp_recs if not (r.get('supp') or {}).get('utc_end') or r['supp']['utc_end'] >= SUPP.DEADLINE_UTC)
    out, bad = {}, {}
    for k in keys:
        if k in ok_recs and k not in dup:
            b = check_record(R2, SUPP, ok_recs[k][0], s0[k])
            if b: bad[k] = b
            out[k] = ok_recs[k][0]
        elif k in kept:                                  # mục 9: not_re_examined, mã supp_harness_error (không giữ san_build_failed)
            out[k] = dict(s0[k], reason=SUPP_HE, reasons=[SUPP_HE], supp_status='harness_error_twice', supp_failed_attempts=errs[k])
    stop = []
    if missing: stop.append(f'thiếu bản ghi của {len(missing)} key')
    if extra: stop.append(f'thừa {len(extra)} key ngoài keys.txt')
    if dup: stop.append(f'{len(dup)} key có hơn một bản ghi')
    if over: stop.append(f'{len(over)} key quá hai lần thử (mục 7 bước 5)')
    if late: stop.append(f'{len(late)} bản ghi xong từ hạn chót {SUPP.DEADLINE_UTC} trở đi (mục 10)')
    return out, dict(missing=missing, extra=extra, duplicate=dup, kept_s0_after_two_errors=kept, over_tries=over, late=late,
                     record_errors=bad, failed_attempt_counts={k: v for k, v in errs.items() if v}, stop=stop)


# ---------------------------------------------------------------- bằng chứng CI (review L6, C4)
def jl(p):
    try:
        with open(p) as f: return json.load(f)
    except (OSError, ValueError): return None


def _iid(m):
    pm = (m or {}).get('params') or {}
    return ((pm.get('gates') or {}).get('env') or {}).get('machine', {}).get('instance_id') or ((m or {}).get('machine') or {}).get('instance_id')


def _env(m):
    return (((m or {}).get('params') or {}).get('gates') or {}).get('env') or {}


def ci_dirs_records(SUPP, smoke, full):
    recs = []
    for d in (smoke, full): recs += SUPP.records(f'{d}/run/{SUPP.OUT_NAME}')
    return recs


def ci_evidence(SUPP, keys, smoke, full, gate, supp_recs, chk):
    """Kiểm bằng chứng CI; ghi từng kiểm qua chk với ci=True (kiểm CI hỏng thì lượt tính là đã dừng). Trả thông tin ghi vào provenance."""
    info = {}
    c = lambda what, ok, **kw: chk(what, ok, ci=True, **kw)
    dirs = dict(smoke=smoke, full=full, **({} if gate is None else dict(gate=gate)))
    c('có thư mục kết quả của mọi nhánh được truyền', all(os.path.isdir(d) for d in dirs.values()), dirs=dirs)
    stops = sorted(f'{d}/STOP.txt' for d in dirs.values() if os.path.exists(f'{d}/STOP.txt'))
    c('không có STOP.txt ở nhánh gate, smoke, đầy đủ', not stops, stop_files=stops)
    att = {}
    for name, d in (('smoke', smoke), ('full', full)):
        a = jl(f'{d}/{SUPP.ATTEMPT}') or {}
        att[name] = a.get('attempt')
        c(f'job {name} hoàn tất (complete.json, không noop.txt)', os.path.exists(f'{d}/{SUPP.COMPLETE}') and not os.path.exists(f'{d}/{SUPP.NOOP}'))
        c(f'job {name}: tối đa {SUPP.MAX_ATTEMPTS} lần thử (attempt.json)', isinstance(a.get('attempt'), int) and 1 <= a['attempt'] <= SUPP.MAX_ATTEMPTS,
          attempt=a.get('attempt'))
    info['attempts'] = att                                       # lần thử 2: disclosure ở notes (mục 7 bước 5)
    cases = [k.split('/')[-1] for k in keys]
    gc = SUPP.gate_check(f'{smoke}/gate/smoke-gate.json', cases)
    c('cổng smoke build (job smoke) đạt cho 36 case', gc['ok'], gate=gc)
    info['gate'] = gc
    ms = {name: jl(f'{d}/run/manifest.json') for name, d in (('smoke', smoke), ('full', full))}
    c('có run/manifest.json của job smoke và job đầy đủ', all(ms.values()))
    job_iid = {name: str(_iid(m)) for name, m in ms.items()}
    iids = sorted(set(job_iid.values()))
    commits = sorted({str((((m or {}).get('params') or {}).get('gates') or {}).get('amendment', {}).get('commit')) for m in ms.values()})
    c('manifest job smoke và job đầy đủ có instance id', 'None' not in iids, instance_ids=job_iid)
    # Le chốt 2026-11-06 (mục 7): hai job được chạy trên hai instance khác nhau khi cả hai cùng loại máy, AMI của mục 7 và cổng môi trường đạt
    want = {k: SUPP.ENV_REQ[k] for k in ('instance_type', 'ami_id')}
    for name, m in ms.items():
        e = _env(m); got = {k: (e.get('machine') or {}).get(k) for k in want}
        c(f'job {name}: cổng môi trường đạt, loại máy {want["instance_type"]}, AMI {want["ami_id"]} (mục 7)',
          e.get('ok') is True and got == want, machine=got, env_ok=e.get('ok'))
    differ = len(iids) > 1
    info['instance'] = dict(smoke=job_iid['smoke'], full=job_iid['full'], differ=differ, machine=want,
                            note='instance của job smoke và job đầy đủ khác nhau: công bố ở notes (amendment mục 7)' if differ else None)
    c('job smoke và job đầy đủ cùng commit amendment', len(commits) == 1 and commits[0] != 'None', commits=commits)
    fw = ((ms['full'] or {}).get('params') or {}).get('workers')
    c(f'job đầy đủ chạy {WORKERS} worker', fw == WORKERS, workers=fw)
    rec_iids = {name: sorted({str((r.get('supp') or {}).get('instance_id')) for r in SUPP.records(f'{d}/run/{SUPP.OUT_NAME}')})
                for name, d in (('smoke', smoke), ('full', full))}
    c('mọi bản ghi của một job mang instance id của manifest job đó', all(rec_iids[n] == [job_iid[n]] for n in rec_iids),
      record_instance_ids=rec_iids, manifest_instance_ids=job_iid)
    builds = (jl(f'{smoke}/build/builds.json') or {}).get('builds') or {}
    badb = []
    for r in supp_recs:
        if r.get('status') == 'harness_error': continue
        b, w = (r.get('supp') or {}).get('build') or {}, builds.get(r.get('case')) or {}
        if not w.get('ok') or b.get('sha256') != w.get('sha256') or not w.get('files') or b.get('files') != w.get('files'):
            badb.append(r.get('key'))
    c('sha256 driver và .so của mọi bản ghi trùng builds.json của job smoke', not badb and bool(builds), mismatched=badb[:5])
    # Le chốt vòng 4: module chỉ được đổi giữa hai lần thử hỏng của cùng một job; mọi bản ghi của job đầy đủ mang một sha module
    msha = {name: sorted({str((r.get('supp') or {}).get('module_sha256')) for r in part})
            for name, part in (('smoke', SUPP.records(f'{smoke}/run/{SUPP.OUT_NAME}')), ('full', SUPP.records(f'{full}/run/{SUPP.OUT_NAME}')))}
    mman = {name: ((m or {}).get('params') or {}).get('module_sha256') for name, m in ms.items()}
    c('mọi bản ghi của job đầy đủ mang cùng một sha256 module', len(msha['full']) == 1 and msha['full'][0] != 'None', module_sha256=msha)
    info['module_sha256'] = dict(records=msha, manifests=mman, smoke_full_differ=msha['smoke'] != msha['full'] or mman['smoke'] != mman['full'],
                                 note='khác nhau giữa smoke và đầy đủ: phải công bố ở notes (amendment mục 7 bước 5)')
    info.update(stop_files=stops, instance_ids=iids, amendment_commits=commits, gate_dir=gate or 'none',
                builds=dict(path=f'{smoke}/build/builds.json', sha256=sha_file(f'{smoke}/build/builds.json')))
    return info


def b0_evidence(SUPP, repo, chk):
    """Le chốt vòng 4 (review R3-07): đọc lại mọi lần nộp B0 (results/ và results-failed/); một lần chạy nhánh (c) ở bất kỳ đâu là lượt đã
    dừng. ls-remote hay fetch lỗi: thoát lỗi, không ghi kết quả (`fail`, chạy lại)."""
    try: col = SUPP.b0_collect(repo)
    except SUPP.Refuse as e: raise SystemExit(f'không đọc được các lần nộp B0 từ {repo}: {e}; không ghi kết quả, chạy lại')
    cs = SUPP.b0_c_runs(col['history'])
    chk('lịch sử B0 (results/ và results-failed/) không có lần chạy nhánh (c)', not cs, ci=True, c_runs=cs[:5])
    return dict(refs=[dict(ref=x['ref'], commit=x['commit'], branch=SUPP.b0_branch(x['summary'])[0] if x['summary'] else None)
                      for x in col['refs']], n_history=len(col['history']), c_runs=cs)


def attrition(recs, R2):
    """R_run theo (kết quả, lý do chính) cho codex-gpt54 và gộp mọi hệ, đủ mọi cặp của rq2.TRANSLATION_REASONS (số 0 cũng ghi) cộng
    supp_harness_error và harness_error (mục 1, mục 9: dòng not re-examined trong R_run theo lý do, S₀ cạnh bản bổ sung)."""
    pairs = [f'{o}:{r}' for o, rs in R2.TRANSLATION_REASONS.items() for r in rs] + [f'not_re_examined:{SUPP_HE}', 'harness_error:None']
    out = {sy: {p: 0 for p in pairs} for sy, _ in SYS_ROWS}
    for r in recs:
        p = f'{r.get("outcome") or r.get("status")}:{r.get("reason") if r.get("outcome") not in (None, "behavioral_disagreement", "behavioral_agreement") else None}'
        for sy in (r['system'], '_all'):
            if sy in out: out[sy][p] = out[sy].get(p, 0) + 1
    return out


# ---------------------------------------------------------------- số
def base_quantities(repo, s0dir):
    spec = importlib.util.spec_from_file_location('gen_rq_macros', f'{repo}/writing/scripts/gen-rq-macros.py')
    G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
    err = io.StringIO()
    with contextlib.redirect_stderr(err): cen, cfiles = G.census_counts(repo, False)
    split = json.load(open(f'{s0dir}/metrics-split.json'))
    base = {}
    for sy, _ in SYS_ROWS:
        c = cen['exe'][('all', sy)]; r1 = split['rq1']['exe']['all'][sy]; r2 = split['rq2']['exe']['all'][sy]
        b = dict(P0=c['P0'], P_acc=c['P_acc'], R0_test=c['R0_test'], R_run=c['R_run'], D_all=r1['D_all'], P_test=r1['P_test'],
                 split_rq2={k: r2[k] for k in ('A', 'F', 'R_test', 'not_adjudicable', 'not_re_examined')})
        b['L_P'] = b['P_acc'] - b['P_test']
        base[sy] = b
    files = {os.path.relpath(p, repo): sha_file(p) for p in cfiles if '02-harvest-repro' in p}
    files[os.path.relpath(f'{s0dir}/metrics-split.json', repo) if s0dir.startswith(repo) else f'{s0dir}/metrics-split.json'] = \
        sha_file(f'{s0dir}/metrics-split.json')
    return base, dict(census_files=files, census_stderr=err.getvalue().strip() or None)


def quantities(recs, base):
    """RQ2 và RQ3 executable theo hệ từ một tập bản ghi R_run (S₀ hoặc S₀ᵃ). Luật §3.6: L_R = |R_0^test| - A - F; cận trên
    (|P_acc| - D + F + L_R)/|P_0|; cận dưới (|P_acc| - D - L_P + F)/|P_0|; độ rộng (L_P + L_R)/|P_0|; r_FF = F/|R_test|."""
    C = collections.defaultdict(collections.Counter)
    for r in recs:
        o = r.get('outcome') or r.get('status'); C[r['system']][o] += 1; C['_all'][o] += 1
    out = {}
    for sy, _ in SYS_ROWS:
        b, c = base[sy], C[sy]
        A, F, NA, NR = (c['behavioral_disagreement'], c['behavioral_agreement'], c['not_adjudicable'], c['not_re_examined'])
        q = dict(A=A, F=F, not_adjudicable=NA, not_re_examined=NR, harness_error=c['harness_error'], R_run_rec=sum(c.values()),
                 R_test=A + F + NA, rff_pct=pct(F, A + F + NA), P0=b['P0'], P_acc=b['P_acc'], D_all=b['D_all'], L_P=b['L_P'],
                 R0_test=b['R0_test'])
        q['L_R'] = b['R0_test'] - A - F
        q['upper_num'] = b['P_acc'] - b['D_all'] + F + q['L_R']
        q['lower_num'] = b['P_acc'] - b['D_all'] - b['L_P'] + F
        q['width_num'] = b['L_P'] + q['L_R']
        for k in ('upper', 'lower', 'width'): q[f'{k}_pct'] = pct(q[f'{k}_num'], b['P0'])
        q['sr_pct'] = pct(b['P_acc'], b['P0'])
        q['contains_sr'] = q['lower_num'] <= b['P_acc'] <= q['upper_num']
        out[sy] = q
    return out


def summarize_36(keys, sa):
    oc = collections.Counter(sa[k]['outcome'] for k in keys)
    rc = collections.Counter(f'{sa[k]["outcome"]}:{sa[k].get("reason")}' for k in keys)
    groups = collections.defaultdict(list)
    for k in keys: groups[f'{sa[k]["outcome"]}:{sa[k].get("reason")}'].append(k)
    k_na, k_nr = oc['not_adjudicable'], oc['not_re_examined']
    return dict(n=len(keys), k=len(keys) - oc['behavioral_disagreement'], k_NA=k_na, k_NR=k_nr, n_disagreement=oc['behavioral_disagreement'],
                n_agreement=oc['behavioral_agreement'], by_outcome={o: oc[o] for o in OUTCOMES}, by_reason=dict(sorted(rc.items())),
                keys_by_group={g: sorted(v) for g, v in sorted(groups.items())})


def run(a):
    repo = os.path.abspath(a.repo)
    R2, SUPP = load_harness(repo)
    checks, prov = [], {}
    chk = lambda what, ok, **kw: checks.append(dict(what=what, ok=bool(ok), **kw))
    keys = [l.strip() for l in open(a.keys) if l.strip()]
    prov['keys'] = dict(path=os.path.abspath(a.keys), sha256=sha_file(a.keys))
    chk('sha256 keys.txt = amendment', prov['keys']['sha256'] == SUPP.KEYS_SHA256, got=prov['keys']['sha256'])
    s0, s0info = SUPP.load_s0(a.s0, keys)                   # kiểm sha256 bản ghi S₀ và từng bản ghi của 36 key (dừng nếu lệch)
    s0recs = [json.loads(l) for l in open(a.s0) if l.strip()]
    prov['s0'] = s0info
    supp_recs = []
    ci = bool(a.smoke_dir or a.full_dir)
    if ci:
        if not (a.smoke_dir and a.full_dir) or a.supp: raise SystemExit('cần cả --smoke-dir và --full-dir, không kèm --supp')
        if not a.gate_dir: raise SystemExit('cần --gate-dir: ci-out/rq2-san-supp-gate, hoặc `none` khi git ls-remote không thấy nhánh gate')
        if not a.b0_repo: raise SystemExit('cần --b0-repo: clone có remote origin của repo luận văn (đọc mọi lần nộp B0)')
        supp_recs = ci_dirs_records(SUPP, a.smoke_dir, a.full_dir)
        for d in (a.smoke_dir, a.full_dir):
            p = f'{d}/run/{SUPP.OUT_NAME}'; prov.setdefault('supp', []).append(dict(path=os.path.abspath(p), sha256=sha_file(p)))
    else:
        if not a.supp: raise SystemExit('cần --smoke-dir và --full-dir (hoặc --supp với --allow-synthetic)')
        if not a.allow_synthetic: raise SystemExit('--supp không có bằng chứng CI: chỉ dùng với --allow-synthetic (test, demo)')
        for p in a.supp:
            rs = SUPP.records(p); supp_recs += rs
            prov.setdefault('supp', []).append(dict(path=os.path.abspath(p), sha256=sha_file(p), n=len(rs)))
    synthetic = any(r.get('synthetic') for r in supp_recs) or not ci
    if synthetic and not a.allow_synthetic: raise SystemExit('bản ghi giả lập (synthetic): cần --allow-synthetic')
    if ci:
        prov['ci'] = ci_evidence(SUPP, keys, a.smoke_dir, a.full_dir, None if a.gate_dir == 'none' else a.gate_dir, supp_recs, chk)
        prov['b0'] = b0_evidence(SUPP, os.path.abspath(a.b0_repo), chk)
    else: chk('bằng chứng CI (chỉ bỏ qua với dữ liệu giả lập)', synthetic)
    sup, minfo = merge(R2, SUPP, s0, keys, supp_recs)
    chk('mọi bản ghi mới qua kiểm (recompute, obs.runs, input, cờ)', not minfo['record_errors'],
        errors={k: v[:3] for k, v in list(minfo['record_errors'].items())[:5]})
    chk('đủ 36 key, không thừa, không trùng, tối đa hai lần thử, xong trước hạn chót', not minfo['stop'], ci=True, stop=minfo['stop'])
    sa = {r['key']: r for r in s0recs}
    for k, r in sup.items(): sa[k] = r
    s0a = list(sa.values())
    base, binfo = base_quantities(repo, os.path.abspath(a.s0_metrics or f'{repo}/experiments/30-main-s0/results'))
    prov.update(binfo)
    q_s0 = quantities(s0recs, base)
    for sy, _ in SYS_ROWS:
        sp = base[sy]['split_rq2']
        chk(f'{sy}: A, F, R_test, not_adjudicable, not_re_examined từ bản ghi S₀ = metrics-split',
            all(q_s0[sy][k] == sp[k] for k in sp), computed={k: q_s0[sy][k] for k in sp}, split=sp)
        chk(f'{sy}: R_run census = số bản ghi', base[sy]['R_run'] == q_s0[sy]['R_run_rec'])
    # k = 36: phép tính với 36 bản ghi S₀ thay cho bản ghi mới (S₀ᵃ = S₀)
    nochange = {r['key']: r for r in s0recs}
    for k in keys: nochange[k] = s0[k]
    q_nc = quantities(list(nochange.values()), base)
    M = rq_macros(f'{repo}/writing/generated/rq-numbers.tex')
    prov['rq_numbers_tex'] = dict(path='writing/generated/rq-numbers.tex', sha256=sha_file(f'{repo}/writing/generated/rq-numbers.tex'))
    for sy, tk in SYS_ROWS:
        for fam, field, part in S0_MACRO_CHECKS:
            name = f'rq{fam}ExeAll{tk}{part}'
            chk(f'k = 36 cho lại {name} của rq-numbers.tex', M.get(name) == str(q_nc[sy][field]), macro=M.get(name), computed=q_nc[sy][field])
    s36_nc = summarize_36(keys, {k: s0[k] for k in keys})
    chk('k = 36 khi không đổi', s36_nc['k'] == 36 and s36_nc['k_NR'] == 36, k=s36_nc['k'])
    q = quantities(s0a, base)
    s36 = summarize_36(keys, {k: sa[k] for k in keys})
    chk('không có behavioral_agreement trong 36 bản (amendment mục 1: F = 0 ở mọi kết quả)', s36['n_agreement'] == 0)
    chk('|R_test| bổ sung = 92 + 36 - k_NR (toàn bộ) và 7 + 36 - k_NR (codex-gpt54)',
        q['_all']['R_test'] == q_s0['_all']['R_test'] + 36 - s36['k_NR'] and q[SYSTEM]['R_test'] == q_s0[SYSTEM]['R_test'] + 36 - s36['k_NR'])
    chk('L_R codex-gpt54 bổ sung = k', q[SYSTEM]['L_R'] == s36['k'])
    # kiểm chéo với exp 38
    bp = os.path.abspath(a.bound or f'{repo}/experiments/38-rq2-san-bound/results/bound-exe.json')
    bd = json.load(open(bp)) if os.path.exists(bp) else None
    prov['bound'] = dict(path=bp, sha256=sha_file(bp))
    for sy, _ in SYS_ROWS:
        rows = ((bd or {}).get('rq3', {}).get('tables', {}).get(sy) or {}).get('rows') or []
        row = next((x for x in rows if x['k'] == s36['k']), None)
        same = row is not None and all(row[f] == q[sy][f] for f in ('A', 'F', 'L_R', 'upper_num', 'lower_num'))
        chk(f'{sy}: A, F, L_R, cận trên, cận dưới trùng hàng k={s36["k"]} của bound-exe.json', same,
            bound=None if row is None else {f: row[f] for f in ('A', 'F', 'L_R', 'upper_num', 'lower_num')},
            computed={f: q[sy][f] for f in ('A', 'F', 'L_R', 'upper_num', 'lower_num')})
    contains = 'contain' if q[SYSTEM]['contains_sr'] else 'do not contain'
    att = dict(s0=attrition(s0recs, R2), supp=attrition(s0a, R2))
    chk('attrition R_run: tổng mỗi cột bằng R_run census', all(sum(att[x][sy].values()) == base[sy]['R_run'] for x in att for sy, _ in SYS_ROWS))
    known = set(attrition([], R2)['_all'])
    unk = sorted({p for x in att for sy in att[x] for p in att[x][sy]} - known)
    chk('attrition R_run: mọi cặp (kết quả, lý do) thuộc danh sách đã biết', not unk, unknown=unk)
    chk('câu cơ học: chứa s khi và chỉ khi k >= 9 (54 + k >= 63)', q[SYSTEM]['contains_sr'] == (s36['k'] >= 9))
    ok = all(c['ok'] for c in checks)
    stopped = not ok                                             # Le chốt vòng 4: mọi kiểm hỏng là lượt đã dừng (gói A, không macro)
    return dict(label='post hoc, quyết định sau khi đã xem số S₀; sơ bộ, chưa kiểm tay',
                synthetic=synthetic, SYNTHETIC='DỮ LIỆU GIẢ LẬP, KHÔNG PHẢI KẾT QUẢ LƯỢT BỔ SUNG' if synthetic else None,
                ok=ok, stopped=stopped, stopped_note=STOPPED_NOTE if stopped else None, checks=checks,
                failed=[c['what'] for c in checks if not c['ok']],
                provenance=dict(prov, repo_head=git(repo, 'rev-parse', 'HEAD'), harness_rq2_sha256=sha_file(f'{repo}/harness/rq2.py'),
                                amendment=SUPP.AMENDMENT, recompute_sha256=sha_file(os.path.abspath(__file__)),
                                module_sha256=SUPP.module_sha()),
                merge=minfo, supp36=s36, s0_36=s36_nc, attrition_rrun=att,
                rq2=dict(s0={sy: {k: q_s0[sy][k] for k in ('A', 'F', 'not_adjudicable', 'not_re_examined', 'R_test', 'rff_pct')} for sy, _ in SYS_ROWS},
                         supp={sy: {k: q[sy][k] for k in ('A', 'F', 'not_adjudicable', 'not_re_examined', 'R_test', 'rff_pct')} for sy, _ in SYS_ROWS}),
                rq3=dict(s0={sy: _rq3(q_s0[sy]) for sy, _ in SYS_ROWS}, supp={sy: _rq3(q[sy]) for sy, _ in SYS_ROWS}),
                contains_codex=contains, sentence=SENTENCE[contains])


def _rq3(x):
    return {k: x[k] for k in ('P0', 'P_acc', 'D_all', 'L_P', 'R0_test', 'A', 'F', 'L_R', 'upper_num', 'upper_pct', 'lower_num', 'lower_pct',
                              'width_num', 'width_pct', 'sr_pct', 'contains_sr')}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--s0', required=True); ap.add_argument('--supp', nargs='+')
    ap.add_argument('--smoke-dir'); ap.add_argument('--full-dir')
    ap.add_argument('--gate-dir', help='ci-out/rq2-san-supp-gate, hoặc none khi không có nhánh gate (bắt buộc với --smoke-dir)')
    ap.add_argument('--b0-repo', help='clone có remote origin của repo luận văn: đọc mọi lần nộp B0 (bắt buộc với --smoke-dir)')
    ap.add_argument('--repo', default=REPO_DEFAULT); ap.add_argument('--keys'); ap.add_argument('--s0-metrics'); ap.add_argument('--bound')
    ap.add_argument('--out'); ap.add_argument('--allow-synthetic', action='store_true')
    a = ap.parse_args(argv)
    a.keys = a.keys or f'{os.path.abspath(a.repo)}/experiments/37-rq2-san-supp/data/keys.txt'
    default_out = os.path.join(os.path.abspath(a.repo), 'experiments', '37-rq2-san-supp', 'results', 'supp-exe.json')
    out = os.path.abspath(a.out or default_out)
    doc = run(a)
    if doc['synthetic'] and (out == default_out or '/results/' in out or 'synthetic' not in os.path.basename(out).lower()):
        raise SystemExit(f'dữ liệu giả lập: tên file ra phải chứa "synthetic" và không nằm dưới results/: {out}')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(doc, open(out, 'w'), indent=1, ensure_ascii=False)
    s = doc['supp36']
    print(('*** DỮ LIỆU GIẢ LẬP (SYNTHETIC) ***\n' if doc['synthetic'] else '') +
          f'36 bản: {s["by_outcome"]}; lý do {s["by_reason"]}; k={s["k"]} (k_NA {s["k_NA"]}, k_NR {s["k_NR"]})')
    for sy, _ in SYS_ROWS:
        x, y = doc['rq3']['s0'][sy], doc['rq3']['supp'][sy]
        print(f'{sy}: L_R {x["L_R"]} -> {y["L_R"]}; cận trên {x["upper_num"]}/{x["P0"]} -> {y["upper_num"]}/{y["P0"]} ({y["upper_pct"]}%); '
              f'cận dưới {y["lower_num"]}/{y["P0"]}; R_test {doc["rq2"]["s0"][sy]["R_test"]} -> {doc["rq2"]["supp"][sy]["R_test"]}')
    print(f'câu cơ học: {doc["contains_codex"]}')
    for c in doc['checks']: print(f'  {"ok  " if c["ok"] else "FAIL"} {c["what"]}')
    ms = (doc['provenance'].get('ci') or {}).get('module_sha256')
    if ms: print(f'sha256 module: smoke {ms["records"]["smoke"]}, đầy đủ {ms["records"]["full"]}'
                 + ('; KHÁC NHAU: công bố ở notes' if ms['smoke_full_differ'] else ''))
    inst = (doc['provenance'].get('ci') or {}).get('instance')
    if inst: print(f'instance: smoke {inst["smoke"]}, đầy đủ {inst["full"]}'
                   + (f'; KHÁC NHAU (cùng {inst["machine"]["instance_type"]}, AMI {inst["machine"]["ami_id"]}): công bố ở notes'
                      if inst['differ'] else ''))
    if doc['stopped']: print(f'DỪNG: {STOPPED_NOTE}')
    print(f'{"ĐẠT" if doc["ok"] else "KHÔNG ĐẠT"}; đã ghi {out}')
    return 0 if doc['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
