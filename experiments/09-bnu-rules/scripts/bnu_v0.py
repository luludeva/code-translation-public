#!/usr/bin/env python3
"""Luật B/N/U v0 (đặc tả: docs/proposal/bnu-rules-v0.md) và phép đo kích thước U trên dữ liệu pilot.

Chỉ đọc dữ liệu pilot đã có (exp 03, exp 04). Không đọc dữ liệu corpus chính.

Cách dùng:
  python3 bnu_v0.py --exp03 <thư mục results exp 03> --exp04 <thư mục layers giải nén từ layers-afl.tar.gz>
                    --verifykill <verify-kills.json từ nhánh results/verifykill> --out <file json>
"""
import argparse, glob, json, math, os, re, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
from harness import observe as OB                     # noqa: E402

# v1: luật NT (cổng A5.3, 2026-10-22); v2: stderr vào phép so, luật U-stderr (decision-log 2026-10-23);
# v3 (rà soát kỹ thuật 2026-10-23): chuẩn hoá và phép so library gọi thẳng harness/observe.py thay vì chép lại. Bản v2 chép tay nên trôi
# khỏi oracle sau các sửa 23/10 (mã luồng panic, R-NaN ranh giới từ, giá trị không hữu hạn trong state, kết quả runner library).
# v5 (rà F6, exp 24 mục 4 điểm 4 và 5; Le chọn 25/10 tối): B2 so hai token số nguyên bằng giá trị nguyên chính xác, không qua float;
# hai bên cùng NT mà oracle khớp mang mã luật NT-prefix thay cho R-NaN; nhánh R15-UB ghi rõ là phòng vệ. Không đổi D, không đổi nhóm ca khác.
RULES_VERSION = 'bnu-v5'
NAN = re.compile(OB.NAN.pattern.decode(), re.I)        # R-NaN, cùng biểu thức với observe.norm
NUM = re.compile(r'([-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?|[-+]?inf(?:inity)?)', re.I)
REL_TOL = 1e-6


def norm_err(e):
    """Chuẩn hoá N cho stderr: gọi observe.norm_err (cùng một cài đặt với oracle)."""
    b = (e or '').encode('utf-8', 'surrogateescape') if isinstance(e, str) else (e or b'')
    return OB.norm_err(b).decode('utf-8', 'surrogateescape')


def r_nan(s):
    return NAN.sub('nan', s)


def lines_b1(s):
    """B1: bỏ khoảng trắng cuối mỗi dòng và các dòng rỗng ở cuối output."""
    ls = [l.rstrip(' \t\r') for l in s.split('\n')]
    while ls and ls[-1] == '':
        ls.pop()
    return ls


def decimals(tok):
    t = tok.lower()
    if 'inf' in t:
        return None
    if 'e' in t:
        return -1                                       # dạng mũ: chỉ dùng sai số tương đối
    return len(t.split('.')[1]) if '.' in t else 0


def int_equal(a, b):
    """Hai token số nguyên (dạng [-+]?chữ số) bằng nhau khi cùng giá trị nguyên. So chuỗi đã chuẩn hoá dấu và số 0 đầu, nên chính xác ở
    mọi độ dài (không qua float, không vướng giới hạn số chữ số của int). -0 bằng 0."""
    def canon(t):
        d = t.lstrip('+-').lstrip('0') or '0'
        return (t.startswith('-') and d != '0', d)
    return canon(a) == canon(b)


def num_equiv(a, b):
    """B2 trên một cặp token số. Hai token số nguyên (không có dấu chấm, không có mũ) chỉ tương đương khi bằng nhau thật sự (§3.5 p5;
    bnu-v5: bản v4 so qua float nên 9007199254740993 và 9007199254740992 bị coi là bằng). Token số thực theo sai số như cũ."""
    if a == b:
        return True
    da, db = decimals(a), decimals(b)
    if da == 0 and db == 0:
        return int_equal(a, b)
    try:
        x, y = float(a), float(b)
    except ValueError:
        return False
    if da is None or db is None:                        # inf
        return x == y
    if x == y:                                          # gồm -0.0 so với 0.0
        return True
    if math.isinf(x) or math.isinf(y):
        return False
    tol = REL_TOL * max(abs(x), abs(y))
    if da > 0 and db > 0:                               # một đơn vị ở chữ số in cuối cùng của token kém chính xác hơn
        tol = max(tol, 10.0 ** (-min(da, db)))
    return abs(x - y) <= tol * (1 + 1e-9)


def line_equiv_b2(lc, lr):
    pc, pr = NUM.split(lc), NUM.split(lr)
    if len(pc) != len(pr):
        return False
    for i, (a, b) in enumerate(zip(pc, pr)):
        if i % 2 == 0:
            if a != b:
                return False
        elif not num_equiv(a, b):
            return False
    return True


def nt_common_prefix(co, ro):
    """Luật NT, phần phân nhóm: hai bên cùng không dừng trong ngân sách thì B1, B2, N3 xét các dòng hoàn chỉnh chung (đã chuẩn hoá R-NaN),
    cắt theo số dòng hoàn chỉnh của bên ít dòng hơn. Cắt theo dòng để khác biệt khoảng trắng không làm lệch điểm cắt. Có divergence hay
    không thì theo oracle (nt_equal), không theo hàm này (Le chọn 25/10 tối, rà F6 lệch 2)."""
    lc, lr = co.split('\n')[:-1], ro.split('\n')[:-1]   # chỉ giữ dòng hoàn chỉnh
    n = min(len(lc), len(lr))
    tail = '\n' if n else ''
    return '\n'.join(lc[:n]) + tail, '\n'.join(lr[:n]) + tail


def nt_equal(co, ro):
    """Phán quyết của oracle cho hai bên cùng NT (observe.nt_cut, đối xứng), trên chuỗi đã chuẩn hoá R-NaN."""
    a, b = OB.nt_cut(co.encode('latin-1', 'replace'), ro.encode('latin-1', 'replace'))
    return a == b


def classify_exe(c_rc, r_rc, c_to, r_to, c_out, r_out, c_ub, truncated=False, c_err=None, r_err=None):
    """Trả về (nhóm, luật). nhóm ∈ {not_S, B, N, U, T}. Áp theo thứ tự, luật khớp đầu tiên thắng.

    c_err, r_err (v2): stderr hai phía. Trạng thái kết thúc và stdout trùng mà stderr khác sau chuẩn hoá N: U-stderr (decision-log
    2026-10-23). Không truyền stderr (dữ liệu pilot cũ) thì luật này không áp. Hai bên cùng NT: stderr không so (bị cắt).

    c_to, r_to: phía đó không dừng trong ngân sách (NT: timeout hoặc vượt giới hạn output; luật NT, decision-log 2026-10-22).
    Hai bên cùng NT: so prefix chung; B1, B2, N3 áp trên prefix chung; không bao giờ ra U-residual (cổng A5.3 điểm 3).

    truncated: bản ghi chỉ giữ phần đuôi stdout (harness pilot cắt ở 1500 hoặc 3000 ký tự). Khi đó các luật dựa trên
    stdout không áp được; nhóm T = không đánh giá được trên dữ liệu đã lưu. Lượt chạy chính phải lưu stdout đầy đủ.

    R15-UB (mọi nhánh): nhánh phòng vệ. harness/metrics.bnu_group chỉ phân loại divergence giữ lại (retained: ổn định, sanitizer phía C
    chạy xong không báo), nên c_ub luôn False và nhánh này không bao giờ chạy từ metrics. Giữ để một lời gọi khác (dữ liệu pilot qua
    main(), hay một caller tương lai truyền divergence chưa lọc) không xếp thực thi UB phía C vào S (R15).
    """
    co, ro = r_nan(c_out or ''), r_nan(r_out or '')
    if truncated:
        if c_ub:
            return 'not_S', 'R15-UB'
        if c_to != r_to:
            return 'N', 'N2-timeout'
        if c_rc != r_rc:
            return 'N', 'N1-status'
        return 'T', 'T-truncated'
    if c_to and r_to:
        if nt_equal(co, ro):
            return 'not_S', 'NT-prefix'                 # hai bên cùng NT, oracle khớp theo luật NT (mã luật riêng từ bnu-v5)
        co, ro = nt_common_prefix(co, ro)
        if c_ub:
            return 'not_S', 'R15-UB'                   # phòng vệ, không chạy từ metrics (docstring)
        if co == ro:
            return 'N', 'N3-line'                       # dòng chung trùng, khác nằm ở dòng một bên mới thấy một phần: khác nội dung
        lc, lr = lines_b1(co), lines_b1(ro)
        if lc == lr:
            return 'B', 'B1-whitespace'
        if len(lc) == len(lr) and all(line_equiv_b2(a, b) for a, b in zip(lc, lr)):
            return 'B', 'B2-numeric'
        return 'N', 'N3-line'                           # prefix chung có dòng khác nội dung (không có U-residual)
    if (c_rc, c_to, co) == (r_rc, r_to, ro):
        if c_err is None or norm_err(c_err) == norm_err(r_err):
            return 'not_S', 'R-NaN'                     # hết khác biệt sau chuẩn hoá
        if c_ub:
            return 'not_S', 'R15-UB'                   # phòng vệ, không chạy từ metrics (docstring)
        return 'U', 'U-stderr'                          # chỉ khác stderr
    if c_ub:
        return 'not_S', 'R15-UB'                        # sanitizer phía C báo UB: ngoài S (phòng vệ, không chạy từ metrics)
    if c_to != r_to:
        return 'N', 'N2-timeout'                        # một bên NT, bên kia dừng (đã xác nhận ở harness, chạy lại gấp 10)
    if c_rc != r_rc:
        return 'N', 'N1-status'                         # exit code hoặc signal khác
    lc, lr = lines_b1(co), lines_b1(ro)
    if lc == lr:
        return 'B', 'B1-whitespace'
    if len(lc) == len(lr) and all(line_equiv_b2(a, b) for a, b in zip(lc, lr)):
        return 'B', 'B2-numeric'
    if any(not line_equiv_b2(a, b) for a, b in zip(lc, lr)):
        return 'N', 'N3-line'                           # có dòng cùng vị trí khác nội dung
    return 'U', 'U-residual'                            # một output là tiền tố (theo dòng) của output kia


def tol_equal(a, b, rel=REL_TOL):
    """Chuẩn hoá library của harness (A3.3): gọi observe.float_tol_equal (từ 2026-10-23 vô cực chỉ bằng vô cực cùng dấu)."""
    return OB.float_tol_equal(a, b, rel)


def classify_lib(c, r, c_ub=False):
    """c, r: quan sát runner (k1, result, state_out, state_nonfinite, stdout, stderr). Kênh khác lấy từ observe.channels_lib, nên mọi
    divergence oracle ghi nhận không bao giờ bị xếp là hết khác sau chuẩn hoá (v3). state_out chứa trạng thái sau lời gọi của mọi
    trường, kể cả tham số con trỏ vào và ra, nên mọi trường khác nhau đều quan sát được từ phía gọi hàm.

    R15-UB: nhánh phòng vệ, không bao giờ chạy từ harness/metrics (chỉ divergence giữ lại được phân loại, c_ub luôn False); xem
    classify_exe."""
    ch = OB.channels_lib(c, r, completed_same=True)   # như RQ1 (Le chọn 25/10 tối)
    if not ch:
        return 'not_S', 'R-norm-lib'
    if c_ub:
        return 'not_S', 'R15-UB'                        # phòng vệ, không chạy từ metrics (docstring)
    if ch == ['stderr']:
        return 'U', 'U-stderr'                          # chỉ khác stderr
    if 'status' in ch:
        return 'N', 'N1-status'                         # kết quả runner khác (kết thúc khác kiểu, crash, timeout một phía)
    if 'state' in ch:
        return 'N', 'N4-field'                          # có trường state khác sau chuẩn hoá, kể cả NaN, inf, -inf
    lc, lr = lines_b1(r_nan(c.get('stdout') or '')), lines_b1(r_nan(r.get('stdout') or ''))   # chỉ còn khác stdout
    if lc == lr:
        return 'B', 'B1-whitespace'
    if len(lc) == len(lr) and all(line_equiv_b2(a, b) for a, b in zip(lc, lr)):
        return 'B', 'B2-numeric'
    if any(not line_equiv_b2(a, b) for a, b in zip(lc, lr)):
        return 'N', 'N3-line'
    return 'U', 'U-residual'


def lib_sanity(verifykill_json):
    """Kiểm tra dương tính: mutant mà harness bắt (đã xác nhận lệch thật) phải ra N; bản gốc so với C phải ra not_S."""
    d = json.load(open(verifykill_json))
    out = []
    for it in d['items']:
        if it.get('kind') != 'mutant' or 'runs' not in it:
            continue
        for k, run in enumerate(it['runs']):
            out.append(dict(system=it['system'], case=it['case'], mutant=it['id'], run=k,
                            mutant_vs_c=classify_lib(run['c'], run['mutant']),
                            orig_vs_c=classify_lib(run['c'], run['orig'])))
    return out


def translation_level(groups):
    """Gộp lên bản dịch theo decision-log 2026-10-12 (bổ sung). T (không đánh giá được) đứng ngay sau N:
    một bản có divergence T mà không có N thì chưa kết luận được ở mức B hay U."""
    gs = [g for g in groups if g != 'not_S']
    if not gs:
        return 'none'
    if 'N' in gs:
        return 'N'
    if 'T' in gs:
        return 'T'
    if 'U' in gs:
        return 'U'
    return 'B'


def load_exp03(d):
    out = []
    for f in sorted(glob.glob(os.path.join(d, 'divergences-*-all_seeds.json'))):
        case, system = os.path.basename(f)[len('divergences-'):-len('-all_seeds.json')].rsplit('-', 1)
        for x in json.load(open(f)):
            out.append(dict(src='exp03', case=case, system=system, layer='v0', seed='all',
                            args=(x['c_rc'], x['rust_rc'], x['c_timeout'], x['rust_timeout'],
                                  x['c_stdout'], x['rust_stdout'], x['c_ub'],
                                  len(x['c_stdout']) >= 3000 or len(x['rust_stdout']) >= 3000)))
    return out


def load_exp04(d):
    out = []
    for f in sorted(glob.glob(os.path.join(d, '*.json'))):
        j = json.load(open(f))
        for system, L in j['divergences'].items():
            for x in L:
                out.append(dict(src='exp04', case=j['case'], system=system, layer=j['layer'], seed=j['seed'],
                                args=(x['c_rc'], x['r_rc'], x['c_to'], x['r_to'], x['c_out'], x['r_out'], x['c_ub'],
                                      len(x['c_out']) >= 1500 or len(x['r_out']) >= 1500)))
    return out


def self_test():
    T = [((0, 0, False, False, '1\n', '1\n', False), 'not_S'),
         ((0, 0, False, False, '-nan\n', 'NaN\n', False), 'not_S'),
         ((0, 0, False, False, 'a\n', 'b\n', True), 'not_S'),
         ((0, 1, False, False, 'a\n', 'a\n', False), 'N'),
         ((0, 0, False, True, 'a\n', 'a', False), 'N'),
         ((0, 0, False, False, 'a  \n\n', 'a\n', False), 'B'),
         ((0, 0, False, False, '0.406993\n', '0.406994\n', False), 'B'),
         ((0, 0, False, False, '-0.000000\n', '0.000000\n', False), 'B'),
         ((0, 0, False, False, '2\n', '3\n', False), 'N'),
         ((0, 0, False, False, '0.813987\n', '0.894282\n', False), 'N'),
         ((0, 0, False, False, 'x\nmenu\n', 'x\n', False), 'U'),
         ((0, 0, False, False, 'x\ny\n', 'x\nz\nw\n', False), 'N'),
         ((0, 0, False, False, 'tail a\n', 'tail b\n', False, True), 'T'),
         ((0, 2, False, False, 'tail a\n', 'tail b\n', False, True), 'N'),
         # luật NT (v1): hai bên cùng không dừng
         ((None, None, True, True, '1\n2\n3\n4', '1\n2\n', False), 'not_S'),
         ((None, None, True, True, '1\n2\nX\n', '1\n2\nY\nZ\n', False), 'N'),
         ((None, None, True, True, 'a  \nb\n', 'a\nb\nc\n', False), 'B'),
         ((None, None, True, True, '0.406993\n1\n', '0.406994\n1\n', False), 'B'),
         ((None, None, True, True, '0.406993\n1\n', '0.406994\n2\n', False), 'N'),
         ((None, None, True, True, 'x\n', 'x\nmenu\n', False), 'not_S'),
         ((0, None, False, True, 'x\n', 'x\nmenu\n', False), 'N'),
         # v2: stderr
         ((0, 0, False, False, 'a\n', 'a\n', False, False, '', "skip ''\n"), 'U'),
         ((0, 0, False, False, 'a\n', 'a\n', False, False, 'Err 0x1f\n', 'err 0xaa  \n'), 'not_S'),
         ((0, 0, False, False, 'a\n', 'a\n', True, False, '', 'x\n'), 'not_S'),
         ((0, 0, False, False, 'a\n', 'b\n', False, False, '', 'x\n'), 'N'),
         # v5: B2 so số nguyên chính xác; mã luật NT-prefix. Kỳ vọng dạng (nhóm, luật) thì kiểm cả mã luật.
         ((0, 0, False, False, '9007199254740993\n', '9007199254740992\n', False), ('N', 'N3-line')),
         ((0, 0, False, False, '1' * 400 + '\n', '1' * 399 + '2\n', False), ('N', 'N3-line')),
         ((0, 0, False, False, '007 -0\n', '7 0\n', False), ('B', 'B2-numeric')),
         ((0, 0, False, False, '3\n', '3.0\n', False), ('B', 'B2-numeric')),
         ((0, 0, False, False, '1e3\n', '1000\n', False), ('B', 'B2-numeric')),
         ((None, None, True, True, '1\n2\n3\n4', '1\n2\n', False), ('not_S', 'NT-prefix')),
         ((0, 0, False, False, '-nan\n', 'NaN\n', False), ('not_S', 'R-NaN'))]
    for args, want in T:
        got = classify_exe(*args)
        if isinstance(want, tuple):
            assert got == want, (args, got, want)
        else:
            assert got[0] == want, (args, got, want)
    return len(T)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exp03'); ap.add_argument('--exp04'); ap.add_argument('--out', required=True)
    ap.add_argument('--verifykill', help='verify-kills.json của job verifykill (kiểm tra dương tính cho luật library)')
    ap.add_argument('--rejected', default='static_vars_fpts:kiro',
                    help='cặp case:hệ có verdict công bố là fail (ngoài phạm vi RQ1), cách nhau bởi dấu phẩy')
    a = ap.parse_args()
    rejected = {tuple(x.split(':')) for x in a.rejected.split(',') if x}
    n_tests = self_test()
    recs = (load_exp03(a.exp03) if a.exp03 else []) + (load_exp04(a.exp04) if a.exp04 else [])
    per_div = defaultdict(Counter)                      # (src, system) -> Counter(rule)
    per_pair = defaultdict(list)                        # (src, case, system) -> [group]
    per_pair_layer = defaultdict(list)                  # (src, case, system, layer, seed) -> [group]
    examples = defaultdict(list)
    per_pair_rule = defaultdict(Counter)
    for r in recs:
        if (r['case'], r['system']) in rejected:
            continue
        g, rule = classify_exe(*r['args'])
        per_pair_rule[(r['src'], r['case'], r['system'])][rule] += 1
        per_div[(r['src'], r['system'])][rule] += 1
        per_pair[(r['src'], r['case'], r['system'])].append(g)
        per_pair_layer[(r['src'], r['case'], r['system'], r['layer'], r['seed'])].append(g)
        if g in ('U', 'B') and len(examples[(r['src'], r['case'], r['system'], rule)]) < 2:
            co, ro = r['args'][4], r['args'][5]
            examples[(r['src'], r['case'], r['system'], rule)].append(dict(c_out_tail=co[-300:], r_out_tail=ro[-300:]))
    res = dict(rules_version=RULES_VERSION, self_tests=n_tests, n_records=len(recs),
               divergence_level={f'{s}|{y}': dict(c) for (s, y), c in sorted(per_div.items())},
               rejected_pairs_skipped=sorted(':'.join(x) for x in rejected),
               translation_level={f'{s}|{c}|{y}': dict(level=translation_level(gs), counts=dict(Counter(gs)),
                                                       rules=dict(per_pair_rule[(s, c, y)]))
                                  for (s, c, y), gs in sorted(per_pair.items())},
               translation_level_by_run={f'{s}|{c}|{y}|{l}|{e}': translation_level(gs)
                                         for (s, c, y, l, e), gs in sorted(per_pair_layer.items())},
               examples={'|'.join(map(str, k)): v for k, v in sorted(examples.items())})
    if a.verifykill:
        res['library_sanity'] = lib_sanity(a.verifykill)
    json.dump(res, open(a.out, 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(dict(n_records=len(recs), self_tests=n_tests,
                          translation_level={k: v['level'] for k, v in res['translation_level'].items()}), indent=1))


if __name__ == '__main__':
    main()
