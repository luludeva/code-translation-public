#!/usr/bin/env python3
"""exp 40: danh sách bản dịch P_test của S₀ theo case, làm mẫu số cho AX-2a (docs/amendment-2026-11-05-supplementary-analyses.md mục 3; post hoc,
sơ bộ, chưa kiểm tay). Bản ghi case chọn theo L5 như harness.main_merge_v2; trạng thái bản dịch tính bằng harness.metrics.rq1_translations
trên bản ghi case với divs rỗng (chỉ khác kết quả khi có seed 'san_infra', S₀ không có: leave.san_infra = 0 ở metrics.json). Kiểm: |P_test|
bằng P_test của metrics.json; mọi bản dịch trong D-<kind>.jsonl thuộc P_test; |R_test| (outcome A hoặc F của rq2-main) bằng
metrics. Không đạt thì dừng.
  python3 experiments/40-review-counts/scripts/ptest_cases.py > experiments/40-review-counts/results/ptest-cases.json"""
import collections, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, ROOT); sys.path.insert(0, f'{ROOT}/experiments/39-prereg-backfill/scripts')
import v3c as V  # noqa: E402
from harness import metrics as HM  # noqa: E402

MET = f'{ROOT}/experiments/30-main-s0/results/metrics.json'
DFILE = f'{ROOT}/experiments/32-robustness-s0/results/D-{{}}.jsonl'
RQ2 = ('rq2-main', 'b757f4d')


def main():
    met = json.load(open(MET)); out = {}
    for kind in ('exe', 'lib'):
        chosen = {}
        for job, cm in V.SHARDS[kind]:
            fc = V.full(cm)
            for l in V.run('git', 'show', f'{fc}:ci-out/{job}/rq1-{kind}.jsonl').decode().splitlines():
                if not l.strip(): continue
                r = json.loads(l)
                if r.get('status') == 'harness_error': continue
                chosen.setdefault((r['bundle'], r['case'], r['seed']), r)
        T = HM.rq1_translations(list(chosen.values()), {}, {}, [0, 1, 2])
        pt = sorted(k for k, t in T.items() if t['status'] == 'P_test')
        want = met[f'rq1_{kind}']['by_group']['all']['P_test']
        if met[f'rq1_{kind}']['by_group']['all']['leave'].get('san_infra'): raise SystemExit('S₀ có san_infra: divs rỗng không đủ')
        if len(pt) != want: raise SystemExit(f'{kind}: |P_test| {len(pt)} khác metrics {want}')
        D = {tuple(json.loads(l)) for l in open(DFILE.format(kind)) if l.strip()}
        if not D <= set(pt): raise SystemExit(f'{kind}: D có bản dịch ngoài P_test: {sorted(D - set(pt))[:5]}')
        by = collections.defaultdict(list)
        for b, c, s in pt: by[f'{b}/{c}'].append(s)
        # R_test (outcome A hoặc F) và F theo case, cho dòng F của AX-2b; kiểm |R_test| bằng mẫu số r_FF của metrics
        rt, ff = collections.defaultdict(list), collections.defaultdict(list)
        for l in V.run('git', 'show', f'{V.full(RQ2[1])}:ci-out/rq2-main/{kind}/rq2-{kind}.jsonl').decode().splitlines():
            if not l.strip(): continue
            r = json.loads(l)
            if r.get('outcome') in ('behavioral_disagreement', 'behavioral_agreement'): rt[f"{r['bundle']}/{r['case']}"].append(r['system'])
            if r.get('outcome') == 'behavioral_agreement': ff[f"{r['bundle']}/{r['case']}"].append(r['system'])
        n_rt = sum(len(v) for v in rt.values())
        want_rt = met[f'rq2_{kind}']['R_test']
        if n_rt != want_rt: raise SystemExit(f'{kind}: |R_test| {n_rt} khác metrics {want_rt}')
        out[kind] = dict(P_test=len(pt), cases=len(by), by_case={k: sorted(v) for k, v in sorted(by.items())},
                         R_test=n_rt, R_test_cases=len(rt), F=sum(len(v) for v in ff.values()), F_cases=len(ff),
                         R_test_by_case={k: sorted(v) for k, v in sorted(rt.items())}, F_by_case={k: sorted(v) for k, v in sorted(ff.items())})
    print(json.dumps(dict(rule='exp 40, P_test theo case (S₀, L5); post hoc, sơ bộ, chưa kiểm tay', **out), indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
