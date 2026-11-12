"""F3 (Le chọn 25/10, master plan Hàng đợi): seed riêng cho từng tầng sinh input executable, báo số sinh, ngoài miền, trùng và thực thi
theo tầng; library không có trường input ngoài P_test theo thiết kế (decision-log 2026-10-20). Không cần corpus.
Chạy: python3 -m unittest tests.test_f3_seed_noinput"""
import hashlib, random, unittest
from unittest import mock

from harness import insensitive as II
from harness import metrics as M
from harness import rq1
from harness.gen import stategen_v2, v1, v2_exe

SEEDS = [dict(argv=['abc', '12', '-x'], stdin='hello 42\nworld 7\n'), dict(argv=['3.5'], stdin='1 2 3\n'),
         dict(argv=[], stdin='quit\n')]
CD = dict(strings=['help', 'quit', '%d'], values=[dict(v=0), dict(v=255), dict(v=-1), dict(v=3.5)])


def key(x): return hashlib.sha1(repr((x[0], x[1])).encode()).hexdigest()


class LayerSeeds(unittest.TestCase):
    def overlap(self, seed):
        m = v2_exe.gen_inputs_v2(SEEDS, 'M', 300, seed, CD); ms = v2_exe.gen_inputs_v2(SEEDS, 'MS', 300, seed, CD)
        km = {key(x) for x in m}
        ops = [x for x in ms if x[2] in ('dict', 'syntax')]
        return sum(key(x) in km for x in ops), len(ops)

    def test_ms_operator_part_independent_of_m(self):
        """Bản cũ (cùng dãy): gần như mọi input toán tử của MS trùng M. Bản sửa: chỉ còn trùng ngẫu nhiên do không gian toán tử nhỏ
        của seed giả (3 seed ngắn), dưới một nửa."""
        for seed in (0, 1, 2):
            with mock.patch.dict(v1.LAYER_RNG_OFFSET, {'MS': 0}):
                d0, n0 = self.overlap(seed)
            d1, n1 = self.overlap(seed)
            self.assertGreaterEqual(d0 / n0, 0.95)
            self.assertLess(d1 / n1, 0.5, f'seed {seed}: {d1}/{n1} input toán tử của MS trùng M')

    def test_m_unchanged(self):
        """Tầng M giữ dãy cũ: phần random dùng Random(seed), phần toán tử dùng Random(seed + 1000)."""
        self.assertEqual(v1.LAYER_RNG_OFFSET['M'], 0)
        old_rng = random.Random(0); new = v1.gen_inputs(SEEDS, 'M', 50, 0)
        ref, seen, guard = [], set(), 0
        while len(ref) < 50 and guard < 2500:
            guard += 1; s = old_rng.choice(SEEDS); a, i = v1.mutate(s, old_rng)
            k = hashlib.sha1(repr((a, i)).encode()).hexdigest()
            if k in seen: continue
            seen.add(k); ref.append((a, i))
        self.assertEqual(new, ref)

    def test_deterministic_and_budget_distinct_within_layer(self):
        for layer in ('M', 'MS'):
            a = v2_exe.gen_inputs_v2(SEEDS, layer, 200, 1, CD); b = v2_exe.gen_inputs_v2(SEEDS, layer, 200, 1, CD)
            self.assertEqual(a, b)
            self.assertEqual(len({key(x) for x in a}), len(a))


class PerLayerCounts(unittest.TestCase):
    def test_gen_exe_reports_by_layer(self):
        gen = {'M': [(['a'], '', 'random'), (['b'], '', 'random'), (['\x00bad'], '', 'random')],
               'MS': [(['a'], '', 'random'), (['c'], '', 'dict')]}
        with mock.patch.object(rq1, 'exe_seeds', return_value=[dict(argv=['a'], stdin='')]), \
             mock.patch.object(rq1, '_cdict', return_value=({}, None)), \
             mock.patch.object(rq1, 'gen_inputs_v2', side_effect=lambda seeds, layer, *a: gen[layer]), \
             mock.patch.object(rq1, 'afl_layer', return_value=([(['d'], '', 'afl'), (['b'], '', 'afl')], {})), \
             mock.patch.object(rq1, 'in_domain', side_effect=lambda argv, stdin: not any('\x00' in x for x in argv)):
            X, info = rq1.gen_exe('/nonexistent', 'B', 'c', 0, dict(budget=3, afl_execs=1), 't')
        self.assertEqual(info['n_gen_by_layer'], {'S': 1, 'M': 3, 'MS': 2, 'A': 2})
        self.assertEqual(info['n_out_of_domain'], {'M': 1})
        self.assertEqual(info['n_dup_by_layer'], {'M': 1, 'MS': 1, 'A': 1})   # ['a'] trùng vector S; ['b'] trùng M
        self.assertEqual(info['n_by_layer'], {'S': 1, 'M': 1, 'MS': 1, 'A': 1})
        self.assertEqual(sum(info['n_by_layer'].values()), len(X))


class NoInputLibrary(unittest.TestCase):
    def test_lib_case_not_run_and_leaves_p_test(self):
        pairs = [dict(system='a', no_input=True), dict(system='b', no_input=True)]
        with mock.patch.object(rq1.BD, 'build_lib_case', side_effect=AssertionError('không được build')):
            r = rq1.rq1_lib_case('/nonexistent', 'B01_x', 'c', pairs, 0, {}, 10, '/nonexistent', 't')
        self.assertEqual(r['status'], 'done'); self.assertFalse(r['input_fields'])
        self.assertEqual(r['pair_status'], {'a': 'no_input_fields', 'b': 'no_input_fields'})
        cs = [dict(r, seed=s) for s in (0, 1, 2)]
        T = M.rq1_translations(cs, {}, {}, [0, 1, 2])
        self.assertEqual({k[2]: t['status'] for k, t in T.items()}, {'a': 'no_input_fields', 'b': 'no_input_fields'})
        S = M.summarize_rq1(T, 'lib')['by_group']['all']
        self.assertEqual((S['P_test'], S['leave']['no_input_fields']), (0, 2))

    def test_priority_over_other_reasons(self):
        cs = [dict(bundle='B01_x', case='c', seed=0, status='done', pair_status={'a': 'no_input_fields'}),
              dict(bundle='B01_x', case='c', seed=1, status='done', pair_status={'a': 'rust_build_failed'}),
              dict(bundle='B01_x', case='c', seed=2, status='done', pair_status={'a': 'P_test'})]
        self.assertEqual(M.rq1_translations(cs, {}, {}, [0, 1, 2])[('B01_x', 'c', 'a')]['status'], 'no_input_fields')


class NoVectorLibrary(unittest.TestCase):
    """Library có trường input nhưng không có vector: sinh từ kiểu (decision-log 2026-10-14, Le giữ 25/10)."""
    PARSED = dict(fields=[('a', None, ('int', 'i32', 32, True)), ('s', None, ('string',)), ('returns', None, ('int', 'i32', 32, True))],
                  run_fn='self.returns = f(self.a, &self.s);', consts={})

    def test_generates_from_types(self):
        g = stategen_v2.generate(self.PARSED, [], {}, 50, 0)
        self.assertEqual(len(g), 50)
        self.assertEqual(g[0]['source'], 'typed'); self.assertEqual(set(g[0]['state']), {'a', 's', 'returns'})
        self.assertTrue(all(x['seed_index'] is None for x in g))
        self.assertEqual(len({repr(sorted(x['state'].items())) for x in g}), 50)
        self.assertEqual(g, stategen_v2.generate(self.PARSED, [], {}, 50, 0))
        self.assertNotEqual(g, stategen_v2.generate(self.PARSED, [], {}, 50, 1))

    def test_no_fields_still_empty(self):
        self.assertEqual(stategen_v2.generate(dict(fields=[], run_fn='', consts={}), [], {}, 50, 0), [])

    def test_with_vectors_unchanged(self):
        seeds = [dict(a=3, s='hi', returns=0)]
        ref = stategen_v2.StateGenV2(self.PARSED, seeds, random.Random(1000), {}).generate_v2(30, 0)
        self.assertEqual(stategen_v2.generate(self.PARSED, seeds, {}, 30, 0), ref)


class InputSyms(unittest.TestCase):
    def test_added_symbols(self):
        self.assertTrue({'fgetwc', 'getwc', 'preadv', 'recvmsg'} <= II.INPUT_SYMS)


if __name__ == '__main__':
    unittest.main()
