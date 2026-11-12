#!/usr/bin/env python3
"""Cổng smoke build của exp 37 (docs/amendment-2026-11-05-rq2-san-supp.md mục 7 bước 3). Chỉ đọc file build trên đĩa và chạy `clang -###`;
không thực thi binary nào. Đạt khi đủ mọi điều kiện ở mọi case; một điều kiện không đạt thì job dừng (mục 10).
  S-orig : marker build cờ gốc của case smoke có ok false, trường log (2000 ký tự cuối) chứa R_X86_64_PC32, "recompile with -fPIC" và
           libsphincs_core.so.
  S-pic  : marker build PIC của mọi case có ok true, và thư mục build có đúng một `driver` (tìm như build_c_exe), trùng trường bin.
  S-cache: CMakeCache.txt của bản PIC (<wd>/build-ninja) có dòng S_CACHE_LINE (đúng chữ của amendment; xem chú thích ở hằng).
  S-ninja: so build.ninja bản PIC với bản cờ gốc sau khi thay thư mục build của từng bản bằng <WD> (cách chuẩn hoá của
           logs/flags-orig-vs-pic-005.txt): mọi object của sphincs_obj thêm đúng -fPIC; object PQCgenKAT_sign.c.o của driver thêm đúng
           -fPIE; mọi object khác giữ nguyên cờ; LINK_FLAGS, LINK_LIBRARIES giống nhau. Ngoài ra mọi dòng khác của build.ninja phải giống
           nhau (khác biệt ngoài các dòng FLAGS đã đăng ký là "khác thay đổi ở mục 4", luật dừng mục 5), và CMakeFiles/rules.ninja của hai
           bản giống nhau sau chuẩn hoá (review N5; chặt hơn văn bản, chỉ theo hướng dừng).
  S-clang: clang -### -fsanitize=address,undefined -O3, có và không có -fPIE, cùng cho -mrelocation-model pic -pic-level 2 -pic-is-pie.
Thư mục: --pic-dir, --orig-dir là thư mục chứa <case>/ và <case>.build.json (build_c_exe: {B}/c-san/<bundle>/).
Dùng: python3 smoke_gate.py --pic-dir P --orig-dir O --keys keys.txt [--out gate.json] [--archive DIR] [--cases-jsonl F]
--cases-jsonl ghi mỗi case một dòng (kết quả S-pic, S-cache, S-ninja); tên rq2-*.jsonl để guard của bước Publish (đếm dòng rq[12]-*.jsonl)
không đè kết quả đã nộp bằng một lần chạy không làm gì.
Mã thoát: 0 đạt, 3 không đạt (luật dừng); 1 khi script lỗi, 2 khi dùng sai: job xếp `fail` (review R2-12)."""
import argparse, glob, json, os, re, shutil, subprocess, sys

SIG = ('R_X86_64_PC32', 'recompile with -fPIC', 'libsphincs_core.so')
# Amendment mục 7 S-cache (Le chốt 2026-11-05, review wave 2 C1): cờ đã đăng ký `-DCMAKE_POSITION_INDEPENDENT_CODE=ON` không ghi kiểu, nên
# CMake 3.28.3 ghi `CMAKE_POSITION_INDEPENDENT_CODE:UNINITIALIZED=ON` (cả 4 cây build PIC của bản tái hiện trong container). Cờ giữ nguyên, không ghi kiểu.
S_CACHE_LINE = 'CMAKE_POSITION_INDEPENDENT_CODE:UNINITIALIZED=ON'
SPHINCS_OBJ = '/sphincs_obj.dir/'
DRIVER_OBJ = '/driver.dir/src/PQCgenKAT_sign.c.o'
CLANG_BASE = ['-fsanitize=address,undefined', '-O3']
CLANG_WANT = dict(relocation_model='pic', pic_level='2', pic_is_pie=True)
EXIT_NOT_PASSED = 3                       # mã 3 như luật dừng của harness.rq2_san_supp; 1 là traceback của script
EDGE = re.compile(r'^build (.*?)(?<!\$): (\S+)')


def jload(p):
    try:
        with open(p) as f: return json.load(f)
    except (OSError, ValueError): return None


def drivers(wd):
    """Như build_c_exe: file `driver` thực thi được dưới thư mục case."""
    return sorted(p for p in glob.glob(f'{wd}/**/driver', recursive=True) if os.path.isfile(p) and os.access(p, os.X_OK))


# ---------------- S-orig, S-pic, S-cache ----------------
def s_orig(orig_dir, case):
    m = jload(f'{orig_dir}/{case}.build.json')
    if m is None: return dict(ok=False, reason='không có marker build cờ gốc')
    log = m.get('log') or ''
    miss = [s for s in SIG if s not in log]
    ok = m.get('ok') is False and not miss
    return dict(ok=ok, marker_ok=m.get('ok'), missing=miss, log_len=len(log),
                reason='ok' if ok else ('build cờ gốc thành công' if m.get('ok') else f'log thiếu chữ ký {miss}'))


def s_pic(pic_dir, case):
    m = jload(f'{pic_dir}/{case}.build.json')
    if m is None: return dict(ok=False, reason='không có marker build PIC')
    ds = drivers(f'{pic_dir}/{case}')
    same = bool(m.get('bin')) and len(ds) == 1 and os.path.realpath(ds[0]) == os.path.realpath(m['bin'])
    ok = m.get('ok') is True and len(ds) == 1 and same
    return dict(ok=ok, marker_ok=m.get('ok'), n_drivers=len(ds), bin_matches=same, sha256=m.get('sha256'),
                reason='ok' if ok else f'marker ok={m.get("ok")}, {len(ds)} driver, bin khớp={same}')


def s_cache(pic_dir, case, line=None):
    line = line or S_CACHE_LINE
    p = f'{pic_dir}/{case}/build-ninja/CMakeCache.txt'
    try: lines = open(p, errors='replace').read().splitlines()
    except OSError: return dict(ok=False, reason='không có CMakeCache.txt')
    found = [l for l in lines if l.startswith('CMAKE_POSITION_INDEPENDENT_CODE:')]
    ok = line in lines
    return dict(ok=ok, want=line, found=found, reason='ok' if ok else f'không có dòng {line}; có {found or "không"}')


# ---------------- S-ninja ----------------
def norm_lines(path, wd):
    txt = open(path, errors='replace').read()
    for w in sorted({os.path.realpath(wd), os.path.abspath(wd)}, key=len, reverse=True): txt = txt.replace(w, '<WD>')
    return txt.splitlines()


def edges(lines):
    """[(dòng đầu, dòng cuối, outputs, rule, {biến: giá trị})] của mọi lệnh `build` trong build.ninja."""
    out, cur = [], None
    for i, l in enumerate(lines):
        m = EDGE.match(l)
        if m:
            cur = [i, i, m.group(1).split(), m.group(2), {}]; out.append(cur)
        elif cur is not None and l.startswith('  ') and ' = ' in l:
            k, _, v = l.strip().partition(' = '); cur[4][k] = v; cur[1] = i
        else:
            cur = None
    return [tuple(e) for e in out]


def _added(fo, fp, tok):
    """True khi fp bằng fo thêm đúng một token tok (fo chưa có tok)."""
    if tok in fo or fp.count(tok) != 1: return False
    q = list(fp); q.remove(tok)
    return q == fo


def s_rules(orig_wd, pic_wd):
    """CMakeFiles/rules.ninja của hai bản giống nhau sau chuẩn hoá đường dẫn (review N5)."""
    f = 'build-ninja/CMakeFiles/rules.ninja'
    try: ro, rp = norm_lines(f'{orig_wd}/{f}', orig_wd), norm_lines(f'{pic_wd}/{f}', pic_wd)
    except OSError as e: return dict(ok=False, reason=f'không đọc được rules.ninja: {e}')
    diff = [f'dòng {i + 1}: {a[:100]!r} -> {b[:100]!r}' for i, (a, b) in enumerate(zip(ro, rp)) if a != b]
    ok = len(ro) == len(rp) and not diff
    return dict(ok=ok, n_lines=len(ro), diff=diff[:10], reason='ok' if ok else f'rules.ninja khác ({len(ro)} và {len(rp)} dòng; {diff[:2]})')


def s_ninja(orig_wd, pic_wd):
    po, pp = f'{orig_wd}/build-ninja/build.ninja', f'{pic_wd}/build-ninja/build.ninja'
    try: lo, lp = norm_lines(po, orig_wd), norm_lines(pp, pic_wd)
    except OSError as e: return dict(ok=False, reason=f'không đọc được build.ninja: {e}')
    rules = s_rules(orig_wd, pic_wd)
    if len(lo) != len(lp): return dict(ok=False, reason=f'số dòng khác nhau ({len(lo)} và {len(lp)})')
    eo, ep = edges(lo), edges(lp)
    if [(a, b, c, d) for a, b, c, d, _ in eo] != [(a, b, c, d) for a, b, c, d, _ in ep]:
        return dict(ok=False, reason='danh sách lệnh build khác nhau')
    allowed, bad, objs = set(), [], dict(sphincs_obj=[], driver=[], other_same=[], other_changed=[])
    link = dict(equal=True, n_link_edges=0)
    for (a, b, outs, rule, vo), (_, _, _, _, vp) in zip(eo, ep):
        if rule.startswith('C_COMPILER__'):
            obj = outs[0]; fo, fp = vo.get('FLAGS', '').split(), vp.get('FLAGS', '').split()
            if SPHINCS_OBJ in f'/{obj}':
                ok = _added(fo, fp, '-fPIC'); objs['sphincs_obj'].append(obj)
            elif f'/{obj}'.endswith(DRIVER_OBJ):
                ok = _added(fo, fp, '-fPIE'); objs['driver'].append(obj)
            else:
                ok = fo == fp; objs['other_same' if ok else 'other_changed'].append(obj)
            if not ok: bad.append(f'{obj}: cờ {fo} -> {fp}')
            for k in set(vo) | set(vp):
                if k != 'FLAGS' and vo.get(k) != vp.get(k): bad.append(f'{obj}: {k} khác')
            for i in range(a, b + 1):
                if lo[i].startswith('  FLAGS = '): allowed.add(i)
        elif '_LINKER__' in rule:
            link['n_link_edges'] += 1
            for k in ('LINK_FLAGS', 'LINK_LIBRARIES'):
                if vo.get(k) != vp.get(k): link['equal'] = False; bad.append(f'{outs[0]}: {k} khác')
    other = [f'dòng {i + 1}: {lo[i][:100]!r} -> {lp[i][:100]!r}' for i in range(len(lo)) if lo[i] != lp[i] and i not in allowed]
    if len(objs['driver']) != 1: bad.append(f'{len(objs["driver"])} object driver PQCgenKAT_sign.c.o')
    if not objs['sphincs_obj']: bad.append('không có object sphincs_obj')
    if not rules['ok']: bad.append(rules['reason'])
    ok = not bad and not other
    return dict(ok=ok, rules_ninja=rules, n_sphincs_obj=len(objs['sphincs_obj']), n_driver_obj=len(objs['driver']), n_other_same=len(objs['other_same']),
                n_other_changed=len(objs['other_changed']), link=link, bad=bad[:20], other_diff_lines=other[:20],
                n_lines=len(lo), reason='ok' if ok else '; '.join((bad + other)[:3]))


# ---------------- S-clang ----------------
def clang_reloc(extra, clang='clang'):
    p = subprocess.run([clang, '-###', *CLANG_BASE, *extra, '-c', '-x', 'c', os.devnull, '-o', os.devnull],
                       capture_output=True, text=True)
    t = p.stderr
    m, lv = re.search(r'"-mrelocation-model" "(\w+)"', t), re.search(r'"-pic-level" "(\d+)"', t)
    return dict(args=CLANG_BASE + extra, rc=p.returncode, relocation_model=m and m.group(1), pic_level=lv and lv.group(1),
                pic_is_pie='"-pic-is-pie"' in t, raw=t)


def s_clang(clang='clang'):
    runs = [clang_reloc([], clang), clang_reloc(['-fPIE'], clang)]
    got = [{k: r[k] for k in CLANG_WANT} for r in runs]
    ok = all(r['rc'] == 0 for r in runs) and all(g == CLANG_WANT for g in got)
    ver = subprocess.run([clang, '--version'], capture_output=True, text=True).stdout.splitlines()[:1]
    return dict(ok=ok, want=CLANG_WANT, without_fPIE=got[0], with_fPIE=got[1], clang=ver[0] if ver else None,
                clang_path=shutil.which(clang), runs=runs, reason='ok' if ok else f'clang cho {got}, cần {CLANG_WANT}')


def clang_text(c):
    """Định dạng như logs/clang-pie-default.txt, kèm toàn bộ output của -###."""
    out = []
    for r in c['runs']:
        toks = re.findall(r'"-mrelocation-model" "\w+" "-pic-level" "\d+"(?: "-pic-is-pie")?', r['raw'])
        out += [f'== {os.path.basename(c["clang_path"] or "clang")} -### {" ".join(r["args"])}', toks[0] if toks else '(không thấy)']
    out.append(f'# {c["clang"]}; kết luận S-clang: {"đạt" if c["ok"] else "KHÔNG ĐẠT"}')
    for r in c['runs']: out += [f'#### output đầy đủ: clang -### {" ".join(r["args"])}', r['raw'].rstrip()]
    return '\n'.join(out) + '\n'


# ---------------- cổng ----------------
def gate(pic_dir, orig_dir, cases, smoke=None, clang='clang', cache_line=None):
    smoke = smoke or cases[0]
    per = {}
    for c in cases:
        per[c] = dict(s_pic=s_pic(pic_dir, c), s_cache=s_cache(pic_dir, c, cache_line),
                      s_ninja=s_ninja(f'{orig_dir}/{c}', f'{pic_dir}/{c}'))
    so = s_orig(orig_dir, smoke)
    sc = s_clang(clang) if clang else dict(ok=False, reason='không chạy S-clang')
    cond = dict(s_orig=so['ok'], s_clang=sc['ok'],
                **{k: all(per[c][k]['ok'] for c in cases) for k in ('s_pic', 's_cache', 's_ninja')})
    failed = {k: [c for c in cases if not per[c][k]['ok']] for k in ('s_pic', 's_cache', 's_ninja')}
    return dict(ok=all(cond.values()) and bool(cases), conditions=cond, failed_cases={k: v for k, v in failed.items() if v},
                smoke_case=smoke, n_cases=len(cases), s_orig=so, s_clang={k: v for k, v in sc.items() if k != 'runs'},
                clang_runs=sc.get('runs'), per_case=per, s_cache_line=cache_line or S_CACHE_LINE)


def summary(g):
    L = [f'cổng smoke build (amendment mục 7 bước 3): {"ĐẠT" if g["ok"] else "KHÔNG ĐẠT"}; {g["n_cases"]} case, smoke {g["smoke_case"]}']
    for k, v in g['conditions'].items():
        L.append(f'  {k}: {"đạt" if v else "KHÔNG ĐẠT"}' + (f' ({len(g["failed_cases"][k])} case: {g["failed_cases"][k][:3]})'
                                                         if k in g['failed_cases'] else ''))
    L.append(f'  S-orig: {g["s_orig"]["reason"]}; S-clang: {g["s_clang"]["reason"]}')
    first = {k: g['per_case'][v[0]][k]['reason'] for k, v in g['failed_cases'].items()}
    for k, r in first.items(): L.append(f'  {k} lý do đầu tiên: {r}')
    n = [g['per_case'][c]['s_ninja'] for c in g['per_case']]
    if n: L.append(f'  S-ninja: sphincs_obj {sorted({x.get("n_sphincs_obj") for x in n})}, driver {sorted({x.get("n_driver_obj") for x in n})}, '
                   f'object khác giữ cờ {sorted({x.get("n_other_same") for x in n})}')
    return '\n'.join(L) + '\n'


def archive(dst, pic_dir, orig_dir, cases, g):
    """Mục 7 bước 3: CMakeCache.txt và build.ninja (đổi đuôi .txt để commit được) của bản PIC và bản cờ gốc, marker, output cổng, clang."""
    for side, d in (('pic', pic_dir), ('orig', orig_dir)):
        for c in cases:
            o = f'{dst}/{side}/{c}'; os.makedirs(o, exist_ok=True)
            for f, name in (('CMakeCache.txt', 'CMakeCache.txt'), ('build.ninja', 'build.ninja.txt'),
                            ('CMakeFiles/rules.ninja', 'rules.ninja.txt')):
                src = f'{d}/{c}/build-ninja/{f}'
                if os.path.exists(src): shutil.copyfile(src, f'{o}/{name}')
            if os.path.exists(f'{d}/{c}.build.json'): shutil.copyfile(f'{d}/{c}.build.json', f'{dst}/{side}/{c}.build.json')
    if g.get('clang_runs'): open(f'{dst}/clang-pie-runner.txt', 'w').write(clang_text(dict(g['s_clang'], runs=g['clang_runs'])))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--pic-dir', required=True); ap.add_argument('--orig-dir', required=True)
    g0 = ap.add_mutually_exclusive_group(required=True)
    g0.add_argument('--keys', help='keys.txt (case = phần cuối của key)'); g0.add_argument('--cases', help='case, phân cách bằng dấu phẩy')
    ap.add_argument('--smoke-case'); ap.add_argument('--out'); ap.add_argument('--archive'); ap.add_argument('--clang', default='clang')
    ap.add_argument('--cases-jsonl')
    a = ap.parse_args(argv)
    cases = ([l.strip().split('/')[-1] for l in open(a.keys) if l.strip()] if a.keys else [c for c in a.cases.split(',') if c])
    g = gate(a.pic_dir, a.orig_dir, cases, a.smoke_case, a.clang)
    if a.archive: os.makedirs(a.archive, exist_ok=True); archive(a.archive, a.pic_dir, a.orig_dir, cases, g)
    doc = {k: v for k, v in g.items() if k != 'clang_runs'}
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        json.dump(doc, open(a.out, 'w'), indent=1, ensure_ascii=False)
        open(os.path.splitext(a.out)[0] + '.txt', 'w').write(summary(g))
    if a.cases_jsonl:
        os.makedirs(os.path.dirname(os.path.abspath(a.cases_jsonl)), exist_ok=True)
        with open(a.cases_jsonl, 'w') as f:
            for c, v in g['per_case'].items(): f.write(json.dumps(dict(case=c, **{k: v[k]['ok'] for k in v}), sort_keys=True) + '\n')
    sys.stdout.write(summary(g))
    return 0 if g['ok'] else EXIT_NOT_PASSED


if __name__ == '__main__':
    sys.exit(main())
