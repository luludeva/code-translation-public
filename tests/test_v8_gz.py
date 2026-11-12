"""V8 (exp 17) đọc file divergence nén (F8): bản thô và bản .gz cho cùng nội dung; file phụ tách như metrics.load_rq1 (sửa 2026-10-26)."""
import importlib.util, json, os, shutil, tempfile, unittest

from harness.record import compress_files
from harness.rq1 import case_files

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_s = importlib.util.spec_from_file_location('v8_exp17', f'{REPO}/experiments/17-v8-resume/scripts/v8.py')
V8 = importlib.util.module_from_spec(_s); _s.loader.exec_module(V8)

REC = dict(key='B01_synthetic/029_strcspn_lib/s0', status='done', secs=1.5, phases={'execute': 1.0}, n_inputs=40)
DIV = [dict(kind='lib', bundle='B01_synthetic', case='029_strcspn_lib', system='kiro', seed=0, idx=3, secs=0.2),
       dict(kind='lib', bundle='B01_synthetic', case='029_strcspn_lib', system='claude', seed=0, idx=1, secs=0.1)]


def _write(out, gz, div=DIV, extra=None):
    os.makedirs(f'{out}/div')
    open(f'{out}/rq1-lib.jsonl', 'w').write(json.dumps(dict(REC, secs=REC['secs'] + gz)) + '\n')
    base = f'{out}/div/B01_synthetic__029_strcspn_lib__s0.jsonl'
    files = case_files(base)          # chính, .capsens, .memlimit, .exact
    for f, rows in zip(files, (div, div[:1], [dict(key='k', side='c', err_tail='memory allocation of 8 bytes failed')],
                               [dict(key='k', c_state=[1.0], r_state=[1.0000001])])):
        with open(f, 'w') as fh:
            for r in rows: fh.write(json.dumps(r) + '\n')
    if extra: extra(files)
    if gz: compress_files(files)
    return files


class TestV8Gz(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.a, self.b = f'{self.d}/A', f'{self.d}/B'

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_gz_read_same_content_as_plain(self):
        _write(self.a, gz=False); _write(self.b, gz=True)
        (ra, da), (rb, db) = V8.load(self.a), V8.load(self.b)
        self.assertTrue(all(f.endswith('.gz') for f in db))
        self.assertEqual(da, {f[:-3]: v for f, v in db.items()})     # cùng nội dung sau khi bỏ trường thời gian
        self.assertEqual(len(db['B01_synthetic__029_strcspn_lib__s0.jsonl.gz']), 2)

    def test_pass_both_gz_side_files_split(self):
        _write(self.a, gz=True); _write(self.b, gz=True)
        (ra, da), (rb, db) = V8.load(self.a), V8.load(self.b)
        res = V8.compare(ra, da, rb, db, [REC['key']])
        self.assertTrue(res['pass'])
        self.assertEqual(sorted(res['div_files_equal']), ['B01_synthetic__029_strcspn_lib__s0.capsens.jsonl.gz',
                                                          'B01_synthetic__029_strcspn_lib__s0.jsonl.gz'])
        self.assertEqual(sorted(res['side_files_equal']), ['B01_synthetic__029_strcspn_lib__s0.exact.jsonl.gz',
                                                           'B01_synthetic__029_strcspn_lib__s0.memlimit.jsonl.gz'])

    def test_diff_in_gz_divergence_detected(self):
        _write(self.a, gz=True); _write(self.b, gz=True, div=[DIV[0], dict(DIV[1], idx=2)])
        (ra, da), (rb, db) = V8.load(self.a), V8.load(self.b)
        res = V8.compare(ra, da, rb, db, [])
        self.assertFalse(res['pass']); self.assertFalse(res['div_files_equal']['B01_synthetic__029_strcspn_lib__s0.jsonl.gz'])

    def test_diff_in_side_file_still_fails(self):
        # tiêu chí V8 đã duyệt so cả file phụ: tách khỏi div_files_equal nhưng vẫn tính vào pass
        def bump(files): open(files[3], 'a').write(json.dumps(dict(key='k2')) + '\n')
        _write(self.a, gz=True); _write(self.b, gz=True, extra=bump)
        (ra, da), (rb, db) = V8.load(self.a), V8.load(self.b)
        res = V8.compare(ra, da, rb, db, [])
        self.assertTrue(all(res['div_files_equal'].values()))
        self.assertFalse(res['side_files_equal']['B01_synthetic__029_strcspn_lib__s0.exact.jsonl.gz']); self.assertFalse(res['pass'])

    def test_plain_vs_gz_name_mismatch_fails(self):
        # một case còn bản thô ở lần này, bản nén ở lần kia: case chưa xong ở một bên, không được tính là đạt
        _write(self.a, gz=False); _write(self.b, gz=True)
        (ra, da), (rb, db) = V8.load(self.a), V8.load(self.b)
        self.assertFalse(V8.compare(ra, da, rb, db, [])['pass'])


if __name__ == '__main__':
    unittest.main()
