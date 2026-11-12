"""Executable không đọc input (Le chọn 2026-10-24, decision-log cùng ngày): RQ1 chỉ chạy chính các vector, báo nhóm riêng.

Lý do: 48 case P01_sphincs_plus executable có driver `int main(void)` không đọc argv, stdin hay biến môi trường; mọi input sinh ra cho
cùng một lần chạy, nên tầng M, MS, A không thêm thông tin, trong khi mỗi lần chạy mất vài giây (ngoại suy x10 khoảng 38.000 giờ máy,
experiments/11-rq1-timing/results/e17c309/findings.md).

Tiêu chí (khách quan, đăng ký trước Protocol Freeze; cả ba điều kiện):
  (1) binary C (bản build thường của harness) liên kết động, đọc được bảng ký hiệu động;
  (2) binary không nhập ký hiệu nào trong INPUT_SYMS (đọc stdin, file, biến môi trường, tuỳ chọn dòng lệnh);
  (3) mọi định nghĩa hàm `main` trong mã nguồn C của case khai báo không tham số (`main()` hoặc `main(void)`), nên chương trình không
      đọc được argv.
Bộ sinh của harness không đổi biến môi trường, nên (2) gồm getenv chỉ để chặt hơn."""
import glob, re, subprocess

INPUT_SYMS = frozenset({
    'read', 'readv', 'pread', 'pread64', '__read_chk', 'fread', 'fread_unlocked', '__fread_chk', 'fgets', 'fgets_unlocked', '__fgets_chk',
    'gets', 'getchar', 'getchar_unlocked', 'getc', 'getc_unlocked', '_IO_getc', 'fgetc', 'fgetc_unlocked', 'getline', 'getdelim',
    '__getdelim', 'getwchar', 'fgetws', 'scanf', 'fscanf', 'vscanf', 'vfscanf', '__isoc99_scanf', '__isoc99_fscanf', '__isoc99_vscanf',
    '__isoc99_vfscanf', '__isoc23_scanf', '__isoc23_fscanf', '__isoc23_vscanf', '__isoc23_vfscanf', 'wscanf', 'fwscanf',
    'getenv', 'secure_getenv', 'getopt', 'getopt_long', 'getopt_long_only', 'fopen', 'fopen64', 'freopen', 'open', 'open64', 'openat',
    'openat64', 'recv', 'recvfrom', 'mmap', 'mmap64', 'stdin', '_IO_2_1_stdin_', 'environ', '__environ',
    'fgetwc', 'getwc', 'preadv', 'recvmsg'})   # bốn ký hiệu cuối thêm 25/10 (Le chọn, master plan Hàng đợi F3)
CMT = re.compile(r'/\*.*?\*/|//[^\n]*', re.S)
STR = re.compile(r'"(?:\\.|[^"\\\n])*"')
MAIN_DEF = re.compile(r'\bmain\s*\(([^()]*)\)\s*\{')


def dyn_syms(binary):
    p = subprocess.run(['nm', '-D', binary], capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip(): return None
    return {l.split()[-1].split('@')[0] for l in p.stdout.splitlines() if l.split()}


_RUST_BASE = {}


def rust_baseline():
    """Ký hiệu INPUT_SYMS mà một binary Rust không đọc input (`fn main() {}`, build bằng rustc của máy, -O) vẫn nhập từ runtime std
    (Le chọn 26/10, dòng 5: trừ tập nền; std nhập sẵn read, getenv, open64, mmap64). Cache theo tiến trình; None khi không build được."""
    if 'syms' not in _RUST_BASE:
        import os, tempfile
        d = tempfile.mkdtemp(prefix='rustbase-'); src, out = os.path.join(d, 'm.rs'), os.path.join(d, 'm')
        open(src, 'w').write('fn main() {}\n')
        try:
            ok = subprocess.run(['rustc', '-O', '-o', out, src], capture_output=True, timeout=300).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        syms = dyn_syms(out) if ok else None
        v = subprocess.run(['rustc', '--version'], capture_output=True, text=True) if ok else None
        _RUST_BASE.update(syms=None if syms is None else sorted(syms & INPUT_SYMS), rustc=v.stdout.strip() if v else None)
    return _RUST_BASE


def input_syms(binary):
    """Hàng đợi master plan dòng 5 (F3, Le chọn 26/10): các ký hiệu INPUT_SYMS mà binary nhập, trừ tập nền của runtime Rust
    (rust_baseline; danh sách sắp xếp, rỗng khi không có); None khi không đọc được bảng ký hiệu động hoặc không có tập nền. Dùng cho
    binary Rust, chỉ để báo số, không thuộc tiêu chí `check`."""
    syms = dyn_syms(binary); base = rust_baseline()['syms']
    return None if syms is None or base is None else sorted((syms & INPUT_SYMS) - set(base))


def main_params(src_root):
    out = []
    for f in sorted(glob.glob(f'{src_root}/**/*.c', recursive=True)):
        s = STR.sub('""', CMT.sub(' ', open(f, errors='ignore').read()))
        out += [(f, m.group(1).strip()) for m in MAIN_DEF.finditer(s)]
    return out


def check(binary, src_root):
    """Trả về (bool, bằng chứng)."""
    syms = dyn_syms(binary)
    mains = main_params(src_root)
    ev = dict(dynamic=syms is not None, input_syms=sorted(syms & INPUT_SYMS) if syms else None,
              mains=[(f[len(src_root) + 1:], p) for f, p in mains])
    ok = syms is not None and not (syms & INPUT_SYMS) and bool(mains) and all(p in ('', 'void') for _, p in mains)
    return ok, ev
