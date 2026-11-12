"""harness.census, phần thu quan sát qua observe.run_lib thật (runner giả): gộp report từng vector, không đặt CANDO2_STATE_DUMP, vector
không có report làm cả lần chạy không có report, và chốt chặn tiến trình mồ côi (kế hoạch A3-A7 mục 3.5)."""
import json, os, shutil, stat, tempfile, textwrap, time, unittest

from harness import census as CE
from harness import observe as OB

FAKE_RUNNER = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, subprocess, sys, time
    a = sys.argv[1:]
    if a and a[0] == 'child':                      # tiến trình con tự tách khỏi nhóm (như con procspawn thoát được kill nhóm)
        os.setpgid(0, 0); time.sleep(60); sys.exit(0)
    vec = a[a.index('--vectors') + 1]; out = a[a.index('--output') + 1]
    v = json.load(open(vec))
    if 'CANDO2_STATE_DUMP' in os.environ: v = dict(r='DumpSet')
    if v['r'] == 'noreport': sys.exit(3)
    if v['r'] == 'orphan':
        subprocess.Popen([sys.argv[0], 'child'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(0.5)
        v = dict(r='Timeout')
    json.dump({vec: dict(result=v['r'], output=dict(stdout='', stderr=''), timeout=a[a.index('--timeout') + 1])}, open(out, 'w'))
''')


class RunReport(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='census-run-')
        self.rdir = os.path.join(self.d, 'runner-target', 'release'); os.makedirs(self.rdir)
        self.runner = os.path.join(self.rdir, 'fake_runner'); open(self.runner, 'w').write(FAKE_RUNNER)
        os.chmod(self.runner, os.stat(self.runner).st_mode | stat.S_IEXEC)
        self.tv = os.path.join(self.d, 'case', 'test_vectors'); os.makedirs(self.tv)

    def tearDown(self):
        CE.orphans(self.rdir, kill=True)
        shutil.rmtree(self.d, ignore_errors=True)

    def vecs(self, **kv):
        for n, r in kv.items(): json.dump(dict(r=r), open(os.path.join(self.tv, n + '.json'), 'w'))
        open(os.path.join(self.tv, 'empty.json'), 'w').close()                  # file rỗng: runner bỏ qua
        with open(os.path.join(self.tv, 'x.json.bak'), 'w') as f: f.write('{}')   # không phải json
        return CE.vector_files(os.path.dirname(self.tv))

    def run1(self, vecs, timeout=10):
        return CE.run_report(self.runner, self.d, vecs, timeout, True, os.path.join(self.d, 'work'))

    def test_merge_per_vector_report(self):
        vecs = self.vecs(**{'1': 'Pass', '2': 'VectorComparisonFailed', '3': 'Skip'})
        self.assertEqual([os.path.basename(v) for v in vecs], ['1.json', '2.json', '3.json'])
        rep, secs, err = self.run1(vecs)
        self.assertIsNone(err)
        self.assertEqual({k: v['result'] for k, v in rep.items()}, {'1.json': 'Pass', '2.json': 'VectorComparisonFailed', '3.json': 'Skip'})
        self.assertEqual(rep['1.json']['timeout'], '10')
        self.assertEqual(CE.tally(rep), ({'Pass': 1, 'VectorComparisonFailed': 1, 'Skip': 1}, 3))
        self.assertEqual(os.listdir(os.path.join(self.d, 'work')), [])                 # report tạm đã xoá

    def test_state_dump_not_set(self):
        os.environ['CANDO2_STATE_DUMP'] = '/nonexistent/should-not-leak'
        try:
            rep, _, _ = self.run1(self.vecs(**{'1': 'Pass'}))
        finally:
            del os.environ['CANDO2_STATE_DUMP']
        self.assertEqual(rep['1.json']['result'], 'Pass')

    def test_missing_report_means_no_report(self):
        rep, _, err = self.run1(self.vecs(**{'1': 'Pass', '2': 'noreport'}))
        self.assertIsNone(rep); self.assertEqual((err['vector'], err['k1']), ('2.json', 'infra'))
        self.assertEqual(CE.run_verdict(True, rep), dict(timeout_used=10, run_ok=False))

    def test_orphan_guard(self):
        rep, _, _ = self.run1(self.vecs(**{'1': 'orphan'}))
        self.assertEqual(rep['1.json']['result'], 'Timeout')
        found = []
        for _ in range(50):                                     # con có thể chưa kịp setpgid khi runner thoát
            found = CE.orphans(self.rdir, kill=True)
            if found: break
            time.sleep(0.1)
        self.assertEqual(len(found), 1)                         # con thoát kill nhóm được đếm và bị dừng
        time.sleep(0.2)
        self.assertEqual(CE.orphans(self.rdir, kill=False), [])

    def test_no_orphan_when_group_killed(self):
        self.run1(self.vecs(**{'1': 'Pass'}))
        self.assertEqual(CE.orphans(self.rdir, kill=False), [])


if __name__ == '__main__':
    unittest.main()
