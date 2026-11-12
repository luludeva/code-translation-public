"""Sweep A7 (b), mutant control A3 (b), compiler control GCC với Clang trên package harness (`docs/proposal/a3-a7-package-plan.md`
mục 2.2 đến 2.6, tiêu chí ghi trước mục 3.1 đến 3.4; Le duyệt 25/10; việc 4 của mục 6).

  python3 -m harness.sweep a7  --kind exe|lib --out OUT --mutants GEN [--levels x1,x3,x10] [--workers N] [--timeout S] [--skip-phase-r]
  python3 -m harness.sweep select --out OUT
  python3 -m harness.sweep a3  --kind exe|lib --level L --set a3-seed2 --labels F --labels-sha256 H --mutants GEN --phase-r R --out OUT
  python3 -m harness.sweep report-a3 --kind exe|lib --out OUT --labels F
  python3 -m harness.sweep cc  --level L --phase-r R --out OUT [--kind exe|lib] [--workers N]
  python3 -m harness.sweep report-cc --out OUT [--codes F]
GEN: thư mục đầu ra của `python3 -m harness.mutants gen` (mutants-<kind>.jsonl; mutant build một lần, dùng lại cho mọi mức).
R: thư mục pha R (đầu ra `harness.rq1 --pilot` ở mức L, seed 0). Build cache ở $HARNESS_BUILD như rq1.

Oracle: mọi quyết định theo input gọi `rq1.judge_exe`, `rq1.judge_lib` (Q1 (a)), nên mutant control và compiler control dùng đúng phép so
của RQ1 (luật NT, chạy lại gấp TIMEOUT_RERUN_FACTOR, ổn định qua STAB_REPS, sanitizer phía C, `retained`). Module này không có phép so
riêng; chỉ chọn input, gọi judge, đếm.

Pha R và pha M của một mức (mục 2.3):
  pha R: `rq1.main(['--pilot', ...])` với ngân sách của mức (LEVELS), ghi vào OUT/<mức>/ (cùng bố cục với job rq1-timing-pilot, nên
         `experiments/11-rq1-timing/scripts/estimate.py` đọc được); manifest của rq1 chép sang manifest-rq1-<kind>.json vì exe và lib
         ghi chung thư mục.
  pha M: đọc tập input pha R đã lưu (`inputs/<bundle>__<case>__s0.inputs.jsonl.gz`, F8; kiểm sha256 nội dung với bản ghi case). Mỗi
         cặp (case, hệ): duyệt input theo thứ tự chỉ số, chạy C một lần, bản gốc một lần (qua judge); input mà bản gốc khớp C thì judge
         từng mutant còn sống trên cùng cache (C và C-san dùng chung cho bản gốc và mọi mutant của cặp); mutant bắt được thì xác nhận
         ngay (CONFIRM_REPS lần) rồi thôi chạy mutant đó. Bản gốc chạy trên mọi input để kiểm chéo với pha R.
  Kết quả: OUT/<mức>/sweep-<kind>/mutants-<kind>.jsonl (một bản ghi mỗi cặp, resume theo khoá), summary-<kind>.json, manifest.json.

Ánh xạ tiêu chí ghi trước:
  3.1 điều kiện 1 (miền runner)          `_Exe.c_obs` (rq1.in_domain), `_Lib.c_obs` (k1 'invalid_input' của C)
      điều kiện 2 (C, bản gốc quan sát, bằng) `scan_pair`: C lib k1 'infra' bỏ; bản gốc phải có verdict 'match' của judge
      điều kiện 3, 4, 5                    `is_catch`: verdict 'div' của judge trên mutant và `retained` (ổn định, sanitizer 'no_report')
      điều kiện 6 (xác nhận)               `confirm`: CONFIRM_REPS lần chạy lại C, bản gốc, mutant; mỗi lần gốc 'match', mutant 'div'
      vector gốc bắt: để riêng             `classify_mutants` (status 'killed_by_vectors', không chạy)
      bản gốc không pass mọi vector: loại `pair_exclusion`; mọi cặp loại ghi `excluded_reason`, mọi mutant giữ dòng danh tính
  3.2 A7 luật chọn                       `choose_level` (gồm Q2 (c)), `cmd_select`; trần 72 giờ: `run_estimate` (estimate.py, sửa cơ học
                                          bỏ bản ghi `input_fields: false`), `cap_rule`; Q3 (c): `insensitive_reference` (tham khảo)
      danh tính phải trùng exp 08         `cmd_a7` gọi mutants.check_identity trước pha R, lệch thì dừng
  3.3 A3                                 `cmd_a3` (một mức, Q6 (a); file nhãn khoá: `check_labels`), `report_a3` (bảng C, D)
  3.4 GCC với Clang                      `cmd_cc`, `cc_exe_case`, `cc_lib_case`, `report_cc`; build ở `harness/controls.py`

Không gán nhãn tương đương (Q5 (b), bước riêng); `report-a3` chỉ đọc file nhãn đã khoá."""
import argparse, collections, gzip, hashlib, importlib.util, io, json, os, shutil, subprocess, time, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout

from . import build as BD
from . import controls as CT
from . import mutants as MU
from . import observe as OB
from . import pairs as PR
from . import rq1
from .config import NO_INPUT_LIB, PILOT_EXE, PILOT_LIB, REPO, TIMEOUT_RERUN_FACTOR
from .record import Store, blob, manifest, open_text
from .vectors import to_bytes

# Ngân sách ba mức như ci/jobs/budget-sweep-hgen.sh dòng 5-7 (kế hoạch mục 2.3).
LEVELS = {'x1': dict(exe=dict(budget=3000, afl_execs=10000), lib=dict(n_inputs=200)),
          'x3': dict(exe=dict(budget=9000, afl_execs=30000), lib=dict(n_inputs=600)),
          'x10': dict(exe=dict(budget=30000, afl_execs=100000), lib=dict(n_inputs=2000))}
ORDER = ('x1', 'x3', 'x10')
CONFIRM_REPS = 2                                   # 3.1 điều kiện 6: chạy thêm 2 lần
LABELS = ('DEAD', 'EQ', 'EQ-ENV', 'EQ-UB', 'NE', 'UNKNOWN')
LABEL_ALIASES = {'không xác định': 'UNKNOWN', 'khong xac dinh': 'UNKNOWN'}
EQUIV = ('DEAD', 'EQ', 'EQ-ENV', 'EQ-UB')
G_CODES = ('G1', 'G2', 'G3', 'G4')
G_FIELDS = ('c_line', 'clause', 'repro')            # 3.4: dòng code C, điều khoản chuẩn, chương trình rút gọn
ESTIMATE = f'{REPO}/experiments/11-rq1-timing/scripts/estimate.py'
EXP20 = f'{REPO}/experiments/20-c-time-exe/results/ctime-exe-8d48aa2.jsonl'
CRITERIA_MARK = 'Tiêu chí ghi trước mục 3.1 đến 3.7'   # câu của mục decision-log ghi việc Le duyệt mục 3 (kế hoạch mục 3, dòng 142)


def _sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else str(b).encode()).hexdigest()


def _sha_file(p):
    return BD.sha256(p)


def head_commit():
    return subprocess.run(['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()


def criteria_commit():
    """Commit của mục decision-log chứa câu duyệt tiêu chí mục 3 (kế hoạch dòng 142: ghi vào manifest mọi job)."""
    p = subprocess.run(['git', '-C', REPO, 'log', '-1', '--format=%H', f'-S{CRITERIA_MARK}', '--', 'docs/decision-log.md'],
                       capture_output=True, text=True)
    return p.stdout.strip() or None


def load_store(path):
    """Bản ghi mới nhất theo khoá; bỏ bản ghi '#error' khi đã có bản thành công cùng khoá; bỏ dòng hỏng cuối file."""
    out = collections.OrderedDict()
    if not os.path.exists(path): return out
    with open(path) as f: lines = f.readlines()
    for l in lines:
        l = l.strip()
        if not l: continue
        try: r = json.loads(l)
        except ValueError: continue
        k = r.get('key', '')
        if k.endswith('#error') and k[:-6] in out: continue
        out[k] = r
    for k in [k for k in out if k.endswith('#error') and k[:-6] in out]: del out[k]
    return out


def _load_jsonl(path):
    if not os.path.exists(path): return []
    with open(path) as f: return [json.loads(l) for l in f if l.strip()]


def _load_json(path):
    with open(path) as f: return json.load(f)


def _dump_json(path, obj):
    with open(path, 'w') as f: json.dump(obj, f, indent=1, ensure_ascii=False, default=str)


# ---------------- pha R ----------------
def rq1_argv(kind, L, out, workers, timeout):
    th = LEVELS[L][kind]
    a = ['--pilot', '--kind', kind, '--tag', L, '--out', out, '--seeds', '0', '--workers', str(workers), '--timeout', str(timeout)]
    if kind == 'exe': a += ['--budget', str(th['budget']), '--afl-execs', str(th['afl_execs'])]
    else: a += ['--n-inputs', str(th['n_inputs'])]
    return a


def phase_r(kind, L, out, workers, timeout):
    """Pha R: RQ1 pilot đầy đủ ở mức L (rq1 tự resume theo khoá). Đồng thời là lần đo thời gian cho estimate.py (mục 2.3)."""
    rq1.main(rq1_argv(kind, L, out, workers, timeout))
    if os.path.exists(f'{out}/manifest.json'): shutil.copy(f'{out}/manifest.json', f'{out}/manifest-rq1-{kind}.json')


def load_phase_r(rdir, kind):
    """(bản ghi case theo (bundle, case), manifest rq1 của loại này). Chỉ seed 0; bỏ bản ghi '#error' (case đó coi như chưa xong)."""
    recs = {}
    for k, r in load_store(f'{rdir}/rq1-{kind}.jsonl').items():
        if k.endswith('#error') or r.get('seed') != 0: continue
        recs[(r['bundle'], r['case'])] = r
    man = None
    for mp in (f'{rdir}/manifest-rq1-{kind}.json', f'{rdir}/manifest.json'):   # thư mục do rq1 chạy riêng chỉ có manifest.json
        if os.path.exists(mp):
            m = _load_json(mp)
            if m.get('params', {}).get('kind') == kind: man = m; break
    return recs, man


def check_phase_r(man, kind, L, timeout, allow_other_commit=False):
    """Pha R phải đúng ngân sách của mức, đúng timeout, và (Q11 (a)) cùng commit đo với job này. Trả về danh sách lỗi."""
    if man is None: return [f'thiếu manifest-rq1-{kind}.json']
    p = man.get('params', {}); err = []
    if p.get('theta') != LEVELS[L][kind]: err.append(f"theta pha R {p.get('theta')} khác mức {L} {LEVELS[L][kind]}")
    if p.get('timeout') != timeout: err.append(f"timeout pha R {p.get('timeout')} khác {timeout}")
    if p.get('seeds') != [0]: err.append(f"seed pha R {p.get('seeds')} khác [0]")
    if not allow_other_commit and man.get('repo_commit') != head_commit():
        err.append(f"pha R ở commit {man.get('repo_commit')}, job ở {head_commit()} (Q11 (a): mọi job ở commit đo)")
    return err


def inputs_file(rdir, bundle, case):
    return rq1.inputs_path(f'{rdir}/div/{bundle}__{case}__s0.jsonl')


def read_inputs(path):
    """Dòng của tập input đã lưu và sha256 của nội dung chưa nén (như record.write_inputs)."""
    h, rows = hashlib.sha256(), []
    with gzip.open(path, 'rb') as g:
        for line in g:
            h.update(line); rows.append(json.loads(line))
    return rows, h.hexdigest()


def phase_r_div_idx(rdir, bundle, case, system):
    """Tập chỉ số input mà hệ này khác C trong file divergence chính của pha R (thô hoặc .gz); None khi không có file."""
    base = f'{rdir}/div/{bundle}__{case}__s0.jsonl'; found, idx = False, set()
    for p in (base, base + '.gz'):
        if not os.path.exists(p): continue
        found = True
        with open_text(p) as f:
            for l in f:
                if not l.strip(): continue
                r = json.loads(l)
                if r.get('system') == system: idx.add(r['idx'])
    return idx if found else None


def case_inputs(rdir, rrec, bundle, case):
    """Tập input pha R của case (đã kiểm sha256, số dòng) hoặc (None, lý do loại)."""
    if rrec is None: return None, 'phase_r_case_missing'
    if rrec.get('status') != 'done': return None, f"phase_r_case_{rrec.get('status')}"
    if rrec.get('input_fields') is False: return None, 'no_input_fields'
    f = rrec.get('inputs_file') or {}
    p = inputs_file(rdir, bundle, case)
    if not os.path.exists(p): return None, 'phase_r_inputs_missing'
    rows, h = read_inputs(p)
    if h != f.get('sha256') or len(rows) != f.get('n'): return None, 'phase_r_inputs_sha256_mismatch'
    return rows, None


# ---------------- mutant ----------------
def pair_exclusion(pr):
    """Cặp bị loại trước khi chạy (3.1 dòng 154 kế hoạch, quy tắc audit 14/10). None nếu cặp chạy được."""
    if pr is None: return 'mutant_pair_missing'
    if pr.get('status') == 'harness_error': return 'mutant_gen_harness_error'
    if pr.get('error'): return 'mutant_gen_error: ' + str(pr['error'])[:200]
    if pr.get('excluded'): return 'orig_fails_vectors: ' + ','.join(pr.get('base_vector_fails') or [])
    if pr.get('base_vector_fails') is None:
        return 'orig_vector_result_unavailable'    # runner TRACTOR không ra report cho bản gốc: không chứng minh được bản gốc pass
    return None


MUT_FIELDS = ('id', 'file', 'line', 'col', 'end', 'op', 'before', 'after', 'built', 'sha256', 'rustc_bootstrap', 'new_vector_fails',
              'killed_by_vectors')


def mutant_key(pair_gen_key, mid): return f'{pair_gen_key}/m{mid}'


def classify_mutants(pr, kind, library=None, pair_excluded=False):
    """Một dòng mỗi mutant đã thử (gồm mutant không build, để mẫu số đủ). status:
      'pair_excluded' | 'not_built' | 'killed_by_vectors' (vector gốc bắt: để riêng) | 'vector_unknown' (runner không ra report cho
      mutant: không biết vector có bắt không, để riêng) | 'artifact_missing' | 'artifact_sha_mismatch' | 'scan' (đưa qua harness)."""
    out = []
    for m in (pr or {}).get('mutants', []):
        row = {k: m.get(k) for k in MUT_FIELDS}
        row['key'] = mutant_key(pr['key'], m['id']); row['caught'] = None
        if pair_excluded: st = 'pair_excluded'
        elif not m.get('built'): st = 'not_built'
        elif m.get('killed_by_vectors'): st = 'killed_by_vectors'
        elif m.get('new_vector_fails') is None: st = 'vector_unknown'
        else:
            art = m.get('artifact') if kind == 'exe' else (f"{m['root']}/translated_rust/target/release/lib{library}.so" if m.get('root') else None)
            if not art or not os.path.exists(art): st = 'artifact_missing'
            elif _sha_file(art) != m.get('sha256'): st = 'artifact_sha_mismatch'
            else: st = 'scan'; row['target'] = m['artifact'] if kind == 'exe' else m['root']
        row['status'] = st
        out.append(row)
    return out


# ---------------- hai phía: executable, library ----------------
def _brief(o, kind):
    if o is None: return None
    if kind == 'exe':
        return dict(status=o.get('status'), rc=o.get('rc'), sig=o.get('sig'), out_sha256=_sha(o.get('out') or b''),
                    err_sha256=_sha(o.get('err') or b''), out_len=len(o.get('out') or b''), err_len=len(o.get('err') or b''))
    enc = lambda s: (s or '').encode('utf-8', 'replace')
    return dict(k1=o.get('k1'), result=o.get('result'), stdout_sha256=_sha(enc(o.get('stdout'))), stderr_sha256=_sha(enc(o.get('stderr'))),
                state_sha256=_sha(json.dumps(o.get('state_out'), sort_keys=True, default=str)), state_nonfinite=o.get('state_nonfinite'))


class _Exe:
    kind = 'exe'

    def __init__(self, t):
        self.t = t

    def prepare(self, orig=True):
        t = self.t; B = t['B']
        self.c = BD.build_c_exe(B, t['bundle'], t['case']); self.cs = BD.build_c_exe(B, t['bundle'], t['case'], san=True)
        if not self.c.get('ok'): return 'c_build_failed'
        self.timeout = rq1.case_timeout(t['bundle'], t['case'], t['timeout'])
        if orig:
            o = BD.build_rust_exe(B, t['system'], t['bundle'], t['case'], t['hcase'])
            if not o.get('ok'): return 'orig_build_failed'
            if t.get('orig_sha256') and o.get('sha256') != t['orig_sha256']: return 'orig_sha256_mismatch'
            self.orig_target = o['bin']
        return None

    def c_obs(self, row, tag=''):
        if not rq1.in_domain(row['argv'], row['stdin']): return 'out_of_domain', None          # 3.1 điều kiện 1
        return 'ok', dict(co=OB.run_exe(self.c['bin'], row['argv'], row['stdin'], self.timeout, row.get('env')), san=None)

    def judge(self, target, rtag, row, cache, tag=''):
        return rq1.judge_exe(self.c['bin'], self.cs, target, row['argv'], row['stdin'], row.get('env'), self.timeout, cache)

    def input_of(self, row):
        return dict(argv=row['argv'], stdin=row['stdin'], env=row.get('env'))

    def cleanup(self): pass


class _Lib:
    kind = 'lib'

    def __init__(self, t):
        self.t = t

    def prepare(self, orig=True):
        t = self.t; B = t['B']
        info = BD.build_lib_case(B, t['bundle'], t['case']); self.info = info
        if not (info.get('runner_ok') and info.get('c_ok')): return 'c_build_failed'
        self.library = info['library']; self.rb = info['runner_bin']
        self.croot = BD.lib_root(B, info, 'c'); self.csroot = BD.lib_root(B, info, 'c-san') if info.get('c-san_ok') else None
        self.preload = BD.asan_preload(); self.timeout = t['timeout']      # library: timeout gốc, như rq1_lib_case
        base = f"{t['run_tag']}/{t['bundle']}/{t['case']}/{t.get('system') or 'cc'}"
        self.dd = f'{B}/dumps-sweep/{base}'; self.vd = f'{B}/sweep-vec/{base}'
        for d in (self.dd, self.vd): shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
        if orig:
            o = BD.build_rust_lib(B, t['system'], t['bundle'], t['case'], t['hcase'], info['library'])
            if not o.get('ok'): return 'orig_build_failed'
            if t.get('orig_sha256') and o.get('sha256') != t['orig_sha256']: return 'orig_sha256_mismatch'
            self.orig_target = BD.lib_root(B, info, 'rust', o['dir'], tag=f"rust-{t['system']}")   # đúng root của RQ1
        return None

    def vec(self, row):
        p = f"{self.vd}/{row['i']}.json"
        if not os.path.exists(p):
            with open(p, 'w') as f: json.dump(row['vector'], f)
        return p

    def _pref(self, row, tag): return f"{self.dd}/{row['i']}" + (f'.{tag}' if tag else '')

    def c_obs(self, row, tag=''):
        p = self.vec(row)
        co = rq1._rl(self.rb, self.croot, p, self.timeout, False, f'{self._pref(row, tag)}.C.dump')
        if co.get('k1') == 'invalid_input': return 'out_of_domain', None                    # 3.1 điều kiện 1
        if co.get('k1') == 'infra': return 'c_infra', None                                   # 3.1 điều kiện 2: C không quan sát được
        return 'ok', dict(co=co, san=None)

    def judge(self, target, rtag, row, cache, tag=''):
        return rq1.judge_lib(self.rb, self.croot, self.csroot, self.preload, target, rtag, self.vec(row), self._pref(row, tag),
                             self.timeout, cache)

    def input_of(self, row):
        return dict(vector=row['vector'])

    def cleanup(self):
        for d in (self.dd, self.vd): shutil.rmtree(d, ignore_errors=True)


SIDES = dict(exe=_Exe, lib=_Lib)


def is_catch(j):
    """3.1 điều kiện 3 đến 5 trên kết quả judge của mutant: mutant quan sát được và khác C ('div'), divergence ổn định, sanitizer phía C
    'no_report' (đúng `retained` của rq1.san_counts)."""
    return j['verdict'] == 'div' and j['retained'] is True


def outcome(j):
    if j['verdict'] in ('match', 'infra'): return j['verdict']
    if not j['stable']: return 'div_unstable'
    if j['san']['status'] != 'no_report': return f"div_san_{j['san']['status']}"
    return 'catch'


def catch_info(side, row, j):
    return dict(idx=row['i'], layer=row.get('layer'), source=row.get('source'), input=side.input_of(row), channels=j['channels'],
                c=_brief(j['c'], side.kind), m=_brief(j['r'], side.kind), san=j['san']['status'], san_markers=j['san'].get('markers'),
                timeout_rerun=(j['info'] or {}).get('timeout_rerun'), timeout_confirmed=(j['info'] or {}).get('timeout_confirmed'),
                c_flag=j['c_flag'], cap_hit=j['cap_hit'])


def confirm(side, m, row, san, reps=CONFIRM_REPS):
    """3.1 điều kiện 6: chạy C, bản gốc, mutant thêm `reps` lần trên x, mỗi lần qua judge (cùng phép so RQ1); đạt khi mọi lần bản gốc
    'match' và mutant 'div'. Kết quả sanitizer phía C trên x lấy lại từ lần bắt (điều kiện 6 không xét sanitizer)."""
    runs = []
    for k in range(reps):
        tag = f'cf{k}'
        st, cache = side.c_obs(row, tag)
        if st != 'ok': runs.append(dict(c=st, ok=False)); continue
        cache['san'] = san
        jo = side.judge(side.orig_target, 'orig', row, cache, tag)
        jm = side.judge(m['target'], f"m{m['id']}", row, cache, tag)
        runs.append(dict(orig=jo['verdict'], mutant=jm['verdict'], mutant_stable=jm['stable'], mutant_retained=jm['retained'],
                         ok=jo['verdict'] == 'match' and jm['verdict'] == 'div'))
    return dict(confirmed=len(runs) == reps and all(r['ok'] for r in runs), reps=reps, runs=runs)


def scan_pair(side, rows, muts, confirm_reps=CONFIRM_REPS):
    """Vòng pha M của một cặp. Input theo thứ tự chỉ số; mutant dừng ở lần bắt đầu tiên (kết quả như duyệt từng mutant riêng, vì mỗi
    mutant gặp input theo cùng thứ tự). Trả về (bộ đếm theo input, tập chỉ số bản gốc khác C)."""
    cnt, orig_div = collections.Counter(), set()
    alive = [m for m in muts if m['status'] == 'scan']
    for m in alive: m.update(caught=False, outcomes=collections.Counter())
    for row in rows:
        st, cache = side.c_obs(row)
        cnt['inputs'] += 1
        if st != 'ok': cnt[st] += 1; continue
        jo = side.judge(side.orig_target, 'orig', row, cache)
        cnt[f"orig_{jo['verdict']}"] += 1
        if jo['verdict'] != 'match':                                   # 3.1 điều kiện 2: bản gốc phải bằng C trên x
            if jo['verdict'] == 'div': orig_div.add(row['i'])
            continue
        for m in list(alive):
            jm = side.judge(m['target'], f"m{m['id']}", row, cache)
            oc = outcome(jm); m['outcomes'][oc] += 1
            if is_catch(jm):
                m.update(caught=True, catch=catch_info(side, row, jm), confirm=confirm(side, m, row, cache['san'], confirm_reps))
                alive.remove(m)
    for m in muts:
        if 'outcomes' in m: m['outcomes'] = dict(m['outcomes'])
    return cnt, orig_div


def crosscheck(rdir, rrec, t, cnt, orig_div):
    """Kiểm chéo nội bộ (mục 2.3): tập input bản gốc khác C ở pha M phải trùng tập idx của hệ trong file divergence pha R; lệch thì ghi,
    không sửa. Library: số input ngoài miền phải trùng `out_of_domain_by_source` của pha R; executable: 0 (pha R đã lọc)."""
    out = dict(n_orig_div_m=len(orig_div))
    if t.get('system') not in (rrec.get('counts') or {}):
        out.update(equal=None, note='system_not_in_phase_r'); return out
    r = phase_r_div_idx(rdir, t['bundle'], t['case'], t['system'])
    if r is None: out.update(equal=None, note='phase_r_div_file_missing'); return out
    ood_r = sum((rrec.get('out_of_domain_by_source') or {}).values()) if t['kind'] == 'lib' else 0
    out.update(equal=r == orig_div and cnt.get('out_of_domain', 0) == ood_r, n_orig_div_r=len(r),
               only_m=sorted(orig_div - r)[:50], only_r=sorted(r - orig_div)[:50], out_of_domain_m=cnt.get('out_of_domain', 0),
               out_of_domain_r=ood_r)
    return out


def pair_task(t):
    """Một cặp ở một mức. t: dict thuần (gửi được sang tiến trình con)."""
    T0 = time.time(); pr = t['pair']
    rec = dict(key=t['key'], job=t['job'], set=t['set'], kind=t['kind'], level=t['level'], system=t['system'], bundle=t['bundle'],
               case=t['case'], hcase=t['hcase'], gen_key=t['gen_key'], timeout_base=t['timeout'])
    reason = pair_exclusion(pr)
    rows = None
    if not reason: rows, reason = case_inputs(t['rdir'], t['rrec'], t['bundle'], t['case'])
    side = SIDES[t['kind']](t)
    if not reason: reason = side.prepare()
    if reason:
        rec.update(status='excluded', excluded_reason=reason, mutants=classify_mutants(pr, t['kind'], pair_excluded=True),
                   base_vector_fails=(pr or {}).get('base_vector_fails'), secs=round(time.time() - T0, 2))
        side.cleanup() if hasattr(side, 'dd') else None
        return rec
    try:
        muts = classify_mutants(pr, t['kind'], getattr(side, 'library', None))
        cnt, orig_div = scan_pair(side, rows, muts, t['confirm_reps'])
    finally:
        side.cleanup()
    for m in muts: m.pop('target', None)
    rec.update(status='done', timeout=side.timeout, n_inputs=len(rows), counts=dict(cnt), crosscheck=crosscheck(t['rdir'], t['rrec'], t, cnt, orig_div),
               mutants=muts, orig_sha256=pr.get('orig_sha256'), secs=round(time.time() - T0, 2))
    return rec


def _safe(fn, t):
    try:
        return fn(t)
    except Exception:
        return dict(status='harness_error', error=traceback.format_exc()[-3000:])


def run_tasks(fn, tasks, workers, sink):
    """workers 1: chạy tuần tự trong tiến trình này; lớn hơn: ProcessPoolExecutor như rq1.main."""
    if workers <= 1:
        for t in tasks: sink(t, _safe(fn, t))
        return
    with ProcessPoolExecutor(workers) as ex:
        futs = {ex.submit(_safe, fn, t): t for t in tasks}
        for fut in as_completed(futs): sink(futs[fut], fut.result())


def summarize(recs):
    """Mẫu số đầy đủ của một (loại, mức): cặp, cặp loại kèm lý do, mutant theo trạng thái, bắt (1-5), xác nhận (6)."""
    s = collections.Counter(); excl = []; caught = []; unconfirmed = []; xc = []
    for r in recs:
        s['pairs'] += 1; s[f"pairs_{r.get('status')}"] += 1
        if r.get('status') == 'excluded': excl.append(dict(key=r['key'], reason=r['excluded_reason']))
        if r.get('status') == 'harness_error': excl.append(dict(key=r['key'], reason='harness_error'))
        if r.get('crosscheck', {}).get('equal') is False: xc.append(r['key'])
        for m in r.get('mutants', []):
            s['mutants_tried'] += 1; s['mutants_built'] += bool(m.get('built')); s[f"status:{m['status']}"] += 1
            s['killed_by_vectors'] += bool(m.get('killed_by_vectors'))
            if m.get('caught'):
                caught.append(m['key'])
                if not m['confirm']['confirmed']: unconfirmed.append(m['key'])
    return dict(counts=dict(s), excluded_pairs=excl, caught=caught, n_caught=len(caught), unconfirmed=unconfirmed,
                n_confirmed=len(caught) - len(unconfirmed), crosscheck_mismatch=xc)


# ---------------- pha M ----------------
def gen_pairs(gen_dir, set_name, kind):
    """Bản ghi cặp của `harness.mutants gen` theo khoá, bỏ '#error' khi đã có bản thành công."""
    return {k: r for k, r in load_store(f'{gen_dir}/mutants-{kind}.jsonl').items() if r.get('set') == set_name and r.get('kind') == kind}


def phase_m(job, kind, set_name, L, rdir, gen_dir, out, workers, timeout, extra=None, allow_other_commit=False):
    recs_r, man = load_phase_r(rdir, kind)
    err = check_phase_r(man, kind, L, timeout, allow_other_commit)
    if err: raise SystemExit('pha R không dùng được: ' + '; '.join(err))
    gp = gen_pairs(gen_dir, set_name, kind)
    ps = MU.set_pairs(set_name, kind)
    keys = [f"{L}/{MU.pair_key(set_name, kind, p)}" for p in ps]
    gfile = f'{gen_dir}/mutants-{kind}.jsonl'
    manifest(out, dict(cmd=f'sweep-{job}', kind=kind, set=set_name, level=L, theta=LEVELS[L][kind], phase_r=os.path.abspath(rdir),
                       phase_r_commit=man.get('repo_commit'), phase_r_created=man.get('created_utc'), mutants_file=os.path.abspath(gfile),
                       mutants_file_sha256=_sha_file(gfile), timeout=timeout, workers=workers, confirm_reps=CONFIRM_REPS,
                       stab_reps=rq1.STAB_REPS, san_timeout_factor=rq1.SAN_TIMEOUT_FACTOR, timeout_rerun_factor=TIMEOUT_RERUN_FACTOR,
                       criteria_commit=criteria_commit(), build_dir=os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness')),
                       oracle='rq1.judge_exe / rq1.judge_lib', pairs=keys, **(extra or {})))
    store = Store(f'{out}/mutants-{kind}.jsonl')
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness'))
    if kind == 'lib': BD.setup_cando2(B)
    tasks = []
    for p, k in zip(ps, keys):
        if store.has(k): continue
        gk = MU.pair_key(set_name, kind, p); pr = gp.get(gk) or gp.get(gk + '#error')   # '#error': lỗi harness lúc sinh
        tasks.append(dict(job=job, key=k, gen_key=gk, set=set_name, kind=kind, level=L, system=p['system'], bundle=p['bundle'],
                          case=p['case'], hcase=p['hcase'], pair=pr, rdir=rdir, rrec=recs_r.get((p['bundle'], p['case'])), B=B,
                          timeout=timeout, confirm_reps=CONFIRM_REPS, orig_sha256=(pr or {}).get('orig_sha256'),
                          run_tag=f'{job}-{L}'))
    print(f'sweep {job} {kind} {L}: {len(tasks)} cặp cần chạy, {workers} worker', flush=True)

    def sink(t, r):
        if r.get('status') == 'harness_error':
            r.update(key=t['key'] + '#error', kind=kind, level=L, system=t['system'], bundle=t['bundle'], case=t['case'])
        store.put(r)
        print(r['key'], r.get('status'), r.get('excluded_reason', ''), r.get('secs'), flush=True)
    run_tasks(pair_task, tasks, workers, sink)
    recs = [r for k, r in load_store(f'{out}/mutants-{kind}.jsonl').items() if not k.endswith('#error')]
    s = summarize(recs); s['missing_pairs'] = [k for k in keys if k not in {r['key'] for r in recs}]
    _dump_json(f'{out}/summary-{kind}.json', s)
    return s


# ---------------- a7 ----------------
def cmd_a7(a):
    kind, set_name = a.kind, a.set
    if set_name != 'a7-seed1': raise SystemExit('a7 chỉ chạy bộ chọn ngân sách a7-seed1 (kế hoạch mục 3.2)')
    levels = a.levels.split(',')
    if [L for L in levels if L not in LEVELS]: raise SystemExit(f'mức không hợp lệ: {levels}')
    os.makedirs(a.out, exist_ok=True)
    # 3.2: sinh lại trong package phải trùng danh tính exp 08; lệch thì dừng, báo Le (trước khi tốn máy cho pha R)
    gp = gen_pairs(a.mutants, set_name, kind)
    res = MU.check_identity(kind, list(gp.values()))
    _dump_json(f'{a.out}/identity-check-{kind}.json', res)
    bad = [r for r in res if r['status'] != 'identical']
    if bad: raise SystemExit(f'danh tính bộ a7-seed1 lệch exp 08 ở {len(bad)} cặp (identity-check-{kind}.json): dừng, báo Le')
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness'))
    start = f'{a.out}/a7-{kind}-start.json'
    if not os.path.exists(start):      # 3.2: estimate.py cần HARNESS_BUILD mới (cache làm số build mỗi case bằng 0)
        _dump_json(start, dict(build_dir=B, build_dir_preexisting=os.path.isdir(B) and bool(os.listdir(B)),
                               utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
    out = {}
    for L in levels:
        rdir = f'{a.out}/{L}'
        if not a.skip_phase_r: phase_r(kind, L, rdir, a.workers, a.timeout)
        out[L] = phase_m('a7', kind, set_name, L, rdir, a.mutants, f'{rdir}/sweep-{kind}', a.workers, a.timeout,
                         allow_other_commit=a.allow_other_commit)
        print(json.dumps(dict(level=L, n_caught=out[L]['n_caught'], n_confirmed=out[L]['n_confirmed'],
                              missing=len(out[L]['missing_pairs'])), ensure_ascii=False), flush=True)
    return out


# ---------------- 3.2: luật chọn mức ----------------
def choose_level(c):
    """Luật decision-log 2026-10-22 (dòng 512): (vế 1) mức nhỏ nhất trong x1, x3, x10 mà mức kế tiếp không bắt thêm (x10 không có mức kế
    tiếp); (vế 2) x10 vẫn bắt thêm so với x3 thì x10. "Bắt thêm" theo số đếm (decision-log 2026-10-25, A7). Hai vế cho hai mức khác
    nhau thì không tự chọn (Q2 (c)): 'q2c' khi c(x1) = c(x3) < c(x10) (ca Q2 nêu); 'conflict' khi c(x3) < c(x1) và c(x10) > c(x3)
    (cùng kiểu mâu thuẫn, kế hoạch không nêu tên; báo Le như nhau)."""
    c1, c3, c10 = (c[L] for L in ORDER)
    first = 'x1' if c3 <= c1 else ('x3' if c10 <= c3 else 'x10')
    second = 'x10' if c10 > c3 else None
    if second and first != second:
        return dict(level=None, status='q2c' if c1 == c3 else 'conflict', first=first, second=second, counts=dict(c))
    return dict(level=first, status='chosen', first=first, second=second, counts=dict(c))


def cap_rule(hours, start, cap):
    """Trần (decision-log dòng 513-515; vòng hạ bậc chép từ estimate.py main): bắt đầu ở mức theo số mutant của từng loại; tổng vượt
    trần thì hạ một bậc loại có giờ lớn hơn; loại đó hết bậc thì hạ loại kia; cả hai hết bậc mà vẫn vượt: không có nghiệm."""
    pick = {k: ORDER.index(L) for k, L in start.items()}
    while True:
        h = {k: hours.get((k, ORDER[i])) for k, i in pick.items()}
        if None in h.values(): return dict(status='missing', pick={k: ORDER[i] for k, i in pick.items()}, hours=h)
        tot = sum(h.values())
        if tot <= cap: return dict(status='chosen', pick={k: ORDER[i] for k, i in pick.items()}, hours=h, total=round(tot, 2))
        k = max(h, key=h.get)
        if pick[k] == 0:
            k2 = min(h, key=h.get)
            if pick[k2] == 0: return dict(status='no_solution', pick={k: ORDER[i] for k, i in pick.items()}, hours=h, total=round(tot, 2))
            k = k2
        pick[k] -= 1


def run_estimate(out):
    """estimate.py (exp 11) trên pha R của job này, với sửa cơ học bắt buộc của 3.2: bỏ bản ghi `input_fields: false` khỏi trung bình
    (thay hàm `load` của module lúc chạy; file script không đổi). Trả về bảng giờ máy theo (loại, mức), dòng kết quả luật của script
    (bắt đầu từ x10 theo bão hoà, chỉ để đối chiếu) và bản ghi đã bỏ."""
    spec = importlib.util.spec_from_file_location('exp11_estimate', ESTIMATE)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    orig, dropped = mod.load, []

    def load(d, kind):
        rs, w = orig(d, kind)
        dropped.extend(r['key'] for r in rs if r.get('input_fields') is False)
        return [r for r in rs if r.get('input_fields') is not False], w
    mod.load = load
    buf = io.StringIO()
    with redirect_stdout(buf): mod.main(out)
    text = buf.getvalue(); hours = {}; rows = []
    for l in text.splitlines():
        cols = [x.strip() for x in l.strip().strip('|').split('|')]
        if len(cols) == 7 and cols[0] in ('exe', 'lib') and cols[1] in ORDER:
            rows.append(cols)
            try: hours[(cols[0], cols[1])] = float(cols[6])
            except ValueError: pass
    verdict = next((l.split('Kết quả luật:', 1)[1].strip() for l in text.splitlines() if 'Kết quả luật:' in l), None)
    return dict(hours=hours, rows=rows, script_verdict=verdict, dropped=sorted(set(dropped)), cap=mod.CAP_HOURS, seeds=mod.SEEDS, text=text)


def insensitive_reference(hours, exp20=EXP20):
    """Q3 (c), chỉ tham khảo, không dùng chọn mức: case exe lượt chính không đọc input (cờ `input_insensitive` của exp 20) chạy một seed,
    chỉ vector; thời gian = tổng theo vector của thời gian C lớn nhất trong 3 lần đo (exp 20) nhân số hệ P_rep của case. Phần còn lại
    giữ mô hình estimate.py, tỉ lệ theo số case (mô hình tuyến tính theo N_k)."""
    prs = PR.prep_pairs('exe'); n_sys = collections.Counter((r['bundle'], r['tractor_case']) for r in prs)
    N = len(PR.cases_of(prs)); term, n_ins = 0.0, 0
    for r in _load_jsonl(exp20):
        b, c = r['key'].split('/', 1)
        if not r.get('input_insensitive') or (b, c) not in n_sys: continue
        n_ins += 1; term += sum(max(v['secs']) for v in r.get('vectors', []) if v.get('secs')) * n_sys[(b, c)]
    alt = {L: round(hours[('exe', L)] * (N - n_ins) / N + term / 3600, 2) for L in ORDER if ('exe', L) in hours and N}
    return dict(n_main_exe_cases=N, n_insensitive=n_ins, insensitive_hours=round(term / 3600, 3), exe_hours_alt=alt,
                note='tham khảo (Q3 (c)); không dùng để chọn mức')


def level_recs(out, L, kind):
    p = f'{out}/{L}/sweep-{kind}'
    man = _load_json(f'{p}/manifest.json') if os.path.exists(f'{p}/manifest.json') else None
    recs = {k: r for k, r in load_store(f'{p}/mutants-{kind}.jsonl').items() if not k.endswith('#error')}
    return man, recs


def kind_selection(out, kind):
    """Đại lượng c_k(L) của 3.2 (3.1 điều kiện 1 đến 5, cộng 3 hệ) và phần báo cáo danh tính, cho một loại."""
    caught, unconf, uni, missing, anomalies = {}, {}, {}, {}, {}
    for L in ORDER:
        man, recs = level_recs(out, L, kind)
        if man is None: missing[L] = ['chưa chạy']; continue
        want = man['params']['pairs']; got = {k: r for k, r in recs.items() if r.get('status') in ('done', 'excluded')}
        miss = [k for k in want if k not in got]
        if miss: missing[L] = miss
        ms = [m for r in got.values() for m in r.get('mutants', [])]
        caught[L] = {m['key'] for m in ms if m.get('caught')}
        unconf[L] = sorted(m['key'] for m in ms if m.get('caught') and not m['confirm']['confirmed'])
        uni[L] = {m['key'] for m in ms if m['status'] == 'scan'}
        # Loại hợp lệ theo luật đã ghi: bản gốc không pass mọi vector (audit 14/10). Mutant để riêng hợp lệ: không build, vector bắt.
        anomalies[L] = sorted([f"{r['key']}: {r['excluded_reason']}" for r in got.values() if r.get('status') == 'excluded'
                               and not r['excluded_reason'].startswith('orig_fails_vectors')]
                              + [f"{m['key']}: {m['status']}" for m in ms if m['status'] in ('vector_unknown', 'artifact_missing',
                                                                                             'artifact_sha_mismatch')])
    res = dict(kind=kind, missing=missing, anomalies=anomalies)
    if missing or len(caught) < 3:
        res.update(status='thiếu số đo', level=None); return res
    if any(anomalies.values()):          # loại hoặc để riêng ngoài luật đã ghi: không tự chọn, báo Le
        res.update(status='anomalies', level=None); return res
    same = uni['x1'] == uni['x3'] == uni['x10']
    c = {L: len(caught[L]) for L in ORDER}
    rule = choose_level(c) if same else dict(level=None, status='universe_differs', counts=c)
    low_not_high = {f'{lo}-{hi}': sorted(caught[lo] - caught[hi]) for lo, hi in (('x1', 'x3'), ('x1', 'x10'), ('x3', 'x10'))}
    res.update(status=rule['status'], level=rule['level'], rule=rule, counts=c, scanned_same_across_levels=same,
               n_scanned={L: len(uni[L]) for L in ORDER}, caught={L: sorted(caught[L]) for L in ORDER},
               low_caught_high_missed={k: len(v) for k, v in low_not_high.items()}, low_caught_high_missed_keys=low_not_high,
               unconfirmed=unconf)
    return res


def cmd_select(a):
    res = dict(kinds={k: kind_selection(a.out, k) for k in ('exe', 'lib')})
    start = {k: v['level'] for k, v in res['kinds'].items()}
    if not a.no_estimate:
        est = run_estimate(a.out)
        res['estimate'] = {k: v for k, v in est.items() if k != 'hours'}
        res['estimate']['hours'] = {f'{k}/{L}': h for (k, L), h in est['hours'].items()}
        res['build_dir_preexisting'] = {k: _load_json(f'{a.out}/a7-{k}-start.json').get('build_dir_preexisting')
                                        for k in ('exe', 'lib') if os.path.exists(f'{a.out}/a7-{k}-start.json')}
        if None in start.values():
            res['cap'] = dict(status='not_applied', reason='luật đếm chưa cho mức ở ít nhất một loại: báo Le')
        else:
            res['cap'] = cap_rule(est['hours'], start, est['cap'])
        res['insensitive_reference'] = insensitive_reference(est['hours'])
    final = res.get('cap', {}).get('status') == 'chosen'
    res['verdict'] = (f"L* đề xuất: exe {res['cap']['pick']['exe']}, lib {res['cap']['pick']['lib']} (chờ Le duyệt)" if final
                      else 'không tự chọn: báo Le')
    _dump_json(f'{a.out}/select.json', res)
    print(select_md(res))
    return res


def select_md(res):
    L = ['# Chọn ngân sách A7 (sweep package)', '']
    for k, v in res['kinds'].items():
        L.append(f"- {k}: trạng thái {v['status']}, mức {v.get('level')}, c = {v.get('counts')}, "
                 f"mức thấp bắt mà mức cao bỏ sót {v.get('low_caught_high_missed')}, chưa qua xác nhận {sum(len(x) for x in (v.get('unconfirmed') or {}).values())}")
        if v.get('missing'): L.append(f"  thiếu: {json.dumps(v['missing'], ensure_ascii=False)[:500]}")
    if 'cap' in res: L.append(f"- trần: {json.dumps(res['cap'], ensure_ascii=False, default=str)}")
    if 'insensitive_reference' in res: L.append(f"- Q3 (c) tham khảo: {json.dumps(res['insensitive_reference'], ensure_ascii=False)}")
    L.append(f"- kết luận: {res['verdict']}")
    return '\n'.join(L)


# ---------------- a3 ----------------
def labels_locked(path, commit=None):
    """File nhãn phải được git theo dõi và không đổi so với HEAD (khoá bằng commit trước khi đẩy job, mục 2.5).
    commit (Le chọn 26/10: nhãn nằm ở nhánh cấu hình config/a3-labels để A3 chạy cùng commit đo với sweep): 'C:đường dẫn' trong repo;
    khoá khi nội dung file bằng đúng blob đó."""
    if commit:
        b = subprocess.run(['git', '-C', REPO, 'show', commit], capture_output=True)
        return b.returncode == 0 and b.stdout == open(path, 'rb').read()
    rel = os.path.relpath(os.path.abspath(path), REPO)
    t = subprocess.run(['git', '-C', REPO, 'ls-files', '--error-unmatch', rel], capture_output=True)
    d = subprocess.run(['git', '-C', REPO, 'diff', '--quiet', 'HEAD', '--', rel], capture_output=True)
    return t.returncode == 0 and d.returncode == 0


def load_labels(path):
    """JSONL, một dòng mỗi mutant: key (như dòng danh tính của harness.mutants: <set>/<kind>/<bundle>/<case>/<hệ>/m<id>), label (LABELS
    hoặc 'không xác định'), tuỳ chọn các trường danh tính (file, line, col, op, before, after) để kiểm khớp."""
    out = {}
    for r in _load_jsonl(path):
        lab = LABEL_ALIASES.get(str(r.get('label')).strip().lower(), str(r.get('label')).strip())
        if lab not in LABELS: raise SystemExit(f"nhãn không hợp lệ {r.get('label')!r} ở {r.get('key')}")
        if r['key'] in out: raise SystemExit(f"nhãn trùng khoá {r['key']}")
        out[r['key']] = dict(r, label=lab)
    return out


def check_labels(path, sha, gp, kind, commit=None):
    """Điều kiện trước khi harness chạm bộ A3 (mục 2.5, 3.3): sha256 đúng giá trị ghi trong job, file khoá ở HEAD, mọi mutant build được
    mà vector không bắt đều có nhãn, trường danh tính (nếu có trong file nhãn) khớp bản sinh lại."""
    if _sha_file(path) != sha: raise SystemExit(f'sha256 file nhãn {_sha_file(path)} khác {sha}: từ chối chạy')
    if not labels_locked(path, commit): raise SystemExit('file nhãn chưa khoá bằng commit (chưa theo dõi, khác HEAD hoặc khác blob ở --labels-commit): từ chối chạy')
    labs = load_labels(path); miss, diff = [], []
    for pr in gp.values():
        for m in pr.get('mutants', []):
            if not m.get('built') or m.get('killed_by_vectors'): continue
            k = mutant_key(pr['key'], m['id']); l = labs.get(k)
            if l is None: miss.append(k); continue
            diff += [k for f in ('file', 'line', 'col', 'op', 'before', 'after') if f in l and l[f] != m.get(f)][:1]
    if miss: raise SystemExit(f'{len(miss)} mutant chưa có nhãn (vd {miss[:3]}): từ chối chạy')
    if diff: raise SystemExit(f'{len(diff)} mutant lệch danh tính với file nhãn (vd {diff[:3]}): từ chối chạy')
    return labs


def cmd_a3(a):
    if not (a.set.startswith('a3-') and a.set in MU.SETS): raise SystemExit(f'bộ A3 không hợp lệ: {a.set}')
    if a.level not in LEVELS: raise SystemExit(f'mức không hợp lệ: {a.level}')
    gp = gen_pairs(a.mutants, a.set, a.kind)
    check_labels(a.labels, a.labels_sha256, gp, a.kind, getattr(a, 'labels_commit', None))
    rdir = a.phase_r
    if not rdir:
        rdir = f'{a.out}/{a.level}'; phase_r(a.kind, a.level, rdir, a.workers, a.timeout)
    out = f'{a.out}/a3-{a.kind}'
    s = phase_m('a3', a.kind, a.set, a.level, rdir, a.mutants, out, a.workers, a.timeout,
                extra=dict(labels=os.path.abspath(a.labels), labels_sha256=a.labels_sha256, level_note='chỉ L* (Q6 (a))'),
                allow_other_commit=a.allow_other_commit)
    rep = report_a3(out, a.kind, a.labels)
    print(json.dumps(dict(summary=dict(n_caught=s['n_caught'], n_confirmed=s['n_confirmed']), C=rep['C']['status'], D=rep['D']),
                     ensure_ascii=False))
    return rep


def report_a3(out, kind, labels_path):
    """Bảng C (chặn, A4) và D (báo) của 3.3 trên kết quả pha M của bộ A3."""
    labs = load_labels(labels_path)
    recs = [r for k, r in load_store(f'{out}/mutants-{kind}.jsonl').items() if not k.endswith('#error')]
    s = summarize(recs)
    c_i, c_ii, k_keys, ne_miss, unk_miss, eq_miss, no_label = [], [], [], [], [], [], []
    for r in recs:
        for m in r.get('mutants', []):
            if m['status'] != 'scan': continue
            lab = (labs.get(m['key']) or {}).get('label')
            if lab is None: no_label.append(m['key']); continue
            if m.get('caught'):
                if not m['confirm']['confirmed']: c_i.append(m['key'])
                if lab in EQUIV: c_ii.append(dict(key=m['key'], label=lab, catch_idx=m['catch']['idx']))
                elif m['confirm']['confirmed']: k_keys.append(m['key'])
            elif lab == 'NE': ne_miss.append(m['key'])
            elif lab == 'UNKNOWN': unk_miss.append(m['key'])
            else: eq_miss.append(m['key'])
    k, u = len(k_keys), len(unk_miss); n = k + len(ne_miss)
    frac = lambda x, y: round(x / y, 4) if y else None
    C = dict(i_unconfirmed=c_i, ii_caught_labelled_equivalent=c_ii,
             status='đạt' if not c_i and not c_ii and not no_label else 'chưa đạt: Le giải quyết từng ca (nhãn sai hoặc lỗi harness, Q12 (b))')
    D = dict(k=k, n=n, u=u, rate=frac(k, n), interval_plan=[frac(k, n + u), frac(k + u, n + u)], interval_exp07=[frac(k, n + u), frac(k, n)],
             n_ne_not_caught=len(ne_miss), n_equiv_not_caught=len(eq_miss), note='k: bắt qua xác nhận, nhãn khác DEAD, EQ, EQ-ENV, EQ-UB')
    rep = dict(kind=kind, C=C, D=D, denominators=s['counts'], excluded_pairs=s['excluded_pairs'], scanned_without_label=no_label,
               crosscheck_mismatch=s['crosscheck_mismatch'], labels_sha256=_sha_file(labels_path))
    _dump_json(f'{out}/a3-report-{kind}.json', rep)
    return rep


# ---------------- 3.4: compiler control ----------------
def _div_record(side, row, j, case_key):
    d = dict(key=f"{case_key}/s0/gcc/{row['i']}", idx=row['i'], layer=row.get('layer'), source=row.get('source'), input=side.input_of(row),
             channels=j['channels'], stable=j['stable'], san=j['san']['status'], san_markers=j['san'].get('markers'), retained=j['retained'],
             c_flag=j['c_flag'], needs_g_code=bool(j['retained']), timeout_rerun=(j['info'] or {}).get('timeout_rerun'),
             timeout_confirmed=(j['info'] or {}).get('timeout_confirmed'))
    if side.kind == 'exe':
        d.update(c_status=j['c']['status'], gcc_status=j['r']['status'], c_out=blob(j['c']['out']), gcc_out=blob(j['r']['out']),
                 c_err=blob(j['c']['err']), gcc_err=blob(j['r']['err']))
    else:
        d.update(c=OB.rec_obs(j['c']), gcc=OB.rec_obs(j['r']))
    return d


def cc_count(cnt, j):
    """Bộ đếm 3.4: divergence thô, trên input UB, không ổn định, giữ lại (ổn định, 'no_report')."""
    cnt[f"verdict_{j['verdict']}"] += 1
    if j['verdict'] != 'div': return
    cnt['div_raw'] += 1
    if not j['stable']: cnt['div_unstable'] += 1
    cnt[f"div_san_{j['san']['status']}"] += 1
    cnt['div_retained'] += bool(j['retained'])


def cc_case(t):
    """Một case của compiler control. Bản C gcc đóng vai phía Rust của judge_* (mục 2.5)."""
    T0 = time.time(); kind = t['kind']; ck = f"{t['bundle']}/{t['case']}"
    rec = dict(key=ck, job='cc', kind=kind, level=t['level'], bundle=t['bundle'], case=t['case'])
    if kind == 'lib' and t['case'] in NO_INPUT_LIB:
        rec.update(status='excluded', excluded_reason='no_input_fields'); return rec           # 3.4: 001_helloworld_lib, ghi lý do
    rows, reason = case_inputs(t['rdir'], t['rrec'], t['bundle'], t['case'])
    side = SIDES[kind](t)
    if not reason: reason = side.prepare(orig=False)
    if reason:
        rec.update(status='excluded', excluded_reason=reason); side.cleanup() if hasattr(side, 'dd') else None; return rec
    B = t['B']
    try:
        if kind == 'exe':
            g = CT.build_c_gcc_exe(B, t['bundle'], t['case'])
            rec['gcc_build'] = {k: g.get(k) for k in ('ok', 'sha256', 'preset', 'flags', 'log')}
            rec['build_check'] = CT.build_checks(g.get('bin'), side.c.get('bin'))
            if not g.get('ok'): rec.update(status='excluded', excluded_reason='gcc_build_failed'); return rec
            side.orig_target = g['bin']
        else:
            g = CT.build_c_gcc_lib(B, side.info)
            rec['gcc_build'] = {k: g.get(k) for k in ('ok', 'sha256', 'preset', 'flags', 'log')}
            rec['build_check'] = CT.build_checks(g.get('so'), f"{side.info['c_dir']}/lib{side.library}.so")
            if not g.get('ok'): rec.update(status='excluded', excluded_reason='gcc_build_failed'); return rec
            # judge_lib gọi phía "Rust" với --rust; .so gcc nằm ở translated_rust/target/release của root riêng (controls.gcc_lib_root).
            side.orig_target = CT.gcc_lib_root(B, side.info, g)
            rec['rust_flag_check'] = rust_flag_check(side, CT.gcc_lib_croot(B, side.info, g), rows)
        cnt = collections.Counter(); divs = []
        for row in rows:
            st, cache = side.c_obs(row)
            cnt['inputs'] += 1
            if st != 'ok': cnt[st] += 1; continue
            j = side.judge(side.orig_target, 'gcc', row, cache)
            cc_count(cnt, j)
            if j['verdict'] == 'div': divs.append(_div_record(side, row, j, ck))
    finally:
        side.cleanup()
    with open(t['div_path'], 'w') as f:
        for d in divs: f.write(json.dumps(d, ensure_ascii=False, sort_keys=True, default=str) + '\n')
    rec.update(status='done', timeout=side.timeout, n_inputs=len(rows), counts=dict(cnt), div_file=os.path.basename(t['div_path']),
               n_pending_g=sum(d['needs_g_code'] for d in divs), secs=round(time.time() - T0, 2))
    return rec


def rust_flag_check(side, gcroot, rows):
    """Kiểm trên máy đo điều đã đọc ở mã cando2 (controls docstring): trên các vector gốc (nguồn 'vector'), .so gcc gọi qua root
    `--rust` (translated_rust) và qua root C (build-ninja, không --rust) cho cùng quan sát theo phép so RQ1. Chỉ báo, không đổi quyết định."""
    n = eq = infra = 0
    for row in rows:
        if row.get('source') != 'vector': continue
        p = side.vec(row); pref = side._pref(row, 'rf')
        a = rq1._rl(side.rb, side.orig_target, p, side.timeout, True, f'{pref}.R.dump')
        b = rq1._rl(side.rb, gcroot, p, side.timeout, False, f'{pref}.C.dump')
        n += 1
        if 'infra' in (a.get('k1'), b.get('k1')): infra += 1
        else: eq += rq1._eq_lib(a, b)
    return dict(n=n, equal=eq, infra=infra, ok=n > 0 and eq + infra == n and infra == 0)


def cmd_cc(a):
    kinds = [a.kind] if a.kind else ['exe', 'lib']
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness'))
    res = {}
    for kind in kinds:
        recs_r, man = load_phase_r(a.phase_r, kind)
        err = check_phase_r(man, kind, a.level, a.timeout, a.allow_other_commit)
        if err: raise SystemExit('pha R không dùng được: ' + '; '.join(err))
        out = f'{a.out}/cc-{kind}'; os.makedirs(f'{out}/div', exist_ok=True)
        cases = sorted(PILOT_EXE if kind == 'exe' else PILOT_LIB)
        manifest(out, dict(cmd='sweep-cc', kind=kind, level=a.level, phase_r=os.path.abspath(a.phase_r), phase_r_commit=man.get('repo_commit'),
                           timeout=a.timeout, workers=a.workers, criteria_commit=criteria_commit(), cases=[f'{b}/{c}' for b, c in cases],
                           gcc_flags=CT.gcc_flags(), oracle='rq1.judge_exe / rq1.judge_lib (gcc ở phía Rust)', build_dir=B))
        store = Store(f'{out}/cc-{kind}.jsonl')
        if kind == 'lib': BD.setup_cando2(B)
        tasks = [dict(kind=kind, level=a.level, bundle=b, case=c, system=None, hcase=None, rdir=a.phase_r, rrec=recs_r.get((b, c)), B=B,
                      timeout=a.timeout, run_tag=f'cc-{a.level}', div_path=f'{out}/div/{b}__{c}.jsonl')
                 for b, c in cases if not store.has(f'{b}/{c}')]

        def sink(t, r):
            if r.get('status') == 'harness_error': r.update(key=f"{t['bundle']}/{t['case']}#error", kind=t['kind'])
            store.put(r); print(r['key'], r.get('status'), r.get('excluded_reason', ''), r.get('counts'), flush=True)
        run_tasks(cc_case, tasks, a.workers, sink)
        res[kind] = report_cc(a.out, kind)
    return res


def load_codes(path):
    """JSONL: key (của bản ghi divergence cc), code G1 đến G4, c_line, clause, repro; tuỳ chọn le_approved."""
    return {r['key']: r for r in _load_jsonl(path)} if path else {}


def report_cc(out, kind, codes_path=None):
    """Đạt (3.4) khi mọi case so được qua kiểm build và mọi divergence giữ lại có mã G1 đến G4 kèm đủ G_FIELDS. Không có ngưỡng
    divergence thô; báo thêm số thô và số trên input UB. Le duyệt từng ca (trường le_approved chỉ báo lại)."""
    d = f'{out}/cc-{kind}'
    recs = [r for k, r in load_store(f'{d}/cc-{kind}.jsonl').items() if not k.endswith('#error')]
    codes = load_codes(codes_path); tot = collections.Counter(); pending, coded, bad_build = [], [], []
    for r in recs:
        if r.get('status') != 'done': continue
        tot.update(r.get('counts', {}))
        if not (r.get('build_check') or {}).get('ok'): bad_build.append(r['key'])
        for x in _load_jsonl(f"{d}/div/{r['div_file']}"):
            if not x['needs_g_code']: continue
            c = codes.get(x['key'])
            ok = bool(c) and c.get('code') in G_CODES and all(c.get(f) for f in G_FIELDS)
            (coded if ok else pending).append(dict(key=x['key'], code=(c or {}).get('code'), le_approved=(c or {}).get('le_approved')))
    excl = [dict(key=r['key'], reason=r.get('excluded_reason') or r.get('status')) for r in recs if r.get('status') != 'done']
    # loại hợp lệ duy nhất là library không có trường input (3.4); case loại vì lý do khác (pha R thiếu, build gcc lỗi) làm chưa đạt
    bad_excl = [x for x in excl if x['reason'] != 'no_input_fields']
    status = 'đạt' if not pending and not bad_build and not bad_excl and recs else 'chưa đạt'
    rep = dict(kind=kind, status=status, cases=len(recs), excluded=excl, excluded_not_allowed=bad_excl, build_check_failed=bad_build, totals=dict(tot),
               div_raw=tot.get('div_raw', 0), div_on_ub_inputs=tot.get('div_san_ub', 0), retained=tot.get('div_retained', 0),
               pending_g_code=pending, coded=coded, codes_file=codes_path)
    _dump_json(f'{d}/cc-report-{kind}.json', rep)
    print(json.dumps({k: rep[k] for k in ('kind', 'status', 'cases', 'div_raw', 'div_on_ub_inputs', 'retained')}, ensure_ascii=False)
          + f' chờ mã G: {len(pending)}', flush=True)
    return rep


# ---------------- CLI ----------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness.sweep')
    ap.add_argument('cmd', choices=['a7', 'select', 'a3', 'report-a3', 'cc', 'report-cc'])
    ap.add_argument('--kind', choices=['exe', 'lib']); ap.add_argument('--out', required=True)
    ap.add_argument('--mutants', help='thư mục đầu ra của harness.mutants gen'); ap.add_argument('--set', default=None)
    ap.add_argument('--levels', default='x1,x3,x10'); ap.add_argument('--level'); ap.add_argument('--phase-r')
    ap.add_argument('--workers', type=int, default=1); ap.add_argument('--timeout', type=int, default=10)
    ap.add_argument('--skip-phase-r', action='store_true', help='a7: dùng pha R đã có trong OUT/<mức>')
    ap.add_argument('--labels'); ap.add_argument('--labels-sha256'); ap.add_argument('--labels-commit'); ap.add_argument('--codes')
    ap.add_argument('--no-estimate', action='store_true', help='select: không chạy estimate.py')
    ap.add_argument('--allow-other-commit', action='store_true', help='chỉ chạy thử: cho phép pha R ở commit khác (trái Q11 (a))')
    a = ap.parse_args(argv)
    need = dict(a7=('kind', 'mutants'), a3=('kind', 'level', 'set', 'labels', 'labels_sha256', 'mutants'), cc=('level', 'phase_r'),
                **{'report-a3': ('kind', 'labels')})
    miss = [f for f in need.get(a.cmd, ()) if not getattr(a, f)]
    if miss: raise SystemExit(f'{a.cmd} cần: ' + ', '.join('--' + m.replace('_', '-') for m in miss))
    if a.cmd == 'a7':
        a.set = a.set or 'a7-seed1'; return cmd_a7(a)
    if a.cmd == 'select': return cmd_select(a)
    if a.cmd == 'a3': return cmd_a3(a)
    if a.cmd == 'report-a3': return report_a3(f'{a.out}/a3-{a.kind}', a.kind, a.labels)
    if a.cmd == 'cc': return cmd_cc(a)
    return {k: report_cc(a.out, k, a.codes) for k in ([a.kind] if a.kind else ['exe', 'lib']) if os.path.isdir(f'{a.out}/cc-{k}')}


if __name__ == '__main__':
    main()
