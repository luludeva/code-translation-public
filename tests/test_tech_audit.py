"""Rà soát kỹ thuật 2026-10-23: bằng chứng chạm trần bộ nhớ trong bản ghi RQ1 (finding 9); xoá file phụ khi chạy lại một case (V8)."""
import collections, io, json, os, subprocess, tempfile, unittest

from harness import observe as OB
from harness import rq1


class MemEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix='memev-')
        src = os.path.join(cls.d, 'm.c'); cls.bin = os.path.join(cls.d, 'm')
        open(src, 'w').write('#include <stdio.h>\nint main(){fputs("memory allocation of 8589934592 bytes failed\\n", stderr);return 134;}\n')
        subprocess.run(['gcc', src, '-o', cls.bin], check=True)

    def test_exe_marker_recorded(self):
        o = OB.run_exe(self.bin, [], '', 5)
        self.assertEqual(o['status'], 'mem_limit'); self.assertEqual(o['mem_marker'], ['memory allocation of'])

    def test_mem_note_counts_and_caps_samples(self):
        o = OB.run_exe(self.bin, [], '', 5); ok = dict(status='exit', rc=0, err=b'')
        cnt, f = collections.Counter(), io.StringIO()
        for i in range(rq1.MEM_SAMPLE + 5):
            rq1.mem_note(cnt, f, f'k/{i}', 'exe', ok, o, 'div', 'M')
        rq1.mem_note(cnt, f, 'k/x', 'exe', o, o, 'match', 'seed')
        self.assertEqual(cnt['mem_limit_r_div'], rq1.MEM_SAMPLE + 5)
        self.assertEqual((cnt['mem_limit_c_match'], cnt['mem_limit_r_match']), (1, 1))
        recs = [json.loads(l) for l in f.getvalue().splitlines()]
        self.assertEqual(sum(r['side'] == 'r' for r in recs), rq1.MEM_SAMPLE)       # mẫu giới hạn theo phía
        self.assertEqual(recs[0]['marker'], ['memory allocation of']); self.assertIn('8589934592', recs[0]['err_tail'])

    def test_lib_marker(self):
        o = dict(k1='reported', result='MemLimit', stderr='memory allocation of 1 bytes failed', mem_marker=['memory allocation of'])
        cnt, f = collections.Counter(), io.StringIO()
        rq1.mem_note(cnt, f, 'k', 'lib', dict(k1='reported', result='Pass'), o, 'div', 'generated')
        self.assertEqual(cnt['mem_limit_r_div'], 1); self.assertEqual(json.loads(f.getvalue())['marker'], ['memory allocation of'])


class ResumeSidecars(unittest.TestCase):
    def test_reset_removes_all(self):
        d = tempfile.mkdtemp(); div = os.path.join(d, 'B__c__s0.jsonl')
        fs = [div, div.replace('.jsonl', '.capsens.jsonl'), div.replace('.jsonl', '.memlimit.jsonl')]
        for f in fs: open(f, 'w').write('{}\n')
        rq1.reset_case_files(div)
        self.assertFalse(any(os.path.exists(f) for f in fs))


if __name__ == '__main__':
    unittest.main()


import importlib.util as _ilu, sys as _sys
_spec = _ilu.spec_from_file_location('bnu_v0', os.path.join(os.path.dirname(__file__), '..', 'experiments', '09-bnu-rules', 'scripts',
                                                            'bnu_v0.py'))
BNU = _ilu.module_from_spec(_spec); _spec.loader.exec_module(BNU)


def _exe_fields(c, r):
    f = lambda o: (o['rc'] if o['status'] == 'exit' else (-o['sig'] if o.get('sig') else None))
    return (f(c), f(r), OB.is_nt(c), OB.is_nt(r), c['out'].decode('latin-1'), r['out'].decode('latin-1'), False, False,
            c['err'].decode('latin-1'), r['err'].decode('latin-1'))


def _e(status='exit', rc=0, sig=None, out=b'', err=b''):
    return dict(status=status, rc=rc if status == 'exit' else None, sig=sig, to=status == 'timeout', out=out, err=err)


def _l(result='Pass', state=None, nonfinite=None, stdout='', stderr='', k1='reported'):
    o = dict(k1=k1, result=result, rc=0, stdout=stdout, stderr=stderr)
    if state is not None: o['state_out'] = state
    if nonfinite is not None: o['state_nonfinite'] = nonfinite
    return o


class ClassifierFollowsOracle(unittest.TestCase):
    """Bất biến (bnu-v5): oracle ghi nhận divergence thì bộ phân loại không xếp "hết khác sau chuẩn hoá"; oracle coi là bằng thì
    bộ phân loại xếp ngoài S. Bốn ca đầu là các ca bản bnu-v2 sai (rà soát kỹ thuật 2026-10-23)."""
    LIB = [(_l(state={'v': None}, nonfinite=['NaN']), _l(state={'v': None}, nonfinite=['inf'])),
           (_l('SegmentationFault'), _l('Panic')),
           (_l(state={'x': 1}), _l('Panic', stderr='thread panicked')),
           (_l(state={'x': 1.0}), _l(state={'x': float('inf')})),
           (_l(state={'x': 1.0}, stdout='a'), _l(state={'x': 1.0}, stdout='a ')),
           (_l(state={'x': 1.0}, stderr='E 0x1'), _l(state={'x': 1.0}, stderr='e 0x2')),
           (_l(state={'x': 1.0}, stderr='e'), _l(state={'x': 1.0}, stderr='')),
           (_l('Timeout'), _l('MemLimit'))]
    EXE = [(_e(rc=101, err=b"thread 'main' (11) panicked at a.rs:1:1:\nx"), _e(rc=101, err=b"thread 'main' (12) panicked at a.rs:1:1:\nx")),
           (_e(out=b'NANCY\n'), _e(out=b'nanCY\n')),
           (_e(out=b'nan\n'), _e(out=b'-NaN\n')),
           (_e(out=b'1\n'), _e(out=b'2\n')),
           (_e(err=b'x'), _e(err=b'')),
           (_e('signal', sig=11), _e('signal', sig=6))]

    def test_lib(self):
        for c, r in self.LIB:
            g, rule = BNU.classify_lib(c, r)
            self.assertEqual(OB.equal_lib(c, r), g == 'not_S', (c, r, g, rule))

    def test_exe(self):
        for c, r in self.EXE:
            g, rule = BNU.classify_exe(*_exe_fields(c, r))
            self.assertEqual(OB.equal_exe(c, r), g == 'not_S', (c, r, g, rule))

    def test_self_test(self):
        self.assertEqual(BNU.self_test(), 32)                    # bnu-v5: thêm 7 ca


class ChecksUseRetry(unittest.TestCase):
    def test_no_bare_run_lib(self):
        src = open(os.path.join(os.path.dirname(__file__), '..', 'harness', 'checks.py')).read()
        self.assertNotIn('OB.run_lib(', src)                     # V5, V6 thử lại lỗi hạ tầng như RQ1


class ReportCounters(unittest.TestCase):
    """Bộ đếm R21, R23, R28 (rq1.obs_note) và blob tái lập từng byte."""
    def test_exe_status_and_both_nt(self):
        cnt = collections.Counter()
        rq1.obs_note(cnt, 'exe', _e('timeout', out=b'a'), _e('output_limit', out=b'a'), True, dict(nt_prefix_bytes=1))
        rq1.obs_note(cnt, 'exe', _e(), _e('signal', sig=11), False, {})
        self.assertEqual((cnt['c_status:timeout'], cnt['r_status:output_limit'], cnt['c_status:exit'], cnt['r_status:signal']), (1, 1, 1, 1))
        self.assertEqual((cnt['both_nt_match'], cnt['both_nt_prefix_bytes']), (1, 1))

    def test_lib_exact(self):
        cnt, f = collections.Counter(), io.StringIO()
        a, b = _l(state={'x': 1.0}), _l(state={'x': 1.0 + 1e-9})
        rq1.obs_note(cnt, 'lib', a, b, True, None, f, 'k', 'random')
        rq1.obs_note(cnt, 'lib', a, _l(state={'x': 1.0}), True, None, f, 'k2', 'random')
        rq1.obs_note(cnt, 'lib', _l(state={'x': float('nan')}), _l(state={'x': float('nan')}), True, None, f, 'k3', 'random')
        self.assertEqual(cnt['match_tol_not_exact'], 1); self.assertEqual(json.loads(f.getvalue())['key'], 'k')
        self.assertEqual(cnt['r_status:Pass'], 3)

    def test_blob_reproducible(self):
        import base64
        from harness.record import blob
        self.assertEqual(base64.b64decode(blob(b'abc')['gz64'])[4:8], b'\0\0\0\0')   # trường MTIME của header gzip bằng 0


class PinnedEnv(unittest.TestCase):
    """Kết quả không phụ thuộc RUST_BACKTRACE của môi trường chạy (máy đo không đặt, container đặt 1)."""
    @unittest.skipUnless(__import__('shutil').which('rustc'), 'cần rustc')
    def test_rust_panic_stderr_independent(self):
        d = tempfile.mkdtemp(); src = os.path.join(d, 'p.rs'); b = os.path.join(d, 'p')
        open(src, 'w').write('fn main(){ let v: Vec<u8> = vec![]; println!("{}", v[std::env::args().count()]); }')
        subprocess.run(['rustc', '-O', src, '-o', b], check=True, capture_output=True)
        errs = []
        for bt in ('1', None):
            old = os.environ.pop('RUST_BACKTRACE', None)
            if bt: os.environ['RUST_BACKTRACE'] = bt
            try: errs.append(OB.norm_err(OB.run_exe(b, [], '', 5)['err']))
            finally:
                os.environ.pop('RUST_BACKTRACE', None)
                if old is not None: os.environ['RUST_BACKTRACE'] = old
        self.assertEqual(errs[0], errs[1]); self.assertNotIn(b'stack backtrace', errs[0])

    def test_load_error_pattern(self):
        msg = b'Internal failure: number out of range at line 1 column 57. To enable backtrace set `RUST_BACKTRACE=1`\n'
        self.assertTrue(OB.LOAD_ERR.search(msg)); self.assertFalse(OB.LOAD_ERR.search(b'runner process timeout'))


from harness.config import T as _T  # noqa: E402


@unittest.skipUnless(os.path.isdir(f'{_T}/B01_organic/gaussian_kernel_lib'), 'cần corpus TRACTOR')
class InvalidInputAnyEnv(unittest.TestCase):
    def test_out_of_range_without_backtrace(self):
        from harness import build as BD
        B = os.environ.get('HARNESS_BUILD', os.path.join(tempfile.gettempdir(), 'harness-test-build'))
        info = BD.build_lib_case(B, 'B01_organic', 'gaussian_kernel_lib'); root = BD.lib_root(B, info, 'c')
        v = json.load(open(sorted(f.path for f in os.scandir(f'{_T}/B01_organic/gaussian_kernel_lib/test_vectors')
                                  if f.name.endswith('.json'))[0]))
        p = os.path.join(B, 'gk-oor.json'); json.dump(dict(v, lib_state_in=dict(v['lib_state_in'], radius=1e300), lib_state_out={}), open(p, 'w'))
        for bt in ('1', '0', None):
            old = os.environ.pop('RUST_BACKTRACE', None)
            if bt: os.environ['RUST_BACKTRACE'] = bt
            try: self.assertEqual(OB.run_lib(info['runner_bin'], root, p, 10, False, os.path.join(B, 'gk-oor.dump'))['k1'], 'invalid_input', bt)
            finally:
                os.environ.pop('RUST_BACKTRACE', None)
                if old is not None: os.environ['RUST_BACKTRACE'] = old
