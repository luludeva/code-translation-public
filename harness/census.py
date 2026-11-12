"""Census library trên package harness (kế hoạch A3-A7 mục 2.3, Q8 (a), Le chọn 25/10): tái lập verdict TRACTOR cho mọi cặp
(library, hệ), rồi kiểm lại các cặp công bố đỗ mà tái lập trượt.

Port của `experiments/06-library-census/scripts/census_lib.py`, `recheck_loss.py` và `census_lib_c7i.py` (bản chạy trên c7i: tuần tự,
kiểm lại lấy từ census mới). Lý do port: hai script cũ gọi runner bằng `subprocess.run` (census_lib.py dòng 26-31), không session riêng,
không kill nhóm tiến trình, không TMPDIR riêng; bản sửa tiến trình mồ côi (decision-log 2026-10-23) chỉ nằm trong `observe._run_lib`.
Ở đây mọi lần gọi runner đi qua `observe.run_lib` (session riêng, kill nhóm sau mỗi lần gọi, TMPDIR riêng, trần output mỗi luồng), và
sau mỗi cặp đếm tiến trình runner còn sống mà trưởng session đã chết (`orphans`; chốt chặn: phải bằng 0, kế hoạch mục 3.5).

Verdict giữ đúng ngữ nghĩa census_lib.py (Q8 (a): phải khớp trên lần cũ; tests.test_census phát lại bản ghi đã lưu qua cả code cũ và
code này). Logic verdict tách thành hàm thuần trên quan sát: `tally`, `needs_full`, `run_verdict`, `pair_record`, `recheck_targets`,
`recheck_verdict`. Phần chạy chỉ thu quan sát (`census_pair`, `recheck_pair`).

Giữ như census_lib.py:
  - nguồn Rust `verified/` nếu có, ngược lại `translated/`; `RUSTC_BOOTSTRAP=1` khi source có `#![feature` (build.build_rust_lib);
  - lượt nhanh timeout 10 giây; cặp công bố đỗ mà có vector không Pass, Skip thì chạy lại mọi vector với 120 giây;
  - đỗ khi mọi vector Pass hoặc Skip, gồm đỗ với 0 vector;
  - không thấy lib<library>.so đúng tên thì census ghi build_ok false (build_rust_lib có alias, nhưng census không dùng alias; alias
    chỉ ở bước kiểm lại, như recheck_loss.py); trường `so_alias_found` chỉ để tham khảo;
  - không đặt CANDO2_STATE_DUMP (bản vá không hoạt động, verdict như cando2 gốc) và không đặt trần bộ nhớ ảo (run_lib dump=False,
    mem_limit=0); runner dùng bản vá v2 của harness thay bản exp 05, hai bản chỉ khác nhánh dump;
  - kiểm lại: tuần tự, 120 giây, 3 lần; ổn định khi ba lần cho cùng kết quả từng vector; đỗ khi cả ba lần có kết quả và mọi vector
    Pass, Skip.

Khác census_lib.py (cách thu quan sát, không đổi luật verdict):
  - runner chạy từng vector một (`--vectors <file>`), như V5; TRACTOR chạy mỗi vector trong một tiến trình con procspawn riêng nên
    kết quả từng vector không phụ thuộc cách gọi. Tập vector như `TestVector::load_all` của cando2: file đuôi json (không phân biệt hoa
    thường), bỏ file rỗng. Một vector không có report (runner lỗi hạ tầng) thì cả lần chạy coi như không có report (run_ok false), như
    runner cũ dừng cả lượt khi gặp lỗi CatastrophicError;
  - một luồng output vượt observe.OUTPUT_CAP thì runner bị dừng, vector mang result `OutputLimit` (nhãn mới, không Pass; trên dữ liệu
    cũ output dài nhất trong report là khoảng 3,6 nghìn ký tự, sơ bộ, đếm bằng script);
  - không thử lại khi lỗi hạ tầng (run_lib, không phải run_lib_retry): census_lib.py không thử lại;
  - C build kèm C-san (build.build_lib_case); C-san không dùng ở census;
  - report kiểm lại ghi ở `recheck-reports/` thay vì chung `reports/` (tránh trùng khoá case trong rq2._report_members).

Quirk của code cũ được giữ: lần chạy 120 giây không ghi report thì census_lib.py đọc lại report của lần 10 giây còn trên đĩa, nên
results là của lần 10 giây với timeout_used 120 (run_verdict giữ y như vậy).

Chạy (máy đo; corpus ở $CORPUS):
  python3 -m harness.census --out DIR [--build DIR] [--workers 1] [--cases b/c,...] [--systems s,...] [--no-recheck]
Đầu ra trong DIR: census-lib.jsonl (resume theo `key`), census-lib-c-side.json, recheck-loss.jsonl, reports/, recheck-reports/,
manifest.json. Thư mục build mặc định ~/build/census (riêng, không dùng chung cache của RQ1, vì build Rust bị xoá sau mỗi cặp)."""
import argparse, collections, csv, glob, json, os, shutil, signal, time
from concurrent.futures import ProcessPoolExecutor, as_completed

from . import build as BD
from . import observe as OB
from .config import NO_INPUT_LIB, PILOT_LIB, REPO, SYSTEMS, T
from .record import Store, manifest

MAP = f'{REPO}/experiments/02-harvest-repro/data/case-name-map.tsv'
PASSING = ('Pass', 'Skip')
TIMEOUT, TIMEOUT_FULL = 10, 120          # census_lib.py dòng 23
REPS, TO = 3, 120                        # recheck_loss.py dòng 17
PILOT = {c for _, c in PILOT_LIB}        # census_lib.py: tên case của spike_lib.SAMPLE
NO_INPUT = NO_INPUT_LIB


# ======================================================================================================================================
# Verdict: hàm thuần trên quan sát. report = {tên vector: mục report của runner (có 'result')} hoặc None khi runner không ghi report.
def tally(report):
    """(số vector theo result, số vector), như census_lib.tally."""
    return dict(collections.Counter(v['result'] for v in report.values())), len(report)


def passed(counts):
    return all(k in PASSING for k in counts)


def needs_full(pub_passed, counts):
    """Chạy lại 120 giây: công bố đỗ mà có vector không Pass, Skip (census_lib.py dòng 108)."""
    return bool(pub_passed) and any(k not in PASSING for k in counts)


def run_verdict(pub_passed, rep_fast, rep_full=None):
    """Các trường chạy của bản ghi census. rep_full: report lần 120 giây (None khi không chạy hoặc runner không ghi report)."""
    if rep_fast is None: return dict(timeout_used=TIMEOUT, run_ok=False)
    counts, n = tally(rep_fast); used = TIMEOUT
    if needs_full(pub_passed, counts):
        used = TIMEOUT_FULL
        if rep_full is not None: counts, n = tally(rep_full)    # None: giữ kết quả lần nhanh, như census_lib.py (quirk, xem docstring)
    elif rep_full is not None:
        raise ValueError('có report 120 giây cho cặp không cần chạy lại')
    return dict(timeout_used=used, run_ok=True, vectors=n, results=counts, ours_passed=passed(counts))


def pair_record(row, system, case, art, build=None, run=None):
    """Bản ghi census của một cặp, cùng trường và thứ tự như census_lib.one.
    row: dòng case-name-map (bundle, tractor_case, harvest_case); case: dict(n_vectors, runner_ok, c_ok, library);
    art: dict(source_dir, pub: nội dung result.json công bố hoặc None khi không có);
    build: dict(rc_ok, so_ok, so_found, log, rustc_bootstrap, secs); run: dict(rep_fast, rep_full, secs)."""
    b, tc, hc = row['bundle'], row['tractor_case'], row['harvest_case']
    rec = dict(bundle=b, tractor_case=tc, harvest_case=hc, system=system, pilot=tc in PILOT, no_input=tc in NO_INPUT,
               n_vectors=case['n_vectors'], source_dir=art['source_dir'])
    pj = art['pub']
    if pj is None:
        rec.update(stage='P0_missing_artifact'); return rec
    rec.update(pub_passed=bool(pj.get('passed')), pub_vectors_failed=pj.get('vectors_failed'), pub_error=pj.get('error'))
    if not (case['runner_ok'] and case['c_ok']):
        rec.update(stage='harness_case_fail'); return rec
    rec['rustc_bootstrap'] = build['rustc_bootstrap']; rec['build_secs'] = build['secs']
    if not build['rc_ok']:
        rec.update(build_ok=False, build_log_tail=(build.get('log') or '')[-1500:]); return rec
    if not build['so_ok']:
        rec.update(build_ok=False, build_log_tail='no lib%s.so; found: %s' % (case['library'], ','.join(build['so_found']))); return rec
    rec['build_ok'] = True
    rec['run_secs'] = run['secs']
    rv = run_verdict(rec['pub_passed'], run['rep_fast'], run.get('rep_full'))
    rec['timeout_used'] = rv.pop('timeout_used'); rec.update(rv)
    return rec


def recheck_targets(census):
    """Cặp kiểm lại: không pilot, có input, công bố đỗ, tái lập không đỗ (recheck_loss.targets, census_lib_c7i.targets)."""
    return [r for r in census if not r['pilot'] and not r['no_input'] and r.get('pub_passed') is True and not r.get('ours_passed')]


def rep_summary(report):
    """Một lần kiểm lại: kết quả và diff (600 ký tự) từng vector, như recheck_loss.recheck."""
    if report is None: return {}
    return dict(results={v: report[v]['result'] for v in sorted(report)},
                diffs={v: report[v].get('diff', '')[:600] for v in sorted(report) if report[v]['result'] not in PASSING})


def recheck_verdict(reps):
    """reps: các dict có 'results' (thiếu khi runner không ghi report). Trả về stable, ours_passed như recheck_loss.recheck.
    Lưu ý (giữ nguyên): ở đây 0 vector là không đỗ (results rỗng), khác census (0 vector là đỗ); cặp 0 vector không bao giờ thành
    đích kiểm lại vì census đã cho đỗ."""
    outs = [json.dumps(x.get('results'), sort_keys=True) for x in reps]
    return dict(stable=len(set(outs)) == 1,
                ours_passed=all(x.get('results') and all(v in PASSING for v in x['results'].values()) for x in reps))


def build_obs(info, library):
    """Quan sát build từ build.build_rust_lib cho census: so_ok chỉ khi có lib<library>.so đúng tên (không tính alias)."""
    log = info.get('log') or ''
    if info.get('ok') and not info.get('so_alias'):
        so = dict(rc_ok=True, so_ok=True, so_found=[])
    elif info.get('ok'):                                   # build_rust_lib đã alias: census cũ coi là thiếu .so
        so = dict(rc_ok=True, so_ok=False, so_found=[info['so_alias'].split(' -> ')[0]])
    elif log.startswith('so: '):                           # cargo đỗ, không có hoặc có nhiều .so
        so = dict(rc_ok=True, so_ok=False, so_found=[x for x in log[4:].split(',') if x] if log[4:] else [])
    else:
        so = dict(rc_ok=False, so_ok=False, so_found=[])
    return dict(so, log=log, rustc_bootstrap=info.get('rustc_bootstrap'), secs=round(info.get('secs') or 0, 1))


# ======================================================================================================================================
# Thu quan sát
def vector_files(troot):
    """Tập vector runner nạp khi không truyền --vectors (cando2 TestVector::load_all): file đuôi json, không phân biệt hoa thường,
    bỏ file rỗng (0 byte)."""
    d = f'{troot}/test_vectors'
    if not os.path.isdir(d): return []
    return sorted(e.path for e in os.scandir(d) if e.is_file() and os.path.splitext(e.name)[1].lower() == '.json'
                  and os.path.getsize(e.path) > 0)


def n_vectors(troot):
    """Như census_lib.prepare_case: số file *.json có nội dung sau strip (chỉ để ghi, không dùng cho verdict)."""
    def nonblank(f):
        with open(f) as fh: return bool(fh.read().strip())
    return len([f for f in glob.glob(f'{troot}/test_vectors/*.json') if nonblank(f)])


def run_report(runner_bin, root, vecs, timeout, rust, work):
    """Chạy mọi vector qua observe.run_lib, gộp thành report kiểu runner {tên vector: mục}. None khi một vector không có report."""
    os.makedirs(work, exist_ok=True)
    report, t0 = {}, time.time()
    for f in vecs:
        name = os.path.basename(f); dump = os.path.join(work, name + '.dump'); repf = dump + '.report.json'
        o = OB.run_lib(runner_bin, root, f, timeout, rust, dump, keep_files=True, dump=False, mem_limit=0)
        entry = None
        if o.get('output_limit'):
            entry = dict(result='OutputLimit', harness=dict(tmp_bytes=o.get('tmp_bytes')))
        elif os.path.exists(repf):
            try:
                with open(repf) as fh: entry = list(json.load(fh).values())[0]
            except Exception: entry = None
        for x in (dump, repf):
            if os.path.exists(x): os.remove(x)
        if not isinstance(entry, dict) or 'result' not in entry:
            return None, round(time.time() - t0, 1), dict(vector=name, k1=o.get('k1'), msg=(o.get('infra_msg') or '')[-800:])
        report[name] = entry
    return report, round(time.time() - t0, 1), None


def _stat(pid):
    with open(f'/proc/{pid}/stat') as f: s = f.read()
    rest = s[s.rindex(')') + 2:].split()
    return int(rest[1]), int(rest[3])          # ppid, session


def orphans(runner_dir, kill=True):
    """Tiến trình runner (argv hoặc exe nằm dưới runner_dir) còn sống mà trưởng session đã chết hoặc cha là PID 1.
    run_lib khởi chạy runner trong session riêng (trưởng session là runner), nên tiến trình con thoát được kill nhóm sẽ rơi vào nhóm này.
    kill=True thì dừng chúng (SIGKILL) sau khi đếm, để cặp sau không bị tranh tài nguyên. Trả về danh sách pid."""
    out = []
    for p in os.listdir('/proc'):
        if not p.isdigit() or int(p) == os.getpid(): continue
        try:
            with open(f'/proc/{p}/cmdline', 'rb') as f: argv = f.read().split(b'\0')
            try: exe = os.readlink(f'/proc/{p}/exe')
            except OSError: exe = ''
            if not (exe.startswith(runner_dir) or any(a.decode('utf-8', 'replace').startswith(runner_dir) for a in argv if a)):
                continue
            ppid, sid = _stat(p)
            if ppid == 1 or not os.path.exists(f'/proc/{sid}'): out.append(int(p))
        except (OSError, ValueError):
            continue
    if kill:
        for p in out:
            try: os.kill(p, signal.SIGKILL)
            except OSError: pass
    return out


def _load(path):
    with open(path) as f: return json.load(f)


def _save(path, report):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f: json.dump(report, f)


def _drop_rust(B, s, b, tc):
    """Xoá build Rust của cặp và marker cache (census_lib.py xoá thư mục build sau mỗi cặp; ổ máy đo không chứa đủ 2.290 build)."""
    td = f'{B}/rust-lib/{s}/{b}/{tc}'
    shutil.rmtree(td, ignore_errors=True)
    for x in (f'{td}.build.json', f'{td}.build.json.lock'):
        if os.path.exists(x): os.remove(x)


def prepare_case(B, out, b, tc):
    """Runner, C (và C-san) qua build.build_lib_case; chạy C trên vector công khai, ghi reports/C/<bundle>/<case>.json."""
    info = BD.build_lib_case(B, b, tc); troot = f'{T}/{b}/{tc}'
    c = dict(bundle=b, case=tc, library=info['library'], runner_ok=info['runner_ok'], runner_bin=info['runner_bin'],
             c_so=info['c_ok'], n_vectors=n_vectors(troot))
    for k in ('runner_log', 'c_log'):
        if info.get(k): c[k] = info[k][-1500:]
    if info['runner_ok'] and info['c_ok']:
        root = BD.lib_root(B, info, 'c', tag='census-C')
        rep, secs, err = run_report(info['runner_bin'], root, vector_files(troot), TIMEOUT, False, f'{B}/census-work/C')
        c['c_results'] = tally(rep)[0] if rep is not None else None
        c['c_secs'] = secs
        if rep is not None: _save(f'{out}/reports/C/{b}/{tc}.json', rep)
        if err: c['c_run_error'] = err
    c['orphans_after'] = len(orphans(os.path.dirname(info['runner_bin'])))
    return c, info


def census_pair(B, out, case, info, row, s):
    """Một cặp (library, hệ): thu quan sát rồi gọi pair_record. case: dict của prepare_case; info: build.build_lib_case."""
    b, tc, hc = row['bundle'], row['tractor_case'], row['harvest_case']
    src = BD.rust_src(s, b, hc)
    pub = _load(f'{src}/result.json') if os.path.exists(f'{src}/result.json') else None
    art = dict(source_dir=os.path.basename(src), pub=pub)
    cs = dict(n_vectors=case['n_vectors'], runner_ok=case['runner_ok'], c_ok=case['c_so'], library=case['library'])
    if pub is None or not (cs['runner_ok'] and cs['c_ok']):
        rec = pair_record(row, s, cs, art)
    else:
        bi = BD.build_rust_lib(B, s, b, tc, hc, case['library']); bo = build_obs(bi, case['library'])
        run = None
        if bo['rc_ok'] and bo['so_ok']:
            root = BD.lib_root(B, info, 'rust', bi['dir'], tag=f'census-{s}')
            vecs = vector_files(f'{T}/{b}/{tc}'); work = f'{B}/census-work/{s}'
            rf, secs, err = run_report(case['runner_bin'], root, vecs, TIMEOUT, True, work)
            rfull = None
            if rf is not None and needs_full(bool(pub.get('passed')), tally(rf)[0]):
                rfull, _, err2 = run_report(case['runner_bin'], root, vecs, TIMEOUT_FULL, True, work)
                err = err or err2
            final = rfull if rfull is not None else rf
            if final is not None: _save(f'{out}/reports/{s}/{b}/{tc}.json', final)
            run = dict(rep_fast=rf, rep_full=rfull, secs=secs)
        rec = pair_record(row, s, cs, art, bo, run)
        if bi.get('so_alias'): rec['so_alias_found'] = bi['so_alias']
        if run is not None and err: rec['run_error'] = err
        _drop_rust(B, s, b, tc)
    rec['key'] = f'{b}/{tc}/{s}'
    rec['orphans_after'] = len(orphans(os.path.dirname(case['runner_bin'])))
    return rec


def recheck_pair(B, out, case, info, r):
    """Kiểm lại một cặp: build lại (alias .so khi chỉ có một .so lệch tên), 3 lần 120 giây, tuần tự (recheck_loss.recheck)."""
    b, tc, s = r['bundle'], r['tractor_case'], r['system']
    rec = dict(bundle=b, tractor_case=tc, system=s, census_results=r.get('results'), census_build=r.get('build_log_tail'))
    if not (case['runner_ok'] and case['c_so']):
        return dict(r, error='C hoặc runner không build được', c_results=case.get('c_results'))
    _drop_rust(B, s, b, tc)
    bi = BD.build_rust_lib(B, s, b, tc, r['harvest_case'], case['library'])
    if not bi['ok']:
        rec.update(build_ok=False, build_log_tail=(bi.get('log') or '')[-1500:])
    else:
        if bi.get('so_alias'): rec['so_alias'] = bi['so_alias']
        rec['build_ok'] = True
        root = BD.lib_root(B, info, 'rust', bi['dir'], tag=f'recheck-{s}')
        vecs = vector_files(f'{T}/{b}/{tc}'); rec['reps'] = []
        for k in range(REPS):
            rep, secs, err = run_report(case['runner_bin'], root, vecs, TO, True, f'{B}/census-work/recheck')
            one = dict(secs=secs, run_error=err, **rep_summary(rep))
            if rep is not None: _save(f'{out}/recheck-reports/{s}/{b}/{tc}.rep{k}.json', rep)
            rec['reps'].append(one)
        rec.update(recheck_verdict(rec['reps']))
    _drop_rust(B, s, b, tc)
    rec['c_results'] = case.get('c_results')
    rec['orphans_after'] = len(orphans(os.path.dirname(case['runner_bin'])))
    return rec


def rows_of(path=MAP, cases=None):
    with open(path) as f:
        rows = [r for r in csv.DictReader(f, delimiter='\t') if r['kind'] == 'lib' and r['bundle'] != 'Examples']
    if cases: rows = [r for r in rows if f"{r['bundle']}/{r['tractor_case']}" in cases]
    return rows


def _pair_job(B, out, case, info, row, s):
    try:
        return census_pair(B, out, case, info, row, s)
    except Exception:
        import traceback
        return dict(bundle=row['bundle'], tractor_case=row['tractor_case'], harvest_case=row['harvest_case'], system=s,
                    key=f"{row['bundle']}/{row['tractor_case']}/{s}#error", stage='harness_error', error=traceback.format_exc()[-3000:])


def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness.census')
    ap.add_argument('--out', required=True)
    ap.add_argument('--build', default=os.path.expanduser('~/build/census'), help='thư mục build riêng (build Rust bị xoá sau mỗi cặp)')
    ap.add_argument('--workers', type=int, default=1, help='mặc định 1: tuần tự như census c7i')
    ap.add_argument('--cases', help='bundle/case, phân cách bằng dấu phẩy (chạy thử)')
    ap.add_argument('--systems', help='hệ, phân cách bằng dấu phẩy (mặc định cả 10 hệ)')
    ap.add_argument('--map', default=MAP); ap.add_argument('--no-recheck', action='store_true')
    a = ap.parse_args(argv)
    B, out = os.path.abspath(a.build), os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True); os.makedirs(B, exist_ok=True)
    os.environ.setdefault('HARNESS_BUILD', B)      # bộ khởi chạy observe.launcher biên dịch vào đây
    systems = a.systems.split(',') if a.systems else list(SYSTEMS)
    rows = rows_of(a.map, set(a.cases.split(',')) if a.cases else None)
    manifest(out, dict(cmd='census', build_dir=B, workers=a.workers, timeout=TIMEOUT, timeout_full=TIMEOUT_FULL, recheck_reps=REPS,
                       recheck_timeout=TO, systems=systems, n_cases=len(rows), map=os.path.relpath(a.map, REPO),
                       state_dump=False, mem_limit=0, output_cap=OB.OUTPUT_CAP, retry_infra=False, runner_call='per_vector'))
    BD.setup_cando2(B)
    cside, infos = {}, {}
    for r in rows:
        k = (r['bundle'], r['tractor_case'])
        cside[k], infos[k] = prepare_case(B, out, *k)
        print('C', r['tractor_case'], cside[k].get('c_results'), 'mồ côi', cside[k]['orphans_after'], flush=True)
    json.dump({f'{k[0]}/{k[1]}': v for k, v in cside.items()}, open(f'{out}/census-lib-c-side.json', 'w'), indent=1)
    store = Store(f'{out}/census-lib.jsonl')
    jobs = [(B, out, cside[(r['bundle'], r['tractor_case'])], infos[(r['bundle'], r['tractor_case'])], r, s)
            for r in rows for s in systems if not store.has(f"{r['bundle']}/{r['tractor_case']}/{s}")]
    print(len(jobs), 'cặp', flush=True)
    t0 = time.time()
    def put(rec):
        store.put(rec)
        print(rec['system'], rec['tractor_case'], rec.get('build_ok'), rec.get('ours_passed'), 'mồ côi', rec.get('orphans_after'), flush=True)
    if a.workers <= 1:
        for j in jobs: put(_pair_job(*j))
    else:
        with ProcessPoolExecutor(a.workers) as ex:
            for f in as_completed([ex.submit(_pair_job, *j) for j in jobs]): put(f.result())
    census_secs = round(time.time() - t0, 1)
    if not a.no_recheck:
        with open(f'{out}/census-lib.jsonl') as f: census = [json.loads(l) for l in f if l.strip()]
        census = [r for r in census if r.get('stage') != 'harness_error']
        tg = recheck_targets(census); print(len(tg), 'cặp kiểm lại', flush=True)
        with open(f'{out}/recheck-loss.jsonl', 'w') as f:
            for r in tg:
                k = (r['bundle'], r['tractor_case'])
                rec = recheck_pair(B, out, cside[k], infos[k], r)
                f.write(json.dumps(rec, ensure_ascii=False) + '\n'); f.flush()
                print(r['system'], r['tractor_case'], rec.get('so_alias', ''), rec.get('ours_passed'), rec.get('stable'), flush=True)
    m = _load(f'{out}/manifest.json')
    m.update(finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), census_secs=census_secs,
             wall_secs=round(time.time() - t0, 1))
    json.dump(m, open(f'{out}/manifest.json', 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
