#!/usr/bin/env python3
"""Sinh writing/generated/rq-numbers.tex: mọi đại lượng Chương 4 báo cho RQ1, RQ2, RQ3, độ nhạy B/N/U và các robustness analyses
(§3.6 `writing/chapters/03-methodology.tex`; `docs/proposal/reporting-rules.md` R1-R29). Mỗi đại lượng có macro tử số (Num) và mẫu số
(Den); đại lượng là tỉ lệ có thêm Pct (phần trăm, một chữ số thập phân, không kèm dấu %). Thiếu nguồn thì in ?? để build lộ ra; mẫu số 0
thì Pct là n/a. Không sửa tay file sinh ra. Bảng tra cứu macro, nguồn và câu hỏi mở: docs/proposal/rq-macro-map.md.

Hai chế độ:
  split: python3 writing/scripts/gen-rq-macros.py split --rq1 <thư mục rq1> --rq2 <thư mục rq2> --seeds 0,1,2 --expect p_rep -o <file>
    Tách số đếm theo (nhóm, hệ) và theo từng seed bằng chính các hàm của harness/metrics.py (rq1_translations, _group_counts,
    summarize_rq2) trên tập con; không đổi luật tính. Cần vì summary của harness.metrics chỉ có cấp nhóm cho RQ1 và chỉ có tổng cho RQ2,
    trong khi §3.6 đòi mọi đại lượng theo hệ. Hàng '_all' của mỗi nhóm phải trùng summary của harness.metrics (kiểm ở chế độ sinh macro).
  sinh macro (mặc định): python3 writing/scripts/gen-rq-macros.py [--in <thư mục>] [--out <file>] [--harness-root <dir>] [--pilot]
    <thư mục> chứa metrics.json (đầu ra `python3 -m harness.metrics --rq1 ... --rq2 ... --expect p_rep [--v6-causes F]`),
    metrics-split.json (đầu ra chế độ split) và analysis-exe.json, analysis-lib.json (đầu ra `python3 -m harness.analysis --kind K`:
    robustness 4, 5 RQ1 và ba robustness RQ2, R23 NT một bên, R24 theo tầng và nguồn, input ngoài miền, hao hụt theo input, nhóm bằng
    chứng non-reproduced). Thiếu file nào thì họ macro tương ứng là ??. Không có --in: mọi số đo được là ??, chỉ số census có giá trị.
    Census và phễu đọc từ các file Chương 3 dùng (đường dẫn lấy từ harness/ ở --harness-root để không lệch nguồn):
      - quyết định công bố: census-exe-ec2.jsonl + data/pub-decision-exe.tsv (executable), census-lib.jsonl (library), như
        gen-census-macros.py và gen-population-table.py;
      - P_rep: harness.pairs.DEFAULT (census + file kiểm lại; library theo HARNESS_P_REP_LIB_CENSUS nếu job đặt);
      - R_run: harness.rq2.CENSUS (luật của rq2.r_run).
    --pilot: population là case pilot (R6, báo riêng), cờ pilot đảo như harness.rq1.pilot_pairs. Không được ghi vào writing/generated/.

Quy ước tên: \\<prefix><Họ><Kind><Nhóm>[<Hệ>]<Num|Den|Pct>, ví dụ \\rqFPExeAllNum, \\rqFFLibBOneKiroPct. Kind: Exe, Lib. Nhóm: All, BOne,
BTwo, PZero, POne. Hệ: SYS_TOK. Họ: FAMILIES. Mã động (luật B/N/U, trạng thái kết thúc, mã lý do) đổi sang chữ bằng tok()."""
import argparse, collections, csv, hashlib, json, os, re, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = f'{ROOT}/writing/generated/rq-numbers.tex'
KINDS = ('exe', 'lib')
KIND_TOK = dict(exe='Exe', lib='Lib')
GROUPS = ('all', 'B01', 'B02', 'P00', 'P01')
GROUP_TOK = {'all': 'All', 'B01': 'BOne', 'B02': 'BTwo', 'P00': 'PZero', 'P01': 'POne'}
# Thứ tự và tên hiển thị như gen-population-table.py (Bảng 3.1)
SYSTEMS = ('kiro', 'claude', 'codex-gpt54', 'c2rust', 'laertes', 'c2saferrust', 'smartc2rust', 'kimi', 'gpt-5.4', 'gemini-3.1-pro-preview')
SYS_TOK = {'kiro': 'Kiro', 'claude': 'Claude', 'codex-gpt54': 'Codex', 'c2rust': 'CTwoRust', 'laertes': 'Laertes',
           'c2saferrust': 'CTwoSaferRust', 'smartc2rust': 'SmartCTwoRust', 'kimi': 'Kimi', 'gpt-5.4': 'GptFive',
           'gemini-3.1-pro-preview': 'Gemini'}
SEEDS = (0, 1, 2)
SEED_TOK = {0: 'Zero', 1: 'One', 2: 'Two'}
# Danh sách cố định để tên macro không phụ thuộc dữ liệu; mã lạ trong dữ liệu vẫn sinh macro (kèm cảnh báo).
EXE_STATUS = ('exit', 'signal', 'timeout', 'output_limit', 'mem_limit', 'invalid_input')          # observe.run_exe
LIB_STATUS = ('Pass', 'VectorComparisonFailed', 'Panic', 'SegmentationFault', 'UnknownFailure', 'Timeout', 'OutputLimit', 'MemLimit',
              'infra', 'invalid_input')                                                          # runner TRACTOR, observe._run_lib
FF_CHANNELS = ('stderr', 'stdout', 'state_float', 'state_other', 'state', 'result:Panic', 'result:SegmentationFault',
               'result:UnknownFailure', 'result:Timeout')                                        # metrics.ff_channels
PRE_REP_CAUSES = ('build', 'timeout', 'unstable', 'non_reproduced')
R0_TEST_PARTS = ('R_run', 'R_nonrep', 'R_nobuild', 'R_other')
LEAVE_CODES_FALLBACK = ('no_input_fields', 'c_build_failed', 'rust_build_failed', 'harness_error', 'no_inputs', 'incomplete',
                        'san_infra', 'missing_seed', 'missing_record')
DIGIT = 'Zero One Two Three Four Five Six Seven Eight Nine'.split()


def tok(s):
    """Mã bất kỳ -> chuỗi chỉ gồm chữ cái, CamelCase; chữ số đổi thành từ (B1-whitespace -> BOneWhitespace)."""
    out = ''
    for p in re.split(r'[^A-Za-z0-9]+', str(s)):
        if not p: continue
        p = ''.join(DIGIT[int(ch)] if ch.isdigit() else ch for ch in p)
        out += p[0].upper() + p[1:]
    return out or 'None'


def sha(p):
    try: return hashlib.sha256(open(p, 'rb').read()).hexdigest()
    except OSError: return None


def git_rev(d):
    try: return subprocess.run(['git', '-C', d, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() or '?'
    except OSError: return '?'


def group_of(bundle):
    return bundle.split('_')[0]


def load_harness(hroot):
    sys.path.insert(0, hroot)
    import harness.metrics as HM, harness.pairs as HP, harness.rq2 as HQ
    return HM, HP, HQ


# ---------------------------------------------------------------- chế độ split
def _by_gs(items, f, key_bundle, key_system):
    """{nhóm: {'_all' | hệ: f(tập con)}}; nhóm 'all' gồm mọi bản."""
    groups = sorted({group_of(key_bundle(x)) for x in items}) + ['all']
    out = {}
    for g in groups:
        ga = [x for x in items if g == 'all' or group_of(key_bundle(x)) == g]
        d = {'_all': f(ga)}
        for s in sorted({key_system(x) for x in ga}):
            d[s] = f([x for x in ga if key_system(x) == s])
        out[g] = d
    return out


def _rq2_ident(r):
    """(bundle, system) của bản ghi RQ2; bản ghi harness_error chỉ có key 'system/bundle/case#error'."""
    if r.get('bundle') and r.get('system'): return r['bundle'], r['system']
    s, b = r['key'].split('#')[0].split('/')[:2]
    return b, s


def split(a):
    HM, HP, HQ = load_harness(os.path.abspath(a.harness_root))
    seeds = [int(x) for x in a.seeds.split(',')]
    res = dict(meta=dict(seeds=seeds, expect=a.expect, rq1=a.rq1, rq2=a.rq2, harness_commit=git_rev(a.harness_root),
                         pilot=a.expect == 'pilot'), rq1={}, rq1_seed={}, rq2={})
    drop = ('ub_R22_by_pair',)
    brief = ('n_translations', 'P_test', 'D_all', 'leave', 'leave_other', 'funnel_ok')
    for kind in KINDS:
        if not a.rq1: break
        cases, divs, caps = HM.load_rq1(a.rq1, kind)
        exp = None
        if a.expect == 'pilot':
            from harness.rq1 import pilot_pairs; exp = pilot_pairs(kind)
        elif a.expect == 'p_rep':
            exp = HP.prep_pairs(kind)
        if not (cases or exp): continue
        T = HM.rq1_translations(cases, divs, caps, seeds, exp)
        gc = lambda ts: {k: v for k, v in HM._group_counts(ts, kind).items() if k not in drop}
        res['rq1'][kind] = _by_gs(list(T.values()), gc, lambda t: t['bundle'], lambda t: t['system'])
        if a.no_seed_split: continue
        res['rq1_seed'][kind] = {}
        for sd in seeds:          # biến thiên giữa các seed (R4, R5): từng seed một, mẫu số P_test của chính seed đó
            Tk = HM.rq1_translations(cases, divs, caps, [sd], exp)
            gb = lambda ts: {k: v for k, v in HM._group_counts(ts, kind).items() if k in brief}
            res['rq1_seed'][kind][str(sd)] = _by_gs(list(Tk.values()), gb, lambda t: t['bundle'], lambda t: t['system'])
    for kind in KINDS:
        if not a.rq2: break
        recs = HM._jsonl(f'{a.rq2}/rq2-{kind}.jsonl')
        if not recs: continue
        res['rq2'][kind] = _by_gs(recs, HM.summarize_rq2, lambda r: _rq2_ident(r)[0], lambda r: _rq2_ident(r)[1])
    os.makedirs(os.path.dirname(os.path.abspath(a.o)), exist_ok=True)
    json.dump(res, open(a.o, 'w'), indent=1, ensure_ascii=False, sort_keys=True)
    print(f'Đã ghi {a.o}', file=sys.stderr)


# ---------------------------------------------------------------- census và phễu
def census_counts(hroot, pilot):
    """{kind: {(nhóm, hệ): Counter}} với nhóm/hệ '_all' là tổng; None cho kind không đọc được nguồn.
    Trường: P0, P_acc, M, R0_build, R0_test, phần của R0_test (R_run, R_nonrep, R_nobuild, R_other), P_rep, nguyên nhân P_acc \\ P_rep."""
    HM, HP, HQ = load_harness(hroot)
    src = dict(exe=dict(pub=f'{hroot}/experiments/02-harvest-repro/results/census-exe-ec2.jsonl',
                        pubdec=f'{hroot}/experiments/02-harvest-repro/data/pub-decision-exe.tsv',
                        prep=HP.DEFAULT['exe']['census'], recheck=HP.DEFAULT['exe']['recheck'], rrun=HQ.CENSUS['exe'][0]),
               lib=dict(pub=f'{hroot}/experiments/06-library-census/results/census-lib.jsonl', pubdec=None,
                        prep=HP.DEFAULT['lib']['census'], recheck=HP.DEFAULT['lib']['recheck'], rrun=HQ.CENSUS['lib'][0]))
    out, files = {}, []
    for kind, s in src.items():
        files += [p for p in s.values() if p]
        key = lambda r: (r['bundle'], r['tractor_case'], r['system'])
        try:
            miss = [p for p in s.values() if p and not os.path.exists(p)]
            if miss: raise OSError(f'thiếu {miss}')        # HP.load trả [] khi thiếu file: phải chặn, nếu không P_rep thành 0
            scope = lambda rows: [dict(r, pilot=False) for r in rows if r['pilot']] if pilot else [r for r in rows if not r['pilot']]
            pub = scope(HP.load(s['pub']))
            prep_rows = scope(HP.load(s['prep']))
            prep_by = {key(r): r for r in prep_rows}
            rrun_rows = {key(r): r for r in scope(HP.load(s['rrun']))}
            recheck = {key(r): r for r in HP.load(s['recheck'])}
            err = {}
            if s['pubdec']:
                err = {key(r): r['error'] for r in csv.DictReader(open(s['pubdec']), delimiter='\t')}
        except (OSError, TypeError, KeyError) as e:
            print(f'census {kind}: không đọc được nguồn ({e}); số census là ??', file=sys.stderr); out[kind] = None; continue
        prep = {key(r) for r in HP.p_rep(prep_rows, list(recheck.values()))}
        C = collections.defaultdict(collections.Counter)
        for r in pub:
            k = key(r)
            f = collections.Counter(P0=1)
            if r.get('stage') == 'P0_missing_artifact': f['M'] += 1
            elif r.get('pub_passed') is True:
                f['P_acc'] += 1
                if k in prep: f['P_rep'] += 1
                else:
                    rk = recheck.get(k) or {}
                    rp = prep_by.get(k, r)                    # census mà P_rep dùng
                    res = set(rp.get('results') or {}) - {'Pass', 'Skip'}
                    # nguyên nhân hao hụt trước P_rep theo §3.2 đoạn Attrition (định nghĩa ở rq-macro-map.md, câu hỏi mở Q-A1)
                    if rk.get('ours_passed') and not rk.get('stable', True): f['pre_unstable'] += 1
                    elif not rp.get('build_ok') and not rk.get('ours_passed'): f['pre_build'] += 1
                    elif res == {'Timeout'}: f['pre_timeout'] += 1
                    else: f['pre_non_reproduced'] += 1
            else:
                e = err.get(k) if kind == 'exe' else r.get('pub_error')
                if e == 'build failed': f['R0_build'] += 1
                elif e == 'test failed':
                    f['R0_test'] += 1
                    rr = rrun_rows.get(k, r)                 # luật harness.rq2.r_run trên census mà RQ2 dùng
                    if rr.get('build_ok') and rr.get('ours_passed') is False: f['R_run'] += 1
                    elif rr.get('build_ok') and rr.get('ours_passed') is True: f['R_nonrep'] += 1
                    elif not rr.get('build_ok'): f['R_nobuild'] += 1
                    else: f['R_other'] += 1
                else: raise SystemExit(f'census {kind}: giai đoạn từ chối không nhận diện {k} {e!r}')
            for g in (group_of(r['bundle']), 'all'):
                for sy in (r['system'], '_all'):
                    C[(g, sy)].update(f)
        out[kind] = C
    return out, sorted(set(files))


# ---------------------------------------------------------------- truy cập số đếm
class Zero(dict):
    """Tập rỗng hợp lệ (census nói nhóm hoặc hệ không có bản dịch nào): mọi trường vắng là 0."""


def dig(d, path):
    """path: chuỗi 'a.b' hoặc tuple khoá (tên hệ có dấu chấm, ví dụ gpt-5.4, phải dùng tuple). Trả None khi thiếu nguồn hoặc trường vô
    hướng vắng (schema cũ); 0 khi d là Zero."""
    if d is None: return None
    cur = d
    for p in (path.split('.') if isinstance(path, str) else path):
        if isinstance(cur, dict) and p in cur: cur = cur[p]
        elif isinstance(cur, Zero): return 0
        else: return None
    return cur


def cnt(d, path, key):
    """Phần tử của bộ đếm dạng dict (seeds_detect, c_status, ...): bộ đếm có mà khoá vắng là 0."""
    c = dig(d, path)
    if c is None: return None
    if isinstance(c, (int, float)) and not isinstance(c, bool): return 0 if isinstance(d, Zero) else None
    return c.get(key, 0) if isinstance(c, dict) else None


def add(*xs):
    return None if any(x is None for x in xs) else sum(xs)


def sub(a, *bs):
    return None if a is None or any(b is None for b in bs) else a - sum(bs)


class Ctx:
    """Số đếm cho một (kind, nhóm, hệ); hệ None là mọi hệ."""

    def __init__(self, D, kind, g, s):
        self.D, self.kind, self.g, self.s = D, kind, g, s
        sk = s or '_all'
        cz = (D.census.get(kind) or {}) if D.census.get(kind) is not None else None
        self.cen = None if cz is None else cz.get((g, sk), collections.Counter())
        empty_rep = self.cen is not None and self.cen['P_rep'] == 0
        empty_run = self.cen is not None and self.cen['R_run'] == 0
        if s is None: r1 = dig(D.metrics, f'rq1_{kind}.by_group.{g}')
        else: r1 = dig(D.split_ok.get(('rq1', kind)), (g, s))
        self.r1 = r1 if r1 is not None else (Zero() if empty_rep and self._has('rq1', kind, s) else None)
        if s is None and g == 'all': r2 = dig(D.metrics, f'rq2_{kind}')
        else: r2 = dig(D.split_ok.get(('rq2', kind)), (g, sk))
        self.r2 = r2 if r2 is not None else (Zero() if empty_run and self._has('rq2', kind, s) else None)
        self.seed = {}
        for sd in SEEDS:
            x = dig(D.split_ok.get(('rq1_seed', kind)), (str(sd), g, sk))
            self.seed[sd] = x if x is not None else (Zero() if empty_rep and D.split_ok.get(('rq1_seed', kind)) else None)
        v6 = dig(D.metrics, f'rq1_{kind}.v6_separation.by_group.{g}')
        if v6 is not None and s is not None:
            v6 = {p: dig(v6, ('by_system', s, p)) for p in ('separated', 'rest')}
            if all(x is None for x in v6.values()): v6 = None   # hệ không có bản dịch nào ở P_rep: để dòng dưới gán Zero khi empty_rep
        if v6 is None and empty_rep and dig(D.metrics, f'rq1_{kind}.v6_separation') is not None: v6 = Zero()
        self.v6 = v6

    def _has(self, which, kind, s):
        """Nguồn của tầng này có mặt (để phân biệt 'tập rỗng' với 'thiếu nguồn')."""
        if s is not None: return self.D.split_ok.get((which, kind)) is not None
        return dig(self.D.metrics, f'{which}_{kind}') is not None

    def c(self, f):
        return None if self.cen is None else self.cen[f]

    def q1(self, p): return dig(self.r1, p)
    def q2(self, p): return dig(self.r2, p)
    def k1(self, p, k): return cnt(self.r1, p, k)
    def k2(self, p, k): return cnt(self.r2, p, k)

    # đại lượng dẫn xuất dùng chung
    def P_test(self): return self.q1('P_test')
    def D_all(self): return self.q1('D_all')
    def L_P(self): return sub(self.c('P_acc'), self.P_test())
    def F(self): return self.q2('F')
    def L_R(self): return sub(self.c('R0_test'), self.q2('A'), self.q2('F'))
    def R_run_rec(self): return add(*(self.q2(x) for x in ('A', 'F', 'not_adjudicable', 'not_re_examined', 'harness_error')))

    def term_total(self, side):
        d = self.q1(f'{side}_status')
        if isinstance(self.r1, Zero): return 0
        return None if d is None else sum(d.values())

    def sum_leave_other(self):
        d = self.q1('leave_other')
        if isinstance(self.r1, Zero): return 0
        return None if d is None else sum(d.values())

    def ff_with(self, chan):
        d = self.q2('ff_channels')
        if isinstance(self.r2, Zero): return 0
        return None if d is None else sum(n for combo, n in d.items() if chan in combo.split('+'))

    def a(self, sec, path):
        """Số từ analysis-<kind>.json (harness.analysis) mục sec, nhóm g, hệ s (hoặc '_all'). Mục vắng: None (??). Nhóm hoặc hệ vắng mà census
        nói tập nền rỗng (AN_BASE): 0, như Zero của metrics."""
        doc = self.D.analysis.get(self.kind)
        secd = None if doc is None else (doc.get('sections') or {}).get(sec)
        if secd is None: return None
        ent = (secd.get(self.g) or {}).get(self.s or '_all')
        if ent is None:
            base = AN_BASE.get(sec, ('P_rep',))
            return 0 if self.cen is not None and sum(self.cen[b] for b in base) == 0 else None
        return dig(ent, path)


# ---------------------------------------------------------------- danh mục đại lượng
# Fam: tên họ, kinds áp dụng, phạm vi ('group': mọi nhóm, mọi hệ gộp; 'sys_all': thêm từng hệ ở nhóm All; 'sys': thêm từng hệ ở mọi
# nhóm), có Pct hay không, hàm tử số, hàm mẫu số, nguồn (§3.6 hoặc R), đường dẫn JSON, câu hỏi mở (rỗng nếu định nghĩa rõ).
Fam = collections.namedtuple('Fam', 'name kinds scope rate num den src path q')
E, L, EL = ('exe',), ('lib',), ('exe', 'lib')


def families(bnu_rules, rq2_reasons, vec_reasons, leave_codes, an_layers=(), an_sources=(), an_nonrep=None):
    """an_layers: [(tầng, kinds)]; an_sources: nguồn input executable; an_nonrep: {phía: nhóm hợp lệ} (từ harness.analysis, an_consts)."""
    an_nonrep = an_nonrep or {}
    F = []
    A = F.append
    # --- phễu (§3.2, §3.6 Table 3.2; R1, R3, R25)
    A(Fam('Pzero', EL, 'sys', False, lambda c: c.c('P0'), lambda c: c.c('P0'), '§3.2 P_0', 'census', ''))
    A(Fam('Pacc', EL, 'sys', True, lambda c: c.c('P_acc'), lambda c: c.c('P0'), '§3.2 P_acc', 'census', ''))
    A(Fam('Missing', EL, 'sys', True, lambda c: c.c('M'), lambda c: c.c('P0'), '§3.2 M', 'census', ''))
    A(Fam('RZeroBuild', EL, 'sys', True, lambda c: c.c('R0_build'), lambda c: c.c('P0'), '§3.2 R_0 build stage', 'census', ''))
    A(Fam('RZeroTest', EL, 'sys', True, lambda c: c.c('R0_test'), lambda c: c.c('P0'), '§3.2 R_0^test', 'census', ''))
    A(Fam('Prep', EL, 'sys', True, lambda c: c.c('P_rep'), lambda c: c.c('P_acc'), '§3.2 P_rep', 'harness.pairs.p_rep', 'Q-A2'))
    A(Fam('Ptest', EL, 'sys', True, lambda c: c.P_test(), lambda c: c.c('P_acc'), '§3.2, §3.6 P_test', 'rq1_K.by_group.G.P_test', ''))
    A(Fam('Lp', EL, 'sys', True, lambda c: c.L_P(), lambda c: c.c('P_acc'), '§3.6 L_P = |P_acc| - |P_test|', 'census - P_test', ''))
    for x in PRE_REP_CAUSES:
        A(Fam(f'PreRep{tok(x)}', EL, 'sys_all', True, lambda c, x=x: c.c(f'pre_{x}'), lambda c: c.c('P_acc'),
              '§3.2 Attrition (trước P_rep), §3.6 L_P theo nguyên nhân', 'census + recheck', 'Q-A1'))
    A(Fam('LeaveTotal', EL, 'sys_all', True, lambda c: sub(c.q1('n_translations'), c.P_test()), lambda c: c.q1('n_translations'),
          '§3.2 Attrition (sau P_rep)', 'rq1_K.by_group.G.n_translations - P_test', ''))
    for x in leave_codes:
        A(Fam(f'Leave{tok(x)}', EL, 'sys_all', True, lambda c, x=x: c.k1('leave', x), lambda c: c.q1('n_translations'),
              '§3.2 Attrition (sau P_rep); R1', f'rq1_K.by_group.G.leave.{x}', 'Q-A3' if x in ('missing_seed', 'missing_record') else ''))
    A(Fam('LeaveOther', EL, 'sys_all', True, lambda c: c.sum_leave_other(), lambda c: c.q1('n_translations'),
          'metrics F7 (không được xảy ra)', 'rq1_K.by_group.G.leave_other', ''))
    A(Fam('Unexpected', EL, 'group', False, lambda c: c.q1('n_unexpected'), lambda c: c.q1('n_translations'),
          'metrics D26 (ngoài phễu)', 'rq1_K.by_group.G.n_unexpected', ''))
    # --- RQ1 chính (§3.6 RQ1; R2, R19, R20)
    A(Fam('FP', EL, 'sys', True, lambda c: c.D_all(), lambda c: c.P_test(), '§3.6 r_FP = D/|P_test|; R2', 'rq1_K.by_group.G.D_all / P_test', ''))
    A(Fam('FPBoundLo', EL, 'sys', True, lambda c: c.D_all(), lambda c: c.c('P_acc'), '§3.6 D/|P_acc|; R2 khoảng chặn',
          'D_all / census P_acc', ''))
    A(Fam('FPBoundHi', EL, 'sys', True, lambda c: add(c.D_all(), c.L_P()), lambda c: c.c('P_acc'), '§3.6 (D+L_P)/|P_acc|',
          '(D_all + L_P) / census P_acc', ''))
    for k, w in ((1, 'One'), (2, 'Two'), (3, 'Three')):
        A(Fam(f'SeedDet{w}', EL, 'sys_all', True, lambda c, k=k: c.k1('seeds_detect', str(k)), lambda c: c.D_all(),
              '§3.6 số seed phát hiện; R19', f'rq1_K.by_group.G.seeds_detect.{k}', ''))
    for sd in SEEDS:
        A(Fam(f'FPSeed{SEED_TOK[sd]}', EL, 'sys_all', True, lambda c, sd=sd: dig(c.seed[sd], 'D_all'),
              lambda c, sd=sd: dig(c.seed[sd], 'P_test'), '§3.6 Reporting: variation across the seeds; R4, R5',
              f'metrics-split rq1_seed.K.{sd}.G.S.D_all / P_test', 'Q-S1'))
        A(Fam(f'SeedMissing{SEED_TOK[sd]}', EL, 'group', True, lambda c, sd=sd: cnt(c.seed[sd], 'leave', 'missing_seed'),
              lambda c, sd=sd: dig(c.seed[sd], 'n_translations'), 'Q-S1 (mẫu số theo seed)',
              f'metrics-split rq1_seed.K.{sd}.G.S.leave.missing_seed', 'Q-S1'))
    A(Fam('UnstableOnly', EL, 'sys_all', True, lambda c: c.q1('unstable_only'), lambda c: c.P_test(),
          '§3.6 nhóm mọi divergence không ổn định', 'rq1_K.by_group.G.unstable_only', ''))
    A(Fam('InconclOnly', EL, 'sys_all', True, lambda c: c.q1('inconclusive_only'), lambda c: c.P_test(),
          '§3.6 nhóm sanitizer inconclusive', 'rq1_K.by_group.G.inconclusive_only', ''))
    A(Fam('InconclUnstable', EL, 'sys_all', True, lambda c: c.q1('inconclusive_and_unstable_only'), lambda c: c.P_test(),
          '§3.6 "the overlap is reported"', 'rq1_K.by_group.G.inconclusive_and_unstable_only', ''))
    A(Fam('InconclAny', EL, 'group', True, lambda c: c.q1('inconclusive_any'), lambda c: c.P_test(),
          'metrics F7 (chỉ để đối chiếu)', 'rq1_K.by_group.G.inconclusive_any', ''))
    A(Fam('Insens', E, 'sys_all', True, lambda c: c.q1('D_insensitive'), lambda c: c.q1('P_test_insensitive'),
          'decision-log 2026-10-24 (nhóm riêng); §3.3', 'rq1_exe.by_group.G.D_insensitive / P_test_insensitive', 'Q-I1'))
    for x in ('with_input_syms', 'without_input_syms', 'unchecked', 'not_recorded'):
        A(Fam(f'InsensRust{tok(x)}', E, 'group', True, lambda c, x=x: c.q1(f'insensitive_rust.{x}'), lambda c: c.q1('insensitive_rust.n'),
              'master plan dòng 5 (F3)', f'rq1_exe.by_group.G.insensitive_rust.{x}', 'Q-I1'))
    # --- độ nhạy B/N/U (§3.6 đoạn 2; R13)
    A(Fam('NBLo', EL, 'sys', True, lambda c: c.q1('NB_L'), lambda c: c.P_test(), '§3.6 sensitivity, cận dưới; R13',
          'rq1_K.by_group.G.NB_L', ''))
    A(Fam('NBHi', EL, 'sys', True, lambda c: c.q1('NB_U'), lambda c: c.P_test(), '§3.6 sensitivity, cận trên; R13',
          'rq1_K.by_group.G.NB_U', ''))
    for r in bnu_rules:
        A(Fam(f'BnuDiv{tok(r)}', EL, 'group', True, lambda c, r=r: c.k1('bnu_rule_div', r), lambda c: c.q1('n_div_retained'),
              'R13; master plan dòng 23', f'rq1_K.by_group.G.bnu_rule_div.{r} / n_div_retained', 'Q-B1'))
        A(Fam(f'BnuTrans{tok(r)}', EL, 'group', True, lambda c, r=r: c.k1('bnu_rule_translations', r), lambda c: c.D_all(),
              'R13; master plan dòng 23', f'rq1_K.by_group.G.bnu_rule_translations.{r} / D_all', 'Q-B1'))
    # --- 8 robustness analyses RQ1 (§3.6 danh sách 1-8)
    A(Fam('RobCCrash', EL, 'sys_all', True, lambda c: c.q1('SA1'), lambda c: c.P_test(), '§3.6 robustness 1', 'rq1_K.by_group.G.SA1', ''))
    A(Fam('RobUnstable', EL, 'sys_all', True, lambda c: c.q1('SA2'), lambda c: c.P_test(), '§3.6 robustness 2', 'rq1_K.by_group.G.SA2', ''))
    A(Fam('RobComplete', E, 'sys_all', True, lambda c: c.q1('D_complete'), lambda c: c.q1('P_complete'), '§3.6 robustness 3',
          'rq1_exe.by_group.G.D_complete / P_complete', ''))
    # robustness 4, 5: harness.analysis (bản ghi RQ1 không đủ để tính D, tử số luôn ??; thành phần tính đúng được ở hai họ sau)
    A(Fam('RobExact', L, 'sys_all', True, lambda c: c.a('rq1_rob_float', 'exact.D.num'), lambda c: c.P_test(), '§3.6 robustness 4; R21',
          'analysis-lib rq1_rob_float.exact.D (không tính được từ bản ghi RQ1: luôn ??)', 'Q-R1'))
    A(Fam('RobOrigFloat', L, 'sys_all', True, lambda c: c.a('rq1_rob_float', 'orig_float.D.num'), lambda c: c.P_test(),
          '§3.6 robustness 5; R21', 'analysis-lib rq1_rob_float.orig_float.D (không tính được từ bản ghi RQ1: luôn ??)', 'Q-R1'))
    A(Fam('RobOrigFloatRemovedDiv', L, 'group', True, lambda c: c.a('rq1_rob_float', 'orig_float.removed_div.num'),
          lambda c: c.a('rq1_rob_float', 'orig_float.removed_div.den'), '§3.6 robustness 5, thành phần: divergence giữ lại bằng nhau theo luật '
          'oracle gốc', 'analysis-lib rq1_rob_float.orig_float.removed_div', 'Q-R1'))
    A(Fam('RobOrigFloatAllRemoved', L, 'group', True, lambda c: c.a('rq1_rob_float', 'orig_float.all_removed_translations.num'),
          lambda c: c.a('rq1_rob_float', 'orig_float.all_removed_translations.den'), '§3.6 robustness 5, thành phần: bản trong D mất mọi '
          'divergence giữ lại (chưa tính divergence mới)', 'analysis-lib rq1_rob_float.orig_float.all_removed_translations', 'Q-R1'))
    A(Fam('RobNoStderr', EL, 'sys_all', True, lambda c: c.q1('no_stderr'), lambda c: c.P_test(), '§3.6 robustness 6; R29',
          'rq1_K.by_group.G.no_stderr', ''))
    A(Fam('RobCapEight', EL, 'sys_all', True, lambda c: c.q1('cap8'), lambda c: c.P_test(), '§3.6 robustness 7; R29',
          'rq1_K.by_group.G.cap8', 'Q-R2'))
    A(Fam('RobInconcl', EL, 'sys_all', True, lambda c: c.q1('D_with_inconclusive'), lambda c: c.P_test(), '§3.6 robustness 8',
          'rq1_K.by_group.G.D_with_inconclusive', ''))
    A(Fam('ExactTrans', L, 'group', True, lambda c: c.q1('exact_translations'), lambda c: c.P_test(), 'R21 (cận trên thô)',
          'rq1_lib.by_group.G.exact_translations', 'Q-R1'))
    A(Fam('MatchTolNotExact', L, 'group', True, lambda c: c.q1('match_tol_not_exact'), lambda c: c.term_total('c'), 'R21 (cấp input)',
          'rq1_lib.by_group.G.match_tol_not_exact / tổng c_status', 'Q-R1'))
    # --- trần output (R29 robustness 7, D26)
    A(Fam('CapHit', EL, 'group', True, lambda c: c.q1('cap_hit_total'), lambda c: c.term_total('c'), '§3.6 robustness 7; R29',
          'rq1_K.by_group.G.cap_hit_total / tổng c_status', 'Q-R2'))
    A(Fam('CapHitDiv', EL, 'group', True, lambda c: c.q1('cap_hit_div'), lambda c: c.q1('cap_hit_total'), '§3.6 robustness 7',
          'rq1_K.by_group.G.cap_hit_div / cap_hit_total', ''))
    A(Fam('CapSensInfra', EL, 'group', True, lambda c: add(c.q1('cap_sens_infra_match'), c.q1('cap_sens_infra_div')),
          lambda c: c.q1('cap_hit_total'), '§3.6 robustness 7 "counted separately"', 'cap_sens_infra_match + cap_sens_infra_div', ''))
    A(Fam('CapSensNewDiv', EL, 'group', False, lambda c: c.q1('cap_sens_new_div'), lambda c: c.q1('cap_hit_total'), 'R29',
          'rq1_K.by_group.G.cap_sens_new_div', 'Q-R2'))
    A(Fam('CapSensTimeoutRerun', EL, 'group', True, lambda c: c.q1('cap_sens_timeout_rerun'), lambda c: c.q1('cap_hit_total'), 'D26',
          'rq1_K.by_group.G.cap_sens_timeout_rerun', ''))
    A(Fam('CapOneSide', EL, 'group', True, lambda c: c.q1('cap_one_side_translations'), lambda c: c.P_test(), 'F7',
          'rq1_K.by_group.G.cap_one_side_translations', ''))
    # --- đếm bổ sung cấp input (§3.6 Reporting procedure; R22, R23, R24, R28, R29)
    for x, d, nm in (('n_div_ub', 'n_div_all', 'UbDiv'), ('n_div_stable_ub', 'n_div_stable', 'UbDivStable'),
                     ('inputs_ub', 'inputs_div', 'UbInputs'), ('inputs_stable_ub', 'inputs_div_stable', 'UbInputsStable'),
                     ('translations_with_ub', 'translations_with_div', 'UbTrans')):
        A(Fam(nm, EL, 'sys_all' if nm == 'UbDiv' else 'group', True, lambda c, x=x: c.q1(f'ub_R22.{x}'),
              lambda c, d=d: c.q1(f'ub_R22.{d}'), '§3.6 Reporting "inputs excluded by the sanitizer check"; R22',
              f'rq1_K.by_group.G.ub_R22.{x} / {d}', 'Q-U1'))
    A(Fam('StderrOnlyDiv', EL, 'sys_all', True, lambda c: c.q1('n_stderr_only_retained'), lambda c: c.q1('n_div_retained'), 'R29',
          'rq1_K.by_group.G.n_stderr_only_retained / n_div_retained', ''))
    A(Fam('StderrOnlyTrans', EL, 'group', True, lambda c: c.q1('D_stderr_only'), lambda c: c.D_all(), 'R29',
          'rq1_K.by_group.G.D_stderr_only / D_all', ''))
    A(Fam('StderrOnlyInputs', EL, 'group', False, lambda c: c.q1('div_stderr_only'), lambda c: c.q1('n_div_retained'), 'R29 (mọi divergence)',
          'rq1_K.by_group.G.div_stderr_only', 'Q-T2'))
    A(Fam('BothNtMatch', EL, 'group', True, lambda c: c.q1('both_nt_match'), lambda c: c.term_total('c'), 'R23; §3.6 "only part of the output"',
          'rq1_K.by_group.G.both_nt_match / tổng c_status', 'Q-T1'))
    A(Fam('BothNtPrefixZero', EL, 'group', True, lambda c: c.q1('both_nt_prefix_zero'), lambda c: c.q1('both_nt_match'), 'R23',
          'rq1_K.by_group.G.both_nt_prefix_zero / both_nt_match', ''))
    A(Fam('BothNtPrefixBytes', EL, 'group', False, lambda c: c.q1('both_nt_prefix_bytes'), lambda c: c.q1('both_nt_match'), 'R23 "số byte đã so"',
          'rq1_K.by_group.G.both_nt_prefix_bytes', ''))
    # R23, R24, input ngoài miền, hao hụt theo input: harness.analysis (analysis-<kind>.json)
    for nm, p, src in (('NtOneSideConfirmed', 'confirmed_retained', 'divergence giữ lại'), ('NtOneSideConfirmedAll', 'confirmed_all', 'mọi divergence'),
                       ('NtOneSideRerunAll', 'rerun_all', 'mọi divergence có chạy lại gấp mười'),
                       ('NtOneSideTransAny', 'translations_any', 'bản trong D có ít nhất một'),
                       ('NtOneSideTransOnly', 'translations_only', 'bản trong D mà mọi divergence giữ lại thuộc nhóm')):
        A(Fam(nm, EL, 'group', True, lambda c, p=p: c.a('nt_one_side', f'{p}.num'), lambda c, p=p: c.a('nt_one_side', f'{p}.den'),
              f'R23 "NT một bên đã xác nhận" ({src})', f'analysis-K nt_one_side.{p}', 'Q-T1'))
    for lay, ks in an_layers:
        for nm, p, src in (('DivLayer', 'div_retained', 'divergence giữ lại / quan sát'), ('DivInputsLayer', 'inputs_retained', 'input phân biệt'),
                           ('DivTransLayer', 'translations', 'bản trong D')):
            A(Fam(f'{nm}{tok(lay)}', ks, 'group', True, lambda c, p=p, lay=lay: c.a('div_by_input', f'layers.{lay}.{p}.num'),
                  lambda c, p=p, lay=lay: c.a('div_by_input', f'layers.{lay}.{p}.den'), f'§3.6 "divergences by input source"; R24 ({src})',
                  f'analysis-K div_by_input.layers.{lay}.{p}', 'Q-G1'))
        A(Fam(f'OutOfDomain{tok(lay)}', ks, 'group', True, lambda c, lay=lay: c.a('out_of_domain', f'layers.{lay}.num'),
              lambda c, lay=lay: c.a('out_of_domain', f'layers.{lay}.den'), '§3.6 "out-of-domain inputs by generation layer or origin"',
              f'analysis-K out_of_domain.layers.{lay}', 'Q-G1'))
    for x in an_sources:
        A(Fam(f'DivSource{tok(x)}', E, 'group', True, lambda c, x=x: c.a('div_by_input', f'sources.{x}.div_retained.num'),
              lambda c, x=x: c.a('div_by_input', f'sources.{x}.div_retained.den'), '§3.6 "divergences by input source"; R24 (theo nguồn)',
              f'analysis-exe div_by_input.sources.{x}.div_retained', 'Q-G1'))
    for x in leave_codes:
        A(Fam(f'AttrInputs{tok(x)}', EL, 'sys_all', True, lambda c, x=x: c.a('attrition_inputs', f'codes.{x}.inputs_lost.num'),
              lambda c, x=x: c.a('attrition_inputs', f'codes.{x}.inputs_lost.den'), '§3.6 "numbers of affected translations and inputs"',
              f'analysis-K attrition_inputs.codes.{x}.inputs_lost', 'Q-A4'))
    A(Fam('AttrInputsUnknown', EL, 'sys_all', True, lambda c: c.a('attrition_inputs', 'translations_inputs_unknown'),
          lambda c: c.a('attrition_inputs', 'n_translations'), '§3.6 attrition theo input: bản dịch có số input không xác định',
          'analysis-K attrition_inputs.translations_inputs_unknown', 'Q-A4'))
    A(Fam('AttrInputsSanUnresolved', EL, 'group', False, lambda c: c.a('attrition_inputs', 'codes.san_infra.san_unresolved_divergences'),
          lambda c: c.a('attrition_inputs', 'codes.san_infra.translations.num'), '§3.6 attrition san_infra: divergence ổn định chỉ thiếu kiểm '
          'sanitizer (Den: số bản san_infra)', 'analysis-K attrition_inputs.codes.san_infra.san_unresolved_divergences', 'Q-A4'))
    # bốn nhóm bằng chứng của non-reproduced decision (§3.2, Phụ lục A): harness.analysis, cần file evidence
    for path, w in (('accepted', 'Acc'), ('rejected', 'Rej')):
        for grp in an_nonrep[path]:
            A(Fam(f'NonRep{w}{tok(grp)}', EL, 'sys_all', True, lambda c, path=path, grp=grp: c.a('nonrep_groups', f'{path}.groups.{grp}.num'),
                  lambda c, path=path, grp=grp: c.a('nonrep_groups', f'{path}.groups.{grp}.den'),
                  '§3.2 Attrition "four groups by the available evidence"; Phụ lục A; R3', f'analysis-K nonrep_groups.{path}.groups.{grp}',
                  'Q-A1, Q-N1'))
        A(Fam(f'NonRep{w}Unclassified', EL, 'sys_all', True, lambda c, path=path: c.a('nonrep_groups', f'{path}.unclassified.num'),
              lambda c, path=path: c.a('nonrep_groups', f'{path}.unclassified.den'), '§3.2 non-reproduced chưa gán nhóm',
              f'analysis-K nonrep_groups.{path}.unclassified', 'Q-N1'))
    for side, w in (('c', 'C'), ('r', 'R')):
        A(Fam(f'TermTotal{w}', EL, 'group', False, lambda c, side=side: c.term_total(side), lambda c, side=side: c.term_total(side), 'R28',
              f'tổng rq1_K.by_group.G.{side}_status', 'Q-T1'))
    # trạng thái kết thúc: theo kind, sinh ở terms()
    # --- V6 (metrics v6_separation; Le chọn 26/10)
    for part, w in (('separated', 'Sep'), ('rest', 'Rest')):
        A(Fam(f'VSix{w}', EL, 'sys_all', True, lambda c, part=part: dig(c.v6, f'{part}.D_all'), lambda c, part=part: dig(c.v6, f'{part}.P_test'),
              'metrics v6_separation (báo tách theo nguyên nhân V6)', f'rq1_K.v6_separation.by_group.G.{part}.D_all / P_test', 'Q-V1'))
    # --- RQ2 (§3.6 RQ2; R3, R14)
    A(Fam('FF', EL, 'sys', True, lambda c: c.F(), lambda c: c.q2('R_test'), '§3.6 r_FF = F/|R_test|; R14', 'rq2_K.F / R_test', ''))
    A(Fam('FFDisagree', EL, 'sys', True, lambda c: c.q2('A'), lambda c: c.q2('R_test'), '§3.6 Table 3.3', 'rq2_K.A', ''))
    A(Fam('FFNotAdj', EL, 'sys', True, lambda c: c.q2('not_adjudicable'), lambda c: c.q2('R_test'), '§3.6 "reported as a separate count"',
          'rq2_K.not_adjudicable', ''))
    A(Fam('FFNotReex', EL, 'sys_all', True, lambda c: c.q2('not_re_examined'), lambda c: c.R_run_rec(), '§3.6 Table 3.3 (phần trong R_run)',
          'rq2_K.not_re_examined', 'Q-F2'))
    A(Fam('FFHarnessError', EL, 'sys_all', True, lambda c: c.q2('harness_error'), lambda c: c.R_run_rec(), 'metrics (bản ghi lỗi harness)',
          'rq2_K.harness_error', 'Q-F2'))
    A(Fam('FFRrunRec', EL, 'sys_all', True, lambda c: c.R_run_rec(), lambda c: c.c('R_run'), 'đối chiếu bản ghi RQ2 với R_run census',
          'A+F+not_adjudicable+not_re_examined+harness_error / census R_run', ''))
    for x in R0_TEST_PARTS:
        A(Fam(f'RZeroTest{tok(x)}', EL, 'sys_all', True, lambda c, x=x: c.c(x), lambda c: c.c('R0_test'),
              '§3.2 Rejected path; R3 (non-reproduced decision dòng riêng)', f'census ({x})', 'Q-F1' if x != 'R_run' else ''))
    A(Fam('Lr', EL, 'sys', True, lambda c: c.L_R(), lambda c: c.c('R0_test'), '§3.6 L_R = |R_0^test| - A - F', 'census R0_test - A - F', ''))
    for o, rs in rq2_reasons.items():
        for r in rs:
            A(Fam(f'FFReason{tok(o)}{tok(r)}', EL, 'group', True, lambda c, o=o, r=r: c.k2('translation_reason', f'{o}:{r}'),
                  lambda c, o=o: c.q2(o), '§3.6 Table 3.3 (một lý do mỗi bản); R14', f'rq2_K.translation_reason["{o}:{r}"]', ''))
    for ch in FF_CHANNELS:
        A(Fam(f'FFChan{tok(ch)}', EL, 'group', True, lambda c, ch=ch: c.ff_with(ch), lambda c: c.F(),
              '§3.6 "attributed to the components"; R14 (bản có kênh này, kể cả tổ hợp)', 'rq2_K.ff_channels (cộng mọi tổ hợp chứa kênh)', 'Q-F3'))
    for nm, p in (('FFCTerm', 'c_term_vectors'), ('FFCTermFF', 'c_term_vectors_ff')):
        for x in ('any', 'exit_101', 'signal'):
            A(Fam(f'{nm}{tok(x)}', EL, 'group', True, lambda c, p=p, x=x: c.q2(f'{p}.{x}'), lambda c, p=p: c.q2(f'{p}.n_vectors'),
                  '§3.6 "termination status ... exit code 101 or signal"; D6', f'rq2_K.{p}.{x} / n_vectors', ''))
    for o, rs in vec_reasons.items():
        for r in rs:
            key = f'{o}:{r}'
            A(Fam(f'FFVec{tok(o)}{tok(r) if r else ""}', EL, 'group', True, lambda c, key=key: c.k2('vector_reasons', key),
                  lambda c: (None if c.q2('vector_reasons') is None else sum(c.q2('vector_reasons').values())) if not isinstance(c.r2, Zero) else 0,
                  '§3.6 RQ2 cấp vector', f'rq2_K.vector_reasons["{key}"]', ''))
    for w, an, ks in (('NoStderr', 'no_stderr', EL), ('Exact', 'exact', L), ('OrigFloat', 'orig_float', L)):
        A(Fam(f'RobFF{w}', ks, 'sys_all', True, lambda c, an=an: c.a('rq2_rob', f'{an}.F.num'), lambda c: c.q2('R_test'),
              '§3.6 ba robustness analyses RQ2 (mẫu số R_test của số chính)', f'analysis-K rq2_rob.{an}.F', 'Q-R3'))
        for x, nm in (('not_adjudicable', 'NotAdj'), ('not_re_examined', 'NotReex'), ('changed', 'Changed')):
            A(Fam(f'RobFF{w}{nm}', ks, 'group', True, lambda c, an=an, x=x: c.a('rq2_rob', f'{an}.{x}.num'), lambda c: c.q2('R_test'),
                  '§3.6 RQ2 robustness "reported separately and stays in the denominator"', f'analysis-K rq2_rob.{an}.{x}', 'Q-R3'))
    # --- RQ3 (§3.6 RQ3; R16)
    A(Fam('SR', EL, 'sys', True, lambda c: c.c('P_acc'), lambda c: c.c('P0'), '§3.6 s = |P_acc|/|P_0|; R16', 'census', 'Q-Z1'))
    A(Fam('SRLo', EL, 'sys', True, lambda c: sub(add(c.c('P_acc'), c.F()), c.D_all(), c.L_P()), lambda c: c.c('P0'),
          '§3.6 cận dưới (|P_acc|-D-L_P+F)/|P_0|; R16', 'census, rq1 D_all, rq2 F', 'Q-Z1'))
    A(Fam('SRHi', EL, 'sys', True, lambda c: sub(add(c.c('P_acc'), c.F(), c.L_R()), c.D_all()), lambda c: c.c('P0'),
          '§3.6 cận trên (|P_acc|-D+F+L_R)/|P_0|; R16', 'census, rq1 D_all, rq2 F, L_R', 'Q-Z1'))
    A(Fam('SRWidth', EL, 'sys', True, lambda c: add(c.L_P(), c.L_R()), lambda c: c.c('P0'), '§3.6 độ rộng (L_P+L_R)/|P_0|',
          'L_P + L_R', 'Q-Z1'))
    return F


def term_families(kind, statuses):
    out = []
    for side, w in (('c', 'C'), ('r', 'R')):
        for st in statuses:
            out.append(Fam(f'Term{w}{tok(st)}', (kind,), 'group', True, lambda c, side=side, st=st: c.k1(f'{side}_status', st),
                           lambda c, side=side: c.term_total(side), '§3.6 "inputs by termination status on each side"; R28',
                           f'rq1_{kind}.by_group.G.{side}_status.{st}', 'Q-T1'))
    return out


def ff_combos(D):
    """Tổ hợp kênh chấm trượt oan có trong dữ liệu (§3.6: "Combinations of components are reported as separate rows"); theo thứ tự tên."""
    seen = set()
    for kind in KINDS:
        seen |= set(dig(D.metrics, f'rq2_{kind}.ff_channels') or {})
        for g, d in (D.split_ok.get(('rq2', kind)) or {}).items():
            seen |= set(dig(d, ('_all', 'ff_channels')) or {})
    return sorted(seen)


def combo_families(D):
    """Họ động: một họ mỗi tổ hợp kênh có trong dữ liệu (tên macro phụ thuộc dữ liệu; bảng tab-rq2-channels.tex dùng)."""
    return [Fam(f'FFCombo{tok(cb)}', EL, 'group', True, lambda c, cb=cb: c.k2('ff_channels', cb), lambda c: c.F(),
                '§3.6 tổ hợp kênh, dòng riêng; R14', f'rq2_K.ff_channels["{cb}"]', 'Q-F3') for cb in ff_combos(D)]


def bnu_rule_list(hroot):
    """Mã luật B/N/U đọc từ experiments/09-bnu-rules/scripts/bnu_v0.py (bản harness dùng); thứ tự B, N, U rồi theo mã."""
    try: s = open(f'{hroot}/experiments/09-bnu-rules/scripts/bnu_v0.py').read()
    except OSError: return []
    rules = set(re.findall(r"return '[BNU]', '([BNU][0-9]?-[a-z-]+)'", s))
    return sorted(rules, key=lambda r: ('BNU'.index(r[0]), r))


# ---------------------------------------------------------------- định dạng và ghi
def fmt(x):
    if x is None: return '??'
    if isinstance(x, float) and x.is_integer(): x = int(x)
    return str(x)


def pct(n, d):
    if n is None or d is None: return '??'
    return 'n/a' if d == 0 else f'{100 * n / d:.1f}'


class Data:
    def __init__(self, metrics, split_doc, census, analysis=None):
        self.metrics, self.split, self.census = metrics, split_doc, census
        self.analysis = dict(analysis or {})          # {kind: đầu ra harness.analysis}
        self.split_ok, self.warn = {}, []


# Mục của harness.analysis dựa trên bản dịch RQ1 (cần cùng P_test với metrics) và trên bản ghi RQ2 (cùng R_test)
AN_RQ1 = ('div_by_input', 'attrition_inputs', 'nt_one_side', 'rq1_rob_float', 'out_of_domain')
AN_BASE = dict(rq2_rob=('R_run',), nonrep_groups=('pre_non_reproduced', 'R_nonrep'))
AN_FALLBACK = dict(layers=[('S', ('exe',)), ('M', ('exe',)), ('MS', ('exe',)), ('A', ('exe',)), ('vector', ('lib',)), ('random', ('lib',)),
                           ('dict', ('lib',)), ('sweep', ('lib',)), ('generated', ('exe', 'lib'))],
                   sources=('seed', 'random', 'dict', 'syntax', 'afl'),
                   nonrep=dict(accepted=('oracle_drift', 'translation', 'undetected_ub', 'unknown'),
                               rejected=('oracle_drift', 'undetected_ub', 'unknown')))


def an_consts(hroot):
    """Tầng, nguồn input và nhóm non-reproduced theo harness.analysis của --harness-root (không có thì AN_FALLBACK)."""
    try:
        sys.path.insert(0, hroot)
        import harness.analysis as HA
    except ImportError:
        return AN_FALLBACK
    lay = [(x, ('exe',)) for x in HA.EXE_LAYERS] + [(x, ('lib',)) for x in HA.LIB_LAYERS] + [(HA.GEN, ('exe', 'lib'))]
    return dict(layers=lay, sources=HA.EXE_SOURCES, nonrep=HA.NONREP_ALLOWED)


def check_analysis(D):
    """analysis-<kind>.json phải cùng kind và cùng tập bản dịch với metrics: P_test, n_translations theo nhóm (RQ1) và R_test (RQ2). Lệch
    thì bỏ các mục liên quan của kind đó (??) và cảnh báo."""
    for kind, doc in list(D.analysis.items()):
        if doc.get('kind') != kind:
            D.warn.append(f'analysis {kind}: file mang kind {doc.get("kind")!r}; bỏ'); D.analysis.pop(kind); continue
        sec = doc.get('sections') or {}
        m1 = dig(D.metrics, f'rq1_{kind}.by_group')
        bad = []
        for g, d in (sec.get('div_by_input') or {}).items():
            mp, mn = dig(m1, (g, 'P_test')), dig(m1, (g, 'n_translations'))
            if mp != d['_all'].get('P_test'): bad.append((g, 'P_test', d['_all'].get('P_test'), mp))
            an = dig(sec, ('attrition_inputs', g, '_all', 'n_translations'))
            if mn != an: bad.append((g, 'n_translations', an, mn))
            s1 = D.split_ok.get(('rq1', kind))
            for s, v in d.items():         # theo hệ: so với metrics-split khi có
                if s != '_all' and s1 is not None and dig(s1, (g, s, 'P_test')) != v.get('P_test'):
                    bad.append((g, s, 'P_test', v.get('P_test'), dig(s1, (g, s, 'P_test'))))
        if bad:
            D.warn.append(f'analysis {kind}: lệch metrics.json ở {bad[:4]}; bỏ mục RQ1 của analysis {kind}')
            for x in AN_RQ1: sec.pop(x, None)
        m2 = dig(D.metrics, f'rq2_{kind}.R_test')
        a2 = dig(sec, ('rq2_rob', 'all', '_all', 'R_test'))
        if 'rq2_rob' in sec and a2 != m2:
            D.warn.append(f'analysis {kind}: R_test {a2} khác metrics {m2}; bỏ rq2_rob'); sec.pop('rq2_rob')


def check_split(D):
    """Hàng '_all' của split phải trùng summary harness.metrics ở mọi khoá vô hướng chung; lệch thì bỏ split của kind đó (??)."""
    sp = D.split or {}
    for kind in KINDS:
        for which in ('rq1', 'rq1_seed', 'rq2'):
            v = (sp.get(which) or {}).get(kind)
            if v is not None: D.split_ok[(which, kind)] = v
        s1 = D.split_ok.get(('rq1', kind))
        m1 = dig(D.metrics, f'rq1_{kind}.by_group')
        if s1 is not None and m1 is not None:
            bad = [(g, k) for g in m1 for k, v in m1[g].items() if not isinstance(v, (dict, list)) and dig(s1, (g, '_all', k)) != v]
            bad += [(g, '(nhóm vắng)') for g in s1 if g not in m1] + [(g, '(nhóm vắng ở split)') for g in m1 if g not in s1]
            if bad:
                D.warn.append(f'rq1 {kind}: split lệch metrics.json ở {bad[:5]}; bỏ số theo hệ và theo seed của {kind}')
                D.split_ok.pop(('rq1', kind)); D.split_ok.pop(('rq1_seed', kind), None)
        elif s1 is not None and m1 is None:
            D.warn.append(f'rq1 {kind}: có split nhưng metrics.json không có rq1_{kind}; bỏ split'); D.split_ok.pop(('rq1', kind))
        s2, m2 = D.split_ok.get(('rq2', kind)), dig(D.metrics, f'rq2_{kind}')
        if s2 is not None:
            keys = ('A', 'F', 'R_test', 'not_adjudicable', 'not_re_examined', 'harness_error')
            if m2 is None or any(dig(s2, ('all', '_all', k)) != m2.get(k) for k in keys):
                D.warn.append(f'rq2 {kind}: split lệch hoặc thiếu metrics.json; bỏ số RQ2 theo nhóm và hệ của {kind}')
                D.split_ok.pop(('rq2', kind))


def consistency(D):
    """Kiểm chéo phễu: |P_rep| census = n_translations của metrics (khi chạy --expect p_rep); bản ghi RQ2 = R_run census."""
    for kind in KINDS:
        cz = D.census.get(kind)
        if cz is None: continue
        for g in GROUPS:
            for s in (None,) + SYSTEMS:
                c = Ctx(D, kind, g, s)
                if s is not None and c.cen['P0'] == 0 and g != 'all': continue
                nt = c.q1('n_translations')
                if nt is not None and not isinstance(c.r1, Zero) and nt != c.c('P_rep'):
                    D.warn.append(f'{kind} {g} {s or "mọi hệ"}: n_translations {nt} khác |P_rep| census {c.c("P_rep")} (metrics chạy không --expect p_rep?)')
                rr = c.R_run_rec()
                if rr is not None and not isinstance(c.r2, Zero) and rr != c.c('R_run'):
                    D.warn.append(f'{kind} {g} {s or "mọi hệ"}: bản ghi RQ2 {rr} khác R_run census {c.c("R_run")}')
                fo = c.q1('funnel_ok')
                if fo is False: D.warn.append(f'{kind} {g} {s or "mọi hệ"}: funnel_ok false trong metrics')


def build_macros(D, fams_by_kind, prefix):
    """[(tên, giá trị)] theo thứ tự cố định."""
    out = []
    for kind in KINDS:
        for f in fams_by_kind[kind]:
            if kind not in f.kinds: continue
            for g in GROUPS:
                for s in (None,) + (SYSTEMS if f.scope == 'sys' or (f.scope == 'sys_all' and g == 'all') else ()):
                    c = Ctx(D, kind, g, s)
                    n, d = f.num(c), f.den(c)
                    base = f'{prefix}{f.name}{KIND_TOK[kind]}{GROUP_TOK[g]}{SYS_TOK[s] if s else ""}'
                    out += [(base + 'Num', fmt(n)), (base + 'Den', fmt(d))]
                    if f.rate: out.append((base + 'Pct', pct(n, d)))
    return out


def dynamic_codes(D, path_fn, known):
    """Mã xuất hiện trong dữ liệu mà danh sách cố định không có (cảnh báo, vẫn sinh macro)."""
    seen = set()
    for kind in KINDS:
        for g in GROUPS:
            x = path_fn(D, kind, g)
            if isinstance(x, dict): seen |= set(x)
    extra = sorted(seen - set(known))
    if extra: D.warn.append(f'mã ngoài danh sách cố định: {extra}')
    return list(known) + extra


def prepare(a):
    hroot = os.path.abspath(a.harness_root)
    HM, HP, HQ = load_harness(hroot)
    metrics = split_doc = None
    inputs, analysis = [], {}
    if a.indir:
        mp, sp = f'{a.indir}/metrics.json', f'{a.indir}/metrics-split.json'
        if os.path.exists(mp): metrics = json.load(open(mp)); inputs.append(mp)
        else: print(f'thiếu {mp}: mọi số đo được là ??', file=sys.stderr)
        if os.path.exists(sp): split_doc = json.load(open(sp)); inputs.append(sp)
        else: print(f'thiếu {sp}: số theo hệ, theo nhóm (RQ2) và theo seed là ??', file=sys.stderr)
        for kind in KINDS:            # đầu ra `python3 -m harness.analysis --kind <kind>` (bảy nhóm số metrics chưa tính)
            ap_ = f'{a.indir}/analysis-{kind}.json'
            if os.path.exists(ap_): analysis[kind] = json.load(open(ap_)); inputs.append(ap_)
            else: print(f'thiếu {ap_}: số của harness.analysis ({kind}) là ??', file=sys.stderr)
    if split_doc and (split_doc.get('meta') or {}).get('pilot') and not a.pilot:
        raise SystemExit('metrics-split.json là pilot (expect=pilot) nhưng không có --pilot')
    if any((d.get('meta') or {}).get('pilot') for d in analysis.values()) and not a.pilot:
        raise SystemExit('analysis-*.json là pilot (expect=pilot) nhưng không có --pilot')
    census, cfiles = census_counts(hroot, a.pilot)
    D = Data(metrics, split_doc, census, analysis)
    check_split(D); check_analysis(D); consistency(D)
    leave = tuple(getattr(HM, 'LEAVE_ORDER', LEAVE_CODES_FALLBACK))
    rq2r = {o: rs for o, rs in HQ.TRANSLATION_REASONS.items() if rs != (None,)}
    vecr = dict(HQ.VECTOR_REASONS)
    ac = an_consts(hroot)
    fams = families(bnu_rule_list(hroot), rq2r, vecr, leave, ac['layers'], ac['sources'], ac['nonrep'])
    st = dict(exe=dynamic_codes(D, lambda D, k, g: {**(dig(D.metrics, f'rq1_{k}.by_group.{g}.c_status') or {}),
                                                    **(dig(D.metrics, f'rq1_{k}.by_group.{g}.r_status') or {})} if k == 'exe' else None, EXE_STATUS),
              lib=dynamic_codes(D, lambda D, k, g: {**(dig(D.metrics, f'rq1_{k}.by_group.{g}.c_status') or {}),
                                                    **(dig(D.metrics, f'rq1_{k}.by_group.{g}.r_status') or {})} if k == 'lib' else None, LIB_STATUS))
    fams_by_kind = {k: fams + term_families(k, st[k]) + combo_families(D) for k in KINDS}
    files = inputs + cfiles + [f'{hroot}/experiments/09-bnu-rules/scripts/bnu_v0.py']
    return D, fams_by_kind, files, hroot


def render(D, fams_by_kind, files, hroot, prefix, pilot):
    macros = build_macros(D, fams_by_kind, prefix)
    names = [n for n, _ in macros]
    dup = [n for n, k in collections.Counter(names).items() if k > 1]
    if dup: raise SystemExit(f'tên macro trùng: {dup[:10]}')
    bad = [n for n in names if not re.fullmatch(r'[A-Za-z]+', n)]
    if bad: raise SystemExit(f'tên macro không hợp lệ: {bad[:10]}')
    meta = (D.split or {}).get('meta') or {}
    lines = ['% SINH TU DONG boi writing/scripts/gen-rq-macros.py. KHONG SUA TAY.',
             '% Bang tra cuu: docs/proposal/rq-macro-map.md. ?? = thieu nguon; n/a = mau so 0.',
             f'% Repo commit: {git_rev(ROOT)}; harness root commit: {git_rev(hroot)}'
             + (f'; split: harness {meta.get("harness_commit")}, seeds {meta.get("seeds")}, expect {meta.get("expect")}' if meta else ''),
             f'% Population: {"PILOT (R6, bao rieng, Le chap nhan khong kiem tay 2026-11-12)" if pilot else "P0 khong pilot"}',
             '% P0, P_acc, M, R0 theo giai doan: cung nguon Bang 3.1 (tab-m-population.tex). P_rep, nguyen nhan truoc P_rep (PreRep*), '
             'phan cua R0_test (RZeroTest*): Le chap nhan khong kiem tay 2026-11-12.',
             '% Moi so tu metrics (RQ1, RQ2, RQ3, B/N/U, robustness): kiem tren mau bang ba luot gan nhan doc lap va Le phan xu '
             '(R9: exp 31, 32; RQ2: exp 34), sai so o robust-numbers.tex (rqRNine*, rqRTwoCheck*); decision-log 2026-11-03.']
    for p in files:
        lines.append(f'% sha256 {sha(p) or "THIEU"}  {os.path.relpath(p, ROOT) if p.startswith(ROOT) else p}')
    for w in D.warn:
        lines.append('% CANH BAO: ' + w.replace('\n', ' '))
    # rqSet{tên}{giá trị}: định nghĩa bằng csname để file gọn (khoảng 14 nghìn macro) và \\input lại được nhiều lần; tên đã kiểm
    # chỉ gồm chữ cái và không trùng (tests/test_rq_macros.py kiểm thêm không trùng macro của các file sinh khác).
    lines += ['', '\\providecommand{\\rqSet}[2]{\\expandafter\\def\\csname #1\\endcsname{#2}}']
    lines += [f'\\rqSet{{{n}}}{{{v}}}' for n, v in macros]
    return '\n'.join(lines) + '\n', macros


def map_rows(fams_by_kind, prefix):
    """Dòng markdown cho docs/proposal/rq-macro-map.md (một dòng mỗi họ)."""
    seen, rows = set(), []
    scope = dict(group='nhóm', sys_all='nhóm; hệ ở All', sys='nhóm x hệ')
    for kind in KINDS:
        for f in fams_by_kind[kind]:
            if f.name in seen: continue
            seen.add(f.name)
            kinds = '/'.join(KIND_TOK[k] for k in f.kinds)
            ex = f'`\\{prefix}{f.name}{KIND_TOK[f.kinds[0]]}All{"Num" if not f.rate else "Pct"}`'
            esc = lambda x: x.replace('|', '\\|')
            rows.append(f'| {ex} | {kinds} | {scope[f.scope]} | {esc(f.src)} | `{esc(f.path)}` | {f.q or ""} |')
    return rows


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['split']:
        ap = argparse.ArgumentParser(prog='gen-rq-macros.py split')
        ap.add_argument('--rq1'); ap.add_argument('--rq2'); ap.add_argument('--seeds', default='0,1,2')
        ap.add_argument('--expect', choices=['pilot', 'p_rep']); ap.add_argument('-o', required=True)
        ap.add_argument('--harness-root', default=ROOT); ap.add_argument('--no-seed-split', action='store_true')
        return split(ap.parse_args(argv[1:]))
    ap = argparse.ArgumentParser(prog='gen-rq-macros.py')
    ap.add_argument('--in', dest='indir'); ap.add_argument('--out', default=OUT); ap.add_argument('--harness-root', default=ROOT)
    ap.add_argument('--prefix', default='rq'); ap.add_argument('--pilot', action='store_true')
    ap.add_argument('--map', action='store_true', help='in bảng họ macro (markdown) cho rq-macro-map.md rồi thoát')
    a = ap.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z]+', a.prefix): raise SystemExit('prefix chỉ gồm chữ cái')
    gen_dir = os.path.realpath(f'{ROOT}/writing/generated')
    if a.pilot and os.path.realpath(a.out).startswith(gen_dir + os.sep):
        raise SystemExit('số pilot không được ghi vào writing/generated/ (R6); dùng --out ở scratchpad')
    D, fams_by_kind, files, hroot = prepare(a)
    if a.map:
        print('\n'.join(map_rows(fams_by_kind, a.prefix))); return
    tex, macros = render(D, fams_by_kind, files, hroot, a.prefix, a.pilot)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, 'w').write(tex)
    n_missing = sum(v == '??' for _, v in macros)
    print(f'Đã ghi {a.out}: {len(macros)} macro, {n_missing} macro ??; {len(D.warn)} cảnh báo', file=sys.stderr)
    for w in D.warn: print('CẢNH BÁO: ' + w, file=sys.stderr)


if __name__ == '__main__':
    main()
