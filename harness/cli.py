"""CLI: python3 -m harness <lệnh> ... (dùng trong ci/jobs/*.sh).

  v6  --kind exe|lib --out DIR [--shard i/n] [--workers N] [--timeout S]
  v5  --kind exe|lib --out DIR [--shard i/n] [--workers N] [--timeout S] [--census F --recheck F]
  pairs --kind exe|lib            in số cặp P_rep và số case
Build cache ở $HARNESS_BUILD (mặc định ~/build/harness). Resume theo khoá bản ghi trong DIR/<lệnh>-<kind>.jsonl."""
import argparse, collections, json, os, sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from . import build as BD
from . import checks as CK
from . import pairs as PR
from .config import PILOT_EXE, PILOT_LIB
from .record import Store, manifest


def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness')
    ap.add_argument('cmd', choices=['v5', 'v6', 'pairs'])
    ap.add_argument('--kind', choices=['exe', 'lib'], required=True)
    ap.add_argument('--out'); ap.add_argument('--shard'); ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--timeout', type=int, default=10)
    ap.add_argument('--census'); ap.add_argument('--recheck')
    ap.add_argument('--cases', help='danh sách bundle/case, phân cách bằng dấu phẩy (chạy thử)')
    a = ap.parse_args(argv)
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness'))
    prs = PR.prep_pairs(a.kind, a.census, a.recheck)
    cases = PR.cases_of(prs)
    if a.cmd == 'v6':      # V6 chạy trên mọi case của lượt chính: case có cặp trong P_rep (pilot đã loại ở census)
        pil = PILOT_EXE if a.kind == 'exe' else PILOT_LIB
        assert not (set(cases) & pil)
    if a.cases: cases = [tuple(x.split('/')) for x in a.cases.split(',')]
    cases = PR.shard(cases, a.shard)
    if a.cmd == 'pairs':
        print(json.dumps(dict(kind=a.kind, pairs=len(prs), cases=len(PR.cases_of(prs)),
                              via=collections.Counter(r['via'] for r in prs), no_input=sum(r['no_input'] for r in prs))))
        return
    manifest(a.out, dict(cmd=a.cmd, kind=a.kind, shard=a.shard, workers=a.workers, timeout=a.timeout, n_cases=len(cases),
                         n_pairs=len(prs), build_dir=B, census=a.census, recheck=a.recheck))
    store = Store(f'{a.out}/{a.cmd}-{a.kind}.jsonl')
    if a.kind == 'lib': BD.setup_cando2(B)          # dựng một lần trước khi chạy song song
    by_case = collections.defaultdict(list)
    for r in prs: by_case[(r['bundle'], r['tractor_case'])].append(r)
    todo = []
    for bundle, case in cases:
        if a.cmd == 'v6':
            if store.has(f'{bundle}/{case}'): continue
            fn = CK.v6_exe_case if a.kind == 'exe' else CK.v6_lib_case
            todo.append((fn, B, bundle, case, a.timeout))
        else:
            ps = [p for p in by_case[(bundle, case)] if not store.has(f'{bundle}/{case}/{p["system"]}')]
            if not ps: continue
            fn = CK.v5_exe_case if a.kind == 'exe' else CK.v5_lib_case
            todo.append((fn, B, bundle, case, ps, a.timeout))
    print(f'{a.cmd} {a.kind}: {len(todo)} case cần chạy', flush=True)
    with ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(CK.safe, *t): t for t in todo}
        for fut in as_completed(futs):
            t = futs[fut]; res = fut.result()
            recs = res if isinstance(res, list) else [res]
            for r in recs:
                if r.get('status') == 'harness_error':
                    r.update(key=f'{t[2]}/{t[3]}#error', check=a.cmd.upper(), kind=a.kind, bundle=t[2], case=t[3])
                store.put(r)
                print(r.get('key'), r.get('status'), r.get('n_unstable', r.get('n_mismatch')), flush=True)


if __name__ == '__main__':
    main()
