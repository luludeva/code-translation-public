"""Sinh bộ mutant cho A7 (b) và A3 (b), tách khỏi harness (`docs/proposal/a3-a7-package-plan.md` mục 2.2, 2.3, 3.2, 3.3; Le duyệt 25/10).

  python3 -m harness.mutants pairs --set a7-seed1|a3-seed2 --kind exe|lib [--systems s1,s2]
  python3 -m harness.mutants gen   --set a7-seed1|a3-seed2 --kind exe|lib --out DIR [--systems ..] [--cases bundle/case,..]
                                   [--dry-run [--no-coverage]]
  python3 -m harness.mutants check --set a7-seed1 --kind exe|lib (--identity DIR/identity-K.jsonl | --sites DIR/sites-K.jsonl)

Bộ (`SETS`): seed xáo vị trí, n mutant build được mỗi cặp, cặp, vị trí phải bỏ.
  a7-seed1: bộ seed 1 của exp 08 (bộ chọn ngân sách), cặp như `experiments/08-harness-v2/results/{exe,lib}/accept-*.json`; sinh lại
            phải trùng danh tính (`check`).
  a3-seed2: Q4 (b): P_rep trên case pilot (`rq1.pilot_pairs`), bỏ ba hệ đã dùng chỉnh harness (kiro, claude, c2rust) và case library
            không có trường input; seed 2; 12 mỗi cặp; bỏ vị trí đã có trong bộ seed 0 (exp 03, 04, 07) và seed 1 (exp 08).
Vị trí đột biến, toán tử, coverage, vector bắt: chép nguyên văn từ thí nghiệm (`harness/gen/mutants_v1.py`, `mutants_lib.py`,
`mutants_cov_exe.py`; `harness/gen/VENDOR-mutants.md`). Build mutant bằng `build._cargo` (RUSTC_BOOTSTRAP=1 chỉ khi có `#![feature`,
khác exp 08 luôn đặt; ghi `rustc_bootstrap` mỗi mutant). Mỗi mutant một thư mục và một tag `lib_root` riêng (rủi ro R7 của kế hoạch).

Đầu ra trong DIR: `mutants-<kind>.jsonl` (một bản ghi mỗi cặp, resume theo khoá), `identity-<kind>.jsonl` (một dòng mỗi mutant đã thử:
set, kind, system, bundle, case, id, file, line, col, op, before, after, built, sha256), `manifest.json`. `--dry-run`: không build
mutant, không chạy vector; ghi `sites-<kind>.jsonl` (mọi vị trí theo thứ tự chọn, sau khi bỏ vị trí trùng). `--no-coverage` (chỉ với
`--dry-run`): coi mọi dòng là được chạy, không build gì; chỉ để kiểm offline thứ tự vị trí.
`line` đánh số từ 1 như exp 08; `col`, `end` là chỉ số ký tự (từ 0) của đoạn bị thay trong dòng, đúng `m.start()`, `m.end()` của
`sites_of` (với toán tử, đoạn khớp gồm cả dấu cách hai bên).
Không chạy mutant qua oracle, không gán nhãn tương đương (Q5 là bước sau)."""
import argparse, collections, glob, json, os, random, shutil, traceback

from . import build as BD
from . import pairs as PR
from .config import NO_INPUT_LIB, PILOT_EXE, PILOT_LIB, REPO
from .gen import mutants_cov_exe as AE
from .gen import mutants_lib as ML
from .gen import mutants_v1 as MV
from .gen.v0 import load_vectors
from .record import Store, manifest

TUNING_SYSTEMS = ('kiro', 'claude', 'c2rust')     # ba hệ đã dùng chỉnh harness (exp 03 đến 08, 21)
EXP08 = {k: f'{REPO}/experiments/08-harness-v2/results/{k}/accept-{k}.json' for k in ('exe', 'lib')}
SEED0_FILES = dict(exe=('experiments/04-coverage-pilot/results/mutants/*.json', 'experiments/03-oracle-spike/results/mutants-*.json'),
                   lib=('experiments/07-library-controls/results/mutants/*.json',))
SETS = {
    'a7-seed1': dict(seed=1, n=12, pairs='exp08', exclude=()),
    'a3-seed2': dict(seed=2, n=12, pairs='prep-pilot-other', exclude=('seed0', 'seed1')),
}
IGNORE = shutil.ignore_patterns('target', 'logs', 'c_src')   # như exp 08 khi chép nguồn để đột biến


# ---------------- vị trí, toán tử ----------------
def ordered_sites(kind, wd, covered, seed):
    """Thứ tự vị trí như exp 08: exe xáo mọi vị trí rồi lọc dòng được chạy (`sites_cov`); lib lọc rồi xáo (`mutants_lib.sites_of`)."""
    if kind == 'exe':
        old = AE.MUT_SEED, MV.SEED
        AE.MUT_SEED = seed
        try: return AE.sites_cov(wd, covered)
        finally: AE.MUT_SEED, MV.SEED = old
    old = ML.SEED; ML.SEED = seed
    try: return ML.sites_of(wd, covered)
    finally: ML.SEED = old


def all_lines(wd, kind):
    """Mọi dòng của file nguồn mà `sites_of` duyệt (exe `src/*.rs`, lib `src/**/*.rs`), như nhánh V2_NO_COV, MUT_NO_COV."""
    pat = f'{wd}/src/*.rs' if kind == 'exe' else f'{wd}/src/**/*.rs'
    return {(os.path.relpath(f, wd), i + 1) for f in glob.glob(pat, recursive=True)
            for i in range(len(open(f, errors='ignore').read().split('\n')))}


def site_row(wd, site, cache=None):
    """Bản ghi danh tính của một vị trí, cắt chuỗi như exp 08 (`strip()[:160]`), không ghi file."""
    rel, i, a, b, rep, op = site
    if cache is None: cache = {}
    if rel not in cache:
        with open(f'{wd}/{rel}', errors='ignore') as f: cache[rel] = f.read().split('\n')
    orig = cache[rel][i]
    new = orig[:a] + rep + orig[b:]
    return dict(file=rel, line=i + 1, col=a, end=b, op=op, rep=rep, before=orig.strip()[:160], after=new.strip()[:160])


def apply_site(wd, site):
    """Áp mutant vào bản chép như vòng lặp exp 08; trả về nội dung cũ để khôi phục."""
    rel = site[0]; path = f'{wd}/{rel}'
    text = open(path, errors='ignore').read(); L = text.split('\n'); orig = L[site[1]]
    L[site[1]] = orig[:site[2]] + site[4] + orig[site[3]:]
    open(path, 'w').write('\n'.join(L))
    return path, text


def site_key(system, case, r):
    """Khoá vị trí: (hệ, case, file, dòng, op, before, after). Bản ghi cũ (exp 03, 04, 07, 08) không lưu cột; trên cùng nguồn, cột và
    phép thay xác định duy nhất chuỗi after của dòng, nên khoá này tương đương (file, dòng, cột, op) của kế hoạch mục 3.3."""
    return (system, case, r['file'], r['line'], r['op'], r['before'], r['after'])


def _mutant_lists(path):
    d = json.load(open(path))
    if isinstance(d, list):                      # exp 03: danh sách mutant, hệ và case nằm trong tên file
        system, case = os.path.basename(path)[len('mutants-'):-len('.json')].split('-', 1)
        yield system, case, d
    elif 'pairs' in d:                           # exp 08
        for p in d['pairs']: yield p['system'], p['case'], p.get('mutants', [])
    else:                                        # exp 04, 07: một cặp mỗi file
        yield d['system'], d['case'], d.get('mutants', [])


def prior_keys(kind, which):
    """Tập khoá vị trí của các bộ cũ: seed0 = exp 03, 04 (exe), exp 07 (lib); seed1 = exp 08. Gồm cả mutant không build được."""
    files = []
    if 'seed0' in which: files += [f for g in SEED0_FILES[kind] for f in sorted(glob.glob(f'{REPO}/{g}'))]
    if 'seed1' in which: files.append(EXP08[kind])
    keys = set()
    for f in files:
        for system, case, ms in _mutant_lists(f):
            keys |= {site_key(system, case, m) for m in ms}
    return keys


def drop_prior(system, case, rows, keys):
    keep = [r for r in rows if site_key(system, case, r) not in keys]
    return keep, len(rows) - len(keep)


# ---------------- cặp ----------------
def _hcase_map(kind):
    return {(r['bundle'], r['tractor_case']): r['harvest_case'] for r in PR.load(PR.DEFAULT[kind]['census'])}


def exp08_pairs(kind):
    """Cặp và thứ tự cặp của exp 08 (gồm cặp bị loại), bundle lấy từ danh sách pilot, tên case HARVEST từ census."""
    bundles = {c: b for b, c in (PILOT_EXE if kind == 'exe' else PILOT_LIB)}
    hc = _hcase_map(kind)
    out = []
    for p in json.load(open(EXP08[kind]))['pairs']:
        b = bundles[p['case']]
        out.append(dict(system=p['system'], bundle=b, case=p['case'], hcase=hc.get((b, p['case']), p['case'])))
    return out


def a3_pairs(kind, systems=None):
    """Q4 (b): P_rep trên case pilot (`rq1.pilot_pairs`, cùng luật P_rep), bỏ hệ đã dùng chỉnh harness và case library không có
    trường input. `systems` (danh sách) giới hạn thêm, khi Le chốt danh sách hệ khác mặc định."""
    from .config import SYSTEMS
    from .rq1 import pilot_pairs
    rows = [r for r in pilot_pairs(kind) if r['system'] not in TUNING_SYSTEMS and r['tractor_case'] not in NO_INPUT_LIB]
    if systems: rows = [r for r in rows if r['system'] in systems]
    rows.sort(key=lambda r: (r['bundle'], r['tractor_case'], SYSTEMS.index(r['system'])))
    return [dict(system=r['system'], bundle=r['bundle'], case=r['tractor_case'], hcase=r['harvest_case']) for r in rows]


def set_pairs(name, kind, systems=None):
    spec = SETS[name]
    if spec['pairs'] == 'exp08':
        ps = exp08_pairs(kind)
        return [p for p in ps if p['system'] in systems] if systems else ps
    return a3_pairs(kind, systems)


def pair_key(name, kind, p): return f"{name}/{kind}/{p['bundle']}/{p['case']}/{p['system']}"


# ---------------- build mutant ----------------
def build_mutant(kind, B, src, pdir, mid, library=None):
    """Build bản chép đã đột biến bằng `build._cargo`; artefact chép sang `pdir/m<id>/` (exe `driver`; lib
    `target/release/lib<library>.so`, đúng chỗ runner tìm khi trỏ `translated_rust` vào thư mục mutant)."""
    td = f'{pdir}/target'; rel = f'{td}/release'
    for p in glob.glob(f'{rel}/*'):          # bỏ artefact của mutant trước: build hỏng không được để lại binary cũ
        if os.path.isfile(p) and (p.endswith('.so') or os.access(p, os.X_OK)): os.remove(p)
    rc, log, secs, feat = BD._cargo(src, f'{pdir}/build-src', td, B)
    info = dict(rustc_bootstrap=feat, build_secs=secs)
    mdir = f'{pdir}/m{mid}'; shutil.rmtree(mdir, ignore_errors=True)
    if rc != 0: return dict(info, built=False, build_log=str(log)[-1500:])
    if kind == 'exe':                            # như build.build_rust_exe: `driver` hoặc binary duy nhất
        bins = [p for p in glob.glob(f'{rel}/*') if os.path.isfile(p) and os.access(p, os.X_OK) and not p.endswith('.d')]
        got = f'{rel}/driver' if f'{rel}/driver' in bins else (bins[0] if len(bins) == 1 else None)
        dst = f'{mdir}/driver'
    else:                                        # như build.build_rust_lib: lib<library>.so, lệch tên thì lấy .so duy nhất
        want = f'{rel}/lib{library}.so'; found = glob.glob(f'{rel}/*.so')
        got = want if os.path.exists(want) else (found[0] if len(found) == 1 else None)
        dst = f'{mdir}/target/release/lib{library}.so'
        if got and got != want: info['so_alias'] = f'{os.path.basename(got)} -> lib{library}.so'
    if not got: return dict(info, built=False, build_log='không tìm thấy artefact')
    os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(got, dst)
    return dict(info, built=True, artifact=dst, mdir=mdir, sha256=BD.sha256(dst))


# ---------------- một cặp ----------------
def gen_pair(ctx, p):
    """ctx: name, kind, seed, n, keys (vị trí bỏ), B, Bm, T, H, dry_run, no_coverage."""
    kind, system, bundle, case, hcase = ctx['kind'], p['system'], p['bundle'], p['case'], p['hcase']
    rec = dict(key=pair_key(ctx['name'], kind, p), set=ctx['name'], kind=kind, seed=ctx['seed'], n=ctx['n'], system=system,
               bundle=bundle, case=case, hcase=hcase, mutants=[])
    B, Bm = ctx['B'], ctx['Bm']
    troot = f"{ctx['T']}/{bundle}/{case}"
    src = BD.rust_src(system, bundle, hcase)
    rec['source_dir'] = os.path.basename(src)
    if not os.path.isfile(f'{src}/Cargo.toml'):
        rec['error'] = f'không có Cargo.toml ở {src}'; return rec
    pdir = f"{Bm}/{ctx['name']}/{kind}/{system}/{bundle}/{case}"; wd = f'{pdir}/src'
    shutil.rmtree(wd, ignore_errors=True); os.makedirs(pdir, exist_ok=True); shutil.copytree(src, wd, ignore=IGNORE)
    info = None
    if not ctx['dry_run']:
        # bản gốc và vector gốc (quy tắc audit 14/10: cặp mà bản gốc không pass hết vector gốc bị loại, ghi lý do)
        if kind == 'exe':
            ob = BD.build_rust_exe(B, system, bundle, case, hcase)
            if not ob.get('ok'): rec['error'] = 'bản gốc không build: ' + str(ob.get('log'))[-300:]; return rec
            base = MV.vec_fails(ob['bin'], troot, f'{pdir}/base.vec.json')
        else:
            info = BD.build_lib_case(B, bundle, case)
            if not info.get('runner_ok') or not info.get('c_ok'): rec['error'] = 'runner hoặc C không build'; return rec
            ob = BD.build_rust_lib(B, system, bundle, case, hcase, info['library'])
            if not ob.get('ok'): rec['error'] = 'bản gốc không build: ' + str(ob.get('log'))[-300:]; return rec
            oroot = BD.lib_root(B, info, 'c', ob['dir'], tag=f'mut-orig-{system}')
            base = ML.vec_fails(info['runner_bin'], oroot, f'{pdir}/base.vec.json')
        rec.update(orig_sha256=ob.get('sha256'), base_vector_fails=base)
        if base:
            rec['excluded'] = 'bản gốc không pass hết vector gốc (quy tắc audit 14/10)'; return rec
    # coverage của vector gốc trên bản dịch gốc
    if ctx['no_coverage']:
        covered, err = all_lines(wd, kind), ''; rec['coverage'] = 'none'
    elif kind == 'exe':
        AE.B, AE.H, AE.HCASE = Bm, ctx['H'], {case: f'{bundle}/{hcase}'}
        covered, err = AE.covered_lines(system, case, load_vectors(troot)); rec['coverage'] = 'lcov'
    else:
        info = info or BD.build_lib_case(B, bundle, case)
        ML.B = Bm; ML._INFO[f'{bundle}/{case}'] = info
        covered, err = ML.coverage(system, case, f'{bundle}/{case}', src, info, dict(os.environ, RUSTC_BOOTSTRAP='1'))
        rec['coverage'] = 'lcov'
    if covered is None:
        rec['error'] = err; return rec
    rec['n_covered_lines'] = len(covered)
    sites = ordered_sites(kind, wd, covered, ctx['seed'])
    cache = {}
    # lib lọc rồi xáo: hạng trong nguồn (trước khi xáo) của vị trí thứ j là perm[j]; ghi lại để kiểm offline (check_sites)
    perm = _lib_perm(len(sites), ctx['seed']) if kind == 'lib' else None
    rows = [dict(site_row(wd, s, cache), _site=s, **({'src_idx': perm[j]} if perm else {})) for j, s in enumerate(sites)]
    rows, n_drop = drop_prior(system, case, rows, ctx['keys'])
    rec.update(n_sites=len(sites), n_sites_excluded_prior=n_drop)
    if ctx['dry_run']:
        rec['sites'] = [{k: v for k, v in r.items() if k != '_site'} for r in rows]
        return rec
    for r in rows:
        if sum(m['built'] for m in rec['mutants']) >= ctx['n']: break
        mid = len(rec['mutants'])
        path, text = apply_site(wd, r['_site'])
        try:
            b = build_mutant(kind, B, wd, pdir, mid, info and info['library'])
        finally:
            open(path, 'w').write(text)          # khôi phục file trước mutant tiếp theo
        m = dict({k: v for k, v in r.items() if k != '_site'}, id=mid, **{k: v for k, v in b.items() if k != 'mdir'})
        if b['built']:
            out = f"{b['mdir']}/vec.json"
            if kind == 'exe':
                vf = MV.vec_fails(b['artifact'], troot, out)
            else:
                m['root'] = BD.lib_root(B, info, 'c', b['mdir'], tag=f"mut-{ctx['name']}-{system}-m{mid}")
                vf = ML.vec_fails(info['runner_bin'], m['root'], out)
            m['new_vector_fails'] = sorted(set(vf or []) - set(base or [])) if vf is not None else None
            m['killed_by_vectors'] = bool(m['new_vector_fails'])
        rec['mutants'].append(m)
        print(rec['key'], {k: m.get(k) for k in ('id', 'line', 'op', 'built', 'killed_by_vectors')}, flush=True)
    shutil.rmtree(f'{pdir}/target', ignore_errors=True)
    return rec


IDENTITY_FIELDS = ('set', 'kind', 'system', 'bundle', 'case', 'id', 'file', 'line', 'col', 'op', 'before', 'after', 'built', 'sha256')


def identity_rows(pair_recs):
    """Một dòng danh tính mỗi mutant đã thử (gồm mutant không build được, vì id đánh theo thứ tự thử như exp 08)."""
    out = []
    for p in pair_recs:
        for m in p.get('mutants', []):
            row = {k: p[k] for k in ('set', 'kind', 'system', 'bundle', 'case')}
            row.update({k: m.get(k) for k in IDENTITY_FIELDS if k not in row})
            row['key'] = f"{p['key']}/m{m['id']}"
            out.append(row)
    return out


# ---------------- kiểm danh tính với exp 08 ----------------
ID5 = ('file', 'line', 'op', 'before', 'after')


def _t(r, f=ID5): return tuple(r[k] for k in f)


def check_identity(kind, pair_recs):
    """So bản ghi `gen` (đã build) với exp 08 theo cặp: danh sách (file, line, op, before, after, built) theo thứ tự id, và cặp bị loại."""
    got = {(r['system'], r['case']): r for r in pair_recs}
    res = []
    for p in json.load(open(EXP08[kind]))['pairs']:
        r = got.get((p['system'], p['case']))
        if r is None: res.append(dict(system=p['system'], case=p['case'], status='missing')); continue
        want = [_t(m, ID5 + ('built',)) for m in p['mutants']]; have = [_t(m, ID5 + ('built',)) for m in r.get('mutants', [])]
        ok = want == have and bool(p.get('excluded')) == bool(r.get('excluded'))
        res.append(dict(system=p['system'], case=p['case'], status='identical' if ok else 'mismatch', n_exp08=len(want), n_gen=len(have),
                        first_diff=next((i for i, (a, b) in enumerate(zip(want, have)) if a != b), None if ok else min(len(want), len(have)))))
    return res


def _lib_perm(n, seed):
    """random.shuffle chỉ phụ thuộc độ dài: vị trí j sau khi xáo là phần tử thứ perm[j] của danh sách đã lọc."""
    perm = list(range(n)); random.Random(seed).shuffle(perm); return perm


def check_sites(kind, site_recs, seed=1):
    """So danh sách vị trí của `gen --dry-run` với exp 08 (chưa build nên không kiểm được `built`).
    coverage 'lcov': danh sách exp 08 phải bằng đầu danh sách vị trí (identical).
    coverage 'none' (không có llvm-tools): kiểm điều kiện cần, kết quả 'consistent' hoặc 'inconsistent':
      exe (xáo rồi lọc): danh sách exp 08 là dãy con theo thứ tự của danh sách xáo; vị trí bị bỏ qua ở giữa không chung dòng với vị trí
          được chọn (coverage theo dòng); n_sites của exp 08 nằm trong cận suy từ dòng được chọn và dòng bị bỏ.
      lib (lọc rồi xáo): với n = n_sites của exp 08, mutant thứ j phải có hạng perm[j] trong danh sách đã lọc; kiểm thứ tự hạng trùng thứ
          tự trong nguồn, khoảng cách hạng không vượt khoảng cách trong nguồn, và hai cận đầu, cuối."""
    got = {(r['system'], r['case']): r for r in site_recs}
    res = []
    for p in json.load(open(EXP08[kind]))['pairs']:
        r = got.get((p['system'], p['case'])); want = [_t(m) for m in p['mutants']]
        base = dict(system=p['system'], case=p['case'], n_exp08=len(want), exp08_excluded=bool(p.get('excluded')))
        if r is None or r.get('error'):
            res.append(dict(base, status='missing' if r is None else 'error', error=r and r.get('error'))); continue
        sites = r['sites']; allt = [_t(s) for s in sites]
        if r.get('coverage') == 'lcov':
            ok = allt[:len(want)] == want
            res.append(dict(base, status='identical' if ok else 'mismatch', n_sites_gen=len(sites), n_sites_exp08=p.get('n_sites')))
            continue
        if not want:
            res.append(dict(base, status='consistent', note='exp 08 không có mutant')); continue
        if p.get('n_sites') == len(sites):     # exp 08 thấy mọi dòng có vị trí đều được chạy: thứ tự xác định đủ, so bằng nhau
            ok = allt[:len(want)] == want
            res.append(dict(base, status='identical' if ok else 'mismatch', note='coverage của exp 08 phủ mọi vị trí',
                            n_sites_exp08=p.get('n_sites'), n_sites_all=len(sites)))
            continue
        if kind == 'exe':
            j, skipped = 0, set()
            for s, t in zip(sites, allt):
                if j == len(want): break
                if t == want[j]: j += 1
                else: skipped.add((s['file'], s['line']))
            chosen = {(m['file'], m['line']) for m in p['mutants']}
            lo = sum(1 for s in sites if (s['file'], s['line']) in chosen); hi = sum(1 for s in sites if (s['file'], s['line']) not in skipped)
            n = p.get('n_sites')
            ok = j == len(want) and not (skipped & chosen) and (n is None or lo <= n <= hi)
            res.append(dict(base, status='consistent' if ok else 'inconsistent', matched=j, line_conflicts=sorted(skipped & chosen),
                            n_sites_bounds=[lo, hi], n_sites_exp08=n))
        else:
            src_order = sorted(sites, key=lambda s: s['src_idx'])      # thứ tự duyệt của sites_of trước khi xáo
            idx = {_t(s): s['src_idx'] for s in sites}
            n = p['n_sites']; perm = _lib_perm(n, seed)
            a = [idx.get(t) for t in want]
            if None in a or len(want) > n:
                res.append(dict(base, status='inconsistent', missing=[k for k, x in enumerate(a) if x is None])); continue
            pr = [perm[j] for j in range(len(want))]
            order_ok = sorted(range(len(a)), key=lambda k: a[k]) == sorted(range(len(pr)), key=lambda k: pr[k])
            prs = sorted(zip(pr, a))
            gaps_ok = all(p2 - p1 <= a2 - a1 for (p1, a1), (p2, a2) in zip(prs, prs[1:]))
            ends_ok = all(x <= y and n - x <= len(src_order) - y for x, y in prs)
            ok = order_ok and gaps_ok and ends_ok
            res.append(dict(base, status='consistent' if ok else 'inconsistent', order_ok=order_ok, gaps_ok=gaps_ok, ends_ok=ends_ok,
                            n_sites_exp08=n, n_sites_all=len(src_order)))
    return res


# ---------------- CLI ----------------
def _load(path): return [json.loads(l) for l in open(path) if l.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness.mutants')
    ap.add_argument('cmd', choices=['gen', 'pairs', 'check'])
    ap.add_argument('--set', required=True, choices=sorted(SETS)); ap.add_argument('--kind', required=True, choices=['exe', 'lib'])
    ap.add_argument('--out'); ap.add_argument('--systems', help='giới hạn hệ, phân cách bằng dấu phẩy')
    ap.add_argument('--cases', help='bundle/case, phân cách bằng dấu phẩy (chạy thử)')
    ap.add_argument('--dry-run', action='store_true', help='không build mutant, không chạy vector; ghi sites-<kind>.jsonl')
    ap.add_argument('--no-coverage', action='store_true', help='chỉ với --dry-run: coi mọi dòng là được chạy (kiểm offline)')
    ap.add_argument('--identity'); ap.add_argument('--sites')
    a = ap.parse_args(argv)
    spec = SETS[a.set]
    systems = a.systems.split(',') if a.systems else None
    ps = set_pairs(a.set, a.kind, systems)
    if a.cases:
        want = {tuple(x.split('/')) for x in a.cases.split(',')}
        ps = [p for p in ps if (p['bundle'], p['case']) in want]
    if a.cmd == 'pairs':
        print(json.dumps(dict(set=a.set, kind=a.kind, seed=spec['seed'], n=spec['n'], exclude=list(spec['exclude']), n_pairs=len(ps),
                              systems=dict(collections.Counter(p['system'] for p in ps)),
                              pairs=[f"{p['bundle']}/{p['case']}/{p['system']}" for p in ps]), ensure_ascii=False))
        return
    if a.cmd == 'check':
        if a.set != 'a7-seed1': raise SystemExit('check chỉ cho a7-seed1 (so với exp 08)')
        if a.identity:
            src = a.identity
            recs = collections.OrderedDict()
            for r in _load(src):          # identity-<kind>.jsonl: gom theo cặp
                recs.setdefault((r['system'], r['case']), dict(system=r['system'], case=r['case'], mutants=[]))['mutants'].append(r)
            pf = os.path.join(os.path.dirname(src), f'mutants-{a.kind}.jsonl')
            if os.path.exists(pf):        # cặp bị loại không có dòng danh tính: lấy từ bản ghi cặp
                for r in _load(pf):
                    recs.setdefault((r['system'], r['case']), dict(system=r['system'], case=r['case'], mutants=[]))['excluded'] = r.get('excluded')
            res = check_identity(a.kind, list(recs.values()))
        elif a.sites:
            res = check_sites(a.kind, _load(a.sites), spec['seed'])
        else:
            raise SystemExit('cần --identity hoặc --sites')
        for r in res: print(json.dumps(r, ensure_ascii=False))
        bad = [r for r in res if r['status'] not in ('identical', 'consistent')]
        print(json.dumps(dict(kind=a.kind, n_pairs=len(res), status=collections.Counter(r['status'] for r in res))))
        raise SystemExit(1 if bad else 0)
    if not a.out: raise SystemExit('gen cần --out')
    if a.no_coverage and not a.dry_run: raise SystemExit('--no-coverage chỉ dùng với --dry-run')
    from .config import H, T
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness'))
    # kiểm công cụ trước khi chạy, để không ghi bản ghi lỗi cho mọi cặp (coverage cần llvm-tools khớp rustc; exe cần cando_binrunner)
    if not a.no_coverage and not os.path.exists(f'{ML.TOOLS}/llvm-profdata'):
        raise SystemExit(f'thiếu llvm-profdata ở {ML.TOOLS!r}: rustup component add llvm-tools')
    if not a.dry_run and a.kind == 'exe' and not os.access(MV.RUNNER, os.X_OK):
        raise SystemExit(f'thiếu runner TRACTOR {MV.RUNNER}')
    ctx = dict(name=a.set, kind=a.kind, seed=spec['seed'], n=spec['n'], keys=prior_keys(a.kind, spec['exclude']), B=B,
               Bm=f'{B}/mutants', T=T, H=H, dry_run=a.dry_run, no_coverage=a.no_coverage)
    manifest(a.out, dict(cmd='mutants-gen', set=a.set, kind=a.kind, seed=spec['seed'], n=spec['n'], exclude=list(spec['exclude']),
                         n_prior_keys=len(ctx['keys']), pairs=[pair_key(a.set, a.kind, p) for p in ps], dry_run=a.dry_run,
                         no_coverage=a.no_coverage, build_dir=B, runner_exe=MV.RUNNER))
    fn = f'{a.out}/sites-{a.kind}.jsonl' if a.dry_run else f'{a.out}/mutants-{a.kind}.jsonl'
    if a.dry_run and os.path.exists(fn): os.remove(fn)          # dry-run không resume
    store = Store(fn)
    if a.kind == 'lib' and not a.dry_run: BD.setup_cando2(B)
    n_err = 0
    for p in ps:
        if store.has(pair_key(a.set, a.kind, p)): continue
        try:
            store.put(gen_pair(ctx, p))
        except Exception:                 # lỗi harness: khoá '#error' để lần chạy sau làm lại cặp này (như rq1)
            n_err += 1
            store.put(dict(key=pair_key(a.set, a.kind, p) + '#error', set=a.set, kind=a.kind, **p, status='harness_error',
                           error=traceback.format_exc()[-3000:]))
    recs = [r for r in _load(fn) if r.get('status') != 'harness_error']
    if not a.dry_run:
        with open(f'{a.out}/identity-{a.kind}.jsonl', 'w') as f:     # sinh lại từ bản ghi cặp, nên resume không nhân đôi dòng
            for r in identity_rows(recs): f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
    done = {r['key'] for r in recs}
    missing = [pair_key(a.set, a.kind, p) for p in ps if pair_key(a.set, a.kind, p) not in done]
    print(json.dumps(dict(set=a.set, kind=a.kind, n_pairs=len(ps), harness_errors_this_run=n_err, pairs_not_done=missing,
                          pair_errors=sum(1 for r in recs if r.get('error')), excluded=sum(1 for r in recs if r.get('excluded')),
                          mutants=sum(len(r.get('mutants', [])) for r in recs),
                          built=sum(m.get('built', False) for r in recs for m in r.get('mutants', []))), ensure_ascii=False))
    if missing: raise SystemExit(1)


if __name__ == '__main__':
    main()
