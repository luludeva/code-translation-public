#!/usr/bin/env python3
"""Sinh writing/generated/setup-numbers.tex: số của Chương 4 (môi trường, cấu hình áp dụng, kết quả kiểm chứng, calibration, nhãn,
vận hành lượt chính). Danh sách macro theo writing/briefs/ch4-material-2026-10-27.md mục 2, 6 và các macro bản nháp §4.1 đến §4.3 dùng.
Đọc thẳng file trên nhánh kết quả và file trong repo; mỗi macro ghi nguồn `<ref>@<commit>:<file>` ở dòng chú thích ngay trên. Thiếu nguồn
thì ??. Định nghĩa bằng \\providecommand rồi \\renewcommand như census-numbers.tex. Không sửa tay file sinh ra.
Mọi số: Le chấp nhận không kiểm tay ngày 2026-11-12, trừ khi Chương 4 nêu kiểm khác.
Dùng (từ gốc repo, đã fetch các nhánh results/*, config/v6-causes, review/a3-labels):
  python3 writing/scripts/gen-setup-macros.py [--out writing/generated/setup-numbers.tex] [--tractor DIR]
  --tractor: clone TRACTOR (có commit 37960ee) để đọc rust-toolchain.toml; không có thì \\sEnvRustcCorpus là ??."""
import argparse, ast, json, os, re, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = f'{ROOT}/writing/generated/setup-numbers.tex'
TRACTOR_COMMIT = '37960ee'
FREEZE = 'bc82907'
JOB_OLD, JOB_NEW = '442d51e', '803ecba'   # commit đẩy lượt chính (trần 1440) và commit đẩy lại (trần 4320), decision-log 2026-10-27


def git(*a, cwd=ROOT):
    p = subprocess.run(['git', '-C', cwd, *a], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def rev(ref):
    r = git('rev-parse', '--short=7', ref)
    return r.strip() if r else None


class Src:
    def __init__(self, ref, label=None):
        self.ref, self.c = ref, rev(ref); self.label = label or ref.replace('refs/remotes/', '').replace('origin/', '')

    def text(self, path):
        return git('show', f'{self.c}:{path}') if self.c else None

    def json(self, path):
        t = self.text(path)
        try: return json.loads(t) if t else None
        except ValueError: return None

    def jsonl(self, path):
        t = self.text(path)
        return [json.loads(l) for l in t.splitlines() if l.strip()] if t else None

    def tag(self, path): return f'{self.label}@{self.c}:{path}'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=OUT); ap.add_argument('--tractor'); a = ap.parse_args()
    M = []

    def put(name, v, src):
        M.append((name, '??' if v is None else (f'{v:.1f}' if isinstance(v, float) else str(v)), src))

    R = lambda b: Src(f'refs/remotes/origin/results/{b}', f'results/{b}')
    cc, sw, hc, ut, v8, a3 = R('compiler-control'), R('sweep-a7'), R('harness-checks'), R('unittest-only'), R('v8'), R('a3-control-r2')
    v6c, lab = Src('refs/remotes/origin/config/v6-causes', 'config/v6-causes'), Src('refs/remotes/origin/review/a3-labels', 'review/a3-labels')
    head = Src('HEAD', 'HEAD')

    # --- E: môi trường (manifest compiler-control ở commit đo)
    p = 'ci-out/compiler-control/cc-exe/manifest.json'; m = cc.json(p) or {}; mach = m.get('machine') or {}
    put('sEnvInstance', mach.get('instance_type'), cc.tag(p)); put('sEnvInstanceId', mach.get('instance_id'), cc.tag(p))
    put('sEnvVcpu', m.get('nproc'), cc.tag(p)); put('sEnvCpu', mach.get('cpu_model'), cc.tag(p))
    put('sEnvMemGiB', None if not mach.get('mem_total_kb') else round(mach['mem_total_kb'] / 2**20, 1), cc.tag(p))
    un = m.get('uname') or ''; km = re.search(r'Linux \S+ (\S+)', un); put('sEnvKernel', km.group(1) if km else None, cc.tag(p))
    ver = lambda s, rx: (re.search(rx, s or '') or [None, None])[1]
    put('sEnvRustc', ver(m.get('rustc'), r'rustc (\S+)'), cc.tag(p)); put('sEnvClang', ver(m.get('clang'), r'clang version (\S+)'), cc.tag(p))
    put('sEnvGcc', ver(m.get('gcc'), r'\) (\S+)'), cc.tag(p)); put('sEnvAfl', ver(m.get('afl'), r'\+\+(\S+)'), cc.tag(p))
    put('sEnvPython', m.get('python'), cc.tag(p))
    rc = None
    if a.tractor:
        t = git('show', f'{TRACTOR_COMMIT}:rust-toolchain.toml', cwd=a.tractor)
        rc = ver(t, r'channel\s*=\s*"([^"]+)"')
    put('sEnvRustcCorpus', rc, f'TRACTOR@{TRACTOR_COMMIT}:rust-toolchain.toml')
    # E5: worker của các shard lượt chính (ops-summary.json, exp 30)
    ops = json.load(open(f'{ROOT}/experiments/30-main-s0/results/ops-summary.json'))
    ws = {j: s.get('workers') for j, s in ops['shards'].items() if s.get('workers')}
    main_w = max(set(ws.values()), key=list(ws.values()).count) if ws else None
    put('sEnvWorkers', main_w, 'experiments/30-main-s0/results/ops-summary.json shards.*.workers (giá trị phổ biến)')
    put('sEnvWorkersShgeti', ws.get('rq1-main-lib-shgeti'), 'ops-summary.json shards.rq1-main-lib-shgeti.workers')

    # --- C: mức ngân sách và kích thước (sweep-a7 select.json; harness/sweep.py LEVELS ở commit đo)
    p = 'ci-out/sweep-a7/select.json'; s = sw.json(p) or {}; ks = s.get('kinds') or {}
    lv = {k: (ks.get(k) or {}).get('level') for k in ('exe', 'lib')}
    put('sLevelExe', lv['exe'], sw.tag(p)); put('sLevelLib', lv['lib'], sw.tag(p))
    t = git('show', f'{FREEZE}:harness/sweep.py'); L = None
    if t:
        mm = re.search(r'^LEVELS = (\{.*?\n)(?=ORDER)', t, re.S | re.M)
        L = eval(mm.group(1), {'__builtins__': {}}, {'dict': dict}) if mm else None   # literal dict(...) trong code đã commit
    sp = f'{FREEZE}:harness/sweep.py LEVELS'
    for lvl, tok in (('x1', 'XOne'), ('x3', 'XThree'), ('x10', '')):
        e = (L or {}).get(lvl, {}).get('exe', {}); l_ = (L or {}).get(lvl, {}).get('lib', {})
        put(f'sBudgetExeInputs{tok}', e.get('budget'), sp); put(f'sBudgetAfl{tok or "Execs"}', e.get('afl_execs'), sp)
        put(f'sBudgetLib{tok or "States"}', l_.get('n_inputs'), sp)
    # P8, P9: trần job và ước tính shard đầu
    for nm, c in (('sJobCapOldMin', JOB_OLD), ('sJobCapNewMin', JOB_NEW)):
        t = git('show', f'{c}:.github/workflows/runner-jobs.yml'); mm = re.search(r'timeout-minutes:\s*(\d+)', t or '')
        put(nm, int(mm.group(1)) if mm else None, f'{c}:.github/workflows/runner-jobs.yml timeout-minutes')
    t = git('show', f'{JOB_OLD}:ci/jobs/rq1-main-exe-1of2.sh'); mm = re.search(r'x10 ([\d.]+) giờ thực', t or '')
    put('sShardEstExeOneH', float(mm.group(1)) if mm else None, f'{JOB_OLD}:ci/jobs/rq1-main-exe-1of2.sh dòng 3 (ci/main_cost.py)')

    # --- U: unit test
    for nm_run, nm_x, src, path in (('sUnitPass', 'sUnitSkip', ut, 'ci-out/unittest-only/unittest.txt'),
                                    ('sUnitRunBc', 'sUnitFailBc', hc, 'ci-out/harness-checks/unittest.txt')):
        t = src.text(path) or ''; tail = t[-400:]
        ran = re.search(r'Ran (\d+) tests', tail); sk = re.search(r'skipped=(\d+)', tail); fl = re.search(r'failures=(\d+)', tail)
        if nm_run == 'sUnitPass':
            n = int(ran.group(1)) if ran else None; k = int(sk.group(1)) if sk else 0
            put('sUnitRun', n, src.tag(path)); put(nm_run, None if n is None or 'OK' not in tail else n - k, src.tag(path)); put(nm_x, k if ran else None, src.tag(path))
        else:
            put(nm_run, int(ran.group(1)) if ran else None, src.tag(path)); put(nm_x, int(fl.group(1)) if fl else (0 if ran else None), src.tag(path))
    put('sUnitCommit', rev(ut.text('ci-out/source-commit.txt').strip()) if ut.text('ci-out/source-commit.txt') else None, ut.tag('ci-out/source-commit.txt'))

    # --- V5, V6 (harness-checks summary.txt ở commit đo)
    p = 'ci-out/harness-checks/summary.txt'; t = hc.text(p) or ''
    for k, K in (('exe', 'Exe'), ('lib', 'Lib')):
        mm = re.search(rf'V5 {k}: (\d+) cặp.*?vector đã so (\d+), cặp có vector lệch (\d+), vector lệch (\d+), vector không quan sát được \(D1\) (\d+)', t)
        g = (lambda i: int(mm.group(i)) if mm else None)
        put(f'sVFive{K}Pairs', g(1), hc.tag(p)); put(f'sVFive{K}Compared', g(1), hc.tag(p)); put(f'sVFive{K}Vec', g(2), hc.tag(p))
        put(f'sVFive{K}MisPairs', g(3), hc.tag(p)); put(f'sVFive{K}MisVec', g(4), hc.tag(p)); put(f'sVFive{K}DOne', g(5), hc.tag(p))
        mm = re.search(rf"V6 {k}: (\d+) case, trạng thái (\{{.*?\}}), input chạy (\d+), case có input không ổn định (\d+)", t)
        put(f'sVSix{K}Cases', int(mm.group(1)) if mm else None, hc.tag(p)); put(f'sVSix{K}Inputs', int(mm.group(3)) if mm else None, hc.tag(p))
        put(f'sVSix{K}Done', ast.literal_eval(mm.group(2)).get('done') if mm else None, hc.tag(p))
        put(f'sVSix{K}Unstable', int(mm.group(4)) if mm else None, hc.tag(p))
    us = [x for x in M if x[0] in ('sVSixExeUnstable', 'sVSixLibUnstable')]
    put('sVSixUnstable', None if any(v == '??' for _, v, _ in us) else sum(int(v) for _, v, _ in us), hc.tag(p) + ' (exe cộng lib)')
    rows = v6c.jsonl('ci-config/v6-causes.jsonl')
    for code, tok in (('C-UB', 'CUB'), ('C-UNINIT', 'CUninit'), ('NEAR-TO', 'NearTo'), ('HARNESS', 'Harness'), ('UNEXPLAINED', 'Unexplained')):
        put(f'sVSix{tok}', None if rows is None else sum(r.get('code') == code for r in rows), v6c.tag('ci-config/v6-causes.jsonl'))
    t = git('show', f'{FREEZE}:harness/checks.py') or ''
    mm = re.search(r'^V6_INPUTS, V6_REPS = (\d+), (\d+)', t, re.M)
    put('sVSixInputsPerCase', int(mm.group(1)) if mm else None, f'{FREEZE}:harness/checks.py V6_INPUTS')
    put('sVSixReps', int(mm.group(2)) if mm else None, f'{FREEZE}:harness/checks.py V6_REPS')

    # --- V8
    for k, K in (('exe', 'Exe'), ('lib', 'Lib')):
        p = f'ci-out/v8/{k}/v8-result.json'; r = v8.json(p); ri = v8.json(f'ci-out/v8/{k}/v8-inputs-result.json')
        o = v8.json(f'ci-out/v8/{k}/orphans-after.json')
        put(f'sVEight{K}Pass', None if r is None else ('pass' if r.get('pass') else 'fail'), v8.tag(p))
        put(f'sVEight{K}InputsPass', None if ri is None else ('pass' if ri.get('pass_') else 'fail'), v8.tag(f'ci-out/v8/{k}/v8-inputs-result.json'))
        put(f'sVEight{K}Orphans', None if o is None else len(o.get('pids') or []), v8.tag(f'ci-out/v8/{k}/orphans-after.json'))

    # --- M: mutant control (a3-control-r2)
    for k, K in (('exe', 'Exe'), ('lib', 'Lib')):
        p = f'ci-out/a3-control/a3-{k}/a3-report-{k}.json'; r = a3.json(p) or {}; D, den, C = r.get('D') or {}, r.get('denominators') or {}, r.get('C') or {}
        put(f'sMut{K}Pairs', den.get('pairs'), a3.tag(p)); put(f'sMut{K}Tried', den.get('mutants_tried'), a3.tag(p))
        put(f'sMut{K}Built', den.get('mutants_built'), a3.tag(p)); put(f'sMut{K}NotBuilt', den.get('status:not_built'), a3.tag(p))
        put(f'sMut{K}KilledVec', den.get('killed_by_vectors'), a3.tag(p)); put(f'sMut{K}Scanned', den.get('status:scan'), a3.tag(p))
        for f in ('k', 'n', 'u'): put(f'sMut{K}{f.upper()}', D.get(f), a3.tag(p))
        f3 = lambda x: None if x is None else f'{x:.3f}'   # tỉ lệ và khoảng giữ ba chữ số như a3-report
        put(f'sMut{K}Rate', f3(D.get('rate')), a3.tag(p))
        iv = D.get('interval_plan'); put(f'sMut{K}Lo', None if not iv else f3(iv[0]), a3.tag(p)); put(f'sMut{K}Hi', None if not iv else f3(iv[1]), a3.tag(p))
        put(f'sMut{K}Eq', D.get('n_equiv_not_caught'), a3.tag(p)); put(f'sMut{K}NeNotCaught', D.get('n_ne_not_caught'), a3.tag(p))
        ok = C.get('status') == 'đạt' and not C.get('i_unconfirmed') and not C.get('ii_caught_labelled_equivalent')
        put(f'sMut{K}Confirmed', None if not C else (D.get('k') if ok else 'fail'), a3.tag(p) + ' C.status')
        put(f'sMut{K}Crosscheck', None if not r else len(r.get('crosscheck_mismatch') or []), a3.tag(p))
        mp = f'ci-out/a3-control/a3-{k}/mutants-{k}.jsonl'; recs = a3.jsonl(mp)
        if recs is not None:
            caught = [(x['bundle'], x['case'], x['system']) for x in recs for mu in (x.get('mutants') or []) if mu.get('caught') is True]
            put(f'sMut{K}NTrans', len(set(caught)), a3.tag(mp) + ' (bản dịch có mutant caught)'); put(f'sMut{K}NCases', len({c[:2] for c in caught}), a3.tag(mp))
        else:
            put(f'sMut{K}NTrans', None, a3.tag(mp)); put(f'sMut{K}NCases', None, a3.tag(mp))

    # --- nhãn tương đương A3 (review/a3-labels)
    p = 'experiments/29-a3-labels/merge/agreement.md'; t = lab.text(p) or ''
    mm = re.search(r'## all\s+- Đồng thuận chính xác theo mutant \(3/3\): (\d+)/(\d+)', t)
    put('sLabMut', int(mm.group(2)) if mm else None, lab.tag(p)); put('sLabAgree', int(mm.group(1)) if mm else None, lab.tag(p))
    t = lab.text('experiments/29-a3-labels/merge/review-sample.md')
    put('sLabSample', None if t is None else len(re.findall(r'^\| *\d', t, re.M)), lab.tag('experiments/29-a3-labels/merge/review-sample.md'))
    t = lab.text('experiments/29-a3-labels/merge/expand-EQ.md')
    put('sLabExtraEq', None if t is None else sum(int(x) for x in re.findall(r'^## \w+ \((\d+) dòng\)', t, re.M)), lab.tag('experiments/29-a3-labels/merge/expand-EQ.md'))
    rows = lab.jsonl('experiments/29-a3-labels/le-decisions.jsonl')
    put('sLabToUnknown', None if rows is None else sum(r.get('label') == 'UNKNOWN' for r in rows), lab.tag('experiments/29-a3-labels/le-decisions.jsonl'))

    # --- G: compiler control
    for k, K in (('exe', 'Exe'), ('lib', 'Lib')):
        p = f'ci-out/compiler-control/cc-{k}/cc-report-{k}.json'; r = cc.json(p) or {}
        put(f'sCc{K}Cases', r.get('cases'), cc.tag(p)); put(f'sCc{K}Excluded', None if not r else len(r.get('excluded') or []), cc.tag(p))
        put(f'sCc{K}Inputs', (r.get('totals') or {}).get('inputs'), cc.tag(p)); put(f'sCc{K}DivRaw', r.get('div_raw'), cc.tag(p))
        put(f'sCc{K}DivUb', r.get('div_on_ub_inputs'), cc.tag(p)); put(f'sCc{K}Retained', r.get('retained'), cc.tag(p))

    # --- B: calibration (sweep-a7 select.json)
    p = 'ci-out/sweep-a7/select.json'
    for k, K in (('exe', 'Exe'), ('lib', 'Lib')):
        x = ks.get(k) or {}; c = x.get('counts') or {}
        for lvl, tok in (('x1', 'XOne'), ('x3', 'XThree'), ('x10', 'XTen')): put(f'sCal{K}{tok}', c.get(lvl), sw.tag(p))
        put(f'sCal{K}IncTen', None if c.get('x10') is None or c.get('x3') is None else c['x10'] - c['x3'], sw.tag(p) + ' (x10 trừ x3)')
        put(f'sCal{K}Scanned', (x.get('n_scanned') or {}).get('x10'), sw.tag(p))
        lc = x.get('low_caught_high_missed') or {}; put(f'sCal{K}LowNotHigh', None if not lc else sum(lc.values()), sw.tag(p))
        un = x.get('unconfirmed') or {}; put(f'sCal{K}Unconfirmed', None if not un else sum(len(v) for v in un.values()), sw.tag(p))
    hrs = (s.get('cap') or {}).get('hours') or {}
    put('sCalHoursExe', hrs.get('exe'), sw.tag(p) + ' cap.hours'); put('sCalHoursLib', hrs.get('lib'), sw.tag(p) + ' cap.hours')
    put('sCalHoursTotal', (s.get('cap') or {}).get('total'), sw.tag(p) + ' cap.total')
    put('sDurationCeilingH', (s.get('estimate') or {}).get('cap'), sw.tag(p) + ' estimate.cap')

    # --- S: nhãn stderr (exp 12)
    e12 = f'{ROOT}/experiments/12-stderr-audit/results'
    lc = [json.loads(l) for l in open(f'{e12}/labels-c.jsonl') if l.strip()]
    r2 = [json.loads(l) for l in open(f'{e12}/relabel/run2.jsonl') if l.strip()]; r3 = [json.loads(l) for l in open(f'{e12}/relabel/run3.jsonl') if l.strip()]
    key = lambda r: r.get('id') or f"{r.get('src')}/{r.get('kind')}/{r.get('case')}/{r.get('system')}/{r.get('idx')}"
    lab_of = lambda rs: {key(r): r.get('label') for r in rs}
    l1, l2, l3 = lab_of(lc), lab_of(r2), lab_of(r3)
    put('sStderrItems', len(lc), 'experiments/12-stderr-audit/results/labels-c.jsonl')
    put('sStderrRunAgree', sum(1 for i in l1 if l1[i] is not None and l1[i] == l2.get(i) == l3.get(i)), 'labels-c.jsonl, relabel/run2.jsonl, relabel/run3.jsonl')
    items = [json.loads(l) for l in open(f'{e12}/relabel/items.jsonl') if l.strip()]
    cs = [str(it.get('case', '')) for it in items]
    put('sStderrSameCause', max(cs.count(c) for c in set(cs)) if cs else None, 'experiments/12-stderr-audit/results/relabel/items.jsonl (case nhiều nhất)')
    t = open(f'{e12}/le-independent-20.md').read()
    mm = re.search(r'Độ khớp\s*(\d+)/(\d+)', t); mu = re.search(r'(\d+) trong (\d+) mục pilot chưa có người xem', t)
    put('sStderrAuthor', int(mm.group(2)) if mm else None, 'experiments/12-stderr-audit/results/le-independent-20.md')
    put('sStderrAuthorAgree', int(mm.group(1)) if mm else None, 'experiments/12-stderr-audit/results/le-independent-20.md')
    put('sStderrUnreviewed', int(mu.group(2)) if mu else None, 'experiments/12-stderr-audit/results/le-independent-20.md')

    # --- vận hành lượt chính (ops-summary.json, exp 30)
    A = ops.get('actions') or {}; op = 'experiments/30-main-s0/results/ops-summary.json'
    put('sMainRunners', A.get('n_runners'), op); put('sMainJobHours', A.get('hours_total'), op)
    jobs = A.get('jobs') or []
    for c, tok in (('success', 'Success'), ('failure', 'Failure'), ('cancelled', 'Cancelled')):
        put(f'sMainJobs{tok}', sum(j['conclusion'] == c for j in jobs), op); put(f'sMainJobHours{tok}', round(sum(j['hours'] for j in jobs if j['conclusion'] == c), 1), op)
    mi = ops.get('merged_inputs_exe') or {}
    for lyr in ('M', 'MS', 'A', 'S'):
        T = lyr.replace('MS', 'Ms')
        for f, tok in (('generated_by_layer', 'Gen'), ('out_of_domain_by_layer', 'Ood'), ('duplicates_by_layer', 'Dup'), ('executed_by_layer', 'Exec')):
            put(f'sMainExeInputs{tok}{T}', (mi.get(f) or {}).get(lyr, 0) if mi.get(f) is not None else None, op + f' merged_inputs_exe.{f}')
    af = mi.get('afl_status_by_record') or {}
    put('sMainExeRecords', (mi.get('records_chosen') or {}).get('exe'), op); put('sMainLibRecords', (mi.get('records_chosen') or {}).get('lib'), op)
    for st, tok in (('done', 'Done'), ('skipped', 'Skipped'), ('afl_error', 'Error'), ('afl_build_failed', 'BuildFailed'), ('None', 'Absent')):
        put(f'sMainAfl{tok}', af.get(st, 0) if af else None, op + ' merged_inputs_exe.afl_status_by_record')

    hd = git('rev-parse', 'HEAD').strip()
    with open(a.out, 'w') as f:
        f.write('% SINH TU DONG boi writing/scripts/gen-setup-macros.py. KHONG SUA TAY.\n')
        f.write(f'% Repo commit: {hd}. So Le chap nhan khong kiem tay 2026-11-12 (Chuong 4: moi truong, kiem chung, calibration, van hanh luot chinh).\n')
        for n, v, src in M:
            vv = v.replace('_', r'\_').replace('%', r'\%')
            f.write(f'% nguon: {src}\n\\providecommand{{\\{n}}}{{}}\\renewcommand{{\\{n}}}{{{vv}}}\n')
    print(f'Đã ghi {a.out}: {len(M)} macro, {sum(v == "??" for _, v, _ in M)} ??')
    for n, v, _ in M:
        if v == '??': print('  ??', n)


if __name__ == '__main__':
    main()
