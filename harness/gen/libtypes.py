#!/usr/bin/env python3
"""Đọc khối `state` của runner library TRACTOR (macro `harness!`) thành cây kiểu, và kiểm kiểu được bộ đột biến hỗ trợ.

Dùng cho K2a (kiểm tĩnh trên cả 229 library) và cho bộ sinh input K2b. Chỉ phân tích cú pháp, không build."""
import re

INTS = {  # tên kiểu -> (số bit, có dấu); x86_64 Linux
    'i8': (8, 1), 'i16': (16, 1), 'i32': (32, 1), 'i64': (64, 1), 'isize': (64, 1),
    'u8': (8, 0), 'u16': (16, 0), 'u32': (32, 0), 'u64': (64, 0), 'usize': (64, 0),
    'c_char': (8, 1), 'c_schar': (8, 1), 'c_uchar': (8, 0), 'c_short': (16, 1), 'c_ushort': (16, 0),
    'c_int': (32, 1), 'c_uint': (32, 0), 'c_long': (64, 1), 'c_ulong': (64, 0),
    'c_longlong': (64, 1), 'c_ulonglong': (64, 0), 'size_t': (64, 0), 'ssize_t': (64, 1),
}
FLOATS = {'f32': 32, 'c_float': 32, 'f64': 64, 'c_double': 64}
PREFIXES = ('libc::', 'std::ffi::', 'core::ffi::', 'std::os::raw::', 'cando2::')


def strip_comments(src):
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    return re.sub(r'//[^\n]*', '', src)


def matching(s, i, open_='{', close='}'):
    """Chỉ số của dấu đóng khớp với dấu mở tại s[i]."""
    d = 0
    for j in range(i, len(s)):
        if s[j] == open_: d += 1
        elif s[j] == close:
            d -= 1
            if d == 0: return j
    raise ValueError('không khớp ngoặc')


def split_top(s, sep=','):
    out, d, cur = [], 0, ''
    for ch in s:
        if ch in '<[(': d += 1
        elif ch in '>])': d -= 1
        if ch == sep and d == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    if cur.strip(): out.append(cur)
    return [x.strip() for x in out if x.strip()]


def parse_fields(body):
    fields = []
    for item in split_top(body):
        item = re.sub(r'^pub(\([^)]*\))?\s+', '', item.strip())
        name, _, ty = item.partition(':')
        fields.append((name.strip(), ty.strip()))
    return fields


def eval_len(expr, consts):
    e = expr.strip()
    for k, v in sorted(consts.items(), key=lambda kv: -len(kv[0])):
        e = re.sub(rf'\b{re.escape(k)}\b', str(v), e)
    e = e.replace('usize', '')
    if not re.fullmatch(r'[\d\s+\-*/()%]+', e): return None
    try: return int(eval(e, {'__builtins__': {}}))
    except Exception: return None


def parse_type(t, structs, consts, aliases, depth=0):
    t = t.strip()
    for p in PREFIXES:
        if t.startswith(p): t = t[len(p):]
    if depth > 20: return ('unsupported', t, 'đệ quy quá sâu')
    if t in aliases: return parse_type(aliases[t], structs, consts, aliases, depth + 1)
    if t in INTS: return ('int', t) + INTS[t]
    if t in FLOATS: return ('float', t, FLOATS[t])
    if t == 'bool': return ('bool',)
    if t == 'CString': return ('cstring',)
    if t == 'String': return ('string',)
    m = re.fullmatch(r'(Vec|Option|Box)\s*<(.*)>', t, flags=re.S)
    if m:
        inner = parse_type(m.group(2), structs, consts, aliases, depth + 1)
        return ('box', inner) if m.group(1) == 'Box' else (m.group(1).lower(), inner)
    if t.startswith('[') and t.endswith(']'):
        parts = split_top(t[1:-1], ';')
        if len(parts) == 2:
            n = eval_len(parts[1], consts)
            if n is None: return ('unsupported', t, f'độ dài mảng không tính được: {parts[1]}')
            return ('array', parse_type(parts[0], structs, consts, aliases, depth + 1), n)
    if t in structs.get('__enums__', {}):
        return ('enum', t, structs['__enums__'][t])
    if t in structs:
        return ('struct', t, [(f, parse_type(ft, structs, consts, aliases, depth + 1)) for f, ft in structs[t]])
    return ('unsupported', t, 'kiểu chưa hỗ trợ')


def unsupported_parts(ty):
    k = ty[0]
    if k == 'unsupported': return [ty[1] + ' (' + ty[2] + ')']
    if k in ('vec', 'option', 'box'): return unsupported_parts(ty[1])
    if k == 'array': return unsupported_parts(ty[1])
    if k == 'struct': return [p for _, ft in ty[2] for p in unsupported_parts(ft)]
    return []


def parse_runner(src_text):
    """Trả về dict: fields [(tên, kiểu thô, cây kiểu)], library, symbol, run_fn, hoặc error nếu không có khối state chuẩn."""
    s = strip_comments(src_text)
    consts = {}
    for m in re.finditer(r'\bconst\s+(\w+)\s*:\s*\w+\s*=\s*([^;]+);', s):
        v = eval_len(m.group(2), consts)
        if v is not None: consts[m.group(1)] = v
    aliases = {m.group(1): m.group(2) for m in re.finditer(r'\btype\s+(\w+)\s*=\s*([^;]+);', s)}
    structs, enums = {}, {}
    # struct/enum khai báo qua state_member! hoặc derive trực tiếp, ở bất kỳ đâu trong file
    for m in re.finditer(r'\b(struct|enum)\s+(\w+)\s*\{', s):
        i = m.end() - 1; j = matching(s, i)
        if m.group(1) == 'struct':
            structs[m.group(2)] = parse_fields(s[i + 1:j])
        else:
            enums[m.group(2)] = [v.split('=')[0].strip() for v in split_top(s[i + 1:j])]
    hm = re.search(r'harness!\s*\{', s)
    if not hm: return dict(error='không có harness!')
    hb = s[hm.end() - 1:matching(s, hm.end() - 1) + 1]
    sm = re.search(r'\bstate\s*:\s*\{', hb)
    if not sm: return dict(error='không có khối state')
    i = sm.end() - 1; j = matching(hb, i)
    raw = parse_fields(hb[i + 1:j])
    structs['__enums__'] = enums
    fields = [(f, t, parse_type(t, structs, consts, aliases)) for f, t in raw]
    lib = re.search(r'\blibrary\s*:\s*"([^"]+)"', hb)
    sym = re.search(r'\bsymbol\s*:\s*"([^"]+)"', hb)
    rm = re.search(r'fn\s+run\s*\(\s*&mut\s+self\s*\)\s*\{', hb)
    run_fn = hb[rm.end() - 1:matching(hb, rm.end() - 1) + 1] if rm else ''
    return dict(fields=fields, library=lib.group(1) if lib else None, symbol=sym.group(1) if sym else None,
                run_fn=run_fn, structs=sorted(k for k in structs if k != '__enums__'), enums=sorted(enums), consts=consts)


def shape_ok(ty, v):
    """Giá trị JSON của vector có khớp hình dạng với cây kiểu không (kiểm nhẹ, cho K2a)."""
    k = ty[0]
    if k == 'int': return isinstance(v, int) and not isinstance(v, bool)
    if k == 'float': return isinstance(v, (int, float)) and not isinstance(v, bool)
    if k == 'bool': return isinstance(v, bool)
    if k == 'enum': return v in ty[2]
    if k in ('cstring', 'string'): return isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, int) for x in v))
    if k == 'vec': return isinstance(v, list) and all(shape_ok(ty[1], x) for x in v)
    if k == 'option': return v is None or shape_ok(ty[1], v)
    if k == 'box': return shape_ok(ty[1], v)
    if k == 'array': return isinstance(v, list) and len(v) == ty[2] and all(shape_ok(ty[1], x) for x in v)
    if k == 'struct': return isinstance(v, dict) and set(v) == {f for f, _ in ty[2]} and all(shape_ok(ft, v[f]) for f, ft in ty[2])
    return False
