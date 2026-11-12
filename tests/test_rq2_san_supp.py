"""harness.rq2_san_supp (exp 37, amendment 2026-11-05): phép gán SAN_FLAGS_EXE (cả trong worker thật), lệnh cmake của build C-san, tính
outcome trên 36 bản ghi S₀ với hàm sanitizer giả (so với kịch bản của exp 38), các đường từ chối và phân loại stop/fail, một job một đoạn
(scan trên remote git thật: STOP, hoàn tất, lần thử đã tính, lịch sử chép tiếp), chạy lại key harness_error một lần trong job đầy đủ, nhánh
B0 (mọi lần nộp ở results/ và results-failed/, script B0 thật), guard của bước Publish thật (chạy nguyên văn từ runner-jobs.yml), điều kiện
từ job smoke, hàm shell của ci/rq2-san-supp-lib.sh, và đường đi của ci/jobs/rq2-san-supp*.sh với stub (có ca dùng scan thật).
Không thực thi binary nào: build_c_exe và rq1._exe_san được thay bằng mock; corpus là thư mục tạm.
Chạy: python3 -m unittest tests.test_rq2_san_supp
Biến môi trường (tuỳ chọn): RQ2_EXE (bản ghi S₀, b757f4d:ci-out/rq2-main/exe/rq2-exe.jsonl), SUPP_KEYS (keys.txt; mặc định
  experiments/37-rq2-san-supp/data/keys.txt), SUPP_AMENDMENT, BOUND_PY (bound.py của exp 38), B0_SH (ci/jobs/rq2-san-log.sh), SUPP_WORKFLOW
  (.github/workflows/runner-jobs.yml; mặc định của repo), RQ2_SAN_SUPP_SRC
  (thư mục chứa rq2_san_supp.py khi module chưa nằm trong harness/ của repo). SUPP_REQUIRE_DATA=1: thiếu dữ liệu thì test THẤT BẠI thay vì
  bỏ qua (dùng khi đưa vào ci/jobs/harness-checks.sh)."""
import collections, copy, importlib.util, json, os, shutil, subprocess, sys, tempfile, textwrap, unittest
from concurrent.futures import Future, ProcessPoolExecutor
from unittest import mock

import harness
if os.environ.get('RQ2_SAN_SUPP_SRC') and os.environ['RQ2_SAN_SUPP_SRC'] not in harness.__path__:
    harness.__path__.append(os.environ['RQ2_SAN_SUPP_SRC'])
from harness import build as BD
from harness import config as CF
from harness import rq1 as R1
from harness import rq2 as R2
from harness import rq2_san_supp as M
from harness.config import REPO

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_SH = os.path.abspath(os.path.join(HERE, '..', 'ci', 'rq2-san-supp-lib.sh'))
JOB_SH = os.path.abspath(os.path.join(HERE, '..', 'ci', 'jobs', 'rq2-san-supp.sh'))
RQ2_EXE = os.environ.get('RQ2_EXE')
HAVE_S0 = bool(RQ2_EXE and os.path.exists(RQ2_EXE))
KEYS_FILE = os.environ.get('SUPP_KEYS') or f'{REPO}/{M.KEYS}'
AMENDMENT_FILE = os.environ.get('SUPP_AMENDMENT') or f'{REPO}/docs/amendment-2026-11-05-rq2-san-supp.md'
BOUND_PY = os.environ.get('BOUND_PY') or f'{REPO}/experiments/38-rq2-san-bound/scripts/bound.py'
REQUIRE = os.environ.get('SUPP_REQUIRE_DATA') == '1'
# Danh sách đã freeze, gõ lại từ harness/config.py dòng 20-21: config đổi thì test này hỏng trước khi lượt bổ sung chạy
FROZEN_LITERAL = ['-DCMAKE_C_FLAGS=-fsanitize=address,undefined -fno-sanitize-recover=undefined -g',
                  '-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined']
OK = dict(ok=True, reason='ok')


def needs(cond, msg):
    """Như skipUnless; với SUPP_REQUIRE_DATA=1 thì thất bại (cho class hoặc method)."""
    if cond: return lambda x: x
    if not REQUIRE: return unittest.skip(msg)

    def deco(x):
        if isinstance(x, type):
            def setUpClass(cls): raise AssertionError(f'SUPP_REQUIRE_DATA=1 mà thiếu dữ liệu: {msg}')
            x.setUpClass = classmethod(setUpClass); return x

        def f(self): self.fail(f'SUPP_REQUIRE_DATA=1 mà thiếu dữ liệu: {msg}')
        return f
    return deco


def git(repo, *a):
    p = subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', *a], capture_output=True, text=True)
    assert p.returncode == 0, (a, p.stderr)
    return p.stdout.strip()


class FakeEx:
    """Executor đồng bộ (mock không pickle được qua ProcessPoolExecutor); gọi initializer như executor thật, ghi lại initializer."""
    seen = []

    def __init__(self, workers=None, initializer=None, mp_context=None):
        FakeEx.seen.append(initializer)
        if initializer: initializer()
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def submit(self, fn, *a):
        f = Future()
        try: f.set_result(fn(*a))
        except BaseException as e: f.set_exception(e)
        return f


def fake_san(status, calls=None):
    """Thay rq1._exe_san: không chạy gì, ghi tham số, đẩy một lần thử giả vào sink như _exe_san."""
    def f(cs, argv, stdin, timeout, env, c_status=None, sink=None):
        if calls is not None: calls.append(dict(cs=cs, argv=argv, stdin=stdin, timeout=timeout, env=env, c_status=c_status, sink=sink))
        n = 3 if status == 'infra' else 1
        mk = ['runtime error:'] if status == 'ub' else []
        for k in range(1, n + 1):
            if sink is not None:
                sink.append(dict(attempt=k, san_status='ub' if status == 'ub' else 'clean', markers=mk, status=status,
                                 obs=dict(status='signal' if status == 'infra' else 'exit', rc=0, sig=None, secs=0.1, out=b'x',
                                          err=b'fake ' + status.encode())))
        return dict(status=status, markers=mk, attempts=n, san_run_status='exit', err_tail='fake')
    return f


def load_bound():
    spec = importlib.util.spec_from_file_location('bound36', BOUND_PY)
    B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
    return B


def gate_file(d, keys, ok=True):
    p = f'{d}/smoke-gate.json'
    json.dump(dict(ok=ok, conditions=dict(s_orig=True, s_pic=True, s_cache=ok, s_ninja=True, s_clang=True),
                   per_case={k.split('/')[-1]: {} for k in keys}), open(p, 'w'))
    return p


class Flags(unittest.TestCase):
    def tearDown(self):
        BD.SAN_FLAGS_EXE = CF.SAN_FLAGS_EXE

    def test_frozen_list_literal(self):
        self.assertEqual(CF.SAN_FLAGS_EXE, FROZEN_LITERAL)
        self.assertEqual(M.FROZEN_SAN_FLAGS_EXE, FROZEN_LITERAL)
        self.assertTrue(M.orig_flags_in_effect())

    def test_install_adds_exactly_pic(self):
        before = copy.deepcopy(CF.SAN_FLAGS_EXE)
        got = M.install_pic()
        self.assertEqual(got, before + ['-DCMAKE_POSITION_INDEPENDENT_CODE=ON'])
        self.assertIs(BD.SAN_FLAGS_EXE, got)
        self.assertEqual(CF.SAN_FLAGS_EXE, before)                     # danh sách đã freeze không đổi nội dung
        self.assertIsNot(BD.SAN_FLAGS_EXE, CF.SAN_FLAGS_EXE)
        self.assertEqual(len(set(got) - set(before)), 1)
        self.assertTrue(M.pic_installed()); self.assertFalse(M.orig_flags_in_effect())
        M.install_pic()                                                # gọi lại (initializer) không cộng dồn
        self.assertEqual(BD.SAN_FLAGS_EXE, before + [M.PIC_FLAG])

    def test_install_refuses_mutated_config(self):
        with mock.patch.object(CF, 'SAN_FLAGS_EXE', FROZEN_LITERAL + ['-DX=1']):
            with self.assertRaises(RuntimeError): M.install_pic()

    def _capture_build(self, pic, wrap=None):
        """Chạy build_c_exe thật với sh giả trên một case giả có CMakePresets.json; trả các lệnh sh và marker."""
        d = tempfile.mkdtemp(prefix='supp-b-'); self.addCleanup(shutil.rmtree, d, True)
        troot = f'{d}/T/P01_sphincs_plus/005_x'; os.makedirs(f'{troot}/test_case')
        json.dump(dict(configurePresets=[dict(name='test', binaryDir='${sourceDir}/build-ninja')]), open(f'{troot}/CMakePresets.json', 'w'))
        open(f'{troot}/CMakeLists.txt', 'w').write('')
        cmds = []

        def sh(cmd, cwd=None, env=None, timeout=3600):
            cmds.append(list(cmd)); return 0, 'log', 0.0
        BD.SAN_FLAGS_EXE = CF.SAN_FLAGS_EXE
        if pic: M.install_pic()
        with mock.patch.object(BD, 'T', f'{d}/T'), mock.patch.object(BD, 'sh', sh):
            if wrap:
                with wrap(): info = BD.build_c_exe(f'{d}/B', 'P01_sphincs_plus', '005_x', san=True)
            else: info = BD.build_c_exe(f'{d}/B', 'P01_sphincs_plus', '005_x', san=True)
        return cmds, info, f'{d}/B/c-san/P01_sphincs_plus/005_x'

    def test_cmake_command_has_pic_flag(self):
        orig, _, wd0 = self._capture_build(False)
        pic, _, wd1 = self._capture_build(True)
        norm = lambda cmds, wd: [[x.replace(wd, '<WD>') for x in c] for c in cmds]
        o, p = norm(orig, wd0), norm(pic, wd1)
        self.assertEqual(o[0], ['cmake', '-S', '<WD>', '--preset', 'test', '-DCMAKE_C_COMPILER=clang'] + FROZEN_LITERAL)
        self.assertEqual(p[0], o[0] + ['-DCMAKE_POSITION_INDEPENDENT_CODE=ON'])   # khác đúng một cờ, ở cuối, không ghi kiểu
        self.assertEqual(p[1:], o[1:])                                             # bước cmake --build như nhau
        self.assertEqual(p[1][:2], ['cmake', '--build'])

    def test_configure_only_skips_build(self):
        cmds, info, _ = self._capture_build(False, wrap=M.configure_only)
        self.assertEqual(len(cmds), 1); self.assertEqual(cmds[0][-len(FROZEN_LITERAL):], FROZEN_LITERAL)
        self.assertFalse(info['ok'])

    def test_configure_only_restores_sh(self):
        real = BD.sh
        with M.configure_only(): self.assertIsNot(BD.sh, real)
        self.assertIs(BD.sh, real)

    def test_supp_key_refuses_without_pic(self):
        BD.SAN_FLAGS_EXE = CF.SAN_FLAGS_EXE
        with self.assertRaises(RuntimeError): M.supp_key('/nonexistent', dict(bundle='b', case='c'), san_fn=fake_san('no_report'))


class RealWorkers(unittest.TestCase):
    """Worker thật của ProcessPoolExecutor nhận cờ PIC qua initializer; tiến trình cha không bị gán (review L10)."""
    def setUp(self):
        BD.SAN_FLAGS_EXE = CF.SAN_FLAGS_EXE
        self.addCleanup(setattr, BD, 'SAN_FLAGS_EXE', CF.SAN_FLAGS_EXE)

    def _check(self, ctx):
        import multiprocessing as mp
        with ProcessPoolExecutor(2, initializer=M.install_pic, mp_context=mp.get_context(ctx)) as ex:
            res = [ex.submit(M.worker_flags).result() for _ in range(4)]
        for flags, ok, pid in res:
            self.assertEqual(flags, FROZEN_LITERAL + [M.PIC_FLAG]); self.assertTrue(ok); self.assertNotEqual(pid, os.getpid())
        self.assertTrue(M.orig_flags_in_effect())

    def test_fork(self):
        self._check('fork')

    @unittest.skipUnless(os.path.exists(os.path.join(os.path.dirname(harness.__file__), 'rq2_san_supp.py')),
                         'spawn cần module nằm trong harness/ của repo (sau commit)')
    def test_spawn(self):
        self._check('spawn')


class OrigAndBuildCommands(unittest.TestCase):
    """Lệnh orig (không gán, build case smoke, configure 35 case) và build (gán, build 36 case) với sh giả: cờ cmake đúng ở từng tiến trình."""
    def setUp(self):
        self.addCleanup(setattr, BD, 'SAN_FLAGS_EXE', CF.SAN_FLAGS_EXE)
        BD.SAN_FLAGS_EXE = CF.SAN_FLAGS_EXE
        self.d = tempfile.mkdtemp(prefix='supp-cmd-'); self.addCleanup(shutil.rmtree, self.d, True)
        self.keys = [f'codex-gpt54/P01_sphincs_plus/{i:03d}_c' for i in (5, 6, 7)]
        for k in self.keys:
            t = f'{self.d}/T/P01_sphincs_plus/{k.split("/")[-1]}'; os.makedirs(f'{t}/test_case')
            json.dump(dict(configurePresets=[dict(name='test')]), open(f'{t}/CMakePresets.json', 'w'))
        self.g = dict(ok=True, failed=[], keys=dict(ok=True, keys=self.keys), amendment=dict(ok=True, commit='c' * 40))
        self.cmds = []

    def sh(self, cmd, cwd=None, env=None, timeout=3600):
        self.cmds.append(list(cmd)); return 1, 'relocation R_X86_64_PC32 ...', 0.0

    def run_cmd(self, argv):
        with mock.patch.object(M, 'preflight', return_value=self.g), mock.patch.object(M, 'manifest'), \
             mock.patch.object(M, 'ProcessPoolExecutor', FakeEx), mock.patch.object(BD, 'T', f'{self.d}/T'), \
             mock.patch.object(BD, 'sh', self.sh):
            return M.main(argv)

    def test_orig_then_build(self):
        common = ['--build-root', f'{self.d}/B', '--orig-root', f'{self.d}/Bo']
        self.run_cmd(['orig', *common, '--out', f'{self.d}/out-orig', '--configure-rest'])
        cfg = [c for c in self.cmds if c[:2] == ['cmake', '-S']]; bld = [c for c in self.cmds if c[:2] == ['cmake', '--build']]
        self.assertEqual(len(cfg), 3); self.assertEqual(len(bld), 0)      # sh giả trả rc 1 ở configure nên không có bước build
        self.assertTrue(all(c[-2:] == FROZEN_LITERAL and M.PIC_FLAG not in c for c in cfg))
        modes = {k: v['mode'] for k, v in json.load(open(f'{self.d}/out-orig/orig-builds.json')).items()}
        self.assertEqual(modes, {'005_c': 'build', '006_c': 'configure_only', '007_c': 'configure_only'})
        self.assertTrue(M.orig_flags_in_effect())
        self.cmds.clear()
        with self.assertRaises(SystemExit) as e: self.run_cmd(['build', *common, '--out', f'{self.d}/out-build'])
        self.assertEqual(e.exception.code, M.EXIT_BUILD)                    # build giả không có driver: mã riêng (review R2-03)
        cfg = [c for c in self.cmds if c[:2] == ['cmake', '-S']]
        self.assertEqual(len(cfg), 3); self.assertTrue(all(c[-3:] == FROZEN_LITERAL + [M.PIC_FLAG] for c in cfg))
        self.assertTrue(all(c[2].startswith(f'{os.path.realpath(self.d)}/B/c-san/') for c in cfg))
        b = json.load(open(f'{self.d}/out-build/builds.json'))
        self.assertEqual(sorted(b['builds']), ['005_c', '006_c', '007_c']); self.assertEqual(b['san_flags_exe'], FROZEN_LITERAL + [M.PIC_FLAG])
        self.assertEqual(b['workers'], 1)                                   # review L5: build PIC tuần tự theo mặc định
        self.assertIs(FakeEx.seen[-1], M.install_pic)

    def test_build_default_workers_is_one(self):
        a = M.build_parser().parse_args(['build', '--out', 'x']); self.assertEqual(a.workers, 1)
        a = M.build_parser().parse_args(['run', '--out', 'x', '--s0', 's', '--full', '--gate-json', 'g']); self.assertEqual(a.workers, 6)

    def test_orig_refuses_with_pic_installed_or_same_root(self):
        M.install_pic()
        with self.assertRaises(SystemExit): self.run_cmd(['orig', '--out', f'{self.d}/o', '--build-root', f'{self.d}/B', '--orig-root', f'{self.d}/Bo'])
        BD.SAN_FLAGS_EXE = CF.SAN_FLAGS_EXE
        with self.assertRaises(SystemExit): self.run_cmd(['orig', '--out', f'{self.d}/o', '--build-root', f'{self.d}/B', '--orig-root', f'{self.d}/B'])
        with self.assertRaises(SystemExit): self.run_cmd(['build', '--out', f'{self.d}/o', '--build-root', f'{self.d}/B', '--orig-root', f'{self.d}/B'])
        self.assertEqual(self.cmds, [])

    def test_expect_builds_hashes_driver_and_so(self):
        B = f'{self.d}/B'
        want = {}
        for k in self.keys:
            c = k.split('/')[-1]; wd = f'{B}/c-san/P01_sphincs_plus/{c}'; os.makedirs(f'{wd}/build-ninja', exist_ok=True)
            open(f'{wd}/build-ninja/driver', 'w').write(c); open(f'{wd}/build-ninja/libsphincs_core.so', 'w').write(c + 'so')
            json.dump(dict(ok=True, sha256=c * 2), open(f'{wd}.build.json', 'w'))
            want[c] = dict(ok=True, sha256=c * 2, files=M.tree_hashes(wd))
        self.assertEqual(sorted(want['005_c']['files']), ['build-ninja/driver', 'build-ninja/libsphincs_core.so'])
        p = f'{self.d}/builds.json'; json.dump(dict(builds=want), open(p, 'w'))
        M.expect_builds(p, B, self.keys)
        open(f'{B}/c-san/P01_sphincs_plus/006_c/build-ninja/libsphincs_core.so', 'w').write('khác')     # review N3: .so đổi
        with self.assertRaises(SystemExit): M.expect_builds(p, B, self.keys)
        open(f'{B}/c-san/P01_sphincs_plus/006_c/build-ninja/libsphincs_core.so', 'w').write('006_cso')
        M.expect_builds(p, B, self.keys)
        json.dump(dict(ok=True, sha256='x'), open(f'{B}/c-san/P01_sphincs_plus/006_c.build.json', 'w'))
        with self.assertRaises(SystemExit): M.expect_builds(p, B, self.keys)


class OptionLines(unittest.TestCase):
    def test_detect(self):
        bad = ['> OPTION I: chưa chốt', '>> **OPTION II** (a/b)', '  > _OPTION III_', '### OPTION IV-k', '> `OPTION` V']
        ok = ['Job tìm chuỗi `OPTION` ở đầu khối trích dẫn', '(ii) không đổi `ASAN_OPTIONS`;', '> Ghi chú: không có OPTION nào',
              '- Amendment đã commit còn khối OPTION.']
        for l in bad: self.assertTrue(M.option_lines(l), l)
        for l in ok: self.assertFalse(M.option_lines(l), l)


@needs(os.path.exists(KEYS_FILE), 'đặt SUPP_KEYS tới keys.txt')
class Refusals(unittest.TestCase):
    """Repo git tạm có amendment, keys.txt; kiểm từng đường từ chối của amendment_check, keys_check, preflight."""
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='supp-git-'); self.addCleanup(shutil.rmtree, self.d, True)
        self.keys = open(KEYS_FILE).read()
        git(self.d, 'init', '-q', '-b', 'main')
        os.makedirs(f'{self.d}/docs'); os.makedirs(f'{self.d}/experiments/37-rq2-san-supp/data')
        self.text = (f'# Amendment\n\nkeys.txt sha256 `{M.KEYS_SHA256}`\nS0 sha256 `{M.S0_SHA256}`\n'
                     'Job tìm chuỗi `OPTION` ở đầu khối trích dẫn; còn thì dừng.\n')
        self.write(self.text); open(f'{self.d}/{M.KEYS}', 'w').write(self.keys)
        git(self.d, 'add', '-A'); git(self.d, 'commit', '-q', '-m', 'amendment')
        self.c1 = git(self.d, 'rev-parse', 'HEAD')

    def write(self, text):
        open(f'{self.d}/{M.AMENDMENT}', 'w').write(text)

    def commit(self, msg='x'):
        git(self.d, 'add', '-A'); git(self.d, 'commit', '-q', '-m', msg); return git(self.d, 'rev-parse', 'HEAD')

    def test_ok(self):
        r = M.amendment_check(self.d)
        self.assertTrue(r['ok'], r); self.assertEqual(r['commit'], self.c1)
        self.assertTrue(M.amendment_check(self.d, self.c1)['ok'])
        k = M.keys_check(self.d); self.assertTrue(k['ok'], k); self.assertEqual(k['n'], 36)
        self.assertEqual(k['smoke_key'], 'codex-gpt54/P01_sphincs_plus/005_sphincs_PQCgenKAT_sign_blake_128f_simple')

    @needs(os.path.exists(AMENDMENT_FILE), 'đặt SUPP_AMENDMENT tới amendment')
    def test_real_amendment_text_passes(self):
        text = open(AMENDMENT_FILE).read()
        self.write(text); self.commit('amendment thật')
        r = M.amendment_check(self.d); self.assertTrue(r['ok'], r); self.assertFalse(M.option_lines(text))
        self.assertIn('CMAKE_POSITION_INDEPENDENT_CODE:UNINITIALIZED=ON', text)      # S-cache theo chữ Le chốt (C1)
        self.assertIn('supp_harness_error', text)                                     # mã lý do đăng ký (L8)
        self.assertNotIn('rqSanSuppADisagreeExeAllCodexNum', text.split('## Nhật ký sửa trước commit')[0])   # tên cũ chỉ còn ở nhật ký
        self.assertIn('rqSanSuppDisagreeOfSuppExeAllCodexNum', text)
        body = text.split('## Nhật ký sửa trước commit')[0]
        for gone in ('rq2-san-supp-store', 'mirror', 'prior-', 'attempts.jsonl', 'RETRY_ERROR', 'segments/'):   # D1: bỏ cơ chế nhiều đoạn
            self.assertNotIn(gone, body, gone)
        self.assertNotIn('\u2014', text)

    def test_ok_with_later_unrelated_commit(self):
        open(f'{self.d}/other.txt', 'w').write('x'); self.commit()
        r = M.amendment_check(self.d); self.assertTrue(r['ok'], r); self.assertEqual(r['commit'], self.c1)

    def test_bad_keys_hash(self):
        open(f'{self.d}/{M.KEYS}', 'w').write(self.keys.replace('005_', '005x_')); self.commit()
        r = M.keys_check(self.d); self.assertFalse(r['ok']); self.assertIn('sha256', r['reason'])

    def test_keys_hash_ok_but_wrong_constant(self):
        r = M.keys_check(self.d, want='0' * 64); self.assertFalse(r['ok'])

    def test_unresolved_option(self):
        for blk in ('> OPTION I (chưa chốt): a hay b\n', '> **OPTION V**: tag r2 / giữ r1\n'):
            self.write(self.text + '\n' + blk); self.commit()
            r = M.amendment_check(self.d); self.assertFalse(r['ok']); self.assertIn('OPTION', r['reason'])

    def test_non_ancestor_commit(self):
        git(self.d, 'checkout', '-q', '-b', 'side')
        self.write(self.text + '\nbản khác\n'); side = self.commit('side')
        git(self.d, 'checkout', '-q', 'main')
        r = M.amendment_check(self.d, side); self.assertFalse(r['ok']); self.assertIn('tổ tiên', r['reason'])

    def test_unknown_commit(self):
        r = M.amendment_check(self.d, 'f' * 40); self.assertFalse(r['ok']); self.assertIn('không tồn tại', r['reason'])

    def test_modified_after_commit(self):
        self.write(self.text + '\nsửa sau\n'); self.commit()
        r = M.amendment_check(self.d, self.c1); self.assertFalse(r['ok']); self.assertIn('khác bản', r['reason'])

    def test_uncommitted_change(self):
        self.write(self.text + '\nchưa commit\n')
        r = M.amendment_check(self.d); self.assertFalse(r['ok']); self.assertIn('chưa commit', r['reason'])
        self.write(self.text); open(f'{self.d}/{M.KEYS}', 'a').write('x\n')
        r = M.amendment_check(self.d); self.assertFalse(r['ok']); self.assertIn('keys.txt', r['reason'])

    def test_not_committed(self):
        d = tempfile.mkdtemp(prefix='supp-git0-'); self.addCleanup(shutil.rmtree, d, True)
        git(d, 'init', '-q'); open(f'{d}/a', 'w').write('a'); git(d, 'add', 'a'); git(d, 'commit', '-q', '-m', 'a')
        r = M.amendment_check(d); self.assertFalse(r['ok']); self.assertIn('chưa được commit', r['reason'])

    def test_amendment_without_hashes(self):
        self.write('# Amendment\n'); self.commit()
        r = M.amendment_check(self.d); self.assertFalse(r['ok']); self.assertIn('sha256', r['reason'])

    def _args(self, **kw):
        a = M.build_parser().parse_args(['check']); a.__dict__.update(kw); return a

    def test_preflight_classes(self):
        trc = dict(ok=True, reason='ok')
        with mock.patch('harness.main_run.freeze_check', return_value=OK), mock.patch.object(M, 'env_check', return_value=OK), \
             mock.patch.object(M, 'tractor_check', return_value=trc), mock.patch.object(M, 'deadline_check', return_value=OK):
            g = M.preflight(self.d, self._args()); self.assertTrue(g['ok'], g); M.require(g); self.assertEqual(M.classify(g), 'ok')
            g = M.preflight(self.d, self._args(freeze_tag='protocol-freeze-r2'))
            self.assertEqual(g['failed'], ['freeze']); self.assertEqual(M.classify(g), 'stop')          # D3a: freeze hỏng là luật dừng
        with mock.patch('harness.main_run.freeze_check', return_value=dict(ok=False, reason='harness/ có file bị sửa')), \
             mock.patch.object(M, 'env_check', return_value=OK), mock.patch.object(M, 'tractor_check', return_value=trc), \
             mock.patch.object(M, 'deadline_check', return_value=OK):
            g = M.preflight(self.d, self._args()); self.assertEqual((g['failed'], M.classify(g)), (['freeze'], 'stop'))
        with mock.patch('harness.main_run.freeze_check', return_value=OK), mock.patch.object(M, 'env_check', return_value=OK), \
             mock.patch.object(M, 'tractor_check', return_value=dict(ok=False, reason='TRACTOR sai commit')), \
             mock.patch.object(M, 'deadline_check', return_value=OK):
            g = M.preflight(self.d, self._args()); self.assertEqual((g['failed'], M.classify(g)), (['tractor'], 'fail'))
        with mock.patch('harness.main_run.freeze_check', return_value=OK), mock.patch.object(M, 'env_check', return_value=OK), \
             mock.patch.object(M, 'tractor_check', return_value=trc), mock.patch.object(M, 'deadline_check', return_value=OK):
            self.write(self.text + '> OPTION I: x\n'); self.commit()
            g = M.preflight(self.d, self._args()); self.assertEqual(g['failed'], ['amendment']); self.assertEqual(M.classify(g), 'stop')
            with self.assertRaises(M.Stop) as e: M.require(g)
            self.assertEqual(e.exception.code, M.EXIT_STOP); self.assertIn('OPTION', str(e.exception))
        self.write(self.text); self.commit()
        with mock.patch('harness.main_run.freeze_check', return_value=OK), \
             mock.patch.object(M, 'env_check', return_value=dict(ok=False, reason='lệch')), mock.patch.object(M, 'tractor_check', return_value=trc), \
             mock.patch.object(M, 'deadline_check', return_value=OK):
            g = M.preflight(self.d, self._args())
            self.assertEqual(g['failed'], ['env'])
            self.assertEqual(M.classify(g), 'fail')                          # C5: lệch môi trường ở preflight là fail
            with self.assertRaises(M.Refuse) as e: M.require(g)
            self.assertNotIsInstance(e.exception, M.Stop)


class Classify(unittest.TestCase):
    def test_table(self):
        g = lambda *f: dict(failed=list(f))
        self.assertEqual(M.classify(g()), 'ok')
        for x in ('env', 'tractor', 'vector_files'): self.assertEqual(M.classify(g(x)), 'fail', x)
        # Le chốt vòng 3 (D3a): freeze_check hỏng là luật dừng, như "cần đổi file đã freeze" ở mục 10
        for x in ('amendment', 'keys', 's0', 'inputs', 'deadline', 'freeze'): self.assertEqual(M.classify(g(x)), 'stop', x)
        self.assertEqual(M.classify(g('env', 'deadline')), 'stop')
        self.assertEqual(M.classify(g('vector_files', 'inputs')), 'stop')


class Env(unittest.TestCase):
    GOOD = dict(instance_type='c7i.2xlarge', ami_id='ami-0c4ae4cba162bf697', instance_id='i-0abc')
    CL, GCC, RT = 'Ubuntu clang version 18.1.3 (1ubuntu1)', 'gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0', '1:18.1.3-1ubuntu1'

    def env(self, m=None, clang=None, gcc=None, rt=None):
        with mock.patch.object(M, 'tool', return_value='x'):
            return M.env_check(dict(self.GOOD) if m is None else m, clang or self.CL, gcc or self.GCC, rt or self.RT)

    def test_env(self):
        self.assertTrue(self.env()['ok'])
        self.assertFalse(self.env(dict(self.GOOD, instance_type='m7i-flex.large'))['ok'])
        self.assertFalse(self.env(dict(self.GOOD, ami_id='ami-0'))['ok'])
        self.assertFalse(self.env(clang='Ubuntu clang version 18.1.8')['ok'])
        self.assertEqual(self.env(gcc='gcc (Ubuntu 14.2.0) 14.2.0')['mismatch'], ['gcc'])
        self.assertEqual(self.env(rt='không có')['mismatch'], ['libclang_rt'])
        r = self.env(dict(source='none', error='URLError'))
        self.assertFalse(r['ok']); self.assertEqual(r['unreadable'], list(M.IMDS_KEYS)); self.assertEqual(r['mismatch'], [])
        r = self.env(dict(self.GOOD, instance_id=None)); self.assertFalse(r['ok']); self.assertEqual(r['unreadable'], ['instance_id'])

    def test_imds_retry(self):
        seq = [dict(source='none'), dict(source='ec2-imds', instance_type='c7i.2xlarge'), dict(self.GOOD)]
        with mock.patch.object(M.time, 'sleep') as sl:
            m = M.machine_info_retry(fn=lambda: seq.pop(0))
        self.assertEqual((m['instance_id'], m['imds_tries']), ('i-0abc', 3)); self.assertEqual(sl.call_count, 2)
        with mock.patch.object(M.time, 'sleep'):
            m = M.machine_info_retry(tries=3, fn=lambda: dict(source='none'))
        self.assertTrue(m['imds_unreadable']); self.assertEqual(m['imds_tries'], 3)

    def test_deadline(self):
        import calendar, time
        dl = calendar.timegm(time.strptime('2026-11-10T05:00:00Z', '%Y-%m-%dT%H:%M:%SZ'))
        self.assertTrue(M.deadline_check(dl - 1)['ok']); self.assertFalse(M.deadline_check(dl)['ok'])


def run_cli(argv, cwd=REPO):
    """Chạy main của module trong tiến trình con như `python3 -m harness.rq2_san_supp` (kèm RQ2_SAN_SUPP_SRC nếu module ngoài repo)."""
    code = ('import os, sys, harness\n'
            'src = os.environ.get("RQ2_SAN_SUPP_SRC")\n'
            'if src and src not in harness.__path__: harness.__path__.append(src)\n'
            'from harness import rq2_san_supp as M\n'
            f'M.main({argv!r}, repo=os.environ.get("CLI_REPO"))\n')
    return subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=REPO,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=REPO, CLI_REPO=cwd))


class GitRemote:
    """Remote git thật (bare) và một clone, để kiểm các lệnh đọc nhánh results/ bằng ls-remote, fetch (không stub git)."""
    def __init__(self, tc, files=None):
        self.d = tempfile.mkdtemp(prefix='remote-'); tc.addCleanup(shutil.rmtree, self.d, True)
        self.origin, self.work, self.clone = f'{self.d}/origin.git', f'{self.d}/work', f'{self.d}/clone'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', self.origin], check=True)
        git(self.d, 'init', '-q', '-b', 'main', self.work)
        for p, text in (files or {'README': 'x\n'}).items():
            os.makedirs(os.path.dirname(f'{self.work}/{p}') or self.work, exist_ok=True); open(f'{self.work}/{p}', 'w').write(text)
        git(self.work, 'add', '-A'); git(self.work, 'commit', '-q', '-m', 'init')
        git(self.work, 'remote', 'add', 'origin', self.origin); git(self.work, 'push', '-q', 'origin', 'main')
        git(self.d, 'clone', '-q', self.origin, self.clone)

    def head(self): return git(self.work, 'rev-parse', 'HEAD')

    def publish(self, branch, files, parent='main'):
        """Như bước Publish: commit ci-out trên commit job rồi push -f lên <branch>. Trả commit kết quả."""
        git(self.work, 'checkout', '-q', '-B', 'pub', parent)
        for p, text in files.items():
            os.makedirs(os.path.dirname(f'{self.work}/{p}'), exist_ok=True); open(f'{self.work}/{p}', 'w').write(text)
        git(self.work, 'add', '-A'); git(self.work, 'commit', '-q', '-m', f'{branch}')
        c = git(self.work, 'rev-parse', 'HEAD')
        git(self.work, 'push', '-q', '-f', 'origin', f'pub:refs/heads/{branch}')
        git(self.work, 'checkout', '-q', 'main'); git(self.work, 'branch', '-q', '-D', 'pub')
        return c


WORKFLOW = os.environ.get('SUPP_WORKFLOW') or f'{REPO}/.github/workflows/runner-jobs.yml'


def publish_step_script(path=WORKFLOW):
    """Thân bước "Publish results" của workflow thật (guard: nhánh results/<job> có nhiều dòng rq[12]-*.jsonl hơn ci-out local thì đẩy sang
    results-failed/<job>-<run>), lấy nguyên văn từ file workflow để test chạy đúng code đó."""
    lines = open(path).read().splitlines()
    i = next(i for i, l in enumerate(lines) if l.strip() == '- name: Publish results')
    j = next(j for j in range(i, len(lines)) if lines[j].strip() == 'run: |')
    ind, body = len(lines[j]) - len(lines[j].lstrip()), []
    for l in lines[j + 1:]:
        if l.strip() and len(l) - len(l.lstrip()) <= ind: break
        body.append(l)
    return textwrap.dedent('\n'.join(body)) + '\n'


def publish_like_workflow(remote, ci_out, job, run_id):
    """Chạy bước Publish thật trên một clone của remote với ci-out chép từ `ci_out`; URL github.com trỏ về remote bằng insteadOf. Trả nhánh
    đích (results/<job> hoặc results-failed/<job>-<run>)."""
    pc = f'{remote.d}/pubclone'
    if not os.path.isdir(pc):
        git(remote.d, 'clone', '-q', remote.origin, pc)
        git(pc, 'config', f'url.file://{remote.origin}.insteadOf', 'https://github.com/o/r.git')
    git(pc, 'checkout', '-q', '--detach', 'origin/main'); git(pc, 'clean', '-qffdx')
    shutil.copytree(ci_out, f'{pc}/ci-out')
    p = subprocess.run(['bash', '-c', publish_step_script()], cwd=pc, capture_output=True, text=True,
                       env=dict(os.environ, GITHUB_REF_NAME=f'jobs/{job}', GITHUB_REPOSITORY='o/r', GITHUB_RUN_ID=str(run_id), PUSH_TOKEN=''))
    assert p.returncode == 0, p.stdout + p.stderr
    failed = f'results-failed/{job}-{run_id}'
    ls = subprocess.run(['git', '-C', pc, 'ls-remote', 'origin', f'refs/heads/{failed}'], capture_output=True, text=True).stdout
    git(pc, 'checkout', '-q', '--detach', 'origin/main'); git(pc, 'clean', '-qffdx')
    return failed if ls.strip() else f'results/{job}'


@needs(os.path.exists(WORKFLOW), 'đặt SUPP_WORKFLOW tới .github/workflows/runner-jobs.yml')
class PublishGuard(unittest.TestCase):
    """Guard của bước Publish thật (R3-01 ii, R3-02): đích là results-failed/<job>-<run> khi NR > NL, còn lại đè results/<job>."""
    def put(self, d, job, n):
        os.makedirs(f'{d}/{job}', exist_ok=True)
        open(f'{d}/{job}/rq2-x.jsonl', 'w').write('{}\n' * n); open(f'{d}/{job}/provenance.txt', 'w').write('p\n')
        return d

    def test_destination_choice(self):
        r = GitRemote(self); t = tempfile.mkdtemp(dir=r.d)
        self.assertEqual(publish_like_workflow(r, self.put(f'{t}/a', 'j', 2), 'j', 1), 'results/j')
        self.assertEqual(publish_like_workflow(r, self.put(f'{t}/b', 'j', 0), 'j', 2), 'results-failed/j-2')     # 0 dòng không đè 2 dòng
        self.assertEqual(publish_like_workflow(r, self.put(f'{t}/c', 'j', 1), 'j', 3), 'results-failed/j-3')
        self.assertEqual(publish_like_workflow(r, self.put(f'{t}/d', 'j', 2), 'j', 4), 'results/j')              # bằng nhau thì đè
        self.assertEqual(git(r.clone, 'ls-remote', 'origin', 'refs/heads/results-failed/*').count('\n') + 1, 2)


class Scan(unittest.TestCase):
    """Một job một đoạn (Le chốt vòng 3, vòng 4): đọc results/<job> và results-failed/<job>-<run> trên remote thật, quyết số lần thử. Một
    lần nộp là lần thử đã tính khi có run/manifest.json (lần chạy đã tới bước thực thi); lịch sử lần thử chép tiếp trong rq2-supp-runs.jsonl."""
    J = M.JOBS

    def setUp(self):
        self.r = GitRemote(self)

    def pub(self, job, stop=False, complete=False, noop=False, attempt=None, failed_run=None, counted=False, history=()):
        """counted: lần chạy đã ghi run/manifest.json (và dòng của nó vào lịch sử). history: dòng lịch sử chép tiếp từ lần nộp trước."""
        f = {f'ci-out/{job}/provenance.txt': 'p\n'}
        if stop: f[f'ci-out/{job}/STOP.txt'] = 'lý do dừng\n'
        if complete: f[f'ci-out/{job}/{M.COMPLETE}'] = '{}\n'
        if noop: f[f'ci-out/{job}/{M.NOOP}'] = 'noop\n'
        if attempt: f[f'ci-out/{job}/{M.ATTEMPT}'] = json.dumps(dict(attempt=attempt))
        lines = list(history) + ([dict(job=job, attempt=attempt, run_id=None, run_attempt=None, utc=f'u{attempt}-{failed_run}')] if counted else [])
        if counted: f[f'ci-out/{job}/{M.RUN_MANIFEST}'] = '{}\n'
        if lines: f[f'ci-out/{job}/{M.RUNS}'] = ''.join(json.dumps(l, sort_keys=True) + '\n' for l in lines)
        self.r.publish(f'results-failed/{job}-{failed_run}' if failed_run else f'results/{job}', f)
        return lines

    def decide(self, mode, declared=1):
        return M.attempt_decision(M.scan_remote(self.r.clone), mode, declared)

    def test_nothing_published(self):
        self.assertEqual(M.scan_remote(self.r.clone), [])
        self.assertEqual(self.decide('smoke')[::2], ('ok', 1))
        self.assertEqual(self.decide('smoke', 2)[::2], ('ok', 2))          # một lần chạy đã tới thực thi mà không nộp được (khai báo)
        self.assertEqual(self.decide('smoke', 3)[0], 'stop')

    def test_counted_attempts(self):
        h = self.pub(self.J['smoke'], attempt=1, counted=True)
        self.assertEqual(self.decide('smoke')[::2], ('ok', 2))
        self.pub(self.J['smoke'], attempt=2, counted=True, history=h)       # lần thử 2 nộp được mà không hoàn tất, không có STOP (bị kill)
        self.assertEqual(self.decide('smoke')[0], 'stop')
        self.assertEqual(self.decide('full')[::2], ('ok', 1))               # số lần thử tính riêng từng job

    def test_refused_runs_not_counted(self):
        """Le chốt vòng 4 (R3-03): lần chạy bị từ chối trước bước thực thi (không có run/manifest.json) được nộp nhưng không tính."""
        self.pub(self.J['smoke'], attempt=1)
        self.pub(self.J['smoke'], attempt=1, failed_run=3)
        self.assertEqual(self.decide('smoke')[::2], ('ok', 1))
        h = self.pub(self.J['smoke'], attempt=1, counted=True)
        self.pub(self.J['smoke'], attempt=2, failed_run=4, history=h)       # bị từ chối ở lần thử 2: vẫn chép tiếp lịch sử, không tính
        self.pub(self.J['smoke'], attempt=2, failed_run=5)
        self.assertEqual(self.decide('smoke')[::2], ('ok', 2))

    def test_history_survives_overwrite(self):
        """R3-01 (ii): lần nộp đã tính bị một lần chạy bị từ chối đè ở results/<job>; dòng của nó còn trong lịch sử chép tiếp."""
        h = self.pub(self.J['full'], attempt=1, counted=True)
        self.pub(self.J['full'], attempt=2, history=h)                      # đè results/rq2-san-supp, chép tiếp 1 dòng
        self.assertEqual(self.decide('full')[::2], ('ok', 2))
        self.pub(self.J['full'], attempt=2)                                 # đè tiếp mà không chép lịch sử (không xảy ra với job thật)
        self.assertEqual(self.decide('full')[::2], ('ok', 1))               # rủi ro còn lại, ghi ở amendment: chỉ run list ở notes phủ được

    def test_formula(self):
        """R3-01 (iii): n = max(khai báo, lớn nhất + 1, số lần thử đã tính + 1)."""
        f = lambda *ns: [dict(job=self.J['smoke'], ref=f'r{i}', commit='c', stop=None, complete=False, noop=False, attempt=n, run_id=None,
                              run_attempt=None, counted=False, history=[dict(attempt=n, utc=str(i))]) for i, n in enumerate(ns)]
        self.assertEqual(M.attempt_decision(f(1), 'smoke')[::2], ('ok', 2))
        self.assertEqual(M.attempt_decision(f(1, 1), 'smoke')[0], 'stop')   # hai lần thử đều ghi số 1: vẫn là hai lần
        self.assertEqual(M.attempt_decision(f(), 'smoke', 2)[::2], ('ok', 2))
        self.assertEqual(M.attempt_decision(f(1), 'smoke', 3)[0], 'stop')

    def test_results_failed_counts(self):
        """Lần nộp bị guard đẩy sang results-failed/<job>-<run> vẫn được đọc: STOP ở đó chặn, lần thử ở đó được đếm."""
        h = self.pub(self.J['full'], attempt=1, counted=True)
        self.pub(self.J['full'], attempt=2, failed_run=123, counted=True, history=h)
        self.assertEqual(self.decide('full')[0], 'stop')
        r = GitRemote(self); self.r = r
        self.pub(self.J['full'], attempt=1, counted=True); self.pub(self.J['full'], stop=True, failed_run=77)
        cls, why, _ = self.decide('full'); self.assertEqual(cls, 'stop'); self.assertIn('results-failed/rq2-san-supp-77', why)
        self.pub(self.J['full'] + '-smoke', attempt=1, failed_run=5)       # tên khác (rq2-san-supp-smoke-5) không bị tính cho job đầy đủ
        self.assertEqual([x['ref'] for x in M.scan_remote(self.r.clone) if x['job'] == 'rq2-san-supp'],
                         ['refs/heads/results-failed/rq2-san-supp-77', 'refs/heads/results/rq2-san-supp'])

    def test_stop_anywhere_and_complete(self):
        self.pub(self.J['gate'], stop=True)
        for mode in ('gate', 'smoke', 'full'): self.assertEqual(self.decide(mode)[0], 'stop', mode)
        self.r = GitRemote(self)
        self.pub(self.J['smoke'], complete=True, attempt=1, counted=True)
        self.assertEqual(self.decide('smoke')[0], 'noop')                   # đã hoàn tất: không chạy lại
        self.assertEqual(self.decide('gate')[0], 'noop')                    # R3-06: gate không chạy khi smoke đã hoàn tất
        self.assertEqual(self.decide('full')[::2], ('ok', 1))
        self.pub(self.J['full'], complete=True, attempt=2, counted=True)
        self.assertEqual(self.decide('gate', 5)[0], 'noop')

    def test_gate_no_attempt_limit(self):
        """Le chốt vòng 4: job gate không giới hạn lần thử, không bao giờ STOP vì số lần chạy."""
        for i in range(4): self.pub(self.J['gate'], attempt=i + 1, failed_run=10 + i)
        self.assertEqual(self.decide('gate')[0], 'ok')
        self.assertEqual(self.decide('gate', 7)[0], 'ok')

    def test_noop_publish_not_counted(self):
        self.pub(self.J['smoke'], attempt=1, counted=True); self.pub(self.J['smoke'], noop=True, failed_run=9)
        self.assertEqual(self.decide('smoke')[::2], ('ok', 2))

    def test_fetch_or_ls_remote_error_is_fail(self):
        self.pub(self.J['smoke'], attempt=1)
        git(self.r.clone, 'remote', 'set-url', 'origin', f'{self.r.d}/khong-co.git')
        with self.assertRaises(M.Refuse): M.scan_remote(self.r.clone)
        with mock.patch.object(M, 'published', side_effect=M.Refuse('tải lỗi')):
            git(self.r.clone, 'remote', 'set-url', 'origin', self.r.origin)
            with self.assertRaises(M.Refuse): M.scan_remote(self.r.clone)

    def test_cli(self):
        out = f'{self.r.d}/out'
        p = run_cli(['scan', '--mode', 'smoke', '--out', out], cwd=self.r.clone)
        self.assertEqual(p.returncode, 0, p.stderr); self.assertIn('ATTEMPT=1', p.stdout)
        self.assertEqual(json.load(open(f'{out}/{M.ATTEMPT}'))['attempt'], 1); self.assertFalse(os.path.exists(f'{out}/{M.RUNS}'))
        self.pub(self.J['smoke'], attempt=1, counted=True)
        p = run_cli(['scan', '--mode', 'smoke', '--out', f'{out}1'], cwd=self.r.clone)
        self.assertIn('ATTEMPT=2', p.stdout); self.assertEqual(len(M.records(f'{out}1/{M.RUNS}')), 1)      # lịch sử chép tiếp
        self.pub(self.J['smoke'], complete=True, attempt=1)
        p = run_cli(['scan', '--mode', 'smoke', '--out', f'{out}2'], cwd=self.r.clone)
        self.assertEqual(p.returncode, M.EXIT_NOOP, p.stderr); self.assertTrue(os.path.exists(f'{out}2/{M.NOOP}'))
        self.pub(self.J['full'], stop=True)
        self.assertEqual(run_cli(['scan', '--mode', 'full', '--out', f'{out}3'], cwd=self.r.clone).returncode, M.EXIT_STOP)


class B0Branch(unittest.TestCase):
    """Mục 7 bước 2 (Le chốt vòng 3, D2): đọc dòng `máy:` và KẾT LUẬN; máy khác hay instance id không đọc được là fail."""
    def s(self, iid, concl):
        return (f'B0 rq2-san-log: marker\nmáy: instance_id={iid} (nguồn: IMDSv2) instance_type=c7i.2xlarge (rq2-main exe chạy ở '
                f'{M.B0_INSTANCE})\n' + (f'KẾT LUẬN: {concl}\n' if concl else ''))

    def test_branches(self):
        W = M.B0_INSTANCE
        self.assertEqual(M.b0_branch(self.s(W, 'TRÙNG với bản tái hiện local (36/36 ...)'))[0], 'a')
        self.assertEqual(M.b0_branch(self.s(W, 'CHƯA TRÙNG HOÀN TOÀN với bản tái hiện local (30/36 ..., máy đúng)'))[0], 'c')
        self.assertEqual(M.b0_branch(self.s(W, 'thư mục build /x KHÔNG tồn tại trên máy này; ...'))[0], 'b')

    def test_other_machine_or_unreadable_is_fail(self):
        for iid in ('i-04c817afe6511fb37', 'i-0other', 'None', ''):
            for concl in ('CHƯA TRÙNG HOÀN TOÀN (... máy KHÁC)', 'thư mục build /x KHÔNG tồn tại trên máy này', 'TRÙNG x'):
                self.assertEqual(M.b0_branch(self.s(iid, concl))[0], 'fail', (iid, concl))   # review R2-02: không bao giờ là (b)
        self.assertEqual(M.b0_branch(self.s(M.B0_INSTANCE, None))[0], 'fail')
        self.assertEqual(M.b0_branch('KẾT LUẬN: TRÙNG x\n')[0], 'fail')
        self.assertEqual(M.b0_branch(None)[0], 'fail')

    def test_decide(self):
        W = M.B0_INSTANCE
        a, c, other = self.s(W, 'TRÙNG x'), self.s(W, 'CHƯA TRÙNG HOÀN TOÀN'), self.s('i-0x', 'TRÙNG x')
        self.assertEqual(M.b0_decide(a, True, True, [('h', 'summary.txt', a)])[0], 'a')
        self.assertEqual(M.b0_decide(a, True, True, [('h', 'summary.txt', a), ('h', M.B0_RUNS, c)])[0], 'c')   # (c) cũ không bị thay
        self.assertEqual(M.b0_decide(other, True, True, [('h', M.B0_RUNS, c), ('h', M.B0_RUNS, other)])[0], 'c')
        self.assertEqual(M.b0_decide(a, False, True, [])[0], 'fail')                  # thiếu lịch sử
        self.assertEqual(M.b0_decide(a, True, False, [])[0], 'fail')                  # chạy trước commit amendment
        self.assertEqual(M.b0_decide(other, True, True, [])[0], 'fail')


@needs(os.path.exists(KEYS_FILE) and os.path.exists(WORKFLOW), 'đặt SUPP_KEYS tới keys.txt, SUPP_WORKFLOW tới runner-jobs.yml')
class B0History(unittest.TestCase):
    """Lệnh b0 trên remote thật với bố cục mà bước Publish thật tạo ra (R3-02): mỗi lần nộp là một commit trên commit nguồn, ở results/
    rq2-san-log hoặc results-failed/rq2-san-log-<run>. Một lần (c) ở bất kỳ ref nào là dừng; B0 phải chạy ở commit amendment hay hậu duệ."""
    def setUp(self):
        text = f'# Amendment\n\nkeys `{M.KEYS_SHA256}`\nS0 `{M.S0_SHA256}`\n'
        self.r = GitRemote(self, {'README': 'x\n'})
        self.before = self.r.head()
        os.makedirs(f'{self.r.work}/docs'); os.makedirs(os.path.dirname(f'{self.r.work}/{M.KEYS}'))
        open(f'{self.r.work}/{M.AMENDMENT}', 'w').write(text); shutil.copyfile(KEYS_FILE, f'{self.r.work}/{M.KEYS}')
        git(self.r.work, 'add', '-A'); git(self.r.work, 'commit', '-q', '-m', 'amendment'); git(self.r.work, 'push', '-q', 'origin', 'main')
        self.after = self.r.head()
        git(self.r.clone, 'pull', '-q', 'origin', 'main')
        self.run_id = 100

    def summ(self, concl, iid=M.B0_INSTANCE):
        return B0Branch.s(None, iid, concl)

    def put(self, summary, runs, source):
        """Một lần chạy B0: ci-out như script B0 ghi (runs None: không tải được lần trước, không ghi lịch sử), nộp bằng bước Publish thật."""
        self.run_id += 1
        d = tempfile.mkdtemp(dir=self.r.d); os.makedirs(f'{d}/{M.B0_JOB}')
        open(f'{d}/{M.B0_JOB}/summary.txt', 'w').write(summary); open(f'{d}/source-commit.txt', 'w').write(source + '\n')
        if runs is not None:
            open(f'{d}/{M.B0_JOB}/{M.B0_RUNS}', 'w').write(''.join(json.dumps(dict(summary=x)) + '\n' for x in runs))
        return publish_like_workflow(self.r, d, M.B0_JOB, self.run_id)

    def b0(self):
        return run_cli(['b0', '--keys', f'{self.r.clone}/{M.KEYS}'], cwd=self.r.clone)

    def test_a(self):
        a = self.summ('TRÙNG x'); self.assertEqual(self.put(a, [a], self.after), 'results/rq2-san-log')
        p = self.b0(); self.assertEqual(p.returncode, 0, p.stderr + p.stdout); self.assertTrue(p.stdout.startswith('a: '))
        self.assertIn('B0_COMMIT=', p.stdout)

    def test_c_in_runs_history_stops(self):
        a, c = self.summ('TRÙNG x'), self.summ('CHƯA TRÙNG HOÀN TOÀN')
        self.put(a, [c, a], self.after)
        self.assertEqual(self.b0().returncode, M.EXIT_STOP)

    def test_c_in_results_failed_stops(self):
        """R3-02: B0 lần 2 không tải được lịch sử và cho (c): guard đẩy sang results-failed/; lệnh b0 vẫn đọc tới và dừng."""
        a, c = self.summ('TRÙNG x'), self.summ('CHƯA TRÙNG HOÀN TOÀN')
        self.assertEqual(self.put(a, [a], self.after), 'results/rq2-san-log')
        self.assertEqual(self.put(c, None, self.after), f'results-failed/rq2-san-log-{self.run_id}')
        self.assertEqual(self.b0().returncode, M.EXIT_STOP)
        self.assertEqual(self.put(a, [a, a], self.after), 'results/rq2-san-log')     # lần sau đè đầu nhánh, không thay được (c)
        p = self.b0(); self.assertEqual(p.returncode, M.EXIT_STOP); self.assertIn('results-failed/rq2-san-log-', p.stderr)

    def test_fetch_error_is_fail(self):
        a = self.summ('TRÙNG x'); self.put(a, [a], self.after); self.put(a, None, self.after)
        real = M._git
        with mock.patch.object(M, '_git', side_effect=lambda repo, *x: subprocess.CompletedProcess(x, 1, '', 'lỗi giả')
                               if x[:1] == ('fetch',) and 'results-failed' in x[-1] else real(repo, *x)):
            with self.assertRaises(M.Refuse): M.b0_collect(self.r.clone)
        git(self.r.clone, 'remote', 'set-url', 'origin', f'{self.r.d}/khong-co.git')
        self.assertEqual(self.b0().returncode, 1)                                       # ls-remote lỗi: fail

    def test_fail_cases(self):
        self.assertEqual(self.b0().returncode, 1)                                       # chưa có B0
        a = self.summ('TRÙNG x')
        self.put(a, [a], self.before); self.assertEqual(self.b0().returncode, 1)        # B0 chạy trước commit amendment
        self.put(a, [a, a, a], self.after)
        self.assertEqual(self.b0().returncode, 0)
        o = self.summ('TRÙNG x', 'i-04c817afe6511fb37')
        self.put(o, [a, a, a, o], self.after); self.assertEqual(self.b0().returncode, 1)  # máy khác: fail, không là (b)


B0_SH = os.environ.get('B0_SH') or f'{REPO}/ci/jobs/rq2-san-log.sh'


@needs(os.path.exists(B0_SH), 'đặt B0_SH tới ci/jobs/rq2-san-log.sh')
class B0Script(unittest.TestCase):
    """Script B0 thật trên một clone có remote thật: dòng lịch sử được chép tiếp qua mỗi lần nộp; không tải được lần trước thì không ghi file
    lịch sử (guard của Publish giữ nhánh). curl bị stub để IMDS lỗi ngay; instance id lấy từ ci-out/runner-env.txt như dự phòng của script."""
    CASES = [l.strip().split('/')[-1] for l in open(KEYS_FILE)] if os.path.exists(KEYS_FILE) else []

    def setUp(self):
        self.r = GitRemote(self)
        self.bin = f'{self.r.d}/bin'; os.makedirs(self.bin)
        open(f'{self.bin}/curl', 'w').write('#!/bin/sh\nexit 7\n'); os.chmod(f'{self.bin}/curl', 0o755)
        self.build = f'{self.r.d}/home/build/rq2-main'

    def markers(self, n_sig):
        for kind in ('c-san', 'c'):
            d = f'{self.build}/{kind}/P01_sphincs_plus'; os.makedirs(d, exist_ok=True)
            for i, c in enumerate(self.CASES):
                log = ('ld.lld: error: relocation R_X86_64_PC32 against symbol SPX_fors_sign can not be used; recompile with -fPIC\n'
                       '>>> libsphincs_core.so\n') if i < n_sig else 'CMake Error: khác\n'
                json.dump(dict(ok=kind == 'c', log='' if kind == 'c' else log, preset='test'), open(f'{d}/{c}.build.json', 'w'))

    def run_b0(self, iid=M.B0_INSTANCE):
        cl = self.r.clone
        shutil.rmtree(f'{cl}/ci-out', True); os.makedirs(f'{cl}/ci-out')
        json.dump(dict(instance_id=iid, instance_type='c7i.2xlarge'), open(f'{cl}/ci-out/runner-env.txt', 'w'))
        p = subprocess.run(['bash', B0_SH], cwd=cl, capture_output=True, text=True,
                           env=dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}', HOME=f'{self.r.d}/home', RQ2_BUILD=self.build,
                                    GITHUB_RUN_ID='42', GITHUB_SHA=self.r.head()))
        self.assertEqual(p.returncode, 0, p.stderr)
        return f'{cl}/ci-out/rq2-san-log'

    def publish(self, run_id=7):
        """Nộp ci-out bằng bước Publish thật của workflow (guard NR > NL)."""
        cl = self.r.clone
        open(f'{cl}/ci-out/source-commit.txt', 'w').write(self.r.head() + '\n')
        return publish_like_workflow(self.r, f'{cl}/ci-out', M.B0_JOB, run_id)

    def test_history_carried(self):
        self.markers(30)
        out = self.run_b0(); self.assertEqual(M.b0_branch(open(f'{out}/summary.txt').read())[0], 'c')
        self.assertEqual(len(M.records(f'{out}/{M.B0_RUNS}')), 1)
        self.publish()
        self.markers(36)
        out = self.run_b0()
        runs = M.records(f'{out}/{M.B0_RUNS}')
        self.assertEqual([M.b0_branch(r['summary'])[0] for r in runs], ['c', 'a'])
        head = open(f'{out}/summary.txt').read()
        self.assertEqual(runs[1]['summary'], head); self.assertEqual(runs[1]['run_id'], '42'); self.assertEqual(M.b0_branch(head)[0], 'a')
        self.assertEqual(self.publish(8), 'results/rq2-san-log')
        hist = M.b0_collect(self.r.clone)['history']
        self.assertEqual([s for _, s, _ in hist].count(M.B0_RUNS), 2)
        self.assertEqual(M.b0_decide(head, True, True, hist)[0], 'c')                     # lần sau không thay được (c)

    def test_other_machine_and_unreachable_history(self):
        self.markers(36)
        out = self.run_b0('i-04c817afe6511fb37'); self.assertEqual(M.b0_branch(open(f'{out}/summary.txt').read())[0], 'fail')
        self.assertEqual(self.publish(8), 'results/rq2-san-log')
        git(self.r.clone, 'remote', 'set-url', 'origin', f'{self.r.d}/khong-co.git')
        self.markers(30)
        out = self.run_b0()
        self.assertFalse(os.path.exists(f'{out}/{M.B0_RUNS}'))                 # không tải được lần trước: không ghi lịch sử
        self.assertIn('KHÔNG tải được', open(f'{out}/summary.txt').read())
        git(self.r.clone, 'remote', 'set-url', 'origin', self.r.origin)
        self.assertEqual(self.publish(9), 'results-failed/rq2-san-log-9')      # guard giữ đầu nhánh; lần (c) nằm ở results-failed/
        self.assertEqual(M.b0_decide(None, True, True, M.b0_collect(self.r.clone)['history'])[0], 'c')


class SmokeAccept(unittest.TestCase):
    """Điều kiện từ job smoke cho job đầy đủ (mục 7 bước 4, 5), trên đúng bố cục ci-out/rq2-san-supp-smoke mà job smoke ghi."""
    KEY = 'codex-gpt54/P01_sphincs_plus/005_x'

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='acc-'); self.addCleanup(shutil.rmtree, self.d, True)
        os.makedirs(f'{self.d}/gate'); os.makedirs(f'{self.d}/run')
        json.dump(dict(ok=True), open(f'{self.d}/gate/smoke-gate.json', 'w'))
        open(f'{self.d}/{M.COMPLETE}', 'w').write('{}')
        self.manifest('i-0abc', 'a' * 40)
        self.pf = dict(amendment=dict(commit='a' * 40))
        self.mi = self.mach('i-0abc')
        self.put([self.ok_rec()])

    @staticmethod
    def mach(iid, **kw):
        return dict(dict(instance_id=iid, instance_type=M.ENV_REQ['instance_type'], ami_id=M.ENV_REQ['ami_id']), **kw)

    def manifest(self, iid, commit, env_ok=True, **kw):
        json.dump(dict(machine=dict(instance_id=None), params=dict(gates=dict(env=dict(ok=env_ok, machine=self.mach(iid, **kw)),
                                                                            amendment=dict(commit=commit)))),
                  open(f'{self.d}/run/manifest.json', 'w'))

    def ok_rec(self):
        return dict(key=self.KEY, outcome='behavioral_disagreement', reasons=[], reason=None, s0_outcome='not_re_examined',
                    supp=dict(try_no=1), vectors=[dict(san='no_report', san_attempts=1, san_markers=[], obs={})])

    def err_rec(self):
        return dict(key=f'{self.KEY}#error', status='harness_error', supp=dict(try_no=1))

    def put(self, recs):
        with open(f'{self.d}/run/{M.OUT_NAME}', 'w') as f:
            for r in recs: f.write(json.dumps(r) + '\n')

    def acc(self, mi=None):
        return M.smoke_accept(self.d, self.KEY, self.pf, mi if mi is not None else self.mi)[0]

    def test_ok(self):
        self.assertEqual(self.acc(), 'ok')

    def test_records(self):
        self.put([self.err_rec(), self.ok_rec()]); self.assertEqual(self.acc(), 'stop')      # smoke hoàn tất không có bản ghi lỗi
        self.put([self.ok_rec(), self.ok_rec()]); self.assertEqual(self.acc(), 'stop')
        self.put([]); self.assertEqual(self.acc(), 'stop')                                    # complete.json mà không có bản ghi
        os.remove(f'{self.d}/{M.COMPLETE}'); self.assertEqual(self.acc(), 'fail')             # job smoke chưa hoàn tất
        r = self.ok_rec(); del r['s0_outcome']; self.put([r]); open(f'{self.d}/{M.COMPLETE}', 'w').write('{}')
        self.assertEqual(self.acc(), 'stop')                                                  # luật 2: thiếu trường thì dừng

    def test_missing_manifest_or_gate_is_fail(self):
        """review R2-06: thiếu run/manifest.json hay gate/ là fail, không là stop."""
        os.remove(f'{self.d}/run/manifest.json')
        cls, why, _ = M.smoke_accept(self.d, self.KEY, self.pf, self.mi); self.assertEqual(cls, 'fail', why)
        self.manifest('i-0abc', 'a' * 40); shutil.rmtree(f'{self.d}/gate')
        self.assertEqual(self.acc(), 'fail')

    def test_other_instance_same_type_and_ami(self):
        """Le chốt 2026-11-06: instance khác job smoke, cùng loại máy và AMI: ok, lý do và thông tin ghi để công bố ở notes."""
        cls, why, info = M.smoke_accept(self.d, self.KEY, self.pf, self.mach('i-0other'))
        self.assertEqual(cls, 'ok', why); self.assertIn('máy khác job smoke', why); self.assertIn('công bố ở notes', why)
        self.assertEqual((info['different_instance'], info['instance_id'], info['smoke_instance_id']), (True, 'i-0other', 'i-0abc'))
        cls, why, info = M.smoke_accept(self.d, self.KEY, self.pf, self.mi)
        self.assertEqual((cls, why, info['different_instance']), ('ok', 'đạt', False))

    def test_other_type_or_ami_is_fail(self):
        """Loại máy hay AMI khác ENV_REQ (máy này hoặc manifest smoke), hoặc không đọc được: fail, cùng lớp với lệch môi trường ở preflight."""
        for kw in (dict(instance_type='m7i-flex.large'), dict(ami_id='ami-0other'), dict(instance_type=None), dict(ami_id=None)):
            self.assertEqual(self.acc(self.mach('i-0abc', **kw)), 'fail', kw)
            self.assertEqual(self.acc(self.mach('i-0other', **kw)), 'fail', kw)
            self.manifest('i-0abc', 'a' * 40, **kw); self.assertEqual(self.acc(), 'fail', kw)
            self.assertEqual(self.acc(self.mach('i-0other')), 'fail', kw)
            self.manifest('i-0abc', 'a' * 40)
        self.manifest('i-0abc', 'a' * 40, env_ok=False); self.assertEqual(self.acc(self.mach('i-0other')), 'fail')
        self.manifest('i-0abc', 'b' * 40, instance_type='m7i-flex.large'); self.assertEqual(self.acc(), 'stop')   # luật dừng thắng

    def test_machine_and_gate(self):
        self.assertEqual(self.acc(self.mach(None, imds_tries=5)), 'fail')
        self.manifest(None, 'a' * 40); self.assertEqual(self.acc(), 'fail')
        self.manifest('i-0abc', 'b' * 40); self.assertEqual(self.acc(), 'stop')                  # luật 3: commit amendment khác
        self.manifest('i-0abc', 'a' * 40)
        json.dump(dict(ok=False), open(f'{self.d}/gate/smoke-gate.json', 'w')); self.assertEqual(self.acc(), 'stop')

    @needs(os.path.exists(KEYS_FILE), 'đặt SUPP_KEYS tới keys.txt')
    def test_cli_exit_codes(self):
        repo = tempfile.mkdtemp(prefix='acc-repo-'); self.addCleanup(shutil.rmtree, repo, True)
        os.makedirs(os.path.dirname(f'{repo}/{M.KEYS}')); shutil.copyfile(KEYS_FILE, f'{repo}/{M.KEYS}')
        self.KEY = open(KEYS_FILE).readline().strip()
        pf = f'{self.d}/pf.json'; json.dump(self.pf, open(pf, 'w'))
        self.put([self.ok_rec(), self.ok_rec()])
        p = run_cli(['accept-smoke', '--keys', f'{repo}/{M.KEYS}', '--smoke-dir', self.d, '--preflight', pf])
        self.assertEqual(p.returncode, 3, p.stderr)
        os.remove(f'{self.d}/{M.COMPLETE}'); self.put([])
        self.assertEqual(run_cli(['accept-smoke', '--keys', f'{repo}/{M.KEYS}', '--smoke-dir', self.d, '--preflight', pf]).returncode, 1)


SH_STUB = r'''
set -euo pipefail
source "$LIB"
git() { if [ "$1" = ls-remote ]; then local j=${4#refs/heads/results/}; local v="LS_${j//-/_}"; return "${!v:-2}"; fi; command git "$@"; }
fr_fetch() { local j=$1 d=$2 v="FF_${1//-/_}"; [ "${!v:-ok}" = ok ] || return 1; mkdir -p "$d/ci-out/$j"; echo "c-$j"; }
'''


class Shell(unittest.TestCase):
    """Hàm shell của ci/rq2-san-supp-lib.sh với git, fr_fetch giả."""
    def sh(self, body, **env):
        d = tempfile.mkdtemp(prefix='sh-'); self.addCleanup(shutil.rmtree, d, True)
        p = subprocess.run(['bash', '-c', SH_STUB + body], capture_output=True, text=True,
                           env=dict(os.environ, LIB=LIB_SH, W=d, **env))
        return p.returncode, p.stdout, p.stderr, d

    def test_syntax(self):
        for f in (LIB_SH, JOB_SH, JOB_SH.replace('.sh', '-smoke.sh'), JOB_SH.replace('.sh', '-gate.sh')):
            self.assertEqual(subprocess.run(['bash', '-n', f]).returncode, 0, f)

    def test_branch_state(self):
        self.assertEqual(self.sh('sup_branch_state rq2-san-supp', LS_rq2_san_supp='0')[1].strip(), 'present')
        self.assertEqual(self.sh('sup_branch_state rq2-san-supp', LS_rq2_san_supp='2')[1].strip(), 'absent')
        self.assertEqual(self.sh('sup_branch_state rq2-san-supp', LS_rq2_san_supp='128')[0], 1)        # lỗi mạng khác "chưa có"

    def test_fetch_existing(self):
        rc, out, _, _ = self.sh('sup_fetch_existing rq2-san-supp "$W/x"', LS_rq2_san_supp='2'); self.assertEqual((rc, out.strip()), (0, ''))
        rc, out, _, _ = self.sh('sup_fetch_existing rq2-san-supp "$W/x"', LS_rq2_san_supp='0'); self.assertEqual((rc, out.strip()), (0, 'c-rq2-san-supp'))
        rc, _, _, _ = self.sh('sup_fetch_existing rq2-san-supp "$W/x"', LS_rq2_san_supp='0', FF_rq2_san_supp='bad'); self.assertEqual(rc, 1)

    def test_cls_exit_and_complete(self):
        out = self.sh('for x in 0 3 1 2 4 137; do sup_cls_exit $x; done')[1].split()
        self.assertEqual(out, ['ok', 'stop', 'fail', 'fail', 'fail', 'fail'])
        rc, _, err, d = self.sh('sup_complete "$W" smoke rq2-san-supp-smoke 2', GITHUB_RUN_ID='9')
        self.assertEqual(rc, 0, err); c = json.load(open(f'{d}/complete.json'))
        self.assertEqual((c['mode'], c['job'], c['attempt'], c['run_id']), ('smoke', 'rq2-san-supp-smoke', 2, '9'))


FAKE_MODULE = r'''
import json, os, subprocess, sys
cmd = sys.argv[1]
open(os.environ['CALLS'], 'a').write(cmd + '\n')
rc = int(os.environ.get('FAKE_RC_' + cmd.replace('-', '_'), '0'))
arg = lambda n: sys.argv[sys.argv.index(n) + 1] if n in sys.argv else None
if cmd == 'scan' and os.environ.get('REAL_SCAN') and 'FAKE_RC_scan' not in os.environ:
    # scan thật của module (git thật, remote thật), repo là thư mục job
    code = ('import os, sys, harness\n'
            'src = os.environ.get("RQ2_SAN_SUPP_SRC")\n'
            'if src and src not in harness.__path__: harness.__path__.append(src)\n'
            'from harness import rq2_san_supp as M\n'
            'M.main(sys.argv[1:], repo=os.environ["JOB_REPO"])\n')
    env = dict(os.environ, PATH=os.environ['ORIG_PATH'], PYTHONPATH=os.environ['REAL_REPO'], RQ2_SAN_SUPP_SRC=os.environ['REAL_SRC'],
               JOB_REPO=os.getcwd())
    sys.exit(subprocess.run([sys.executable, '-c', code] + sys.argv[1:], env=env, cwd=os.environ['REAL_REPO']).returncode)
if cmd == 'scan':
    if rc == 10: open(arg('--out') + '/noop.txt', 'w').write('đã hoàn tất\n')
    if rc == 0: print('{}'); print('ATTEMPT=' + os.environ.get('FAKE_ATTEMPT', '1'))
if cmd == 'b0' and rc == 0: print('a: TRÙNG x'); print('B0_COMMIT=deadbeef')
if cmd == 'run' and not os.environ.get('FAKE_RUN_PRE'):
    # như module thật: manifest rồi dòng lịch sử, trước khi giao key (FAKE_RUN_PRE: từ chối trước bước này)
    os.makedirs(arg('--out'), exist_ok=True); open(arg('--out') + '/manifest.json', 'w').write('{}')
    if arg('--history'):
        open(arg('--history'), 'a').write(json.dumps(dict(attempt=int(arg('--attempt')), run_id=os.environ.get('GITHUB_RUN_ID'),
                                                          run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT')), sort_keys=True) + '\n')
    if rc == 0:
        open(arg('--out') + '/rq2-san-supp-exe.jsonl', 'w').write(json.dumps(dict(key='k', outcome='behavioral_disagreement')) + '\n')
if rc == 3: print('DỪNG: giả', file=sys.stderr)
sys.exit(rc)
'''
FAKE_GATE = r'''
import json, os, sys
open(os.environ['CALLS'], 'a').write('smoke_gate\n')
rc = int(os.environ.get('FAKE_RC_gate', '0'))
if rc == 1: raise RuntimeError('lỗi đĩa giả')
out = sys.argv[sys.argv.index('--out') + 1]; os.makedirs(os.path.dirname(out), exist_ok=True); json.dump(dict(ok=rc == 0), open(out, 'w'))
sys.exit(rc)
'''
FAKE_GIT = r'''#!/usr/bin/env bash
case "$1" in
  rev-parse) echo deadbeefdeadbeef;;
  cat-file) exit 0;;
  fetch) exit "${FAKE_GIT_FETCH:-0}";;
  show) cat "$S0FILE";;
  ls-remote) j=${4#refs/heads/results/}; v="LS_${j//-/_}"; exit "${!v:-0}";;
  *) exit 0;;
esac
'''


@needs(HAVE_S0, 'đặt RQ2_EXE tới rq2-exe.jsonl (S₀; job kiểm sha256)')
class JobScript(unittest.TestCase):
    """Chạy ci/jobs/rq2-san-supp*.sh thật trong cây tạm: module harness, smoke_gate.py, git và các script ci/ đã freeze được thay bằng stub.
    Kiểm đường đi của job (review R2-03, R2-06, R2-12, R2-14, D1): STOP.txt, complete.json, noop.txt, dòng LỖI HẠ TẦNG, lần thử thứ hai."""
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='job-'); self.addCleanup(shutil.rmtree, self.d, True)
        R = f'{self.d}/repo'
        for p in ('ci/jobs', 'harness', 'experiments/37-rq2-san-supp/scripts', 'experiments/37-rq2-san-supp/data', 'bin', 'home'):
            os.makedirs(f'{R}/{p}' if p not in ('bin', 'home') else f'{self.d}/{p}')
        for f in ('rq2-san-supp.sh', 'rq2-san-supp-smoke.sh', 'rq2-san-supp-gate.sh'):
            shutil.copyfile(os.path.join(os.path.dirname(JOB_SH), f), f'{R}/ci/jobs/{f}')
        shutil.copyfile(LIB_SH, f'{R}/ci/rq2-san-supp-lib.sh')
        stubs = {'ci/fetch-results.sh': 'fr_fetch() { mkdir -p "$2/ci-out/$1"; [ ! -d "$FIX/$1" ] || cp -a "$FIX/$1/." "$2/ci-out/$1/"; echo "c-$1"; }\n'
                                        'fr_source() { echo src; }\n',
                 'ci/main-run-env.sh': 'mr_history() { :; }\nmr_machine() { :; }\n', 'ci/disk-guard.sh': 'dg_stop() { :; }\n',
                 'ci/mem-cgroup.sh': ':\n', 'ci/auto-shutdown.sh': 'echo auto-shutdown\n', 'harness/__init__.py': '',
                 'harness/rq2_san_supp.py': FAKE_MODULE, 'experiments/37-rq2-san-supp/scripts/smoke_gate.py': FAKE_GATE,
                 'experiments/37-rq2-san-supp/data/keys.txt': 'codex-gpt54/P01_sphincs_plus/005_x\n'}
        for p, t in stubs.items(): open(f'{R}/{p}', 'w').write(t)
        for name, t in (('git', FAKE_GIT), ('cmake', '#!/bin/sh\necho cmake version 3.28.3\n'), ('ninja', '#!/bin/sh\necho 1.11.1\n')):
            open(f'{self.d}/bin/{name}', 'w').write(t); os.chmod(f'{self.d}/bin/{name}', 0o755)
        self.R = R

    def job(self, which='smoke', **env):
        script = dict(smoke='ci/jobs/rq2-san-supp-smoke.sh', gate='ci/jobs/rq2-san-supp-gate.sh', full='ci/jobs/rq2-san-supp.sh')[which]
        job = dict(smoke='rq2-san-supp-smoke', gate='rq2-san-supp-gate', full='rq2-san-supp')[which]
        shutil.rmtree(f'{self.R}/ci-out', True); open(f'{self.d}/calls', 'w').close()
        base = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'RQ2_SAN_SUPP_SRC')}
        p = subprocess.run(['bash', script], cwd=self.R, capture_output=True, text=True,
                           env=dict(base, PATH=f'{self.d}/bin:{os.environ["PATH"]}', HOME=f'{self.d}/home', CALLS=f'{self.d}/calls',
                                    S0FILE=RQ2_EXE, FIX=f'{self.d}/fix', PYTHONDONTWRITEBYTECODE='1', ORIG_PATH=os.environ['PATH'],
                                    REAL_REPO=REPO, REAL_SRC=os.path.dirname(os.path.abspath(M.__file__)), **env))
        out = f'{self.R}/ci-out/{job}'
        ex = lambda f: os.path.exists(f'{out}/{f}')
        prov = open(f'{out}/provenance.txt').read() if ex('provenance.txt') else ''
        return dict(rc=p.returncode, stop=ex('STOP.txt'), complete=ex('complete.json'), noop=ex('noop.txt'), prov=prov, job=job,
                    calls=open(f'{self.d}/calls').read().split(), err=p.stderr + p.stdout, out=out)

    def test_smoke_ok(self):
        r = self.job()
        self.assertEqual(r['rc'], 0, r['err']); self.assertTrue(r['complete']); self.assertFalse(r['stop'])
        self.assertEqual(r['calls'], ['scan', 'check', 'b0', 'orig', 'build', 'smoke_gate', 'run'])

    def test_gate_mode(self):
        r = self.job('gate'); self.assertEqual(r['rc'], 0, r['err']); self.assertTrue(r['complete'])
        self.assertNotIn('run', r['calls'])

    def test_build_failure_goes_to_gate(self):
        """review R2-03: build có case lỗi (mã 4) thì cổng xếp S-pic; cổng không đạt (mã 3) là luật dừng."""
        r = self.job(FAKE_RC_build='4', FAKE_RC_gate='3')
        self.assertTrue(r['stop']); self.assertNotEqual(r['rc'], 0); self.assertEqual(r['calls'][-1], 'smoke_gate')

    def test_build_refusal_is_fail(self):
        """review R2-03: preflight của build từ chối (mã 1) là fail qua on_rc, không đi tới cổng, không STOP."""
        r = self.job(FAKE_RC_build='1')
        self.assertFalse(r['stop']); self.assertNotEqual(r['rc'], 0); self.assertNotIn('smoke_gate', r['calls'])
        self.assertIn('LỖI HẠ TẦNG', r['prov']); self.assertFalse(r['complete'])
        r = self.job(FAKE_RC_build='3'); self.assertTrue(r['stop'])

    def test_gate_crash_is_fail(self):
        """review R2-12: smoke_gate.py crash (mã 1) là fail, không ghi STOP."""
        r = self.job(FAKE_RC_gate='1')
        self.assertFalse(r['stop']); self.assertNotEqual(r['rc'], 0); self.assertIn('smoke_gate.py lỗi', r['prov'])

    def test_run_refusal_logged(self):
        """review R2-14: run trả mã 1 thì provenance có dòng LỖI HẠ TẦNG; mã 3 thì STOP."""
        r = self.job(FAKE_RC_run='1')
        self.assertFalse(r['stop']); self.assertFalse(r['complete']); self.assertIn('LỖI HẠ TẦNG', r['prov'])
        r = self.job(FAKE_RC_run='3'); self.assertTrue(r['stop'])

    def test_second_attempt_failure_writes_stop(self):
        """Le chốt vòng 4 (R3-03): chỉ lần thử đã tới bước thực thi (run/manifest.json) mới được tính; lần thử thứ hai đã tính mà không hoàn
        tất thì ghi STOP.txt khi thoát. Bị từ chối trước bước thực thi (scan, check, b0, cổng, run từ chối sớm) thì không STOP."""
        r = self.job(FAKE_ATTEMPT='2', FAKE_RC_run='1')
        self.assertTrue(r['stop']); self.assertIn('lần thử thứ 2', r['prov']); self.assertEqual(len(M.records(f'{r["out"]}/{M.RUNS}')), 1)
        for k in ('FAKE_RC_check', 'FAKE_RC_b0', 'FAKE_RC_gate', 'FAKE_RC_orig'):
            r = self.job(FAKE_ATTEMPT='2', **{k: '1'})
            self.assertFalse(r['stop'], k); self.assertIn('không tính là lần thử', r['prov'], k)
        r = self.job(FAKE_ATTEMPT='2', FAKE_RC_run='1', FAKE_RUN_PRE='1')
        self.assertFalse(r['stop']); self.assertFalse(os.path.exists(f'{r["out"]}/{M.RUNS}'))
        r = self.job(FAKE_ATTEMPT='2'); self.assertTrue(r['complete']); self.assertFalse(r['stop'])
        r = self.job(FAKE_ATTEMPT='1', FAKE_RC_run='1'); self.assertFalse(r['stop']); self.assertIn('lần thử 1 không hoàn tất', r['prov'])
        r = self.job('gate', FAKE_ATTEMPT='5', FAKE_RC_gate='1'); self.assertFalse(r['stop'])          # gate không giới hạn lần thử

    def test_scan_outcomes(self):
        """scan noop: thoát 0; scan stop: STOP; scan lỗi (ls-remote, fetch): bị từ chối trước bước thực thi, không tính, không STOP, không ghi
        lịch sử (R3-01 i đã đóng: lần sau đếm theo lần thử đã tính, test_attempt_sequence_real_scan)."""
        r = self.job(FAKE_RC_scan='10')
        self.assertEqual(r['rc'], 0, r['err']); self.assertTrue(r['noop']); self.assertEqual(r['calls'], ['scan']); self.assertFalse(r['stop'])
        r = self.job(FAKE_RC_scan='3'); self.assertTrue(r['stop']); self.assertEqual(r['calls'], ['scan'])
        r = self.job(FAKE_RC_scan='1', FAKE_ATTEMPT='2')
        self.assertFalse(r['stop']); self.assertIn('không tính là lần thử', r['prov']); self.assertEqual(r['calls'], ['scan'])
        self.assertFalse(os.path.exists(f'{r["out"]}/{M.RUNS}'))

    def test_attempt_sequence_real_scan(self):
        """E2 (R3-01): scan thật trên remote thật, nộp bằng bước Publish thật. (B) Lần thử 1 đã nộp, rồi một lần scan lỗi, rồi một lần bị từ
        chối ở check: lần chạy kế là lần thử 2, không STOP. (A) Lần thử 1 đã nộp, lần thử 2 tới thực thi rồi chết không nộp được (khai báo
        SUPP_ATTEMPT=3), rồi một lần scan lỗi: lần chạy kế sẽ là lần thử thứ ba nên dừng. (A') Lần thử 2 đã nộp mà mất STOP.txt (job bị kill),
        rồi một lần scan lỗi: lần chạy kế dừng."""
        def setup():
            rem = GitRemote(self)
            shutil.rmtree(f'{self.R}/.git', True); git(self.R, 'init', '-q'); git(self.R, 'remote', 'add', 'origin', rem.origin)
            return rem
        def go(rem, which, rid, drop_stop=False, **env):
            r = self.job(which, REAL_SCAN='1', GITHUB_RUN_ID=str(rid), GITHUB_RUN_ATTEMPT='1', **env)
            if drop_stop and r['stop']: os.remove(f'{r["out"]}/STOP.txt')
            r['dest'] = publish_like_workflow(rem, f'{self.R}/ci-out', r['job'], rid)
            return r
        os.makedirs(f'{self.d}/fix/rq2-san-supp-smoke', exist_ok=True)
        rem = setup()                                                                       # (B)
        r = go(rem, 'smoke', 101, FAKE_RC_run='1'); self.assertFalse(r['stop']); self.assertEqual(r['dest'], 'results/rq2-san-supp-smoke')
        r = go(rem, 'smoke', 102, FAKE_RC_scan='1'); self.assertEqual(r['dest'], 'results-failed/rq2-san-supp-smoke-102')   # 0 dòng: không đè
        r = go(rem, 'smoke', 103, FAKE_RC_check='1'); self.assertFalse(r['stop']); self.assertIn('không tính là lần thử', r['prov'])
        r = go(rem, 'smoke', 104); self.assertTrue(r['complete'], r['err']); self.assertFalse(r['stop']); self.assertIn('lần thử 2', r['prov'])
        self.assertIn('đã tính [1]', open(f'{r["out"]}/scan.txt').read())                     # scan thật đếm đúng một lần thử đã tính
        rem = setup()                                                                       # (A)
        go(rem, 'full', 201, FAKE_RC_run='1')
        r = go(rem, 'full', 202, FAKE_RC_scan='1'); self.assertTrue(r['dest'].startswith('results-failed/'))
        r = go(rem, 'full', 203, SUPP_ATTEMPT='3'); self.assertTrue(r['stop']); self.assertEqual(r['calls'], ['scan'])
        rem = setup()                                                                       # (A')
        go(rem, 'full', 301, FAKE_RC_run='1')
        r = go(rem, 'full', 302, FAKE_RC_run='1', drop_stop=True); self.assertFalse(os.path.exists(f'{r["out"]}/STOP.txt'))
        go(rem, 'full', 303, FAKE_RC_scan='1')
        r = go(rem, 'full', 304); self.assertTrue(r['stop']); self.assertIn('lần thử thứ 3', r['prov'])

    def test_preflight_classes(self):
        r = self.job(FAKE_RC_check='3'); self.assertTrue(r['stop']); self.assertEqual(r['calls'], ['scan', 'check'])
        r = self.job(FAKE_RC_check='1'); self.assertFalse(r['stop']); self.assertIn('LỖI HẠ TẦNG', r['prov'])

    def test_b0_missing_or_tag_fetch_error_is_fail(self):
        r = self.job(FAKE_RC_b0='1'); self.assertFalse(r['stop']); self.assertIn('LỖI HẠ TẦNG', r['prov']); self.assertNotIn('orig', r['calls'])
        r = self.job(FAKE_GIT_FETCH='1'); self.assertFalse(r['stop']); self.assertNotEqual(r['rc'], 0)
        r = self.job(FAKE_RC_b0='3'); self.assertTrue(r['stop'])

    def test_full(self):
        os.makedirs(f'{self.d}/fix/rq2-san-supp-smoke')
        r = self.job('full')
        self.assertEqual(r['rc'], 0, r['err']); self.assertTrue(r['complete'])
        self.assertEqual(r['calls'], ['scan', 'check', 'accept-smoke', 'run'])
        r = self.job('full', **{'FAKE_RC_accept_smoke': '1'}); self.assertFalse(r['stop']); self.assertNotIn('run', r['calls'])
        r = self.job('full', **{'FAKE_RC_accept_smoke': '3'}); self.assertTrue(r['stop'])
        r = self.job('full', LS_rq2_san_supp_smoke='2'); self.assertFalse(r['stop']); self.assertIn('chưa có results/rq2-san-supp-smoke', r['prov'])


def s0_targets():
    recs = [json.loads(l) for l in open(RQ2_EXE)]
    return recs, sorted((r for r in recs if M.TARGET_REASON in (r.get('reasons') or [])), key=lambda r: r['key'])


class FakeCorpus:
    """Thư mục tạm thay T (vector dựng lại từ trường input của bản ghi) và B (marker giả cho kiểm 'đã cache')."""
    def __init__(self, tc, targets, stdin_override=None, override_keys=None):
        self.d = tempfile.mkdtemp(prefix='supp-c-'); tc.addCleanup(shutil.rmtree, self.d, True)
        self.T, self.B = f'{self.d}/T', f'{self.d}/B'
        for r in targets:
            for v in r['vectors']:
                p = f'{self.T}/{r["bundle"]}/{r["case"]}/test_vectors'; os.makedirs(p, exist_ok=True)
                st = v['input']
                assert not st['argv'] and st['stdin']['len'] == 0, 'test dựng vector rỗng; dữ liệu đã đổi'
                bad = stdin_override and (override_keys is None or r['key'] in override_keys)
                json.dump(dict(argv=[], stdin=stdin_override if bad else '', env=st['env']), open(f'{p}/{v["vector"]}', 'w'))
            wd = f'{self.B}/c-san/{r["bundle"]}/{r["case"]}'; os.makedirs(f'{wd}/build-ninja', exist_ok=True)
            open(f'{wd}.build.json', 'w').write('{}'); open(f'{wd}/build-ninja/driver', 'w').write(r['case'])
        self.cs = dict(ok=True, bin='/nonexistent/driver', sha256='0' * 64, preset='test', secs=1.0)


@needs(HAVE_S0, 'đặt RQ2_EXE tới rq2-exe.jsonl (S₀)')
class OutcomesOnS0(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs, cls.targets = s0_targets()
        cls.keys = [r['key'] for r in cls.targets]

    def setUp(self):
        M.install_pic(); self.addCleanup(setattr, BD, 'SAN_FLAGS_EXE', CF.SAN_FLAGS_EXE)
        self.fc = FakeCorpus(self, self.targets)

    def run_all(self, status, calls=None, targets=None):
        out = {}
        with mock.patch.object(BD, 'build_c_exe', return_value=self.fc.cs):
            for r in targets or self.targets: out[r['key']] = M.supp_key(self.fc.B, r, san_fn=fake_san(status, calls), troot=self.fc.T)
        return out

    def test_keys_mechanical(self):
        self.assertEqual(len(self.keys), 36)
        if os.path.exists(KEYS_FILE): self.assertEqual(self.keys, [l.strip() for l in open(KEYS_FILE) if l.strip()])
        import hashlib
        self.assertEqual(hashlib.sha256(''.join(k + '\n' for k in self.keys).encode()).hexdigest(), M.KEYS_SHA256)
        s0, info = M.load_s0(RQ2_EXE, self.keys)
        self.assertEqual(sorted(s0), self.keys); self.assertEqual(info['sha256'], M.S0_SHA256)

    def test_load_s0_refuses(self):
        with self.assertRaises(SystemExit): M.load_s0(RQ2_EXE, self.keys, want='0' * 64)
        with self.assertRaises(SystemExit): M.load_s0(RQ2_EXE, self.keys[1:])

    @needs(os.path.exists(BOUND_PY), 'đặt BOUND_PY tới bound.py của exp 38')
    def test_outcomes_equal_exp38_scenarios(self):
        B38 = load_bound()
        for status in ('no_report', 'ub', 'inconclusive', 'infra'):
            got = self.run_all(status)
            for r in self.targets:
                o, rs, vos = B38.outcome_under(R2, r, status)
                n = got[r['key']]
                self.assertEqual((n['outcome'], n['reasons']), (o, rs), (status, r['key']))
                self.assertEqual([(v['outcome'], v['reason']) for v in n['vectors']], [tuple(x) for x in vos])
                self.assertEqual(n['reason'], R2.primary_reason(o, rs))
            c = collections.Counter((n['outcome'], n['reason']) for n in got.values())
            want = dict(no_report=('behavioral_disagreement', None), ub=('not_adjudicable', 'ub_in_c'),
                        inconclusive=('not_adjudicable', 'sanitizer_inconclusive'),
                        infra=('not_re_examined', 'incomplete_harness_run:san_infra'))[status]
            self.assertEqual(c, {want: 36}, status)
            self.assertNotIn('behavioral_agreement', {n['outcome'] for n in got.values()})

    def test_exe_san_arguments(self):
        calls = []
        self.run_all('no_report', calls)
        self.assertEqual(len(calls), 36)
        by = {r['key']: r for r in self.targets}
        for c, r in zip(calls, self.targets):
            self.assertIs(c['cs'], self.fc.cs)
            self.assertEqual((c['argv'], c['stdin'], c['env']), ([], '', None))
            self.assertEqual(c['timeout'], by[r['key']]['timeout'])           # timeout theo case của S₀, không nhân
            self.assertEqual(c['timeout'] * R1.SAN_TIMEOUT_FACTOR, r['vectors'][0]['san_timeout'])
            self.assertEqual(c['c_status'], 'exit'); self.assertIsInstance(c['sink'], list)

    def test_c_status_is_c_side_of_first_rep(self):
        """review L10: cả 36 có trạng thái C và Rust đều exit, nên lấy nhầm phía Rust vẫn qua test trên. Bản sao đổi trạng thái để phân biệt."""
        ts = copy.deepcopy(self.targets[:4])
        for i, r in enumerate(ts):
            e = r['vectors'][0]['obs']['runs']
            if i % 2 == 0: e[0]['first']['r']['status'] = 'signal'                   # phía Rust khác: c_status vẫn exit
            else: e[0]['first']['c']['status'] = 'signal'                            # phía C khác ở rep 1
            if i == 3: e[1]['first']['c']['status'] = 'exit'
        calls = []
        self.run_all('no_report', calls, ts)
        self.assertEqual([c['c_status'] for c in calls], ['exit', 'signal', 'exit', 'signal'])

    def test_record_fields(self):
        got = self.run_all('inconclusive')
        for r in self.targets:
            n, v0 = got[r['key']], r['vectors'][0]
            v = n['vectors'][0]
            self.assertEqual(n['key'], r['key'])
            self.assertEqual(json.dumps(v['obs']['runs'], sort_keys=True), json.dumps(v0['obs']['runs'], sort_keys=True))
            for k in ('runs', 'c_stable', 'input', 'c_out', 'r_out', 'c_err', 'r_err', 'orig', 'san_timeout', 'has_ub'):
                self.assertEqual(v[k], v0[k], k)
            self.assertEqual((v['san'], v['san_attempts'], v['san_cause']), ('inconclusive', 1, None))
            self.assertEqual(len(v['obs']['san']['attempts']), 1)
            a = v['obs']['san']['attempts'][0]
            self.assertEqual(R2.dec_obs(a['obs'], 'exe')['err'], b'fake inconclusive')   # mã hoá như examine_vector
            self.assertEqual(v['would_be'], 'supports_rejection')
            self.assertEqual(tuple(R2.recompute_vector(v, 'exe')), (v['outcome'], v['reason']))
            self.assertEqual(v['s0']['reason'], 'san_build_failed')
            self.assertEqual((n['s0_outcome'], n['s0_reasons']), ('not_re_examined', [M.TARGET_REASON]))
            self.assertEqual(n['supp']['san_flags_exe'], FROZEN_LITERAL + [M.PIC_FLAG])
            self.assertEqual(n['supp']['build']['files'], {'build-ninja/driver': M.sha_file(f'{self.fc.B}/c-san/{r["bundle"]}/{r["case"]}/build-ninja/driver')})
            self.assertTrue(n['c_san_ok'])
            json.dumps(n)                                                        # ghi được vào JSONL

    def test_real_exe_san_on_failed_build_reproduces_s0(self):
        """build PIC vẫn lỗi: _exe_san đã freeze trả infra/c_san_build_failed, không thực thi gì; kết quả trùng S₀."""
        with mock.patch.object(BD, 'build_c_exe', return_value=dict(ok=False, bin=None)), \
             mock.patch.object(R1.OB, 'run_exe', side_effect=AssertionError('không được thực thi')):
            for r in self.targets:
                n = M.supp_key(self.fc.B, r, troot=self.fc.T)
                self.assertEqual((n['outcome'], n['reasons'], n['reason']), (r['outcome'], r['reasons'], r['reason']))

    def test_inputs_check_in_preflight(self):
        """Lệch input của bất kỳ key nào bị bắt ở preflight (không chạy gì), là luật dừng; file vector không đọc được là fail (R2-05)."""
        s0, _ = M.load_s0(RQ2_EXE, self.keys)
        self.assertTrue(M.inputs_check(s0, self.fc.T)['ok'])
        fc = FakeCorpus(self, self.targets, stdin_override='x', override_keys={self.keys[20]})
        r = M.inputs_check(s0, fc.T); self.assertFalse(r['ok']); self.assertIn('InputMismatch', r['bad'][0]); self.assertEqual(r['unreadable'], [])
        bad = copy.deepcopy(s0); bad[self.keys[3]]['vectors'][0]['san_timeout'] += 1
        self.assertFalse(M.inputs_check(bad, self.fc.T)['ok'])
        a = M.build_parser().parse_args(['check', '--s0', RQ2_EXE]); a.keys = KEYS_FILE
        kc = dict(ok=True, reason='ok', keys=self.keys)

        def pf(corpus):
            with mock.patch.object(M, 'keys_check', return_value=kc), mock.patch.object(M, 'amendment_check', return_value=OK), \
                 mock.patch('harness.main_run.freeze_check', return_value=OK), mock.patch.object(M, 'env_check', return_value=OK), \
                 mock.patch.object(M, 'tractor_check', return_value=OK), mock.patch.object(M, 'deadline_check', return_value=OK), \
                 mock.patch.object(CF, 'T', corpus.T):
                return M.preflight(REPO, a)
        g = pf(fc)
        self.assertEqual(g['failed'], ['inputs']); self.assertEqual(M.classify(g), 'stop')
        with self.assertRaises(M.Stop): M.require(g)
        fu = FakeCorpus(self, self.targets)
        r0 = self.targets[5]; os.remove(f'{fu.T}/{r0["bundle"]}/{r0["case"]}/test_vectors/{r0["vectors"][0]["vector"]}')
        r = M.inputs_check(s0, fu.T); self.assertEqual((r['bad'], len(r['unreadable'])), ([], 1))
        g = pf(fu)
        self.assertEqual(g['failed'], ['vector_files']); self.assertEqual(M.classify(g), 'fail')      # R2-05: không đọc được là fail
        with self.assertRaises(M.Refuse) as e: M.require(g)
        self.assertNotIsInstance(e.exception, M.Stop)
        open(f'{fu.T}/{r0["bundle"]}/{r0["case"]}/test_vectors/{r0["vectors"][0]["vector"]}', 'w').write('{không phải json')
        r = M.inputs_check(s0, fu.T); self.assertEqual((len(r['bad']), r['unreadable']), (1, []))   # đọc được mà hỏng: lệch, dừng

    def test_safe_key_does_not_swallow_input_mismatch(self):
        fc = FakeCorpus(self, self.targets[:1], stdin_override='x')
        with mock.patch.object(BD, 'build_c_exe', return_value=fc.cs), mock.patch.object(CF, 'T', fc.T):
            with self.assertRaises(M.InputMismatch): M._safe_key(fc.B, self.targets[0], dict(try_no=1))
            with mock.patch.object(R1, '_exe_san', side_effect=ValueError('lỗi module')), mock.patch.object(CF, 'T', self.fc.T):
                r = M._safe_key(self.fc.B, self.targets[0], dict(try_no=1))
        self.assertEqual((r['status'], r['key'], r['supp']['try_no']), ('harness_error', self.keys[0] + '#error', 1))

    def test_requires_cached_build(self):
        r = self.targets[0]
        os.remove(f'{self.fc.B}/c-san/{r["bundle"]}/{r["case"]}.build.json')
        with mock.patch.object(BD, 'build_c_exe', side_effect=AssertionError('không được build')):
            with self.assertRaises(RuntimeError): M.supp_key(self.fc.B, r, san_fn=fake_san('no_report'), troot=self.fc.T)

    # ---- cmd_run đầu cuối với executor đồng bộ
    def _ctx(self, out, calls, san=None, deadline=None, corpus=None, supp_key=None):
        g = dict(ok=True, failed=[], keys=dict(ok=True, keys=self.keys), amendment=dict(ok=True, commit='c' * 40),
                 env=dict(ok=True, machine=dict(instance_id='i-0abc')))
        mf = lambda o, p: json.dump(dict(params=p), open(f'{o}/manifest.json', 'w'))
        st = contextlib_exit()
        cms = [mock.patch.object(M, 'preflight', return_value=g), mock.patch.object(M, 'manifest', side_effect=mf),
               mock.patch.object(M, 'ProcessPoolExecutor', FakeEx), mock.patch.object(BD, 'build_c_exe', return_value=self.fc.cs),
               mock.patch.object(R1, '_exe_san', san or fake_san('no_report', calls)), mock.patch.object(CF, 'T', (corpus or self.fc).T),
               mock.patch.object(M, 'deadline_check', side_effect=deadline or (lambda now=None: dict(OK, now_utc='t')))]
        if supp_key: cms.append(mock.patch.object(M, 'supp_key', side_effect=supp_key))
        for cm in cms: st.enter_context(cm)
        return st

    def _base(self, out):
        keysf = f'{out}/keys.txt'; open(keysf, 'w').write(''.join(k + '\n' for k in self.keys))
        return ['run', '--s0', RQ2_EXE, '--keys', keysf, '--build-root', self.fc.B, '--gate-json', gate_file(out, self.keys)]

    def _out(self):
        out = tempfile.mkdtemp(prefix='supp-out-'); self.addCleanup(shutil.rmtree, out, True); return out

    def test_cmd_run_smoke_then_full(self):
        """smoke chạy key đầu, full chạy 35 key còn lại; mỗi job một đoạn: thư mục ra đã có bản ghi thì từ chối (không chạy lại key nào)."""
        out = self._out(); calls = []
        BD.SAN_FLAGS_EXE = CF.SAN_FLAGS_EXE                                       # cmd_run phải tự gán
        base = self._base(out)
        with self._ctx(out, calls):
            M.main(base + ['--out', f'{out}/smoke', '--smoke'])
            self.assertEqual(len(calls), 1); self.assertIs(FakeEx.seen[-1], M.install_pic)
            M.main(base + ['--out', f'{out}/full', '--full', '--attempt', '1', '--history', f'{out}/full-runs.jsonl'])
            self.assertEqual(len(calls), 36)
            with self.assertRaises(M.Refuse):                                                             # đã có bản ghi: không chạy lại
                M.main(base + ['--out', f'{out}/full', '--full', '--attempt', '2', '--history', f'{out}/full-runs.jsonl'])
            self.assertEqual(len(M.records(f'{out}/full-runs.jsonl')), 1)       # từ chối trước manifest: không thêm dòng lịch sử
            self.assertEqual(len(calls), 36)
            with self.assertRaises(SystemExit): M.main(base + ['--out', f'{out}/full2', '--full', '--workers', '2'])
            bad_gate = gate_file(tempfile.mkdtemp(dir=out), self.keys, ok=False)
            with self.assertRaises(SystemExit): M.main(base[:-1] + [bad_gate, '--out', f'{out}/full3', '--full'])
        sm = M.records(f'{out}/smoke/{M.OUT_NAME}'); fu = M.records(f'{out}/full/{M.OUT_NAME}')
        self.assertEqual([r['key'] for r in sm], self.keys[:1])
        self.assertEqual(sorted(r['key'] for r in fu), self.keys[1:])
        self.assertTrue(all(r['outcome'] == 'behavioral_disagreement' for r in sm + fu))
        m = json.load(open(f'{out}/full/manifest.json'))
        self.assertEqual(m['params']['san_flags_exe'], FROZEN_LITERAL + [M.PIC_FLAG]); self.assertEqual(m['late'], [])
        self.assertTrue(all(r['supp']['instance_id'] == 'i-0abc' and r['supp']['amendment_commit'] == 'c' * 40 for r in fu))
        # Le chốt vòng 4 (R3-08): sha256 module trong manifest, trong mọi bản ghi, và trong dòng lịch sử của lần thử
        self.assertEqual(m['params']['module_sha256'], M.module_sha()); self.assertEqual(m['params']['attempt'], 1)
        self.assertIn('smoke_gate_sha256', m['params'])
        self.assertEqual({r['supp']['module_sha256'] for r in sm + fu}, {M.module_sha()})
        h = M.records(f'{out}/full-runs.jsonl')[0]
        self.assertEqual((h['attempt'], h['module_sha256'], h['job']), (1, M.module_sha(), M.JOBS['full']))
        self.assertFalse(os.path.exists(f'{out}/full/segments')); self.assertFalse(os.path.exists(f'{out}/full/attempts.jsonl'))

    def _flaky(self, bad):
        """supp_key thật, nhưng key trong `bad` lỗi module ở các lần thử ghi trong bad[key]."""
        real, n = M.supp_key, collections.Counter()

        def f(B, rec, ctx=None, **kw):
            n[rec['key']] += 1
            if n[rec['key']] in bad.get(rec['key'], ()): raise ValueError(f'lỗi module giả lần {n[rec["key"]]}')
            return real(B, rec, ctx=ctx, **kw)
        return f, n

    def test_full_retries_harness_error_once_in_job(self):
        """mục 7 bước 5 (Le chốt vòng 3): key harness_error chạy lại một lần trong cùng job; hai lần thì là bản ghi cuối (supp_harness_error)."""
        out = self._out(); calls = []; k1, k2 = self.keys[3], self.keys[9]
        f, n = self._flaky({k1: (1,), k2: (1, 2)})
        with self._ctx(out, calls, supp_key=f):
            M.main(self._base(out) + ['--out', f'{out}/full', '--full'])                 # xong (mã 0): mọi key có bản ghi cuối
        self.assertEqual((n[k1], n[k2]), (2, 2))
        recs = M.records(f'{out}/full/{M.OUT_NAME}')
        by = collections.Counter(r['key'] for r in recs)
        self.assertEqual((by[k1 + '#error'], by[k1], by[k2 + '#error'], by[k2]), (1, 1, 2, 0))
        self.assertEqual(len(calls), 34)                                                 # 33 key một lần, k1 lần thử thứ hai
        self.assertEqual(sorted(r['supp']['try_no'] for r in recs if M.base_key(r['key']) == k2), [1, 2])
        self.assertEqual(json.load(open(f'{out}/full/manifest.json'))['harness_error_tries'], {k1: 1, k2: 2})

    def test_smoke_harness_error_is_failed_attempt(self):
        """Job smoke không chạy lại trong job: harness_error của key smoke là lần thử không hoàn tất (mã 1, lớp fail)."""
        out = self._out(); calls = []
        f, n = self._flaky({self.keys[0]: (1, 2)})
        with self._ctx(out, calls, supp_key=f):
            with self.assertRaises(M.Refuse) as e: M.main(self._base(out) + ['--out', f'{out}/smoke', '--smoke'])
        self.assertNotIsInstance(e.exception, M.Stop); self.assertEqual(n[self.keys[0]], 1)
        self.assertEqual([r['key'] for r in M.records(f'{out}/smoke/{M.OUT_NAME}')], [self.keys[0] + '#error'])

    def test_broken_pool_is_failed_attempt(self):
        """Pool hỏng lúc giao key hoặc khi lấy kết quả: lần thử của job không hoàn tất (Refuse, mã 1), không bản ghi giả nào."""
        from concurrent.futures.process import BrokenProcessPool
        for where in ('submit', 'result'):
            out = self._out(); calls = []; n = [0]

            class Ex(FakeEx):
                def submit(self, fn, *a):
                    n[0] += 1
                    if n[0] == 3 and where == 'submit': raise BrokenProcessPool('pool hỏng')
                    f = super().submit(fn, *a)
                    if n[0] == 3:
                        f = Future(); f.set_exception(BrokenProcessPool('worker chết'))
                    return f
            with self._ctx(out, calls), mock.patch.object(M, 'ProcessPoolExecutor', Ex):
                with self.assertRaises(M.Refuse) as e: M.main(self._base(out) + ['--out', f'{out}/full', '--full'])
            self.assertNotIsInstance(e.exception, M.Stop)
            self.assertEqual(len(M.records(f'{out}/full/{M.OUT_NAME}')), dict(submit=2, result=5)[where], where)   # 6 worker: 5 key khác đã xong
            self.assertIn('BrokenProcessPool', json.load(open(f'{out}/full/manifest.json'))['broken'])

    def test_deadline_checked_before_each_submit(self):
        """Hạn chót tới giữa job thì không giao thêm key, thoát mã luật dừng."""
        out = self._out(); calls = []; n = [0]

        def dl(now=None):
            n[0] += 1
            return dict(ok=n[0] <= 5, now_utc='t', reason='ok' if n[0] <= 5 else 'đã quá hạn chót')
        with self._ctx(out, calls, deadline=dl):
            with self.assertRaises(SystemExit) as e: M.main(self._base(out) + ['--out', f'{out}/full', '--full'])
        self.assertEqual(e.exception.code, M.EXIT_STOP)
        self.assertEqual(len(calls), 5); self.assertEqual(len(M.records(f'{out}/full/{M.OUT_NAME}')), 5)

    def test_record_after_deadline_stops(self):
        """Le chốt vòng 3 (D3c): bản ghi giao trước hạn mà xong sau hạn chót làm lượt dừng."""
        out = self._out(); calls = []
        with self._ctx(out, calls), mock.patch.object(M, 'DEADLINE_UTC', '2000-01-01T00:00:00Z'):
            with self.assertRaises(M.Stop) as e: M.main(self._base(out) + ['--out', f'{out}/smoke', '--smoke'])
        self.assertIn('sau hạn chót', str(e.exception))

    def test_input_mismatch_during_run_stops(self):
        """Lệch input phát hiện trong `run` là luật dừng (mã 3), không thành bản ghi harness_error chạy lại được."""
        out = self._out(); calls = []
        fc = FakeCorpus(self, self.targets, stdin_override='x', override_keys={self.keys[2]})
        with self._ctx(out, calls, corpus=fc):
            with self.assertRaises(SystemExit) as e: M.main(self._base(out) + ['--out', f'{out}/full', '--full'])
        self.assertEqual(e.exception.code, M.EXIT_STOP)
        recs = M.records(f'{out}/full/{M.OUT_NAME}')
        self.assertFalse([r for r in recs if r.get('status') == 'harness_error'])
        self.assertNotIn(self.keys[2], {r['key'] for r in recs})


def contextlib_exit():
    import contextlib
    return contextlib.ExitStack()


if __name__ == '__main__':
    unittest.main()
