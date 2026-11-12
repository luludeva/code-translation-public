"""Kiểm smoke_gate.py trên cây build có sẵn của bản tái hiện (4 case, build cờ gốc và build PIC; không thực thi binary nào) và trên
build.ninja đã sửa có chủ ý. Cây build chỉ được đọc: test dựng thư mục tạm gồm symlink tới từng case và marker dựng lại từ log build
(build_c_exe giữ 2000 ký tự cuối của log configure cộng log build).
Chạy (từ gốc repo): [SMOKE_BUILD2=<cây build>] python3 experiments/37-rq2-san-supp/scripts/test_smoke_gate.py -v
SMOKE_BUILD2: cây build tái hiện trong container (orig/ và pic/ của 4 case 005, 006, 031, 050; không nằm trong repo, cách dựng ở
results/repro-container/FINDINGS.md). Không đặt thì RealTrees, MutatedNinja bị bỏ qua, lớp Units vẫn chạy.
SUPP_REQUIRE_DATA=1: thiếu cây build thì test THẤT BẠI thay vì bỏ qua (review L10)."""
import glob, hashlib, importlib.util, json, os, shutil, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('smoke_gate', os.path.join(HERE, 'smoke_gate.py'))
G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
BUILD2 = os.environ.get('SMOKE_BUILD2')
CASES = ['005_sphincs_PQCgenKAT_sign_blake_128f_simple', '006_sphincs_PQCgenKAT_sign_blake_128f_robust',
         '031_sphincs_PQCgenKAT_sign_shake_128s_simple', '050_sphincs_PQCgenKAT_sign_haraka_256f_robust']
HAVE = bool(BUILD2) and all(os.path.isdir(f'{BUILD2}/{s}/{c}') for s in ('orig', 'pic') for c in CASES)
REQUIRE = os.environ.get('SUPP_REQUIRE_DATA') == '1'


def needs(cond, msg):
    if cond: return lambda x: x
    if not REQUIRE: return unittest.skip(msg)

    def deco(cls):
        def setUpClass(c): raise AssertionError(f'SUPP_REQUIRE_DATA=1 mà thiếu dữ liệu: {msg}')
        cls.setUpClass = classmethod(setUpClass); return cls
    return deco


def tail(p, n=4000):
    try: return open(p, errors='replace').read()[-n:]
    except OSError: return ''


def mk_tree(tc, build2, cases):
    """Thư mục tạm pic/, orig/: symlink tới case trong build2 và marker như build_c_exe ghi."""
    d = tempfile.mkdtemp(prefix='gate-'); tc.addCleanup(shutil.rmtree, d, True)
    for side in ('pic', 'orig'):
        os.makedirs(f'{d}/{side}')
        for c in cases:
            os.symlink(f'{build2}/{side}/{c}', f'{d}/{side}/{c}')
            ds = G.drivers(f'{d}/{side}/{c}')
            ok = side == 'pic' and len(ds) == 1
            log = '' if ok else (tail(f'{build2}/{side}/{c}.cfg.txt') + tail(f'{build2}/{side}/{c}.build.txt'))[-2000:]
            json.dump(dict(kind='c-san', bundle='P01_sphincs_plus', case=c, preset='test', ok=ok, bin=ds[0] if ok else None,
                           sha256=hashlib.sha256(open(ds[0], 'rb').read()).hexdigest() if ok else None, secs=0, log=log),
                      open(f'{d}/{side}/{c}.build.json', 'w'))
    return d


@needs(HAVE, 'đặt SMOKE_BUILD2 tới thư mục build2 (orig/, pic/ của 4 case)')
class RealTrees(unittest.TestCase):
    def setUp(self):
        self.d = mk_tree(self, BUILD2, CASES)

    def test_gate_on_repro_trees(self):
        """Le chốt 5/11 (review C1): S-cache đòi `:UNINITIALIZED=ON`, đúng dòng CMake 3.28.3 ghi cho cờ không ghi kiểu; cổng đạt trên cây
        tái hiện."""
        self.assertEqual(G.S_CACHE_LINE, 'CMAKE_POSITION_INDEPENDENT_CODE:UNINITIALIZED=ON')
        g = G.gate(f'{self.d}/pic', f'{self.d}/orig', CASES)
        c = g['conditions']
        self.assertTrue(c['s_orig'], g['s_orig']); self.assertTrue(c['s_pic']); self.assertTrue(c['s_ninja'], g['per_case'])
        self.assertTrue(c['s_clang'], g['s_clang']); self.assertTrue(c['s_cache'], g['failed_cases'])
        self.assertTrue(g['ok']); self.assertEqual(g['failed_cases'], {})
        for x in CASES:
            self.assertEqual(g['per_case'][x]['s_cache']['found'], ['CMAKE_POSITION_INDEPENDENT_CODE:UNINITIALIZED=ON'])
            n = g['per_case'][x]['s_ninja']
            self.assertEqual((n['n_sphincs_obj'], n['n_driver_obj'], n['n_other_changed']), (8, 1, 0))
            self.assertTrue(n['link']['equal']); self.assertEqual(n['other_diff_lines'], []); self.assertTrue(n['rules_ninja']['ok'])
        self.assertEqual(g['per_case']['005_sphincs_PQCgenKAT_sign_blake_128f_simple']['s_ninja']['n_other_same'], 7)  # như flags-orig-vs-pic-005

    def test_gate_fails_with_typed_bool_line(self):
        """Chữ cũ của amendment (`:BOOL=ON`) không khớp cây thật: cổng phải trượt nếu hằng bị đổi về chữ cũ."""
        g = G.gate(f'{self.d}/pic', f'{self.d}/orig', CASES, cache_line='CMAKE_POSITION_INDEPENDENT_CODE:BOOL=ON')
        self.assertFalse(g['ok']); self.assertEqual(g['failed_cases'], {'s_cache': CASES})

    def test_orig_marker_signature(self):
        r = G.s_orig(f'{self.d}/orig', CASES[0]); self.assertTrue(r['ok'], r)
        m = f'{self.d}/orig/{CASES[0]}.build.json'; j = json.load(open(m))
        json.dump(dict(j, log=j['log'].replace('R_X86_64_PC32', 'R_X86_64_32')), open(m, 'w'))
        r = G.s_orig(f'{self.d}/orig', CASES[0]); self.assertFalse(r['ok']); self.assertEqual(r['missing'], ['R_X86_64_PC32'])
        json.dump(dict(j, ok=True), open(m, 'w'))
        self.assertFalse(G.s_orig(f'{self.d}/orig', CASES[0])['ok'])
        os.remove(m); self.assertFalse(G.s_orig(f'{self.d}/orig', CASES[0])['ok'])

    def test_orig_builds_have_no_driver(self):
        for c in CASES:
            self.assertEqual(G.drivers(f'{self.d}/orig/{c}'), [])
            self.assertFalse(G.s_pic(f'{self.d}/orig', c)['ok'])           # dùng nhầm thư mục đối chứng làm bản PIC thì hỏng

    def test_cli_and_archive(self):
        out = f'{self.d}/out'
        rc = G.main(['--pic-dir', f'{self.d}/pic', '--orig-dir', f'{self.d}/orig', '--cases', ','.join(CASES), '--out', f'{out}/gate.json',
                     '--archive', f'{out}/archive', '--cases-jsonl', f'{out}/rq2-gate-cases.jsonl'])
        self.assertEqual(rc, 0)
        rows = [json.loads(l) for l in open(f'{out}/rq2-gate-cases.jsonl')]
        self.assertEqual([r['case'] for r in rows], CASES); self.assertTrue(all(r['s_pic'] and r['s_cache'] and r['s_ninja'] for r in rows))
        doc = json.load(open(f'{out}/gate.json')); self.assertTrue(doc['ok'])
        self.assertIn('ĐẠT', open(f'{out}/gate.txt').read()); self.assertNotIn('KHÔNG ĐẠT', open(f'{out}/gate.txt').read())
        for side in ('pic', 'orig'):
            for c in CASES:
                for f in ('CMakeCache.txt', 'build.ninja.txt', 'rules.ninja.txt'):
                    self.assertTrue(os.path.isfile(f'{out}/archive/{side}/{c}/{f}'), (side, c, f))
                self.assertTrue(os.path.isfile(f'{out}/archive/{side}/{c}.build.json'))
        t = open(f'{out}/archive/clang-pie-runner.txt').read()
        self.assertIn('"-mrelocation-model" "pic" "-pic-level" "2" "-pic-is-pie"', t)


    def test_cli_exit_codes(self):
        """review R2-12: cổng không đạt cho mã 3 (job ghi STOP); script lỗi cho mã khác (job xếp fail)."""
        m = f'{self.d}/orig/{CASES[0]}.build.json'; j = json.load(open(m)); json.dump(dict(j, ok=True), open(m, 'w'))
        with mock.patch('sys.stdout'):
            rc = G.main(['--pic-dir', f'{self.d}/pic', '--orig-dir', f'{self.d}/orig', '--cases', ','.join(CASES)])
        self.assertEqual(rc, G.EXIT_NOT_PASSED); self.assertEqual(rc, 3)
        import subprocess, sys
        p = subprocess.run([sys.executable, os.path.join(HERE, 'smoke_gate.py'), '--pic-dir', f'{self.d}/pic', '--orig-dir', f'{self.d}/orig',
                            '--keys', f'{self.d}/khong-co-keys.txt'], capture_output=True, text=True,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(p.returncode, 1, p.stderr); self.assertIn('Traceback', p.stderr)          # crash: mã 1, khác mã 3


@needs(HAVE, 'đặt SMOKE_BUILD2 tới thư mục build2')
class MutatedNinja(unittest.TestCase):
    """build.ninja bản PIC chép vào thư mục tạm rồi sửa: mỗi lệch phải làm S-ninja hỏng."""
    case = CASES[0]

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='ninja-'); self.addCleanup(shutil.rmtree, self.d, True)
        self.src = {s: open(f'{BUILD2}/{s}/{self.case}/build-ninja/build.ninja').read() for s in ('orig', 'pic')}

        self.rules = {s: open(f'{BUILD2}/{s}/{self.case}/build-ninja/CMakeFiles/rules.ninja').read() for s in ('orig', 'pic')}

    def put(self, side, text, rules=None):
        wd = f'{self.d}/{side}'; os.makedirs(f'{wd}/build-ninja/CMakeFiles', exist_ok=True)
        open(f'{wd}/build-ninja/build.ninja', 'w').write(text.replace(f'{BUILD2}/{side}/{self.case}', wd))
        open(f'{wd}/build-ninja/CMakeFiles/rules.ninja', 'w').write((rules or self.rules[side]).replace(f'{BUILD2}/{side}/{self.case}', wd))
        return wd

    def check(self, pic_text, orig_text=None, pic_rules=None):
        o = self.put('orig', orig_text or self.src['orig']); p = self.put('pic', pic_text, pic_rules)
        return G.s_ninja(o, p)

    def test_rules_ninja_changed(self):
        """review N5: rules.ninja khác (ví dụ lệnh compile đổi) thì S-ninja trượt dù build.ninja giống."""
        self.assertTrue(self.check(self.src['pic'])['rules_ninja']['ok'])
        r = self.check(self.src['pic'], pic_rules=self.rules['pic'].replace('$FLAGS', '$FLAGS -fno-plt', 1))
        self.assertFalse(r['ok']); self.assertFalse(r['rules_ninja']['ok'])
        os.remove(f'{self.d}/pic/build-ninja/CMakeFiles/rules.ninja')
        self.assertFalse(G.s_ninja(f'{self.d}/orig', f'{self.d}/pic')['ok'])

    def test_unmodified_ok(self):
        self.assertTrue(self.check(self.src['pic'])['ok'])

    def test_orig_vs_orig_fails(self):
        r = self.check(self.src['orig']); self.assertFalse(r['ok'])         # không có -fPIC thêm vào sphincs_obj

    def test_other_object_changed(self):
        t = self.src['pic'].replace('-DPARAMS=sphincs-blake-128f -O3 -DNDEBUG -std=gnu99 -fPIC', '-DPARAMS=sphincs-blake-128f -O2 -DNDEBUG -std=gnu99 -fPIC', 1)
        r = self.check(t); self.assertFalse(r['ok']); self.assertEqual(r['n_other_changed'], 1)

    def test_sphincs_obj_extra_flag(self):
        i = self.src['pic'].index('sphincs_obj.dir/src/fors.c.o:')
        j = self.src['pic'].index('-fPIC', i)
        t = self.src['pic'][:j] + '-fPIC -fno-plt' + self.src['pic'][j + 5:]
        self.assertFalse(self.check(t)['ok'])

    def test_driver_without_fpie(self):
        i = self.src['pic'].index('driver.dir/src/PQCgenKAT_sign.c.o:')
        j = self.src['pic'].index(' -fPIE', i)
        self.assertFalse(self.check(self.src['pic'][:j] + self.src['pic'][j + 6:])['ok'])

    def test_link_flags_changed(self):
        t = self.src['pic'].replace('  LINK_FLAGS = -fsanitize=address,undefined', '  LINK_FLAGS = -fsanitize=address,undefined -static-libsan', 1)
        r = self.check(t); self.assertFalse(r['ok']); self.assertFalse(r['link']['equal'])

    def test_other_line_changed(self):
        t = self.src['pic'].replace('ninja_required_version = ', 'ninja_required_version = 9', 1)
        r = self.check(t); self.assertFalse(r['ok']); self.assertTrue(r['other_diff_lines'])

    def test_line_count_changed(self):
        self.assertFalse(self.check(self.src['pic'] + '\n# thêm\n')['ok'])


class Units(unittest.TestCase):
    def test_added(self):
        self.assertTrue(G._added(['-a', '-b'], ['-a', '-b', '-fPIC'], '-fPIC'))
        self.assertTrue(G._added(['-a', '-b'], ['-a', '-fPIC', '-b'], '-fPIC'))
        self.assertFalse(G._added(['-a', '-fPIC'], ['-a', '-fPIC', '-fPIC'], '-fPIC'))
        self.assertFalse(G._added(['-a'], ['-a', '-fPIC', '-x'], '-fPIC'))
        self.assertFalse(G._added(['-a'], ['-a'], '-fPIC'))

    def test_clang_mismatch(self):
        fake = lambda extra, clang='clang': dict(args=extra, rc=0, relocation_model='pic', pic_level='2', pic_is_pie=not extra, raw='')
        with mock.patch.object(G, 'clang_reloc', fake): self.assertFalse(G.s_clang()['ok'])
        ok = lambda extra, clang='clang': dict(args=extra, rc=0, relocation_model='pic', pic_level='2', pic_is_pie=True, raw='')
        with mock.patch.object(G, 'clang_reloc', ok): self.assertTrue(G.s_clang()['ok'])

    def test_two_drivers_fail(self):
        d = tempfile.mkdtemp(prefix='drv-'); self.addCleanup(shutil.rmtree, d, True)
        for p in ('c/build-ninja/driver', 'c/build-ninja/x/driver'):
            os.makedirs(os.path.dirname(f'{d}/{p}'), exist_ok=True); open(f'{d}/{p}', 'w').write(''); os.chmod(f'{d}/{p}', 0o755)
        json.dump(dict(ok=True, bin=f'{d}/c/build-ninja/driver'), open(f'{d}/c.build.json', 'w'))
        r = G.s_pic(d, 'c'); self.assertFalse(r['ok']); self.assertEqual(r['n_drivers'], 2)


if __name__ == '__main__':
    unittest.main()
