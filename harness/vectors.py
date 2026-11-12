"""Đọc vector TRACTOR và quy ước byte của input.

Quy ước: mọi chuỗi trong input của harness là "chuỗi byte" (mỗi ký tự có mã < 256 là một byte). Chuỗi lấy từ vector được
chuyển sang byte theo UTF-8, như runner TRACTOR ghi stdin (`write_all(s.as_bytes())`) và truyền argv. Bộ sinh chép từ
exp 04, 08 thao tác trên chuỗi; với seed ASCII, input sinh ra giống hệt pilot. Khác pilot: harness pilot mã hoá bằng
latin-1 kèm `replace`, nên 4 vector có ký tự ngoài ASCII bị đổi byte (ghi ở experiments/10-harness-checks/notes.md)."""
import glob, json, os


def u2b(s):
    """Chuỗi Unicode của vector -> chuỗi byte (UTF-8)."""
    return s.encode('utf-8').decode('latin-1')


def to_bytes(s):
    """Chuỗi byte -> bytes. Ký tự >= 256 (vd hằng chuỗi trong dictionary) mã hoá UTF-8."""
    try:
        return s.encode('latin-1')
    except UnicodeEncodeError:
        return b''.join(c.encode('latin-1') if ord(c) < 256 else c.encode('utf-8') for c in s)


def read_vector(path):
    txt = open(path).read().strip()
    return json.loads(txt) if txt else None


def vector_files(troot):
    def key(p):
        b = os.path.basename(p)[:-5]
        return (0, int(b), b) if b.isdigit() else (1, 0, b)
    return sorted(glob.glob(f'{troot}/test_vectors/*.json'), key=key)


def exe_seeds(troot):
    """Vector executable không mang has_ub, dạng seed của bộ sinh: name, argv, stdin (chuỗi byte), vec gốc."""
    out = []
    for f in vector_files(troot):
        v = read_vector(f)
        if v is None or 'has_ub' in v: continue
        out.append(dict(name=os.path.basename(f), argv=[u2b(a) for a in (v.get('argv') or [])], stdin=u2b(v.get('stdin') or ''),
                        env=v.get('env'), vec=v))
    return out


def lib_seeds(troot):
    """Vector library không mang has_ub và có lib_state_in (như accept_lib.case_inputs)."""
    out = []
    for f in vector_files(troot):
        v = read_vector(f)
        if v is None or v.get('has_ub') is not None or 'lib_state_in' not in v: continue
        out.append(dict(file=os.path.basename(f), path=f, vec=v))
    return out
