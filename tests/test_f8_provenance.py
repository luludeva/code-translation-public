"""F8 (Le chọn 25/10, A8 (a), exp 22): blob 32 MiB, tập input nén, hash theo tầng, nén file divergence theo case, manifest đủ mục,
loại máy, chia file lớn trước khi đẩy kết quả. Không cần corpus. Chạy: python3 -m unittest tests.test_f8_provenance"""
import gzip, json, os, subprocess, tempfile, unittest
from unittest import mock

from harness import metrics as M
from harness import record as R
from harness import rq1
from harness.config import REPO
from harness.observe import OUTPUT_CAP


class Blob(unittest.TestCase):
    def test_limit_equals_output_cap(self):
        self.assertEqual(R.BLOB_LIMIT, OUTPUT_CAP)
        b = R.blob(b'x' * (2 << 20))
        self.assertFalse(b['truncated']); self.assertEqual(b['len'], 2 << 20)
        self.assertEqual(M.unblob(b), b'x' * (2 << 20))
        self.assertTrue(R.blob(b'y' * 10, limit=4)['truncated'])


class InputsFile(unittest.TestCase):
    def test_roundtrip_and_deterministic(self):
        d = tempfile.mkdtemp(); rows = [dict(i=0, layer='M', argv=['a'], stdin='x'), dict(i=1, layer='MS', argv=[], stdin='')]
        a = R.write_inputs(f'{d}/a/x.inputs.jsonl.gz', rows); b = R.write_inputs(f'{d}/b/x.inputs.jsonl.gz', rows)
        self.assertEqual(a['n'], 2); self.assertEqual(a['sha256'], b['sha256'])
        self.assertEqual(open(a['path'], 'rb').read(), open(b['path'], 'rb').read())        # gzip mtime 0: byte giống nhau
        with gzip.open(a['path'], 'rt') as f: self.assertEqual([json.loads(l) for l in f], rows)

    def test_paths(self):
        div = '/out/x10/div/B01_x__c__s0.jsonl'
        self.assertEqual(rq1.inputs_path(div), '/out/x10/inputs/B01_x__c__s0.inputs.jsonl.gz')
        self.assertEqual(len(rq1.case_files(div)), 4)


class CompressAndRead(unittest.TestCase):
    def test_metrics_reads_gz_and_skips_side_files(self):
        out = tempfile.mkdtemp(); os.makedirs(f'{out}/div')
        d = dict(kind='exe', bundle='B01_x', case='c', system='a', seed=0, stable=True, san='no_report', channels=['stdout'])
        div = f'{out}/div/B01_x__c__s0.jsonl'
        open(div, 'w').write(json.dumps(d) + '\n')
        open(div.replace('.jsonl', '.exact.jsonl'), 'w').write(json.dumps(dict(key='k', c_state={}, r_state={})) + '\n')
        open(div.replace('.jsonl', '.memlimit.jsonl'), 'w').write(json.dumps(dict(key='k', side='C')) + '\n')
        open(f'{out}/rq1-exe.jsonl', 'w').write(json.dumps(dict(bundle='B01_x', case='c', seed=0, status='done',
                                                                pair_status={'a': 'P_test'})) + '\n')
        R.compress_files(rq1.case_files(div))
        self.assertFalse(os.path.exists(div)); self.assertTrue(os.path.exists(div + '.gz'))
        cases, divs, caps = M.load_rq1(out, 'exe')
        self.assertEqual(len(divs[('B01_x', 'c', 'a', 0)]), 1)                  # file .exact và .memlimit không bị đọc như divergence
        rq1.reset_case_files(div)
        self.assertEqual([f for f in os.listdir(f'{out}/div')], [])


class Manifest(unittest.TestCase):
    def test_fields(self):
        with mock.patch.object(R, 'machine_info', return_value=dict(source='ec2-imds', instance_type='c7i.2xlarge')):
            m = R.manifest(tempfile.mkdtemp(), dict(x=1))
        for k in ('repo_commit', 'repo_dirty', 'machine', 'python', 'gcc', 'afl', 'cando2', 'blob_limit', 'params'):
            self.assertIn(k, m)
        self.assertEqual(m['machine']['instance_type'], 'c7i.2xlarge'); self.assertTrue(m['cando2']['state_dump_patch_sha256'])

    def test_machine_info_off_ec2(self):
        m = R.machine_info()
        self.assertIn(m['source'], ('none', 'ec2-imds'))
        if m['source'] == 'ec2-imds': self.assertTrue(m.get('instance_type'))

    def test_generator_params(self):
        g = rq1.gen_params()
        self.assertEqual(g['layer_rng_offset'], {'M': 0, 'MS': 500000}); self.assertEqual(g['c_time_factor'], rq1.C_TIME_FACTOR)


class SplitLarge(unittest.TestCase):
    def test_split_and_rejoin(self):
        d = tempfile.mkdtemp(); big = os.urandom(3 << 20); small = b'abc'
        open(f'{d}/big.bin', 'wb').write(big); open(f'{d}/small.bin', 'wb').write(small)
        subprocess.run(['bash', f'{REPO}/ci/split-large.sh', d], env=dict(os.environ, LIMIT_MB='1'), check=True, capture_output=True)
        self.assertFalse(os.path.exists(f'{d}/big.bin')); self.assertTrue(os.path.exists(f'{d}/small.bin'))
        parts = sorted(f for f in os.listdir(d) if f.startswith('big.bin.part'))
        self.assertEqual(b''.join(open(f'{d}/{p}', 'rb').read() for p in parts), big)
        self.assertIn('big.bin', open(f'{d}/split-files.txt').read())


def _slow_build(d, tag):
    """Hàm build giả cho BuildLock: ghi số lần gọi, giữ 0,5 giây, ghi marker."""
    import time as _t
    from harness import build as BD

    @BD._locked(lambda d, tag: f'{d}/x.build.json')
    def f(d, tag):
        open(f'{d}/calls', 'a').write(tag + '\n'); _t.sleep(0.5)
        json.dump(dict(ok=True, tag=tag), open(f'{d}/x.build.json', 'w')); return dict(ok=True, tag=tag)
    return f(d, tag)


class BuildLock(unittest.TestCase):
    """Hai worker build cùng một đích khi thư mục build còn trống: chỉ build một lần, worker sau đọc cache."""
    def test_single_build_under_concurrency(self):
        from concurrent.futures import ProcessPoolExecutor
        d = tempfile.mkdtemp()
        with ProcessPoolExecutor(3) as ex: res = list(ex.map(_slow_build, [d] * 3, ['a', 'b', 'c']))
        self.assertEqual(len(open(f'{d}/calls').read().split()), 1)
        self.assertEqual(len({r['tag'] for r in res}), 1)


class NoAflArchive(unittest.TestCase):
    """Decision-log 2026-10-25 (input tầng AFL++): lưu tập input gộp, gồm input tầng A; không lưu metadata khác của chiến dịch AFL++."""
    def test_no_afl_artifact(self):
        self.assertFalse(hasattr(rq1, 'archive_dir')); self.assertFalse(hasattr(rq1, 'afl_path'))
        out = tempfile.mkdtemp(); div = f'{out}/div/B__c__s0.jsonl'
        self.assertNotIn('afl', rq1.inputs_path(div).split('/')[-2])

if __name__ == '__main__':
    unittest.main()
