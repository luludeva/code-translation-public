"""Gộp shard RQ1 của lượt chính hoặc dryrun (file mới, luật kế thừa tag 2026-10-26: không sửa harness/merge_shards.py).

merge_shards.merge so commit và tham số đo nhưng không so chế độ chạy, nên một shard dryrun cùng commit, cùng seed có thể lọt vào bản
gộp lượt chính. Module này kiểm trước: mọi shard có params.main_run.mode bằng --mode, cùng nhãn (params.tag), cùng commit tag freeze
(lượt chính); lượt chính còn kiểm lại luật kế thừa tag ở HEAD của máy gộp (main_run.freeze_check). Đạt thì gọi merge_shards.merge,
ghi main-merge-report.json; dryrun ghi thêm DRYRUN.txt vào thư mục gộp.
Cách dùng: python3 -m harness.main_merge --mode main|dryrun --kind exe|lib --out DIR [--freeze-tag T] [--expect cases.txt]
           [--seeds 0,1,2] SHARD_DIR..."""
import argparse, json, os, sys

from . import merge_shards as MS
from .main_run import DRYRUN_BANNER, freeze_check


def check_shards(mode, shards, freeze=None):
    problems, tags, tcs = [], set(), set()
    for d in shards:
        try: m = json.load(open(f'{d}/manifest.json'))
        except (OSError, ValueError) as e:
            problems.append(f'không đọc được manifest {d}: {type(e).__name__}'); continue
        p = m.get('params', {}); mr = p.get('main_run') or {}
        if mr.get('mode') != mode: problems.append(f'shard {d} chế độ {mr.get("mode")!r}, không phải {mode!r}')
        if (mode == 'dryrun') != (p.get('tag') == 'dryrun'): problems.append(f'shard {d} nhãn {p.get("tag")!r} không hợp chế độ {mode}')
        tags.add(p.get('tag')); tcs.add((mr.get('freeze') or {}).get('tag_commit'))
    if len(tags) > 1: problems.append(f'nhãn khác nhau giữa các shard: {sorted(map(str, tags))}')
    if mode == 'main':
        if len(tcs) > 1: problems.append(f'commit tag freeze khác nhau: {sorted(map(str, tcs))}')
        if freeze is not None and tcs and tcs != {freeze.get('tag_commit')}:
            problems.append(f'commit tag freeze của shard {sorted(map(str, tcs))} khác tag {freeze.get("tag")} ({freeze.get("tag_commit")})')
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness.main_merge')
    ap.add_argument('--mode', choices=['main', 'dryrun'], required=True)
    ap.add_argument('--kind', choices=['exe', 'lib'], required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--freeze-tag'); ap.add_argument('--expect'); ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('shards', nargs='+')
    a = ap.parse_args(argv)
    p = os.path.abspath(a.out)
    if (a.mode == 'dryrun') != ('dryrun' in p): raise SystemExit(f'--out {p}: dryrun phải chứa "dryrun", lượt chính thì không')
    freeze = None
    if a.mode == 'main':
        freeze = freeze_check(a.freeze_tag)
        if not freeze['ok']: raise SystemExit(f'Từ chối gộp lượt chính: {freeze["reason"]}')
    problems = check_shards(a.mode, a.shards, freeze)
    os.makedirs(a.out, exist_ok=True)
    rep = dict(mode=a.mode, kind=a.kind, shards=list(a.shards), freeze=freeze, mode_problems=problems)
    if a.mode == 'dryrun':
        rep['DRYRUN'] = DRYRUN_BANNER; open(f'{a.out}/DRYRUN.txt', 'w').write(DRYRUN_BANNER + '\n')
    if not problems:
        rep['merge'] = MS.merge(a.kind, a.shards, a.out, a.expect, [int(x) for x in a.seeds.split(',')])
    rep['ok'] = not problems and rep['merge']['ok']
    json.dump(rep, open(f'{a.out}/main-merge-report.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    sys.exit(0 if rep['ok'] else 1)


if __name__ == '__main__':
    main()
