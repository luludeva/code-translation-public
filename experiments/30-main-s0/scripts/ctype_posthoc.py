#!/usr/bin/env python3
"""RQ1 post-hoc có và không có toàn bộ bản dịch của case 027_ctype_ascii (decision-log 2026-10-29; nhãn post-hoc, không thay số chính).

Cách tính: bản dịch độc lập theo case, nên D, P_test, NB_L, NB_U khi bỏ case = số của S₀ (metrics.json) trừ phần của case. Phần của case
tính lại bằng chính harness.metrics.rq1_translations trên bản ghi của case, chọn theo luật L5 (shard ưu tiên trước, bản ghi khác
harness_error đầu tiên cho mỗi (case, seed)), từ các nhánh results ở hash S₀ (decision-log 2026-11-02, 2026-11-03). Chỉ tải bản ghi case
và file div/ của case, không cần máy đo.
Kiểm: n_div_all từng bản dịch của case khớp ub_R22_by_pair trong metrics.json; mọi seed của case có bản ghi (main-merge-report).
Chạy từ gốc repo: python3 experiments/30-main-s0/scripts/ctype_posthoc.py WORKDIR > experiments/30-main-s0/results/ctype-posthoc.json"""
import collections, json, os, subprocess, sys

sys.path.insert(0, os.getcwd())
from harness import metrics as HM  # noqa: E402

S0 = dict(exe=[('rq1-main-exe-1of2', '1fa636f'), ('rq1-main-exe-2of2', 'c867337'), ('rq1-main-exe-light', '40fedd1')],
          lib=[('rq1-main-lib-1of2', 'a980c52'), ('rq1-main-lib-2of2', '97f80c5'), ('rq1-main-lib-shgeti', 'c8c41a3'),
               ('rq1-main-lib-2of2-light', 'e8f9704')])
CASE = dict(exe=('B01_synthetic', '027_ctype_ascii'), lib=('B01_synthetic', '027_ctype_ascii_lib'))
SEEDS = [0, 1, 2]
FIELDS = ('D_all', 'P_test', 'NB_L', 'NB_U')
RES = 'experiments/30-main-s0/results'


def git(*a, **k): return subprocess.run(['git', *a], check=True, **k)


def fetch(job, commit, kind, bundle, case, dest):
    full = subprocess.run(['git', 'rev-parse', commit], capture_output=True, text=True, check=True).stdout.strip()
    pre = f'ci-out/{job}/div/{bundle}__{case}__s'
    paths = [f'ci-out/{job}/rq1-{kind}.jsonl'] + [l.split('\t')[1] for l in subprocess.run(
        ['git', 'ls-tree', '-r', full, f'ci-out/{job}/div/'], capture_output=True, text=True, check=True).stdout.splitlines()
        if l.split('\t')[1].startswith(pre) and l.split('\t')[1].endswith('.jsonl.gz')]
    os.makedirs(dest, exist_ok=True)
    ar = subprocess.run(['git', 'archive', full, '--', *paths], capture_output=True, check=True).stdout
    subprocess.run(['tar', '-x', '-C', dest], input=ar, check=True)
    return full, f'{dest}/ci-out/{job}'


def main(work):
    m = json.load(open(f'{RES}/metrics.json'))
    out = {}
    for kind in ('exe', 'lib'):
        bundle, case = CASE[kind]
        chosen, prov = {}, []
        for job, c in S0[kind]:
            full, d = fetch(job, c, kind, bundle, case, f'{work}/{kind}/{job}')
            prov.append(f'{job}@{full}')
            for r in HM._jsonl(f'{d}/rq1-{kind}.jsonl'):
                if (r.get('bundle'), r.get('case')) != (bundle, case) or r.get('status') == 'harness_error': continue
                chosen.setdefault(r['seed'], (d, r))
        mini = f'{work}/{kind}/merged'; os.makedirs(f'{mini}/div', exist_ok=True)
        with open(f'{mini}/rq1-{kind}.jsonl', 'w') as f:
            for sd, (d, r) in sorted(chosen.items()):
                f.write(json.dumps(r) + '\n')
                for fn in os.listdir(f'{d}/div'):
                    if fn.startswith(f'{bundle}__{case}__s{sd}.'):
                        dst = f'{mini}/div/{fn}'
                        if not os.path.exists(dst): os.symlink(os.path.abspath(f'{d}/div/{fn}'), dst)
        cases, divs, caps = HM.load_rq1(mini, kind)
        T = HM.rq1_translations(cases, divs, caps, SEEDS)
        per = {k[2]: dict(status=t['status'], in_D=bool(t.get('in_S')), NB_L=bool(t.get('NB_L')), NB_U=bool(t.get('NB_U')),
                          n_div_all=t.get('n_div_all'), n_div_retained=t.get('n_div_retained')) for k, t in sorted(T.items())}
        case_part = dict(D_all=sum(p['in_D'] for p in per.values()), P_test=sum(p['status'] == 'P_test' for p in per.values()),
                         NB_L=sum(p['in_D'] and p['NB_L'] for p in per.values()), NB_U=sum(p['in_D'] and p['NB_U'] for p in per.values()))
        ref = m[f'rq1_{kind}']['by_group']['all'].get('ub_R22_by_pair', {}).get(bundle, {}).get(case, {})
        check_div = {s: (per.get(s, {}).get('n_div_all'), v.get('n_div_all')) for s, v in ref.items()}
        rep = json.load(open(f'{RES}/main-merge-report-{kind}.json'))
        missing = [x for x in rep.get('missing', []) if x.startswith(f'{bundle}/{case}/')]
        res = dict(case=f'{bundle}/{case}', seeds_with_record=sorted(chosen), seeds_missing_in_merge=missing, sources=prov,
                   translations=per, case_part=case_part,
                   check_n_div_all_vs_metrics=dict(pairs=check_div, ok=all(a == b for a, b in check_div.values())), groups={})
        g0 = bundle.split('_')[0]
        for g in ('all', g0):
            tot = {f: m[f'rq1_{kind}']['by_group'][g][f] for f in FIELDS}
            wo = {f: tot[f] - case_part[f] for f in FIELDS}
            res['groups'][g] = dict(with_case=tot, without_case=wo,
                                    pct_with=round(100 * tot['D_all'] / tot['P_test'], 1),
                                    pct_without=round(100 * wo['D_all'] / wo['P_test'], 1) if wo['P_test'] else None)
        out[kind] = res
    out['rule'] = 'decision-log 2026-10-29: bỏ toàn bộ bản dịch của case (exe và lib); nhãn post-hoc'
    print(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1])
