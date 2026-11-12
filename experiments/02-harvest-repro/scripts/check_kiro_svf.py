#!/usr/bin/env python3
"""W4 (A5.5): kiểm 7 vector fail của kiro static_vars_fpts.

Với mọi vector của case (TRACTOR 37960ee): chạy bản C (clang) và bản C kèm ASan+UBSan trên đúng argv, stdin của vector;
so stdout của C với stdout của bản kiro ghi trong báo cáo oracle gốc ngày 28/09 (results/static-vars-fpts.kiro.report.json).
Không chạy lại bản Rust.

Biến môi trường: CORPUS (thư mục chứa clone TRACTOR ở 'tractor'), C_BIN, C_SAN_BIN, OUT.
Build (từ test_case của case):
  cmake -S <case>/test_case -B build-c -G Ninja -DCMAKE_C_COMPILER=clang && cmake --build build-c
  cmake -S <case>/test_case -B build-san -G Ninja -DCMAKE_C_COMPILER=clang \
        "-DCMAKE_C_FLAGS=-fsanitize=address,undefined -fno-sanitize-recover=undefined -g" && cmake --build build-san
"""
import json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.environ.get('CORPUS', os.path.expanduser('~/corpus')) + '/tractor/Public-Tests/B02_synthetic/static_vars_fpts'
REP = os.path.join(HERE, '..', 'results', 'static-vars-fpts.kiro.report.json')
C_BIN, C_SAN = os.environ['C_BIN'], os.environ['C_SAN_BIN']
OUT = os.environ.get('OUT', os.path.join(HERE, '..', 'results', 'kiro-svf-check.json'))
SAN = re.compile(rb'runtime error:|AddressSanitizer|LeakSanitizer|UndefinedBehaviorSanitizer')


def run(b, v, to=10):
    return subprocess.run([b] + list(v.get('argv') or []), input=(v.get('stdin') or '').encode('utf-8'),
                          capture_output=True, timeout=to)


rep = json.load(open(REP))
out = {}
for name in sorted(os.listdir(f'{T}/test_vectors')):
    v = json.load(open(f'{T}/test_vectors/{name}'))
    c, s = run(C_BIN, v), run(C_SAN, v)
    r = rep.get(name, {})
    out[name] = dict(oracle_result=r.get('result'), c_rc=c.returncode, c_san_rc=s.returncode,
                     c_ub=bool(SAN.search(s.stderr)), c_san_stderr=s.stderr.decode('utf-8', 'replace')[:500],
                     has_ub_field='has_ub' in v,
                     c_stdout_eq_kiro=(c.stdout.decode('utf-8', 'replace') == r['output']['stdout']) if 'output' in r else None)
json.dump(out, open(OUT, 'w'), indent=1, ensure_ascii=False)
fails = [n for n, o in out.items() if o['oracle_result'] != 'Pass']
print('fail:', len(fails), '| C-san báo UB trên vector fail:', sum(out[n]['c_ub'] for n in fails),
      '| C khác kiro trên vector fail:', sum(out[n]['c_stdout_eq_kiro'] is False for n in fails))
print('vector pass mà C khác kiro:', [n for n, o in out.items() if o['oracle_result'] == 'Pass' and o['c_stdout_eq_kiro'] is False])
print('vector pass mà C-san báo UB:', [n for n, o in out.items() if o['oracle_result'] == 'Pass' and o['c_ub']])
