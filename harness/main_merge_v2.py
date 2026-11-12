"""Gộp shard RQ1 lượt chính theo amendment 2026-11-01 (docs/amendment-2026-11-01-budget-cutoff.md, L2, L5, L6; Le duyệt 1/11).
File mới theo luật kế thừa tag (không sửa merge_shards.py, main_merge.py).

Khác harness.main_merge ở ba điểm, mọi kiểm khác giữ nguyên (gọi lại main_merge.check_shards và merge_shards.merge):
  1. Đồng nhất mã đo: thay so `repo_commit` (khác nhau giữa shard vì mỗi lần chạy tiếp ghi lại manifest) bằng hai điều kiện:
     (a) mỗi shard thoả luật kế thừa tag ở commit của nó: git diff <tag> <repo_commit> -- harness/ chỉ có trạng thái A;
     (b) mọi file harness/ có mặt ở hơn một shard có cùng blob ở mọi shard đó (file chỉ có ở một số shard là file thêm sau, ví dụ file này).
  2. Chọn bản ghi khi trùng (L5): thứ tự shard trên dòng lệnh là thứ tự ưu tiên; mỗi (case, seed) lấy bản ghi khác harness_error đầu
     tiên; file div/ và inputs/ của (case, seed) đi theo shard được chọn. Bản ghi harness_error không vào bản gộp; (case, seed) có
     harness_error mà không shard nào có bản ghi khác được ghi vào harness_error_unresolved và tính là thiếu (L2).
  3. Thiếu (case, seed) so với --expect không làm dừng: ghi danh sách `missing` vào báo cáo; harness.metrics gán missing_seed hoặc
     missing_record theo luật P_test qua seed đã đăng ký (L2).
Bản xem từng shard dựng ở OUT/_view/<i>/ bằng symlink; manifest của bản xem ghi repo_commit = 'harness-blobs:<sha256 tập blob>' và giữ
commit gốc ở repo_commit_original, chỉ để merge_shards so khớp; bản gốc không bị sửa.
Cách dùng: python3 -m harness.main_merge_v2 --kind exe|lib --out DIR --freeze-tag T [--expect cases.txt] [--seeds 0,1,2] SHARD_DIR...
           (SHARD_DIR theo thứ tự ưu tiên)"""
import argparse, hashlib, json, os, subprocess, sys

from . import merge_shards as MS
from .main_merge import check_shards
from .main_run import freeze_check
from .config import REPO


def _git(*a):
    return subprocess.run(['git', '-C', REPO, *a], capture_output=True, text=True)


def harness_blobs(commit):
    p = _git('ls-tree', '-r', commit, '--', 'harness/')
    if p.returncode != 0: return None
    out = {}
    for line in p.stdout.splitlines():
        meta, path = line.split('\t', 1)
        if path.endswith('.pyc') or '/__pycache__/' in path: continue
        out[path] = meta.split()[2]
    return out


def code_identity(shards, tag_commit):
    """Kiểm 1(a), 1(b). Trả về (problems, info)."""
    problems, blobs, info = [], {}, {}
    for d in shards:
        c = json.load(open(f'{d}/manifest.json')).get('repo_commit')
        b = harness_blobs(c) if c else None
        if b is None: problems.append(f'không đọc được cây harness/ ở commit {c} ({d}); máy gộp phải có commit đó'); continue
        diff = _git('diff', '--no-renames', '--name-status', tag_commit, c, '--', 'harness/')
        bad = [l for l in diff.stdout.splitlines() if l.strip() and not l.startswith('A\t')]
        if diff.returncode != 0 or bad: problems.append(f'shard {d} ở {c}: harness/ khác tag ngoài thêm file: {bad[:5] or diff.stderr[:200]}')
        blobs[d] = b; info[d] = dict(repo_commit=c, n_files=len(b))
    paths = set().union(*[set(b) for b in blobs.values()]) if blobs else set()
    for p in sorted(paths):
        have = {b[p] for b in blobs.values() if p in b}
        if len(have) > 1: problems.append(f'file {p} khác nhau giữa các shard: {sorted(have)}')
    common = sorted(p for p in paths if all(p in b for b in blobs.values()))
    ident = hashlib.sha256(''.join(f'{p} {next(iter(blobs.values()))[p]}\n' for p in common).encode()).hexdigest() if blobs else None
    return problems, dict(shards=info, common_files=len(common), identity=ident)


def _cs(r): return MS._case_seed(r)


def _files_of(d, sub, cs):
    b, c, s = cs.split('/')
    pre = f'{b}__{c}__{s}.'
    return [f for f in (os.listdir(f'{d}/{sub}') if os.path.isdir(f'{d}/{sub}') else []) if f.startswith(pre)]


def build_views(kind, shards, out, identity):
    chosen, ok_any, err_cs, sel = {}, set(), set(), []
    for d in shards:
        for l in open(f'{d}/rq1-{kind}.jsonl'):
            if not l.strip(): continue
            r = json.loads(l)
            if r.get('status') == 'harness_error': err_cs.add(_cs(r)); continue
            ok_any.add(_cs(r)); chosen.setdefault(_cs(r), (d, r))
    views = []
    for i, d in enumerate(shards):
        v = f'{out}/_view/{i}'; os.makedirs(f'{v}/div', exist_ok=True); os.makedirs(f'{v}/inputs', exist_ok=True)
        m = json.load(open(f'{d}/manifest.json'))
        json.dump(dict(m, repo_commit=f'harness-blobs:{identity}', repo_commit_original=m.get('repo_commit'), view_of=os.path.abspath(d)),
                  open(f'{v}/manifest.json', 'w'), indent=1, ensure_ascii=False)
        mine = sorted(cs for cs, (dd, _) in chosen.items() if dd == d)
        with open(f'{v}/rq1-{kind}.jsonl', 'w') as f:
            for cs in mine: f.write(json.dumps(chosen[cs][1], ensure_ascii=False) + '\n')
        for cs in mine:
            for sub in ('div', 'inputs'):
                for fn in _files_of(d, sub, cs): os.symlink(os.path.abspath(f'{d}/{sub}/{fn}'), f'{v}/{sub}/{fn}')
        n_rec = sum(1 for l in open(f'{d}/rq1-{kind}.jsonl') if l.strip())
        sel.append(dict(shard=d, records=n_rec, chosen=len(mine)))
        views.append(v)
    return views, sel, sorted(err_cs - ok_any), set(chosen)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness.main_merge_v2')
    ap.add_argument('--kind', choices=['exe', 'lib'], required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--freeze-tag', required=True); ap.add_argument('--expect'); ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('shards', nargs='+')
    a = ap.parse_args(argv)
    if 'dryrun' in os.path.abspath(a.out): raise SystemExit('main_merge_v2 chỉ cho lượt chính')
    freeze = freeze_check(a.freeze_tag)
    if not freeze['ok']: raise SystemExit(f'Từ chối gộp lượt chính: {freeze["reason"]}')
    seeds = [int(x) for x in a.seeds.split(',')]
    problems = check_shards('main', a.shards, freeze)
    idp, ident = code_identity(a.shards, freeze['tag_commit'])
    problems += idp
    os.makedirs(a.out, exist_ok=True)
    rep = dict(mode='main', kind=a.kind, rule='amendment 2026-11-01 L2, L5, L6', priority=list(a.shards), freeze=freeze,
               mode_problems=problems, code_identity=ident)
    if not problems:
        views, sel, unresolved, got = build_views(a.kind, a.shards, a.out, ident['identity'])
        rep['merge'] = MS.merge(a.kind, views, a.out, None, seeds)
        rep.update(selection=sel, harness_error_unresolved=unresolved, n_harness_error_unresolved=len(unresolved))
        if a.expect:
            want = {f'{c.strip()}/s{s}' for c in open(a.expect) if c.strip() for s in seeds}
            rep['missing'] = sorted(want - got); rep['n_missing'] = len(rep['missing'])
            rep['extra'] = sorted(got - want)
            if rep['extra']: problems.append(f'thừa {len(rep["extra"])} (case, seed) ngoài danh sách, ví dụ {rep["extra"][:3]}')
    rep['ok'] = not problems and rep.get('merge', {}).get('ok', False)
    json.dump(rep, open(f'{a.out}/main-merge-report.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in rep.items() if k not in ('missing', 'freeze')}, indent=1, ensure_ascii=False)[:4000])
    sys.exit(0 if rep['ok'] else 1)


if __name__ == '__main__':
    main()
