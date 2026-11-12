"""Gộp kết quả shard (harness/merge_shards.py): đủ, không trùng, manifest khớp."""
import json, os, tempfile, unittest

from harness import merge_shards as MS


def shard(root, name, keys, commit='abc', timeout=10, divs=()):
    d = os.path.join(root, name); os.makedirs(f'{d}/div')
    json.dump(dict(repo_commit=commit, params=dict(kind='exe', seeds=[0, 1, 2], timeout=timeout)), open(f'{d}/manifest.json', 'w'))
    open(f'{d}/rq1-exe.jsonl', 'w').write(''.join(json.dumps(dict(key=k, status='done')) + '\n' for k in keys))
    for f in divs: open(f'{d}/div/{f}', 'w').write('{}\n')
    return d


class Merge(unittest.TestCase):
    def setUp(self):
        self.r = tempfile.mkdtemp(); self.exp = os.path.join(self.r, 'cases.txt'); open(self.exp, 'w').write('B/a\nB/b\n')

    def test_ok(self):
        a = shard(self.r, 's1', ['B/a/s0', 'B/a/s1', 'B/a/s2'], divs=['B__a__s0.jsonl'])
        b = shard(self.r, 's2', ['B/b/s0', 'B/b/s1', 'B/b/s2'], divs=['B__b__s0.jsonl'])
        rep = MS.merge('exe', [a, b], os.path.join(self.r, 'out'), self.exp)
        self.assertTrue(rep['ok'], rep['problems']); self.assertEqual(rep['n_records'], 6)
        self.assertEqual(sorted(os.listdir(os.path.join(self.r, 'out', 'div'))), ['B__a__s0.jsonl', 'B__b__s0.jsonl'])

    def test_duplicate_missing_and_manifest(self):
        a = shard(self.r, 's1', ['B/a/s0', 'B/a/s1', 'B/a/s2'])
        b = shard(self.r, 's2', ['B/a/s0', 'B/b/s0'], commit='def', timeout=20)
        rep = MS.merge('exe', [a, b], os.path.join(self.r, 'out'), self.exp)
        p = ' '.join(rep['problems'])
        self.assertFalse(rep['ok'])
        for frag in ('trùng khoá B/a/s0', 'repo_commit', 'timeout', 'thiếu 2'): self.assertIn(frag, p)


if __name__ == '__main__':
    unittest.main()
