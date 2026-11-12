#!/usr/bin/env python3
"""L1a, harness v2 (`docs/proposal/harness-v2-design.md` mục 2): dictionary hằng số trích từ AST của source C.

Cách làm: cấu hình CMake như census (preset của case nếu có, ngược lại `test_case`) với CMAKE_EXPORT_COMPILE_COMMANDS, chạy lại đúng lệnh biên dịch của từng file `.c`
kèm `-Xclang -ast-dump=json -fsyntax-only`, duyệt các khai báo nằm trong file chính (bỏ phần đến từ header hệ thống) và lấy
IntegerLiteral, FloatingLiteral, StringLiteral, CharacterLiteral. Literal nằm dưới toán tử một ngôi `-` lấy dạng âm.

Đầu ra (dict): ints, floats, strings (hằng gốc kèm số lần xuất hiện) và `values` là danh sách giá trị số đã mở rộng
(hằng gốc, lân cận, dẫn xuất), giới hạn MAX_VALUES, theo thứ tự ưu tiên của đặc tả.
Dùng: python3 cdict.py <thư mục case (chứa test_case/)> [thư mục build tạm]  (in JSON)."""
import collections, json, math, os, shlex, subprocess, sys, tempfile

MAX_VALUES, MAX_STRINGS, TOP_PAIR = 256, 64, 16


def configure_preset(case_root):
    """Như spike_lib.configure_preset: preset 'test' nếu có, ngược lại preset không ẩn đầu tiên."""
    f = f'{case_root}/CMakePresets.json'
    if not os.path.exists(f): return None
    names = [p['name'] for p in json.load(open(f)).get('configurePresets', []) if not p.get('hidden')]
    return 'test' if 'test' in names else (names[0] if names else None)


def compile_commands(case_root, build_dir):
    """Cấu hình như census (preset nếu case có CMakePresets.json, ngược lại test_case trực tiếp) để lấy đúng cờ biên dịch."""
    cc = f'{build_dir}/compile_commands.json'
    if not os.path.exists(cc):
        preset = configure_preset(case_root)
        cfg = (['cmake', '-S', case_root, '--preset', preset, '-B', build_dir] if preset
               else ['cmake', '-S', f'{case_root}/test_case', '-B', build_dir, '-G', 'Ninja'])
        subprocess.run(cfg + ['-DCMAKE_C_COMPILER=clang', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'], check=True, capture_output=True)
    return json.load(open(cc))


def ast_of(entry):
    args = entry['arguments'] if 'arguments' in entry else shlex.split(entry['command'])
    keep, skip = [], False
    for a in args[1:]:
        if skip: skip = False; continue
        if a == '-o': skip = True; continue
        if a in ('-c',) or a.endswith(('.o', '.obj')): continue
        keep.append(a)
    cmd = ['clang', *keep, '-fsyntax-only', '-Xclang', '-ast-dump=json']
    p = subprocess.run(cmd, cwd=entry['directory'], capture_output=True, text=True)
    if not p.stdout.strip(): return None
    return json.loads(p.stdout)


def walk(node, out, neg=False):
    k = node.get('kind')
    if k == 'UnaryOperator' and node.get('opcode') == '-' and node.get('inner'):
        for ch in node['inner']: walk(ch, out, not neg)
        return
    if k == 'IntegerLiteral':
        v = int(node['value']); out['ints'][-v if neg else v] += 1
    elif k == 'FloatingLiteral':
        v = float(node['value']); out['floats'][-v if neg else v] += 1
    elif k == 'CharacterLiteral':
        out['ints'][int(node['value'])] += 1
    elif k == 'StringLiteral':
        s = node.get('value', '')
        try: s = json.loads(s)   # clang ghi giá trị kèm dấu nháy và escape kiểu C, gần với JSON
        except Exception: s = s.strip('"')
        out['strings'][s] += 1
    for ch in node.get('inner', []) or []:
        walk(ch, out, neg if k in ('ImplicitCastExpr', 'ParenExpr', 'CStyleCastExpr') else False)


def in_main_file(decl):
    loc = decl.get('loc', {}) or {}
    if decl.get('isImplicit'): return False
    if 'includedFrom' in loc: return False
    rng = decl.get('range', {}).get('begin', {}) or {}
    return 'includedFrom' not in rng


def extract(case_root, build_dir=None):
    build_dir = build_dir or tempfile.mkdtemp(prefix='cdict-')
    out = dict(ints=collections.Counter(), floats=collections.Counter(), strings=collections.Counter())
    n_files = 0
    for e in compile_commands(case_root, build_dir):
        if not e['file'].endswith('.c'): continue
        ast = ast_of(e)
        if ast is None: continue
        n_files += 1
        for d in ast.get('inner', []):
            if in_main_file(d): walk(d, out)
    return finalize(out, n_files)


def neighbours_float(c):
    return [c, c + 1, c - 1, -c, math.nextafter(c, math.inf), math.nextafter(c, -math.inf)]


def finalize(out, n_files):
    consts = [(v, n, 'int') for v, n in out['ints'].items()] + [(v, n, 'float') for v, n in out['floats'].items()]
    consts.sort(key=lambda x: (-x[1], abs(x[0]), str(x[0])))
    vals, seen = [], set()

    def add(v, kind):
        if isinstance(v, float) and not math.isfinite(v): return
        key = (kind, v)
        if key in seen or len(vals) >= MAX_VALUES: return
        seen.add(key); vals.append(dict(v=v, kind=kind))

    for v, _, k in consts: add(v, 'const')                              # 1. hằng gốc
    for v, _, k in consts:                                              # 2. lân cận
        for x in (neighbours_float(float(v)) if k == 'float' else [v + 1, v - 1, -v]):
            add(x, 'near')
    top = [v for v, _, _ in consts[:TOP_PAIR]]                          # 3. dẫn xuất từ cặp hằng phổ biến nhất
    for i, a in enumerate(top):
        for b in top[i + 1:]:
            add(a + b, 'pair'); add(a - b, 'pair'); add(b - a, 'pair')
    strings = [s for s, _ in sorted(out['strings'].items(), key=lambda x: (-x[1], x[0]))][:MAX_STRINGS]
    return dict(n_files=n_files, ints=dict(out['ints']), floats={repr(k): v for k, v in out['floats'].items()},
                strings=strings, values=vals)


if __name__ == '__main__':
    d = extract(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(d, ensure_ascii=False, indent=1))
