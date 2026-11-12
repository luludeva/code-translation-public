"""Luật quyết định của RQ2 ở cấp vector và cấp bản dịch (§3.6, Bảng 3.3; decision-log 2026-10-22 mục §3.6, 2026-10-23).

Phần quyết định (observe_vector, vector_outcome, translation_outcome) tách khỏi phần chạy (r_run, examine_vector, rq2_pair, main ở
cuối file) để kiểm được bằng test không cần corpus. Phần chạy viết 2026-10-23 (phiên kỹ thuật, Việc 6); không dùng observe.equal_lib cho
quyết định "khớp" khi hai bên cùng vượt ngân sách (rà độc lập 2026-10-23), vì vector_outcome xét trường hợp đó trước.

Một vector trượt được chạy REPS lần trên cả hai phía. Ở mỗi lần, nếu đúng một bên vượt ngân sách thì chạy lại lần đó trên cả hai phía
với timeout gấp TIMEOUT_RERUN_FACTOR và dùng quan sát mới (như RQ1, §3.3 p5).
  - supports_rejection: C cho cùng quan sát ở mọi lần, Rust khác C ở mọi lần, sanitizer phía C không báo UB.
  - agrees: hai bên bằng nhau ở mọi lần, sanitizer phía C chạy xong không báo.
  - not_adjudicable: còn lại; lý do ghi: ub_in_c, sanitizer_inconclusive, both_budget, c_unstable (C đổi quan sát giữa các lần trong
    khi Rust khác C ở mọi lần; D2, Le chọn 25/10), unstable_comparison (phép so đổi kết quả giữa các lần).
  - incomplete: vector không có kết quả; bản dịch rơi vào "not re-examined" nếu không có vector nào ủng hộ việc từ chối. Mã lý do tách
    (F5, 2026-10-25; trước đây runner lỗi và sanitizer lỗi gộp thành 'infra'): invalid_input (runner từ chối đọc vector đã xoá output
    kỳ vọng, Le chọn 23/10: không được tính là khớp; executable: argv có byte NUL, không thực thi được), vector_unreadable (file vector
    rỗng), run_unobserved (runner không ghi report sau khi thử lại, ở lần chạy dùng để quyết định), san_build_failed (bản C-san không
    build được), san_infra (C-san lỗi hạ tầng sau SAN_ATTEMPTS lần thử).
Hai bên cùng vượt ngân sách ở một lần bất kỳ: not_adjudicable (both_budget), vì khớp trên quan sát một phần không đủ để nói khớp.
Library, runner không trả report (k1 'infra' sau thử lại, kể cả quá hạn chót, rc None) ở một bên: lần chạy không quan sát được, không
kích hoạt chạy lại gấp mười, vector run_unobserved (D1, Le chọn 25/10; như RQ1 và decision-log 2026-10-23 ghi 2026-10-25).
Mỗi vector mang đúng một mã khi kết quả khác supports_rejection, agrees (VECTOR_REASONS); thứ tự xét trong vector_outcome quyết định mã
khi nhiều điều kiện cùng đúng. Thứ tự đó ghi trong VECTOR_REASON_ORDER, cũng là thứ tự ưu tiên chọn một mã cấp bản dịch (D3)."""
from . import observe as OB
from .config import TIMEOUT_RERUN_FACTOR

REPS = 3


def _budget(o, kind):
    return OB.is_nt(o) if kind == 'exe' else OB.lib_timeout(o)


# Thứ tự xét mã cấp vector (D3, Le chọn 25/10): vector_unreadable xét trong rq2_pair trước khi chạy; các mã còn lại theo thứ tự xét của
# vector_outcome. Mã của hai kết quả not_adjudicable, incomplete loại trừ nhau trong một vector; thứ tự này chỉ có tác dụng khi chọn một
# mã cho bản dịch có nhiều vector mang mã khác nhau (primary_reason).
VECTOR_REASON_ORDER = ('vector_unreadable', 'invalid_input', 'run_unobserved', 'san_build_failed', 'san_infra',
                       'ub_in_c', 'both_budget', 'sanitizer_inconclusive', 'c_unstable', 'unstable_comparison')
VECTOR_REASONS = dict(supports_rejection=(None,), agrees=(None,),
                      not_adjudicable=('ub_in_c', 'both_budget', 'sanitizer_inconclusive', 'c_unstable', 'unstable_comparison'),
                      incomplete=('vector_unreadable', 'invalid_input', 'run_unobserved', 'san_build_failed', 'san_infra'))
assert VECTOR_REASON_ORDER == VECTOR_REASONS['incomplete'] + VECTOR_REASONS['not_adjudicable']
# Mã cấp bản dịch. not_adjudicable: tập mã not_adjudicable của các vector. not_re_examined: mã trước khi chạy (rq2_pair) hoặc
# 'incomplete_harness_run:<mã vector incomplete>' (F5: tách theo mã vector thay vì gộp). Trường `reason` một mã: mã đầu tiên của
# `reasons` theo TRANSLATION_REASON_ORDER (D3, Le chọn 25/10; bỏ 'multiple'); `reasons` giữ đủ mã.
PRE_RUN_REASONS = ('no_failing_vector', 'report_missing', 'timeout_only_rule_pending', 'build_failed_in_harness')
TRANSLATION_REASONS = dict(behavioral_disagreement=(None,), behavioral_agreement=(None,),
                           not_adjudicable=VECTOR_REASONS['not_adjudicable'],
                           not_re_examined=PRE_RUN_REASONS + tuple(f'incomplete_harness_run:{r}' for r in VECTOR_REASONS['incomplete']))
TRANSLATION_REASON_ORDER = PRE_RUN_REASONS + tuple(f'incomplete_harness_run:{r}' for r in VECTOR_REASON_ORDER
                                                   if r in VECTOR_REASONS['incomplete']) + VECTOR_REASONS['not_adjudicable']


def _infra(o, kind):
    """Library: runner không ghi report sau thử lại (k1 'infra'), kể cả quá hạn chót của _run_lib (rc None). Lần chạy không quan sát được;
    observe.lib_timeout tính rc None là vượt ngân sách, nên phải xét hàm này trước _budget (D1)."""
    return kind == 'lib' and o.get('k1') == 'infra'


def _invalid(o, kind):
    """Runner từ chối đọc vector (library) hoặc argv có byte NUL, không thực thi được (executable, observe.run_exe)."""
    return (o.get('k1') if kind == 'lib' else o.get('status')) == 'invalid_input'


def _equal(a, b, kind):
    return OB.equal_exe(a, b) if kind == 'exe' else OB.equal_lib(a, b)


def observe_vector(run_c, run_r, timeout, kind, reps=REPS, log=None):
    """run_c(timeout), run_r(timeout): một lần chạy mỗi phía. Trả về danh sách (c, r, reran) dài reps.
    log (F5): danh sách; nếu có, nhận mỗi lần một dict gồm quan sát lần đầu và quan sát chạy lại (nếu có), kèm timeout của từng lượt,
    để bản ghi giữ cả quan sát bị thay khi chạy lại."""
    out = []
    for i in range(reps):
        c, r = run_c(timeout), run_r(timeout)
        # D1 (Le chọn 25/10): lần chạy có một bên không quan sát được (k1 'infra') không kích hoạt chạy lại gấp mười; vector_outcome
        # xếp vector run_unobserved. Trước đó lib_timeout (rc None) làm lần này thành "đúng một bên vượt ngân sách".
        unobserved = _infra(c, kind) or _infra(r, kind)
        reran = not unobserved and _budget(c, kind) != _budget(r, kind)
        ent = dict(rep=i, reran=reran, first=dict(timeout=timeout, c=c, r=r), rerun=None)
        if unobserved: ent['unobserved'] = True
        if reran:
            c, r = run_c(timeout * TIMEOUT_RERUN_FACTOR), run_r(timeout * TIMEOUT_RERUN_FACTOR)
            ent['rerun'] = dict(timeout=timeout * TIMEOUT_RERUN_FACTOR, c=c, r=r)
        if log is not None: log.append(ent)
        out.append((c, r, reran))
    return out


def vector_outcome(runs, san, kind, san_cause=None):
    """runs: kết quả observe_vector. san: trạng thái sanitizer phía C ('ub', 'no_report', 'inconclusive', 'infra'). san_cause:
    trường 'cause' của kết quả sanitizer ('c_san_build_failed' khi bản C-san không build được). Trả về (outcome, reason)."""
    if any(_invalid(c, kind) or _invalid(r, kind) for c, r, _ in runs):
        return 'incomplete', 'invalid_input'          # sửa 2026-10-23 (Việc 6): hai bên cùng invalid_input từng bị so là khớp
    if any(_infra(c, kind) or _infra(r, kind) for c, r, _ in runs):
        return 'incomplete', 'run_unobserved'
    if san == 'infra':
        return 'incomplete', 'san_build_failed' if san_cause == 'c_san_build_failed' else 'san_infra'
    if san == 'ub':
        return 'not_adjudicable', 'ub_in_c'
    if any(_budget(c, kind) and _budget(r, kind) for c, r, _ in runs):
        return 'not_adjudicable', 'both_budget'
    c0 = runs[0][0]
    c_stable = all(_equal(c0, c, kind) for c, _, _ in runs[1:])
    all_differ = all(not _equal(c, r, kind) for c, r, _ in runs)
    if c_stable and all_differ:
        if san == 'inconclusive':
            return 'not_adjudicable', 'sanitizer_inconclusive'
        return 'supports_rejection', None
    if all(_equal(c, r, kind) for c, r, _ in runs):
        if san != 'no_report':
            return 'not_adjudicable', 'sanitizer_inconclusive'
        return 'agrees', None
    if all_differ:                                      # D2 (Le chọn 25/10): phép so không đổi, C đổi quan sát giữa các lần
        return 'not_adjudicable', 'c_unstable'
    return 'not_adjudicable', 'unstable_comparison'     # phép so đổi kết quả giữa các lần


def translation_outcome(vector_outcomes):
    """vector_outcomes: danh sách (outcome, reason) của mọi vector trượt của một bản dịch trong R_test.
    Trả về (outcome, reasons): behavioral_disagreement, behavioral_agreement, not_adjudicable, not_re_examined."""
    outs = [o for o, _ in vector_outcomes]
    if not outs:
        return 'not_re_examined', ['no_failing_vector']
    if 'supports_rejection' in outs:
        return 'behavioral_disagreement', []
    if 'incomplete' in outs:
        return 'not_re_examined', sorted({f'incomplete_harness_run:{r}' for o, r in vector_outcomes if o == 'incomplete'})
    if all(o == 'agrees' for o in outs):
        return 'behavioral_agreement', []
    return 'not_adjudicable', sorted({r for o, r in vector_outcomes if o == 'not_adjudicable'})


def primary_reason(outcome, reasons):
    """Một mã cho mỗi kết quả cấp bản dịch: None với hai kết quả phân xử được; còn lại mã đầu tiên của `reasons` theo
    TRANSLATION_REASON_ORDER (D3, Le chọn 25/10; thay 'multiple' của F5). Mã ngoài thứ tự (bản ghi cũ, ví dụ 'incomplete_harness_run'
    trước F5) xếp sau mọi mã đã biết, theo thứ tự chữ."""
    if outcome in ('behavioral_disagreement', 'behavioral_agreement'): return None
    rs = set(reasons or [])
    if not rs: return None
    rank = {r: i for i, r in enumerate(TRANSLATION_REASON_ORDER)}
    return min(rs, key=lambda r: (rank.get(r, len(rank)), r))


# ======================================================================================================================================
# Phần chạy (2026-10-23, Việc 6). Algorithm 2 của harness-design.md mục 5, theo luật §3.6 và decision-log 2026-10-22, 2026-10-23.
#
# R_run (§3.2): bản bị từ chối ở bước test (result.json công bố: passed false, error "test failed"), build được khi tái lập, và oracle
# gốc tái lập được việc trượt (ours_passed false trong census). V_f: các vector có kết quả khác Pass, Skip trong báo cáo runner của lượt
# tái lập (nguồn đã chốt ở Q7, decision-log 2026-10-14; không dùng vectors_failed công bố vì có giá trị giữ chỗ).
# Nguồn census: executable census-exe-ec2 (cùng báo cáo); library census-lib-c7i (lượt chạy lại trên c7i, có báo cáo từng vector).
# Bản chỉ trượt vì Timeout cần luật kiểm lại 3/3 như phía chấp nhận: trên census hiện tại không có bản nào như vậy (0 executable,
# 0 library), nên r_run đánh dấu `timeout_only` thay vì tự áp luật; gặp thì dừng và hỏi.
import collections, json, os, tarfile, time, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

from .config import REPO, T, PILOT_EXE, PILOT_LIB

CENSUS = dict(exe=(f'{REPO}/experiments/02-harvest-repro/results/census-exe-ec2.jsonl',
                   f'{REPO}/experiments/02-harvest-repro/results/census-exe-ec2-reports.tar.gz'),
              lib=(f'{REPO}/experiments/06-library-census/results/census-lib-c7i.jsonl',
                   f'{REPO}/experiments/06-library-census/results/census-lib-c7i-reports.tar.gz'))
PASSING = ('Pass', 'Skip')


def _report_members(tgz):
    """{(system, bundle, case): báo cáo runner {vector: {result, ...}}} từ tarball báo cáo census."""
    out = {}
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            if not m.isfile() or not m.name.endswith('.json'): continue
            p = m.name.split('/'); case = os.path.basename(m.name).split('.')[0]
            out[(p[-3], p[-2], case)] = json.load(t.extractfile(m))
    return out


def _pub_error(row):
    """Giai đoạn bị từ chối theo result.json công bố (decision-log 2026-10-20, Phễu §3.2). Census library đã có pub_error."""
    if 'pub_error' in row: return row['pub_error']
    from .build import rust_src
    d = rust_src(row['system'], row['bundle'], row['harvest_case'])
    for rj in (f'{d}/result.json', f'{os.path.dirname(d)}/result.json'):
        if os.path.exists(rj): return json.load(open(rj)).get('error')
    return None


def _orig(o):
    """Kết quả oracle gốc của một vector trượt: result, diff cắt 300 ký tự; với diff 'Library State Mismatch' giữ thêm cả chuỗi
    (`state_diff`) để metrics.ff_channels tách kênh số thực (D6; census library: 74/135 diff state dài hơn 300 ký tự, dài nhất khoảng
    3,1 nghìn ký tự, sơ bộ, đếm bằng script)."""
    d = str(o.get('diff', ''))
    out = dict(result=o.get('result'), diff=d[:300])
    if 'State Mismatch' in d: out['state_diff'] = d
    return out


def r_run(kind, pilot=False, census=None, reports=None):
    """Danh sách bản thuộc R_run kèm V_f. pilot=True: chỉ case pilot (chạy thử, R6); False: chỉ case ngoài pilot."""
    cp, tp = CENSUS[kind]
    rows = [json.loads(l) for l in open(census or cp)]
    reps = _report_members(reports or tp)
    out = []
    for r in rows:
        if bool(r['pilot']) != pilot or r.get('pub_passed') is not False or not r.get('build_ok') or r.get('ours_passed') is not False:
            continue
        if _pub_error(r) != 'test failed': continue
        rep = reps.get((r['system'], r['bundle'], r['tractor_case'])) or {}
        vf = sorted(os.path.basename(v) for v, o in rep.items() if (o or {}).get('result') not in PASSING)
        res = set(r.get('results') or {}) - set(PASSING)
        out.append(dict(r, v_f=vf, orig={os.path.basename(v): _orig(o) for v, o in rep.items() if os.path.basename(v) in vf},
                        timeout_only=res == {'Timeout'}, report_found=bool(rep)))
    return out


def strip_expected(vec):
    """Vector library đã xoá output kỳ vọng (decision-log 2026-10-23): state, stdout, stderr kỳ vọng. Giữ input, stdin, env."""
    v = {k: x for k, x in vec.items() if k not in ('lib_state_out', 'stdout', 'stderr')}
    v['lib_state_out'] = {}
    return v


def _unblob(b):
    """Ngược của record.blob (như metrics.unblob; chép lại để rq2 không nạp bnu_v0 qua metrics)."""
    import base64, gzip
    return gzip.decompress(base64.b64decode(b['gz64'])) if b else b''


# D5 (Le chọn 25/10): state_debug (chuỗi Debug của Rust trong dump state v2) dài hơn ngưỡng này thì lưu nén qua record.blob; ngắn hơn
# thì giữ chuỗi. Dùng cho robustness analysis theo luật oracle gốc (phân biệt optional với trường đơn lẻ); không vào phép so.
STATE_DEBUG_INLINE = 4096


def enc_obs(o, kind):
    """Quan sát thô -> dict lưu được (F5, 2026-10-25): giữ mọi trường; output (executable: out, err; library: stdout, stderr) qua
    record.blob như RQ1. Library giữ result, k1, rc, state_out, state_nonfinite, state_debug (D5; nén khi dài hơn STATE_DEBUG_INLINE),
    thông báo hạ tầng và dấu hiệu bộ nhớ như runner trả về."""
    from .record import blob
    if o is None: return None
    streams = ('out', 'err') if kind == 'exe' else ('stdout', 'stderr')
    d = {k: v for k, v in o.items() if k not in streams}
    for k in streams:
        if k in o: d[k] = blob(o[k])
    sd = d.get('state_debug')
    if isinstance(sd, str) and len(sd) > STATE_DEBUG_INLINE: d['state_debug'] = blob(sd)
    return d


def dec_obs(d, kind):
    """Ngược của enc_obs: bản ghi -> quan sát dùng được cho observe.equal_* (để tính lại kết quả không cần chạy thêm)."""
    if d is None: return None
    o = dict(d)
    if kind == 'exe':
        for k in ('out', 'err'):
            if k in d: o[k] = _unblob(d[k])
    else:
        for k in ('stdout', 'stderr'):
            if k in d: o[k] = None if d[k] is None else _unblob(d[k]).decode('utf-8')
        if isinstance(d.get('state_debug'), dict): o['state_debug'] = _unblob(d['state_debug']).decode('utf-8')   # D5
    return o


def _enc_san_attempt(a, kind):
    from .record import blob
    out = {k: v for k, v in a.items() if k not in ('obs', 'streams')}
    out['obs'] = enc_obs(a.get('obs'), kind)
    if 'streams' in a: out['streams'] = [blob(x) for x in a['streams']]
    return out


def examine_vector(run_c, run_r, san_fn, kind, timeout, san_sink=None):
    """Một vector trượt: REPS lần quan sát hai phía (chạy lại gấp TIMEOUT_RERUN_FACTOR khi đúng một bên vượt ngân sách), sanitizer phía
    C chạy trên mọi vector trượt, kể cả khi hai bên khớp (decision-log 2026-10-23). san_fn(c_obs) trả dict có 'status'.
    san_sink: danh sách mà san_fn ghi quan sát thô của từng lần thử sanitizer vào (rq1._exe_san, rq1.lib_san tham số sink).
    Bản ghi `obs` (F5, 2026-10-25; decision-log 2026-10-23 ghi 2026-10-25: lưu quan sát đầy đủ của từng lần chạy để robustness analyses
    tính lại không cần chạy thêm): mọi lần chạy C và Rust ở cả REPS lần, quan sát lần đầu và quan sát chạy lại gấp mười (nếu có), kết quả
    và quan sát từng lần thử sanitizer."""
    log = []
    runs = observe_vector(run_c, run_r, timeout, kind, log=log)
    san = san_fn(runs[0][0])
    outcome, reason = vector_outcome(runs, san['status'], kind, san.get('cause'))
    ch = (lambda a, b: OB.channels_exe(a, b) if not (OB.is_nt(a) and OB.is_nt(b)) else ['both_budget']) if kind == 'exe' \
        else (lambda a, b: ['run_unobserved'] if _infra(a, kind) or _infra(b, kind)       # D1: không quan sát được, không so kênh
              else OB.channels_lib(a, b) if not (OB.lib_timeout(a) and OB.lib_timeout(b)) else ['both_budget'])
    summ = []
    for c, r, reran in runs:
        s = dict(reran=reran, channels=ch(c, r))
        if kind == 'exe': s.update(c_status=c['status'], r_status=r['status'], c_rc=c.get('rc'), r_rc=r.get('rc'))
        else: s.update(c_result=(c.get('k1'), c.get('result')), r_result=(r.get('k1'), r.get('result')))
        summ.append(s)
    c0 = runs[0][0]
    c_stable = all(_equal(c0, c, kind) for c, _, _ in runs[1:])
    all_differ = all(not _equal(c, r, kind) for c, r, _ in runs)
    obs = dict(runs=[dict(rep=e['rep'], reran=e['reran'], **({'unobserved': True} if e.get('unobserved') else {}),
                          first=dict(timeout=e['first']['timeout'], c=enc_obs(e['first']['c'], kind), r=enc_obs(e['first']['r'], kind)),
                          rerun=None if e['rerun'] is None else dict(timeout=e['rerun']['timeout'], c=enc_obs(e['rerun']['c'], kind),
                                                                     r=enc_obs(e['rerun']['r'], kind)))
                     for e in log],
               san=dict(result=dict(san), attempts=[_enc_san_attempt(x, kind) for x in (san_sink or [])]))
    d = dict(outcome=outcome, reason=reason, san=san['status'], san_markers=san.get('markers'), san_attempts=san.get('attempts'),
             san_cause=san.get('cause'), c_stable=c_stable, runs=summ, obs=obs)
    # Chi tiết, không phải mã: hướng của vector bị chặn bởi kiểm inconclusive (nếu sanitizer chạy xong không báo thì vector sẽ là gì).
    if reason == 'sanitizer_inconclusive': d['would_be'] = 'supports_rejection' if c_stable and all_differ else 'agrees'
    return d, runs


def recompute_vector(v, kind):
    """Tính lại (outcome, reason) của một bản ghi vector chỉ từ trường `obs`, không chạy lại (F5). Lần chạy dùng để quyết định là lần
    chạy lại khi reran, như observe_vector. Vector không có `obs` (vector_unreadable) trả lại kết quả đã ghi."""
    if not v.get('obs'): return v['outcome'], v['reason']
    runs = []
    for e in v['obs']['runs']:
        ph = e['rerun'] if e['reran'] else e['first']
        runs.append((dec_obs(ph['c'], kind), dec_obs(ph['r'], kind), e['reran']))
    return vector_outcome(runs, v['san'], kind, v.get('san_cause'))


def unreadable_vector(name, row):
    """Bản ghi vector khi file vector rỗng (read_vector trả None): trước F5 rq2_pair chạy với argv, state rỗng; nay không có kết quả."""
    return dict(vector=name, has_ub=False, orig=row['orig'].get(name), outcome='incomplete', reason='vector_unreadable', san=None,
                runs=[], obs=None)


def _blobs_exe(runs):
    from .record import blob
    c, r, _ = runs[0]
    return dict(c_out=blob(c['out']), r_out=blob(r['out']), c_err=blob(c['err']), r_err=blob(r['err']))


def _done(rec, outcome, reasons, **kw):
    """Bản ghi cấp bản dịch: `reasons` (mọi mã, như trước F5) và `reason` (một mã, primary_reason)."""
    return dict(rec, outcome=outcome, reasons=reasons, reason=primary_reason(outcome, reasons), **kw)


def rq2_pair(B, kind, row, timeout):
    """Chạy V_f của một bản thuộc R_run. Trả về bản ghi cấp bản dịch (kèm bản ghi từng vector)."""
    from . import build as BD
    from . import rq1
    from .record import blob
    from .vectors import read_vector, to_bytes, u2b
    T0 = time.time()
    bundle, case, system = row['bundle'], row['tractor_case'], row['system']
    # Executable: timeout theo case như RQ1 (decision-log 2026-10-25 "Timeout theo case cho các kiểm và RQ2"; cài 2026-10-26).
    base = timeout
    if kind == 'exe': timeout = rq1.case_timeout(bundle, case, timeout)
    rec = dict(key=f'{system}/{bundle}/{case}', kind=kind, bundle=bundle, case=case, system=system, n_v_f=len(row['v_f']),
               timeout=timeout, timeout_base=base, timeout_only=row['timeout_only'])
    if row['timeout_only']:
        return _done(rec, 'not_re_examined', ['timeout_only_rule_pending'], vectors=[])
    if not row['v_f']:
        return _done(rec, 'not_re_examined', ['no_failing_vector' if row['report_found'] else 'report_missing'], vectors=[])
    troot = f'{T}/{bundle}/{case}'
    vecs = []
    if kind == 'exe':
        c = BD.build_c_exe(B, bundle, case); cs = BD.build_c_exe(B, bundle, case, san=True)
        rs = BD.build_rust_exe(B, system, bundle, case, row['harvest_case'])
        rec.update(c_ok=c.get('ok'), c_san_ok=cs.get('ok'), rust_ok=rs.get('ok'))
        if not (c.get('ok') and rs.get('ok')):
            return _done(rec, 'not_re_examined', ['build_failed_in_harness'], vectors=[])
        for name in row['v_f']:
            v = read_vector(f'{troot}/test_vectors/{name}')
            if not v: vecs.append(unreadable_vector(name, row)); continue
            argv = [u2b(a) for a in (v.get('argv') or [])]; stdin = u2b(v.get('stdin') or ''); env = v.get('env')
            run_c = lambda t: OB.run_exe(c['bin'], argv, stdin, t, env)
            run_r = lambda t: OB.run_exe(rs['bin'], argv, stdin, t, env)
            sink = []
            san_fn = lambda co: rq1._exe_san(cs, argv, stdin, timeout, env, co['status'], sink=sink)
            d, runs = examine_vector(run_c, run_r, san_fn, kind, timeout, san_sink=sink)
            vecs.append(dict(vector=name, has_ub='has_ub' in v, orig=row['orig'].get(name), **d, **_blobs_exe(runs),
                             input=dict(argv=[blob(to_bytes(a)) for a in argv], stdin=blob(to_bytes(stdin)), env=env),   # như RQ1
                             san_timeout=timeout * rq1.SAN_TIMEOUT_FACTOR))
    else:
        info = BD.build_lib_case(B, bundle, case)
        rl = BD.build_rust_lib(B, system, bundle, case, row['harvest_case'], info['library']) if info['runner_ok'] else {}
        rec.update(c_ok=info.get('c_ok'), c_san_ok=info.get('c-san_ok'), runner_ok=info.get('runner_ok'), rust_ok=rl.get('ok'))
        if not (info['runner_ok'] and info['c_ok'] and rl.get('ok')):
            return _done(rec, 'not_re_examined', ['build_failed_in_harness'], vectors=[])
        croot = BD.lib_root(B, info, 'c'); rroot = BD.lib_root(B, info, 'rust', rl['dir'], tag=f'rust-{system}')
        csroot = BD.lib_root(B, info, 'c-san') if info.get('c-san_ok') else None
        preload = BD.asan_preload(); rb = info['runner_bin']
        vd = f'{B}/rq2-vec/{system}/{bundle}/{case}'; os.makedirs(vd, exist_ok=True)
        cnt = collections.Counter()
        for name in row['v_f']:
            v = read_vector(f'{troot}/test_vectors/{name}')
            if not v: vecs.append(unreadable_vector(name, row)); continue
            sv = strip_expected(v)
            p = f'{vd}/{name}'; json.dump(sv, open(p, 'w'))
            def mk(root, rust, side):
                def f(t):
                    cnt[side] += 1
                    return rq1._rl(rb, root, p, t, rust, f'{vd}/{name}.{side}{cnt[side]}.dump')
                return f
            sink = []
            san_fn = lambda co: rq1.lib_san(rb, csroot, p, timeout * rq1.SAN_TIMEOUT_FACTOR, f'{vd}/{name}.san.dump', preload, co,
                                            sink=sink)
            d, runs = examine_vector(mk(croot, False, 'C'), mk(rroot, True, 'R'), san_fn, kind, timeout, san_sink=sink)
            c0, r0, _ = runs[0]
            vecs.append(dict(vector=name, has_ub='has_ub' in v, orig=row['orig'].get(name), **d,
                             c_first={k: c0.get(k) for k in ('k1', 'result', 'state_out', 'stdout', 'stderr', 'state_nonfinite')},
                             r_first={k: r0.get(k) for k in ('k1', 'result', 'state_out', 'stdout', 'stderr', 'state_nonfinite')},
                             input=sv, san_timeout=timeout * rq1.SAN_TIMEOUT_FACTOR))
    outcome, reasons = translation_outcome([(x['outcome'], x['reason']) for x in vecs])
    return _done(rec, outcome, reasons, vectors=vecs, secs=round(time.time() - T0, 2),
                 vector_outcomes=dict(collections.Counter(x['outcome'] for x in vecs)))


def rq2_case(B, kind, rows, timeout):
    """Mọi bản của một case trong cùng một worker: bản C, C-san và runner của case build một lần, không có hai worker build cùng thư
    mục (chạy thử pilot 23/10: song song theo bản dịch làm hai worker cùng build bản C của một case)."""
    out = []
    for row in rows:
        try: out.append(rq2_pair(B, kind, row, timeout))
        except Exception: out.append(dict(key=f'{row["system"]}/{row["bundle"]}/{row["tractor_case"]}#error', status='harness_error',
                                          reason='harness_error', error=traceback.format_exc()[-3000:]))
    return out


def main(argv=None):
    import argparse
    from . import build as BD
    from .record import Store, manifest
    ap = argparse.ArgumentParser(prog='harness.rq2')
    ap.add_argument('--kind', choices=['exe', 'lib'], required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--pilot', action='store_true', help='chạy thử trên case pilot (R6, không vào số chính)')
    ap.add_argument('--workers', type=int, default=1); ap.add_argument('--timeout', type=int, default=10)
    a = ap.parse_args(argv)
    if not a.pilot:
        raise SystemExit('Lượt chính chưa mở: chờ Protocol Freeze. Dùng --pilot.')
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness'))
    rows = r_run(a.kind, pilot=True)
    pil = PILOT_EXE if a.kind == 'exe' else PILOT_LIB
    assert all((r['bundle'], r['tractor_case']) in pil for r in rows), 'bản ngoài pilot'
    os.makedirs(a.out, exist_ok=True)
    manifest(a.out, dict(cmd='rq2', kind=a.kind, pilot=a.pilot, workers=a.workers, timeout=a.timeout, reps=REPS,
                         rerun_factor=TIMEOUT_RERUN_FACTOR, census=CENSUS[a.kind], n_r_run=len(rows),
                         n_timeout_only=sum(r['timeout_only'] for r in rows)))
    store = Store(f'{a.out}/rq2-{a.kind}.jsonl')
    if a.kind == 'lib': BD.setup_cando2(B)
    todo = [r for r in rows if not store.has(f'{r["system"]}/{r["bundle"]}/{r["tractor_case"]}')]
    by_case = collections.defaultdict(list)
    for r in todo: by_case[(r['bundle'], r['tractor_case'])].append(r)
    print(f'rq2 {a.kind}: {len(todo)} bản cần chạy, {len(by_case)} case, {a.workers} worker', flush=True)
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(rq2_case, B, a.kind, rs, a.timeout) for _, rs in sorted(by_case.items())]
        for f in as_completed(futs):
            for r in f.result():
                store.put(r); print(r.get('key'), r.get('outcome') or r.get('status'), r.get('reasons'), flush=True)


if __name__ == '__main__':
    main()
