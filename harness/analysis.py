"""Phân tích sau đo: bảy nhóm số §3.6 hứa mà harness/metrics.py chưa tính (Le chọn 26/10: cài ở file mới; sau commit đo bc82907,
harness/ chỉ được thêm file mới, nên file này không sửa metrics, rq1, rq2, observe mà gọi lại hàm của chúng).

Chỉ đọc bản ghi đã lưu của harness.rq1 (bản ghi case, div/*.jsonl(.gz), inputs/*.inputs.jsonl.gz) và harness.rq2 (bản ghi bản dịch kèm
quan sát từng lần chạy `obs`), census cho nhóm non-reproduced decision; không chạy chương trình nào.

Dùng: python3 -m harness.analysis --rq1 DIR --kind exe|lib [--rq2 DIR] --out FILE.json [--seeds 0,1,2] [--expect pilot|p_rep]
      [--nonrep-evidence FILE] [--nonrep-unclassified missing|unknown]
Đầu ra: JSON {meta, kind, sections: {<mục>: {<nhóm>: {'_all' | <hệ>: {...}}}}}. Mọi đại lượng có dạng {num, den}; num hoặc den là null
khi bản ghi không đủ để tính đúng (không ước lượng; lý do ở meta.gaps và trường `missing` của mục). Mục và định nghĩa:

1. rq1_rob_float (chỉ library): robustness analyses 4 (so số thực chính xác) và 5 (luật số thực của oracle gốc) của RQ1. Bản ghi RQ1 KHÔNG
   đủ để tính số bản dịch D của hai phân tích (D.num luôn null, `missing` liệt kê phần thiếu). Phần tính đúng được, báo làm thành phần:
   phân tích 5, số divergence giữ lại mà hai quan sát bằng nhau theo luật oracle gốc (bỏ được chắc chắn, bất kể kiểm ổn định) và số bản
   dịch trong D mà mọi divergence giữ lại thuộc loại đó. Phân tích 4 không bỏ được divergence nào bằng phép so (so chính xác chặt hơn sai số
   tương đối), chỉ có thể đổi qua kiểm ổn định, mà lần chạy lại không được lưu.
2. rq2_rob: ba robustness analyses RQ2 (bỏ stderr; library so số thực chính xác; library theo luật oracle gốc). Tính lại kết quả cấp vector
   bằng rq2.recompute_vector với phép so thay thế (gán tạm rq2._equal, nên luật quyết định là đúng mã của rq2), rồi rq2.translation_outcome.
   Mẫu số R_test của số chính; bản đổi thành not adjudicable hoặc not re-examined báo riêng, vẫn trong mẫu số. Phép so thay thế áp cho mọi
   lần so của vector (C với Rust và C giữa các lần chạy). Bản ghi không có `obs` (trước F5) không tính lại được: num null.
3. div_by_input (R24): divergence theo tầng (executable S, M, MS, A; library vector, random, dict, sweep) và theo nguồn (executable seed,
   random, dict, syntax, afl), thêm 'generated' (mọi tầng trừ vector gốc). Đơn vị chính: (input, bản dịch, seed) trên bản dịch P_test, mẫu
   số là số quan sát (input đã thực thi của tầng nhân số bản dịch, cộng qua seed cần); kèm input phân biệt (case, seed, idx) và bản dịch
   trong D có divergence giữ lại từ tầng đó (mẫu số D).
4. out_of_domain: input ngoài miền theo tầng (executable gen.n_out_of_domain trên gen.n_gen_by_layer) hoặc nguồn (library
   out_of_domain_by_source trên n_by_source); đơn vị input của (case, seed), một lần mỗi case, chỉ theo nhóm.
5. attrition_inputs: hao hụt sau P_rep tính theo input. Mỗi bản dịch: số input lên lịch (input đã thực thi của case ở mỗi seed cần) trừ số
   input đã quan sát; mã rời P_test như metrics. Mã mà input không xác định (case không sinh input, thiếu bản ghi) báo số bản dịch không xác
   định thay vì đoán; san_infra báo thêm số divergence ổn định chỉ thiếu kiểm sanitizer.
6. nt_one_side (R23): nhóm "NT một bên đã xác nhận": divergence có timeout_confirmed (sau chạy lại gấp mười vẫn đúng một bên vượt ngân
   sách), theo divergence giữ lại, mọi divergence, bản dịch trong D có ít nhất một và có mọi divergence giữ lại thuộc nhóm.
7. nonrep_groups: bốn nhóm bằng chứng của non-reproduced decision (§3.2, Phụ lục A: oracle drift, lỗi truy được về bản dịch, UB không bị
   sanitizer phát hiện, chưa rõ) trên hai phía. Tập non-reproduced lấy từ census theo cùng luật gen-rq-macros.census_counts (phía chấp nhận:
   phần còn lại của P_acc \\ P_rep sau unstable, build, timeout; phía từ chối: R_0^test build được và tái lập đỗ). Gán nhóm cần bằng chứng
   tay, nên đọc từ file --nonrep-evidence (JSONL kind, path accepted|rejected, bundle, case, system, group, source); không có file thì số
   theo nhóm là null. Nhóm hợp lệ theo chiều khác biệt: NONREP_ALLOWED (câu hỏi mở, chờ Le chốt)."""
import argparse, collections, contextlib, csv, json, math, os, struct, subprocess, sys

from . import metrics as HM
from . import observe as OB
from . import rq2 as HQ
from .config import INSENSITIVE_SEED, REPO, T as TRACTOR_TESTS, TRACTOR_COMMIT
from .record import open_text

EXE_LAYERS = ('S', 'M', 'MS', 'A')
LIB_LAYERS = ('vector', 'random', 'dict', 'sweep')
EXE_SOURCES = ('seed', 'random', 'dict', 'syntax', 'afl')
GEN = 'generated'                       # gộp mọi tầng sinh (executable M, MS, A; library mọi nguồn trừ vector)
RQ2_ANALYSES = dict(exe=('no_stderr',), lib=('no_stderr', 'exact', 'orig_float'))
R_TEST = ('behavioral_disagreement', 'behavioral_agreement', 'not_adjudicable')
OUTCOMES = R_TEST + ('not_re_examined',)
NONREP_GROUPS = ('oracle_drift', 'translation', 'undetected_ub', 'unknown')
# Phụ lục A: "a group is assigned only where it applies to the direction of the discrepancy". Đề xuất của phiên kỹ thuật: lỗi truy được về
# bản dịch chỉ áp cho phía chấp nhận (bản đỗ công bố trượt khi tái lập); phía từ chối (bản trượt công bố đỗ khi tái lập) chỉ có ba nhóm còn
# lại. Chưa có trong decision-log (câu hỏi mở Q-N1 trong rq-macro-map.md).
NONREP_ALLOWED = dict(accepted=NONREP_GROUPS, rejected=('oracle_drift', 'undetected_ub', 'unknown'))
# Nguồn quyết định công bố, như gen-rq-macros.census_counts (Bảng 3.1).
NONREP_PUB = dict(exe=dict(pub=f'{REPO}/experiments/02-harvest-repro/results/census-exe-ec2.jsonl',
                           pubdec=f'{REPO}/experiments/02-harvest-repro/data/pub-decision-exe.tsv'),
                  lib=dict(pub=f'{REPO}/experiments/06-library-census/results/census-lib.jsonl', pubdec=None))

GAPS = dict(
    rq1_rob_exact=['Input khớp không được lưu từng input: chỉ có bộ đếm match_tol_not_exact (khớp theo sai số tương đối, khác khi so chính '
                   'xác) và tối đa rq1.EXACT_SAMPLE mẫu mỗi (case, hệ) trong div/*.exact.jsonl, chỉ gồm state; divergence mới không có kiểm '
                   'ổn định và kết quả sanitizer riêng',
                   'Lần chạy lại kiểm ổn định của divergence không được lưu (chỉ cờ stable theo sai số tương đối), nên không biết divergence '
                   'giữ lại còn ổn định khi so chính xác'],
    rq1_rob_orig=['Như phân tích 4: input khớp không được lưu, nên divergence mới (mảng, trường optional so chính xác; NaN khác NaN) không '
                  'đếm được; input khớp có NaN hai bên không có bộ đếm nào',
                  'Lần chạy lại kiểm ổn định không được lưu, nên không biết divergence giữ lại còn ổn định theo luật oracle gốc',
                  'Kiểu trường state lấy từ runner/src/main.rs của corpus đã pin (harness.gen.libtypes.parse_runner), không có trong bản ghi'],
    nt_one_side=['Input một bên vượt ngân sách mà chạy lại thì khớp không có bộ đếm (nhánh khớp chỉ đếm c_status, r_status), nên không có '
                 'mẫu số "mọi input một bên vượt ngân sách"; chỉ báo được trên divergence'],
    div_by_input=['Executable: mẫu số theo nguồn (seed, random, dict, syntax, afl) cần inputs/*.inputs.jsonl.gz (F8); bản ghi case chỉ có '
                  'n_by_layer, nên thiếu file thì mẫu số theo nguồn là null'],
    attrition_inputs=['c_build_failed, harness_error, missing_seed, missing_record: không có bản ghi case dùng được ở seed đó (case không sinh '
                      'input), nên số input bị mất không xác định; báo số bản dịch không xác định',
                      'Hao hụt trước P_rep (build, timeout, unstable, non-reproduced) xảy ra trước harness: không có input sinh ra; số vector '
                      'của oracle gốc nằm ở census, không thuộc mục này'],
    rq2_rob=['Bản ghi RQ2 trước F5 (2026-10-25) không có obs: không tính lại được (đếm ở uncomputable.no_obs)',
             'Luật oracle gốc cần kiểu trường từ runner của corpus; vector có NaN hai bên trong state có trường chuỗi là không xác định '
             '(token NaN có thể đến từ chuỗi), đếm ở uncomputable.ambiguous_nonfinite'],
    nonrep_groups=['Gán nhóm bằng chứng là việc tay (Phụ lục A); không có file --nonrep-evidence thì số theo nhóm là null'])


def nd(num, den):
    return dict(num=num, den=den)


def group_of(bundle):
    return bundle.split('_')[0]


def by_gs(items, f, bundle_of, system_of, systems=True):
    """{nhóm: {'_all' | hệ: f(tập con)}}; nhóm 'all' gồm mọi phần tử (như gen-rq-macros._by_gs)."""
    groups = sorted({group_of(bundle_of(x)) for x in items}) + ['all']
    out = {}
    for g in groups:
        ga = [x for x in items if g == 'all' or group_of(bundle_of(x)) == g]
        d = {'_all': f(ga)}
        if systems:
            for s in sorted({system_of(x) for x in ga}): d[s] = f([x for x in ga if system_of(x) == s])
        out[g] = d
    return out


def _jsonl(p):
    if not p or not os.path.exists(p): return []
    with open_text(p) as f: return [json.loads(l) for l in f if l.strip()]


# ====================================================================================================================================
# Phép so số thực thay thế (library)
F32_EPS, F64_EPS = 2.0 ** -23, 2.0 ** -52     # f32::EPSILON, f64::EPSILON (default_max_relative của crate approx)
ORIG_ABS = 1e-6                               # TRACTOR 37960ee tools/cando2/src/approx_eq.rs dòng 10


def _f32(x):
    return struct.unpack('f', struct.pack('f', x))[0]


def approx_eq(a, b, bits):
    """approx 0.5.1 Relative::default().epsilon(1e-6).eq (relative_eq.rs) trong kiểu f32 hoặc f64: a == b; vô cực chỉ bằng chính nó;
    |a - b| <= 1e-6; hoặc |a - b| <= max(|a|, |b|) * EPSILON của kiểu. NaN khác mọi giá trị. f32: mỗi phép toán làm tròn về f32 (giá trị
    JSON do serde ghi từ f32 nên đổi về f32 là chính xác; hiệu hai f32 tính trong f64 rồi làm tròn, có thể lệch ở ca làm tròn kép rất hiếm)."""
    a, b = float(a), float(b)
    if bits == 32: a, b = _f32(a), _f32(b)
    if a == b: return True
    if math.isinf(a) or math.isinf(b) or math.isnan(a) or math.isnan(b): return False
    if bits == 32:
        d = _f32(abs(a - b))
        return d <= _f32(ORIG_ABS) or d <= _f32(max(abs(a), abs(b)) * F32_EPS)
    d = abs(a - b)
    return d <= ORIG_ABS or d <= max(abs(a), abs(b)) * F64_EPS


class Undecided(Exception):
    """Phép so thay thế không quyết định được từ bản ghi (kiểu trường không đọc được, token NaN có thể đến từ chuỗi)."""


def _text_leaf(ty):
    k = ty[0]
    if k in ('string', 'cstring', 'unsupported'): return True
    if k in ('vec', 'option', 'box', 'array'): return _text_leaf(ty[1])
    if k == 'struct': return any(_text_leaf(ft) for _, ft in ty[2])
    return False


def state_exact(a, b):
    """R21 "so chính xác": sai số 0 cho mọi số thực (như bộ đếm rq1.obs_note match_tol_not_exact), NaN vẫn bằng NaN."""
    return OB.float_tol_equal(a.get('state_out'), b.get('state_out'), rel=0) and a.get('state_nonfinite') == b.get('state_nonfinite')


def state_tol(a, b):
    """Luật chính (observe.channels_lib): sai số tương đối 1e-6, dãy giá trị không hữu hạn bằng nhau."""
    return OB.float_tol_equal(a.get('state_out'), b.get('state_out')) and a.get('state_nonfinite') == b.get('state_nonfinite')


def state_orig(a, b, fields):
    """Luật oracle gốc (TRACTOR 37960ee tools/cando2/src/lib.rs dòng 326-345, approx_eq.rs): trường cấp một có kiểu f32, f64 (kể cả
    c_float, c_double, std::any::type_name trả kiểu đã giải bí danh) so bằng approx_eq; mọi trường khác (mảng, Vec, Option, struct, số
    nguyên, chuỗi) so bằng PartialEq, tức số thực bên trong so chính xác và NaN khác NaN. fields: {tên: cây kiểu libtypes}; None thì không
    quyết định được. serde ghi NaN, inf, -inf thành null: dãy token state_nonfinite (thứ tự Debug, như observe) khác nhau thì khác; có NaN
    thì khác (NaN khác NaN ở cả hai cách so), trừ khi state có trường chuỗi (token có thể từ chuỗi): không quyết định được."""
    na, nb = a.get('state_nonfinite'), b.get('state_nonfinite')
    sa, sb = a.get('state_out'), b.get('state_out')
    if na != nb: return False
    if fields is None: raise Undecided('runner_types_unavailable')
    if na and 'NaN' in na:
        if any(_text_leaf(t) for t in fields.values()): raise Undecided('ambiguous_nonfinite')
        return False
    if sa is None or sb is None: return sa is None and sb is None
    if not (isinstance(sa, dict) and isinstance(sb, dict)): raise Undecided('state_not_object')
    if sa.keys() != sb.keys(): return False
    for k in sa:
        ty = fields.get(k)
        if ty is None or ty[0] == 'unsupported': raise Undecided('runner_types_unavailable')
        x, y = sa[k], sb[k]
        if ty[0] == 'float':
            if x is None or y is None:
                if x is None and y is None: continue          # cùng vị trí không hữu hạn, token bằng nhau, không có NaN: inf bằng inf
                return False
            if not approx_eq(x, y, ty[2]): return False
        elif not OB.float_tol_equal(x, y, rel=0):
            return False
    return True


def lib_channels(a, b, state_eq, completed_same=False):
    """Như observe.channels_lib (cùng thứ tự kênh, cùng luật hai bên cùng vượt ngân sách), với phép so state thay được. Kiểm bằng test:
    state_eq=state_tol cho đúng kết quả của observe.channels_lib."""
    if OB.lib_timeout(a) and OB.lib_timeout(b): return []
    enc = lambda x: (x or '').encode('utf-8', 'replace')
    res = lambda o: 'completed' if completed_same and o.get('k1') == 'reported' and o.get('result') in OB.COMPLETED else o.get('result')
    ch = []
    if (a.get('k1'), res(a)) != (b.get('k1'), res(b)): ch.append('status')
    if not state_eq(a, b): ch.append('state')
    if OB.norm(enc(a.get('stdout'))) != OB.norm(enc(b.get('stdout'))): ch.append('stdout')
    if OB.norm_err(enc(a.get('stderr'))) != OB.norm_err(enc(b.get('stderr'))): ch.append('stderr')
    return ch


def _lib_eq(state_eq):
    """Phép bằng library với state_eq thay thế; Undecided chỉ lan ra khi các kênh khác đều bằng (kênh khác đã khác thì quyết định là khác)."""
    def eq(a, b):
        try:
            return not lib_channels(a, b, state_eq)
        except Undecided:
            if lib_channels(a, b, lambda x, y: True): return False
            raise
    return eq


def eq_no_stderr(kind):
    """Phép so của số chính bỏ kênh stderr (executable: luật NT không đổi, hai bên cùng vượt ngân sách so prefix stdout)."""
    if kind == 'exe':
        return lambda a, b: OB.nt_prefix(a, b)[0] if OB.is_nt(a) and OB.is_nt(b) else not [c for c in OB.channels_exe(a, b) if c != 'stderr']
    return lambda a, b: not [c for c in OB.channels_lib(a, b) if c != 'stderr']


def rq2_eq(analysis, kind, fields=None):
    if analysis == 'no_stderr': return eq_no_stderr(kind)
    if kind != 'lib': raise ValueError(f'{analysis} chỉ áp cho library')
    if analysis == 'exact': return _lib_eq(state_exact)
    if analysis == 'orig_float': return _lib_eq(lambda a, b: state_orig(a, b, fields))
    raise ValueError(analysis)


@contextlib.contextmanager
def rq2_equal(fn):
    """Gán tạm rq2._equal (vector_outcome tra tên này lúc gọi) để tính lại đúng luật của rq2 với phép so khác; trả lại khi xong."""
    old = HQ._equal
    HQ._equal = lambda a, b, kind: fn(a, b)
    try: yield
    finally: HQ._equal = old


_FIELDS = {}


def runner_fields(bundle, case):
    """{tên trường: cây kiểu} của state runner library (corpus đã pin); None khi không đọc được."""
    k = (bundle, case)
    if k not in _FIELDS:
        try:
            from .gen.libtypes import parse_runner
            with open(f'{TRACTOR_TESTS}/{bundle}/{case}/runner/src/main.rs') as f: p = parse_runner(f.read())
            _FIELDS[k] = None if p.get('error') else {f: t for f, _, t in p['fields']}
        except OSError:
            _FIELDS[k] = None
    return _FIELDS[k]


# ====================================================================================================================================
# RQ1: bản dịch, bản ghi case, seed cần
def case_records(cases):
    """{(bundle, case, seed): bản ghi case}; như metrics.rq1_translations, bản chạy lại thành công thắng bản harness_error."""
    best = {}
    for r in cases:
        k = (r['bundle'], r['case'], r['seed'])
        if k not in best or (best[k].get('status') == 'harness_error' and r.get('status') != 'harness_error'): best[k] = r
    return best


def need_seeds(recs, bundle, case, seeds):
    """Seed metrics đòi cho bản dịch của case: case không đọc input chỉ seed INSENSITIVE_SEED (như metrics.rq1_translations)."""
    per = [recs[(bundle, case, sd)] for sd in seeds if (bundle, case, sd) in recs]
    return [INSENSITIVE_SEED] if any(r.get('input_insensitive') for r in per) and INSENSITIVE_SEED in seeds else list(seeds)


def n_exec(rec, kind):
    """Số input đã thực thi của một (case, seed) (sau bỏ ngoài miền và trùng); None khi bản ghi không có."""
    if rec is None or rec.get('n_inputs') is None: return None
    if kind == 'exe': return rec['n_inputs']
    return rec['n_inputs'] - sum((rec.get('out_of_domain_by_source') or {}).values())


def layer_counts(rec, kind):
    """{tầng: số input đã thực thi} của một (case, seed); None khi bản ghi không có."""
    if rec is None: return None
    if kind == 'exe':
        x = (rec.get('gen') or {}).get('n_by_layer')
        return dict(x) if x is not None else None
    if rec.get('n_by_source') is None: return None
    ood = rec.get('out_of_domain_by_source') or {}
    return {s: n - ood.get(s, 0) for s, n in rec['n_by_source'].items()}


def div_layer(d, kind):
    if kind == 'lib': return d.get('source')
    if d.get('layer'): return d['layer']
    return {'seed': 'S', 'afl': 'A'}.get(d.get('source'))           # bản ghi cũ không có layer: random, dict, syntax có ở cả M và MS


def _with_gen(c, kind):
    """Thêm khoá GEN: mọi tầng trừ vector gốc (executable S, library vector)."""
    if c is None: return None
    c = collections.Counter(c)
    c[GEN] = sum(n for L, n in c.items() if L not in ('S', 'vector', GEN))
    return c


class InputsCache:
    """Nguồn của từng input đã thực thi, đọc từ inputs/<bundle>__<case>__s<seed>.inputs.jsonl.gz (F8); None khi không có file."""

    def __init__(self, rq1dir): self.d, self.c = rq1dir, {}

    def sources(self, bundle, case, seed):
        k = (bundle, case, seed)
        if k not in self.c:
            p = f'{self.d}/inputs/{bundle}__{case}__s{seed}.inputs.jsonl.gz'
            self.c[k] = collections.Counter(r.get('source') for r in _jsonl(p)) if os.path.exists(p) else None
        return self.c[k]


def rq1_units(rq1dir, kind, seeds, expected=None):
    """Đơn vị cấp bản dịch cho các mục RQ1: mỗi bản dịch của metrics.rq1_translations (bỏ `unexpected`) kèm số liệu cần cho mọi mục."""
    cases, divs, caps = HM.load_rq1(rq1dir, kind)
    T = HM.rq1_translations(cases, divs, caps, seeds, expected)
    recs = case_records(cases)
    inp = InputsCache(rq1dir)
    units = []
    for (b, c, s), t in sorted(T.items()):
        if t.get('unexpected'): continue
        need = need_seeds(recs, b, c, seeds)
        u = dict(bundle=b, case=c, system=s, status=t['status'], in_S=bool(t.get('in_S')), need=need, P_test=t['status'] == 'P_test')
        # 5. hao hụt theo input
        sched = obs = 0; unknown = 0
        for sd in need:
            r = recs.get((b, c, sd))
            n = n_exec(r, kind) if r is not None and r.get('status') == 'done' else None
            if r is not None and r.get('status') == 'done' and r.get('input_fields') is False: n = 0       # library không có trường input
            if n is None: unknown += 1; continue
            sched += n
            obs += ((r.get('counts') or {}).get(s) or {}).get('observed', 0)
        u.update(sched=sched, observed=obs, unknown_seeds=unknown, san_unresolved=t['counts'].get('div_stable_san_infra', 0))
        if u['P_test']:
            ds = [d for sd in need for d in divs.get((b, c, s, sd), [])]
            ret = [d for d in ds if HM.retained(d)]
            u['divs'], u['ret'] = ds, ret
            # 3. mẫu số theo tầng, theo nguồn
            lay, src, src_missing, cs = collections.Counter(), collections.Counter(), 0, {}
            for sd in need:
                lc = layer_counts(recs.get((b, c, sd)), kind)
                if lc is None: lay = None; break
                lay.update(lc); cs[(b, c, sd)] = lc
                if kind == 'exe':
                    sc = inp.sources(b, c, sd)
                    if sc is None: src_missing += 1
                    else: src.update(sc)
            u.update(obs_layer=_with_gen(lay, kind), obs_source=None if (kind != 'exe' or src_missing) else src, case_seeds=cs)
        units.append(u)
    return units, cases, recs


# ------------------------------------------------------------------------------------------------------------------------------------
# 3. divergence theo tầng và nguồn (R24)
def _layers(kind):
    return (EXE_LAYERS if kind == 'exe' else LIB_LAYERS) + (GEN,)


def div_by_input(units, kind):
    pt = [u for u in units if u['P_test']]
    D = sum(u['in_S'] for u in pt)
    lay_known = all(u['obs_layer'] is not None for u in pt)
    obs = collections.Counter(); da, dr, tr = collections.Counter(), collections.Counter(), collections.Counter()
    inputs_ret, inputs_den = collections.defaultdict(set), {}
    so, sa, sr = collections.Counter(), collections.Counter(), collections.Counter()
    src_known = kind == 'exe' and all(u.get('obs_source') is not None for u in pt)
    no_layer = 0
    for u in pt:
        if u['obs_layer'] is not None: obs.update(u['obs_layer'])
        for k, lc in u['case_seeds'].items(): inputs_den[k] = _with_gen(lc, kind)
        seen = set()
        for d in u['divs']:
            L = div_layer(d, kind)
            if L is None: no_layer += 1; continue
            keys = [L] + ([GEN] if L not in ('S', 'vector') else [])
            for x in keys: da[x] += 1
            if kind == 'exe': sa[d.get('source')] += 1
            if not HM.retained(d): continue
            for x in keys:
                dr[x] += 1; seen.add(x)
                inputs_ret[x].add((d['bundle'], d['case'], d['seed'], d.get('idx')))
            if kind == 'exe': sr[d.get('source')] += 1
        if u.get('obs_source') is not None: so.update(u['obs_source'])
        for x in seen: tr[x] += u['in_S']
    den_in = collections.Counter()
    for lc in inputs_den.values(): den_in.update(lc)
    out = dict(unit='(input, bản dịch, seed) trên P_test; input phân biệt (case, seed, idx); bản dịch trong D', P_test=len(pt), D=D,
               divergences_without_layer=no_layer, layers={})
    for L in _layers(kind):
        o = obs[L] if lay_known else None
        out['layers'][L] = dict(div_retained=nd(dr[L], o), div_all=nd(da[L], o),
                                inputs_retained=nd(len(inputs_ret[L]), den_in[L] if lay_known else None), translations=nd(tr[L], D))
    if kind == 'exe':
        out['sources'] = {S: dict(div_retained=nd(sr[S], so[S] if src_known else None), div_all=nd(sa[S], so[S] if src_known else None))
                          for S in EXE_SOURCES}
    return out


# ------------------------------------------------------------------------------------------------------------------------------------
# 4. input ngoài miền
def out_of_domain(cases, kind, seeds):
    """Theo (case, seed) có sinh input; case C build lỗi, library không có trường input không sinh input nên không vào."""
    recs = [r for r in case_records(cases).values() if r.get('status') == 'done' and r['seed'] in seeds]

    def f(rs):
        ood, gen, no_field, used = collections.Counter(), collections.Counter(), 0, 0
        for r in rs:
            if kind == 'lib' and r.get('input_fields') is False: continue
            if kind == 'exe':
                g, o = (r.get('gen') or {}).get('n_gen_by_layer'), (r.get('gen') or {}).get('n_out_of_domain')
            else:
                g, o = r.get('n_by_source'), r.get('out_of_domain_by_source')
            if g is None or o is None: no_field += 1; continue
            used += 1; gen.update(g); ood.update(o)
        ok = no_field == 0
        gen, ood = _with_gen(gen, kind), _with_gen(ood, kind)
        return dict(unit='input của (case, seed), trước khi bỏ ngoài miền và trùng', case_seeds=used, case_seeds_without_field=no_field,
                    layers={L: nd(ood[L] if ok else None, gen[L] if ok else None) for L in _layers(kind)})
    return by_gs(recs, f, lambda r: r['bundle'], None, systems=False)


# ------------------------------------------------------------------------------------------------------------------------------------
# 5. hao hụt theo input
def attrition_inputs(units):
    codes = list(HM.LEAVE_ORDER) + ['P_test']
    codes += sorted({u['status'] for u in units} - set(codes))
    known = [u for u in units if not u['unknown_seeds']]
    out = dict(unit='input x bản dịch x seed cần; lên lịch = input đã thực thi của case', n_translations=len(units),
               inputs_scheduled_known=sum(u['sched'] for u in known), translations_inputs_unknown=len(units) - len(known), codes={})
    for c in codes:
        us = [u for u in units if u['status'] == c]
        unk = sum(bool(u['unknown_seeds']) for u in us)
        lost = sum(u['sched'] - u['observed'] for u in us if not u['unknown_seeds'])
        out['codes'][c] = dict(translations=nd(len(us), len(units)), inputs_lost=nd(None if unk else lost, out['inputs_scheduled_known']),
                               inputs_lost_known_part=lost, translations_inputs_unknown=unk)
    out['codes']['san_infra']['san_unresolved_divergences'] = sum(u['san_unresolved'] for u in units if u['status'] == 'san_infra')
    out['P_test_inputs_lost'] = sum(u['sched'] - u['observed'] for u in units if u['P_test'] and not u['unknown_seeds'])   # phải bằng 0
    return out


# ------------------------------------------------------------------------------------------------------------------------------------
# 6. NT một bên đã xác nhận (R23)
def _nt_side(d, kind):
    if kind == 'exe': return 'c' if d.get('c_to') else ('r' if d.get('r_to') else None)
    return 'c' if OB.lib_timeout(d.get('c') or {}) else ('r' if OB.lib_timeout(d.get('r') or {}) else None)


def nt_one_side(units, kind):
    pt = [u for u in units if u['P_test']]
    D = sum(u['in_S'] for u in pt)
    c = collections.Counter(); missing = 0; any_t = only_t = 0
    for u in pt:
        for d in u['divs']:
            if 'timeout_confirmed' not in d: missing += 1; continue
            r = HM.retained(d)
            c['div_all'] += 1; c['div_retained'] += r
            c['rerun_all'] += bool(d.get('timeout_rerun')); c['rerun_retained'] += r and bool(d.get('timeout_rerun'))
            if d['timeout_confirmed']:
                c['conf_all'] += 1; c['conf_retained'] += r
                if r: c[f"conf_retained_{_nt_side(d, kind) or 'unknown'}_nt"] += 1
        conf = [bool(d.get('timeout_confirmed')) for d in u['ret']]
        if u['in_S'] and any(conf): any_t += 1
        if u['in_S'] and conf and all(conf): only_t += 1
    ok = missing == 0
    v = lambda x: c[x] if ok else None
    return dict(unit='divergence (input, bản dịch, seed) trên P_test; bản dịch trong D', records_without_field=missing,
                confirmed_retained=nd(v('conf_retained'), v('div_retained')), confirmed_all=nd(v('conf_all'), v('div_all')),
                confirmed_retained_by_side={x: nd(v(f'conf_retained_{x}_nt'), v('conf_retained')) for x in ('c', 'r', 'unknown')},
                rerun_retained=nd(v('rerun_retained'), v('div_retained')), rerun_all=nd(v('rerun_all'), v('div_all')),
                translations_any=nd(any_t if ok else None, D), translations_only=nd(only_t if ok else None, D))


# ------------------------------------------------------------------------------------------------------------------------------------
# 1. robustness analyses 4 và 5 (library)
def rq1_rob_float(units, fields_fn=runner_fields):
    pt = [u for u in units if u['P_test']]
    D = sum(u['in_S'] for u in pt)
    n_ret = removed = undecided = 0; all_removed = 0; undec_reasons = collections.Counter()
    for u in pt:
        flags = []
        fields = fields_fn(u['bundle'], u['case'])
        for d in u['ret']:
            n_ret += 1
            try:
                rm = not lib_channels(d['c'], d['r'], lambda a, b: state_orig(a, b, fields), completed_same=True)
            except Undecided as e:
                rm = None
                if not lib_channels(d['c'], d['r'], lambda a, b: True, completed_same=True): undecided += 1; undec_reasons[str(e)] += 1
                else: rm = False
            removed += rm is True
            flags.append(rm)
        if u['in_S'] and flags and all(f is True for f in flags): all_removed += 1
    ok = undecided == 0
    return dict(
        exact=dict(D=nd(None, len(pt)), computable=False, missing='meta.gaps.rq1_rob_exact',
                   removed_div_by_comparison=nd(0, n_ret),
                   note='so chính xác chặt hơn sai số tương đối: không divergence giữ lại nào thành bằng nhau; phần đổi qua kiểm ổn định và '
                        'divergence mới không tính được'),
        orig_float=dict(D=nd(None, len(pt)), computable=False, missing='meta.gaps.rq1_rob_orig',
                        removed_div=nd(removed if ok else None, n_ret), undecided_div=undecided, undecided_reasons=dict(undec_reasons),
                        all_removed_translations=nd(all_removed if ok else None, D),
                        note='removed_div: divergence giữ lại mà hai quan sát bằng nhau theo luật oracle gốc (bỏ chắc chắn); '
                             'all_removed_translations: bản trong D mất mọi divergence giữ lại của số chính, chưa tính divergence mới'))


# ====================================================================================================================================
# 2. RQ2
def _rq2_ident(r):
    if r.get('bundle') and r.get('system'): return r['bundle'], r['system']
    s, b = r['key'].split('#')[0].split('/')[:2]
    return b, s


def rq2_recompute(r, kind, analysis, fields_fn=runner_fields):
    """(kết quả mới, None) hoặc (None, lý do không tính được) cho một bản ghi bản dịch RQ2."""
    vs = r.get('vectors') or []
    if any(v.get('runs') and not v.get('obs') for v in vs): return None, 'no_obs'
    fields = fields_fn(r['bundle'], r['case']) if analysis == 'orig_float' else None
    eq = rq2_eq(analysis, kind, fields) if analysis != 'primary' else None
    outs = []
    try:
        with (rq2_equal(eq) if eq else contextlib.nullcontext()):
            for v in vs: outs.append(HQ.recompute_vector(v, kind))
    except Undecided as e:
        return None, str(e)
    return HQ.translation_outcome(outs)[0], None


def rq2_rob(recs, kind, fields_fn=runner_fields):
    """Thêm `_rob` vào mỗi bản ghi thuộc R_test của số chính; trả về hàm gộp cho by_gs."""
    rt = [r for r in recs if r.get('outcome') in R_TEST]
    for r in rt:
        r['_rob'] = {a: rq2_recompute(r, kind, a, fields_fn) for a in ('primary',) + RQ2_ANALYSES[kind]}

    def f(rs):
        rs = [r for r in rs if r.get('outcome') in R_TEST]
        n = len(rs)
        prim = collections.Counter(r['_rob']['primary'][0] == r['outcome'] if r['_rob']['primary'][1] is None else 'uncomputable' for r in rs)
        out = dict(R_test=n, F_primary=sum(r['outcome'] == 'behavioral_agreement' for r in rs),
                   primary_recompute=dict(same=prim[True], differs=prim[False], uncomputable=prim['uncomputable']))
        for a in RQ2_ANALYSES[kind]:
            res = [r['_rob'][a] for r in rs]
            unc = collections.Counter(why for o, why in res if why)
            ok = not unc
            cnt = collections.Counter(o for o, why in res if not why)
            tr = collections.Counter(f"{r['outcome']}->{r['_rob'][a][0]}" for r in rs if not r['_rob'][a][1] and r['_rob'][a][0] != r['outcome'])
            v = lambda x: cnt[x] if ok else None
            out[a] = dict(F=nd(v('behavioral_agreement'), n), A=nd(v('behavioral_disagreement'), n),
                          not_adjudicable=nd(v('not_adjudicable'), n), not_re_examined=nd(v('not_re_examined'), n),
                          changed=nd(sum(tr.values()) if ok else None, n), transitions=dict(tr), uncomputable=dict(unc), computable=ok)
        return out
    return f


# ====================================================================================================================================
# 7. non-reproduced decision
def nonrep_population(kind, pilot=False, src=None):
    """Danh sách non-reproduced decision hai phía từ census, cùng luật gen-rq-macros.census_counts (kiểm chéo ở tests/test_analysis.py).
    Phía chấp nhận: P_acc \\ P_rep không thuộc unstable (kiểm lại đỗ mà không ổn định), build (không build và kiểm lại không cứu), timeout
    (chỉ trượt vì Timeout). Phía từ chối: R_0^test build được và tái lập đỗ (ours_passed True trên census mà RQ2 dùng)."""
    from . import pairs as PR
    s = dict(NONREP_PUB[kind], prep=PR.DEFAULT[kind]['census'], recheck=PR.DEFAULT[kind]['recheck'], rrun=HQ.CENSUS[kind][0])
    s.update(src or {})
    miss = [p for p in s.values() if p and not os.path.exists(p)]
    if miss: raise OSError(f'thiếu {miss}')
    key = lambda r: (r['bundle'], r['tractor_case'], r['system'])
    scope = lambda rows: [dict(r, pilot=False) for r in rows if r['pilot']] if pilot else [r for r in rows if not r['pilot']]
    pub, prep_rows = scope(PR.load(s['pub'])), scope(PR.load(s['prep']))
    prep_by = {key(r): r for r in prep_rows}
    rrun = {key(r): r for r in scope(PR.load(s['rrun']))}
    recheck = {key(r): r for r in PR.load(s['recheck'])}
    err = {}
    if s.get('pubdec'):
        with open(s['pubdec']) as f: err = {key(r): r['error'] for r in csv.DictReader(f, delimiter='\t')}
    prep = {key(r) for r in PR.p_rep(prep_rows, list(recheck.values()))}
    out = []
    for r in pub:
        k = key(r)
        if r.get('stage') == 'P0_missing_artifact': continue
        if r.get('pub_passed') is True:
            if k in prep: continue
            rk, rp = recheck.get(k) or {}, prep_by.get(k, r)
            res = set(rp.get('results') or {}) - {'Pass', 'Skip'}
            if rk.get('ours_passed') and not rk.get('stable', True): continue
            if not rp.get('build_ok') and not rk.get('ours_passed'): continue
            if res == {'Timeout'}: continue
            out.append(dict(bundle=r['bundle'], case=r['tractor_case'], system=r['system'], path='accepted'))
        else:
            e = err.get(k) if kind == 'exe' else r.get('pub_error')
            if e != 'test failed': continue
            rr = rrun.get(k, r)
            if rr.get('build_ok') and rr.get('ours_passed') is True:
                out.append(dict(bundle=r['bundle'], case=r['tractor_case'], system=r['system'], path='rejected'))
    return out


def load_evidence(path, kind):
    """{(path, bundle, case, system): (nhóm, nguồn)} từ JSONL; báo lỗi khi nhóm lạ, chiều không hợp lệ, hoặc một cặp hai nhóm."""
    out = {}
    with open_text(path) as f:
        for n, line in enumerate(f, 1):
            if not line.strip(): continue
            d = json.loads(line)
            if d.get('kind') != kind: continue
            miss = [x for x in ('path', 'bundle', 'case', 'system', 'group') if not d.get(x)]
            if miss: raise ValueError(f'{path}:{n}: thiếu {miss}')
            if d['path'] not in NONREP_ALLOWED: raise ValueError(f"{path}:{n}: path lạ {d['path']!r}")
            if d['group'] not in NONREP_ALLOWED[d['path']]:
                raise ValueError(f"{path}:{n}: nhóm {d['group']!r} không áp cho phía {d['path']} (NONREP_ALLOWED)")
            k = (d['path'], d['bundle'], d['case'], d['system'])
            if k in out and out[k][0] != d['group']: raise ValueError(f'{path}:{n}: {k} có hai nhóm')
            out[k] = (d['group'], d.get('source'))
    return out


def nonrep_groups(pop, evidence, unclassified='missing'):
    """Gắn nhóm cho từng phần tử của pop (sửa tại chỗ) và trả về (hàm gộp, các dòng evidence không khớp phần tử nào)."""
    keys = set()
    for p in pop:
        k = (p['path'], p['bundle'], p['case'], p['system']); keys.add(k)
        p['group'] = (evidence or {}).get(k, (None,))[0]
    unmatched = sorted('/'.join(k) for k in (evidence or {}) if k not in keys)

    def f(ps):
        out = {}
        for path in ('accepted', 'rejected'):
            xs = [p for p in ps if p['path'] == path]
            unc = sum(p['group'] is None for p in xs)
            cnt = collections.Counter(p['group'] for p in xs if p['group'])
            if unclassified == 'unknown' and evidence is not None: cnt['unknown'] += unc
            complete = evidence is not None and (unc == 0 or unclassified == 'unknown')
            out[path] = dict(population=len(xs), unclassified=nd(unc, len(xs)), complete=complete,
                             groups={g: nd(cnt[g] if complete else None, len(xs)) for g in NONREP_ALLOWED[path]})
        return out
    return f, unmatched


# ====================================================================================================================================
def git_rev(d):
    try: return subprocess.run(['git', '-C', d, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() or None
    except OSError: return None


def analyse(rq1dir, kind, rq2dir=None, seeds=(0, 1, 2), expect=None, evidence_path=None, unclassified='missing', fields_fn=runner_fields,
            nonrep_src=None):
    seeds = list(seeds)
    exp = None
    if expect == 'pilot':
        from .rq1 import pilot_pairs; exp = pilot_pairs(kind)
    elif expect == 'p_rep':
        from .pairs import prep_pairs; exp = prep_pairs(kind)
    units, cases, _ = rq1_units(rq1dir, kind, seeds, exp)
    bo, so = (lambda u: u['bundle']), (lambda u: u['system'])
    sec = dict(div_by_input=by_gs(units, lambda us: div_by_input(us, kind), bo, so),
               out_of_domain=out_of_domain(cases, kind, seeds),
               attrition_inputs=by_gs(units, attrition_inputs, bo, so),
               nt_one_side=by_gs(units, lambda us: nt_one_side(us, kind), bo, so))
    if kind == 'lib': sec['rq1_rob_float'] = by_gs(units, lambda us: rq1_rob_float(us, fields_fn), bo, so)
    meta = dict(kind=kind, rq1=os.path.abspath(rq1dir), rq2=os.path.abspath(rq2dir) if rq2dir else None, seeds=seeds, expect=expect,
                pilot=expect == 'pilot', harness_commit=git_rev(REPO), gaps=GAPS, nonrep_allowed=NONREP_ALLOWED,
                tractor_commit_expected=TRACTOR_COMMIT, tractor_commit_found=git_rev(os.path.dirname(TRACTOR_TESTS)),
                n_case_records=len(cases), n_translations=len(units))
    warn = []
    if meta['tractor_commit_found'] != TRACTOR_COMMIT:
        warn.append(f"corpus TRACTOR ở {meta['tractor_commit_found']} khác {TRACTOR_COMMIT}: kiểu trường state (luật oracle gốc) có thể lệch")
    if rq2dir:
        recs = _jsonl(f'{rq2dir}/rq2-{kind}.jsonl')
        if recs:
            f = rq2_rob(recs, kind, fields_fn)
            sec['rq2_rob'] = by_gs(recs, f, lambda r: _rq2_ident(r)[0], lambda r: _rq2_ident(r)[1])
            meta['n_rq2_records'] = len(recs)
            for r in recs: r.pop('_rob', None)
    try:
        pop = nonrep_population(kind, pilot=expect == 'pilot', src=nonrep_src)
    except OSError as e:
        pop = None; warn.append(f'non-reproduced: không đọc được census ({e}); mục nonrep_groups vắng')
    if pop is not None:
        ev = load_evidence(evidence_path, kind) if evidence_path else None
        f, unmatched = nonrep_groups(pop, ev, unclassified)
        sec['nonrep_groups'] = by_gs(pop, f, lambda p: p['bundle'], lambda p: p['system'])
        meta.update(nonrep_evidence=os.path.abspath(evidence_path) if evidence_path else None, nonrep_unclassified=unclassified,
                    nonrep_unmatched=unmatched)
        if unmatched: warn.append(f'evidence không khớp non-reproduced decision nào: {unmatched[:5]}')
    meta['warnings'] = warn
    return dict(meta=meta, kind=kind, sections=sec)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness.analysis', description=__doc__.split('\n')[0])
    ap.add_argument('--rq1', required=True); ap.add_argument('--kind', choices=['exe', 'lib'], required=True)
    ap.add_argument('--rq2'); ap.add_argument('--out', required=True); ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--expect', choices=['pilot', 'p_rep'], help='như harness.metrics --expect (pilot: tập non-reproduced cũng là pilot)')
    ap.add_argument('--nonrep-evidence', metavar='F', help='JSONL nhóm bằng chứng của non-reproduced decision (mục 7)')
    ap.add_argument('--nonrep-unclassified', choices=['missing', 'unknown'], default='missing',
                    help='cặp không có trong evidence: missing (số theo nhóm null) hoặc unknown (tính vào nhóm chưa rõ)')
    a = ap.parse_args(argv)
    gen_dir = os.path.realpath(f'{REPO}/writing/generated')
    if a.expect == 'pilot' and os.path.realpath(a.out).startswith(gen_dir + os.sep):
        raise SystemExit('số pilot không được ghi vào writing/generated/ (R6)')
    res = analyse(a.rq1, a.kind, a.rq2, [int(x) for x in a.seeds.split(',')], a.expect, a.nonrep_evidence, a.nonrep_unclassified)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    with open(a.out, 'w') as f: json.dump(res, f, indent=1, ensure_ascii=False, sort_keys=True)
    print(f'Đã ghi {a.out}', file=sys.stderr)
    for w in res['meta']['warnings']: print('CẢNH BÁO: ' + w, file=sys.stderr)


if __name__ == '__main__':
    main()
