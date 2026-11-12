"""Gộp kết quả RQ1 của nhiều shard (nhiều máy) và kiểm đủ, không trùng (rà soát kỹ thuật 2026-10-23, C5).

Vào: các thư mục kết quả shard (mỗi thư mục có manifest.json, rq1-<kind>.jsonl, div/). Ra: một thư mục gộp cùng cấu trúc, kèm
merge-report.json. Dừng với lỗi khi:
  - manifest khác nhau ở các tham số đo (commit repo, TRACTOR, HARVEST, rustc, clang, theta, timeout, seed, stab_reps, mem_limit...);
  - một khoá (case, seed) xuất hiện ở hơn một shard, hoặc một file div trùng tên;
  - thiếu (case, seed) so với danh sách mong đợi (--expect: file mỗi dòng bundle/case), hoặc có bản ghi harness_error là bản ghi duy nhất
    của (case, seed) đó. D26 (Le quyết 25/10): harness_error của (case, seed) đã có bản ghi khác harness_error (chạy lại thành công) trong
    các shard thì không chặn; số ca và khoá ghi ở merge-report (harness_error_resolved, n_harness_error_resolved).
Cách dùng: python3 -m harness.merge_shards --kind exe --out DIR [--expect cases.txt] [--seeds 0,1,2] SHARD_DIR..."""
import argparse, json, os, shutil, sys

SAME = ('repo_commit', 'tractor_commit', 'harvest_commit', 'rustc', 'clang')
SAME_PARAMS = ('kind', 'seeds', 'theta', 'timeout', 'stab_reps', 'san_timeout_factor', 'input_domain', 'mem_limit', 'argv0',
               'compare_stderr', 'output_cap_sens', 'exe_san_env', 'lib_san_env')


def _case_seed(r):
    """(case, seed) của bản ghi: theo trường bundle, case, seed; bản ghi thiếu trường thì theo khoá bỏ hậu tố '#...'."""
    if all(x in r for x in ('bundle', 'case', 'seed')): return f"{r['bundle']}/{r['case']}/s{r['seed']}"
    return r['key'].split('#', 1)[0]


def merge(kind, shards, out, expect=None, seeds=(0, 1, 2)):
    problems, man0 = [], None
    os.makedirs(f'{out}/div', exist_ok=True)
    keys, recs, errs = {}, [], []
    for d in shards:
        m = json.load(open(f'{d}/manifest.json'))
        if man0 is None: man0 = m
        for k in SAME:
            if m.get(k) != man0.get(k): problems.append(f'manifest khác ở {k}: {d}')
        for k in SAME_PARAMS:
            if m['params'].get(k) != man0['params'].get(k): problems.append(f'tham số khác ở {k}: {d}')
        for l in open(f'{d}/rq1-{kind}.jsonl'):
            if not l.strip(): continue
            r = json.loads(l)
            if r.get('status') == 'harness_error': errs.append((r, d))
            if r['key'] in keys: problems.append(f'trùng khoá {r["key"]}: {keys[r["key"]]} và {d}')
            keys[r['key']] = d; recs.append(r)
        for sub in ('div', 'inputs'):                       # inputs/: tập input nén, gồm input tầng A (F8)
            os.makedirs(f'{out}/{sub}', exist_ok=True)
            for f in os.listdir(f'{d}/{sub}') if os.path.isdir(f'{d}/{sub}') else []:
                dst = f'{out}/{sub}/{f}'
                if os.path.exists(dst): problems.append(f'trùng file {sub} {f} ({d})')
                else: shutil.copy2(f'{d}/{sub}/{f}', dst)
    # D26: (case, seed) của bản ghi harness_error, khoá dạng bundle/case/s<seed>#error; có bản ghi khác harness_error cùng (case, seed) thì nới
    ok_cs = {_case_seed(r) for r in recs if r.get('status') != 'harness_error'}
    resolved = []
    for r, d in errs:
        if _case_seed(r) in ok_cs: resolved.append(r.get('key'))
        else: problems.append(f'harness_error {r.get("key")} ({d})')
    missing = []
    if expect:
        want = {f'{c.strip()}/s{s}' for c in open(expect) if c.strip() for s in seeds}
        missing = sorted(want - set(keys)); extra = sorted(set(k for k in keys if '#' not in k) - want)
        if missing: problems.append(f'thiếu {len(missing)} (case, seed), ví dụ {missing[:3]}')
        if extra: problems.append(f'thừa {len(extra)} (case, seed) ngoài danh sách, ví dụ {extra[:3]}')
    with open(f'{out}/rq1-{kind}.jsonl', 'w') as f:
        for r in sorted(recs, key=lambda r: r['key']): f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
    if man0: json.dump(dict(man0, merged_from=list(shards)), open(f'{out}/manifest.json', 'w'), indent=1, ensure_ascii=False)
    rep = dict(kind=kind, shards=list(shards), n_records=len(recs), problems=problems, ok=not problems,
               n_harness_error_resolved=len(resolved), harness_error_resolved=sorted(resolved))
    json.dump(rep, open(f'{out}/merge-report.json', 'w'), indent=1, ensure_ascii=False)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness.merge_shards')
    ap.add_argument('--kind', choices=['exe', 'lib'], required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--expect'); ap.add_argument('--seeds', default='0,1,2'); ap.add_argument('shards', nargs='+')
    a = ap.parse_args(argv)
    rep = merge(a.kind, a.shards, a.out, a.expect, [int(x) for x in a.seeds.split(',')])
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    sys.exit(0 if rep['ok'] else 1)


if __name__ == '__main__':
    main()
