"""harness/sweep.py (kế hoạch A3-A7 mục 2.2 đến 2.6, tiêu chí 3.1 đến 3.4): runner, build, pha R giả; không cần corpus.

Kiểm theo mục 2.6 và mục 3:
  - bản gốc khác C trên x thì mutant không được tính bắt tại x (không chạy mutant tại x); divergence không ổn định không tính; input
    sanitizer phía C báo UB không tính; input ngoài miền không chạy (3.1 điều kiện 1 đến 5);
  - xác nhận (điều kiện 6): mutant bắt ở lượt chính mà lần chạy lại khớp C thì `confirmed` False, vẫn tính ở A7 (1 đến 5), A3 chặn;
  - mutant vector gốc bắt để riêng, không chạy; cặp bản gốc không pass vector bị loại, ghi lý do; mẫu số đủ;
  - kiểm chéo pha M với pha R; luật chọn mức gồm Q2 (c); trần 72 giờ; estimate.py sửa cơ học; file nhãn A3 khoá; compiler control.
Chạy: python3 -m unittest tests.test_sweep"""
import collections, gzip, json, os, shutil, subprocess, tempfile, unittest
from unittest import mock

from harness import build as BD
from harness import controls as CT
from harness import mutants as MU
from harness import observe as OB
from harness import rq1
from harness import sweep as SW
from harness.record import write_inputs

UB_ERR = b'==7==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x1\nSUMMARY: AddressSanitizer: heap-buffer-overflow\n'
HEAD = SW.head_commit()


def e(status='exit', out=b'x\n', rc=0, err=b'', **kw):
    o = dict(status=status, rc=rc if status == 'exit' else None, sig=11 if status == 'signal' else None, to=status == 'timeout',
             out=out, err=err, secs=0.0)
    o.update(kw); return o


def l(result='Pass', k1='reported', stdout='x', stderr='', **kw):
    if k1 != 'reported': return dict(k1=k1, rc=1)
    o = dict(k1='reported', result=result, rc=0, state_out={'v': 1}, stdout=stdout, stderr=stderr); o.update(kw); return o


# ---------------- executable: hành vi theo token stdin ----------------
# side: 'c', 'cs' (C-san), 'o' (bản gốc), 'm0'.. (mutant), 'g' (gcc); n: số lần đã gọi (side, token)
EXE = {
    'same': lambda s, n: e(),
    'orig_div_mut_div': lambda s, n: e(out=b'y\n') if s in ('o', 'm0') else e(),      # bản gốc khác C: mutant không được xét
    'm1_unstable': lambda s, n: (e(out=b'y\n') if n == 0 else e(out=b'z\n')) if s == 'm1' else e(),
    'm2_ub': lambda s, n: e(out=b'y\n') if s == 'm2' else (e(err=UB_ERR, rc=1) if s == 'cs' else e()),
    'm0_div': lambda s, n: e(out=b'y\n') if s == 'm0' else e(),
    'm3_flaky': lambda s, n: (e(out=b'y\n') if n < 1 + rq1.STAB_REPS else e()) if s == 'm3' else e(),
    'g_div': lambda s, n: e(out=b'q\n') if s == 'g' else e(),
    'g_div_ub': lambda s, n: e(out=b'q\n') if s == 'g' else (e(err=UB_ERR, rc=1) if s == 'cs' else e()),
}


class FakeExe:
    def __init__(self, sides):
        self.sides, self.calls, self.n = sides, [], collections.Counter()

    def __call__(self, binary, argv, stdin, timeout, env=None, cwd=None, cap=None, mem_limit=None, san=False):
        side = self.sides[binary]; k = (side, stdin); n = self.n[k]; self.n[k] += 1
        self.calls.append((side, stdin, timeout))
        return EXE[stdin](side, n)


def _sha(p): return BD.sha256(p)


class Fixture:
    """Pha R giả (rq1-<kind>.jsonl, manifest, tập input nén, file div nén) và thư mục gen giả (mutants-<kind>.jsonl, artefact)."""

    def __init__(self, kind='exe', L='x1', commit=HEAD):
        self.d = tempfile.mkdtemp(); self.kind, self.L, self.commit = kind, L, commit
        self.rdir = f'{self.d}/out/{L}'; self.gen = f'{self.d}/gen'
        os.makedirs(f'{self.rdir}/div'); os.makedirs(self.gen); os.makedirs(f'{self.d}/bin')

    def phase_r(self, bundle, case, rows, div=None, systems=('a',), ood=None):
        div_path = f'{self.rdir}/div/{bundle}__{case}__s0.jsonl'
        f = write_inputs(rq1.inputs_path(div_path), rows)
        rec = dict(key=f'{bundle}/{case}/s0', kind=self.kind, bundle=bundle, case=case, seed=0, status='done', inputs_file=f,
                   counts={s: {} for s in systems}, phases=dict(build=1, execute=1))
        if ood is not None: rec['out_of_domain_by_source'] = ood
        with open(f'{self.rdir}/rq1-{self.kind}.jsonl', 'a') as fh: fh.write(json.dumps(rec) + '\n')
        with gzip.open(div_path + '.gz', 'wt') as g:
            for s, idx in (div or {}).items():
                for i in idx: g.write(json.dumps(dict(system=s, idx=i)) + '\n')
        json.dump(dict(repo_commit=self.commit, params=dict(kind=self.kind, theta=SW.LEVELS[self.L][self.kind], timeout=10, seeds=[0])),
                  open(f'{self.rdir}/manifest-rq1-{self.kind}.json', 'w'))
        return rec

    def art(self, name, content=None):
        p = f'{self.d}/bin/{name}'
        with open(p, 'w') as f: f.write(content or name)
        return p

    def pair(self, set_name, system, bundle, case, mutants, **kw):
        key = MU.pair_key(set_name, self.kind, dict(system=system, bundle=bundle, case=case))
        rec = dict(key=key, set=set_name, kind=self.kind, system=system, bundle=bundle, case=case, hcase=case, mutants=mutants,
                   orig_sha256='osha', base_vector_fails=[])
        rec.update(kw)
        with open(f'{self.gen}/mutants-{self.kind}.jsonl', 'a') as fh: fh.write(json.dumps(rec) + '\n')
        return rec


def exe_mut(fx, mid, built=True, killed=False, vf=(), sha=None, system='a'):
    p = fx.art(f'm{mid}-{system}')
    return dict(id=mid, file='src/main.rs', line=10 + mid, col=4, end=6, op='<', before='a < b', after='a <= b', built=built,
                artifact=p if built else None, sha256=sha or (_sha(p) if built else None), killed_by_vectors=killed,
                new_vector_fails=(['test1.json'] if killed else list(vf)) if built else None)


EXE_ROWS = ['orig_div_mut_div', 'same', 'm1_unstable', 'm2_ub', 'm0_div', 'm3_flaky']


def exe_rows(toks, nul_at=None):
    rows = []
    for i, t in enumerate(toks):
        argv = ['-v', 'a\x00b'] if i == nul_at else ['-v', str(i)]
        rows.append(dict(i=i, layer='S' if i == 0 else 'M', source='seed' if i == 0 else 'v2', argv=argv, stdin=t, env=None))
    return rows


def exe_setup(fx, set_name='a7-seed1', div_a=(0,), rows=None):
    rows = rows or exe_rows(EXE_ROWS)
    fx.phase_r('B02_x', 'cx', rows, div={'a': list(div_a)}, systems=('a', 'b'))
    ms = [exe_mut(fx, k) for k in range(4)]
    ms += [exe_mut(fx, 4, killed=True), exe_mut(fx, 5, built=False), exe_mut(fx, 6, sha='0' * 64)]
    fx.pair(set_name, 'a', 'B02_x', 'cx', ms)
    fx.pair(set_name, 'b', 'B02_x', 'cx', [exe_mut(fx, 0, system='b')], excluded='bản gốc không pass hết vector gốc',
            base_vector_fails=['test2.json'])
    fx.pair(set_name, 'z', 'B02_x', 'cx', [exe_mut(fx, 0, system='z')], base_vector_fails=None)
    sides = {'/c': 'c', '/cs': 'cs', '/o-a': 'o'}
    sides.update({m['artifact']: f"m{m['id']}" for m in ms if m.get('artifact')})
    pairs = [dict(system=s, bundle='B02_x', case='cx', hcase='cx') for s in ('a', 'b', 'z', 'w')]
    return FakeExe(sides), pairs


def exe_patches(fake, pairs):
    cb = lambda B, b, c, san=False: dict(ok=True, bin='/cs') if san else dict(ok=True, bin='/c')
    return [mock.patch.object(BD, 'build_c_exe', side_effect=cb),
            mock.patch.object(BD, 'build_rust_exe', side_effect=lambda B, s, b, c, h: dict(ok=True, bin=f'/o-{s}', sha256='osha')),
            mock.patch.object(OB, 'run_exe', side_effect=fake), mock.patch.object(SW.MU, 'set_pairs', return_value=pairs)]


class _Patched:
    def __init__(self, ps): self.ps = ps
    def __enter__(self):
        for p in self.ps: p.start()
    def __exit__(self, *a):
        for p in reversed(self.ps): p.stop()


def run_m(fx, fake, pairs, set_name='a7-seed1', job='a7', **kw):
    out = f'{fx.d}/out/{fx.L}/sweep-{fx.kind}'
    with _Patched(exe_patches(fake, pairs)), mock.patch.dict(os.environ, HARNESS_BUILD=f'{fx.d}/build'):
        s = SW.phase_m(job, fx.kind, set_name, fx.L, fx.rdir, fx.gen, out, 1, 10, **kw)
    recs = SW.load_store(f'{out}/mutants-{fx.kind}.jsonl')
    return s, recs, out


class ExeCatch(unittest.TestCase):
    """3.1 điều kiện 1 đến 6 trên executable."""

    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture('exe'); cls.fake, pairs = exe_setup(cls.fx)
        with mock.patch.object(rq1, 'judge_exe', wraps=rq1.judge_exe) as J:
            cls.s, cls.recs, cls.out = run_m(cls.fx, cls.fake, pairs)
            cls.n_judge = J.call_count
        cls.a = cls.recs['x1/a7-seed1/exe/B02_x/cx/a']
        cls.m = {m['id']: m for m in cls.a['mutants']}

    def test_uses_rq1_judge(self):
        self.assertGreater(self.n_judge, 0)

    def test_orig_div_blocks_mutant(self):
        self.assertFalse(any(s == 'm0' and t == 'orig_div_mut_div' for s, t, _ in self.fake.calls))
        self.assertEqual(self.m[0]['catch']['idx'], 4)                     # bắt ở input sau, nơi bản gốc khớp C
        self.assertEqual(self.a['counts']['orig_div'], 1)

    def test_unstable_and_ub_not_counted(self):
        self.assertFalse(self.m[1]['caught']); self.assertEqual(self.m[1]['outcomes'].get('div_unstable'), 1)
        self.assertFalse(self.m[2]['caught']); self.assertEqual(self.m[2]['outcomes'].get('div_san_ub'), 1)

    def test_catch_fields_and_confirm(self):
        c = self.m[0]
        self.assertTrue(c['caught']); self.assertTrue(c['confirm']['confirmed']); self.assertEqual(len(c['confirm']['runs']), SW.CONFIRM_REPS)
        self.assertEqual((c['catch']['san'], c['catch']['channels'], c['catch']['input']['stdin']), ('no_report', ['stdout'], 'm0_div'))
        f = self.m[3]
        self.assertTrue(f['caught']); self.assertFalse(f['confirm']['confirmed'])
        self.assertEqual([r['mutant'] for r in f['confirm']['runs']], ['match', 'match'])
        self.assertEqual(self.s['unconfirmed'], [f['key']]); self.assertEqual((self.s['n_caught'], self.s['n_confirmed']), (2, 1))

    def test_stop_at_first_catch(self):
        self.assertEqual(sum(1 for s, t, _ in self.fake.calls if s == 'm0' and t == 'm3_flaky'), 0)

    def test_set_aside_and_denominators(self):
        st = {k: m['status'] for k, m in self.m.items()}
        self.assertEqual((st[4], st[5], st[6]), ('killed_by_vectors', 'not_built', 'artifact_sha_mismatch'))
        self.assertFalse(any(s in ('m4', 'm5', 'm6') for s, _, _ in self.fake.calls))
        ex = {r['key'].rsplit('/', 1)[1]: r['reason'] for r in self.s['excluded_pairs']}
        self.assertTrue(ex['b'].startswith('orig_fails_vectors: test2.json'))
        self.assertEqual((ex['z'], ex['w']), ('orig_vector_result_unavailable', 'mutant_pair_missing'))
        c = self.s['counts']
        self.assertEqual((c['pairs'], c['mutants_tried'], c['mutants_built'], c['killed_by_vectors'], c['status:pair_excluded']), (4, 9, 8, 1, 2))
        self.assertEqual(self.s['missing_pairs'], [])

    def test_crosscheck(self):
        self.assertEqual(self.a['crosscheck']['equal'], True)

    def test_resume_skips_done(self):
        n0 = len(self.fake.calls)
        _, pairs = exe_setup(Fixture('exe'))       # chỉ để lấy danh sách cặp
        run_m(self.fx, self.fake, pairs)
        self.assertEqual(len(self.fake.calls), n0)


class ExeMisc(unittest.TestCase):
    def test_crosscheck_mismatch_reported(self):
        fx = Fixture('exe'); fake, pairs = exe_setup(fx, div_a=(0, 2))
        s, recs, _ = run_m(fx, fake, pairs)
        x = recs['x1/a7-seed1/exe/B02_x/cx/a']['crosscheck']
        self.assertEqual((x['equal'], x['only_r'], x['only_m']), (False, [2], []))
        self.assertEqual(s['crosscheck_mismatch'], ['x1/a7-seed1/exe/B02_x/cx/a'])

    def test_out_of_domain_not_run(self):
        fx = Fixture('exe'); fake, pairs = exe_setup(fx, rows=exe_rows(['m0_div', 'same'], nul_at=0))
        s, recs, _ = run_m(fx, fake, pairs)
        a = recs['x1/a7-seed1/exe/B02_x/cx/a']
        self.assertEqual(a['counts']['out_of_domain'], 1); self.assertFalse(a['mutants'][0]['caught'])
        self.assertFalse(any(t == 'm0_div' for _, t, _ in fake.calls))
        self.assertEqual(a['crosscheck']['equal'], False)          # pha R đã lọc miền: input ngoài miền ở pha M là dấu hiệu trôi

    def test_phase_r_commit_and_theta(self):
        fx = Fixture('exe', commit='0' * 40); fake, pairs = exe_setup(fx)
        with self.assertRaises(SystemExit): run_m(fx, fake, pairs)
        s, _, _ = run_m(fx, fake, pairs, allow_other_commit=True)
        self.assertEqual(s['n_caught'], 2)
        fx2 = Fixture('exe', L='x3'); fake2, pairs2 = exe_setup(fx2)
        m = json.load(open(f'{fx2.rdir}/manifest-rq1-exe.json')); m['params']['theta'] = SW.LEVELS['x1']['exe']
        json.dump(m, open(f'{fx2.rdir}/manifest-rq1-exe.json', 'w'))
        with self.assertRaises(SystemExit): run_m(fx2, fake2, pairs2)

    def test_inputs_sha_checked(self):
        fx = Fixture('exe'); fake, pairs = exe_setup(fx)
        recs = [json.loads(x) for x in open(f'{fx.rdir}/rq1-exe.jsonl')]; recs[0]['inputs_file']['sha256'] = 'f' * 64
        open(f'{fx.rdir}/rq1-exe.jsonl', 'w').write(''.join(json.dumps(r) + '\n' for r in recs))
        s, recs2, _ = run_m(fx, fake, pairs)
        self.assertEqual(recs2['x1/a7-seed1/exe/B02_x/cx/a']['excluded_reason'], 'phase_r_inputs_sha256_mismatch')

    def test_orig_sha_mismatch_excluded(self):
        fx = Fixture('exe'); fake, pairs = exe_setup(fx)
        g = f'{fx.gen}/mutants-exe.jsonl'; rows = [json.loads(x) for x in open(g)]
        rows[0]['orig_sha256'] = 'other'                               # gen build bản gốc khác binary pha M đang dùng
        with open(g, 'w') as f: f.write(''.join(json.dumps(r) + '\n' for r in rows))
        _, recs, _ = run_m(fx, fake, pairs)
        self.assertEqual(recs['x1/a7-seed1/exe/B02_x/cx/a']['excluded_reason'], 'orig_sha256_mismatch')


# ---------------- library ----------------
LIB = {
    'same': lambda s, n: l(),
    'c_invalid': lambda s, n: l(k1='invalid_input') if s == 'c' else l(),
    'c_infra': lambda s, n: l(k1='infra') if s == 'c' else l(),
    'm0_infra': lambda s, n: l(k1='infra') if s == 'mut-m0' else l(),
    'm0_div': lambda s, n: l(stdout='y') if s == 'mut-m0' else l(),
    'm0_vcf': lambda s, n: l('VectorComparisonFailed') if s == 'mut-m0' else l(),   # RQ1: Pass và VCF cùng kết quả
}


class FakeLib:
    def __init__(self):
        self.calls, self.n = [], collections.Counter()

    def __call__(self, rb, root, p, timeout, rust, dump, preload=None, extra_env=None, keep_files=False, cap=None, **kw):
        side = os.path.basename(root); tok = json.load(open(p))['lib_state_in']['tok']
        k = (side, tok); n = self.n[k]; self.n[k] += 1
        self.calls.append((side, tok, rust, os.path.basename(dump)))
        return LIB[tok](side, n)


def lib_fixture(set_name='a7-seed1'):
    fx = Fixture('lib')
    toks = ['c_invalid', 'c_infra', 'm0_vcf', 'm0_infra', 'm0_div', 'same']
    rows = [dict(i=i, source='vector' if i < 2 else 'stategen', vector=dict(lib_state_in=dict(tok=t), lib_state_out={})) for i, t in enumerate(toks)]
    fx.phase_r('B01_x', 'cl_lib', rows, div={'a': []}, ood={'vector': 1})
    root = f'{fx.d}/roots/mut-m0'; os.makedirs(f'{root}/translated_rust/target/release')
    so = f'{root}/translated_rust/target/release/libx.so'; open(so, 'w').write('so')
    fx.pair(set_name, 'a', 'B01_x', 'cl_lib', [dict(id=0, file='src/lib.rs', line=3, col=1, end=2, op='+', before='a', after='b', built=True,
                                                    root=root, sha256=_sha(so), killed_by_vectors=False, new_vector_fails=[])])
    pairs = [dict(system='a', bundle='B01_x', case='cl_lib', hcase='cl_lib')]
    return fx, pairs


def lib_patches(fake, pairs, d):
    info = dict(runner_ok=True, c_ok=True, library='x', runner_bin='/rb', bundle='B01_x', case='cl_lib', c_dir=f'{d}/cdir')
    info['c-san_ok'] = True
    return [mock.patch.object(BD, 'build_lib_case', return_value=info), mock.patch.object(BD, 'setup_cando2'),
            mock.patch.object(BD, 'build_rust_lib', side_effect=lambda B, s, b, c, h, lib: dict(ok=True, dir=f'/r/{s}', sha256='osha')),
            mock.patch.object(BD, 'lib_root', side_effect=lambda B, info, kind, rust_dir=None, tag=None: f'/root/{tag or kind}'),
            mock.patch.object(BD, 'asan_preload', return_value='/asan.so'),
            mock.patch.object(rq1, '_rl', side_effect=fake), mock.patch.object(OB, 'run_lib', side_effect=fake),
            mock.patch.object(SW.MU, 'set_pairs', return_value=pairs)]


class LibCatch(unittest.TestCase):
    def test_lib_conditions(self):
        fx, pairs = lib_fixture(); fake = FakeLib()
        out = f'{fx.d}/out/x1/sweep-lib'
        with _Patched(lib_patches(fake, pairs, fx.d)), mock.patch.dict(os.environ, HARNESS_BUILD=f'{fx.d}/build'):
            s = SW.phase_m('a7', 'lib', 'a7-seed1', 'x1', fx.rdir, fx.gen, out, 1, 10)
        r = SW.load_store(f'{out}/mutants-lib.jsonl')['x1/a7-seed1/lib/B01_x/cl_lib/a']
        m = r['mutants'][0]
        self.assertEqual((r['counts']['out_of_domain'], r['counts']['c_infra']), (1, 1))
        self.assertEqual(m['outcomes'], dict(match=1, infra=1, catch=1))           # VCF cùng kết quả với Pass; infra không là bắt
        self.assertEqual((m['catch']['idx'], m['confirm']['confirmed']), (4, True))
        self.assertEqual(r['crosscheck']['equal'], True)
        # mutant chạy qua root riêng với --rust; bản gốc qua root RQ1 (tag rust-<hệ>); vector và dump dọn sau cặp
        self.assertTrue(any(sd == 'mut-m0' and rust for sd, _, rust, _ in fake.calls))
        self.assertTrue(any(sd == 'rust-a' and rust for sd, _, rust, _ in fake.calls))
        self.assertFalse(os.path.exists(f'{fx.d}/build/sweep-vec/a7-x1/B01_x/cl_lib/a'))
        self.assertEqual(s['n_caught'], 1)


# ---------------- 3.2 ----------------
class Rule(unittest.TestCase):
    def test_choose_level(self):
        cases = [((5, 5, 5), 'x1', 'chosen'), ((5, 6, 6), 'x3', 'chosen'), ((5, 6, 7), 'x10', 'chosen'), ((5, 7, 6), 'x3', 'chosen'),
                 ((5, 5, 7), None, 'q2c'), ((6, 5, 7), None, 'conflict'), ((6, 5, 5), 'x1', 'chosen'), ((6, 5, 6), None, 'conflict')]
        for (a, b, c), lvl, st in cases:
            with self.subTest(c=(a, b, c)):
                r = SW.choose_level(dict(x1=a, x3=b, x10=c)); self.assertEqual((r['level'], r['status']), (lvl, st))

    def test_cap_rule(self):
        h = {('exe', 'x1'): 5, ('exe', 'x3'): 20, ('exe', 'x10'): 60, ('lib', 'x1'): 1, ('lib', 'x3'): 3, ('lib', 'x10'): 15}
        self.assertEqual(SW.cap_rule(h, dict(exe='x10', lib='x10'), 72)['pick'], dict(exe='x3', lib='x10'))
        self.assertEqual(SW.cap_rule(h, dict(exe='x3', lib='x1'), 72)['pick'], dict(exe='x3', lib='x1'))
        h2 = dict(h); h2[('exe', 'x1')] = 80
        self.assertEqual(SW.cap_rule(h2, dict(exe='x1', lib='x3'), 72)['status'], 'no_solution')
        self.assertEqual(SW.cap_rule({}, dict(exe='x1', lib='x1'), 72)['status'], 'missing')

    def _level(self, out, L, kind, caught, unconf=(), pairs=('p',), scan=('m0', 'm1', 'm2')):
        d = f'{out}/{L}/sweep-{kind}'; os.makedirs(d, exist_ok=True)
        with open(f'{d}/manifest.json', 'w') as f: json.dump(dict(params=dict(pairs=[f'{L}/{p}' for p in pairs])), f)
        ms = [dict(key=f'k/{m}', status='scan', caught=m in caught, confirm=dict(confirmed=m not in unconf)) for m in scan]
        with open(f'{d}/mutants-{kind}.jsonl', 'w') as f: f.write(json.dumps(dict(key=f'{L}/p', status='done', mutants=ms)) + '\n')

    def test_kind_selection(self):
        out = tempfile.mkdtemp()
        self._level(out, 'x1', 'exe', {'m0'}); self._level(out, 'x3', 'exe', {'m1'}, unconf={'m1'}); self._level(out, 'x10', 'exe', {'m0', 'm1'})
        r = SW.kind_selection(out, 'exe')
        self.assertEqual((r['status'], r['level'], r['counts']), ('q2c', None, dict(x1=1, x3=1, x10=2)))
        self.assertEqual(r['low_caught_high_missed'], {'x1-x3': 1, 'x1-x10': 0, 'x3-x10': 0})
        self.assertEqual(r['unconfirmed']['x3'], ['k/m1'])
        self._level(out, 'x10', 'exe', {'m0'}, pairs=('p', 'q'))
        self.assertEqual(SW.kind_selection(out, 'exe')['status'], 'thiếu số đo')
        self._level(out, 'x10', 'exe', {'m0'}, scan=('m0', 'm1'))
        self.assertEqual(SW.kind_selection(out, 'exe')['status'], 'universe_differs')
        self._level(out, 'x10', 'exe', {'m0'})
        d = f'{out}/x10/sweep-exe'
        with open(f'{d}/mutants-exe.jsonl', 'a') as f: f.write(json.dumps(dict(key='x10/p', status='excluded', excluded_reason='phase_r_case_missing', mutants=[])) + '\n')
        r = SW.kind_selection(out, 'exe')
        self.assertEqual((r['status'], r['anomalies']['x10']), ('anomalies', ['x10/p: phase_r_case_missing']))

    def test_estimate_mechanical_fix(self):
        out = tempfile.mkdtemp()
        for L, sec in (('x1', 10), ('x3', 30), ('x10', 100)):
            os.makedirs(f'{out}/{L}')
            for kind in ('exe', 'lib'):
                rs = [dict(key=f'B/c{i}/s0', status='done', secs=sec, phases=dict(build=5, gen=1, gen_afl=1, execute=sec)) for i in range(3)]
                if kind == 'lib': rs.append(dict(key='B01_synthetic/001_helloworld_lib/s0', status='done', input_fields=False, phases={}, secs=0))
                open(f'{out}/{L}/rq1-{kind}.jsonl', 'w').write(''.join(json.dumps(r) + '\n' for r in rs))
                json.dump(dict(wall_secs=sec * 3, workers=6), open(f'{out}/{L}/wall-{kind}.json', 'w'))
        import importlib.util
        spec = importlib.util.spec_from_file_location('e11', SW.ESTIMATE); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        with self.assertRaises(KeyError), mock.patch('sys.stdout'): mod.main(out)        # bản gốc hỏng như kế hoạch mục 2.1 ghi
        est = SW.run_estimate(out)
        self.assertEqual(len(est['hours']), 6); self.assertEqual(est['dropped'], ['B01_synthetic/001_helloworld_lib/s0'])
        self.assertEqual(est['cap'], 72)
        self.assertLess(est['hours'][('exe', 'x1')], est['hours'][('exe', 'x10')])
        ref = SW.insensitive_reference(est['hours'])
        self.assertGreater(ref['n_insensitive'], 0); self.assertEqual(set(ref['exe_hours_alt']), set(SW.ORDER))


class A7Cmd(unittest.TestCase):
    def test_identity_mismatch_stops_before_phase_r(self):
        fx = Fixture('exe'); fake, pairs = exe_setup(fx)
        a = SW.main.__wrapped__ if hasattr(SW.main, '__wrapped__') else None
        with mock.patch.object(SW.MU, 'check_identity', return_value=[dict(status='mismatch')]), \
             mock.patch.object(rq1, 'main') as R, self.assertRaises(SystemExit):
            SW.main(['a7', '--kind', 'exe', '--out', f'{fx.d}/out', '--mutants', fx.gen, '--levels', 'x1'])
        R.assert_not_called()
        self.assertTrue(os.path.exists(f'{fx.d}/out/identity-check-exe.json'))

    def test_a7_flow(self):
        fx = Fixture('exe'); fake, pairs = exe_setup(fx)
        with _Patched(exe_patches(fake, pairs)), mock.patch.object(SW.MU, 'check_identity', return_value=[dict(status='identical')]), \
             mock.patch.dict(os.environ, HARNESS_BUILD=f'{fx.d}/build'), mock.patch.object(SW, 'phase_r') as R:
            res = SW.main(['a7', '--kind', 'exe', '--out', f'{fx.d}/out', '--mutants', fx.gen, '--levels', 'x1'])
        R.assert_called_once_with('exe', 'x1', f'{fx.d}/out/x1', 1, 10)
        self.assertEqual((res['x1']['n_caught'], res['x1']['n_confirmed']), (2, 1))
        m = json.load(open(f'{fx.d}/out/x1/sweep-exe/manifest.json'))
        self.assertEqual((m['params']['set'], m['params']['oracle'], m['params']['phase_r_commit']), ('a7-seed1', 'rq1.judge_exe / rq1.judge_lib', HEAD))
        self.assertIsNotNone(m['params']['criteria_commit'])
        self.assertTrue(os.path.exists(f'{fx.d}/out/a7-exe-start.json'))

    def test_rq1_argv(self):
        self.assertEqual(SW.rq1_argv('exe', 'x3', 'O', 6, 10)[-4:], ['--budget', '9000', '--afl-execs', '30000'])
        self.assertEqual(SW.rq1_argv('lib', 'x10', 'O', 6, 10)[-2:], ['--n-inputs', '2000'])


# ---------------- 3.3 ----------------
class A3(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture('exe'); self.fake, self.pairs = exe_setup(self.fx, set_name='a3-seed2')

    def labels(self, lab):
        p = f'{self.fx.d}/labels.jsonl'
        with open(p, 'w') as f:
            for mid, x in lab.items():
                f.write(json.dumps(dict(key=f'a3-seed2/exe/B02_x/cx/a/m{mid}', label=x, line=10 + mid)) + '\n')
            f.write(json.dumps(dict(key='a3-seed2/exe/B02_x/cx/a/m6', label='NE')) + '\n')     # build được, vector không bắt
            for s in ('b', 'z'): f.write(json.dumps(dict(key=f'a3-seed2/exe/B02_x/cx/{s}/m0', label='NE')) + '\n')
        return p

    def run_a3(self, p, sha=None, locked=True):
        with _Patched(exe_patches(self.fake, self.pairs)), mock.patch.object(SW, 'labels_locked', return_value=locked), \
             mock.patch.dict(os.environ, HARNESS_BUILD=f'{self.fx.d}/build'):
            return SW.main(['a3', '--kind', 'exe', '--level', 'x1', '--set', 'a3-seed2', '--labels', p, '--labels-sha256', sha or BD.sha256(p),
                            '--mutants', self.fx.gen, '--phase-r', self.fx.rdir, '--out', f'{self.fx.d}/a3'])

    def test_refusals(self):
        p = self.labels({0: 'NE', 1: 'NE', 2: 'UNKNOWN', 3: 'NE'})
        with self.assertRaises(SystemExit): self.run_a3(p, sha='0' * 64)
        with self.assertRaises(SystemExit): self.run_a3(p, locked=False)
        p2 = self.labels({0: 'NE', 1: 'NE', 2: 'UNKNOWN'})
        with self.assertRaises(SystemExit): self.run_a3(p2)                # m3 thiếu nhãn
        p3 = self.labels({0: 'NE', 1: 'NE', 2: 'UNKNOWN', 3: 'NE'})
        rows = [json.loads(x) for x in open(p3)]; rows[0]['line'] = 99
        open(p3, 'w').write(''.join(json.dumps(r) + '\n' for r in rows))
        with self.assertRaises(SystemExit): self.run_a3(p3)                # lệch danh tính
        self.assertFalse(self.fake.calls)                                  # harness chưa chạm bộ A3

    def test_tables(self):
        rep = self.run_a3(self.labels({0: 'NE', 1: 'NE', 2: 'UNKNOWN', 3: 'NE'}))
        self.assertTrue(rep['C']['status'].startswith('chưa đạt'))
        self.assertEqual((len(rep['C']['i_unconfirmed']), rep['C']['ii_caught_labelled_equivalent']), (1, []))
        D = rep['D']
        self.assertEqual((D['k'], D['n'], D['u'], D['rate']), (1, 2, 1, 0.5))
        self.assertEqual(D['interval_plan'], [round(1 / 3, 4), round(2 / 3, 4)]); self.assertEqual(D['interval_exp07'], [round(1 / 3, 4), 0.5])
        self.assertEqual(len(rep['excluded_pairs']), 3)

    def test_caught_equivalent_label(self):
        rep = self.run_a3(self.labels({0: 'EQ', 1: 'NE', 2: 'NE', 3: 'NE'}))
        self.assertEqual([x['label'] for x in rep['C']['ii_caught_labelled_equivalent']], ['EQ'])
        self.assertEqual(rep['D']['k'], 0)

    def test_label_alias(self):
        p = f'{self.fx.d}/l.jsonl'; open(p, 'w').write(json.dumps(dict(key='k', label='không xác định')) + '\n')
        self.assertEqual(SW.load_labels(p)['k']['label'], 'UNKNOWN')
        open(p, 'w').write(json.dumps(dict(key='k', label='MAYBE')) + '\n')
        with self.assertRaises(SystemExit): SW.load_labels(p)


# ---------------- 3.4 ----------------
class CC(unittest.TestCase):
    def test_build_checks(self):
        d = tempfile.mkdtemp(); a, b = f'{d}/a', f'{d}/b'
        open(a, 'w').write('gcc'); open(b, 'w').write('clang')
        with mock.patch.object(CT, 'comment_section', return_value='GCC: (Ubuntu 13) 13.2'):
            self.assertTrue(CT.build_checks(a, b)['ok'])
        with mock.patch.object(CT, 'comment_section', return_value='clang version 18'):
            self.assertFalse(CT.build_checks(a, b)['gcc_comment_clang_free'])
        open(b, 'w').write('gcc')
        with mock.patch.object(CT, 'comment_section', return_value=''):
            self.assertFalse(CT.build_checks(a, b)['bytes_differ'])
        self.assertFalse(CT.build_checks(None, b)['ok'])

    def test_gcc_lib_root(self):
        d = tempfile.mkdtemp(); so = f'{d}/g/libx.so'; os.makedirs(f'{d}/g'); open(so, 'w').write('g')
        info = dict(bundle='B01_x', case='c_lib', library='x', c_dir=f'{d}/clang')
        root = CT.gcc_lib_root(d, info, dict(so=so, dir=f'{d}/g'))
        self.assertEqual(os.path.basename(os.path.dirname(os.path.dirname(root))), 'cc-gcc')
        self.assertEqual(os.path.realpath(f'{root}/translated_rust/target/release/libx.so'), os.path.realpath(so))
        self.assertEqual(os.path.realpath(f'{root}/build-ninja'), os.path.realpath(f'{d}/clang'))
        cr = CT.gcc_lib_croot(d, info, dict(so=so, dir=f'{d}/g'))
        self.assertEqual(os.path.realpath(f'{cr}/build-ninja'), os.path.realpath(f'{d}/g'))

    def test_cc_exe_and_report(self):
        fx = Fixture('exe')
        fx.phase_r('B02_x', 'cx', exe_rows(['same', 'g_div', 'g_div_ub']), systems=('a',))
        fake = FakeExe({'/c': 'c', '/cs': 'cs', '/g': 'g'})
        ps = exe_patches(fake, [])[:3] + [mock.patch.object(SW, 'PILOT_EXE', {('B02_x', 'cx')}),
                                          mock.patch.object(CT, 'build_c_gcc_exe', return_value=dict(ok=True, bin='/g')),
                                          mock.patch.object(CT, 'build_checks', return_value=dict(ok=True))]
        with _Patched(ps), mock.patch.dict(os.environ, HARNESS_BUILD=f'{fx.d}/build'):
            res = SW.main(['cc', '--kind', 'exe', '--level', 'x1', '--phase-r', fx.rdir, '--out', f'{fx.d}/cc'])
        r = res['exe']
        self.assertEqual((r['status'], r['div_raw'], r['div_on_ub_inputs'], r['retained'], len(r['pending_g_code'])), ('chưa đạt', 2, 1, 1, 1))
        key = r['pending_g_code'][0]['key']; self.assertEqual(key, 'B02_x/cx/s0/gcc/1')
        cp = f'{fx.d}/codes.jsonl'
        open(cp, 'w').write(json.dumps(dict(key=key, code='G3', c_line='a.c:3', clause='C11 6.5p8', repro='r.c')) + '\n')
        self.assertEqual(SW.report_cc(f'{fx.d}/cc', 'exe', cp)['status'], 'đạt')
        open(cp, 'w').write(json.dumps(dict(key=key, code='G3', c_line='a.c:3')) + '\n')
        self.assertEqual(SW.report_cc(f'{fx.d}/cc', 'exe', cp)['status'], 'chưa đạt')

    def test_cc_lib_excludes_no_input(self):
        t = dict(kind='lib', level='x1', bundle='B01_synthetic', case='001_helloworld_lib')
        self.assertEqual(SW.cc_case(t)['excluded_reason'], 'no_input_fields')

    def test_cc_report_exclusions(self):
        d = tempfile.mkdtemp(); os.makedirs(f'{d}/cc-lib/div'); open(f'{d}/cc-lib/div/x.jsonl', 'w').close()
        done = dict(key='B/a_lib', status='done', counts={}, build_check=dict(ok=True), div_file='x.jsonl')
        rows = [done, dict(key='B/001_helloworld_lib', status='excluded', excluded_reason='no_input_fields')]
        open(f'{d}/cc-lib/cc-lib.jsonl', 'w').write(''.join(json.dumps(r) + '\n' for r in rows))
        self.assertEqual(SW.report_cc(d, 'lib')['status'], 'đạt')
        with open(f'{d}/cc-lib/cc-lib.jsonl', 'a') as f: f.write(json.dumps(dict(key='B/b_lib', status='excluded', excluded_reason='phase_r_case_missing')) + '\n')
        r = SW.report_cc(d, 'lib'); self.assertEqual((r['status'], len(r['excluded_not_allowed'])), ('chưa đạt', 1))

    @unittest.skipUnless(all(shutil.which(x) for x in ('cmake', 'ninja', 'gcc', 'clang', 'readelf')), 'cần cmake, ninja, gcc, clang')
    def test_real_gcc_exe_build(self):
        """Build thật một case nhỏ bằng clang (build.build_c_exe) và gcc (controls): khác byte, .comment gcc không có clang."""
        d = tempfile.mkdtemp(); tc = f'{d}/T/B9/c9/test_case'; os.makedirs(tc)
        open(f'{tc}/CMakeLists.txt', 'w').write('cmake_minimum_required(VERSION 3.10)\nproject(t C)\nadd_executable(driver main.c)\n')
        open(f'{tc}/main.c', 'w').write('#include <stdio.h>\nint main(void){printf("%d\\n", 7); return 0;}\n')
        with mock.patch.object(BD, 'T', f'{d}/T'), mock.patch.object(CT, 'T', f'{d}/T'):
            c = BD.build_c_exe(f'{d}/B', 'B9', 'c9'); g = CT.build_c_gcc_exe(f'{d}/B', 'B9', 'c9')
        self.assertTrue(c['ok'] and g['ok'], (c.get('log'), g.get('log')))
        chk = CT.build_checks(g['bin'], c['bin'])
        self.assertEqual((chk['bytes_differ'], chk['gcc_comment_clang_free']), (True, True))
        self.assertIn('clang', CT.comment_section(c['bin']).lower())


if __name__ == '__main__':
    unittest.main()


class LabelsCommit(unittest.TestCase):
    """Le chọn 26/10: nhãn A3 ở nhánh cấu hình; khoá khi nội dung file bằng đúng blob 'commit:đường dẫn'."""
    def test_blob_match(self):
        import subprocess as sp, tempfile as tf
        from harness import sweep as SW
        blob = sp.run(['git', '-C', SW.REPO, 'show', 'HEAD:CLAUDE.md'], capture_output=True).stdout
        f = tf.mktemp(); open(f, 'wb').write(blob)
        self.assertTrue(SW.labels_locked(f, 'HEAD:CLAUDE.md'))
        open(f, 'ab').write(b'x')
        self.assertFalse(SW.labels_locked(f, 'HEAD:CLAUDE.md'))
        self.assertFalse(SW.labels_locked(f, 'HEAD:khong-co-file'))
