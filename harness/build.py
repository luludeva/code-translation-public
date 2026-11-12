"""Dựng binary cho harness, cache theo thư mục build (BUILD) và ghi log (harness-design.md mục 4.4, module build).

Executable C: như orchestrator TRACTOR (`experiments/02-harvest-repro/scripts/c_side.py`): case có CMakePresets.json cấu hình
  bằng preset 'test' từ bản chép của thư mục case; còn lại cấu hình `test_case` bằng Ninja. Compiler clang.
  Lưu ý: census executable (census.py) build C không theo preset; c-oracle-validity.json (theo preset) cho 109/109 case đỗ.
Rust: như census (`census.py` one, `census_lib.py` one): nguồn `verified/` nếu có, ngược lại `translated/`; RUSTC_BOOTSTRAP=1
  khi source có `#![feature`; executable lấy `driver` hoặc binary duy nhất; library lấy lib<library>.so, lệch tên thì alias
  khi chỉ có một .so (thủ tục §3.2, recheck_loss.py).
Library runner: crate runner của case, cando2 vá chế độ xuất state (cando2-state-dump.patch), như spike_lib.build_case."""
import contextlib, fcntl, functools, glob, hashlib, json, os, re, shutil, subprocess, time

from .config import H, SAN_FLAGS_EXE, SAN_FLAGS_LIB, STATE_DUMP_PATCH, T, CORPUS
from .gen.libtypes import parse_runner


def sh(cmd, cwd=None, env=None, timeout=3600):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-4000:], round(time.time() - t0, 2)
    except subprocess.TimeoutExpired:
        return 'timeout', '', round(time.time() - t0, 2)


def sha256(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest() if path and os.path.exists(path) else None


def preset_name(troot):
    f = f'{troot}/CMakePresets.json'
    if not os.path.exists(f): return None
    names = [p['name'] for p in json.load(open(f)).get('configurePresets', []) if not p.get('hidden')]
    return 'test' if 'test' in names else (names[0] if names else None)


@contextlib.contextmanager
def _lock(marker):
    """Khoá file theo đích build (sửa 2026-10-25, phát hiện khi chạy thử F8): khi thư mục build còn trống, hai worker chạy hai seed của
    cùng case build cùng một đích cùng lúc (rmtree của worker này xoá thư mục worker kia đang dùng; FileExistsError). Giữ khoá trong lúc
    build; worker sau đọc kết quả đã cache."""
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker + '.lock', 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)


def _locked(target):
    """Bọc hàm build: tính marker bằng target(*args), giữ khoá, kiểm cache lại sau khi có khoá."""
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **k):
            marker = target(*a, **k)
            got = _cached(marker)
            if got: return got
            with _lock(marker):
                got = _cached(marker)                      # worker khác vừa build xong trong lúc chờ khoá
                return got if got else fn(*a, **k)
        return w
    return deco


def _cached(marker):
    return json.load(open(marker)) if os.path.exists(marker) else None


# ---------------- executable ----------------
@_locked(lambda B, bundle, case, san=False: f"{B}/{'c-san' if san else 'c'}/{bundle}/{case}.build.json")
def build_c_exe(B, bundle, case, san=False):
    kind = 'c-san' if san else 'c'
    wd = f'{B}/{kind}/{bundle}/{case}'; marker = f'{wd}.build.json'
    got = _cached(marker)
    if got: return got
    troot = f'{T}/{bundle}/{case}'
    shutil.rmtree(wd, ignore_errors=True); os.makedirs(wd)
    shutil.copytree(f'{troot}/test_case', f'{wd}/test_case', symlinks=True)
    preset = preset_name(troot)
    bdir = f'{wd}/build-ninja'
    if preset:
        for f in ('CMakePresets.json', 'CMakeLists.txt'):
            if os.path.exists(f'{troot}/{f}'): shutil.copy(f'{troot}/{f}', wd)
        cfg = ['cmake', '-S', wd, '--preset', preset, '-DCMAKE_C_COMPILER=clang']
    else:
        cfg = ['cmake', '-S', f'{wd}/test_case', '-B', bdir, '-G', 'Ninja', '-DCMAKE_C_COMPILER=clang']
    rc1, l1, s1 = sh(cfg + (SAN_FLAGS_EXE if san else []))
    rc2, l2, s2 = sh(['cmake', '--build', bdir]) if rc1 == 0 else (rc1, '', 0)
    drivers = [p for p in glob.glob(f'{wd}/**/driver', recursive=True) if os.path.isfile(p) and os.access(p, os.X_OK)]
    ok = rc1 == 0 and rc2 == 0 and len(drivers) == 1
    info = dict(kind=kind, bundle=bundle, case=case, preset=preset, ok=ok, bin=drivers[0] if ok else None,
                sha256=sha256(drivers[0]) if ok else None, secs=round(s1 + s2, 2), log='' if ok else (l1 + l2)[-2000:])
    json.dump(info, open(marker, 'w'), indent=1)
    return info


def rust_src(system, bundle, hcase):
    base = f'{H}/{system}/{bundle}/{hcase}'
    return f'{base}/verified' if os.path.isdir(f'{base}/verified') else f'{base}/translated'


def _cargo(src, wd, td, B):
    if not os.path.isfile(f'{src}/Cargo.toml'):
        return 'no_source', f'không có Cargo.toml ở {src}', 0, False
    shutil.rmtree(wd, ignore_errors=True); os.makedirs(os.path.dirname(wd), exist_ok=True)
    shutil.copytree(src, wd, ignore=shutil.ignore_patterns('target', 'logs'))
    feat = any('#![feature' in open(f, errors='ignore').read() for f in glob.glob(f'{wd}/**/*.rs', recursive=True))
    env = dict(os.environ, RUSTC_BOOTSTRAP='1') if feat else dict(os.environ)
    rc, log, secs = sh(['cargo', 'build', '--release', '--target-dir', td], cwd=wd, env=env, timeout=3600)
    shutil.rmtree(wd, ignore_errors=True)
    return rc, log, secs, feat


@_locked(lambda B, system, bundle, case, hcase: f'{B}/rust/{system}/{bundle}/{case}.build.json')
def build_rust_exe(B, system, bundle, case, hcase):
    td = f'{B}/rust/{system}/{bundle}/{case}'; marker = f'{td}.build.json'
    got = _cached(marker)
    if got: return got
    src = rust_src(system, bundle, hcase)
    rc, log, secs, feat = _cargo(src, f'{B}/src/{system}/{bundle}/{case}', td, B)
    info = dict(system=system, bundle=bundle, case=case, source_dir=os.path.basename(src), rustc_bootstrap=feat, secs=secs)
    if rc != 0:
        info.update(ok=False, log=log[-2000:])
    else:
        bins = [p for p in glob.glob(f'{td}/release/*') if os.path.isfile(p) and os.access(p, os.X_OK) and not p.endswith('.d')]
        binp = f'{td}/release/driver' if f'{td}/release/driver' in bins else (bins[0] if len(bins) == 1 else None)
        info.update(ok=binp is not None, bin=binp, sha256=sha256(binp),
                    log='' if binp else 'no unique binary: ' + ','.join(map(os.path.basename, bins)))
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    json.dump(info, open(marker, 'w'), indent=1)
    return info


# ---------------- library ----------------
def setup_cando2(B):
    dst = f'{B}/cando2-dump'
    # Sửa 2026-10-23: kiểm hash bản vá; bản cũ chỉ kiểm file .patched tồn tại nên đổi bản vá không làm build lại.
    if os.path.exists(f'{dst}/.patched') and open(f'{dst}/.patched').read().strip() == sha256(STATE_DUMP_PATCH): return dst
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(f'{CORPUS}/tractor/tools/cando2', dst, ignore=shutil.ignore_patterns('target'))
    subprocess.run(['git', 'apply', STATE_DUMP_PATCH], cwd=dst, check=True, capture_output=True)
    open(f'{dst}/.patched', 'w').write(sha256(STATE_DUMP_PATCH) + '\n')
    return dst


@_locked(lambda B, bundle, case: f'{B}/libcase/{bundle}/{case}.build.json')
def build_lib_case(B, bundle, case):
    """Runner crate của case + C .so + C-san .so. Trả về dict thông tin case (cache)."""
    d = f'{B}/libcase/{bundle}/{case}'; marker = f'{d}.build.json'
    got = _cached(marker)
    if got and got.get('state_dump_patch_sha256') == sha256(STATE_DUMP_PATCH): return got   # bản vá đổi thì build lại runner
    os.makedirs(d, exist_ok=True)
    troot = f'{T}/{bundle}/{case}'
    parsed = parse_runner(open(f'{troot}/runner/src/main.rs').read())
    info = dict(bundle=bundle, case=case, library=parsed.get('library') or case, symbol=parsed.get('symbol'))
    cd2 = setup_cando2(B)
    rdir = f'{d}/runner'; shutil.rmtree(rdir, ignore_errors=True)
    shutil.copytree(f'{troot}/runner', rdir, ignore=shutil.ignore_patterns('target', 'fuzz'))
    toml = open(f'{rdir}/Cargo.toml').read().replace('path = "../../../../tools/cando2"', f'path = "{cd2}"')
    if '[workspace]' not in toml: toml += '\n[workspace]\n'
    open(f'{rdir}/Cargo.toml', 'w').write(toml)
    if os.path.exists(f'{cd2}/Cargo.lock'): shutil.copy(f'{cd2}/Cargo.lock', f'{rdir}/Cargo.lock')
    pkg = re.search(r'name\s*=\s*"([^"]+)"', toml).group(1)
    rc, log, secs = sh(['cargo', 'build', '--release', '-q', '--target-dir', f'{B}/runner-target'], cwd=rdir)
    info['runner_bin'] = f'{B}/runner-target/release/{pkg}'
    info['runner_ok'] = rc == 0 and os.path.exists(info['runner_bin'])
    if not info['runner_ok']: info['runner_log'] = log[-2000:]
    info['state_dump_patch_sha256'] = sha256(STATE_DUMP_PATCH)
    preset = preset_name(troot); info['preset'] = preset
    for kind, flags in (('c', []), ('c-san', SAN_FLAGS_LIB)):
        bd = f'{d}/{kind}'; shutil.rmtree(bd, ignore_errors=True)
        cfg = (['cmake', '-S', troot, '--preset', preset, '-B', bd, '-DCMAKE_C_COMPILER=clang'] if preset
               else ['cmake', '-S', f'{troot}/test_case', '-B', bd, '-G', 'Ninja', '-DCMAKE_C_COMPILER=clang'])
        rc1, l1, _ = sh(cfg + flags)
        rc2, l2, _ = sh(['cmake', '--build', bd]) if rc1 == 0 else (rc1, '', 0)
        so = f'{bd}/lib{info["library"]}.so'
        info[f'{kind}_ok'] = os.path.exists(so); info[f'{kind}_dir'] = bd; info[f'{kind}_sha256'] = sha256(so)
        if not info[f'{kind}_ok']: info[f'{kind}_log'] = (l1 + l2)[-2000:]
    json.dump(info, open(marker, 'w'), indent=1)
    return info


@_locked(lambda B, system, bundle, case, hcase, library: f'{B}/rust-lib/{system}/{bundle}/{case}.build.json')
def build_rust_lib(B, system, bundle, case, hcase, library):
    td = f'{B}/rust-lib/{system}/{bundle}/{case}'; marker = f'{td}.build.json'
    got = _cached(marker)
    if got: return got
    src = rust_src(system, bundle, hcase)
    rc, log, secs, feat = _cargo(src, f'{B}/src-lib/{system}/{bundle}/{case}', f'{td}/target', B)
    info = dict(system=system, bundle=bundle, case=case, source_dir=os.path.basename(src), rustc_bootstrap=feat, secs=secs, dir=td)
    rel = f'{td}/target/release'; want = f'{rel}/lib{library}.so'
    if rc != 0:
        info.update(ok=False, log=log[-2000:])
    elif os.path.exists(want):
        info.update(ok=True, so=want, sha256=sha256(want))
    else:
        found = glob.glob(f'{rel}/*.so')
        if len(found) == 1:
            os.symlink(os.path.basename(found[0]), want)
            info.update(ok=True, so=want, sha256=sha256(want), so_alias=f'{os.path.basename(found[0])} -> lib{library}.so')
        else:
            info.update(ok=False, log='so: ' + ','.join(map(os.path.basename, found)))
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    json.dump(info, open(marker, 'w'), indent=1)
    return info


def lib_root(B, info, kind, rust_dir=None, tag=None):
    """Thư mục gốc test cho runner: tên thư mục = tên case (runner suy tên library mặc định từ đó)."""
    tag = tag or kind
    root = f'{B}/roots/{tag}/{info["bundle"]}/{info["case"]}'
    if os.path.isdir(root): return root
    os.makedirs(root)
    troot = f'{T}/{info["bundle"]}/{info["case"]}'
    os.symlink(f'{troot}/test_case', f'{root}/test_case'); os.symlink(f'{troot}/test_vectors', f'{root}/test_vectors')
    os.symlink(info['c-san_dir'] if kind == 'c-san' else info['c_dir'], f'{root}/build-ninja')
    if rust_dir: os.symlink(rust_dir, f'{root}/translated_rust')
    return root


def asan_preload():
    p = subprocess.run(['clang', '-print-file-name=libclang_rt.asan-x86_64.so'], capture_output=True, text=True).stdout.strip()
    return p if os.path.exists(p) else None
