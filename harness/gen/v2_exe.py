#!/usr/bin/env python3
"""Bộ sinh input executable cho harness v2 (`docs/proposal/harness-v2-design.md` mục 2): harness v1 cộng L1a và L3a.

Mỗi tầng M, MS với ngân sách N: 70% đầu là đúng các input đầu tiên mà harness v1 sinh (cùng seed), nhãn `random`;
30% còn lại sinh bằng một phép v2 trên seed vector: phép dictionary (nhãn `dict`) hoặc toán tử cú pháp L3a (nhãn `syntax`).
  - dict: thay token argv bằng hằng (chuỗi hoặc số), chèn hằng vào argv, chèn hằng vào stdin.
  - syntax: thêm khoảng trắng đầu token argv; lặp một ký tự thành chuỗi dài 64 đến 4096; cắt cụt stdin ở vị trí ngẫu nhiên.
Tầng AFL: file dictionary cho `afl-fuzz -x` (write_afl_dict).
Tất định theo (seeds, layer, budget, seed, dictionary). Ngân sách tính bằng số input sinh, khác nhau trong tầng; mỗi tầng
một dãy ngẫu nhiên riêng (LAYER_RNG_OFFSET, 25/10)."""
import hashlib, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
from .v1 import LAYER_RNG_OFFSET, gen_inputs

P_V2 = 0.3
AFL_TOKEN_MAX = 128


def tokens(cd):
    """Chuỗi hằng và giá trị số (dạng chữ) của dictionary, bỏ trùng, giữ thứ tự ưu tiên."""
    out, seen = [], set()
    for s in cd.get('strings', []):
        if s and s not in seen: seen.add(s); out.append(s)
    for x in cd.get('values', []):
        v = x['v']; t = str(int(v)) if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) < 1e15) else repr(v)
        if t not in seen: seen.add(t); out.append(t)
    return out


def op_dict(argv, stdin, rng, toks):
    argv = list(argv); t = rng.choice(toks); k = rng.random()
    if argv and k < 0.4:
        argv[rng.randrange(len(argv))] = t
    elif k < 0.7:
        argv.insert(rng.randint(0, len(argv)), t)
    else:
        lines = stdin.split('\n') if stdin else ['']
        i = rng.randrange(len(lines)); words = lines[i].split(' ')
        j = rng.randrange(len(words))
        if words[j] and rng.random() < 0.5: words[j] = t
        else: words.insert(j, t)
        lines[i] = ' '.join(words); stdin = '\n'.join(lines)
    return argv, stdin


def op_syntax(argv, stdin, rng):
    argv = list(argv)
    choices = []
    if argv: choices += ['lead_ws', 'long']
    if stdin: choices += ['truncate', 'long_stdin']
    if not choices: return argv, stdin
    c = rng.choice(choices)
    if c == 'lead_ws':
        i = rng.randrange(len(argv)); argv[i] = rng.choice([' ', '\t', '  ']) + argv[i]
    elif c == 'long':
        i = rng.randrange(len(argv)); ch = rng.choice(argv[i] or '0') if argv[i] else rng.choice('0123456789a')
        argv[i] = ch * rng.randint(64, 4096)
    elif c == 'truncate':
        stdin = stdin[:rng.randrange(len(stdin))]
    else:
        lines = stdin.split('\n'); i = rng.randrange(len(lines)); ch = rng.choice(lines[i] or '0')
        lines[i] = lines[i] + ch * rng.randint(64, 4096); stdin = '\n'.join(lines)
    return argv, stdin


def gen_inputs_v2(seeds, layer, budget, seed, cd):
    """Trả về danh sách (argv, stdin, source)."""
    n_v2 = round(P_V2 * budget); n_v1 = budget - n_v2
    v1 = gen_inputs(seeds, layer, n_v1, seed)
    out = [(a, s, 'random') for a, s in v1]
    seen = {hashlib.sha1(repr((a, s)).encode()).hexdigest() for a, s in v1}
    # Seed của phần toán tử phụ thuộc tầng (Le chọn 25/10): trước đây `seed + 1000` cho cả M và MS nên phần toán tử của MS lặp đúng dãy
    # của M rồi bị bỏ trùng giữa tầng (exp 11 x10: MS còn 11.478 đến 20.287 trên 30.000). Tầng M giữ seed cũ.
    toks = tokens(cd); rng = random.Random(seed + 1000 + LAYER_RNG_OFFSET[layer]); guard = 0
    while len(out) < budget and seeds and guard < n_v2 * 50:
        guard += 1
        sd = rng.choice(seeds)
        if toks and rng.random() < 0.5:
            argv, stdin = op_dict(sd['argv'], sd['stdin'], rng, toks); src = 'dict'
        else:
            argv, stdin = op_syntax(sd['argv'], sd['stdin'], rng); src = 'syntax'
        key = hashlib.sha1(repr((argv, stdin)).encode()).hexdigest()
        if key in seen: continue
        seen.add(key); out.append((argv, stdin, src))
    return out


def write_afl_dict(cd, path):
    """Định dạng dictionary của AFL++: mỗi dòng `name="..."`, escape byte ngoài ASCII in được."""
    lines = []
    for i, t in enumerate(tokens(cd)):
        b = t.encode('latin-1', 'replace')[:AFL_TOKEN_MAX]
        if not b: continue
        esc = ''.join(chr(c) if 32 <= c < 127 and chr(c) not in '"\\' else f'\\x{c:02x}' for c in b)
        lines.append(f'tok{i}="{esc}"')
    open(path, 'w').write('\n'.join(lines) + '\n')
    return len(lines)
