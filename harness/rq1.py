"""RQ1: Algorithm 1 của harness-design.md mục 5, chạy theo case (input sinh theo case, C chạy một lần mỗi input, rồi mọi bản Rust
của case thuộc P_rep trên cùng input).

Mỗi input:
  [E] chạy C một lần, rồi từng bản Rust; so bằng observe.compare_exe / observe.equal_lib (luật NT, chạy lại gấp 10 khi một bên NT).
  [V] khác thì chạy lại thêm STAB_REPS lần trên hai phía; ổn định khi mọi lần chạy lại của mỗi phía khớp lần đầu của phía đó.
  [U] khác thì chạy C-san trên input (một lần mỗi input, dùng chung cho mọi hệ): 'ub' | 'no_report' | 'infra'.
  [R] ghi bản ghi divergence; input khớp chỉ đếm.
Đầu ra (thư mục --out): rq1-<kind>.jsonl (một bản ghi mỗi case và seed: số đếm theo hệ, thời gian từng pha, hash tập input) và
divergences-<kind>.jsonl (một bản ghi mỗi divergence, trường theo bnu_v0.py: c_rc, r_rc, c_to, r_to, c_out, r_out, c_ub).

Tham số ngân sách (theta) là tham số Protocol Freeze, đọc từ CLI. Bản này dùng cho job đo thời gian trên case pilot
(decision-log 2026-10-22, luật chọn ngân sách và sửa cách ước tính); lượt chính dùng cùng mã sau khi chốt protocol.

Miền input (decision-log 2026-10-22, miền input và rò bộ nhớ): chỉ giữ input mà runner TRACTOR truyền được, tức argv và stdin là
UTF-8 hợp lệ (vector là chuỗi JSON) và argv không chứa byte NUL. Input ngoài miền bị bỏ trước khi chạy, đếm theo tầng.
Sanitizer phía C: báo rò bộ nhớ không tính là UB; tắt phát hiện rò ở cả executable và library (khác pilot exp 04, nơi
LeakSanitizer được tính). Bản ghi giữ danh sách marker khớp. Báo cáo ASan về giới hạn bộ nhớ: trạng thái 'mem_limit', không phải UB.
Từ 2026-10-23 (decision-log): stderr vào phép so sau chuẩn hoá N (observe.norm_err); bản ghi divergence có `channels` (kênh khác) và bộ
đếm `div_stderr_only`; argv[0] chung "driver"; trần bộ nhớ 2 GB mỗi lần chạy (ASan: hard_rss_limit_mb); input chạm trần output được chạy
lại với trần gấp OUTPUT_CAP_SENS, kết quả ở `cap_sens` (phân tích độ nhạy trần 32 MiB); từ bản sửa cùng ngày áp cả input đã khớp
và cả library, divergence mới ở trần lớn ghi vào `div/*.capsens.jsonl`. Từ 2026-10-25 (F4): lần chạy ở trần lớn theo cùng luật chạy lại
gấp TIMEOUT_RERUN_FACTOR như lần chính; lỗi hạ tầng ở trần lớn là outcome 'infra' (không khớp, không divergence), đếm riêng.

Giới hạn đã biết (ghi lại, chưa xử lý):
  - input sinh từ seed không mang `env` của vector gốc (giống bộ sinh exp 04, 08); seed giữ nguyên env.
  - tầng A dựng C bằng afl-clang-fast không theo preset (như exp 04); input của tầng A vẫn chạy trên C build theo preset."""
import argparse, collections, glob, gzip, hashlib, json, math, os, re, shutil, subprocess, time, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

from . import build as BD
from . import insensitive
from . import observe as OB
from . import pairs as PR
from .checks import _cdict, _lib_inputs
from .config import INSENSITIVE_SEED, PILOT_EXE, PILOT_LIB, SAN_MARKERS, T, TIMEOUT_RERUN_FACTOR
from .gen.v1 import SHIM_C
from .gen.v2_exe import gen_inputs_v2, write_afl_dict
from .record import Store, blob, compress_files, manifest, write_inputs
from .vectors import exe_seeds, to_bytes

STAB_REPS = 2
SAN_TIMEOUT_FACTOR = 3                       # như v1.sanitizer_flags_ub
AFL_ENV = dict(AFL_SKIP_CPUFREQ='1', AFL_NO_UI='1', AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES='1', AFL_NO_AFFINITY='1', AFL_QUIET='1')
SAN_UB_MARKERS = tuple(m for m in SAN_MARKERS if m != b'LeakSanitizer')
# Chạy kèm sanitizer không đặt RLIMIT_AS (ASan cần không gian địa chỉ lớn); trần bộ nhớ do ASan: hard_rss_limit_mb (decision-log
# 2026-10-23). Báo cáo của ASan về giới hạn bộ nhớ không phải UB: SAN_MEM_MARKERS, trạng thái 'mem_limit'.
SAN_RSS_MB = int(os.environ.get('HARNESS_MEM_LIMIT', 2 << 30)) >> 20
EXE_SAN_ENV = dict(ASAN_OPTIONS=f'detect_leaks=0:hard_rss_limit_mb={SAN_RSS_MB}')
LIB_SAN_ENV = dict(ASAN_OPTIONS=f'detect_leaks=0:halt_on_error=1:verify_asan_link_order=0:hard_rss_limit_mb={SAN_RSS_MB}',
                   UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=0')
# Loại báo cáo ASan về giới hạn bộ nhớ, so ở đầu phần mô tả loại của dòng tiêu đề (sau tên công cụ), không phân biệt hoa thường.
# Dạng thật (clang 18): 'ERROR: AddressSanitizer: out of memory: allocator is trying to allocate ...' + 'SUMMARY: AddressSanitizer:
# out-of-memory'; 'ERROR: AddressSanitizer: requested allocation size ... exceeds maximum supported size' + 'SUMMARY: AddressSanitizer:
# allocation-size-too-big'; '==N==AddressSanitizer: hard rss limit exhausted (...)' (không có 'ERROR:', không có dòng SUMMARY).
SAN_MEM_MARKERS = (b'out of memory', b'out-of-memory', b'allocator is out of memory', b'requested allocation size',
                   b'allocation-size-too-big', b'hard rss limit exhausted')
# Dòng tiêu đề báo cáo sanitizer, phân biệt hoa thường (Le chọn 25/10, rà §3.3 v12, K1/M3/M4): '==N==ERROR: <công cụ>...',
# '==N==<công cụ>...' (dòng do Report() của sanitizer in, luôn có tiền tố ==pid==) hoặc dòng bắt đầu bằng 'SUMMARY: <công cụ>'. Công cụ là
# AddressSanitizer hoặc UndefinedBehaviorSanitizer; LeakSanitizer không tính. Dòng frame (ví dụ '... libsanitizer/asan/...' của GCC) và
# chữ chương trình tự in ('hand sanitizer', 'Runtime error:') không khớp. Nhóm 2: phần mô tả loại sau tên công cụ.
SAN_HEADER = re.compile(rb'(?:==\d+==(?:ERROR: )?|^SUMMARY: )(AddressSanitizer|UndefinedBehaviorSanitizer)\b:?[ \t]*(.*)')
SAN_UBSAN_LINE = b'runtime error:'
OUTPUT_CAP_SENS = 8   # phân tích độ nhạy trần output: chạy lại với trần gấp 8 khi một bên chạm trần output


def _h(x):
    return hashlib.sha256(repr(x).encode()).hexdigest()


def _san_lines(report):
    """report: bytes (stderr thô của executable) hoặc dãy luồng (bytes hoặc str) đã tách, ví dụ stdout, stderr của lời gọi library."""
    if report is None: return []
    if isinstance(report, (bytes, bytearray, str)): report = [report]
    out = []
    for s in report:
        if not s: continue
        out += (s.encode('utf-8', 'replace') if isinstance(s, str) else bytes(s)).splitlines()
    return out


def san_status(report):
    """Phân loại báo cáo sanitizer theo từng dòng; Le chọn 25/10 (rà §3.3 v12, K1/M3/M4). Chỉ xét dòng UBSan chứa 'runtime error:' và dòng
    tiêu đề SAN_HEADER, cả hai phân biệt hoa thường. Dòng tiêu đề có loại bắt đầu bằng một chuỗi SAN_MEM_MARKERS là báo cáo bộ nhớ; dòng
    tiêu đề khác (heap-buffer-overflow, SEGV, use-after-free, undefined-behavior...) và dòng 'runtime error:' là báo cáo UB; UB xét trước.
    'ub': có báo cáo UB; 'mem_limit': chỉ có báo cáo bộ nhớ; còn lại 'no_report'.
    Trả về (trạng thái, marker): marker là các chuỗi của SAN_UB_MARKERS khớp trên dòng báo cáo UB, nên khác rỗng khi và chỉ khi 'ub' (m9)."""
    found, mem = set(), False
    for l in _san_lines(report):
        if SAN_UBSAN_LINE in l: found.add(SAN_UBSAN_LINE)
        m = SAN_HEADER.search(l)
        if not m: continue
        if m.group(2).lower().startswith(SAN_MEM_MARKERS): mem = True
        else: found.add(m.group(1))
    mk = [m.decode() for m in SAN_UB_MARKERS if m in found]
    if mk: return 'ub', mk
    return ('mem_limit' if mem else 'no_report'), []


def lib_san_streams(report_path, so):
    """Luồng output của một lời gọi library cho san_status (K1, Le chọn 25/10: giải mã JSON trước khi phân loại theo dòng). Report của
    runner TRACTOR là JSON một dòng {"<vector>": {"result": ..., "output": {"stdout": ..., "stderr": ...}, ...}} (cando2 runner.rs,
    Serialize của TestOutcome), nên phân loại trên chuỗi thô gộp output chương trình và báo cáo sanitizer vào một dòng. Lấy stderr
    đã giải mã của report, stderr của file dump (so, do observe._run_lib đọc) và infra_msg (output thô của tiến trình runner khi
    không có report). Report không giải mã được thì bỏ qua (observe cũng không đọc được nên k1 là 'infra')."""
    streams = []
    try:
        if report_path and os.path.exists(report_path):
            with open(report_path, encoding='utf-8') as f: rep = json.load(f)
        else: rep = {}
    except (ValueError, OSError):
        rep = {}
    for v in (rep.values() if isinstance(rep, dict) else []):
        if not isinstance(v, dict): continue
        o = v.get('output')
        if isinstance(o, dict): streams.append(o.get('stderr'))
    # Le chọn 25/10: chỉ stderr, như executable (stdout của lời gọi không xét). infra_msg là output của tiến trình runner khi không có report.
    streams += [so.get('stderr'), so.get('infra_msg')]
    return [s for s in streams if isinstance(s, (str, bytes)) and s]


def in_domain(argv, stdin):
    """Miền input của runner TRACTOR: argv, stdin là UTF-8 hợp lệ; argv không chứa NUL."""
    try:
        for a in argv:
            if '\x00' in a: return False
            to_bytes(a).decode('utf-8')
        to_bytes(stdin).decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


# ---------------- tầng A (AFL++ phía C) ----------------
def encode(argv, stdin):
    """Định dạng input của shim AFL (gen/v1.py SHIM_C): argv nối bằng NUL, byte 0x01, rồi stdin."""
    return b'\x00'.join(to_bytes(a) for a in argv) + b'\x01' + to_bytes(stdin)


def decode(b):
    if b'\x01' in b:
        a, s = b.split(b'\x01', 1)
        argv = [x.decode('latin-1') for x in a.split(b'\x00')] if a else []
    else:
        argv, s = [], b
    return argv, s.decode('latin-1')


def build_c_afl(B, bundle, case):
    out = f'{B}/c-afl/{bundle}/{case}'; marker = f'{out}.build.json'
    if os.path.exists(marker): return json.load(open(marker))
    shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
    env = dict(os.environ, **AFL_ENV); tc = f'{T}/{bundle}/{case}/test_case'
    steps = [['afl-clang-fast', '-c', f'{out}/shim.c', '-o', f'{out}/shim.o'],
             ['cmake', '-S', tc, '-B', out, '-G', 'Ninja', '-DCMAKE_C_COMPILER=afl-clang-fast'],
             ['cmake', '-S', tc, '-B', out, '-DCMAKE_C_FLAGS=-Dmain=__orig_main', f'-DCMAKE_EXE_LINKER_FLAGS={out}/shim.o'],
             ['cmake', '--build', out]]
    open(f'{out}/shim.c', 'w').write(SHIM_C)
    t0, log, ok = time.time(), '', True
    for cmd in steps:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if p.returncode: ok, log = False, (p.stdout + p.stderr)[-2000:]; break
    drv = f'{out}/driver'
    info = dict(ok=ok and os.path.exists(drv), bin=drv if os.path.exists(drv) else None, secs=round(time.time() - t0, 2), log=log)
    json.dump(info, open(marker, 'w'), indent=1)
    return info


def afl_layer(B, bundle, case, seeds, seed, execs, cd, tag):
    """Chạy afl-fuzz -s seed -E execs -x dictionary trên C-afl; trả về (input, thông tin)."""
    info = dict(execs=execs)
    if execs <= 0: info['status'] = 'skipped'; return [], info
    a = build_c_afl(B, bundle, case); info['build_ok'] = a['ok']
    if not a['ok']: info.update(status='afl_build_failed', log=a['log']); return [], info
    wd = f'{B}/afl/{tag}/{bundle}/{case}-s{seed}'; shutil.rmtree(wd, ignore_errors=True)
    os.makedirs(f'{wd}/in'); od = f'{wd}/out'
    for i, s in enumerate(seeds): open(f'{wd}/in/seed{i:04d}', 'wb').write(encode(s['argv'], s['stdin']))
    if not seeds: open(f'{wd}/in/empty', 'wb').write(b'\x01')
    n_dict = write_afl_dict(cd, f'{wd}/afl.dict')
    cmd = ['afl-fuzz', '-i', f'{wd}/in', '-o', od, '-s', str(seed), '-E', str(execs), '-t', '1000']
    if n_dict: cmd += ['-x', f'{wd}/afl.dict']
    t0 = time.time()
    p = subprocess.run(cmd + ['--', a['bin']], env=dict(os.environ, **AFL_ENV), capture_output=True, text=True)
    info.update(secs=round(time.time() - t0, 2), rc=p.returncode, n_dict=n_dict)
    if p.returncode: info['log'] = (p.stdout + p.stderr)[-1500:]
    files = sorted(f for k in ('queue', 'crashes', 'hangs') for f in glob.glob(f'{od}/*/{k}/id:*'))
    ins = [(*decode(open(f, 'rb').read()), 'afl') for f in files]
    info.update(status='done' if not p.returncode else 'afl_error', n=len(ins))
    shutil.rmtree(f'{wd}/in', ignore_errors=True)
    return ins, info


# ---------------- executable ----------------
def gen_exe(B, bundle, case, seed, theta, tag, insensitive=False):
    """X = vector seed (nguồn 'seed') + tầng M, MS (v2) + tầng A. Bỏ input ngoài miền runner (in_domain), bỏ trùng, giữ thứ tự.
    insensitive=True (harness/insensitive.py, decision-log 2026-10-24): chỉ các vector, không sinh tầng M, MS, A."""
    troot = f'{T}/{bundle}/{case}'
    seeds = exe_seeds(troot)
    cd, err = _cdict(B, bundle, case)
    t0 = time.time()
    X = [(s['argv'], s['stdin'], 'seed', 'S', s.get('env')) for s in seeds]
    if not insensitive:
        for layer in ('M', 'MS'):
            X += [(a, s, src, layer, None) for a, s, src in gen_inputs_v2(seeds, layer, theta['budget'], seed, cd)]
    t_gen = time.time() - t0
    afl, ainfo = afl_layer(B, bundle, case, seeds, seed, 0 if insensitive else theta['afl_execs'], cd, tag)
    X += [(a, s, src, 'A', None) for a, s, src in afl]
    # Báo theo tầng (Le chọn 25/10): số sinh ra (n_gen_by_layer), số ngoài miền runner (n_out_of_domain), số trùng với input đã có ở
    # tầng trước (n_dup_by_layer, bỏ trùng theo thứ tự S, M, MS, A) và số thực thi (n_by_layer).
    seen, out, ood, dup = set(), [], collections.Counter(), collections.Counter()
    for x in X:
        if not in_domain(x[0], x[1]): ood[x[3]] += 1; continue
        k = _h((x[0], x[1], x[4]))
        if k in seen: dup[x[3]] += 1; continue
        seen.add(k); out.append(x)
    return out, dict(n_seed=len(seeds), cdict_error=err, gen_secs=round(t_gen, 2), afl=ainfo, n_out_of_domain=dict(ood),
                     n_gen_by_layer=dict(collections.Counter(x[3] for x in X)), n_dup_by_layer=dict(dup),
                     n_by_layer=dict(collections.Counter(x[3] for x in out)), input_set_sha256=_h([x[:2] for x in out]))


# ---------------- bằng chứng chạm trần bộ nhớ ----------------
# Rà soát kỹ thuật 2026-10-23 (finding 9 của bản rà §3.3): chạm trần bộ nhớ nhận bằng chuỗi trong stderr (observe.MEM_MARKERS), nên cần
# mẫu để kiểm tay và mẫu số. Đếm mọi lần quan sát cuối (sau chạy lại khi một bên vượt ngân sách) bị xếp chạm trần, theo phía và nhánh
# (khớp hoặc divergence); ghi tối đa MEM_SAMPLE bản ghi mỗi (case, hệ, phía) vào `div/*.memlimit.jsonl`, kèm marker khớp và đuôi stderr.
# Không đổi quyết định nào.
MEM_SAMPLE = 20


def _is_mem(o, kind):
    return o.get('status') == 'mem_limit' if kind == 'exe' else o.get('result') == 'MemLimit'


def mem_note(cnt, memf, key, kind, c1, r1, branch, src):
    for side, o in (('c', c1), ('r', r1)):
        if not _is_mem(o, kind): continue
        cnt[f'mem_limit_{side}_{branch}'] += 1
        if cnt[f'mem_limit_{side}_{branch}'] + cnt[f'mem_limit_{side}_{"div" if branch == "match" else "match"}'] <= MEM_SAMPLE:
            err = o.get('err') if kind == 'exe' else (o.get('mem_context') or o.get('stderr') or '').encode('utf-8', 'replace')
            memf.write(json.dumps(dict(key=key, kind=kind, side=side, branch=branch, source=src, marker=o.get('mem_marker'),
                                       other_side_status=(r1 if side == 'c' else c1).get('status' if kind == 'exe' else 'result'),
                                       err_tail=(err or b'')[-1500:].decode('latin-1')), ensure_ascii=False, sort_keys=True) + '\n')


# ---------------- bộ đếm cho quy tắc báo cáo R21, R23, R28 ----------------
# Rà soát kỹ thuật 2026-10-23: các số này cần cho reporting-rules nhưng trước đây không được ghi (nhánh khớp không lưu gì). Không đổi quyết
# định nào. Đếm trên quan sát cuối của mỗi (input, hệ), sau chạy lại khi một bên vượt ngân sách.
#   R28: trạng thái kết thúc của C và của Rust (executable: status; library: result của runner).
#   R23: input hai bên cùng vượt ngân sách mà khớp theo luật NT; executable cộng thêm số byte prefix đã so.
#   F7: trần output một phía (cap_c_only, cap_r_only, cap_one_side_match là phần nằm ở nhánh khớp) và hai phía (cap_both).
#   R21: library, input khớp theo sai số tương đối 1e-6 nhưng khác khi so chính xác (sai số 0, NaN vẫn bằng NaN); ghi mẫu tối đa
#        EXACT_SAMPLE mỗi (case, hệ) vào `div/*.exact.jsonl`. Đây là số input, chưa qua kiểm ổn định và sanitizer.
EXACT_SAMPLE = 20


def obs_note(cnt, kind, c1, r1, eq, info=None, exactf=None, key=None, src=None):
    st = (lambda o: o['status']) if kind == 'exe' else (lambda o: o.get('result') or o.get('k1'))
    cnt[f'c_status:{st(c1)}'] += 1; cnt[f'r_status:{st(r1)}'] += 1
    # F7, đếm trần một phía: một bên chạm trần output, bên kia không (cả nhánh khớp: bên kia có thể vượt ngân sách theo cách khác, luật NT).
    cap = 'output_limit' if kind == 'exe' else 'OutputLimit'
    cc, rc = st(c1) == cap, st(r1) == cap
    if cc != rc:
        cnt['cap_c_only' if cc else 'cap_r_only'] += 1
        cnt['cap_one_side_match'] += bool(eq)
    elif cc: cnt['cap_both'] += 1
    both_nt = OB.is_nt(c1) and OB.is_nt(r1) if kind == 'exe' else OB.lib_timeout(c1) and OB.lib_timeout(r1)
    if eq and both_nt:
        cnt['both_nt_match'] += 1
        if kind == 'exe' and info and info.get('nt_prefix_bytes') is not None:
            cnt['both_nt_prefix_bytes'] += info['nt_prefix_bytes']
            cnt['both_nt_prefix_zero'] += info['nt_prefix_bytes'] == 0      # khớp mà không so được byte nào (Le chọn 25/10, §3.8)
    if kind == 'lib' and eq and not both_nt and not OB.float_tol_equal(c1.get('state_out'), r1.get('state_out'), rel=0):
        cnt['match_tol_not_exact'] += 1
        if exactf is not None and cnt['match_tol_not_exact'] <= EXACT_SAMPLE:
            exactf.write(json.dumps(dict(key=key, source=src, c_state=c1.get('state_out'), r_state=r1.get('state_out')),
                                    ensure_ascii=False, sort_keys=True, default=str) + '\n')


# ---------------- phân tích độ nhạy trần output ----------------
# Decision-log 2026-10-23 (R29): mọi input mà một bên chạm trần output được chạy lại hai bên với trần gấp OUTPUT_CAP_SENS. Bản đầu
# (19fc56e) chỉ chạy lại trong nhánh divergence, nên input hai bên cùng chạm trần mà prefix trùng không được chạy lại và phân tích chỉ
# có thể bớt divergence. Sửa 2026-10-23 (Le duyệt): chạy lại cả nhánh khớp; divergence mới ở trần lớn ghi vào file `*.capsens.jsonl`
# riêng (file divergence chính giữ nguyên nghĩa), kèm kiểm ổn định ở trần lớn và sanitizer phía C như lượt chính.
def cap_hit_exe(c, r):
    return 'output_limit' in (c['status'], r['status'])


def cap_hit_lib(c, r):
    return 'OutputLimit' in (c.get('result'), r.get('result'))


# Sửa 2026-10-25 (F4, master plan Chương 3; phiên kỹ thuật, chờ Le xác nhận): lần chạy ở trần lớn dùng cùng luật như lần chạy chính, chỉ
# đổi trần output (decision-log 2026-10-14: mỗi phân tích độ nhạy đổi đúng một yếu tố). (1) Bắt đầu ở timeout của case; một bên vượt ngân
# sách, bên kia dừng thì chạy lại hai bên với timeout gấp TIMEOUT_RERUN_FACTOR trước khi kết luận (executable: observe.compare_exe; library:
# như nhánh chạy lại trong rq1_lib_case). Bản trước chạy một lần ở timeout đã nhân sẵn nếu lần chính có chạy lại, và không chạy lại.
# (2) Lỗi hạ tầng ở trần lớn (library: k1 'infra' sau thử lại, ở lần chạy, lần chạy lại hay lần kiểm ổn định; executable: trạng thái
# ngoài EXE_OBSERVED) cho outcome 'infra': không tính là khớp hay divergence mới, đếm riêng `cap_sens_infra_match`, `cap_sens_infra_div`.
# Bản trước so 'infra' như một trạng thái kết thúc, nên lỗi hạ tầng thành divergence mới.
EXE_OBSERVED = ('exit', 'signal') + OB.NT


def _outcome(infra, eq):
    return 'infra' if infra else ('equal' if eq else 'div')


def cap_sens_exe(c_bin, r_bin, argv, stdin, timeout, env):
    """Chạy lại hai bên với trần output gấp OUTPUT_CAP_SENS, theo observe.compare_exe (luật NT và chạy lại gấp TIMEOUT_RERUN_FACTOR).
    timeout: timeout của case, chưa nhân. Trả về (info, c8, r8); info['outcome'] là 'equal' | 'div' | 'infra', info['equal'] là None khi
    'infra'; info['timeout_rerun'] cho biết lần kết luận dùng timeout gấp TIMEOUT_RERUN_FACTOR (dùng cho kiểm ổn định ở trần lớn)."""
    cap = OB.OUTPUT_CAP * OUTPUT_CAP_SENS
    eq, c8, r8, x = OB.compare_exe(c_bin, r_bin, argv, stdin, timeout, env=env, cap=cap)
    infra = not (c8['status'] in EXE_OBSERVED and r8['status'] in EXE_OBSERVED)
    return dict(factor=OUTPUT_CAP_SENS, outcome=_outcome(infra, eq), equal=None if infra else eq, c_status=c8['status'],
                r_status=r8['status'], timeout_rerun=x['timeout_rerun'], timeout_confirmed=x['timeout_confirmed']), c8, r8


def cap_sens_timeout(timeout, cs8):
    """Timeout cho kiểm ổn định ở trần lớn: như lần chạy chính, gấp TIMEOUT_RERUN_FACTOR khi lần kết luận ở trần lớn là lần chạy lại."""
    return timeout * (TIMEOUT_RERUN_FACTOR if cs8.get('timeout_rerun') else 1)


def cap_sens_stable_exe(c_bin, r_bin, argv, stdin, timeout, env, c8, r8):
    """timeout: cap_sens_timeout(timeout của case, info của cap_sens_exe)."""
    cap = OB.OUTPUT_CAP * OUTPUT_CAP_SENS
    reps_c = [OB.run_exe(c_bin, argv, stdin, timeout, env, cap=cap) for _ in range(STAB_REPS)]
    reps_r = [OB.run_exe(r_bin, argv, stdin, timeout, env, cap=cap) for _ in range(STAB_REPS)]
    return all(OB.equal_exe(c8, x) for x in reps_c) and all(OB.equal_exe(r8, x) for x in reps_r)


def _infra(*obs):
    return any(o.get('k1') == 'infra' for o in obs)


def cap_sens_lib(rb, croot, rroot, p, timeout, dumps):
    """Library: như cap_sens_exe, theo nhánh chạy lại của rq1_lib_case. dumps: tiền tố đường dẫn file dump. timeout: timeout của case.
    Trả về (info, c8, r8)."""
    cap = OB.OUTPUT_CAP * OUTPUT_CAP_SENS
    c8 = _rl(rb, croot, p, timeout, False, f'{dumps}.C.cap.dump', cap=cap)
    r8 = _rl(rb, rroot, p, timeout, True, f'{dumps}.R.cap.dump', cap=cap)
    rerun = confirmed = False; eq = None
    if not _infra(c8, r8):
        eq = _eq_lib(c8, r8)
        if not eq and OB.lib_timeout(c8) != OB.lib_timeout(r8):
            rerun = True
            c8 = _rl(rb, croot, p, timeout * TIMEOUT_RERUN_FACTOR, False, f'{dumps}.C.cap.re.dump', cap=cap)
            r8 = _rl(rb, rroot, p, timeout * TIMEOUT_RERUN_FACTOR, True, f'{dumps}.R.cap.re.dump', cap=cap)
            if not _infra(c8, r8):
                confirmed = OB.lib_timeout(c8) != OB.lib_timeout(r8)
                eq = _eq_lib(c8, r8)
    infra = _infra(c8, r8)
    return dict(factor=OUTPUT_CAP_SENS, outcome=_outcome(infra, eq), equal=None if infra else eq, c_result=c8.get('result'),
                r_result=r8.get('result'), c_k1=c8.get('k1'), r_k1=r8.get('k1'), timeout_rerun=rerun, timeout_confirmed=confirmed), c8, r8


def cap_sens_stable_lib(rb, croot, rroot, p, timeout, dumps, c8, r8):
    """Kiểm ổn định ở trần lớn như lần chạy chính: mỗi phía thêm STAB_REPS lần, so với lần đầu của phía đó. Lỗi hạ tầng ở lần kiểm thì
    trả None (như nhánh chính: không phải divergence không ổn định). timeout: cap_sens_timeout(...)."""
    cap = OB.OUTPUT_CAP * OUTPUT_CAP_SENS
    reps_c = [_rl(rb, croot, p, timeout, False, f'{dumps}.v{k}.C.cap.dump', cap=cap) for k in range(STAB_REPS)]
    reps_r = [_rl(rb, rroot, p, timeout, True, f'{dumps}.v{k}.R.cap.dump', cap=cap) for k in range(STAB_REPS)]
    if _infra(*reps_c, *reps_r): return None
    return all(_eq_lib(c8, y) for y in reps_c) and all(_eq_lib(r8, y) for y in reps_r)


# Timeout theo case (Le chọn 25/10, F3, exp 20): max(timeout gốc, ceil(C_TIME_FACTOR × thời gian C lớn nhất trên vector)), thời gian C đo
# trước trên máy đo (harness/data/exe-c-time.json, job c-time-exe tại 8d48aa2), không nhìn phía Rust. Case không có trong bảng: timeout gốc.
# Luật chạy lại gấp TIMEOUT_RERUN_FACTOR và kiểm sanitizer gấp SAN_TIMEOUT_FACTOR nhân trên timeout của case.
C_TIME_FACTOR = 3
_CT = os.path.join(os.path.dirname(__file__), 'data', 'exe-c-time.json')
C_TIME = json.load(open(_CT))['max_c_secs']; C_TIME_SHA = hashlib.sha256(open(_CT, 'rb').read()).hexdigest()


def gen_params():
    """Tham số bộ sinh ghi vào manifest (F8)."""
    from .gen import stategen_v2 as SG, v1 as G1, v2_exe as G2
    return dict(exe_p_v2=G2.P_V2, layer_rng_offset=G1.LAYER_RNG_OFFSET, lib_p_dict=SG.P_DICT, lib_p_sweep=SG.P_SWEEP, lib_small_max=SG.SMALL_MAX,
                c_time_factor=C_TIME_FACTOR, stab_reps=STAB_REPS)


def case_timeout(bundle, case, base):
    return max(base, math.ceil(C_TIME_FACTOR * C_TIME.get(f'{bundle}/{case}', 0)))


# Case executable không đọc input (harness/insensitive.py) chạy đúng các vector ở mọi seed, nên chỉ chạy ở seed INSENSITIVE_SEED
# (config; Le chọn 25/10); seed khác ghi trạng thái 'insensitive_other_seed', metrics chỉ đòi seed này cho các bản dịch của case đó.


# ---------------- quyết định một input: judge_exe, judge_lib ----------------
# Q1 (a) (Le duyệt 25/10, docs/proposal/a3-a7-package-plan.md mục 2.3, 6 việc 1): vòng quyết định theo input tách khỏi rq1_*_case để
# RQ1 và harness/sweep.py (mutant control: cùng oracle, binary hoặc root phía Rust là mutant) gọi chung. Refactor thuần: thứ tự và số
# lần gọi runner, bản ghi và bộ đếm như trước (tests/test_a37_judge.py so với golden sinh trên mã trước khi tách). Hàm judge không ghi
# file, không đụng bộ đếm; bên gọi giữ hai việc đó.
#
# Trường của dict trả về (chung exe và lib):
#   verdict    'match' | 'div' | 'infra' (chỉ library: lỗi hạ tầng sau thử lại, input không quan sát được cho phía Rust này)
#   infra_at   library: 'rust' (lần chạy Rust đầu), 'rerun' (lần chạy lại gấp TIMEOUT_RERUN_FACTOR), 'stability' (lần kiểm ổn định);
#              None khi verdict không phải 'infra'. Với 'stability', eq, c, r là của lần so trước kiểm ổn định (bên gọi vẫn đếm
#              mem_note, obs_note như mã trước khi tách)
#   eq         kết quả so (luật NT, chạy lại khi một bên vượt ngân sách); None khi infra_at 'rust' hoặc 'rerun'
#   c, r       quan sát cuối của hai phía (sau chạy lại nếu có)
#   info       exe: info của observe.compare_exe (timeout_rerun, timeout_confirmed, nt_prefix_bytes hoặc channels, thêm cap_sens ở nhánh
#              divergence chạm trần); lib: timeout_rerun, timeout_confirmed, thêm channels và cap_sens ở nhánh divergence. Bản ghi
#              divergence của RQ1 trải dict này (**info)
#   channels   info.get('channels')
#   cap_hit    một bên chạm trần output ở quan sát cuối
#   stable     nhánh divergence: mọi lần chạy lại của mỗi phía khớp lần đầu của phía đó; None ở nhánh khớp
#   san        kết quả sanitizer phía C (dict của _exe_san, lib_san), lấy từ cache; None khi quyết định không cần
#   retained   nhánh divergence: stable và san 'no_report' (cùng điều kiện với san_counts); None ở nhánh khớp
#   c_flag     nhánh divergence: C crash (exe: signal; lib: LIB_CRASH) và san 'no_report'
#   cap_sens   info độ nhạy trần output (cap_sens_exe, cap_sens_lib): nhánh khớp chạm trần và nhánh divergence chạm trần; None nếu không
#   c8, r8, stable8, channels8   nhánh khớp chạm trần: quan sát ở trần lớn; stable8, channels8 chỉ khi cap_sens['outcome'] là 'div'
#   t0_div     time.time() lúc bắt đầu xử lý divergence (nhánh divergence, hoặc nhánh khớp chạm trần), None nếu không có; bên gọi
#              cộng time.time() - t0_div vào pha divergence_handling sau khi ghi file, như trước
# cache: dict dùng chung cho mọi phía Rust trên cùng một input. 'co': quan sát C thường ở timeout của case, bên gọi chạy trước (library:
# bên gọi đã loại k1 'invalid_input' và 'infra'); 'san': kết quả sanitizer phía C, None khi chưa chạy, judge chạy khi cần và ghi vào.
def _judge(**kw):
    j = dict(verdict=None, infra_at=None, eq=None, c=None, r=None, info=None, channels=None, cap_hit=False, stable=None, san=None,
             retained=None, c_flag=None, cap_sens=None, c8=None, r8=None, stable8=None, channels8=None, t0_div=None)
    j.update(kw); return j


def judge_exe(c_bin, cs, r_bin, argv, stdin, env, timeout, cache):
    """Một input executable cho một binary phía Rust. c_bin: binary C; cs: build C-san (BD.build_c_exe(..., san=True)); r_bin: binary
    phía Rust (bản dịch hoặc mutant); timeout: timeout của case (case_timeout), chưa nhân. Trường trả về: xem chú thích phía trên."""
    co = cache['co']
    def san():
        if cache.get('san') is None:
            cache['san'] = _exe_san(cs, argv, stdin, timeout, env, co['status'])
        return cache['san']
    eq, c1, r1, info = OB.compare_exe(c_bin, r_bin, argv, stdin, timeout, co, env)
    j = _judge(verdict='match' if eq else 'div', eq=eq, c=c1, r=r1, info=info, channels=info.get('channels'), cap_hit=cap_hit_exe(c1, r1))
    if eq:
        if j['cap_hit']:                                             # độ nhạy trần output, nhánh khớp
            j['t0_div'] = time.time()
            cs8, c8, r8 = cap_sens_exe(c_bin, r_bin, argv, stdin, timeout, env)   # F4: cùng luật chạy lại
            j.update(cap_sens=cs8, c8=c8, r8=r8)
            if cs8['outcome'] == 'div':                              # thứ tự như trước: sanitizer rồi mới kiểm ổn định ở trần lớn
                to8 = cap_sens_timeout(timeout, cs8)
                j['san'] = san()
                j.update(channels8=OB.channels_exe(c8, r8), stable8=cap_sens_stable_exe(c_bin, r_bin, argv, stdin, to8, env, c8, r8))
        return j
    j['t0_div'] = time.time()
    to = timeout * (TIMEOUT_RERUN_FACTOR if info['timeout_rerun'] else 1)
    reps_c = [OB.run_exe(c_bin, argv, stdin, to, env) for _ in range(STAB_REPS)]
    reps_r = [OB.run_exe(r_bin, argv, stdin, to, env) for _ in range(STAB_REPS)]
    stable = all(OB.equal_exe(c1, x) for x in reps_c) and all(OB.equal_exe(r1, x) for x in reps_r)
    sn = san()
    j.update(stable=stable, san=sn, retained=_retained(stable, sn['status']),
             c_flag=c1['status'] in ('signal',) and sn['status'] == 'no_report')
    if j['cap_hit']:                                                 # độ nhạy trần output, nhánh divergence (decision-log 2026-10-23)
        info['cap_sens'] = j['cap_sens'] = cap_sens_exe(c_bin, r_bin, argv, stdin, timeout, env)[0]   # F4: cùng luật chạy lại
    return j


def rq1_exe_case(B, bundle, case, pairs, seed, theta, timeout, div_path, tag):
    T0 = time.time(); ph = {}
    base_timeout, timeout = timeout, case_timeout(bundle, case, timeout)
    rec = dict(key=f'{bundle}/{case}/s{seed}', kind='exe', bundle=bundle, case=case, seed=seed, theta=theta, timeout=timeout,
               timeout_base=base_timeout)
    t = time.time()
    c = BD.build_c_exe(B, bundle, case); cs = BD.build_c_exe(B, bundle, case, san=True)
    rust = {p['system']: BD.build_rust_exe(B, p['system'], bundle, case, p['harvest_case']) for p in pairs}
    ph['build'] = round(time.time() - t, 2)
    rec['c_build'] = {k: c.get(k) for k in ('ok', 'preset', 'sha256')}; rec['c_san_build_ok'] = cs.get('ok')
    rec['rust_build'] = {s: {k: r.get(k) for k in ('ok', 'sha256', 'rustc_bootstrap')} for s, r in rust.items()}
    if not c['ok']:     # F7: ghi pair_status để mọi bản dịch của case còn trong mẫu số với mã rời P_test riêng (trước: case biến mất)
        rec.update(status='c_build_failed', pair_status={p['system']: 'c_build_failed' for p in pairs}, phases=ph,
                   secs=round(time.time() - T0, 2))
        return rec
    t = time.time()
    ins, ins_ev = insensitive.check(c['bin'], f'{T}/{bundle}/{case}/test_case')
    rec['input_insensitive'] = ins; rec['input_insensitive_evidence'] = ins_ev
    if ins:
        # Hàng đợi master plan dòng 5 (F3, Le chọn 26/10 "kiểm thêm binary Rust, báo số"): tiêu chí chỉ xét binary C; ghi thêm ký hiệu
        # đọc input mà binary Rust của từng bản dịch nhập (list, rỗng khi không có), None khi không đọc được bảng ký hiệu động (ví dụ
        # binary tĩnh). Chỉ ghi, không đổi tầng input được sinh hay quyết định nào. Bản dịch build lỗi không có khoá.
        rec['rust_input_syms'] = {s: insensitive.input_syms(r['bin']) if r.get('bin') else None for s, r in rust.items() if r.get('ok')}
        rec['rust_input_syms_baseline'] = insensitive.rust_baseline()      # tập nền đã trừ (dòng 5, Le chọn 26/10)
    if ins and seed != INSENSITIVE_SEED:
        rec.update(status='insensitive_other_seed', phases=ph, secs=round(time.time() - T0, 2)); return rec
    X, ginfo = gen_exe(B, bundle, case, seed, theta, tag, insensitive=ins)
    ph['gen_afl'] = round(time.time() - t, 2); rec['gen'] = ginfo; rec['n_inputs'] = len(X)
    # F8 (Le chọn 25/10): lưu đủ tập input đã chạy (sau bỏ trùng và ngoài miền), nén; hash theo tầng.
    rec['inputs_file'] = write_inputs(inputs_path(div_path), (dict(i=i, layer=x[3], source=x[2], argv=x[0], stdin=x[1], env=x[4])
                                                              for i, x in enumerate(X)))
    ginfo['input_sha256_by_layer'] = {L: _h([x[:2] for x in X if x[3] == L]) for L in sorted({x[3] for x in X})}
    systems = [s for s, r in rust.items() if r['ok']]
    cnt = {s: collections.Counter() for s in systems}
    for s, r in rust.items():
        if not r['ok']: cnt.setdefault(s, collections.Counter())['rust_build_failed'] = 1
    divf = open(div_path, 'a'); capf = open(div_path.replace('.jsonl', '.capsens.jsonl'), 'a')
    memf = open(div_path.replace('.jsonl', '.memlimit.jsonl'), 'a')
    t = time.time(); t_div = 0.0
    for i, (argv, stdin, src, layer, env) in enumerate(X):
        cache = dict(co=OB.run_exe(c['bin'], argv, stdin, timeout, env), san=None)   # C và C-san một lần mỗi input, chung mọi hệ
        for s in systems:
            j = judge_exe(c['bin'], cs, rust[s]['bin'], argv, stdin, env, timeout, cache)
            eq, c1, r1, info = j['eq'], j['c'], j['r'], j['info']
            cnt[s]['observed'] += 1
            mem_note(cnt[s], memf, f'{bundle}/{case}/s{seed}/{s}/{i}', 'exe', c1, r1, 'match' if eq else 'div', src)
            obs_note(cnt[s], 'exe', c1, r1, eq, info)
            if eq:
                cnt[s]['match'] += 1
                if j['cap_hit']:                                     # độ nhạy trần output, nhánh khớp
                    cnt[s]['cap_hit_match'] += 1
                    cs8, c8, r8 = j['cap_sens'], j['c8'], j['r8']    # F4: cùng luật chạy lại
                    cnt[s]['cap_sens_timeout_rerun'] += cs8['timeout_rerun']
                    if cs8['outcome'] == 'infra':                    # F4: không quan sát được ở trần lớn, không là khớp hay divergence
                        cnt[s]['cap_sens_infra_match'] += 1
                    elif cs8['outcome'] == 'div':
                        cnt[s]['cap_sens_new_div'] += 1
                        san = j['san']
                        capf.write(json.dumps(dict(key=f'{bundle}/{case}/s{seed}/{s}/{i}', kind='exe', bundle=bundle, case=case,
                                                   seed=seed, system=s, idx=i, source=src, layer=layer, branch='match',
                                                   argv=[blob(to_bytes(a)) for a in argv], stdin=blob(to_bytes(stdin)), env=env,
                                                   cap_sens=cs8, channels=j['channels8'], stable=j['stable8'],
                                                   san=san['status'], san_markers=san['markers'], c_ub=san['status'] == 'ub',
                                                   c_out=blob(c8['out']), r_out=blob(r8['out']), c_err=blob(c8['err']),
                                                   r_err=blob(r8['err'])), ensure_ascii=False, sort_keys=True) + '\n')
                    t_div += time.time() - j['t0_div']
                continue
            stable, san, c_flag = j['stable'], j['san'], j['c_flag']
            cnt[s]['div'] += 1; cnt[s]['div_stable'] += stable
            retained = san_counts(cnt[s], stable, san['status'])
            cnt[s]['div_stderr_only'] += info.get('channels') == ['stderr']
            if j['cap_hit']:                                         # độ nhạy trần output, nhánh divergence (decision-log 2026-10-23)
                cnt[s]['cap_hit_div'] += 1; cnt[s]['cap_sens_timeout_rerun'] += info['cap_sens']['timeout_rerun']
                cnt[s]['cap_sens_infra_div'] += info['cap_sens']['outcome'] == 'infra'   # F4: equal None, metrics giữ kết quả chính
            d = dict(key=f'{bundle}/{case}/s{seed}/{s}/{i}', kind='exe', bundle=bundle, case=case, seed=seed, system=s, idx=i,
                     source=src, layer=layer, argv=[blob(to_bytes(a)) for a in argv], stdin=blob(to_bytes(stdin)), env=env,
                     c_status=c1['status'], r_status=r1['status'], c_rc=c1['rc'] if c1['status'] == 'exit' else (-c1['sig'] if c1['sig'] else None),
                     r_rc=r1['rc'] if r1['status'] == 'exit' else (-r1['sig'] if r1['sig'] else None),
                     c_to=OB.is_nt(c1), r_to=OB.is_nt(r1), c_out=blob(c1['out']), r_out=blob(r1['out']),
                     c_err=blob(c1['err']), r_err=blob(r1['err']), stable=stable, san=san['status'], san_markers=san['markers'],
                     retained=retained, san_attempts=san.get('attempts'), c_mem_marker=c1.get('mem_marker'),
                     r_mem_marker=r1.get('mem_marker'), c_ub=san['status'] == 'ub', c_flag=c_flag, **info)
            divf.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + '\n')
            t_div += time.time() - j['t0_div']
    divf.close(); capf.close(); memf.close()
    ph['execute'] = round(time.time() - t, 2); ph['divergence_handling'] = round(t_div, 2)
    rec['counts'] = {s: dict(v) for s, v in cnt.items()}
    rec['pair_status'] = {s: pair_status(v, len(X)) for s, v in cnt.items()}
    rec.update(status='done', phases=ph, secs=round(time.time() - T0, 2), n_systems=len(systems))
    return rec


# Kết quả kiểm sanitizer phía C cho một input (sửa 2026-10-23 theo rà độc lập, khớp decision-log 2026-10-20 cổng A4.2 phần 1):
#   'ub'           sanitizer báo UB: input không làm bằng chứng;
#   'no_report'    C-san chạy xong không báo: input dùng được;
#   'inconclusive' C-san vượt ngân sách (timeout gấp SAN_TIMEOUT_FACTOR, trần output, trần RSS của ASan): không biết có UB hay không;
#                  divergence không vào S, đếm riêng (div_stable_san_inconclusive) để báo cạnh tỉ lệ;
#   'infra'        C-san không build được, hoặc chết không có diagnostic trong khi C thường không chết: thử lại tới SAN_ATTEMPTS lần;
#                  còn 'infra' thì bản dịch rời P_test nếu quyết định của nó cần kiểm này (pair_status 'san_infra').
# Bản cũ xếp timeout và chết không diagnostic vào 'no_report', còn build lỗi làm divergence biến mất âm thầm khỏi tập giữ lại.
SAN_ATTEMPTS = 3


def classify_san(st, mk, budget, crashed, c_crashed):
    # Sửa 2026-10-26 (Le chọn, hàng đợi master plan dòng 24): UB xét trước vượt ngân sách và chạm trần bộ nhớ, như san_status xét UB trước
    # dấu hiệu bộ nhớ (2026-10-25). Bản cũ: lần chạy C-san báo UB rồi vượt ngân sách bị xếp 'inconclusive'.
    if st == 'ub': return 'ub'
    if st == 'mem_limit' or budget: return 'inconclusive'
    if crashed and not c_crashed: return 'infra'
    return 'no_report'


def _exe_san(cs, argv, stdin, timeout, env, c_status=None, sink=None):
    """sink (F5, 2026-10-25): danh sách; nếu có, nhận quan sát thô của từng lần thử (RQ2 lưu đủ). Không đổi kết quả trả về."""
    if not cs.get('ok'): return dict(status='infra', markers=[], attempts=0, cause='c_san_build_failed')
    for k in range(1, SAN_ATTEMPTS + 1):
        so = OB.run_exe(cs['bin'], argv, stdin, timeout * SAN_TIMEOUT_FACTOR, dict(env or {}, **EXE_SAN_ENV), san=True)
        st, mk = san_status(so['err'])
        status = classify_san(st, mk, so['status'] in ('timeout', 'output_limit'), so['status'] == 'signal', c_status == 'signal')
        if sink is not None: sink.append(dict(attempt=k, san_status=st, markers=mk, status=status, obs=so))
        if status != 'infra': break
    return dict(status=status, markers=mk, attempts=k, san_run_status=so['status'], err_tail=so['err'][-800:].decode('latin-1'))


def san_counts(cnt, stable, st):
    """Bộ đếm và trường `retained` dùng cùng một điều kiện: divergence ổn định và sanitizer phía C chạy xong không báo."""
    cnt['div_stable_noub'] += stable and st == 'no_report'
    cnt['div_stable_san_inconclusive'] += stable and st == 'inconclusive'
    cnt['div_stable_san_infra'] += stable and st == 'infra'
    return _retained(stable, st)


def _retained(stable, st):
    return stable and st == 'no_report'


def pair_status(v, n_inputs):
    """P_test khi mọi input đã quan sát. Rời P_test: build Rust lỗi; harness chưa quan sát hết input (lỗi hạ tầng sau khi thử lại);
    hoặc không có divergence nào vào S mà có divergence ổn định chỉ thiếu kiểm sanitizer vì lỗi hạ tầng (quyết định phụ thuộc kiểm đó)."""
    if v.get('rust_build_failed'): return 'rust_build_failed'
    if n_inputs == 0: return 'no_inputs'      # Le chọn 25/10 (rà §3.3 v10): không có input nào được quan sát, rời P_test với mã riêng
    if v.get('observed') != n_inputs: return 'incomplete'
    if not v.get('div_stable_noub') and v.get('div_stable_san_infra'): return 'san_infra'
    return 'P_test'


# ---------------- library ----------------
def lib_san(rb, csroot, vec, timeout, dump, preload, c_obs=None, sink=None):
    """Chạy C-san (runner + .so có ASan, UBSan) trên một input library. Báo cáo sanitizer nằm trong stderr mà runner ghi vào file
    report; khi tiến trình con chết thì file dump trống. Đọc cả report, như observe.run_lib tính san_flag (sửa 2026-10-22: bản đầu
    chỉ đọc dict kết quả nên bỏ sót báo cáo, xem decision-log cùng ngày).
    Sửa 2026-10-23: phân loại theo classify_san (thêm 'inconclusive', 'infra'), thử lại khi 'infra'; csroot None (C-san .so không build
    được) là 'infra'. c_obs: quan sát C thường của input, để biết C thường có chết không.
    Sửa 2026-10-25 (Le chọn 25/10, rà §3.3 v12, K1): phân loại trên luồng đã giải mã (lib_san_streams), không trên chuỗi JSON thô.
    sink (F5, 2026-10-25): như _exe_san, nhận quan sát thô và luồng đã giải mã của từng lần thử. Không đổi kết quả trả về."""
    if not csroot: return dict(status='infra', markers=[], attempts=0, cause='c_san_build_failed')
    for k in range(1, SAN_ATTEMPTS + 1):
        so = OB.run_lib(rb, csroot, vec, timeout, False, dump, preload, LIB_SAN_ENV, keep_files=True)
        streams = lib_san_streams(f'{dump}.report.json', so)   # Le chọn 25/10 (rà §3.3 v12, K1): giải mã report rồi mới phân loại
        for f in (dump, f'{dump}.report.json'):
            if os.path.exists(f): os.remove(f)
        st, mk = san_status(streams)
        # Sửa 2026-10-26 (Le chọn, hàng đợi master plan dòng 6): runner C-san vượt hạn chót của tiến trình (observe._run_lib, rc None,
        # 'runner process timeout') là vượt ngân sách, ra 'inconclusive' như executable; trước đó xếp 'infra' (thử lại, có thể thành hao hụt).
        deadline = so.get('k1') == 'infra' and so.get('rc', 0) is None and so.get('infra_msg') == RUNNER_DEADLINE_MSG
        if so.get('k1') == 'infra' and st != 'ub' and not deadline: status = 'infra'
        else:
            status = classify_san(st, mk, OB.lib_timeout(so) or deadline, so.get('result') in LIB_CRASH,
                                  bool(c_obs) and c_obs.get('result') in LIB_CRASH)
        if sink is not None: sink.append(dict(attempt=k, san_status=st, markers=mk, status=status, obs=so, streams=streams))
        if status != 'infra': break
    return dict(status=status, markers=mk, attempts=k, san_result=so.get('result'), san_k1=so.get('k1'))


LIB_CRASH = ('SegmentationFault', 'Panic', 'UnknownFailure')
RUNNER_DEADLINE_MSG = 'runner process timeout'                  # observe._run_lib, khi vượt hạn chót của tiến trình runner


# RQ1 so library với Pass và VectorComparisonFailed là cùng kết quả (Le chọn 25/10 tối, rà F6 lệch 1; observe.channels_lib).
def _eq_lib(a, b): return OB.equal_lib(a, b, completed_same=True)
def _ch_lib(a, b): return OB.channels_lib(a, b, completed_same=True)
LIB_INFRA_ATTEMPTS = OB.LIB_INFRA_ATTEMPTS


def _rl(*a, **kw):
    """observe.run_lib_retry (sửa 2026-10-23: bản cũ so 'infra' như một trạng thái kết thúc, nên một bên lỗi hạ tầng thành divergence)."""
    return OB.run_lib_retry(*a, **kw)


def judge_lib(rb, croot, csroot, preload, r_root, rtag, p, dumps, timeout, cache):
    """Một input library cho một root phía Rust (Q1 (a); trường trả về và cache: xem chú thích trước judge_exe). rb: runner TRACTOR; croot,
    csroot: root C và C-san (csroot None khi C-san không build được: san 'infra'); preload: thư viện ASan nạp trước cho C-san; r_root: root
    phía Rust (bản dịch hoặc mutant); rtag: nhãn phía Rust trong tên file dump (RQ1: tên hệ); p: file vector; dumps: tiền tố file dump của
    input (RQ1: f'{dd}/{n}'), file phía Rust là f'{dumps}.{rtag}...'; timeout: timeout của case, chưa nhân."""
    co = cache['co']; rd = f'{dumps}.{rtag}'
    def san():
        if cache.get('san') is None:
            cache['san'] = lib_san(rb, csroot, p, timeout * SAN_TIMEOUT_FACTOR, f'{dumps}.Csan.dump', preload, co)
        return cache['san']
    ro = _rl(rb, r_root, p, timeout, True, f'{rd}.dump')
    if ro.get('k1') == 'infra': return _judge(verdict='infra', infra_at='rust', c=co, r=ro)
    c1, x = co, dict(timeout_rerun=False, timeout_confirmed=False)
    eq = _eq_lib(c1, ro)
    if not eq and OB.lib_timeout(c1) != OB.lib_timeout(ro):
        x['timeout_rerun'] = True
        c1 = _rl(rb, croot, p, timeout * TIMEOUT_RERUN_FACTOR, False, f'{dumps}.C.re.dump')
        ro = _rl(rb, r_root, p, timeout * TIMEOUT_RERUN_FACTOR, True, f'{rd}.re.dump')
        if 'infra' in (c1.get('k1'), ro.get('k1')):
            return _judge(verdict='infra', infra_at='rerun', c=c1, r=ro, info=x)
        x['timeout_confirmed'] = OB.lib_timeout(c1) != OB.lib_timeout(ro)
        eq = _eq_lib(c1, ro)
    to = timeout * (TIMEOUT_RERUN_FACTOR if x['timeout_rerun'] else 1)
    j = _judge(verdict='match' if eq else 'div', eq=eq, c=c1, r=ro, info=x, cap_hit=cap_hit_lib(c1, ro))
    if eq:
        if j['cap_hit']:                                             # độ nhạy trần output, nhánh khớp
            j['t0_div'] = time.time()
            cs8, c8, r8 = cap_sens_lib(rb, croot, r_root, p, timeout, rd)   # F4: cùng luật chạy lại
            stable8 = None
            if cs8['outcome'] == 'div':
                stable8 = cap_sens_stable_lib(rb, croot, r_root, p, cap_sens_timeout(timeout, cs8), rd, c8, r8)
                if stable8 is None: cs8.update(outcome='infra', equal=None, infra_at='stability')   # như nhánh chính
            j.update(cap_sens=cs8, c8=c8, r8=r8)
            if cs8['outcome'] == 'div':
                j.update(san=san(), channels8=_ch_lib(c8, r8), stable8=stable8)
        return j
    j['t0_div'] = time.time()
    reps_c = [_rl(rb, croot, p, to, False, f'{dumps}.C.v{k}.dump') for k in range(STAB_REPS)]
    reps_r = [_rl(rb, r_root, p, to, True, f'{rd}.v{k}.dump') for k in range(STAB_REPS)]
    if any(y.get('k1') == 'infra' for y in reps_c + reps_r):         # lỗi hạ tầng khi xác nhận: không phải divergence không ổn định
        j.update(verdict='infra', infra_at='stability'); return j
    stable = all(_eq_lib(c1, y) for y in reps_c) and all(_eq_lib(ro, y) for y in reps_r)
    sn = san()
    x['channels'] = _ch_lib(c1, ro)
    j.update(stable=stable, san=sn, retained=_retained(stable, sn['status']), channels=x['channels'],
             c_flag=c1.get('result') in LIB_CRASH and sn['status'] == 'no_report')
    if j['cap_hit']:                                                 # độ nhạy trần output, nhánh divergence
        x['cap_sens'] = j['cap_sens'] = cap_sens_lib(rb, croot, r_root, p, timeout, rd)[0]   # F4: cùng luật chạy lại
    return j


def rq1_lib_case(B, bundle, case, pairs, seed, theta, timeout, div_path, tag):
    T0 = time.time(); ph = {}
    rec = dict(key=f'{bundle}/{case}/s{seed}', kind='lib', bundle=bundle, case=case, seed=seed, theta=theta, timeout=timeout)
    # Library không có trường input (census `no_input`: 013_poor_quality_addition_lib, 014_dead_code_lib, parse_uname_lib): thuộc P0,
    # bản được chấp nhận không vào P_test theo thiết kế, báo như hao hụt (decision-log 2026-10-20, §3.2; Le giữ 25/10). Không chạy.
    if pairs and all(p.get('no_input') for p in pairs):
        rec.update(status='done', input_fields=False, pair_status={p['system']: 'no_input_fields' for p in pairs},
                   phases={}, secs=round(time.time() - T0, 2))
        return rec
    t = time.time()
    info = BD.build_lib_case(B, bundle, case)
    rec['build'] = {k: info.get(k) for k in ('runner_ok', 'c_ok', 'c-san_ok', 'c_sha256', 'preset')}
    if not (info['runner_ok'] and info['c_ok']):
        ph['build'] = round(time.time() - t, 2)    # F7: như executable, mọi bản dịch của case rời P_test với mã 'c_build_failed'
        rec.update(status='c_build_failed', pair_status={p['system']: 'c_build_failed' for p in pairs}, phases=ph)
        return rec
    rust = {p['system']: BD.build_rust_lib(B, p['system'], bundle, case, p['harvest_case'], info['library']) for p in pairs}
    ph['build'] = round(time.time() - t, 2)
    rec['rust_build'] = {s: {k: r.get(k) for k in ('ok', 'sha256', 'so_alias')} for s, r in rust.items()}
    t = time.time()
    files, err, nseeds = _lib_inputs(B, info, theta['n_inputs'], seed, include_vectors=True)
    ph['gen'] = round(time.time() - t, 2)
    rec.update(cdict_error=err, n_seed_vectors=nseeds, n_inputs=len(files),
               input_set_sha256=_h([open(p).read() for p, _ in files]), n_by_source=dict(collections.Counter(s for _, s in files)))
    # F8 (Le chọn 25/10): lưu đủ tập input (nội dung file vector), nén; hash theo nguồn.
    rec['inputs_file'] = write_inputs(inputs_path(div_path), (dict(i=i, source=src, vector=json.load(open(p))) for i, (p, src) in enumerate(files)))
    rec['input_sha256_by_source'] = {S: _h([open(p).read() for p, src in files if src == S]) for S in sorted({src for _, src in files})}
    if not files:    # Le chọn 25/10 (rà §3.3 v10): case vẫn ghi 'done', mọi bản dịch rời P_test với mã 'no_inputs' (trước: case biến mất)
        rec.update(status='done', phases=ph, secs=round(time.time() - T0, 2),
                   pair_status={s: 'rust_build_failed' if not r['ok'] else 'no_inputs' for s, r in rust.items()})
        return rec
    croot = BD.lib_root(B, info, 'c'); csroot = BD.lib_root(B, info, 'c-san') if info.get('c-san_ok') else None
    preload = BD.asan_preload()
    systems = [s for s, r in rust.items() if r['ok']]
    roots = {s: BD.lib_root(B, info, 'rust', rust[s]['dir'], tag=f'rust-{s}') for s in systems}
    cnt = {s: collections.Counter() for s in systems}
    for s, r in rust.items():
        if not r['ok']: cnt.setdefault(s, collections.Counter())['rust_build_failed'] = 1
    dd = f'{B}/dumps-rq1/{tag}/{bundle}/{case}'; os.makedirs(dd, exist_ok=True)
    rb = info['runner_bin']; divf = open(div_path, 'a'); capf = open(div_path.replace('.jsonl', '.capsens.jsonl'), 'a')
    memf = open(div_path.replace('.jsonl', '.memlimit.jsonl'), 'a')
    exf = open(div_path.replace('.jsonl', '.exact.jsonl'), 'a')
    t = time.time(); t_div = 0.0; n_out_of_domain = collections.Counter()
    for i, (p, src) in enumerate(files):
        n = os.path.basename(p)
        co = _rl(rb, croot, p, timeout, False, f'{dd}/{n}.C.dump')
        if co.get('k1') == 'invalid_input':                          # ngoài miền runner: bỏ, đếm theo nguồn (như miền UTF-8 executable)
            n_out_of_domain[src] += 1
            continue
        if co.get('k1') == 'infra':                                  # C lỗi hạ tầng sau khi thử lại: input không quan sát được
            for s in systems: cnt[s]['infra_inputs'] += 1
            continue
        cache = dict(co=co, san=None)                                # C-san một lần mỗi input, chung mọi hệ
        for s in systems:
            j = judge_lib(rb, croot, csroot, preload, roots[s], s, p, f'{dd}/{n}', timeout, cache)
            if j['infra_at'] == 'rust': cnt[s]['infra_inputs'] += 1; continue
            if j['infra_at'] in ('rerun', 'stability'): cnt[s]['observed'] += 0      # giữ khoá observed trong bản ghi như trước
            if j['infra_at'] == 'rerun':
                cnt[s]['infra_inputs'] += 1; continue
            if j['infra_at'] == 'stability':                         # lỗi hạ tầng khi xác nhận: không phải divergence không ổn định
                # Sửa 2026-10-26 (Le chọn): xét trước mem_note, obs_note để input không quan sát được không vào c_status, r_status,
                # cap_*, mem_limit_* (trước đó các bộ đếm này gồm input đã bị trừ khỏi observed).
                cnt[s]['infra_inputs'] += 1; t_div += time.time() - j['t0_div']; continue
            cnt[s]['observed'] += 1
            eq, c1, ro, x = j['eq'], j['c'], j['r'], j['info']
            mem_note(cnt[s], memf, f'{bundle}/{case}/s{seed}/{s}/{i}', 'lib', c1, ro, 'match' if eq else 'div', src)
            obs_note(cnt[s], 'lib', c1, ro, eq, None, exf, f'{bundle}/{case}/s{seed}/{s}/{i}', src)
            if eq:
                cnt[s]['match'] += 1
                if j['cap_hit']:                                     # độ nhạy trần output, nhánh khớp
                    cnt[s]['cap_hit_match'] += 1
                    cs8, c8, r8 = j['cap_sens'], j['c8'], j['r8']    # F4: cùng luật chạy lại
                    cnt[s]['cap_sens_timeout_rerun'] += cs8['timeout_rerun']
                    if cs8['outcome'] == 'infra':                    # F4: không quan sát được ở trần lớn, không là khớp hay divergence
                        cnt[s]['cap_sens_infra_match'] += 1
                    elif cs8['outcome'] == 'div':
                        cnt[s]['cap_sens_new_div'] += 1
                        san = j['san']
                        capf.write(json.dumps(dict(key=f'{bundle}/{case}/s{seed}/{s}/{i}', kind='lib', bundle=bundle, case=case,
                                                   seed=seed, system=s, idx=i, source=src, branch='match', input=json.load(open(p)),
                                                   c=OB.rec_obs(c8), r=OB.rec_obs(r8), cap_sens=cs8, channels=j['channels8'], stable=j['stable8'],
                                                   san=san['status'], san_markers=san['markers'], c_ub=san['status'] == 'ub'),
                                              ensure_ascii=False, sort_keys=True, default=str) + '\n')
                    t_div += time.time() - j['t0_div']
                continue
            stable, san = j['stable'], j['san']
            cnt[s]['div'] += 1; cnt[s]['div_stable'] += stable
            retained = san_counts(cnt[s], stable, san['status'])
            cnt[s]['div_stderr_only'] += x['channels'] == ['stderr']
            if j['cap_hit']:                                         # độ nhạy trần output, nhánh divergence
                cnt[s]['cap_hit_div'] += 1; cnt[s]['cap_sens_timeout_rerun'] += x['cap_sens']['timeout_rerun']
                cnt[s]['cap_sens_infra_div'] += x['cap_sens']['outcome'] == 'infra'   # F4: equal None, metrics giữ kết quả chính
            d = dict(key=f'{bundle}/{case}/s{seed}/{s}/{i}', kind='lib', bundle=bundle, case=case, seed=seed, system=s, idx=i,
                     source=src, input=json.load(open(p)), c=OB.rec_obs(c1), r=OB.rec_obs(ro), stable=stable, san=san['status'],
                     san_markers=san['markers'], c_ub=san['status'] == 'ub', retained=retained, san_attempts=san.get('attempts'),
                     c_flag=j['c_flag'], **x)   # cờ C crash library (24/10)
            divf.write(json.dumps(d, ensure_ascii=False, sort_keys=True, default=str) + '\n')
            t_div += time.time() - j['t0_div']
    divf.close(); capf.close(); memf.close(); exf.close()
    ph['execute'] = round(time.time() - t, 2); ph['divergence_handling'] = round(t_div, 2)
    rec['counts'] = {s: dict(v) for s, v in cnt.items()}
    rec['out_of_domain_by_source'] = dict(n_out_of_domain)
    rec['pair_status'] = {s: pair_status(v, len(files) - sum(n_out_of_domain.values())) for s, v in cnt.items()}
    rec.update(status='done', phases=ph, secs=round(time.time() - T0, 2), n_systems=len(systems))
    return rec


# ---------------- chạy theo shard ----------------
def pilot_pairs(kind):
    """P_rep trên case pilot: cùng luật P_rep, áp lên dòng pilot của census (R6: pilot báo riêng, không vào con số chính)."""
    d = PR.DEFAULT[kind]
    rows = [dict(r, pilot=False, pilot_case=True) for r in PR.load(d['census']) if r['pilot']]
    return PR.p_rep(rows, PR.load(d['recheck']))


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return dict(status='harness_error', error=traceback.format_exc()[-3000:])


def case_files(div):
    """File divergence của một (case, seed) và các file phụ."""
    return [div, *(div.replace('.jsonl', x) for x in ('.capsens.jsonl', '.memlimit.jsonl', '.exact.jsonl'))]


def inputs_path(div):
    """File tập input nén của một (case, seed), cạnh thư mục div (F8)."""
    return os.path.join(os.path.dirname(os.path.dirname(div)), 'inputs', os.path.basename(div).replace('.jsonl', '.inputs.jsonl.gz'))


def reset_case_files(div):
    """Xoá file divergence của một (case, seed) và các file phụ (sửa 2026-10-23: bản cũ chỉ xoá file chính, nên khi chạy tiếp sau khi dừng
    thì bản ghi trong *.capsens.jsonl bị nhân đôi). Gồm bản nén và file tập input (F8)."""
    for f in (*case_files(div), *(x + '.gz' for x in case_files(div)), inputs_path(div)):
        if os.path.exists(f): os.remove(f)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='harness.rq1')
    ap.add_argument('--kind', choices=['exe', 'lib'], required=True)
    ap.add_argument('--out', required=True); ap.add_argument('--tag', required=True, help='nhãn mức ngân sách, vd x3')
    ap.add_argument('--pilot', action='store_true', help='chạy trên case pilot (job đo thời gian)')
    ap.add_argument('--seeds', default='0'); ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--timeout', type=int, default=10); ap.add_argument('--shard')
    ap.add_argument('--budget', type=int, default=3000, help='exe: số input mỗi tầng M, MS')
    ap.add_argument('--afl-execs', type=int, default=10000, help='exe: afl-fuzz -E')
    ap.add_argument('--n-inputs', type=int, default=200, help='lib: số input StateGen v2')
    ap.add_argument('--cases', help='bundle/case, phân cách bằng dấu phẩy')
    a = ap.parse_args(argv)
    if not a.pilot:
        raise SystemExit('Lượt chính chưa mở: chờ Protocol Freeze (decision-log 2026-10-22). Dùng --pilot.')
    B = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness'))
    prs = pilot_pairs(a.kind)
    pil = PILOT_EXE if a.kind == 'exe' else PILOT_LIB
    by_case = collections.defaultdict(list)
    for r in prs: by_case[(r['bundle'], r['tractor_case'])].append(r)
    assert set(by_case) <= pil, 'case không thuộc pilot'
    cases = sorted(by_case)
    if a.cases: cases = [tuple(x.split('/')) for x in a.cases.split(',')]
    cases = PR.shard(cases, a.shard)
    theta = dict(budget=a.budget, afl_execs=a.afl_execs) if a.kind == 'exe' else dict(n_inputs=a.n_inputs)
    seeds = [int(s) for s in a.seeds.split(',')]
    os.makedirs(a.out, exist_ok=True)
    manifest(a.out, dict(cmd='rq1', kind=a.kind, tag=a.tag, pilot=a.pilot, seeds=seeds, workers=a.workers, timeout=a.timeout,
                         theta=theta, n_cases=len(cases), n_pairs=sum(len(by_case[c]) for c in cases), build_dir=B,
                         stab_reps=STAB_REPS, san_timeout_factor=SAN_TIMEOUT_FACTOR, input_domain='utf8_runner',
                         san_ub_markers=[m.decode() for m in SAN_UB_MARKERS], san_header=SAN_HEADER.pattern.decode(),
                         san_mem_markers=[m.decode() for m in SAN_MEM_MARKERS], exe_san_env=EXE_SAN_ENV, lib_san_env=LIB_SAN_ENV,
                         mem_limit=OB.MEM_LIMIT, argv0=OB.ARGV0.decode(), compare_stderr=True, output_cap_sens=OUTPUT_CAP_SENS,
                         exe_case_timeout=dict(rule='max(timeout, ceil(factor * max_c_secs))', factor=C_TIME_FACTOR,
                                               table='harness/data/exe-c-time.json', table_sha256=C_TIME_SHA),
                         p_rep_source=PR.source_info(a.kind),
                         insensitive_seed=INSENSITIVE_SEED, output_cap=OB.OUTPUT_CAP, timeout_rerun_factor=TIMEOUT_RERUN_FACTOR,
                         generator=gen_params(), files=dict(div='div/*.jsonl.gz (nén khi case xong)', inputs='inputs/*.inputs.jsonl.gz (gồm input tầng A)')))
    store = Store(f'{a.out}/rq1-{a.kind}.jsonl')
    if a.kind == 'lib': BD.setup_cando2(B)
    fn = rq1_exe_case if a.kind == 'exe' else rq1_lib_case
    todo = []
    for sd in seeds:
        for bundle, case in cases:
            if store.has(f'{bundle}/{case}/s{sd}'): continue
            div = f'{a.out}/div/{bundle}__{case}__s{sd}.jsonl'; os.makedirs(os.path.dirname(div), exist_ok=True)
            reset_case_files(div)                            # case chạy lại từ đầu thì bỏ bản ghi dở dang
            todo.append((fn, B, bundle, case, by_case[(bundle, case)], sd, theta, a.timeout, div, a.tag))
    print(f'rq1 {a.kind} {a.tag}: {len(todo)} (case, seed) cần chạy, {a.workers} worker', flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(_safe, *t): t for t in todo}
        for fut in as_completed(futs):
            t = futs[fut]; r = fut.result()
            if r.get('status') == 'harness_error':
                # F7: pair_status theo danh sách cặp của case, để metrics giữ các bản dịch này với mã 'harness_error'
                r.update(key=f'{t[2]}/{t[3]}/s{t[5]}#error', kind=a.kind, bundle=t[2], case=t[3], seed=t[5],
                         pair_status={p['system']: 'harness_error' for p in t[4]})
            compress_files(case_files(t[8]))                # F8: nén file divergence khi case xong, trước khi ghi bản ghi case
            store.put(r)
            print(r.get('key'), r.get('status'), r.get('secs'), r.get('n_inputs'), flush=True)
    json.dump(dict(wall_secs=round(time.time() - t0, 2), workers=a.workers, n_jobs=len(todo)),
              open(f'{a.out}/wall-{a.kind}.json', 'w'))
    m = json.load(open(f'{a.out}/manifest.json'))                 # F8: giờ kết thúc vào manifest
    m.update(finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), wall_secs=round(time.time() - t0, 2))
    json.dump(m, open(f'{a.out}/manifest.json', 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
