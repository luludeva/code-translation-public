#!/usr/bin/env python3
"""Harness v0 (spike A3.2): differential testing C vs Rust bằng mutation trên test vector của TRACTOR.
Không dùng coverage. Kênh so sánh: exit code + stdout (byte-exact). stderr ghi lại, không so.
Mỗi input phân kỳ được chạy lại trên bản C build kèm ASan+UBSan để gắn cờ UB."""
import json, glob, os, random, re, subprocess, hashlib

BOUNDARY = ['0', '-1', '1', '2147483647', '-2147483648', '2147483648', '4294967295', '-9999999999', '255', '256', '65535', '1e308', '-0.0', 'nan', '']

def load_vectors(troot, exclude=()):
    seeds = []
    for f in sorted(glob.glob(f'{troot}/test_vectors/*.json')):
        name = os.path.basename(f)
        v = json.load(open(f))
        if 'has_ub' in v or name in exclude: continue
        seeds.append(dict(name=name, argv=list(v.get('argv') or []), stdin=v.get('stdin') or ''))
    return seeds

NUM = re.compile(r'-?\d+(\.\d+)?')

def mut_token(tok, rng):
    if NUM.fullmatch(tok) and rng.random() < 0.8:
        r = rng.random()
        if r < 0.5: return rng.choice(BOUNDARY)
        if '.' in tok: return str(float(tok) * rng.choice([-1, 2, 0.5, 1e6]))
        return str(int(tok) + rng.choice([-1, 1, -2, 2, 10**6, -10**6]))
    return rng.choice([tok * 2, tok[:max(0, len(tok) - 1)], rng.choice(BOUNDARY), tok + rng.choice(['x', ' ', '\t', '"', '\\'])])

def mutate(seed, rng, n_ops=None):
    argv, stdin = list(seed['argv']), seed['stdin']
    for _ in range(n_ops or rng.randint(1, 3)):
        if argv and (not stdin or rng.random() < 0.5):
            op = rng.random(); i = rng.randrange(len(argv))
            if op < 0.6: argv[i] = mut_token(argv[i], rng)
            elif op < 0.75: del argv[i]
            elif op < 0.9: argv.insert(i, argv[i])
            else: j = rng.randrange(len(argv)); argv[i], argv[j] = argv[j], argv[i]
        elif stdin:
            lines = stdin.split('\n'); op = rng.random(); i = rng.randrange(len(lines))
            if op < 0.45:
                toks = lines[i].split(' ')
                k = rng.randrange(len(toks)); toks[k] = mut_token(toks[k], rng); lines[i] = ' '.join(toks)
            elif op < 0.6: del lines[i]
            elif op < 0.72: lines.insert(i, lines[i])
            elif op < 0.8: j = rng.randrange(len(lines)); lines[i], lines[j] = lines[j], lines[i]
            elif op < 0.9: lines = lines[:i]
            else:
                b = bytearray(lines[i].encode()); 
                if b: b[rng.randrange(len(b))] = rng.randrange(1, 256)
                lines[i] = b.decode('latin-1')
            stdin = '\n'.join(lines)
    return argv, stdin

def run(binary, argv, stdin, timeout=5):
    try:
        p = subprocess.run([binary] + argv, input=stdin.encode('latin-1', 'replace'), capture_output=True, timeout=timeout)
        return dict(rc=p.returncode, out=p.stdout, err=p.stderr[-2000:], to=False)
    except subprocess.TimeoutExpired:
        return dict(rc=None, out=b'', err=b'', to=True)

def same(a, b):
    return a['to'] == b['to'] and (a['to'] or (a['rc'] == b['rc'] and a['out'] == b['out']))

SAN = re.compile(rb'runtime error:|AddressSanitizer|LeakSanitizer|UndefinedBehaviorSanitizer')

def campaign(c_bin, c_san_bin, rust_bin, seeds, budget, seed, timeout=5, stop_first=False):
    rng = random.Random(seed); found = []; tried = 0; seen = set()
    while tried < budget and seeds:
        s = rng.choice(seeds); argv, stdin = mutate(s, rng)
        key = hashlib.sha1(repr((argv, stdin)).encode()).hexdigest()
        if key in seen: continue
        seen.add(key); tried += 1
        c = run(c_bin, argv, stdin, timeout); r = run(rust_bin, argv, stdin, timeout)
        if same(c, r): continue
        san = run(c_san_bin, argv, stdin, timeout * 3) if c_san_bin else None
        found.append(dict(seed_vector=s['name'], argv=argv, stdin=stdin,
                          c_rc=c['rc'], c_timeout=c['to'], rust_rc=r['rc'], rust_timeout=r['to'],
                          c_stdout=c['out'].decode('latin-1')[-3000:], rust_stdout=r['out'].decode('latin-1')[-3000:],
                          rust_stderr=r['err'].decode('latin-1')[-800:],
                          c_ub=bool(san and SAN.search(san['err'])), c_san_stderr=(san['err'].decode('latin-1')[-800:] if san else None)))
        if stop_first: break
    return tried, found

def negative_control(bin_path, seeds, n_inputs, reps, seed, timeout=5):
    """Chạy cùng binary reps lần trên cùng input; trả về số input có output không ổn định."""
    rng = random.Random(seed); unstable = 0
    for _ in range(n_inputs):
        argv, stdin = mutate(rng.choice(seeds), rng)
        outs = [run(bin_path, argv, stdin, timeout) for _ in range(reps)]
        if not all(same(outs[0], o) for o in outs[1:]): unstable += 1
    return unstable
