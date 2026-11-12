#!/usr/bin/env python3
"""Số vận hành lượt chính cho Chương 4 §4.3 (việc A3, Le duyệt thứ tự 4/11). Chỉ đọc, không đổi số đo.

Nguồn: (1) các nhánh results ở hash S₀ (decision-log 2026-11-02, 2026-11-03): manifest.json, runner-env.txt, wall-*.json, rq1-*.jsonl,
kích thước div/ và inputs/ theo git ls-tree; (2) GitHub Actions API, workflow runner-jobs.yml, mọi run của nhánh jobs/rq1-main-*,
jobs/rq2-main-* (file JSON truyền vào, lấy bằng `gh api repos/<repo>/actions/runs/<id>/jobs`).
Đếm input theo tầng (exe) trên bản ghi được chọn theo luật L5 (shard ưu tiên trước, bản ghi khác harness_error đầu tiên mỗi (case, seed)),
như harness.main_merge_v2. Không có số RAM đỉnh: harness không ghi (chỉ ghi đĩa trống, heartbeat).
Chạy từ gốc repo: python3 experiments/30-main-s0/scripts/ops_summary.py JOBS_JSON > experiments/30-main-s0/results/ops-summary.json"""
import collections, datetime as dt, json, subprocess, sys

S0 = dict(exe=[('rq1-main-exe-1of2', '1fa636f'), ('rq1-main-exe-2of2', 'c867337'), ('rq1-main-exe-light', '40fedd1')],
          lib=[('rq1-main-lib-1of2', 'a980c52'), ('rq1-main-lib-2of2', '97f80c5'), ('rq1-main-lib-shgeti', 'c8c41a3'),
               ('rq1-main-lib-2of2-light', 'e8f9704')],
          rq2=[('rq2-main', 'b757f4d')])


def sh(*a): return subprocess.run(a, capture_output=True, text=True).stdout


def show(c, p):
    r = subprocess.run(['git', 'show', f'{c}:{p}'], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def P(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None


def sizes(c, job):
    out = collections.Counter()
    for l in sh('git', 'ls-tree', '-r', '-l', c, f'ci-out/{job}/').splitlines():
        meta, path = l.split('\t'); sz = meta.split()[3]
        k = 'div' if '/div/' in path else 'inputs' if '/inputs/' in path else 'other'
        out[k] += int(sz) if sz != '-' else 0
    return dict(out)


def main(jobs_json):
    tag_time = sh('git', 'log', '-1', '--format=%cI', 'protocol-freeze-r1^{commit}').strip()
    res = dict(freeze_tag_commit_time=tag_time, shards={}, merged_inputs_exe=None, actions=None,
               note='RAM đỉnh không có trong bản ghi; giờ máy dưới đây là giờ job trên runner, không phải giờ máy bật (tính tiền theo giờ bật)')
    chosen = collections.OrderedDict()
    for kind, lst in S0.items():
        for job, c in lst:
            full = sh('git', 'rev-parse', c).strip()
            m = json.loads(show(full, f'ci-out/{job}/manifest.json') or '{}')
            renv = show(full, 'ci-out/runner-env.txt')
            wall = show(full, f'ci-out/{job}/wall-{"exe" if "exe" in job else "lib"}.json')
            recs_txt = show(full, f'ci-out/{job}/rq1-{"exe" if "exe" in job else "lib"}.jsonl') if kind != 'rq2' else None
            st = collections.Counter()
            if recs_txt:
                for l in recs_txt.splitlines():
                    if not l.strip(): continue
                    r = json.loads(l); st[r.get('status')] += 1
                    if r.get('status') != 'harness_error': chosen.setdefault((kind, r['bundle'], r['case'], r['seed']), r)
            mp = m.get('params') or {}
            res['shards'][job] = dict(
                commit=full, created_utc=m.get('created_utc'), finished_utc=m.get('finished_utc'), wall_secs=m.get('wall_secs'),
                wall_file=json.loads(wall) if wall else None, instance=(m.get('machine') or {}).get('instance_id'),
                instance_type=(m.get('machine') or {}).get('instance_type'), runner_env=json.loads(renv) if renv else None,
                workers=mp.get('workers'), n_cases=mp.get('n_cases'), n_pairs=mp.get('n_pairs'), theta=mp.get('theta'),
                record_status=dict(st), bytes=sizes(full, job))
    L, gen, dup, ood, afl, n_rec = [collections.Counter() for _ in range(6)]
    for (kind, *_), r in chosen.items():
        if kind != 'exe': n_rec[kind] += 1; continue
        n_rec['exe'] += 1; g = r.get('gen') or {}
        for src, dst in (('n_by_layer', L), ('n_gen_by_layer', gen), ('n_dup_by_layer', dup), ('n_out_of_domain', ood)):
            for k, v in (g.get(src) or {}).items(): dst[k] += v
        afl[(g.get('afl') or {}).get('status')] += 1
    res['merged_inputs_exe'] = dict(records_chosen=dict(n_rec), executed_by_layer=dict(L), generated_by_layer=dict(gen),
                                    duplicates_by_layer=dict(dup), out_of_domain_by_layer=dict(ood),
                                    afl_status_by_record={str(k): v for k, v in afl.items()})
    jobs = json.load(open(jobs_json))
    rows, by_runner = [], collections.defaultdict(float)
    for j in jobs:
        if not j.get('runner') or not j.get('completed'): continue
        h = (P(j['completed']) - P(j['started'])).total_seconds() / 3600
        rows.append(dict(branch=j['branch'], run=j['run'], conclusion=j['conclusion'], runner=j['runner'], started=j['started'],
                         completed=j['completed'], hours=round(h, 2), after_freeze=bool(tag_time) and P(j['started']) >= P(tag_time)))
        by_runner[j['runner']] += h
    rows.sort(key=lambda r: r['started'])
    res['actions'] = dict(jobs=rows, hours_by_runner={k: round(v, 2) for k, v in sorted(by_runner.items())},
                          hours_total=round(sum(by_runner.values()), 2), n_runners=len(by_runner),
                          hours_after_freeze=round(sum(r['hours'] for r in rows if r['after_freeze']), 2))
    print(json.dumps(res, indent=1, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1])
