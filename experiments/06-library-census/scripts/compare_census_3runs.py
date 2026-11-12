#!/usr/bin/env python3
"""Đối chiếu ba lần census library theo cặp (kế hoạch A3-A7 mục 2.5, 3.5; Q9 (a), Le chọn 25/10):
  lần 1: census gốc (EC2 m7i-flex.large, 2 worker; results/census-lib.jsonl, recheck-loss.jsonl, census-lib-c-side.json, reports.tar.gz);
  lần 2: census c7i (tuần tự; results/census-lib-c7i.jsonl, recheck-loss-c7i.jsonl, census-lib-c-side-c7i.json, census-lib-c7i-reports.tar.gz);
  lần 3: census trên package `python3 -m harness.census` (job census-lib3), thư mục đầu ra cho bằng --run3.
Mở rộng logic của compare_census_lib_c7i.py (dùng lại `cat` và `POP` của file đó, không sửa nó). Liệt kê MỌI khác biệt, không cắt:
  1. tập cặp; 2. trường population; 3. nhóm verdict (`cat`) và số vector theo kết quả; 4. kết quả từng vector (đọc report);
  5. phía C (`c_results`); 6. kiểm lại hao hụt (tập đích, ours_passed, stable, alias .so); 7. P_rep (`harness.pairs.p_rep`, cùng luật
  cho ba lần) và cách vào (census hay kiểm lại);
  8. chốt chặn tiến trình mồ côi: `orphans_after` phải có và bằng 0 ở mọi bản ghi của lần 3 (census, kiểm lại, phía C).
Bản ghi lỗi harness (`stage: harness_error`, khoá '#error') không vào so sánh, liệt kê riêng.

Chạy (từ gốc repo):
  python3 experiments/06-library-census/scripts/compare_census_3runs.py --run3 ci-out/census-lib3 [--json FILE]
  Chạy thử trên hai lần đã có: --run3 trỏ tới thư mục chứa bản sao lần 2 đổi tên như đầu ra harness.census (lần 2 không có
  orphans_after nên chốt chặn mục 8 trượt, đúng như mong đợi).
Mã thoát: 0 khi chốt chặn mồ côi đạt, 1 khi trượt (khác biệt verdict không làm đổi mã thoát: chỉ báo, Le duyệt)."""
import argparse, collections as C, json, os, sys, tarfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
from harness.pairs import p_rep                    # noqa: E402
from compare_census_lib_c7i import POP, cat         # noqa: E402

R = os.path.join(HERE, '..', 'results')
RUNS_OLD = {
    'r1': dict(census=f'{R}/census-lib.jsonl', recheck=f'{R}/recheck-loss.jsonl', cside=f'{R}/census-lib-c-side.json',
               reports=f'{R}/reports.tar.gz'),
    'r2': dict(census=f'{R}/census-lib-c7i.jsonl', recheck=f'{R}/recheck-loss-c7i.jsonl', cside=f'{R}/census-lib-c-side-c7i.json',
               reports=f'{R}/census-lib-c7i-reports.tar.gz'),
}
NAMES = ('r1', 'r2', 'r3')


def key(r): return r['bundle'], r['tractor_case'], r['system']
def ks(k): return '/'.join(k)


def load_jsonl(p):
    with open(p) as f: return [json.loads(l) for l in f if l.strip()]


def dedup(rows):
    """Bản ghi mới nhất theo khoá (Store của harness ghi nối tiếp khi resume); tách bản ghi lỗi harness."""
    ok, err = {}, []
    for r in rows:
        if r.get('stage') == 'harness_error' or str(r.get('key', '')).endswith('#error'): err.append(r); continue
        ok[key(r)] = r
    return ok, err


def run3_files(d):
    rep = f'{d}/reports.tar.gz' if os.path.exists(f'{d}/reports.tar.gz') else f'{d}/reports'
    return dict(census=f'{d}/census-lib.jsonl', recheck=f'{d}/recheck-loss.jsonl', cside=f'{d}/census-lib-c-side.json', reports=rep)


def load_reports(src):
    """{(hệ hoặc 'C', bundle, case): {vector: result}} từ tar.gz hoặc thư mục reports/<hệ>/<bundle>/<case>.json."""
    out = {}
    def put(rel, data):
        parts = rel.split('/')
        if len(parts) < 4 or not parts[-1].endswith('.json'): return
        s, b, c = parts[-3], parts[-2], parts[-1][:-5]
        out[(s, b, c)] = {v: (e or {}).get('result') for v, e in json.loads(data).items()}
    if src.endswith('.tar.gz'):
        with tarfile.open(src) as t:
            for m in t.getmembers():
                if m.isfile(): put(m.name, t.extractfile(m).read())
    elif os.path.isdir(src):
        for dp, _, fs in os.walk(src):
            for f in fs:
                p = os.path.join(dp, f); put(os.path.relpath(p, os.path.dirname(src)), open(p, 'rb').read())
    return out


def load_run(files):
    census, cerr = dedup(load_jsonl(files['census']))
    rc = load_jsonl(files['recheck']) if os.path.exists(files['recheck']) else []
    recheck = {key(r): r for r in rc}
    cside = json.load(open(files['cside'])) if os.path.exists(files['cside']) else {}
    reports = load_reports(files['reports']) if os.path.exists(files['reports']) else {}
    return dict(census=census, census_errors=cerr, recheck=recheck, recheck_rows=rc, cside=cside, reports=reports, files=files)


def triple(runs, f):
    return {n: f(runs[n]) for n in NAMES}


def compare(runs):
    res, L = {}, []
    P = lambda *a: L.append(' '.join(str(x) for x in a))
    for n in NAMES:
        r = runs[n]
        P(f"{n}: {len(r['census'])} cặp, lỗi harness {len(r['census_errors'])}, kiểm lại {len(r['recheck'])}, phía C {len(r['cside'])} case, "
          f"report {len(r['reports'])} file; nguồn {os.path.relpath(r['files']['census'], ROOT)}")
    for n in NAMES:
        for e in runs[n]['census_errors']: P(f"  lỗi harness {n}: {e.get('key')} {str(e.get('error', ''))[-200:]!r}")
    res['census_errors'] = {n: [e.get('key') for e in runs[n]['census_errors']] for n in NAMES}

    # 1. tập cặp
    sets = {n: set(runs[n]['census']) for n in NAMES}
    allk = sorted(set.union(*sets.values()))
    common = sorted(set.intersection(*sets.values()))
    miss = {ks(k): [n for n in NAMES if k not in sets[n]] for k in allk if any(k not in sets[n] for n in NAMES)}
    P(f'\n== 1. Tập cặp: hợp {len(allk)}, chung {len(common)}, cặp thiếu ở ít nhất một lần {len(miss)}')
    for k, v in miss.items(): P(f'  thiếu {k}: ở {v}')
    res['missing_pairs'] = miss

    # 2. trường population
    pop = []
    for k in common:
        vals = {f: [runs[n]['census'][k].get(f) for n in NAMES] for f in POP}
        for f, v in vals.items():
            if len({json.dumps(x, sort_keys=True) for x in v}) > 1: pop.append(dict(pair=ks(k), field=f, values=dict(zip(NAMES, v))))
    P(f'\n== 2. Trường population lệch: {len(pop)} (theo trường: {dict(C.Counter(d["field"] for d in pop))})')
    for d in pop: P(f"  {d['pair']} {d['field']}: {d['values']}")
    res['population_diffs'] = pop

    # 3. nhóm verdict và số vector theo kết quả
    vd, cd = [], []
    for k in common:
        rr = [runs[n]['census'][k] for n in NAMES]
        cats = [cat(r) for r in rr]
        row = dict(pair=ks(k), pub_passed=rr[0].get('pub_passed'), cat=dict(zip(NAMES, cats)),
                   results=dict(zip(NAMES, [r.get('results') for r in rr])), ours_passed=dict(zip(NAMES, [r.get('ours_passed') for r in rr])))
        if len(set(cats)) > 1: vd.append(row)
        elif len({json.dumps(r.get('results'), sort_keys=True) for r in rr}) > 1: cd.append(row)
    P(f'\n== 3. Nhóm verdict khác giữa ba lần: {len(vd)}')
    for (a, b, c), n in sorted(C.Counter(tuple(d['cat'][x] for x in NAMES) for d in vd).items()): P(f'  {a} | {b} | {c}: {n}')
    for d in vd: P(f"  {d['pair']} công bố đỗ={d['pub_passed']}: {d['cat']} | {d['results']}")
    P(f'   cùng nhóm nhưng khác số vector theo kết quả: {len(cd)}')
    for d in cd: P(f"  {d['pair']}: {d['results']}")
    res['verdict_diffs'] = vd; res['count_diffs'] = cd

    # 4. kết quả từng vector (report); cặp không có report ở cả ba lần thì bỏ qua, cặp có ở lần này mà thiếu ở lần khác thì liệt kê
    vecd, repmiss = [], []
    for k in common:
        rk = (k[2], k[0], k[1])
        reps = {n: runs[n]['reports'].get(rk) for n in NAMES}
        have = [n for n in NAMES if reps[n] is not None]
        if not have: continue
        if len(have) < 3: repmiss.append(dict(pair=ks(k), have=have)); continue
        vs = sorted(set().union(*[set(reps[n]) for n in NAMES]))
        dv = {v: {n: reps[n].get(v) for n in NAMES} for v in vs if len({reps[n].get(v) for n in NAMES}) > 1}
        if dv: vecd.append(dict(pair=ks(k), vectors=dv))
    P(f'\n== 4. Kết quả từng vector khác (report): {len(vecd)} cặp; cặp có report ở một số lần, thiếu ở lần khác: {len(repmiss)}')
    for d in vecd: P(f"  {d['pair']}: " + '; '.join(f'{v} {x}' for v, x in d['vectors'].items()))
    for d in repmiss: P(f"  report chỉ có ở {d['have']}: {d['pair']}")
    res['vector_diffs'] = vecd; res['report_missing'] = repmiss

    # 5. phía C
    cks = sorted(set().union(*[set(runs[n]['cside']) for n in NAMES]))
    cdif = []
    for c in cks:
        v = {n: (runs[n]['cside'].get(c) or {}).get('c_results') for n in NAMES}
        if len({json.dumps(x, sort_keys=True) for x in v.values()}) > 1: cdif.append(dict(case=c, c_results=v))
    P(f'\n== 5. Phía C: {len(cks)} case, c_results khác: {len(cdif)}')
    for d in cdif: P(f"  {d['case']}: {d['c_results']}")
    res['c_side_diffs'] = cdif

    # 6. kiểm lại hao hụt
    rsets = {n: set(runs[n]['recheck']) for n in NAMES}
    rall = sorted(set.union(*rsets.values()))
    rdif = []
    for k in rall:
        v = {n: (lambda r: None if r is None else dict(ours_passed=r.get('ours_passed'), stable=r.get('stable'), so_alias=r.get('so_alias'),
                                                      build_ok=r.get('build_ok'), error=r.get('error')))(runs[n]['recheck'].get(k)) for n in NAMES}
        if len({json.dumps(x, sort_keys=True) for x in v.values()}) > 1: rdif.append(dict(pair=ks(k), recheck=v))
    P(f"\n== 6. Kiểm lại hao hụt: số cặp {[len(rsets[n]) for n in NAMES]}, hợp {len(rall)}, khác (gồm có ở lần này mà không có ở lần khác): {len(rdif)}")
    for d in rdif: P(f"  {d['pair']}: {d['recheck']}")
    res['recheck_diffs'] = rdif

    # 7. P_rep
    preps = {n: {key(r): r for r in p_rep(list(runs[n]['census'].values()), runs[n]['recheck_rows'])} for n in NAMES}
    for n in NAMES:
        pr = preps[n]; ni = sum(r['no_input'] for r in pr.values())
        P(f"\n== 7. P_rep {n}: {len(pr)} ({len(pr) - ni} có input, {ni} không input); qua kiểm lại {sum(r['via'] == 'recheck' for r in pr.values())}")
    pk = sorted(set().union(*[set(preps[n]) for n in NAMES]))
    pdif = []
    for k in pk:
        v = {n: (preps[n][k]['via'] if k in preps[n] else None) for n in NAMES}
        if len(set(v.values())) > 1: pdif.append(dict(pair=ks(k), via=v))
    P(f'  cặp đổi thành viên P_rep hoặc đổi cách vào giữa ba lần: {len(pdif)}')
    for d in pdif: P(f"  {d['pair']}: {d['via']}")
    res['p_rep'] = {n: len(preps[n]) for n in NAMES}; res['p_rep_diffs'] = pdif
    res['p_rep_r3_vs_r1'] = dict(only_r1=[ks(k) for k in sorted(set(preps['r1']) - set(preps['r3']))],
                                 only_r3=[ks(k) for k in sorted(set(preps['r3']) - set(preps['r1']))])
    res['p_rep_r3_vs_r2'] = dict(only_r2=[ks(k) for k in sorted(set(preps['r2']) - set(preps['r3']))],
                                 only_r3=[ks(k) for k in sorted(set(preps['r3']) - set(preps['r2']))])
    P(f"  r3 so r1: chỉ r1 {res['p_rep_r3_vs_r1']['only_r1']}, chỉ r3 {res['p_rep_r3_vs_r1']['only_r3']}")
    P(f"  r3 so r2: chỉ r2 {res['p_rep_r3_vs_r2']['only_r2']}, chỉ r3 {res['p_rep_r3_vs_r2']['only_r3']}")

    # 8. chốt chặn mồ côi (lần 3)
    r3 = runs['r3']; bad = []
    for where, rows in (('census', list(r3['census'].values()) + r3['census_errors']), ('recheck', r3['recheck_rows']),
                        ('c_side', [dict(v, _k=k) for k, v in r3['cside'].items()])):
        for r in rows:
            o = r.get('orphans_after')
            if o != 0: bad.append(dict(where=where, key=r.get('key') or r.get('_k') or ks(key(r)), orphans_after=o))
    n_rec = len(r3['census']) + len(r3['census_errors']) + len(r3['recheck_rows']) + len(r3['cside'])
    ok = not bad and n_rec > 0
    P(f"\n== 8. Chốt chặn mồ côi lần 3: {'ĐẠT' if ok else 'TRƯỢT'}; {n_rec} bản ghi, lệch (thiếu trường hoặc khác 0): {len(bad)} "
      f"(theo nơi: {dict(C.Counter(b['where'] for b in bad))}, theo giá trị: {dict(C.Counter(str(b['orphans_after']) for b in bad))})")
    for b in bad: P(f"  {b['where']} {b['key']}: orphans_after={b['orphans_after']}")
    res['orphans'] = dict(pass_=ok, n_records=n_rec, violations=bad)
    return res, L


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--run3', required=True, help='thư mục đầu ra harness.census (lần 3)')
    ap.add_argument('--json', help='ghi kết quả máy đọc được')
    a = ap.parse_args(argv)
    runs = dict(r1=load_run(RUNS_OLD['r1']), r2=load_run(RUNS_OLD['r2']), r3=load_run(run3_files(os.path.abspath(a.run3))))
    res, L = compare(runs)
    print('Đối chiếu ba lần census library (sơ bộ, chưa kiểm tay)')
    print('\n'.join(L))
    if a.json:
        with open(a.json, 'w') as f: json.dump(res, f, indent=1, ensure_ascii=False)
    sys.exit(0 if res['orphans']['pass_'] else 1)


if __name__ == '__main__':
    main()
