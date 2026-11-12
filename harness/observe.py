"""Hàm quan sát O(p, x) và hàm so sánh dùng chung (harness-design.md mục 4.3; A3.3 mục 1.1 đến 1.3).

Executable: trạng thái kết thúc (exit code, số signal, hoặc vượt ngân sách), stdout và stderr.
  Bằng nhau khi cùng trạng thái kết thúc, stdout trùng sau R-NaN và stderr trùng sau chuẩn hoá N (decision-log 2026-10-23, căn cứ
  exp 12; trước đó stderr chỉ ghi lại). Hai phía cùng vượt ngân sách: so prefix chung của stdout (luật NT); stderr không so vì bị cắt.
Library: k1 (runner báo kết quả hay lỗi hạ tầng), result của runner, state_out, stdout, stderr.
  Bằng nhau khi cùng k1, cùng result, stdout trùng sau R-NaN, stderr trùng sau N, state_out khớp với sai số tương đối 1e-6
  (NaN bằng NaN).
Mọi lần chạy (trừ chạy kèm sanitizer) có trần bộ nhớ ảo MEM_LIMIT (2 GB, decision-log 2026-10-23); chạm trần thì trạng thái
`mem_limit`, thuộc nhóm vượt ngân sách. argv[0] của mọi chương trình là "driver" để C và Rust nhận cùng tên.
  So `result` giữ đúng hàm eq_tol của nghiệm thu v2 (exp 08) để V7 so được.
Một phía timeout: chạy lại hai phía với timeout gấp TIMEOUT_RERUN_FACTOR; vẫn một phía thì khác, gắn timeout_confirmed."""
import json, math, os, re, resource, shutil, signal, subprocess, tempfile, time

from .config import SAN_MARKERS, TIMEOUT_RERUN_FACTOR
from .vectors import to_bytes

# R-NaN có ranh giới từ (sửa 2026-10-23 theo rà độc lập: bản cũ biến "NANCY" thành "nanCY", "nano" của hai bên vẫn bằng nhau nhưng
# chuỗi chứa "nan" bên trong từ khác bị đổi tuỳ ý).
NAN = re.compile(rb'(?<![a-z0-9_])-?nan(?![a-z0-9_])', re.I)


def rundir():
    """Thư mục làm việc trống cho mỗi lần chạy; cùng đường dẫn cho C và Rust trong một tiến trình worker.
    Chương trình đo có thể ghi file vào thư mục làm việc (vd pointer_comparison_ascii_art lưu scene); làm trống trước mỗi lần chạy
    để file của lần trước không ảnh hưởng lần sau và không rơi vào repo. Khác TRACTOR (dùng thư mục của runner, giữ file giữa vector)."""
    d = os.path.join(os.environ.get('HARNESS_RUNDIR', tempfile.gettempdir()), f'harness-run-{os.getpid()}')
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    return d


def norm(out):
    """R-NaN: -nan, nan, NaN coi như nhau."""
    return NAN.sub(b'nan', out)


# Địa chỉ: mọi chuỗi 0x... (luật đăng ký trước của exp 12). Rà độc lập 23/10 chỉ ra luật này cũng che số hex chương trình in có chủ
# đích; đổi ngưỡng là sửa luật đã đăng ký, chờ Le quyết, nên giữ nguyên.
ADDR = re.compile(rb'0x[0-9a-f]+'); PID = re.compile(rb'==\d+==')
# Rust từ 1.89 in mã luồng hệ điều hành trong thông báo panic: "thread 'main' (12345) panicked at ...". Mã đổi mỗi lần chạy, nên không
# chuẩn hoá thì mọi divergence có panic bị xếp không ổn định và vector RQ2 có panic thành không phân xử được (phát hiện 2026-10-23,
# rustc 1.97.0 của máy đo).
TID = re.compile(rb"(thread '[^'\n]*') \(\d+\) panicked")


def norm_err(err):
    """Chuẩn hoá N cho stderr (luật đăng ký trước của exp 12): chữ thường; địa chỉ 0x... thành <addr>; ==pid== thành ==<pid>==; bỏ khoảng
    trắng cuối dòng và dòng trống. Đường dẫn binary không cần thay vì argv[0] của hai phía đều là ARGV0.
    Sửa 2026-10-23: thêm mã luồng trong thông báo panic của Rust thành <tid>."""
    e = (err or b'').lower()
    e = ADDR.sub(b'<addr>', e); e = PID.sub(b'==<pid>==', e); e = TID.sub(rb'\1 (<tid>) panicked', e)
    return b'\n'.join(l.rstrip() for l in e.split(b'\n') if l.strip())


ARGV0 = b'driver'
MEM_LIMIT = int(os.environ.get('HARNESS_MEM_LIMIT', 2 << 30))   # byte; 0 thì không đặt trần
# Dấu hiệu cấp phát thất bại trong stderr: Rust in "memory allocation of N bytes failed" rồi abort; C và thư viện in thông báo ENOMEM.
# Thông báo cấp phát thất bại (decision-log 2026-10-23: Rust "memory allocation of ... failed", ENOMEM). Le chọn 25/10 (rà §3.3 v10): chỉ
# nhận từ trình cấp phát; bỏ 'out of memory', 'std::bad_alloc', 'allocation failed' vì chương trình có thể tự in các chuỗi đó.
MEM_MARKERS = (b'memory allocation of', b'cannot allocate memory')


_ASAN = {}


def is_asan(binary):
    """Binary có ASan (chứa ký hiệu __asan_init): không đặt RLIMIT_AS, vì ASan cần dành vùng shadow rất lớn. Cache theo đường dẫn."""
    if binary not in _ASAN:
        try: _ASAN[binary] = b'__asan_init' in open(binary, 'rb').read()
        except OSError: _ASAN[binary] = False
    return _ASAN[binary]


# Trần kích thước một file mà tiến trình đo được ghi (RLIMIT_FSIZE, sửa 2026-10-23 sau sự cố hết đĩa EC2): lưới cuối cho file do chương
# trình đo hoặc runner TRACTOR ghi (file stdout tạm, report, dump, file chương trình tự tạo). Vượt thì kernel gửi SIGXFSZ. Giới hạn output
# thật vẫn là OUTPUT_CAP mỗi luồng; trần này chỉ chặn trường hợp bộ kiểm tra không kịp dừng.
FSIZE_LIMIT = int(os.environ.get('HARNESS_FSIZE_LIMIT', 1 << 30))


_LAUNCH_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'launch.c')
_LAUNCH = {}


def launcher():
    """Đường dẫn bộ khởi chạy C (launch.c), biên dịch một lần vào HARNESS_BUILD, khoá theo sha256 của mã nguồn."""
    if 'bin' not in _LAUNCH:
        import hashlib
        src = open(_LAUNCH_SRC, 'rb').read(); tag = hashlib.sha256(src).hexdigest()[:12]
        d = os.environ.get('HARNESS_BUILD', os.path.expanduser('~/build/harness'))
        out = os.path.join(d, f'harness-launch-{tag}')
        if not os.path.exists(out):
            os.makedirs(d, exist_ok=True); tmp = f'{out}.{os.getpid()}'
            cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
            subprocess.run([cc, '-O2', '-o', tmp, _LAUNCH_SRC], check=True, capture_output=True)
            os.replace(tmp, out)
        _LAUNCH['bin'] = out
    return _LAUNCH['bin']


def launch_args(binary, argv0, args, mem_limit):
    """argv cho Popen: bộ khởi chạy đặt trần bộ nhớ ảo (mem_limit, 0 = không đặt), trần kích thước file (FSIZE_LIMIT) và chặn core dump,
    rồi exec binary với argv[0] = argv0. Thay preexec_fn từ 2026-10-23; giới hạn áp như cũ."""
    return [launcher(), str(int(mem_limit or 0)), str(int(FSIZE_LIMIT or 0)), binary, argv0] + list(args)


# ---------------- executable ----------------
# Giới hạn output giữ lại mỗi luồng (2026-10-22). Lần chạy harness-checks 21/10 làm máy đo OOM: một worker giữ 8 GB vì chương trình
# C in vô hạn với input đột biến (vd vòng scanf gặp EOF; 3/30 case đầu in khoảng 19 MB trong 3 giây). Vượt giới hạn thì dừng chương
# trình, trạng thái `output_limit`, giữ OUTPUT_CAP byte đầu. Cách so: luật NT bên dưới (decision-log 2026-10-22).
OUTPUT_CAP = int(os.environ.get('HARNESS_OUTPUT_CAP', 32 << 20))


def _drain(pipe, buf, cap, over, proc):
    while True:
        ch = pipe.read(1 << 16)
        if not ch: break
        room = cap - len(buf)
        if room > 0: buf += ch[:room]
        if len(ch) > room and not over:
            over.append(True)
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
    pipe.close()


def _feed(pipe, data):
    try:
        if data: pipe.write(data)
    except (BrokenPipeError, OSError):
        pass
    finally:
        try: pipe.close()
        except OSError: pass


def run_exe(binary, argv, stdin, timeout, env=None, cwd=None, cap=None, mem_limit=None, san=False):
    """Chạy binary một lần. argv, stdin là chuỗi byte (vectors.py). Trả về dict quan sát thô; stdout, stderr giữ tối đa cap byte.
    san=True: lần chạy kèm sanitizer, không đặt trần bộ nhớ ảo (ASan cần không gian địa chỉ lớn); trần do ASAN_OPTIONS của bên gọi."""
    import threading
    cap = cap or OUTPUT_CAP
    lim = 0 if (san or is_asan(binary)) else (MEM_LIMIT if mem_limit is None else mem_limit)
    args = launch_args(binary, ARGV0, [to_bytes(a) for a in argv], lim)
    data = to_bytes(stdin)
    e = dict(os.environ, **PINNED_ENV); e.update(env or {})      # biến môi trường cố định trước, env của vector đè lên (như runner)
    t0 = time.time()
    try:
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=e,
                             cwd=cwd or rundir(), start_new_session=True)
    except ValueError as ex:          # argv chứa byte NUL: input không thực thi được
        return dict(status='invalid_input', rc=None, sig=None, to=False, out=b'', err=str(ex).encode(), secs=0.0)
    out, err, over = bytearray(), bytearray(), []
    th = [threading.Thread(target=_drain, args=(p.stdout, out, cap, over, p), daemon=True),
          threading.Thread(target=_drain, args=(p.stderr, err, cap, over, p), daemon=True),
          threading.Thread(target=_feed, args=(p.stdin, data), daemon=True)]
    for t in th: t.start()
    try:
        p.wait(timeout=timeout); to = False
    except subprocess.TimeoutExpired:
        to = True
    try: os.killpg(p.pid, signal.SIGKILL)       # dọn cả tiến trình con còn sót trong nhóm
    except ProcessLookupError: pass
    p.wait()
    for t in th: t.join(timeout=5)
    rc = p.returncode
    mk = [m.decode() for m in MEM_MARKERS if m in bytes(err).lower()]
    mem = bool(lim) and not over and not to and (rc != 0) and bool(mk)
    if over: status, sig, rcv = 'output_limit', None, None
    elif mem: status, sig, rcv = 'mem_limit', None, None
    elif to: status, sig, rcv = 'timeout', None, None
    elif rc < 0: status, sig, rcv = 'signal', -rc, None
    else: status, sig, rcv = 'exit', None, rc
    o = dict(status=status, rc=rcv, sig=sig, to=to, out=bytes(out), err=bytes(err), secs=round(time.time() - t0, 4))
    if mem: o['mem_marker'] = mk          # dấu hiệu khớp, để kiểm tay mẫu các lần xếp chạm trần (nhận dạng bằng chuỗi)
    return o


NT = ('timeout', 'output_limit', 'mem_limit')   # vượt ngân sách (luật NT 2026-10-22; thêm trần bộ nhớ 2026-10-23)


def is_nt(o):
    return o['status'] in NT


def nt_prefix(a, b):
    """Phần prefix chung so được của hai output bị cắt: chuẩn hoá R-NaN từng bên, cắt ở độ dài bên ngắn hơn, bỏ dòng cuối dở dang
    (tiến trình bị dừng giữa dòng). Trả về (bằng nhau, số byte đã so)."""
    pa, pb = nt_cut(norm(a['out']), norm(b['out']))
    return pa == pb, max(len(pa), len(pb))


def nt_cut(na, nb):
    """Phần so của luật NT trên hai output đã chuẩn hoá: cắt cả hai ở độ dài bên ngắn hơn, mỗi bên bỏ dòng cuối dở dang của chính nó.
    Đối xứng (Le chọn 25/10 tối, rà F6 lệch 3: bản trước lấy điểm cắt dòng từ phía C nên đổi vai C và Rust có thể đổi kết quả). Không có
    dòng hoàn chỉnh thì phần so rỗng (mục 2026-10-25). Dùng chung cho bnu (experiments/09-bnu-rules)."""
    n = min(len(na), len(nb))
    a, b = na[:n], nb[:n]
    return a[:a.rfind(b'\n') + 1], b[:b.rfind(b'\n') + 1]


def equal_exe(a, b):
    """Luật NT (B): hai bên cùng không dừng trong ngân sách (timeout hoặc vượt giới hạn output, không phân biệt) thì so prefix chung;
    còn lại so trạng thái kết thúc và toàn bộ stdout sau R-NaN. Một bên NT, bên kia dừng: khác."""
    if is_nt(a) and is_nt(b): return nt_prefix(a, b)[0]
    return not channels_exe(a, b)


def channels_exe(a, b):
    """Kênh khác nhau giữa hai quan sát không cùng vượt ngân sách: 'status', 'stdout', 'stderr' (rỗng nghĩa là bằng nhau)."""
    ch = []
    if (a['status'], a['rc'], a['sig']) != (b['status'], b['rc'], b['sig']): ch.append('status')
    if norm(a['out']) != norm(b['out']): ch.append('stdout')
    if norm_err(a['err']) != norm_err(b['err']): ch.append('stderr')
    return ch


def one_sided_nt(a, b):
    return is_nt(a) != is_nt(b)


def compare_exe(c_bin, r_bin, argv, stdin, timeout, c_obs=None, env=None, cwd=None, cap=None):
    """So C với Rust trên một input. c_obs: quan sát C đã có (C chạy một lần mỗi input). Trả về (equal, c, r, info).
    Một bên NT: chạy lại hai bên với timeout gấp TIMEOUT_RERUN_FACTOR (A3.3 mục 1.2, mở rộng cho output_limit); vẫn một bên thì khác.
    cap: trần output mỗi luồng (mặc định OUTPUT_CAP); phân tích độ nhạy trần output (rq1.cap_sens_exe) truyền trần lớn hơn để dùng cùng
    luật này ở trần lớn (F4, 2026-10-25)."""
    c = c_obs or run_exe(c_bin, argv, stdin, timeout, env, cwd, cap=cap)
    r = run_exe(r_bin, argv, stdin, timeout, env, cwd, cap=cap)
    info = dict(timeout_rerun=False, timeout_confirmed=False)
    if is_nt(c) and is_nt(r): info['nt_prefix_bytes'] = nt_prefix(c, r)[1]
    elif not one_sided_nt(c, r): info['channels'] = channels_exe(c, r)
    if equal_exe(c, r): return True, c, r, info
    if one_sided_nt(c, r):
        info['timeout_rerun'] = True
        c2 = run_exe(c_bin, argv, stdin, timeout * TIMEOUT_RERUN_FACTOR, env, cwd, cap=cap)
        r2 = run_exe(r_bin, argv, stdin, timeout * TIMEOUT_RERUN_FACTOR, env, cwd, cap=cap)
        if one_sided_nt(c2, r2): info['timeout_confirmed'] = True
        if is_nt(c2) and is_nt(r2): info['nt_prefix_bytes'] = nt_prefix(c2, r2)[1]
        elif not one_sided_nt(c2, r2): info['channels'] = channels_exe(c2, r2)
        return equal_exe(c2, r2), c2, r2, info
    return False, c, r, info


def san_flag(err):
    return any(m in err for m in SAN_MARKERS)


# ---------------- library ----------------
def float_tol_equal(a, b, rel=1e-6):
    """Như spike_lib.float_tol_equal, thêm NaN bằng NaN (A3.3 mục 1.3)."""
    if isinstance(a, bool) or isinstance(b, bool): return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, int) and isinstance(b, int): return a == b
        if a == b: return True
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b): return True
        if math.isinf(a) or math.isinf(b) or math.isnan(a) or math.isnan(b): return False   # vô cực chỉ bằng cùng dấu (sửa 2026-10-23)
        return abs(a - b) <= rel * max(abs(a), abs(b))
    if isinstance(a, list) and isinstance(b, list): return len(a) == len(b) and all(float_tol_equal(x, y, rel) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict): return a.keys() == b.keys() and all(float_tol_equal(a[k], b[k], rel) for k in a)
    return a == b


# serde_json ghi NaN, inf, -inf thành null, nên trong state_out ba giá trị này trông như nhau (rà độc lập 2026-10-23). Bản vá runner v2
# ghi thêm state_debug (định dạng Debug của Rust: NaN, inf, -inf). Hai bên dùng cùng struct state của runner nên thứ tự duyệt trường như
# nhau: khi state_out bằng nhau (cùng vị trí null), so dãy giá trị không hữu hạn theo thứ tự xuất hiện là so đúng từng vị trí.
NONFINITE = re.compile(r'(?<![A-Za-z0-9_.])(NaN|-inf|inf)(?![A-Za-z0-9_])')


def nonfinite_tokens(debug):
    return NONFINITE.findall(debug or '')


def _killpg(p):
    try: os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError): pass


def run_lib(runner_bin, root, vec_path, timeout, rust, dump_path, preload=None, extra_env=None, keep_files=False, cap=None,
            dump=True, mem_limit=None):
    """Một vector qua runner TRACTOR (bản patch state-dump). Như spike_lib.run_one, nhưng giữ đủ stdout, stderr.
    File dump và report bị xoá sau khi đọc (sửa 2026-10-23: bản cũ để lại mọi file, tích tụ trên đĩa máy đo); nội dung cần cho phép so
    đã nằm trong dict trả về. keep_files=True giữ lại để hàm gọi tự đọc report (rq1.lib_san) rồi tự xoá.
    dump=False, mem_limit=0 (thêm 2026-10-26 cho harness.census): không đặt CANDO2_STATE_DUMP (bản vá không hoạt động, verdict như
    cando2 gốc) và không đặt trần bộ nhớ ảo, như census_lib.py; mặc định giữ nguyên hành vi cũ cho mọi hàm gọi khác."""
    try:
        return _run_lib(runner_bin, root, vec_path, timeout, rust, dump_path, preload, extra_env, cap or OUTPUT_CAP, dump, mem_limit)
    finally:
        if not keep_files:
            for f in (dump_path, dump_path + '.report.json'):
                try: os.remove(f)
                except OSError: pass


# Biến môi trường cố định cho mọi lần chạy đo (rà soát kỹ thuật 2026-10-23). Máy đo không đặt RUST_BACKTRACE, cloud container đặt
# RUST_BACKTRACE=1: stderr của panic Rust và thông báo lỗi của runner khác nhau giữa hai môi trường. Cụ thể, không có backtrace thì
# thông báo runner từ chối đọc vector không chứa "load_vectors", nên trên máy đo input ngoài miền bị xếp lỗi hạ tầng (test
# test_out_of_range_is_invalid_input trượt trong harness-checks tại ef1b8d4, đạt trên container).
PINNED_ENV = dict(RUST_BACKTRACE='0')
# Runner TRACTOR không đọc được vector: "Internal failure: <lỗi serde_json> at line N column M" (cando2/src/error.rs dòng 146).
LOAD_ERR = re.compile(rb'Internal failure: [^\n]* at line \d+ column \d+')


LIB_INFRA_ATTEMPTS = 3


def run_lib_retry(*a, **kw):
    """run_lib, thử lại khi runner không ghi report (k1 'infra', lỗi hạ tầng) tới LIB_INFRA_ATTEMPTS lần (decision-log 2026-10-20: lỗi
    hạ tầng không phải quan sát). Dùng chung cho RQ1 (rq1._rl) và V5, V6 (checks; rà soát kỹ thuật 2026-10-23: V5, V6 chưa thử lại).
    'invalid_input' là tất định, không thử lại."""
    for _ in range(LIB_INFRA_ATTEMPTS):
        o = run_lib(*a, **kw)
        if o.get('k1') != 'infra': return o
    return o


def _run_lib(runner_bin, root, vec_path, timeout, rust, dump_path, preload, extra_env, cap=None, dump=True, mem_limit=None):
    cap = cap or OUTPUT_CAP   # cap: trần mỗi luồng output; phân tích độ nhạy trần output truyền trần lớn hơn (rq1.cap_sens_lib)
    for f in (dump_path, dump_path + '.report.json'):
        if os.path.exists(f): os.remove(f)
    rep = dump_path + '.report.json'
    cmd = [runner_bin, '--log-level', 'quiet', '--test-root-dir', root, '--timeout', str(timeout), '--vectors', vec_path,
           '--output', rep] + (['--rust'] if rust else []) + ['lib']
    env = dict(os.environ, **PINNED_ENV)
    if dump: env['CANDO2_STATE_DUMP'] = dump_path
    else: env.pop('CANDO2_STATE_DUMP', None)
    if extra_env: env.update(extra_env)
    if preload: env['LD_PRELOAD'] = preload
    lim = 0 if preload else (MEM_LIMIT if mem_limit is None else mem_limit)   # chạy kèm ASan (preload): không đặt trần bộ nhớ ảo
    # Sửa 2026-10-23 (sự cố hết đĩa EC2 22/10, decision-log cùng ngày). Runner TRACTOR chạy hàm library trong một tiến trình con
    # (procspawn), ghi stdout, stderr của tiến trình con vào file tạm (tempfile, theo TMPDIR) không giới hạn, và khi Timeout thì không
    # dừng tiến trình con (lib_runner.rs: join_timeout rồi trả Timeout, không gọi kill). Tiến trình con lặp vô hạn chạy tiếp sau khi
    # runner thoát, ghi tiếp vào file tạm đã bị xoá: chiếm CPU và đĩa mà du không thấy. Trên EC2 còn 43 tiến trình như vậy sau 7 giờ.
    # Cách chặn: (1) runner chạy trong session riêng, mọi tiến trình trong nhóm bị kill khi runner xong hoặc quá hạn; (2) TMPDIR riêng
    # cho mỗi lần chạy, theo dõi kích thước file tạm; một luồng vượt OUTPUT_CAP thì dừng cả nhóm, kết quả OutputLimit (như executable).
    rd = rundir(); tmp = os.path.join(rd, '.tmp'); os.makedirs(tmp)
    env['TMPDIR'] = tmp
    t0 = time.time(); deadline = t0 + timeout * 6 + 30; over = False; big = 0
    p = subprocess.Popen(launch_args(runner_bin, runner_bin, cmd[1:], lim), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         cwd=rd, start_new_session=True)
    try:
        while True:
            try:
                o, e = p.communicate(timeout=0.2); rc, perr = p.returncode, (o + e)[-3000:]; break
            except subprocess.TimeoutExpired:
                big = max([f.stat().st_size for f in os.scandir(tmp) if f.is_file(follow_symlinks=False)] or [0])
                if big > cap or time.time() > deadline:
                    over = big > cap
                    _killpg(p)
                    o, e = p.communicate()
                    rc, perr = None, (b'output limit' if over else b'runner process timeout')
                    break
    finally:
        _killpg(p)
    res = dict(rc=rc, secs=round(time.time() - t0, 4))
    if over:
        res.update(k1='reported', result='OutputLimit', output_limit=True, tmp_bytes=big, san_flag=None)
        return res
    report = None
    if os.path.exists(rep):
        try: report = list(json.load(open(rep)).values())[0]
        except Exception as e: perr += f' | report parse error: {e}'.encode()
    if report is None:
        # Runner từ chối đọc vector (serde_json báo lỗi trong load_vectors, ví dụ số ngoài miền của kiểu f32): input nằm ngoài miền
        # runner truyền được, tất định và như nhau ở hai phía (cùng binary runner); khác lỗi hạ tầng (sửa 2026-10-23).
        k1 = 'invalid_input' if (b'load_vectors' in perr or LOAD_ERR.search(perr)) else 'infra'
        res.update(k1=k1, infra_msg=perr.decode('latin-1')); return res
    res['k1'] = 'reported'
    res['result'] = report.get('result') if isinstance(report, dict) else str(report)
    full = json.dumps(report).encode()
    if os.path.exists(dump_path) and os.path.getsize(dump_path) > 4 * cap:   # runner ghi đủ stdout: chặn đọc file khổng lồ
        res.update(output_limit=True, dump_bytes=os.path.getsize(dump_path)); res['result'] = 'OutputLimit'
        os.remove(dump_path)
    if os.path.exists(dump_path):
        lines = [json.loads(l) for l in open(dump_path) if l.strip()]
        if lines:
            d = lines[-1]
            res.update(state_out=d['state_out'], stdout=d['stdout'], stderr=d['stderr'])
            # Kiểm trần sau lời gọi (Le chọn 25/10, master plan Hàng đợi F1): theo dõi file tạm chỉ chạy mỗi 0,2 giây khi tiến trình còn
            # sống, nên lời gọi kết thúc trước lần kiểm kế tiếp mà một luồng vượt trần vẫn được so. Như executable và decision-log
            # 2026-10-23: một luồng trên trần là vượt ngân sách.
            ob = max(len((d.get('stdout') or '').encode('utf-8', 'replace')), len((d.get('stderr') or '').encode('utf-8', 'replace')))
            if ob > cap and res.get('result') != 'OutputLimit':
                res.update(output_limit=True, out_bytes=ob); res['result'] = 'OutputLimit'
            if 'state_debug' in d:
                res['state_nonfinite'] = nonfinite_tokens(d['state_debug'])
                # D5 (Le chọn 25/10): giữ cả chuỗi Debug cho robustness analysis RQ2 theo luật oracle gốc (optional so chính xác, trường
                # đơn lẻ theo ngưỡng); không dùng trong channels_lib, equal_lib.
                res['state_debug'] = d['state_debug']
            full += d['stderr'].encode('utf-8', 'replace')
    res['san_flag'] = san_flag(full) or san_flag(perr)
    if lim and res.get('result') not in ('Pass', 'VectorComparisonFailed', 'Timeout', 'OutputLimit') and \
            any(m in full.lower() for m in MEM_MARKERS):
        res['mem_limit'] = True; res['result'] = 'MemLimit'
        res['mem_marker'] = [m.decode() for m in MEM_MARKERS if m in full.lower()]   # để kiểm tay mẫu (2026-10-23, rà soát kỹ thuật)
        k = min(full.lower().find(m) for m in MEM_MARKERS if m in full.lower())       # marker có thể nằm trong báo cáo runner, không ở stderr
        res['mem_context'] = full[max(0, k - 300):k + 300].decode('utf-8', 'replace')
    return res


COMPLETED = ('Pass', 'VectorComparisonFailed')


def channels_lib(a, b, completed_same=False):
    """Kênh khác nhau: 'status' (k1 hoặc result), 'state', 'stdout', 'stderr'.
    completed_same=True (RQ1 và bnu; Le chọn 25/10 tối, rà F6 lệch 1): vector RQ1 không có output kỳ vọng, nên runner trả Pass khi và chỉ
    khi hai luồng rỗng; Pass và VectorComparisonFailed vì thế không mang thông tin riêng, coi là cùng kết quả (lời gọi hoàn tất). RQ2, V5,
    V6 giữ so result như cũ.
    Hai bên cùng vượt ngân sách (Timeout, OutputLimit, MemLimit, runner không trả lời; lib_timeout) thì coi là cùng lớp, không kênh nào
    khác, như executable (Le chốt 2026-10-23). Runner không ghi stdout, state khi vượt ngân sách nên không có prefix để so."""
    if lib_timeout(a) and lib_timeout(b): return []
    enc = lambda x: (x or '').encode('utf-8', 'replace')
    ch = []
    res = lambda o: 'completed' if completed_same and o.get('k1') == 'reported' and o.get('result') in COMPLETED else o.get('result')
    if (a.get('k1'), res(a)) != (b.get('k1'), res(b)): ch.append('status')
    if not float_tol_equal(a.get('state_out'), b.get('state_out')) or a.get('state_nonfinite') != b.get('state_nonfinite'):
        ch.append('state')
    if norm(enc(a.get('stdout'))) != norm(enc(b.get('stdout'))): ch.append('stdout')
    if norm_err(enc(a.get('stderr'))) != norm_err(enc(b.get('stderr'))): ch.append('stderr')
    return ch


def equal_lib(a, b, completed_same=False):
    return not channels_lib(a, b, completed_same)


def rec_obs(o):
    """Bản quan sát để ghi vào record RQ1 và V5: bỏ state_debug (Le chọn 26/10: D5 chỉ áp cho RQ2, nơi robustness analysis cần chuỗi
    Debug; RQ1 và V5 giữ state_nonfinite)."""
    return {k: v for k, v in o.items() if k != 'state_debug'} if isinstance(o, dict) else o


def lib_timeout(o):
    """Library: NT gồm Timeout của runner, runner không trả lời, một luồng output vượt giới hạn (OutputLimit) và trần bộ nhớ (MemLimit).
    Hai bên cùng NT thì channels_lib coi là cùng lớp (gộp như executable, Le chốt 2026-10-23; trước đó phải cùng loại mới khớp)."""
    return o.get('result') in ('Timeout', 'OutputLimit', 'MemLimit') or ('rc' in o and o['rc'] is None)
