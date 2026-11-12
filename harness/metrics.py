"""Bước tính số liệu (rà soát kỹ thuật 2026-10-23, C2): gộp bản ghi RQ1, RQ2 thành số đếm cấp bản dịch theo reporting-rules.

Không chạy chương trình nào; chỉ đọc đầu ra của harness.rq1 và harness.rq2. Mọi số trả về là số đếm kèm mẫu số (R1); tỉ lệ để bước
sinh macro tính. Nguồn luật:
  - P_test qua seed (harness-design Q6): bản dịch thuộc P_test khi pair_status là P_test ở mọi seed yêu cầu; thiếu seed là `missing_seed`.
    Lý do rời P_test ưu tiên: rust_build_failed, incomplete, san_infra, missing_seed.
  - S và R19: bản dịch có divergence khi ít nhất một seed có divergence giữ lại (`retained`: ổn định và sanitizer phía C chạy xong không
    báo); báo phân bố số seed phát hiện. Bản ghi trước 2026-10-23 không có `retained`: dùng stable và san == 'no_report'.
  - unstable_only (decision-log 2026-10-20 A4.2): không có divergence giữ lại nhưng có divergence không ổn định.
  - Dải B/N/U (R13, decision-log 2026-10-12): phân loại từng divergence giữ lại bằng bnu_v0 (bản bnu-v5), gộp: NB^L khi có N, NB^U khi
    có N hoặc U.
  - SA-1: bỏ divergence gắn cờ c_flag (C crash, sanitizer không báo); bản ra khỏi tử số khi mọi divergence giữ lại đều mang cờ.
  - SA-2: cộng các bản unstable_only có ít nhất một divergence không bị loại theo R15 (c_ub false).
  - Không so stderr (R29): bản ra khỏi tử số khi mọi divergence giữ lại chỉ khác ở stderr.
  - Trần output gấp 8 (R29): bỏ divergence giữ lại mà lần chạy ở trần lớn khớp; cộng divergence mới ở trần lớn (file *.capsens.jsonl)
    ổn định, sanitizer không báo.
  - Chỉ case đủ tầng M, MS, A: mẫu số P_complete (executable có đủ ba tầng ở mọi seed).
  - RQ2 (R14): 5 kết quả; r_FF = F / |R_test|, R_test = A + F + not_adjudicable; phân rã ca FF theo kênh oracle gốc báo trượt.
Bộ đếm R21, R23, R28 (thêm 2026-10-23, rà soát kỹ thuật): phân bố trạng thái kết thúc C và Rust; input hai bên cùng vượt ngân sách mà
khớp, kèm số byte prefix; input library khớp theo sai số nhưng khác khi so chính xác (giới hạn ở `gaps`).
F7 (survivorship, kế hoạch Chương 3): mọi bản dịch của danh sách cặp đầu vào có mặt trong kết quả với P_test hoặc một mã rời P_test
(case C build lỗi, harness_error, thiếu bản ghi); bộ đếm cấp bản dịch cho nhóm inconclusive; div_stderr_only cả hai loại; trần một phía.
D26 (Le quyết đêm 25/10): bộ đếm độ nhạy trần output (F4) lên summary kèm mẫu số; bản dịch `unexpected` ra khỏi mẫu số và mọi tử số,
đếm riêng ở `n_unexpected` ngoài phễu."""
import collections, glob, importlib.util, json, os

from .config import INSENSITIVE_SEED, REPO
from .record import open_text

_spec = importlib.util.spec_from_file_location('bnu_v0', f'{REPO}/experiments/09-bnu-rules/scripts/bnu_v0.py')
BNU = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(BNU)

# no_input_fields: library không có trường input, ngoài P_test theo thiết kế (decision-log 2026-10-20; Le giữ 25/10), xét trước.
# no_inputs: không có input nào được quan sát (Le chọn 25/10).
# F7 (thứ tự chèn mã mới do phiên kỹ thuật đặt, chờ Le xác nhận):
#   c_build_failed: C (hoặc runner library) không build được, cả case không quan sát được; lý do cấp case nên xét ngay sau no_input_fields
#                   (lý do theo thiết kế) và trước mọi lý do cấp bản dịch.
#   harness_error:  ngoại lệ trong harness ở một (case, seed) chưa được chạy lại thành công; xét sau rust_build_failed vì build Rust lỗi là
#                   tính chất tất định của bản dịch (bản rời P_test dù seed khác lỗi harness), còn harness_error là lỗi lần chạy.
#   missing_record: bản dịch có trong danh sách cặp mong đợi nhưng không có bản ghi ở seed nào; loại trừ mọi mã khác nên đặt cuối.
LEAVE_ORDER = ('no_input_fields', 'c_build_failed', 'rust_build_failed', 'harness_error', 'no_inputs', 'incomplete', 'san_infra',
               'missing_seed', 'missing_record')
# Trạng thái bản ghi case có thể mang lý do rời P_test cho mọi bản dịch của case (bản ghi cũ không có pair_status).
CASE_LEVEL = ('c_build_failed', 'harness_error')
GAPS = ['R21: match_tol_not_exact là số input khớp theo sai số nhưng khác khi so chính xác, chưa qua kiểm ổn định và sanitizer; '
        'bản dịch có số này > 0 là cận trên của phần tăng thêm khi so chính xác',
        'Bản ghi trước bộ đếm 2026-10-23 (rà soát kỹ thuật) không có R21, R23, R28: các trường đó bằng 0',
        'Bản ghi trước F7 không có cap_c_only, cap_r_only, cap_both, cap_one_side_match: các trường đó và cap_one_side_translations bằng 0',
        'Không truyền danh sách cặp mong đợi (--expect): bản dịch không có bản ghi nào không được đếm (missing_record bằng 0), và bản ghi '
        'c_build_failed, harness_error cũ không có pair_status, rust_build chỉ được đếm ở unattributed_case_records',
        'Bản ghi trước F4 (2026-10-25) không có cap_hit_div, cap_sens_infra_match, cap_sens_infra_div, cap_sens_timeout_rerun: các trường '
        'đó bằng 0, và cap_hit_total chỉ gồm cap_hit_match',
        'Dòng 5 (F3, 26/10): bản ghi case không đọc input trước 26/10 không có rust_input_syms: bản dịch đếm ở insensitive_rust.not_recorded. '
        'Runtime của Rust std nhập getenv, read, open64, mmap64 ngay cả khi chương trình không đọc input, nên with_input_syms là cận trên '
        'thô, không phải bằng chứng bản Rust đọc input',
        'Dòng 22 (F7, R22 thu hẹp): C-san chỉ chạy trên input divergence của lượt chính, nên ub_R22 chỉ có mẫu số là divergence (mọi '
        'divergence, divergence ổn định); không có tỉ lệ UB trên mọi input. Cấp cặp đếm (input, bản dịch); inputs_* đếm input phân biệt '
        '(case, seed, idx); bản ghi không có idx gộp các input cùng seed']
COUNT_KEYS = ('both_nt_match', 'both_nt_prefix_bytes', 'both_nt_prefix_zero', 'match_tol_not_exact',
              # F7: số input (cấp bản dịch cộng qua seed); div_stderr_only gồm mọi divergence, chưa lọc ổn định và sanitizer
              'div_stderr_only', 'div_stable_san_inconclusive', 'cap_hit_match', 'cap_sens_new_div',
              'cap_c_only', 'cap_r_only', 'cap_both', 'cap_one_side_match',
              # D26 (F4): số input chạm trần theo nhánh (khớp, divergence); trong đó lỗi hạ tầng ở trần lớn theo nhánh; số lần kết luận ở
              # trần lớn dùng timeout gấp TIMEOUT_RERUN_FACTOR (cả hai nhánh, mẫu số cap_hit_total)
              'cap_hit_div', 'cap_sens_infra_match', 'cap_sens_infra_div', 'cap_sens_timeout_rerun')


class Translations(dict):
    """{(bundle, case, system): trạng thái bản dịch}; `meta` giữ số đếm cấp bản ghi không gắn được vào bản dịch nào (F7)."""
    meta = None


def _jsonl(p):
    if not os.path.exists(p): return []
    with open_text(p) as f: return [json.loads(l) for l in f if l.strip()]


def unblob(b):
    """Ngược của record.blob: dict gzip + base64 -> bytes (None -> b'')."""
    import base64, gzip
    return gzip.decompress(base64.b64decode(b['gz64'])) if b else b''


def retained(d):
    return bool(d['retained']) if 'retained' in d else bool(d.get('stable')) and d.get('san') == 'no_report'


def bnu_group(d):
    return bnu_rule(d)[0]


def bnu_rule(d):
    """(nhóm, mã luật) của bnu_v0 (bản bnu-v5) cho một divergence. Hàng đợi master plan dòng 23 (F6, F7; Le chọn 26/10 "metrics lưu và
    đếm theo luật"): giữ mã luật thay vì chỉ nhóm."""
    if d['kind'] == 'exe':
        g = BNU.classify_exe(d.get('c_rc'), d.get('r_rc'), d.get('c_to'), d.get('r_to'),
                             unblob(d.get('c_out')).decode('latin-1'), unblob(d.get('r_out')).decode('latin-1'), d.get('c_ub', False),
                             False, unblob(d.get('c_err')).decode('latin-1'), unblob(d.get('r_err')).decode('latin-1'))
    else:
        g = BNU.classify_lib(d['c'], d['r'], d.get('c_ub', False))
    return g[0], g[1]


def is_ub(d):
    """Divergence mà kiểm sanitizer phía C báo UB (R15); bản ghi cũ chỉ có c_ub."""
    return d.get('san') == 'ub' or bool(d.get('c_ub'))


# Hàng đợi master plan dòng 22 (F7, Le chọn 26/10 "thu hẹp R22, kèm mẫu số"): C-san chỉ chạy trên input divergence (lượt chính), nên số
# thực thi bị loại theo R15 chỉ đo được trên các input đó. Khoá cấp bản dịch (cộng qua seed cần) và mẫu số tương ứng:
#   n_div_ub / n_div_all: divergence (cặp input, bản dịch) mà C-san báo UB trên mọi divergence;
#   n_div_stable_ub / n_div_stable: như trên, chỉ divergence ổn định.
UB_KEYS = ('n_div_all', 'n_div_ub', 'n_div_stable', 'n_div_stable_ub')


def load_rq1(out_dir, kind):
    """Bản ghi case và divergence của một lần chạy harness.rq1 (một kind)."""
    # F7: giữ cả bản ghi c_build_failed và harness_error (trước chỉ 'done', nên bản dịch của các case đó mất khỏi mẫu số);
    # rq1_translations chọn bản ghi theo (case, seed) và bỏ trạng thái không mang pair_status (insensitive_other_seed).
    cases = [r for r in _jsonl(f'{out_dir}/rq1-{kind}.jsonl') if r.get('status') in ('done', *CASE_LEVEL)]
    divs, caps = collections.defaultdict(list), collections.defaultdict(list)
    for f in glob.glob(f'{out_dir}/div/*.jsonl') + glob.glob(f'{out_dir}/div/*.jsonl.gz'):   # .gz: F8, nén khi case xong
        n = f[:-3] if f.endswith('.gz') else f
        if n.endswith(('.memlimit.jsonl', '.exact.jsonl')): continue
        tgt = caps if n.endswith('.capsens.jsonl') else divs
        if tgt is None: continue
        for d in _jsonl(f):
            if d['kind'] != kind: continue
            tgt[(d['bundle'], d['case'], d['system'], d['seed'])].append(d)
    return cases, divs, caps


def _expected_by_case(expected):
    """expected: các (bundle, case, system) hoặc dòng cặp của harness.pairs (bundle, tractor_case, system)."""
    out = collections.defaultdict(list)
    for e in expected or ():
        b, c, s = (e['bundle'], e.get('tractor_case', e.get('case')), e['system']) if isinstance(e, dict) else e
        if s not in out[(b, c)]: out[(b, c)].append(s)
    return out


def _pair_status(r, exp, unattr):
    """pair_status của bản ghi case; bản ghi c_build_failed, harness_error cũ (không có pair_status) suy từ rust_build hoặc danh sách cặp."""
    if r.get('pair_status'): return r['pair_status']
    st = r.get('status')
    if st not in CASE_LEVEL: return None
    systems = list(r.get('rust_build') or {}) or exp.get((r['bundle'], r['case']), [])
    if not systems: unattr[st] += 1; return None
    return {s: st for s in systems}


def rq1_translations(cases, divs, caps, seeds, expected=None):
    """{(bundle, case, system): dict trạng thái và các cờ cấp bản dịch}.

    F7: expected (danh sách cặp đầu vào, tuỳ chọn) để bản dịch không có bản ghi nào mang mã 'missing_record'; bản dịch có bản ghi mà
    ngoài danh sách mang cờ `unexpected` (giữ trong kết quả; summarize_rq1 loại khỏi mẫu số và tử số, D26). Một (case, seed) có cả bản ghi harness_error và bản ghi chạy lại thành công
    thì dùng bản chạy lại."""
    T = Translations(); exp = _expected_by_case(expected); unattr = collections.Counter()
    best = {}
    for r in cases:
        ps = _pair_status(r, exp, unattr)
        if ps is None: continue
        k, rank = (r['bundle'], r['case'], r['seed']), r.get('status') == 'harness_error'
        if k not in best or rank < best[k][0]: best[k] = (rank, ps, r)
    by = collections.defaultdict(dict)
    for (b, c, sd), (_, ps, r) in sorted(best.items()):
        for s, st in ps.items():
            by[(b, c, s)][sd] = (st, r)
    for k, per in by.items():
        # Case không đọc input chỉ chạy ở seed INSENSITIVE_SEED (Le chọn 25/10): chỉ đòi seed đó.
        need = [INSENSITIVE_SEED] if any(r.get('input_insensitive') for _, r in per.values()) and INSENSITIVE_SEED in seeds else seeds
        sts = [per[sd][0] if sd in per else 'missing_seed' for sd in need]
        # A1 (Le chọn 24/10, sửa code): pair_status 'san_infra' là theo từng seed (seed đó không có divergence giữ lại và có divergence
        # ổn định chỉ thiếu kiểm sanitizer). Gộp qua ba seed: bản dịch đã có divergence giữ lại ở một seed khác thì quyết định không còn
        # phụ thuộc kiểm bị lỗi, nên seed 'san_infra' tính như P_test; chỉ rời P_test khi không seed nào có divergence giữ lại.
        if 'san_infra' in sts and any(retained(d) for sd in need for d in divs.get((*k, sd), [])):
            sts = ['P_test' if x == 'san_infra' else x for x in sts]
        leave = next((x for x in LEAVE_ORDER if x in sts), None)
        # F7: mã lạ (ngoài LEAVE_ORDER) trước đây rơi vào P_test; nay rời P_test với chính mã đó và hiện ở leave_other
        if leave is None: leave = next((x for x in sts if x != 'P_test'), None)
        t = dict(bundle=k[0], case=k[1], system=k[2], status='P_test' if leave is None else leave)
        cn = collections.Counter()
        for sd in need:
            if sd in per: cn.update((per[sd][1].get('counts') or {}).get(k[2]) or {})
        t['counts'] = cn
        if leave is None:
            ds = {sd: divs.get((*k, sd), []) for sd in need}
            ret = {sd: [d for d in v if retained(d)] for sd, v in ds.items()}
            allret = [d for v in ret.values() for d in v]
            alld = [d for v in ds.values() for d in v]
            t['in_S'] = bool(allret)
            t['n_seeds_detect'] = sum(bool(v) for v in ret.values())
            t['unstable_only'] = not allret and any(not d.get('stable') for d in alld)
            rules = [bnu_rule(d) for d in allret]
            grp = [g for g, _ in rules]
            t['bnu_rules'] = dict(collections.Counter(r for _, r in rules))   # dòng 23: số divergence giữ lại theo mã luật
            t['NB_L'] = 'N' in grp; t['NB_U'] = 'N' in grp or 'U' in grp
            t['SA1'] = any(not d.get('c_flag') for d in allret)
            t['SA2'] = t['in_S'] or (t['unstable_only'] and any(not d.get('c_ub') for d in alld))
            t['no_stderr'] = any(d.get('channels') != ['stderr'] for d in allret)
            kept8 = [d for d in allret if not (d.get('cap_sens') or {}).get('equal')]
            new8 = [d for sd in need for d in caps.get((*k, sd), []) if d.get('stable') and d.get('san') == 'no_report']
            t['cap8'] = bool(kept8 or new8)
            layers = [set((per[sd][1].get('gen') or {}).get('n_by_layer') or {}) for sd in need]
            t['complete_layers'] = all({'M', 'MS', 'A'} <= L for L in layers)
            t['input_insensitive'] = any(per[sd][1].get('input_insensitive') for sd in need)
            if t['input_insensitive']:
                # dòng 5 (F3): ký hiệu đọc input mà binary Rust nhập; None: không kiểm được; 'not_recorded': bản ghi trước 26/10
                rs = [per[sd][1]['rust_input_syms'] for sd in need if 'rust_input_syms' in per[sd][1]]
                t['rust_input_syms'] = rs[0].get(k[2], 'not_recorded') if rs else 'not_recorded'
            # dòng 22 (F7): UB theo C-san trên input divergence, kèm khoá input (seed, idx) để đếm input phân biệt theo nhóm
            t.update(n_div_all=len(alld), n_div_ub=sum(map(is_ub, alld)), n_div_stable=sum(bool(d.get('stable')) for d in alld),
                     n_div_stable_ub=sum(bool(d.get('stable')) and is_ub(d) for d in alld))
            t['div_inputs'] = sorted({(d['seed'], d.get('idx')) for d in alld}, key=str)
            t['div_stable_inputs'] = sorted({(d['seed'], d.get('idx')) for d in alld if d.get('stable')}, key=str)
            t['ub_inputs'] = sorted({(d['seed'], d.get('idx')) for d in alld if is_ub(d)}, key=str)
            t['ub_stable_inputs'] = sorted({(d['seed'], d.get('idx')) for d in alld if d.get('stable') and is_ub(d)}, key=str)
            t['n_div_retained'] = len(allret); t['n_stderr_only'] = sum(d.get('channels') == ['stderr'] for d in allret)
            # F7, nhóm inconclusive (decision-log 2026-10-23 khuya, rà §3.6 finding 8): không có divergence giữ lại nhưng có ít nhất một
            # divergence ổn định với kiểm sanitizer 'inconclusive'; ở lại P_test, ngoài D. inconclusive_any chỉ để đối chiếu.
            inc = [d for d in alld if d.get('stable') and d.get('san') == 'inconclusive']
            t['n_div_inconclusive'] = len(inc); t['inconclusive_any'] = bool(inc); t['inconclusive_only'] = bool(inc) and not allret
        T[k] = t
    if expected is not None:
        for (b, c), ss in exp.items():
            for s in ss:
                if (b, c, s) not in T:
                    T[(b, c, s)] = dict(bundle=b, case=c, system=s, status='missing_record', counts=collections.Counter())
        for k, t in T.items(): t['unexpected'] = k[2] not in exp.get(k[:2], ())
    T.meta = dict(unattributed_case_records=dict(unattr), expected=None if expected is None else sum(map(len, exp.values())))
    return T


def summarize_rq1(T, kind, v6_causes=None):
    """Số đếm theo nhóm corpus (B01, B02, P00, P01) và tổng; mẫu số P_test (SA chỉ đủ tầng: P_complete).
    v6_causes (tuỳ chọn, load_v6_causes): thêm mục `v6_separation` (báo tách theo nguyên nhân V6); không truyền thì kết quả như trước."""
    out = {}
    groups = sorted({t['bundle'].split('_')[0] for t in T.values()}) + ['all']
    for g in groups:
        ga = [t for t in T.values() if g == 'all' or t['bundle'].startswith(g)]
        out[g] = _group_counts(ga, kind)
        if g == 'all':      # dòng 22 (F7): chi tiết theo cặp chỉ ở nhóm tổng
            pt = [t for t in ga if not t.get('unexpected') and t['status'] == 'P_test']
            out[g]['ub_R22_by_pair'] = {f"{t['bundle']}/{t['case']}/{t['system']}": {x: t[x] for x in UB_KEYS} for t in pt if t['n_div_all']}
    meta = getattr(T, 'meta', None) or {}
    res = dict(kind=kind, by_group=out, gaps=GAPS, expected=meta.get('expected'),
               unattributed_case_records=meta.get('unattributed_case_records', {}))
    if v6_causes is not None: res['v6_separation'] = v6_separation(T, kind, v6_causes, groups)
    return res


def _group_counts(ga, kind):
    """Số đếm của một tập bản dịch (một nhóm corpus, hoặc một phần của nhóm ở v6_separation)."""
    # D26 (F7, Le quyết 25/10): bản dịch ngoài danh sách cặp mong đợi không vào mẫu số, tử số hay phễu; chỉ đếm ở n_unexpected
    ts = [t for t in ga if not t.get('unexpected')]
    pt = [t for t in ts if t['status'] == 'P_test']
    c = dict(n_translations=len(ts), P_test=len(pt), leave={x: sum(t['status'] == x for t in ts) for x in LEAVE_ORDER},
             # F7: trạng thái ngoài LEAVE_ORDER (không được xảy ra) vẫn được đếm; funnel_ok kiểm n_translations = P_test + rời
             leave_other=dict(collections.Counter(t['status'] for t in ts if t['status'] != 'P_test' and t['status'] not in LEAVE_ORDER)),
             n_unexpected=sum(bool(t.get('unexpected')) for t in ga),
             D_all=sum(t['in_S'] for t in pt), unstable_only=sum(t['unstable_only'] for t in pt),
             seeds_detect=dict(collections.Counter(t['n_seeds_detect'] for t in pt if t['in_S'])),
             NB_L=sum(t['NB_L'] for t in pt), NB_U=sum(t['NB_U'] for t in pt), SA1=sum(t['SA1'] for t in pt),
             SA2=sum(t['SA2'] for t in pt), no_stderr=sum(t['no_stderr'] for t in pt), cap8=sum(t['cap8'] for t in pt))
    c['funnel_ok'] = c['n_translations'] == c['P_test'] + sum(c['leave'].values()) + sum(c['leave_other'].values())
    # F7, nhóm inconclusive (cấp bản dịch, mẫu số P_test) và robustness analysis tính nhóm này vào tử số
    c.update(inconclusive_only=sum(t['inconclusive_only'] for t in pt), inconclusive_any=sum(t['inconclusive_any'] for t in pt),
             inconclusive_and_unstable_only=sum(t['inconclusive_only'] and t['unstable_only'] for t in pt),
             D_with_inconclusive=sum(t['in_S'] or t['inconclusive_only'] for t in pt))
    # F7, stderr (R29): số divergence giữ lại chỉ khác ở stderr, và số bản trong D mà mọi divergence giữ lại chỉ khác ở stderr
    c.update(n_stderr_only_retained=sum(t['n_stderr_only'] for t in pt), D_stderr_only=sum(t['in_S'] and not t['no_stderr'] for t in pt))
    # dòng 23 (F6, F7): số divergence giữ lại theo mã luật B/N/U (mẫu số n_div_retained) và số bản dịch có ít nhất một divergence
    # theo mã luật đó (mẫu số D_all)
    br = collections.Counter(); bt = collections.Counter()
    for t in pt:
        br.update(t.get('bnu_rules') or {}); bt.update(set(t.get('bnu_rules') or {}))
    c.update(n_div_retained=sum(t['n_div_retained'] for t in pt), bnu_rule_div=dict(br), bnu_rule_translations=dict(bt))
    # dòng 22 (F7): R22 thu hẹp. Cấp cặp cộng qua bản dịch P_test; cấp input phân biệt theo (case, seed, idx) vì C-san chạy một lần
    # mỗi input, chung mọi hệ (cùng input UB được đếm một lần dù nhiều bản dịch cùng divergence trên đó)
    inp = {x: {(t['bundle'], t['case'], *e) for t in pt for e in t[x]}
           for x in ('div_inputs', 'div_stable_inputs', 'ub_inputs', 'ub_stable_inputs')}
    c['ub_R22'] = dict({x: sum(t[x] for t in pt) for x in UB_KEYS},
                       translations_with_div=sum(t['n_div_all'] > 0 for t in pt), translations_with_ub=sum(t['n_div_ub'] > 0 for t in pt),
                       inputs_div=len(inp['div_inputs']), inputs_ub=len(inp['ub_inputs']),
                       inputs_div_stable=len(inp['div_stable_inputs']), inputs_stable_ub=len(inp['ub_stable_inputs']))
    agg = collections.Counter()
    for t in pt: agg.update(t['counts'])
    c.update({x: agg[x] for x in COUNT_KEYS}, cap_hit_total=agg['cap_hit_match'] + agg['cap_hit_div'],   # D26: mẫu số trần lớn
             exact_translations=sum(t['counts']['match_tol_not_exact'] > 0 for t in pt),
             cap_one_side_translations=sum(t['counts']['cap_c_only'] + t['counts']['cap_r_only'] > 0 for t in pt),   # F7
             c_status={x.split(':', 1)[1]: n for x, n in agg.items() if x.startswith('c_status:')},
             r_status={x.split(':', 1)[1]: n for x, n in agg.items() if x.startswith('r_status:')})
    if kind == 'exe':
        pi = [t for t in pt if t.get('input_insensitive')]      # nhóm riêng (decision-log 2026-10-24)
        c.update(P_test_insensitive=len(pi), D_insensitive=sum(t['in_S'] for t in pi))
        # dòng 5 (F3): bản dịch P_test của case không đọc input mà binary Rust nhập ký hiệu đọc input; mẫu số P_test_insensitive
        rsy = [t.get('rust_input_syms', 'not_recorded') for t in pi]
        sym_n = collections.Counter(x for v in rsy if isinstance(v, list) for x in v)
        c['insensitive_rust'] = dict(n=len(pi), with_input_syms=sum(isinstance(v, list) and bool(v) for v in rsy),
                                     without_input_syms=sum(v == [] for v in rsy), unchecked=sum(v is None for v in rsy),
                                     not_recorded=sum(v == 'not_recorded' for v in rsy), sym_translations=dict(sym_n))
        pc = [t for t in pt if t['complete_layers']]
        c.update(P_complete=len(pc), D_complete=sum(t['in_S'] for t in pc))
    return c


# ---------------- Báo tách theo nguyên nhân V6 (Le chọn 26/10) ----------------
# Q10 (c) (docs/proposal/a3-a7-package-plan.md mục 0) và decision-log 2026-10-25 "Timeout theo case ...; tiêu chí V6": bản dịch của case
# mà V6 thấy input không ổn định, với nguyên nhân C không tất định hoặc chưa giải thích được, báo tách trong RQ1. Le chọn 26/10: tách các
# mã C-UNINIT, C-SRC, NEAR-TO, UNEXPLAINED (danh sách mã: experiments/28-v6-causes/README.md mục 2). Không tách C-UB (input đã ra khỏi S
# theo luật sanitizer của RQ1), INFRA (chạy lại input), HARNESS (sửa rồi chạy lại V6).
V6_SEPARATED = ('C-UNINIT', 'C-SRC', 'NEAR-TO', 'UNEXPLAINED')
V6_CODES = ('C-UB', 'INFRA', 'HARNESS') + V6_SEPARATED
# Số đếm gọn cho từng hệ; mức nhóm dùng đủ _group_counts
_BRIEF = ('n_translations', 'P_test', 'leave', 'leave_other', 'n_unexpected', 'D_all', 'unstable_only', 'inconclusive_only', 'NB_L',
          'NB_U', 'SA1', 'SA2', 'no_stderr', 'cap8', 'funnel_ok')


def load_v6_causes(path):
    """File JSONL, mỗi dòng {"kind": "exe"|"lib", "bundle", "case", "code"}. Trả về {(kind, bundle, case): code}.
    Báo lỗi (ValueError) khi thiếu trường, kind hoặc mã lạ, hay một case có hai mã khác nhau (mỗi case một mã, exp 28 mục 2)."""
    out = {}
    with open_text(path) as f:
        for n, line in enumerate(f, 1):
            if not line.strip(): continue
            d = json.loads(line)
            miss = [x for x in ('kind', 'bundle', 'case', 'code') if not d.get(x)]
            if miss: raise ValueError(f'{path}:{n}: thiếu trường {miss}')
            if d['kind'] not in ('exe', 'lib'): raise ValueError(f"{path}:{n}: kind lạ {d['kind']!r}")
            if d['code'] not in V6_CODES: raise ValueError(f"{path}:{n}: mã lạ {d['code']!r} (hợp lệ: {', '.join(V6_CODES)})")
            k = (d['kind'], d['bundle'], d['case'])
            if out.get(k, d['code']) != d['code']: raise ValueError(f'{path}:{n}: case {k} có hai mã {out[k]!r}, {d["code"]!r}')
            out[k] = d['code']
    return out


def v6_separation(T, kind, causes, groups):
    """Theo nhóm corpus: số đếm của phần báo tách (`separated`: bản dịch của case có mã trong V6_SEPARATED) và phần còn lại (`rest`), mỗi
    phần có mẫu số riêng (n_translations, P_test, leave); `all` của nhóm là by_group cùng tên (separated + rest, kiểm ở `split_ok`).
    Kèm theo từng hệ (`by_system`, số đếm gọn _BRIEF), số bản dịch theo mã (mọi mã, kể cả không tách), danh sách case tách, và các dòng
    của file không khớp bản dịch nào (`unmatched`, để bắt sai tên case)."""
    mine = {(b, c): code for (k, b, c), code in causes.items() if k == kind}
    code_of = lambda t: mine.get((t['bundle'], t['case']))
    sep = lambda t: code_of(t) in V6_SEPARATED
    out = {}
    for g in groups:
        ga = [t for t in T.values() if g == 'all' or t['bundle'].startswith(g)]
        a, b = [t for t in ga if sep(t)], [t for t in ga if not sep(t)]
        full, cs, cr = _group_counts(ga, kind), _group_counts(a, kind), _group_counts(b, kind)
        e = dict(separated=cs, rest=cr,
                 split_ok=all(full[x] == cs[x] + cr[x] for x in ('n_translations', 'P_test', 'D_all', 'n_unexpected')),
                 by_code=dict(collections.Counter(code_of(t) for t in ga if code_of(t) and not t.get('unexpected'))),
                 by_system={})
        for s in sorted({t['system'] for t in ga}):
            e['by_system'][s] = {part: {x: c[x] for x in _BRIEF} for part, c in
                                 (('all', _group_counts([t for t in ga if t['system'] == s], kind)),
                                  ('separated', _group_counts([t for t in a if t['system'] == s], kind)),
                                  ('rest', _group_counts([t for t in b if t['system'] == s], kind)))}
        out[g] = e
    seen = {(t['bundle'], t['case']) for t in T.values()}
    return dict(codes_separated=list(V6_SEPARATED), n_cases_in_file=len(mine),
                separated_cases=sorted(f'{b}/{c}:{code}' for (b, c), code in mine.items() if code in V6_SEPARATED and (b, c) in seen),
                unmatched=sorted(f'{b}/{c}:{code}' for (b, c), code in mine.items() if (b, c) not in seen), by_group=out)


def _state_parts(diff):
    """(expected, got) từ diff 'Library State Mismatch. Expected:<xuống dòng><json><xuống dòng>Got:<xuống dòng><json>' của runner TRACTOR; None nếu không giải mã được
    (diff bị cắt ở 300 ký tự trong bản ghi trước D6, hoặc định dạng khác)."""
    try:
        a, b = diff.split('Expected:', 1)[1].split('\nGot:', 1)
        dec = json.JSONDecoder()
        return dec.raw_decode(a.strip())[0], dec.raw_decode(b.strip())[0]
    except (IndexError, ValueError):
        return None


def _float_only(a, b):
    """True khi a và b cùng cấu trúc (cùng khoá, mảng cùng độ dài) và mọi lá khác nhau là cặp số mà ít nhất một bên là số thực JSON
    (có dấu chấm hoặc mũ). Lá có null (NaN, inf của serde_json hoặc optional None), bool, chuỗi, số nguyên khác nhau: False."""
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_float_only(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_float_only(x, y) for x, y in zip(a, b))
    if type(a) is type(b) and a == b: return True
    return num(a) and num(b) and (isinstance(a, float) or isinstance(b, float))


def state_channel(orig):
    """Kênh của một diff State Mismatch (D6, Le chọn 25/10): 'state_float' khi Expected và Got chỉ khác ở giá trị số thực, 'state_other'
    khi khác ở trường khác (số nguyên, bool, chuỗi, null, cấu trúc), 'state' khi không giải mã được (giữ nhãn trước D6)."""
    p = _state_parts(orig.get('state_diff') or orig.get('diff') or '')
    if p is None: return 'state'
    return 'state_float' if p[0] != p[1] and _float_only(*p) else 'state_other'


def ff_channels(vectors):
    """Kênh oracle gốc báo trượt, theo trường diff của báo cáo tái lập (Q7b): 'stderr', 'stdout' (diff bắt đầu bằng tên luồng; diff có cả
    hai luồng lấy luồng đứng đầu, như trước D6), 'state_float', 'state_other', 'state' (D6: tách kênh state, xem state_channel), còn lại
    'result:<kết quả runner>' (trạng thái kết thúc: Panic là exit 101, SegmentationFault, UnknownFailure là signal; Timeout; và
    'Return code mismatch'). Trả về các kênh của mọi vector trượt của bản dịch, nối bằng '+'."""
    ch = set()
    for v in vectors:
        o = v.get('orig') or {}
        d = o.get('diff') or ''
        if d.startswith('Stderr diff'): ch.add('stderr')
        elif d.startswith('Stdout diff'): ch.add('stdout')
        elif 'State Mismatch' in d: ch.add(state_channel(o))
        else: ch.add(f"result:{o.get('result')}")
    return '+'.join(sorted(ch))


# Trạng thái kết thúc mà runner gốc xếp thất bại không xét vector (runner.rs parse_exit_status, decision-log 2026-10-23 ghi 2026-10-25):
# exit 101 là Panic; signal là SegmentationFault (SIGSEGV) hoặc UnknownFailure. Library: runner trả thẳng các kết quả đó.
LIB_TERM = dict(Panic='exit_101', SegmentationFault='signal', UnknownFailure='signal')


def c_termination(v):
    """Tập nhãn {'exit_101', 'signal'} của phía C ở các lần chạy dùng để quyết định của một bản ghi vector RQ2 (D6). Executable: c_status
    'signal', hoặc 'exit' với c_rc 101. Library: kết quả runner của C theo LIB_TERM."""
    out = set()
    for s in v.get('runs') or []:
        if 'c_status' in s:
            if s['c_status'] == 'signal': out.add('signal')
            elif s['c_status'] == 'exit' and s.get('c_rc') == 101: out.add('exit_101')
        elif s.get('c_result'):
            k1, res = s['c_result']
            if k1 == 'reported' and res in LIB_TERM: out.add(LIB_TERM[res])
    return out


def c_term_counts(recs, outcomes=None):
    """Số vector trượt (bản ghi vector có lần chạy) mà C kết thúc bằng exit 101 hoặc signal ở ít nhất một lần dùng để quyết định, kèm mẫu
    số. outcomes: chỉ đếm bản dịch có kết quả thuộc tập này (ví dụ chấm trượt oan: behavioral_agreement)."""
    c = collections.Counter()
    for r in recs:
        if outcomes is not None and r.get('outcome') not in outcomes: continue
        for v in r.get('vectors') or []:
            if not v.get('runs'): continue
            c['n_vectors'] += 1
            t = c_termination(v)
            c['any'] += bool(t)
            for x in t: c[x] += 1
    return {k: c[k] for k in ('n_vectors', 'any', 'exit_101', 'signal')}


def summarize_rq2(recs):
    outs = collections.Counter(r.get('outcome', 'harness_error') for r in recs)
    A, F = outs['behavioral_disagreement'], outs['behavioral_agreement']
    na = outs['not_adjudicable']
    reasons = collections.Counter(x for r in recs if r.get('outcome') == 'not_adjudicable' for x in r.get('reasons') or [])
    nre = collections.Counter(x for r in recs if r.get('outcome') == 'not_re_examined' for x in r.get('reasons') or [])
    ffch = collections.Counter(ff_channels(r['vectors']) for r in recs if r.get('outcome') == 'behavioral_agreement')
    # F5 (2026-10-25): một mã mỗi bản dịch (`reason`, rq2.primary_reason; bản ghi cũ suy từ `reasons`), tổng theo kết quả bằng số bản;
    # và số vector theo (kết quả, mã) trên mọi bản dịch.
    # D3 (Le chọn 25/10): mã theo thứ tự ưu tiên rq2.TRANSLATION_REASON_ORDER; bản ghi cũ không có `reason` hoặc mang 'multiple' (F5) tính
    # lại từ `reasons`.
    from .rq2 import primary_reason
    one = collections.Counter()
    for r in recs:
        o = r.get('outcome', 'harness_error')
        if o in ('behavioral_disagreement', 'behavioral_agreement'): continue
        code = 'harness_error' if o == 'harness_error' else r.get('reason')
        if code in (None, 'multiple'): code = primary_reason(o, r.get('reasons'))
        one[f'{o}:{code}'] += 1
    vec = collections.Counter(f"{v.get('outcome')}:{v.get('reason')}" for r in recs for v in r.get('vectors') or [])
    return dict(A=A, F=F, not_adjudicable=na, R_test=A + F + na, not_adjudicable_reasons=dict(reasons),
                not_re_examined=outs['not_re_examined'], not_re_examined_reasons=dict(nre), harness_error=outs['harness_error'],
                ff_channels=dict(ffch), translation_reason=dict(one), vector_reasons=dict(vec),
                # D6: vector trượt có C kết thúc bằng exit 101 hoặc signal, trên mọi bản và trên bản chấm trượt oan
                c_term_vectors=c_term_counts(recs), c_term_vectors_ff=c_term_counts(recs, ('behavioral_agreement',)))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog='harness.metrics')
    ap.add_argument('--rq1'); ap.add_argument('--rq2'); ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--expect', choices=['pilot', 'p_rep'],
                    help='F7: danh sách cặp mong đợi (pilot: như harness.rq1 --pilot; p_rep: harness.pairs.prep_pairs), đếm missing_record')
    ap.add_argument('--v6-causes', metavar='F',
                    help='JSONL {"kind","bundle","case","code"}: mã nguyên nhân V6 theo case (exp 28); thêm mục v6_separation (báo tách '
                         'C-UNINIT, C-SRC, NEAR-TO, UNEXPLAINED) vào summary RQ1')
    a = ap.parse_args(argv)
    seeds = [int(x) for x in a.seeds.split(',')]
    v6 = load_v6_causes(a.v6_causes) if a.v6_causes else None
    res = {}
    if a.rq1:
        for kind in ('exe', 'lib'):
            cases, divs, caps = load_rq1(a.rq1, kind)
            exp = None
            if a.expect == 'pilot':
                from .rq1 import pilot_pairs; exp = pilot_pairs(kind)
            elif a.expect == 'p_rep':
                from .pairs import prep_pairs; exp = prep_pairs(kind)
            if cases or exp: res[f'rq1_{kind}'] = summarize_rq1(rq1_translations(cases, divs, caps, seeds, exp), kind, v6)
    if a.rq2:
        for kind in ('exe', 'lib'):
            recs = _jsonl(f'{a.rq2}/rq2-{kind}.jsonl')
            if recs: res[f'rq2_{kind}'] = summarize_rq2(recs)
    print(json.dumps(res, indent=1, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
