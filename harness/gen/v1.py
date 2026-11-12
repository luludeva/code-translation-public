#!/usr/bin/env python3
"""Harness v1 (exp 04, pilot cho cổng A3.3).

Giữ nguyên kênh so sánh và luật của harness v0 (exit code + stdout, R-NaN, sanitizer phía C cho input phân kỳ),
thêm hai nguồn input:
  - MS: đột biến cấu trúc (argv rỗng, chèn token rỗng, bật/tắt stdin) trước các phép đột biến của v0;
  - A : queue của AFL++ khi fuzz phía C (shim đọc argv và stdin từ một file đầu vào), replay trên C gốc và Rust.
Một input sinh ra được chạy trên C đúng một lần rồi so với mọi bản Rust của cùng case.
"""
import os, re, sys, random, hashlib, subprocess
from .v0 import mutate, SAN  # giữ nguyên toán tử của v0

NAN = re.compile(rb'-?nan', re.I)

def norm(out: bytes) -> bytes:
    """Luật chuẩn hoá đã đăng ký: R-NaN (coi -nan, nan, NaN là như nhau)."""
    return NAN.sub(b'nan', out)

def run(binary, argv, stdin, timeout=5):
    try:
        p = subprocess.run([binary] + argv, input=stdin.encode('latin-1', 'replace'), capture_output=True, timeout=timeout)
        return dict(rc=p.returncode, out=p.stdout, err=p.stderr[-2000:], to=False)
    except subprocess.TimeoutExpired:
        return dict(rc=None, out=b'', err=b'', to=True)

def same(a, b):
    """Quyết định của oracle: hai phía cùng timeout, hoặc cùng exit code và cùng stdout sau chuẩn hoá."""
    return a['to'] == b['to'] and (a['to'] or (a['rc'] == b['rc'] and norm(a['out']) == norm(b['out'])))

# ---------- MS: đột biến cấu trúc ----------
def mutate_struct(seed, rng, all_seeds, p_struct=0.3):
    s = dict(seed)
    if rng.random() < p_struct:
        op = rng.random()
        if op < 0.3:
            s['argv'] = []                                   # không truyền đối số nào
        elif op < 0.55:
            a = list(s['argv']); a.insert(rng.randint(0, len(a)), ''); s['argv'] = a   # chèn token rỗng
        elif op < 0.8:
            s['stdin'] = ''                                  # tắt stdin
        else:
            donors = [x for x in all_seeds if x['stdin']]    # bật stdin bằng stdin của vector khác
            s['stdin'] = rng.choice(donors)['stdin'] if donors else rng.choice(['\n', '0\n', 'x\n'])
        if rng.random() < 0.5:
            return s['argv'], s['stdin']
    return mutate(s, rng)

# Độ lệch seed theo tầng (Le chọn 25/10, master plan Hàng đợi F3): trước đây M và MS dùng chung dãy ngẫu nhiên. Tầng M giữ nguyên
# (offset 0) để input M không đổi so với các lần chạy trước; MS lấy dãy riêng.
LAYER_RNG_OFFSET = {'M': 0, 'MS': 500_000}


def gen_inputs(seeds, layer, budget, seed):
    """Sinh tối đa `budget` input khác nhau, tất định theo (seeds, layer, seed); mỗi tầng một dãy ngẫu nhiên riêng."""
    rng = random.Random(seed + LAYER_RNG_OFFSET[layer]); seen = set(); out = []; guard = 0
    while len(out) < budget and seeds and guard < budget * 50:
        guard += 1
        s = rng.choice(seeds)
        argv, stdin = mutate(s, rng) if layer == 'M' else mutate_struct(s, rng, seeds)
        key = hashlib.sha1(repr((argv, stdin)).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key); out.append((argv, stdin))
    return out

# ---------- A: mã hoá input cho shim AFL ----------
SEP = b'\x01'

def encode(argv, stdin):
    return b'\x00'.join(a.encode('latin-1', 'replace') for a in argv) + SEP + stdin.encode('latin-1', 'replace')

def decode(blob):
    if SEP in blob:
        a, s = blob.split(SEP, 1)
        argv = [x.decode('latin-1') for x in a.split(b'\x00')] if a else []
    else:
        argv, s = [], blob
    return argv, s.decode('latin-1')

SHIM_C = r'''
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
int __orig_main(int, char **);
int main(int argc, char **argv) {
  static unsigned char buf[1 << 20]; size_t n = 0; ssize_t r;
  while (n < sizeof buf && (r = read(0, buf + n, sizeof buf - n)) > 0) n += (size_t)r;
  unsigned char *sep = memchr(buf, 1, n);
  size_t alen = sep ? (size_t)(sep - buf) : 0;
  unsigned char *in = sep ? sep + 1 : buf; size_t inlen = sep ? n - alen - 1 : n;
  char *av[256]; int ac = 0; av[ac++] = argv[0];
  if (sep) { size_t st = 0; for (size_t i = 0; i <= alen && ac < 255; i++) if (i == alen || buf[i] == 0) {
      char *t = malloc(i - st + 1); memcpy(t, buf + st, i - st); t[i - st] = 0; av[ac++] = t; st = i + 1; } }
  av[ac] = NULL;
  int fd = memfd_create("in", 0); if (inlen) { ssize_t w = write(fd, in, inlen); (void)w; } lseek(fd, 0, SEEK_SET); dup2(fd, 0); close(fd);
  return __orig_main(ac, av);
}
'''

def sanitizer_flags_ub(c_san_bin, argv, stdin, timeout):
    san = run(c_san_bin, argv, stdin, timeout * 3)
    return bool(SAN.search(san['err'])), san['err'].decode('latin-1')[-800:]
