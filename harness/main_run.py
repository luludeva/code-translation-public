"""Lượt chính RQ1 (và RQ2) trên toàn P_rep (R_run cho RQ2), sau Protocol Freeze. File mới sau commit đo ứng viên `bc82907`: luật kế thừa
tag (decision-log 2026-10-26) chỉ cho thêm file mới vào harness/, nên module này KHÔNG sửa rq1.py, rq2.py mà gọi lại đúng các hàm theo
case của chúng (rq1_exe_case, rq1_lib_case, rq2_case), Store, manifest, cách chia shard, cùng vòng chạy như rq1.main, rq2.main ở pilot.

Khác pilot: chọn cặp bằng pairs.prep_pairs(kind) (RQ1) hoặc rq2.r_run(kind, pilot=False) (RQ2); nguồn P_rep library qua
HARNESS_P_REP_LIB_CENSUS, HARNESS_P_REP_LIB_RECHECK (ci/p-rep-lib3.sh, census lần ba), ghi trong manifest (pairs.source_info).

Hai chế độ, loại trừ nhau:
  --freeze-tag T: lượt chính. Từ chối chạy trừ khi T là tag có thật, commit của T là HEAD hoặc tổ tiên của HEAD, `git diff --no-renames
      --name-status T HEAD -- harness/` chỉ có dòng trạng thái A (file thêm mới), và cây làm việc không có thay đổi chưa commit trong
      harness/ (file đã theo dõi). Seed cố định 0, 1, 2. RQ1 library đòi đặt cả hai biến nguồn P_rep library (census lần ba).
  --dryrun-sample F --sample-seed S: chạy thử đầu cuối, KHÔNG đòi tag. Chọn mẫu phân tầng theo nhóm (B01, B02, P00, P01, theo tiền tố
      bundle; exe và lib riêng), mỗi nhóm có mặt ít nhất 1 case, seed cố định. Manifest ghi tag=dryrun và dòng DRYRUN lớn, thư mục ra có file
      DRYRUN.txt; đường dẫn --out phải chứa chữ 'dryrun' (lượt chính thì cấm chữ này), nên đầu ra không lẫn với lượt chính.
  Thư mục ra đã có manifest của chế độ khác, tag freeze khác hoặc nhãn mức khác thì từ chối (chạy tiếp chỉ trong cùng một lượt).

Ngân sách (tham số Protocol Freeze, L* do Le chọn): --level x1|x3|x10 (bảng harness.sweep.LEVELS, memo W6) hoặc số tường minh
(--budget, --afl-execs cho exe; --n-inputs cho lib); đưa cả hai thì phải khớp. Không có giá trị mặc định cho lượt chính.

Cách dùng:
  python3 -m harness.main_run --kind exe|lib --out DIR --freeze-tag T --level x10 [--workers 6] [--timeout 10] [--shard i/n | --cases b/c,...]
  python3 -m harness.main_run --rq 2 --kind exe|lib --out DIR --freeze-tag T [--workers 6] [--timeout 10]
  python3 -m harness.main_run --kind lib --out DIR-dryrun --dryrun-sample 0.05 --sample-seed 0 --level x1 [--seeds 0,1,2]
  python3 -m harness.main_run --list-cases FILE --kind exe|lib [--rq 2]     (danh sách case mong đợi, cho merge_shards --expect)"""
import argparse, collections, json, os, random, subprocess, time
from concurrent.futures import ProcessPoolExecutor, as_completed

from . import build as BD
from . import observe as OB
from . import pairs as PR
from . import rq1 as R1
from . import rq2 as R2
from .config import INSENSITIVE_SEED, PILOT_EXE, PILOT_LIB, REPO, TIMEOUT_RERUN_FACTOR
from .record import Store, compress_files, manifest

GROUPS = ('B01', 'B02', 'P00', 'P01')
MAIN_SEEDS = (0, 1, 2)
DRYRUN_BANNER = '*** DRYRUN: CHẠY THỬ ĐẦU CUỐI TRÊN MẪU, KHÔNG PHẢI KẾT QUẢ LƯỢT CHÍNH, KHÔNG DÙNG CHO SỐ LIỆU LUẬN VĂN ***'
LIB_ENV = ('HARNESS_P_REP_LIB_CENSUS', 'HARNESS_P_REP_LIB_RECHECK')


def group_of(bundle):
    """Nhóm phân tầng: tiền tố bundle trước dấu '_' đầu tiên (B01_organic, B01_synthetic -> B01)."""
    return bundle.split('_', 1)[0]


# ---------------- kiểm tag Protocol Freeze ----------------
def _git(repo, *a):
    return subprocess.run(['git', '-C', repo, *a], capture_output=True, text=True)


def freeze_check(tag, repo=REPO):
    """Luật kế thừa tag (decision-log 2026-10-26) áp cho harness/. Trả về dict có ok, reason và bằng chứng (ghi vào manifest)."""
    r = dict(tag=tag, rule='tag là HEAD hoặc tổ tiên; git diff --no-renames --name-status <tag> HEAD -- harness/ chỉ có trạng thái A; '
                          'harness/ không có thay đổi chưa commit', ok=False)
    if not tag: return dict(r, reason='không có tag')
    p = _git(repo, 'rev-parse', '-q', '--verify', f'refs/tags/{tag}^{{commit}}')
    if p.returncode != 0 or not p.stdout.strip(): return dict(r, reason=f'tag {tag} không tồn tại (job phải fetch tag trước)')
    tc = p.stdout.strip(); head = _git(repo, 'rev-parse', 'HEAD').stdout.strip()
    r.update(tag_commit=tc, head=head)
    if _git(repo, 'merge-base', '--is-ancestor', tc, head).returncode != 0:
        return dict(r, reason=f'commit của tag {tc} không phải HEAD hay tổ tiên của HEAD {head} (hoặc clone nông thiếu lịch sử)')
    d = _git(repo, 'diff', '--no-renames', '--name-status', tc, head, '--', 'harness/')
    if d.returncode != 0: return dict(r, reason=f'git diff lỗi: {d.stderr.strip()[:300]}')
    lines = [l for l in d.stdout.splitlines() if l.strip()]
    r['harness_diff'] = lines
    r['harness_added'] = [l.split('\t', 1)[1] for l in lines if l.startswith('A\t')]
    bad = [l for l in lines if not l.startswith('A\t')]
    if bad: return dict(r, reason=f'harness/ có file đã có bị sửa, xoá hoặc đổi tên sau tag: {bad[:5]}', harness_not_added=bad)
    st = _git(repo, 'status', '--porcelain', '--untracked-files=no', '--', 'harness/')
    if st.returncode != 0: return dict(r, reason=f'git status lỗi: {st.stderr.strip()[:300]}')
    if st.stdout.strip(): return dict(r, reason=f'harness/ có thay đổi chưa commit: {st.stdout.split()[:6]}')
    return dict(r, ok=True, reason='ok')


# ---------------- mẫu phân tầng cho dryrun ----------------
def stratified_sample(cases, fraction, seed, kind):
    """Mẫu phân tầng theo nhóm: mỗi nhóm có mặt lấy max(1, round(fraction * số case)) case (không quá số case), chọn bằng
    random.Random('<seed>/<kind>/<nhóm>') trên danh sách đã sắp xếp, nên tất định và không phụ thuộc thứ tự đầu vào.
    Trả về (danh sách case đã sắp xếp, {nhóm: {n_sample, n_cases}})."""
    if not 0 < fraction <= 1: raise ValueError(f'fraction phải trong (0, 1]: {fraction}')
    by = collections.defaultdict(list)
    for b, c in sorted(set(cases)): by[group_of(b)].append((b, c))
    out, info = [], {}
    for g in sorted(by):
        cs = by[g]; n = min(len(cs), max(1, round(fraction * len(cs))))
        out += random.Random(f'{seed}/{kind}/{g}').sample(cs, n)
        info[g] = dict(n_sample=n, n_cases=len(cs))
    return sorted(out), info


# ---------------- chọn cặp ----------------
def main_pairs(kind):
    """Cặp của RQ1 lượt chính: đúng pairs.prep_pairs(kind) (P_rep, gồm 'via', 'so_alias', 'no_input')."""
    return PR.prep_pairs(kind)


def rq2_rows(kind, census=None, reports=None):
    """R_run của RQ2 lượt chính: rq2.r_run(kind, pilot=False), nguồn mặc định rq2.CENSUS (census-lib-c7i cho library)."""
    return R2.r_run(kind, pilot=False, census=census, reports=reports)


def _by_case(rows):
    d = collections.defaultdict(list)
    for r in rows: d[(r['bundle'], r['tractor_case'])].append(r)
    return d


def _parse_cases(s):
    out = []
    for x in s.split(','):
        x = x.strip()
        if not x: continue
        b, c = x.split('/', 1); out.append((b, c))
    return out


def theta_of(kind, level=None, budget=None, afl_execs=None, n_inputs=None):
    """theta từ --level (harness.sweep.LEVELS) và/hoặc số tường minh; phải đủ và khớp. Trả về (theta, nhãn mức)."""
    from .sweep import LEVELS
    given = dict(budget=budget, afl_execs=afl_execs) if kind == 'exe' else dict(n_inputs=n_inputs)
    other = dict(n_inputs=n_inputs) if kind == 'exe' else dict(budget=budget, afl_execs=afl_execs)
    if any(v is not None for v in other.values()):
        raise SystemExit(f'tham số ngân sách {sorted(k for k, v in other.items() if v is not None)} không thuộc kind {kind}')
    if level is not None:
        if level not in LEVELS: raise SystemExit(f'mức không hợp lệ: {level}')
        th = dict(LEVELS[level][kind])
        for k, v in given.items():
            if v is not None and v != th[k]: raise SystemExit(f'--{k.replace("_", "-")} {v} khác mức {level} ({th[k]})')
        return th, level
    if any(v is None for v in given.values()):
        raise SystemExit(f'thiếu ngân sách: cần --level hoặc đủ {sorted(given)} (L* do Le chọn, không có mặc định)')
    th = {k: int(v) for k, v in given.items()}
    lv = next((L for L, t in LEVELS.items() if t[kind] == th), None)
    return th, lv or 'custom'


def rq1_params(kind, tag, seeds, workers, timeout, theta, n_cases, n_pairs, B):
    """Tham số manifest như rq1.main (cùng khoá, để merge_shards so SAME_PARAMS và metrics đọc như lượt pilot)."""
    return dict(cmd='rq1', kind=kind, tag=tag, pilot=False, seeds=seeds, workers=workers, timeout=timeout,
                theta=theta, n_cases=n_cases, n_pairs=n_pairs, build_dir=B,
                stab_reps=R1.STAB_REPS, san_timeout_factor=R1.SAN_TIMEOUT_FACTOR, input_domain='utf8_runner',
                san_ub_markers=[m.decode() for m in R1.SAN_UB_MARKERS], san_header=R1.SAN_HEADER.pattern.decode(),
                san_mem_markers=[m.decode() for m in R1.SAN_MEM_MARKERS], exe_san_env=R1.EXE_SAN_ENV, lib_san_env=R1.LIB_SAN_ENV,
                mem_limit=OB.MEM_LIMIT, argv0=OB.ARGV0.decode(), compare_stderr=True, output_cap_sens=R1.OUTPUT_CAP_SENS,
                exe_case_timeout=dict(rule='max(timeout, ceil(factor * max_c_secs))', factor=R1.C_TIME_FACTOR,
                                      table='harness/data/exe-c-time.json', table_sha256=R1.C_TIME_SHA),
                p_rep_source=PR.source_info(kind),
                insensitive_seed=INSENSITIVE_SEED, output_cap=OB.OUTPUT_CAP, timeout_rerun_factor=TIMEOUT_RERUN_FACTOR,
                generator=R1.gen_params(), files=dict(div='div/*.jsonl.gz (nén khi case xong)',
                                                      inputs='inputs/*.inputs.jsonl.gz (gồm input tầng A)'))


def _guard_out(out, mode, tag, freeze):
    """Chặn lẫn đầu ra: tên thư mục theo chế độ; thư mục đã có manifest thì phải cùng chế độ, cùng tag freeze, cùng nhãn."""
    p = os.path.abspath(out)
    if mode == 'dryrun' and 'dryrun' not in p: raise SystemExit(f'dryrun: đường dẫn --out phải chứa "dryrun": {p}')
    if mode == 'main' and 'dryrun' in p: raise SystemExit(f'lượt chính: đường dẫn --out không được chứa "dryrun": {p}')
    mf = f'{out}/manifest.json'
    if os.path.exists(mf):
        try: old = json.load(open(mf))
        except ValueError: raise SystemExit(f'manifest cũ không đọc được: {mf}')
        om = old.get('params', {}).get('main_run') or {}
        if om.get('mode') != mode: raise SystemExit(f'thư mục {out} đã có kết quả chế độ {om.get("mode")!r}, không phải {mode!r}')
        if old['params'].get('tag') != tag: raise SystemExit(f'thư mục {out} đã có kết quả nhãn {old["params"].get("tag")!r}, không phải {tag!r}')
        if mode == 'main' and (om.get('freeze') or {}).get('tag_commit') != freeze.get('tag_commit'):
            raise SystemExit(f'thư mục {out} đã có kết quả ở tag freeze khác')
    if mode == 'dryrun':
        os.makedirs(out, exist_ok=True)
        open(f'{out}/DRYRUN.txt', 'w').write(DRYRUN_BANNER + '\n')


def _select(all_cases, a, mode, kind):
    """Danh sách case của lần chạy: toàn bộ (main) hoặc mẫu (dryrun), rồi --cases (phải thuộc danh sách đó), rồi --shard."""
    sample = None
    cases = sorted(all_cases)
    if mode == 'dryrun':
        cases, info = stratified_sample(cases, a.dryrun_sample, a.sample_seed, kind)
        sample = dict(fraction=a.dryrun_sample, seed=a.sample_seed, groups=info, cases=[f'{b}/{c}' for b, c in cases])
    if a.cases:
        req = _parse_cases(a.cases); bad = [x for x in req if x not in set(cases)]
        if bad: raise SystemExit(f'--cases ngoài {"mẫu dryrun" if mode == "dryrun" else "danh sách cặp"}: {bad[:5]}')
        cases = req
    return PR.shard(cases, a.shard), sample


def _mode_info(a, mode, freeze, sample, extra):
    d = dict(mode=mode, selection=extra, shard=a.shard, cases_arg=bool(a.cases), sample=sample, freeze=freeze)
    if mode == 'dryrun': d['DRYRUN'] = DRYRUN_BANNER
    return d


def _finish(out, t0, kind, n_jobs, workers, fname):
    json.dump(dict(wall_secs=round(time.time() - t0, 2), workers=workers, n_jobs=n_jobs), open(f'{out}/{fname}-{kind}.json', 'w'))
    m = json.load(open(f'{out}/manifest.json'))
    m.update(finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), wall_secs=round(time.time() - t0, 2))
    json.dump(m, open(f'{out}/manifest.json', 'w'), indent=1, ensure_ascii=False)


def run_rq1(a, mode, freeze):
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/main-run'))
    theta, level = theta_of(a.kind, a.level, a.budget, a.afl_execs, a.n_inputs)
    tag = 'dryrun' if mode == 'dryrun' else f'main-{level}'
    by_case = _by_case(main_pairs(a.kind))
    pil = PILOT_EXE if a.kind == 'exe' else PILOT_LIB
    assert not set(by_case) & pil, 'P_rep có case pilot'
    cases, sample = _select(by_case, a, mode, a.kind)
    seeds = list(MAIN_SEEDS) if mode == 'main' else [int(s) for s in a.seeds.split(',')]
    _guard_out(a.out, mode, tag, freeze)
    os.makedirs(a.out, exist_ok=True)
    params = rq1_params(a.kind, tag, seeds, a.workers, a.timeout, theta, len(cases), sum(len(by_case[c]) for c in cases), B)
    params.update(level=level, main_run=_mode_info(a, mode, freeze, sample, 'harness.pairs.prep_pairs(kind)'),
                  p_rep_env={k: os.environ.get(k) for k in LIB_ENV})
    if mode == 'dryrun': params['DRYRUN'] = DRYRUN_BANNER
    manifest(a.out, params)
    open(f'{a.out}/cases.txt', 'w').write(''.join(f'{b}/{c}\n' for b, c in cases))
    store = Store(f'{a.out}/rq1-{a.kind}.jsonl')
    if a.kind == 'lib': BD.setup_cando2(B)
    fn = R1.rq1_exe_case if a.kind == 'exe' else R1.rq1_lib_case
    todo = []
    for sd in seeds:
        for bundle, case in cases:
            if store.has(f'{bundle}/{case}/s{sd}'): continue
            div = f'{a.out}/div/{bundle}__{case}__s{sd}.jsonl'; os.makedirs(os.path.dirname(div), exist_ok=True)
            R1.reset_case_files(div)
            todo.append((fn, B, bundle, case, by_case[(bundle, case)], sd, theta, a.timeout, div, tag))
    print(f'main_run rq1 {a.kind} {tag} ({mode}): {len(todo)} (case, seed) cần chạy, {a.workers} worker', flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(R1._safe, *t): t for t in todo}
        for fut in as_completed(futs):
            t = futs[fut]; r = fut.result()
            if r.get('status') == 'harness_error':
                r.update(key=f'{t[2]}/{t[3]}/s{t[5]}#error', kind=a.kind, bundle=t[2], case=t[3], seed=t[5],
                         pair_status={p['system']: 'harness_error' for p in t[4]})
            compress_files(R1.case_files(t[8]))
            store.put(r)
            print(r.get('key'), r.get('status'), r.get('secs'), r.get('n_inputs'), flush=True)
    _finish(a.out, t0, a.kind, len(todo), a.workers, 'wall')


def run_rq2(a, mode, freeze):
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/main-run'))
    tag = 'dryrun' if mode == 'dryrun' else 'main'
    rows = rq2_rows(a.kind, a.r_run_census, a.r_run_reports)
    pil = PILOT_EXE if a.kind == 'exe' else PILOT_LIB
    assert not any((r['bundle'], r['tractor_case']) in pil for r in rows), 'R_run có bản pilot'
    by_case = _by_case(rows)
    cases, sample = _select(by_case, a, mode, a.kind)
    _guard_out(a.out, mode, tag, freeze)
    os.makedirs(a.out, exist_ok=True)
    cp, tp = R2.CENSUS[a.kind]
    sel = [r for c in cases for r in by_case[c]]
    params = dict(cmd='rq2', kind=a.kind, tag=tag, pilot=False, workers=a.workers, timeout=a.timeout, reps=R2.REPS,
                  rerun_factor=TIMEOUT_RERUN_FACTOR, census=a.r_run_census or cp, reports=a.r_run_reports or tp,
                  n_r_run=len(sel), n_r_run_all=len(rows), n_timeout_only=sum(r['timeout_only'] for r in sel),
                  main_run=_mode_info(a, mode, freeze, sample, 'harness.rq2.r_run(kind, pilot=False)'))
    if mode == 'dryrun': params['DRYRUN'] = DRYRUN_BANNER
    manifest(a.out, params)
    open(f'{a.out}/cases.txt', 'w').write(''.join(f'{b}/{c}\n' for b, c in cases))
    store = Store(f'{a.out}/rq2-{a.kind}.jsonl')
    if a.kind == 'lib': BD.setup_cando2(B)
    todo = [r for r in sel if not store.has(f'{r["system"]}/{r["bundle"]}/{r["tractor_case"]}')]
    tb = _by_case(todo)
    print(f'main_run rq2 {a.kind} ({mode}): {len(todo)} bản cần chạy, {len(tb)} case, {a.workers} worker', flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(R2.rq2_case, B, a.kind, rs, a.timeout) for _, rs in sorted(tb.items())]
        for f in as_completed(futs):
            for r in f.result():
                store.put(r); print(r.get('key'), r.get('outcome') or r.get('status'), r.get('reasons'), flush=True)
    _finish(a.out, t0, a.kind, len(todo), a.workers, 'wall-rq2')


def list_cases(kind, rq, path, census=None, reports=None):
    rows = main_pairs(kind) if rq == 1 else rq2_rows(kind, census, reports)
    cs = sorted(_by_case(rows))
    open(path, 'w').write(''.join(f'{b}/{c}\n' for b, c in cs))
    return cs


def build_parser():
    ap = argparse.ArgumentParser(prog='harness.main_run')
    ap.add_argument('--rq', type=int, choices=[1, 2], default=1)
    ap.add_argument('--kind', choices=['exe', 'lib'], required=True); ap.add_argument('--out')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--freeze-tag', help='lượt chính: tag Protocol Freeze (kiểm luật kế thừa tag cho harness/)')
    g.add_argument('--dryrun-sample', type=float, metavar='FRACTION', help='chạy thử trên mẫu phân tầng, không đòi tag')
    g.add_argument('--list-cases', metavar='FILE', help='ghi danh sách case (bundle/case) của P_rep hoặc R_run rồi thoát')
    ap.add_argument('--sample-seed', type=int, default=0)
    ap.add_argument('--seeds', default='0,1,2', help='chỉ dùng ở dryrun; lượt chính luôn 0,1,2')
    ap.add_argument('--level', help='x1|x3|x10 (harness.sweep.LEVELS)')
    ap.add_argument('--budget', type=int); ap.add_argument('--afl-execs', type=int); ap.add_argument('--n-inputs', type=int)
    ap.add_argument('--workers', type=int, default=6); ap.add_argument('--timeout', type=int, default=10)
    ap.add_argument('--shard'); ap.add_argument('--cases', help='bundle/case, phân cách bằng dấu phẩy')
    ap.add_argument('--r-run-census', help='RQ2: census thay rq2.CENSUS (mặc định giữ nguồn của rq2)')
    ap.add_argument('--r-run-reports', help='RQ2: tarball báo cáo đi cùng --r-run-census')
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.list_cases:
        cs = list_cases(a.kind, a.rq, a.list_cases, a.r_run_census, a.r_run_reports)
        print(f'{len(cs)} case -> {a.list_cases}'); return
    if not a.out: raise SystemExit('thiếu --out')
    if bool(a.r_run_census) != bool(a.r_run_reports): raise SystemExit('--r-run-census và --r-run-reports đi cùng nhau')
    if a.rq == 1 and (a.r_run_census or a.r_run_reports): raise SystemExit('--r-run-* chỉ dùng cho --rq 2')
    if a.dryrun_sample is not None:
        mode, freeze = 'dryrun', dict(tag='dryrun', ok=None, reason='dryrun: không kiểm tag')
    elif a.freeze_tag:
        mode, freeze = 'main', freeze_check(a.freeze_tag)
        if not freeze['ok']: raise SystemExit(f'Từ chối lượt chính: {freeze["reason"]}')
        if a.seeds != '0,1,2': raise SystemExit('lượt chính luôn chạy seed 0,1,2; --seeds chỉ dùng ở dryrun')
        if a.kind == 'lib' and a.rq == 1 and not all(os.environ.get(k) for k in LIB_ENV):
            raise SystemExit(f'lượt chính library cần {LIB_ENV} (census lần ba, ci/p-rep-lib3.sh)')
        if a.kind == 'lib' and a.rq == 1 and (PR.DEFAULT['lib']['census'], PR.DEFAULT['lib']['recheck']) != tuple(os.environ[k] for k in LIB_ENV):
            raise SystemExit('pairs.DEFAULT library không khớp biến môi trường (biến phải đặt trước khi tiến trình khởi động)')
    else:
        raise SystemExit('Cần --freeze-tag T (lượt chính) hoặc --dryrun-sample F (chạy thử); lượt chính không chạy khi thiếu tag.')
    if a.rq == 2 and any(v is not None for v in (a.level, a.budget, a.afl_execs, a.n_inputs)):
        raise SystemExit('RQ2 không có tham số ngân sách')
    (run_rq1 if a.rq == 1 else run_rq2)(a, mode, freeze)


if __name__ == '__main__':
    main()
