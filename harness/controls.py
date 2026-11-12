"""Compiler control GCC với Clang: dựng bản C bằng gcc (kế hoạch A3-A7 mục 2.3 dòng `harness/controls.py`, 2.5, 3.4; Le duyệt 25/10).

Bản C gcc đóng vai phía Rust trong `rq1.judge_*`, nên so bằng đúng oracle RQ1 (ổn định qua STAB_REPS, sanitizer phía C-clang), trên
tập input của pha R ở L*, seed 0. Module chỉ dựng và kiểm build; vòng so nằm ở `harness/sweep.py` (lệnh `cc`).

Executable: như `build.build_c_exe` (preset 'test' nếu có, ngược lại Ninja trên `test_case`), chỉ đổi `-DCMAKE_C_COMPILER=gcc`.
Library: như phần `c` của `build.build_lib_case`, đổi `-DCMAKE_C_COMPILER=gcc` và `-DCLANG_EXECUTABLE=<gcc>` (CMakeLists của P01 tự ép
  clang nếu tìm thấy, `experiments/07-library-controls/scripts/gcc_clang_control.py` dòng 23-25). Cùng cờ đặt ở executable cho đồng
  nhất (biến cache, case không dùng thì không có tác dụng).
Kiểm build (mục 3.4, như gcc_clang_control.py dòng 43-47): artefact gcc khác byte artefact clang; mục `.comment` của artefact gcc không
  chứa "clang".

Phía runner library: `rq1.judge_lib` luôn gọi phía "Rust" với `--rust`, nên `.so` gcc được đặt ở `translated_rust/target/release/`
  của một root riêng (`gcc_lib_root`). Ở cando2 tại tractor_commit, `--rust` của chế độ lib chỉ đổi thư mục tìm `.so`
  (`tools/cando2/src/common.rs` get_build_dir, `runners/lib_runner.rs` get_library); khác chữ mục 2.5 ("chạy không --rust"), lý do
  ở `sweep.cc_lib_case` và báo cáo. `rust_flag_check` chạy vector gốc trên `.so` gcc theo cả hai cách gọi để kiểm điều đó trên máy đo."""
import glob, json, os, shutil, subprocess

from . import build as BD
from .config import T


def gcc_path():
    return shutil.which('gcc') or 'gcc'


def gcc_flags():
    return ['-DCMAKE_C_COMPILER=gcc', f'-DCLANG_EXECUTABLE={gcc_path()}']


def comment_section(path):
    """Nội dung mục .comment (readelf -p), chuỗi rỗng nếu không đọc được."""
    try:
        return subprocess.run(['readelf', '-p', '.comment', path], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ''


def build_checks(gcc_art, clang_art):
    """Mục 3.4: hai artefact khác byte; .comment của artefact gcc không có 'clang'. None khi thiếu artefact."""
    ok = bool(gcc_art) and os.path.exists(gcc_art) and bool(clang_art) and os.path.exists(clang_art)
    if not ok: return dict(bytes_differ=None, gcc_comment_clang_free=None, ok=False)
    differ = open(gcc_art, 'rb').read() != open(clang_art, 'rb').read()
    free = 'clang' not in comment_section(gcc_art).lower()
    return dict(bytes_differ=differ, gcc_comment_clang_free=free, ok=differ and free, gcc_sha256=BD.sha256(gcc_art),
                clang_sha256=BD.sha256(clang_art))


@BD._locked(lambda B, bundle, case: f'{B}/c-gcc/{bundle}/{case}.build.json')
def build_c_gcc_exe(B, bundle, case):
    """Như build.build_c_exe (san=False), compiler gcc. Cache theo marker như build.py."""
    wd = f'{B}/c-gcc/{bundle}/{case}'; marker = f'{wd}.build.json'
    got = BD._cached(marker)
    if got: return got
    troot = f'{T}/{bundle}/{case}'
    shutil.rmtree(wd, ignore_errors=True); os.makedirs(wd)
    shutil.copytree(f'{troot}/test_case', f'{wd}/test_case', symlinks=True)
    preset = BD.preset_name(troot)
    bdir = f'{wd}/build-ninja'
    if preset:
        for f in ('CMakePresets.json', 'CMakeLists.txt'):
            if os.path.exists(f'{troot}/{f}'): shutil.copy(f'{troot}/{f}', wd)
        cfg = ['cmake', '-S', wd, '--preset', preset] + gcc_flags()
    else:
        cfg = ['cmake', '-S', f'{wd}/test_case', '-B', bdir, '-G', 'Ninja'] + gcc_flags()
    rc1, l1, s1 = BD.sh(cfg)
    rc2, l2, s2 = BD.sh(['cmake', '--build', bdir]) if rc1 == 0 else (rc1, '', 0)
    drivers = [p for p in glob.glob(f'{wd}/**/driver', recursive=True) if os.path.isfile(p) and os.access(p, os.X_OK)]
    ok = rc1 == 0 and rc2 == 0 and len(drivers) == 1
    info = dict(kind='c-gcc', bundle=bundle, case=case, preset=preset, ok=ok, bin=drivers[0] if ok else None,
                sha256=BD.sha256(drivers[0]) if ok else None, secs=round(s1 + s2, 2), log='' if ok else (l1 + l2)[-2000:],
                flags=gcc_flags())
    json.dump(info, open(marker, 'w'), indent=1)
    return info


@BD._locked(lambda B, info: f'{B}/c-gcc-lib/{info["bundle"]}/{info["case"]}.build.json')
def build_c_gcc_lib(B, info):
    """Như phần `c` của build.build_lib_case, compiler gcc. info: kết quả build.build_lib_case (bundle, case, library, preset)."""
    bundle, case = info['bundle'], info['case']
    bd = f'{B}/c-gcc-lib/{bundle}/{case}/c'; marker = f'{B}/c-gcc-lib/{bundle}/{case}.build.json'
    got = BD._cached(marker)
    if got: return got
    troot = f'{T}/{bundle}/{case}'
    preset = BD.preset_name(troot)
    shutil.rmtree(bd, ignore_errors=True)
    cfg = (['cmake', '-S', troot, '--preset', preset, '-B', bd] if preset
           else ['cmake', '-S', f'{troot}/test_case', '-B', bd, '-G', 'Ninja']) + gcc_flags()
    rc1, l1, _ = BD.sh(cfg)
    rc2, l2, _ = BD.sh(['cmake', '--build', bd]) if rc1 == 0 else (rc1, '', 0)
    so = f'{bd}/lib{info["library"]}.so'
    out = dict(bundle=bundle, case=case, library=info['library'], preset=preset, dir=bd, so=so, ok=os.path.exists(so),
               sha256=BD.sha256(so), flags=gcc_flags(), log='' if os.path.exists(so) else (l1 + l2)[-2000:])
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    json.dump(out, open(marker, 'w'), indent=1)
    return out


def gcc_lib_root(B, info, g):
    """Root runner cho phía 'Rust' của judge_lib: build-ninja trỏ C-clang (như mọi root của harness), translated_rust/target/release
    chứa lib<library>.so là bản gcc (symlink). Tag riêng 'cc-gcc' (rủi ro R7: lib_root trả thư mục cũ khi đã tồn tại)."""
    rd = f'{B}/c-gcc-lib/{info["bundle"]}/{info["case"]}/as-rust'
    rel = f'{rd}/target/release'; os.makedirs(rel, exist_ok=True)
    link = f'{rel}/lib{info["library"]}.so'
    if not os.path.lexists(link): os.symlink(g['so'], link)
    return BD.lib_root(B, info, 'c', rd, tag='cc-gcc')


def gcc_lib_croot(B, info, g):
    """Root để gọi .so gcc như phía C (không --rust): build-ninja trỏ thư mục gcc. Chỉ dùng cho rust_flag_check."""
    return BD.lib_root(B, dict(info, c_dir=g['dir']), 'c', tag='cc-gcc-as-c')
