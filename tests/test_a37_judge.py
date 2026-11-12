"""A3/A7 mục 6 việc 1 (Q1 (a), Le duyệt 25/10, docs/proposal/a3-a7-package-plan.md mục 2.3): tách judge_exe, judge_lib ra khỏi
rq1_exe_case, rq1_lib_case là refactor thuần, không đổi hành vi.

Golden: tests/golden/a37_judge.json sinh trên mã TRƯỚC khi tách (main 7ff87fd), bằng
    A37_WRITE_GOLDEN=1 python3 -m unittest tests.test_a37_judge
Mỗi kịch bản chạy rq1_exe_case hoặc rq1_lib_case với runner giả và so với golden: bản ghi case (bộ đếm theo đúng thứ tự khoá, pair_status;
bỏ giá trị thời gian), nội dung bốn file div, capsens, memlimit, exact theo từng dòng, và dãy lời gọi runner (thứ tự, binary hoặc root,
timeout, trần output, file dump, cờ sanitizer). Dãy lời gọi trùng nghĩa là cùng thứ tự chạy và cùng số lần gọi runner.
Không cần corpus hay trình biên dịch. Chạy: python3 -m unittest tests.test_a37_judge"""
import collections, json, os, re, tempfile, unittest
from unittest import mock

from harness import observe as OB
from harness import rq1

BIG = OB.OUTPUT_CAP * rq1.OUTPUT_CAP_SENS
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden', 'a37_judge.json')
UB_ERR = b'==7==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x1\nSUMMARY: AddressSanitizer: heap-buffer-overflow\n'


# ---------------- quan sát giả ----------------
def e(status='exit', out=b'x\n', rc=0, err=b'', sig=None, **kw):
    o = dict(status=status, rc=rc if status == 'exit' else None, sig=(sig or 11) if status == 'signal' else None,
             to=status == 'timeout', out=out, err=err, secs=0.0)
    o.update(kw); return o


def l(result='Pass', k1='reported', state=None, stdout='x', stderr='', **kw):
    if k1 != 'reported': return dict(k1=k1, rc=1)
    o = dict(k1='reported', result=result, rc=0, state_out={'v': 1} if state is None else state, stdout=stdout, stderr=stderr)
    o.update(kw); return o


R = ('a', 'b')
OL = lambda: e('output_limit', out=b'p\n' * 4)
LOL = lambda: l('OutputLimit')

# Kịch bản executable: hàm (phía, timeout, trần lớn?, số lần đã gọi phía đó ở trần đó) -> quan sát. Phía: 'c', 'cs' (C-san), 'a', 'b'.
EXE = {
    'match': lambda s, t, big, n: e(),
    'div_stable': lambda s, t, big, n: e(out=b'y\n') if s in R else e(),
    'div_unstable': lambda s, t, big, n: (e(out=b'y\n') if n == 0 else e(out=b'z\n')) if s == 'a' else (e(out=b'y\n') if s == 'b' else e()),
    'nt_rerun_equal': lambda s, t, big, n: e('timeout') if (s == 'a' and t == 10) else e(),
    'nt_confirmed': lambda s, t, big, n: e('timeout', out=b'') if s in R else e(),
    'both_nt': lambda s, t, big, n: e('timeout', out=b'zz\nq') if s == 'b' else (e('timeout', out=b'ab\nc') if s in ('c', 'a') else e()),
    'san_ub': lambda s, t, big, n: e(out=b'y\n') if s in R else (e(err=UB_ERR, rc=1) if s == 'cs' else e()),
    'san_inconclusive': lambda s, t, big, n: e(out=b'y\n') if s == 'a' else (e('timeout') if s == 'cs' else e()),
    'san_infra': lambda s, t, big, n: e(out=b'y\n') if s == 'a' else (e('signal') if s == 'cs' else e()),
    'c_signal': lambda s, t, big, n: e('signal') if s in ('c', 'b') else e(),
    'stderr_only': lambda s, t, big, n: e(err=b'boom\n') if s == 'a' else e(),
    'mem': lambda s, t, big, n: e('mem_limit', out=b'', rc=None, mem_marker=['out of memory'], err=b'out of memory\n')
                                if s in ('c', 'b') else e(),
    'cap_match_equal': lambda s, t, big, n: e() if big else OL(),
    'cap_match_new_div': lambda s, t, big, n: (e(out=b'y\n') if s == 'a' else e()) if big else OL(),
    'cap_match_infra': lambda s, t, big, n: (e('invalid_input', out=b'') if s == 'a' else e()) if big else OL(),
    'cap_match_nt_rerun': lambda s, t, big, n: (e('timeout') if (s == 'b' and t == 10) else e()) if big else OL(),
    'cap_div': lambda s, t, big, n: e() if big else (OL() if s in ('c', 'b') else e(out=b'z\n')),
    'cap_div_infra': lambda s, t, big, n: (e('invalid_input', out=b'') if s == 'a' else e()) if big else (OL() if s == 'c' else e(out=b'z\n')),
    'san_first_in_capsens': lambda s, t, big, n: (e(out=b'y\n') if s == 'a' else e()) if big
                                                 else (OL() if s in ('c', 'a') else e(out=b'q\n', err=UB_ERR if s == 'cs' else b'')),
}


class FakeExe:
    def __init__(self, toks, sides):
        self.toks, self.sides, self.calls, self.n = toks, sides, [], collections.Counter()

    def __call__(self, binary, argv, stdin, timeout, env=None, cwd=None, cap=None, mem_limit=None, san=False):
        side = self.sides[binary]; big = cap == BIG
        self.calls.append(dict(bin=binary, argv=list(argv), stdin=stdin, timeout=timeout, env=env, cwd=cwd,
                               cap='BIG' if big else cap, mem_limit=mem_limit, san=san))
        k = (side, stdin, big); n = self.n[k]; self.n[k] += 1
        return EXE[stdin](side, timeout, big, n)


# Kịch bản library: hàm (phía, timeout, trần lớn?, số lần đã gọi) -> quan sát của runner. Phía: 'c', 'cs', 'a', 'b'.
LIB = {
    'match': lambda s, t, big, n: l(),
    'vcf_same': lambda s, t, big, n: l('VectorComparisonFailed') if s == 'a' else l(),
    'div_stable': lambda s, t, big, n: l(stdout='y') if s in R else l(),
    'div_unstable': lambda s, t, big, n: (l(stdout='y') if n == 0 else l(stdout='z')) if s == 'a' else l(),
    'nt_rerun_equal': lambda s, t, big, n: l('Timeout') if (s == 'a' and t == 10) else l(),
    'nt_confirmed': lambda s, t, big, n: l('Timeout') if s in R else l(),
    'both_nt': lambda s, t, big, n: l('Timeout') if s in ('c', 'a') else l(),
    'rust_infra': lambda s, t, big, n: l(k1='infra') if s == 'a' else (l(stdout='y') if s == 'b' else l()),
    'rerun_infra': lambda s, t, big, n: (l('Timeout') if t == 10 else l(k1='infra')) if s == 'a' else l(),
    'stability_infra': lambda s, t, big, n: (l(stdout='y') if n == 0 else l(k1='infra')) if s == 'a' else l(),
    'c_infra': lambda s, t, big, n: l(k1='infra') if s == 'c' else l(),
    'c_invalid': lambda s, t, big, n: l(k1='invalid_input') if s == 'c' else l(),
    'san_ub': lambda s, t, big, n: l(stdout='y') if s in R else (l(stderr=UB_ERR.decode()) if s == 'cs' else l()),
    'san_inconclusive': lambda s, t, big, n: l(stdout='y') if s == 'a' else (l('Timeout') if s == 'cs' else l()),
    'c_crash': lambda s, t, big, n: l('SegmentationFault') if s in ('c', 'cs', 'b') else l(),
    'tol_not_exact': lambda s, t, big, n: l(state={'v': 1.00000001}) if s == 'a' else l(state={'v': 1.0}),
    'stderr_only': lambda s, t, big, n: l(stderr='e2') if s == 'a' else l(),
    'mem': lambda s, t, big, n: l('MemLimit', mem_context='oom ctx', mem_marker=['out of memory']) if s == 'c' else l(),
    'cap_match_equal': lambda s, t, big, n: l() if big else LOL(),
    'cap_match_new_div': lambda s, t, big, n: (l(stdout='y') if s == 'a' else l()) if big else LOL(),
    'cap_match_infra': lambda s, t, big, n: (l(k1='infra') if s == 'a' else l()) if big else LOL(),
    'cap_match_stab_infra': lambda s, t, big, n: ((l(stdout='y') if n == 0 else l(k1='infra')) if s == 'a' else l()) if big else LOL(),
    'cap_match_nt_rerun': lambda s, t, big, n: (l('Timeout') if (s == 'b' and t == 10) else l()) if big else LOL(),
    'cap_div': lambda s, t, big, n: (l(stdout='w') if s == 'a' else l()) if big else (LOL() if s == 'c' else l(stdout='y')),
    'san_first_in_capsens': lambda s, t, big, n: (l(stdout='y') if s == 'a' else l()) if big
                                                 else (LOL() if s in ('c', 'a') else l(stdout='q', stderr=UB_ERR.decode() if s == 'cs' else '')),
}


class FakeLib:
    """Thay cả rq1._rl (run_lib_retry) và observe.run_lib (lib_san gọi trực tiếp); ghi chung một dãy lời gọi."""
    def __init__(self, base):
        self.base, self.calls, self.n = base, [], collections.Counter()

    def __call__(self, rb, root, p, timeout, rust, dump, preload=None, extra_env=None, keep_files=False, cap=None, fn='_rl'):
        side = {'/root/c': 'c', '/root/c-san': 'cs'}.get(root) or root.rsplit('-', 1)[1]
        tok = os.path.basename(p)[:-5]; big = cap == BIG
        self.calls.append(dict(fn=fn, rb=rb, root=root, vec=os.path.basename(p), timeout=timeout, rust=rust,
                               dump=dump.replace(self.base, '<D>'), preload=preload, extra_env=extra_env, keep_files=keep_files,
                               cap='BIG' if big else cap))
        k = (side, tok, big); n = self.n[k]; self.n[k] += 1
        return LIB[tok](side, timeout, big, n)

    def run_lib(self, *a, **kw):
        return self(*a, fn='run_lib', **kw)


# ---------------- chạy một kịch bản ----------------
def _norm(x, d):
    if isinstance(x, str): return x.replace(d, '<D>')
    if isinstance(x, dict): return {k: _norm(v, d) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [_norm(v, d) for v in x]
    return x


def _files(div, d):
    out = {}
    for suf in ('', '.capsens', '.memlimit', '.exact'):
        p = div.replace('.jsonl', f'{suf}.jsonl')
        if not os.path.exists(p): out[suf or '.div'] = None; continue
        with open(p) as f: out[suf or '.div'] = [x.replace(d, '<D>') for x in f.read().splitlines()]
    return out


def _rec(r, d):
    r = _norm(r, d)
    r['secs'] = 'T'; r['phases'] = {k: 'T' for k in r.get('phases', {})}
    return r


def run_exe_scenario(toks, cs_ok=True):
    d = tempfile.mkdtemp(); div = f'{d}/out/div/P01_x__c__s0.jsonl'; os.makedirs(os.path.dirname(div))
    X = [(['-v', str(i)], tok, 'seed' if i % 2 == 0 else 'v2', 'S' if i % 2 == 0 else 'M', {'K': '1'} if i == 1 else None)
         for i, tok in enumerate(toks)]
    fake = FakeExe(toks, {'/c': 'c', '/cs': 'cs', '/r/a': 'a', '/r/b': 'b'})
    pairs = [dict(system=s, harvest_case='c') for s in ('a', 'b', 'z')]
    cbuild = lambda B, b, c, san=False: dict(ok=cs_ok, bin='/cs') if san else dict(ok=True, bin='/c', sha256='h', preset='p')
    rbuild = lambda B, s, b, c, h: dict(ok=s != 'z', bin=f'/r/{s}', sha256=s, rustc_bootstrap=False)
    with mock.patch.object(rq1.BD, 'build_c_exe', side_effect=cbuild), \
         mock.patch.object(rq1.BD, 'build_rust_exe', side_effect=rbuild), \
         mock.patch.object(rq1.insensitive, 'check', return_value=(False, {})), \
         mock.patch.object(rq1, 'gen_exe', side_effect=lambda *a, **k: (list(X), dict(n_seed=1))), \
         mock.patch.object(OB, 'run_exe', side_effect=fake):
        r = rq1.rq1_exe_case(d, 'P01_x', 'c', pairs, 0, dict(budget=1, afl_execs=0), 10, div, 't')
    return dict(rec=_rec(r, d), files=_files(div, d), calls=_norm(fake.calls, d))


def run_lib_scenario(toks, cs_ok=True):
    d = tempfile.mkdtemp(); div = f'{d}/out/div/B01_x__c__s0.jsonl'; os.makedirs(os.path.dirname(div))
    files = []
    for i, tok in enumerate(toks):
        p = f'{d}/vec/{i:02d}/{tok}.json'; os.makedirs(os.path.dirname(p))
        with open(p, 'w') as f: json.dump(dict(lib_state_in={'tok': tok, 'i': i}, lib_state_out={}), f)
        files.append((p, 'vector' if i % 2 == 0 else 'stategen'))
    fake = FakeLib(d)
    pairs = [dict(system=s, harvest_case='c') for s in ('a', 'b', 'z')]
    info = dict(runner_ok=True, c_ok=True, library='x', runner_bin='/rb', bundle='B01_x', case='c', c_sha256='h', preset='p')
    info['c-san_ok'] = cs_ok
    with mock.patch.object(rq1.BD, 'build_lib_case', return_value=info), \
         mock.patch.object(rq1.BD, 'build_rust_lib', side_effect=lambda B, s, b, c, h, lib: dict(ok=s != 'z', dir=f'/r/{s}', sha256=s)), \
         mock.patch.object(rq1.BD, 'lib_root', side_effect=lambda B, info, kind, rust_dir=None, tag=None: f'/root/{tag or kind}'), \
         mock.patch.object(rq1.BD, 'asan_preload', return_value='/asan.so'), \
         mock.patch.object(rq1, '_lib_inputs', return_value=(files, None, 1)), \
         mock.patch.object(rq1, '_rl', side_effect=fake), \
         mock.patch.object(OB, 'run_lib', side_effect=fake.run_lib):
        r = rq1.rq1_lib_case(d, 'B01_x', 'c', pairs, 0, dict(n_inputs=len(toks)), 10, div, 't')
    return dict(rec=_rec(r, d), files=_files(div, d), calls=fake.calls)


SCENARIOS = {}
for _t in EXE: SCENARIOS[f'exe/{_t}'] = (run_exe_scenario, [_t], True)
SCENARIOS['exe/all'] = (run_exe_scenario, list(EXE), True)
SCENARIOS['exe/c_san_build_failed'] = (run_exe_scenario, ['match', 'div_stable', 'cap_match_new_div'], False)
for _t in LIB: SCENARIOS[f'lib/{_t}'] = (run_lib_scenario, [_t], True)
SCENARIOS['lib/all'] = (run_lib_scenario, list(LIB), True)
SCENARIOS['lib/c_san_build_failed'] = (run_lib_scenario, ['match', 'div_stable', 'cap_match_new_div'], False)


def run_all():
    return {k: fn(toks, cs) for k, (fn, toks, cs) in SCENARIOS.items()}


def _dump(x):
    return json.dumps(x, ensure_ascii=False, default=repr)          # không sort_keys: so cả thứ tự khoá (bộ đếm)


# Sửa 2026-10-26 (harness-checks bc82907 trên máy đo): byte XFL và OS của header gzip (byte 8, 9) do bản Python ghi khác nhau (container
# Python 3.13 ghi OS 0xff, máy đo ghi 0x03), nên blob gz64 khác ở hai ký tự base64 của header dù nội dung nén giống hệt. So golden sau khi
# chuẩn hoá hai ký tự đó; phần dữ liệu nén vẫn so từng byte.
_GZ_HDR = re.compile(r'H4sIAAAAAAA[A-Za-z0-9+/]{2}')


def _cmp(s):
    return _GZ_HDR.sub('H4sIAAAAAAA??', s)


class Golden(unittest.TestCase):
    """rq1_*_case cho cùng bản ghi, cùng file, cùng dãy lời gọi runner như mã trước khi tách judge_*."""

    @classmethod
    def setUpClass(cls):
        cls.cur = run_all()
        if os.environ.get('A37_WRITE_GOLDEN'):
            os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
            with open(GOLDEN, 'w') as f:                          # một dòng mỗi kịch bản, để diff đọc được
                f.write('{\n' + ',\n'.join(f'{json.dumps(k)}: {_dump(v)}' for k, v in cls.cur.items()) + '\n}\n')
        with open(GOLDEN) as f: cls.gold = json.load(f)

    def test_same_scenarios(self):
        self.assertEqual(list(self.gold), list(self.cur))

    def test_each_scenario(self):
        for k in self.gold:
            for part in ('rec', 'files', 'calls'):
                with self.subTest(scenario=k, part=part):
                    self.assertEqual(_cmp(_dump(self.gold[k][part])), _cmp(_dump(json.loads(_dump(self.cur[k][part])))))

    def test_golden_covers_branches(self):
        """Golden phải chạm đủ nhánh cần chứng minh, để test không đạt dễ dãi trên kịch bản rỗng."""
        cn = lambda k, s='a': self.gold[k]['rec']['counts'][s]
        self.assertEqual(cn('exe/match')['match'], 1)
        self.assertEqual((cn('exe/div_stable')['div_stable'], cn('exe/div_unstable')['div_stable']), (1, 0))
        self.assertEqual(cn('exe/nt_rerun_equal')['match'], 1)
        self.assertEqual(cn('exe/nt_confirmed')['div'], 1); self.assertEqual(cn('exe/both_nt')['both_nt_match'], 1)
        self.assertEqual(cn('exe/san_ub', 'b').get('div_stable_noub', 0), 0)
        self.assertEqual(self.gold['exe/san_ub']['files']['.div'][0].count('"san": "ub"'), 1)
        self.assertEqual(cn('exe/cap_match_new_div')['cap_sens_new_div'], 1); self.assertEqual(cn('exe/cap_div')['cap_hit_div'], 1)
        self.assertEqual(cn('exe/cap_match_infra')['cap_sens_infra_match'], 1)
        self.assertEqual(cn('lib/rust_infra')['infra_inputs'], 1); self.assertEqual(cn('lib/rerun_infra')['observed'], 0)
        self.assertEqual(cn('lib/stability_infra')['infra_inputs'], 1); self.assertEqual(cn('lib/c_infra')['infra_inputs'], 1)
        self.assertEqual(self.gold['lib/c_invalid']['rec']['out_of_domain_by_source'], {'vector': 1})
        self.assertEqual(cn('lib/tol_not_exact')['match_tol_not_exact'], 1)
        self.assertEqual(cn('lib/cap_match_stab_infra')['cap_sens_infra_match'], 1)
        self.assertEqual(self.gold['lib/c_san_build_failed']['rec']['pair_status']['a'], 'san_infra')
        # C-san chạy một lần mỗi input, dùng chung cho mọi hệ (cache), kể cả khi lần đầu cần là ở nhánh độ nhạy trần
        for k in ('exe/div_stable', 'exe/san_first_in_capsens'):
            self.assertEqual(sum(c['san'] for c in self.gold[k]['calls']), 1, k)
        for k in ('lib/div_stable', 'lib/san_first_in_capsens'):
            self.assertEqual(sum(c['fn'] == 'run_lib' for c in self.gold[k]['calls']), 1, k)


# ---------------- judge_exe, judge_lib trực tiếp ----------------
def _no_write_open(real=open):
    """open giả: cấm ghi file (judge_* không được ghi file); đọc vẫn cho."""
    def f(path, mode='r', *a, **kw):
        if any(m in mode for m in 'wax+'): raise AssertionError(f'judge ghi file: {path} {mode}')
        return real(path, mode, *a, **kw)
    return f


CS = dict(ok=True, bin='/cs')


def judge_e(tok, s='a', cache=None, cs=CS):
    fake = FakeExe([tok], {'/c': 'c', '/cs': 'cs', '/r/a': 'a', '/r/b': 'b'})
    with mock.patch.object(OB, 'run_exe', side_effect=fake), mock.patch('builtins.open', side_effect=_no_write_open()):
        if cache is None: cache = dict(co=OB.run_exe('/c', ['-v', '0'], tok, 10, None), san=None)
        n0 = len(fake.calls)
        j = rq1.judge_exe('/c', cs, f'/r/{s}', ['-v', '0'], tok, None, 10, cache)
    return j, fake.calls[n0:], cache


def judge_l(tok, s='a', cache=None, csroot='/root/c-san'):
    d = tempfile.mkdtemp(); p = f'{d}/{tok}.json'
    with open(p, 'w') as f: json.dump(dict(lib_state_in={'tok': tok}), f)
    fake = FakeLib(d)
    with mock.patch.object(rq1, '_rl', side_effect=fake), mock.patch.object(OB, 'run_lib', side_effect=fake.run_lib), \
         mock.patch('builtins.open', side_effect=_no_write_open()):
        if cache is None: cache = dict(co=rq1._rl('/rb', '/root/c', p, 10, False, f'{d}/dumps/x.C.dump'), san=None)
        n0 = len(fake.calls)
        j = rq1.judge_lib('/rb', '/root/c', csroot, '/asan.so', f'/root/rust-{s}', s, p, f'{d}/dumps/x', 10, cache)
    return j, fake.calls[n0:], cache


class JudgeExe(unittest.TestCase):
    def test_match_runs_only_rust(self):
        j, calls, cache = judge_e('match')
        self.assertEqual((j['verdict'], j['eq'], j['stable'], j['san'], j['cap_sens'], j['t0_div']), ('match', True, None, None, None, None))
        self.assertEqual([c['bin'] for c in calls], ['/r/a']); self.assertIsNone(cache['san'])     # C lấy từ cache, không chạy C-san

    def test_stable_div_fills_and_reuses_san_cache(self):
        j, calls, cache = judge_e('div_stable')
        self.assertEqual((j['verdict'], j['stable'], j['retained'], j['c_flag'], j['channels']), ('div', True, True, False, ['stdout']))
        self.assertIs(j['san'], cache['san']); self.assertEqual(cache['san']['status'], 'no_report')
        self.assertEqual(sum(c['san'] for c in calls), 1); self.assertEqual(len(calls), 1 + 2 * rq1.STAB_REPS + 1)
        j2, calls2, _ = judge_e('div_stable', 'b', cache)                                        # hệ khác (hoặc mutant), cùng input
        self.assertEqual(sum(c['san'] for c in calls2), 0); self.assertIs(j2['san'], cache['san'])

    def test_prefilled_san_cache_is_used(self):
        co = e(); cache = dict(co=co, san=dict(status='ub', markers=['AddressSanitizer'], attempts=1))
        j, calls, _ = judge_e('div_stable', cache=cache)
        self.assertEqual((j['san']['status'], j['retained']), ('ub', False)); self.assertFalse(any(c['san'] for c in calls))

    def test_unstable_not_retained(self):
        j, _, _ = judge_e('div_unstable')
        self.assertEqual((j['verdict'], j['stable'], j['retained']), ('div', False, False))

    def test_one_sided_nt_rerun_and_confirmed(self):
        j, calls, _ = judge_e('nt_rerun_equal')
        self.assertEqual((j['verdict'], j['info']['timeout_rerun'], j['info']['timeout_confirmed']), ('match', True, False))
        self.assertEqual([c['timeout'] for c in calls], [10, 100, 100])
        j, calls, _ = judge_e('nt_confirmed')
        self.assertEqual((j['verdict'], j['info']['timeout_confirmed'], j['stable']), ('div', True, True))
        self.assertTrue(all(c['timeout'] == 100 for c in calls[3:3 + 2 * rq1.STAB_REPS]))           # kiểm ổn định ở timeout gấp 10

    def test_both_nt(self):
        j, _, _ = judge_e('both_nt')
        self.assertEqual((j['verdict'], j['info']['nt_prefix_bytes']), ('match', 3))
        j, _, _ = judge_e('both_nt', 'b')
        self.assertEqual(j['verdict'], 'div')

    def test_san_ub_and_c_flag(self):
        j, _, _ = judge_e('san_ub')
        self.assertEqual((j['san']['status'], j['retained']), ('ub', False))
        j, _, _ = judge_e('c_signal')
        self.assertEqual((j['verdict'], j['c_flag'], j['retained']), ('div', True, True))
        j, _, _ = judge_e('div_stable', cs=dict(ok=False))
        self.assertEqual((j['san']['status'], j['retained']), ('infra', False))

    def test_cap_match_new_div(self):
        j, calls, cache = judge_e('cap_match_new_div')
        self.assertEqual((j['verdict'], j['cap_hit'], j['cap_sens']['outcome'], j['stable8'], j['channels8']), ('match', True, 'div', True, ['stdout']))
        self.assertIs(j['san'], cache['san']); self.assertIsNotNone(j['t0_div'])
        j, _, _ = judge_e('cap_match_infra')
        self.assertEqual((j['cap_sens']['outcome'], j['san'], j['stable8']), ('infra', None, None))

    def test_cap_div(self):
        j, _, _ = judge_e('cap_div')
        self.assertEqual((j['verdict'], j['cap_hit']), ('div', True)); self.assertIs(j['cap_sens'], j['info']['cap_sens'])


class JudgeLib(unittest.TestCase):
    def test_match(self):
        j, calls, cache = judge_l('match')
        self.assertEqual((j['verdict'], j['infra_at'], j['eq'], j['san']), ('match', None, True, None))
        self.assertEqual([(c['root'], c['dump'].split('/')[-1]) for c in calls], [('/root/rust-a', 'x.a.dump')])

    def test_infra_cases(self):
        j, calls, _ = judge_l('rust_infra')
        self.assertEqual((j['verdict'], j['infra_at'], j['eq'], len(calls)), ('infra', 'rust', None, 1))
        j, calls, _ = judge_l('rerun_infra')
        self.assertEqual((j['verdict'], j['infra_at'], j['eq'], len(calls)), ('infra', 'rerun', None, 3))
        j, calls, cache = judge_l('stability_infra')
        self.assertEqual((j['verdict'], j['infra_at'], j['eq'], j['stable'], cache['san']), ('infra', 'stability', False, None, None))

    def test_div_fields_and_dump_names(self):
        j, calls, cache = judge_l('div_stable', 'b')
        self.assertEqual((j['verdict'], j['stable'], j['retained'], j['channels'], j['info']['channels']), ('div', True, True, ['stdout'], ['stdout']))
        self.assertEqual([c['dump'].split('/')[-1] for c in calls],
                         ['x.b.dump', 'x.C.v0.dump', 'x.C.v1.dump', 'x.b.v0.dump', 'x.b.v1.dump', 'x.Csan.dump'])
        self.assertEqual(cache['san']['status'], 'no_report')

    def test_c_crash_flag_and_ub(self):
        j, _, _ = judge_l('c_crash')
        self.assertEqual((j['verdict'], j['c_flag']), ('div', True))
        j, _, _ = judge_l('san_ub')
        self.assertEqual((j['san']['status'], j['retained']), ('ub', False))
        j, _, _ = judge_l('div_stable', csroot=None)
        self.assertEqual((j['san']['status'], j['san']['cause']), ('infra', 'c_san_build_failed'))

    def test_cap(self):
        j, _, cache = judge_l('cap_match_new_div')
        self.assertEqual((j['verdict'], j['cap_sens']['outcome'], j['stable8'], j['channels8']), ('match', 'div', True, ['stdout']))
        self.assertIs(j['san'], cache['san'])
        j, _, _ = judge_l('cap_match_stab_infra')
        self.assertEqual((j['cap_sens']['outcome'], j['cap_sens']['infra_at'], j['san']), ('infra', 'stability', None))
        j, _, _ = judge_l('cap_div')
        self.assertEqual((j['verdict'], j['cap_sens']['outcome']), ('div', 'div')); self.assertIs(j['cap_sens'], j['info']['cap_sens'])


class JudgeMatchesRecords(unittest.TestCase):
    """Mục 2.6 của kế hoạch: với mỗi kịch bản một input, trường quyết định của judge_* bằng bản ghi mà rq1_*_case ghi (golden)."""

    def check(self, kind, toks, judge):
        with open(GOLDEN) as f: gold = json.load(f)
        for tok in toks:
            g = gold[f'{kind}/{tok}']
            divs = {r['system']: r for r in map(json.loads, g['files']['.div'] or [])}
            caps = {r['system']: r for r in map(json.loads, g['files']['.capsens'] or [])}
            for s in ('a', 'b'):
                with self.subTest(kind=kind, tok=tok, system=s):
                    j = judge(tok, s)[0]; cn = g['rec']['counts'][s]
                    if s in divs:
                        d = divs[s]; self.assertEqual(j['verdict'], 'div')
                        got = dict(stable=j['stable'], san=j['san']['status'], san_markers=j['san']['markers'], retained=j['retained'],
                                   c_flag=j['c_flag'], channels=j['channels'], cap_sens=j['cap_sens'],
                                   timeout_rerun=j['info']['timeout_rerun'], timeout_confirmed=j['info']['timeout_confirmed'])
                        self.assertEqual(json.loads(json.dumps(got)), {k: d.get(k) for k in got})
                    elif s in caps:
                        d = caps[s]; self.assertEqual(j['verdict'], 'match')
                        got = dict(cap_sens=j['cap_sens'], stable=j['stable8'], channels=j['channels8'], san=j['san']['status'])
                        self.assertEqual(json.loads(json.dumps(got)), {k: d.get(k) for k in got})
                    elif cn.get('infra_inputs'):
                        self.assertEqual(j['verdict'], 'infra')
                    else:
                        self.assertEqual(j['verdict'], 'match'); self.assertNotEqual((j['cap_sens'] or {}).get('outcome'), 'div')

    def test_exe(self):
        self.check('exe', list(EXE), judge_e)

    def test_lib(self):
        self.check('lib', [t for t in LIB if t not in ('c_infra', 'c_invalid')], judge_l)   # hai ca này C bị loại trước judge


if __name__ == '__main__':
    unittest.main()


class CountersReconcile(unittest.TestCase):
    """Sửa 2026-10-26 (Le chọn): với library, mỗi input trong observed được đếm đúng một lần ở c_status:* và r_status:*; input lỗi hạ
    tầng (kể cả ở lần kiểm ổn định) không vào các bộ đếm này."""
    def test_status_sums_equal_observed(self):
        gold = json.load(open(GOLDEN))
        n = 0
        for name, g in gold.items():
            if not name.startswith('lib/'): continue
            for s, c in (g['rec'].get('counts') or {}).items():
                for side in ('c', 'r'):
                    self.assertEqual(sum(v for k, v in c.items() if k.startswith(f'{side}_status:')), c.get('observed', 0),
                                     f'{name} {s} {side}')
                n += 1
        self.assertGreater(n, 20)
        self.assertEqual(gold['lib/stability_infra']['rec']['counts']['a'], dict(observed=0, infra_inputs=1))


class GzipHeaderNormalisation(unittest.TestCase):
    """Golden không phụ thuộc byte OS, XFL của header gzip (khác giữa bản Python); dữ liệu nén khác vẫn bị bắt."""
    def test_os_byte_only(self):
        import base64, gzip
        a = base64.b64encode(gzip.compress(b'xin chao', mtime=0)).decode()
        raw = bytearray(base64.b64decode(a)); raw[9] = 3 if raw[9] != 3 else 255
        b = base64.b64encode(bytes(raw)).decode()
        self.assertNotEqual(a, b); self.assertEqual(_cmp(a), _cmp(b))
        c = base64.b64encode(gzip.compress(b'xin chao!', mtime=0)).decode()
        self.assertNotEqual(_cmp(a), _cmp(c))
