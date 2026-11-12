#!/usr/bin/env python3
"""exp 38 (post hoc, sơ bộ, chưa kiểm tay): cận tất định cho các bản RQ2 executable có outcome not_re_examined vì bản C-san không
build được (reason incomplete_harness_run:san_build_failed).

Không chạy lại gì. Đọc bản ghi RQ2 lượt chính (rq2-exe.jsonl, trường `obs` của F5), tính lại kết quả bằng chính luật đã đóng băng
(harness.rq2.recompute_vector, translation_outcome), rồi thay trạng thái sanitizer phía C của các vector san_build_failed bằng từng giá
trị sanitizer có thể trả về khi build được (no_report, ub, inconclusive; thêm infra không kèm cause, tức san_infra, làm kịch bản phụ).
Bảng RQ3 cho từng k lấy đại lượng nền từ S0. k định nghĩa như amendment 2026-11-05 (docs/amendment-2026-11-05-rq2-san-supp.md §9):
k = số bản trong tập (36) không kết thúc là behavioral_disagreement, tức not_adjudicable hoặc vẫn not_re_examined. Đại lượng nền: census qua
writing/scripts/gen-rq-macros.py census_counts (cùng nguồn rq-numbers.tex), D_all, A, F theo hệ từ experiments/30-main-s0/results/
metrics-split.json; kiểm chéo với writing/generated/rq-numbers.tex.

Dùng: python3 experiments/38-rq2-san-bound/scripts/bound.py <rq2-exe.jsonl> [--repo <repo>] [--s0 <dir>] [--out <file>]"""
import argparse, collections, hashlib, importlib.util, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TARGET_REASON = 'incomplete_harness_run:san_build_failed'
SCENARIOS = ('no_report', 'ub', 'inconclusive')        # trạng thái sanitizer khi bản C-san build được và chạy xong
EXTRA = ('infra',)                                     # kịch bản phụ: build được nhưng lỗi hạ tầng (san_infra)
SYSTEM = 'codex-gpt54'
ANSI = re.compile(r'\x1b\[[0-9;]*m')
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
ORIG_DIFF_CUT = 300                                    # harness.rq2._orig cắt diff ở 300 ký tự


def sha_file(p):
    try:
        with open(p, 'rb') as f: return hashlib.sha256(f.read()).hexdigest()
    except OSError: return None


def git(repo, *args):
    try: return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True).stdout.strip() or None
    except OSError: return None


def load_rq2(repo):
    sys.path.insert(0, repo)
    from harness import rq2
    return rq2


def is_target(r):
    return r.get('outcome') == 'not_re_examined' and TARGET_REASON in (r.get('reasons') or [r.get('reason')])


def is_sbf(v):
    return v.get('outcome') == 'incomplete' and v.get('reason') == 'san_build_failed'


# ---------------------------------------------------------------- 1. kiểm tái lập
def validate(rq2, recs):
    vn, vbad, tn, tbad, tskip = 0, [], 0, [], 0
    for r in recs:
        vos = []
        for v in r.get('vectors') or []:
            got = rq2.recompute_vector(v, 'exe'); vn += 1
            if list(got) != [v['outcome'], v['reason']]: vbad.append(dict(key=r['key'], vector=v['vector'], stored=[v['outcome'], v['reason']], got=list(got)))
            vos.append(got)
        if not r.get('vectors'):
            tskip += 1; continue              # bản dừng trước khi chạy (pre-run reason): không có gì để tính lại
        o, rs = rq2.translation_outcome(vos); tn += 1
        if o != r['outcome'] or sorted(rs) != sorted(r.get('reasons') or []):
            tbad.append(dict(key=r['key'], stored=[r['outcome'], r.get('reasons')], got=[o, rs]))
    return dict(vectors_recomputed=vn, vector_mismatches=len(vbad), vector_mismatch_list=vbad[:20],
                translations_recomputed=tn, translation_mismatches=len(tbad), translation_mismatch_list=tbad[:20],
                translations_without_vectors=tskip)


# ---------------------------------------------------------------- 2. kịch bản sanitizer
def outcome_under(rq2, r, san):
    """Kết quả cấp bản dịch khi mọi vector san_build_failed của r mang trạng thái sanitizer san (cause bỏ trống); vector khác giữ bản ghi."""
    vos = []
    for v in r['vectors']:
        if is_sbf(v): vos.append(rq2.recompute_vector(dict(v, san=san, san_cause=None), 'exe'))
        else: vos.append(rq2.recompute_vector(v, 'exe'))
    o, rs = rq2.translation_outcome(vos)
    return o, rs, vos


def scenarios(rq2, recs, targets):
    out, per = {}, {}
    base = collections.Counter(r['outcome'] for r in recs)
    for san in SCENARIOS + EXTRA:
        tc, rc, vc = collections.Counter(), collections.Counter(), collections.Counter()
        for r in targets:
            o, rs, vos = outcome_under(rq2, r, san)
            tc[o] += 1; rc.update(rs); vc.update(f'{a}:{b}' for a, b in vos)
            per.setdefault(r['key'], {})[san] = o
        whole = base.copy(); whole.subtract({'not_re_examined': len(targets)}); whole.update(tc)
        out[san] = dict(extra=san in EXTRA, translation_outcomes=dict(tc), translation_reasons=dict(rc), vector_outcomes=dict(vc),
                        F_targets=tc['behavioral_agreement'], A_targets=tc['behavioral_disagreement'],
                        F_R_run=whole['behavioral_agreement'], A_R_run=whole['behavioral_disagreement'],
                        R_run_outcomes={k: v for k, v in whole.items() if v})
    pattern = collections.Counter(json.dumps(v, sort_keys=True) for v in per.values())
    return out, per, dict(base_R_run_outcomes=dict(base), per_translation_patterns={k: n for k, n in pattern.items()})


def composite(rq2, recs, targets, k, undecided='ub'):
    """k bản đầu (theo key) mang trạng thái undecided, các bản còn lại no_report; trả Counter outcome theo (system) trên toàn R_run."""
    tk = sorted(r['key'] for r in targets)
    und = set(tk[:k])
    C = collections.defaultdict(collections.Counter)
    for r in recs:
        if is_target(r): o = outcome_under(rq2, r, undecided if r['key'] in und else 'no_report')[0]
        else: o = r['outcome']
        C[r['system']][o] += 1; C['_all'][o] += 1
    return C


# ---------------------------------------------------------------- 3. bằng chứng trong bản ghi
def parse_diff(d):
    d = ANSI.sub('', d or '')
    exp, got, hunks, starts = [], [], 0, []
    in_h = False
    for ln in d.split('\n'):
        m = HUNK.match(ln)
        if m: hunks += 1; in_h = True; starts.append((int(m.group(1)), int(m.group(3)))); continue
        if not in_h: continue
        if ln.startswith('-'): exp.append(ln[1:])
        elif ln.startswith('+'): got.append(ln[1:])
        elif ln.startswith(' '): exp.append(ln[1:]); got.append(ln[1:])
    return dict(expected=exp, got=got, hunks=hunks, starts=starts, stdout_diff=d.startswith('Stdout diff:'))


def evidence(rq2, targets):
    ev = collections.Counter()
    c_distinct, r_distinct, chans, failures = collections.Counter(), collections.Counter(), collections.Counter(), []
    for r in targets:
        for v in r['vectors']:
            if not is_sbf(v): continue
            ev['vectors'] += 1
            od = (v.get('orig') or {}).get('diff', '')
            if len(od) >= ORIG_DIFF_CUT: ev['orig_diff_maybe_truncated'] += 1
            pd = parse_diff(od)
            whole = pd['hunks'] == 1 and pd['starts'] == [(1, 1)] and pd['stdout_diff']
            cs, rs, ceq, req = set(), set(), True, True
            for e in v['obs']['runs']:
                ph = e['rerun'] if e['reran'] else e['first']
                c, rr = rq2.dec_obs(ph['c'], 'exe'), rq2.dec_obs(ph['r'], 'exe')
                cs.add((c['status'], c.get('rc'), c.get('sig'), hashlib.sha256(c['out']).hexdigest(), hashlib.sha256(c['err']).hexdigest()))
                rs.add((rr['status'], rr.get('rc'), rr.get('sig'), hashlib.sha256(rr['out']).hexdigest(), hashlib.sha256(rr['err']).hexdigest()))
                ceq &= whole and c['out'].decode('utf-8', 'replace').splitlines() == pd['expected']
                req &= whole and rr['out'].decode('utf-8', 'replace').splitlines() == pd['got']
                ev['reps'] += 1; ev['reruns'] += bool(e['reran'])
            for s in v['runs']: chans['+'.join(s['channels']) or '(none)'] += 1
            ev['c_equals_expected'] += ceq; ev['rust_equals_published_got'] += req
            ev['diff_single_whole_hunk'] += whole
            c_distinct[len(cs)] += 1; r_distinct[len(rs)] += 1
            if not (ceq and req): failures.append(r['key'])
    return dict(n_vectors=ev['vectors'], n_reps=ev['reps'], n_reruns=ev['reruns'],
                orig_diff_maybe_truncated=ev['orig_diff_maybe_truncated'], diff_single_whole_hunk=ev['diff_single_whole_hunk'],
                c_stdout_equals_expected=ev['c_equals_expected'], rust_stdout_equals_published_got=ev['rust_equals_published_got'],
                distinct_c_observations_across_reps=dict(c_distinct), distinct_rust_observations_across_reps=dict(r_distinct),
                channels_per_rep=dict(chans), keys_failing_evidence=failures,
                note='quan sát = (status, rc, sig, sha256 stdout, sha256 stderr) của lần chạy dùng để quyết định ở mỗi rep')


# ---------------------------------------------------------------- 4. RQ3 theo k
def rq_macros(path):
    out = {}
    try:
        with open(path) as f: lines = f.read().splitlines()
        for ln in lines:
            m = re.match(r'\\rqSet\{([A-Za-z]+)\}\{([^}]*)\}', ln)
            if m: out[m.group(1)] = m.group(2)
    except OSError: pass
    return out


def pct(n, d): return None if not d else round(100 * n / d, 1)


def rq3(rq2, repo, s0, recs, targets):
    spec = importlib.util.spec_from_file_location('gen_rq_macros', f'{repo}/writing/scripts/gen-rq-macros.py')
    G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
    import io, contextlib
    err = io.StringIO()
    with contextlib.redirect_stderr(err): cen, cfiles = G.census_counts(repo, False)
    with open(f'{s0}/metrics-split.json') as f: split = json.load(f)
    rec_counts = collections.defaultdict(collections.Counter)
    for r in recs: rec_counts[r['system']][r['outcome']] += 1; rec_counts['_all'][r['outcome']] += 1
    M = rq_macros(f'{repo}/writing/generated/rq-numbers.tex')
    tables, checks = {}, []
    for sy, tokn in ((SYSTEM, 'Codex'), ('_all', '')):
        c = cen['exe'][('all', sy)]
        r1, r2 = split['rq1']['exe']['all'][sy], split['rq2']['exe']['all'][sy]
        base = dict(P0=c['P0'], P_acc=c['P_acc'], R0_test=c['R0_test'], R_run=c['R_run'], D_all=r1['D_all'], P_test=r1['P_test'],
                    A=r2['A'], F=r2['F'], not_re_examined=r2['not_re_examined'], not_adjudicable=r2['not_adjudicable'])
        base['L_P'] = base['P_acc'] - base['P_test']
        base['L_R'] = base['R0_test'] - base['A'] - base['F']
        base['upper_num'] = base['P_acc'] - base['D_all'] + base['F'] + base['L_R']
        base['lower_num'] = base['P_acc'] - base['D_all'] - base['L_P'] + base['F']
        # kiểm chéo: bản ghi rq2-exe.jsonl và rq-numbers.tex phải cho cùng số
        rc = rec_counts[sy]
        checks.append(dict(system=sy, what='A,F,not_re_examined từ rq2-exe.jsonl = metrics-split',
                           ok=(rc['behavioral_disagreement'], rc['behavioral_agreement'], rc['not_re_examined']) ==
                              (base['A'], base['F'], base['not_re_examined'])))
        checks.append(dict(system=sy, what='R_run census = số bản ghi RQ2', ok=base['R_run'] == sum(rc.values())))
        suf = f'ExeAll{tokn}'
        for fam, val in (('SRHi', base['upper_num']), ('SRLo', base['lower_num']), ('Lr', base['L_R']), ('SR', base['P_acc'])):
            mv = M.get(f'rq{fam}{suf}Num')
            checks.append(dict(system=sy, what=f'rq{fam}{suf}Num ở rq-numbers.tex', macro=mv, computed=val,
                               ok=mv is not None and mv == str(val)))
        n_t = sum(1 for r in targets if sy == '_all' or r['system'] == sy)
        rows = []
        for k in range(n_t + 1):
            C = composite(rq2, recs, [r for r in targets if sy == '_all' or r['system'] == sy], k)
            C2 = composite(rq2, recs, [r for r in targets if sy == '_all' or r['system'] == sy], k, undecided='inconclusive')
            # k gồm cả bản vẫn not_re_examined (amendment §9): kịch bản phụ infra phải cho cùng A, F (L_R chứa cả hai loại)
            C3 = composite(rq2, recs, [r for r in targets if sy == '_all' or r['system'] == sy], k, undecided='infra')
            A_k, F_k = C[sy]['behavioral_disagreement'], C[sy]['behavioral_agreement']
            L_R = base['R0_test'] - A_k - F_k
            up = base['P_acc'] - base['D_all'] + F_k + L_R
            lo = base['P_acc'] - base['D_all'] - base['L_P'] + F_k
            rows.append(dict(k=k, A=A_k, F=F_k, L_R=L_R, upper_num=up, lower_num=lo, den=base['P0'], upper_pct=pct(up, base['P0']),
                             lower_pct=pct(lo, base['P0']), sr_num=base['P_acc'], sr_pct=pct(base['P_acc'], base['P0']),
                             upper_below_sr=up < base['P_acc'], upper_equals_sr=up == base['P_acc'],
                             ub_vs_inconclusive_same=(C[sy] == C2[sy]),
                             ub_vs_infra_same_AF=(A_k, F_k) == (C3[sy]['behavioral_disagreement'], C3[sy]['behavioral_agreement'])))
        below = [x['k'] for x in rows if x['upper_below_sr']]
        tables[sy] = dict(base=base, n_targets=n_t, rows=rows, k_max_upper_below_sr=max(below) if below else None,
                          k_upper_equals_sr=[x['k'] for x in rows if x['upper_equals_sr']],
                          k36_reproduces_base=rows[-1]['upper_num'] == base['upper_num'] and rows[-1]['L_R'] == base['L_R'])
    exe_files = [p for p in cfiles if '02-harvest-repro' in p]
    return dict(tables=tables, checks=checks, census_files_exe={os.path.relpath(p, repo): sha_file(p) for p in exe_files},
                census_stderr=err.getvalue().strip() or None,
                s0_files={os.path.relpath(f'{s0}/{f}', repo) if f'{s0}'.startswith(repo) else f'{s0}/{f}': sha_file(f'{s0}/{f}')
                          for f in ('metrics.json', 'metrics-split.json')},
                rq_numbers_tex=dict(path='writing/generated/rq-numbers.tex', sha256=sha_file(f'{repo}/writing/generated/rq-numbers.tex')),
                note='k: số bản trong tập san_build_failed không kết thúc là behavioral_disagreement, tức not_adjudicable hoặc vẫn '
                     'not_re_examined (định nghĩa của amendment 2026-11-05 §9). Bảng dựng với k bản mang ub, 36-k bản mang no_report; '
                     'inconclusive cho cùng bảng (ub_vs_inconclusive_same), infra không cause cho cùng A, F (ub_vs_infra_same_AF). '
                     'Cận trên dùng luật §3.6: (|P_acc| - D + F + L_R)/|P_0|, L_R = |R_0^test| - A - F.')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('rq2_exe'); ap.add_argument('--repo', default=REPO_DEFAULT)
    ap.add_argument('--s0', default=None); ap.add_argument('--out', default=None)
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo); s0 = os.path.abspath(a.s0 or f'{repo}/experiments/30-main-s0/results')
    out = a.out or os.path.join(HERE, '..', 'results', 'bound-exe.json')
    rq2 = load_rq2(repo)
    with open(a.rq2_exe) as f: recs = [json.loads(l) for l in f]
    targets = [r for r in recs if is_target(r)]
    bad_targets = [r['key'] for r in targets if not all(is_sbf(v) for v in r['vectors'] if v['outcome'] == 'incomplete')]
    val = validate(rq2, recs)
    sc, per, meta = scenarios(rq2, recs, targets)
    ev = evidence(rq2, targets)
    A_vals = [sc[s]['A_R_run'] for s in SCENARIOS]; AF_vals = [sc[s]['A_R_run'] + sc[s]['F_R_run'] for s in SCENARIOS]
    doc = dict(
        label='post hoc, sơ bộ, chưa kiểm tay',
        provenance=dict(input=os.path.abspath(a.rq2_exe), input_sha256=sha_file(a.rq2_exe),
                        input_git_blob=git(repo, 'hash-object', os.path.abspath(a.rq2_exe)),
                        expected_source='origin/results/rq2-main b757f4da7c979623c2e0878c6a644f277d9a8be4:ci-out/rq2-main/exe/rq2-exe.jsonl',
                        expected_git_blob=git(repo, 'rev-parse', 'b757f4da7c979623c2e0878c6a644f277d9a8be4:ci-out/rq2-main/exe/rq2-exe.jsonl'),
                        repo_head=git(repo, 'rev-parse', 'HEAD'), harness_rq2_sha256=sha_file(f'{repo}/harness/rq2.py'),
                        harness_observe_sha256=sha_file(f'{repo}/harness/observe.py')),
        n_records=len(recs), validation=val,
        targets=dict(reason=TARGET_REASON, n=len(targets), keys=sorted(r['key'] for r in targets),
                     systems=dict(collections.Counter(r['system'] for r in targets)),
                     bundles=dict(collections.Counter(r['bundle'] for r in targets)),
                     c_san_ok=dict(collections.Counter(str(r.get('c_san_ok')) for r in targets)),
                     n_vectors=dict(collections.Counter(len(r['vectors']) for r in targets)),
                     with_other_incomplete_reason=bad_targets),
        scenarios=sc, scenario_meta=meta,
        F_per_scenario={s: sc[s]['F_R_run'] for s in SCENARIOS + EXTRA},
        A_range_R_run=dict(min=min(A_vals), max=max(A_vals), adjudicated_min=min(AF_vals), adjudicated_max=max(AF_vals),
                           R_run=len(recs), over=list(SCENARIOS)),
        any_behavioral_agreement=any(sc[s]['F_targets'] > 0 for s in SCENARIOS + EXTRA),
        evidence=ev,
        rq3=rq3(rq2, repo, s0, recs, targets))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w') as f: json.dump(doc, f, indent=1, ensure_ascii=False)
    # tóm tắt ra stdout (run-log)
    v = val
    print(f'input {doc["provenance"]["input_sha256"]} blob {doc["provenance"]["input_git_blob"]} (kỳ vọng {doc["provenance"]["expected_git_blob"]})')
    print(f'records {len(recs)}; vectors recomputed {v["vectors_recomputed"]}, mismatches {v["vector_mismatches"]}; '
          f'translations recomputed {v["translations_recomputed"]}, mismatches {v["translation_mismatches"]}')
    print(f'targets ({TARGET_REASON}): {len(targets)} {doc["targets"]["systems"]} {doc["targets"]["bundles"]}')
    for s in SCENARIOS + EXTRA:
        print(f'  san={s}{" (phụ)" if s in EXTRA else ""}: targets {sc[s]["translation_outcomes"]} reasons {sc[s]["translation_reasons"]}; '
              f'F_R_run {sc[s]["F_R_run"]}, A_R_run {sc[s]["A_R_run"]}')
    print(f'A range R_run: {doc["A_range_R_run"]}; any behavioral_agreement: {doc["any_behavioral_agreement"]}')
    print(f'evidence: C=expected {ev["c_stdout_equals_expected"]}/{ev["n_vectors"]}, Rust=got {ev["rust_stdout_equals_published_got"]}/{ev["n_vectors"]}, '
          f'distinct C {ev["distinct_c_observations_across_reps"]}, distinct Rust {ev["distinct_rust_observations_across_reps"]}, '
          f'channels {ev["channels_per_rep"]}, diff truncated {ev["orig_diff_maybe_truncated"]}')
    for c in doc['rq3']['checks']: print(f'  check {c["system"]}: {c["what"]}: {"ok" if c["ok"] else "FAIL"}' + (f' (macro {c["macro"]}, tính {c["computed"]})' if 'macro' in c else ''))
    for sy, t in doc['rq3']['tables'].items():
        b = t['base']
        print(f'RQ3 {sy}: base P0 {b["P0"]} P_acc {b["P_acc"]} R0_test {b["R0_test"]} D {b["D_all"]} L_P {b["L_P"]} A {b["A"]} F {b["F"]} '
              f'L_R {b["L_R"]} upper {b["upper_num"]}/{b["P0"]} lower {b["lower_num"]}/{b["P0"]}; k_max(upper<SR) {t["k_max_upper_below_sr"]}, '
              f'k(upper=SR) {t["k_upper_equals_sr"]}, k=n reproduces base {t["k36_reproduces_base"]}')
        for x in t['rows']:
            if sy == SYSTEM or x['k'] in (0, t['n_targets']):
                print(f'  k={x["k"]:2d} A={x["A"]} F={x["F"]} L_R={x["L_R"]} upper {x["upper_num"]}/{x["den"]} ({x["upper_pct"]}%) '
                      f'SR {x["sr_num"]}/{x["den"]} ({x["sr_pct"]}%) below={x["upper_below_sr"]} ub~inconcl={x["ub_vs_inconclusive_same"]} '
                      f'ub~infra(A,F)={x["ub_vs_infra_same_AF"]}')
    print(f'Đã ghi {os.path.abspath(out)}')
    ok = (v['vector_mismatches'] == 0 and v['translation_mismatches'] == 0 and all(c['ok'] for c in doc['rq3']['checks']) and not bad_targets)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
