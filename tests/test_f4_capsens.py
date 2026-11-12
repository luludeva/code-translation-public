"""F4 (master plan Chương 3, phiên kỹ thuật 2026-10-25): phân tích độ nhạy trần output (R29) dùng cùng luật như lần chạy chính.
  - Lỗi hạ tầng ở trần lớn (library: k1 'infra' sau thử lại; executable: trạng thái không quan sát được) là outcome 'infra', đếm riêng,
    không tính là divergence mới hay khớp.
  - Một bên vượt ngân sách, bên kia dừng ở trần lớn: chạy lại hai bên với timeout gấp TIMEOUT_RERUN_FACTOR trước khi kết luận.
  - Ca bình thường không đổi.
Dùng mock, không cần corpus hay trình biên dịch. Chạy: python3 -m unittest tests.test_f4_capsens"""
import gzip, json, os, tempfile, unittest
from unittest import mock

from harness import observe as OB
from harness import rq1
from harness.config import TIMEOUT_RERUN_FACTOR as F

BIG = OB.OUTPUT_CAP * rq1.OUTPUT_CAP_SENS


def e(status='exit', out=b'x\n', rc=0):
    return dict(status=status, rc=rc if status == 'exit' else None, sig=None, to=status == 'timeout', out=out, err=b'')


def l(result='Pass', k1='reported', state=None, stdout='x'):
    if k1 != 'reported': return dict(k1=k1, rc=1)
    return dict(k1='reported', result=result, rc=0, state_out=state if state is not None else {'v': 1}, stdout=stdout, stderr='')


class FakeExe:
    """run_exe giả: script(binary, timeout, cap) trả quan sát; ghi lại mọi lần gọi."""
    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, binary, argv, stdin, timeout, env=None, cwd=None, cap=None, mem_limit=None, san=False):
        self.calls.append((binary, timeout, cap))
        return self.script(binary, timeout, cap)


class FakeLib:
    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, rb, root, p, timeout, rust, dump, cap=None, **kw):
        self.calls.append(('R' if rust else 'C', timeout, cap, dump))
        return self.script('R' if rust else 'C', timeout, cap)


# ---------------- executable, mức hàm ----------------
class ExeCapSens(unittest.TestCase):
    def run_cs(self, script):
        f = FakeExe(script)
        with mock.patch.object(OB, 'run_exe', side_effect=f):
            info, c8, r8 = rq1.cap_sens_exe('/c', '/r', [], '', 10, None)
        self.assertTrue(f.calls and all(cap == BIG for _, _, cap in f.calls))      # mọi lần chạy ở trần lớn
        return info, f.calls

    def test_one_sided_nt_rerun_then_equal(self):
        # Trần lớn, timeout gốc: C dừng, Rust timeout (in chậm hơn); gấp 10: hai bên dừng, output trùng. Bản trước: divergence mới.
        info, calls = self.run_cs(lambda b, t, cap: e('timeout') if (b == '/r' and t == 10) else e())
        self.assertEqual(info['outcome'], 'equal'); self.assertTrue(info['equal'])
        self.assertTrue(info['timeout_rerun']); self.assertFalse(info['timeout_confirmed'])
        self.assertEqual(sorted(t for _, t, _ in calls), [10, 10, 10 * F, 10 * F])

    def test_one_sided_nt_confirmed(self):
        info, calls = self.run_cs(lambda b, t, cap: e('timeout') if b == '/r' else e())
        self.assertEqual(info['outcome'], 'div'); self.assertFalse(info['equal'])
        self.assertTrue(info['timeout_rerun']); self.assertTrue(info['timeout_confirmed'])
        self.assertEqual(rq1.cap_sens_timeout(10, info), 10 * F)                   # kiểm ổn định ở trần lớn dùng timeout gấp 10

    def test_unobservable_status_is_infra(self):
        info, _ = self.run_cs(lambda b, t, cap: e('invalid_input', out=b'') if b == '/r' else e())
        self.assertEqual(info['outcome'], 'infra'); self.assertIsNone(info['equal'])

    def test_normal_equal_unchanged(self):
        info, calls = self.run_cs(lambda b, t, cap: e())
        self.assertEqual((info['outcome'], info['equal'], info['timeout_rerun']), ('equal', True, False))
        self.assertEqual([t for _, t, _ in calls], [10, 10])
        self.assertEqual(rq1.cap_sens_timeout(10, info), 10)

    def test_normal_div_unchanged(self):
        info, calls = self.run_cs(lambda b, t, cap: e(out=b'y\n') if b == '/r' else e())
        self.assertEqual((info['outcome'], info['equal'], info['timeout_rerun']), ('div', False, False))
        self.assertEqual(len(calls), 2)

    def test_compare_exe_default_cap_unchanged(self):
        f = FakeExe(lambda b, t, cap: e())
        with mock.patch.object(OB, 'run_exe', side_effect=f):
            OB.compare_exe('/c', '/r', [], '', 10)
        self.assertEqual([cap for _, _, cap in f.calls], [None, None])               # lần chạy chính: trần mặc định


# ---------------- library, mức hàm ----------------
class LibCapSens(unittest.TestCase):
    def run_cs(self, script):
        f = FakeLib(script)
        with mock.patch.object(rq1, '_rl', side_effect=f):
            info, c8, r8 = rq1.cap_sens_lib('/rb', '/c', '/r', '/v.json', 10, '/d/v.a')
        self.assertTrue(all(cap == BIG for _, _, cap, _ in f.calls))
        return info, f.calls

    def test_infra_at_large_cap(self):
        info, calls = self.run_cs(lambda side, t, cap: l(k1='infra') if side == 'R' else l())
        self.assertEqual(info['outcome'], 'infra'); self.assertIsNone(info['equal']); self.assertEqual(info['r_k1'], 'infra')
        self.assertEqual(len(calls), 2); self.assertFalse(info['timeout_rerun'])      # không chạy lại, không so

    def test_one_sided_nt_rerun_then_equal(self):
        info, calls = self.run_cs(lambda side, t, cap: l('Timeout') if (side == 'R' and t == 10) else l())
        self.assertEqual((info['outcome'], info['equal'], info['timeout_rerun'], info['timeout_confirmed']), ('equal', True, True, False))
        self.assertEqual(sorted(t for _, t, _, _ in calls), [10, 10, 10 * F, 10 * F])
        self.assertEqual(len({d for *_, d in calls}), 4)                             # file dump riêng cho lần chạy lại

    def test_one_sided_nt_confirmed(self):
        info, _ = self.run_cs(lambda side, t, cap: l('OutputLimit') if side == 'R' else l())
        self.assertEqual((info['outcome'], info['timeout_rerun'], info['timeout_confirmed']), ('div', True, True))

    def test_infra_on_rerun(self):
        info, _ = self.run_cs(lambda side, t, cap: (l('Timeout') if t == 10 else l(k1='infra')) if side == 'R' else l())
        self.assertEqual(info['outcome'], 'infra'); self.assertTrue(info['timeout_rerun'])

    def test_normal_unchanged(self):
        info, calls = self.run_cs(lambda side, t, cap: l())
        self.assertEqual((info['outcome'], info['equal'], info['timeout_rerun']), ('equal', True, False)); self.assertEqual(len(calls), 2)
        info, calls = self.run_cs(lambda side, t, cap: l(stdout='y') if side == 'R' else l())
        self.assertEqual((info['outcome'], info['equal']), ('div', False)); self.assertEqual(len(calls), 2)

    def test_stability_infra_is_none(self):
        f = FakeLib(lambda side, t, cap: l(k1='infra') if side == 'R' else l())
        with mock.patch.object(rq1, '_rl', side_effect=f):
            self.assertIsNone(rq1.cap_sens_stable_lib('/rb', '/c', '/r', '/v', 10, '/d/v.a', l(), l(stdout='y')))
        f = FakeLib(lambda side, t, cap: l(stdout='y') if side == 'R' else l())
        with mock.patch.object(rq1, '_rl', side_effect=f):
            self.assertTrue(rq1.cap_sens_stable_lib('/rb', '/c', '/r', '/v', 10 * F, '/d/v.a', l(), l(stdout='y')))
        self.assertTrue(all(t == 10 * F and cap == BIG for _, t, cap, _ in f.calls))


# ---------------- bộ đếm và bản ghi trong rq1_lib_case, rq1_exe_case ----------------
def _caps(div):
    p = div.replace('.jsonl', '.capsens.jsonl')
    return [json.loads(x) for x in open(p)] if os.path.exists(p) else []


class LibCaseCounters(unittest.TestCase):
    def run_case(self, big):
        """Lần chính: hai bên OutputLimit (cùng NT: khớp, chạm trần). big(side, timeout): quan sát ở trần lớn."""
        d = tempfile.mkdtemp(); vec = f'{d}/v0.json'; json.dump(dict(lib_state_in={'a': 1}, lib_state_out={}), open(vec, 'w'))
        div = f'{d}/out/div/B01_x__c__s0.jsonl'; os.makedirs(os.path.dirname(div))
        def rl(rb, root, p, timeout, rust, dump, cap=None, **k):
            return big('R' if rust else 'C', timeout) if cap == BIG else l('OutputLimit')
        with mock.patch.object(rq1.BD, 'build_lib_case', return_value=dict(runner_ok=True, c_ok=True, library='x', runner_bin='/rb')), \
             mock.patch.object(rq1.BD, 'build_rust_lib', return_value=dict(ok=True, dir='/r')), \
             mock.patch.object(rq1.BD, 'lib_root', return_value='/root'), mock.patch.object(rq1.BD, 'asan_preload', return_value=None), \
             mock.patch.object(rq1, '_lib_inputs', return_value=([(vec, 'vector')], None, 1)), \
             mock.patch.object(rq1, '_rl', side_effect=rl), \
             mock.patch.object(rq1, 'lib_san', return_value=dict(status='no_report', markers=[], attempts=1)):
            r = rq1.rq1_lib_case(d, 'B01_x', 'c', [dict(system='a', harvest_case='c')], 0, dict(n_inputs=1), 10, div, 't')
        self.assertEqual(r['status'], 'done'); self.assertEqual(r['pair_status'], {'a': 'P_test'})   # độ nhạy không đổi P_test
        return r['counts']['a'], _caps(div)

    def test_infra_not_new_div(self):
        cn, caps = self.run_case(lambda side, t: l(k1='infra') if side == 'R' else l())
        self.assertEqual((cn['cap_hit_match'], cn.get('cap_sens_infra_match'), cn.get('cap_sens_new_div', 0)), (1, 1, 0))
        self.assertEqual(caps, [])

    def test_one_sided_nt_rerun(self):
        cn, caps = self.run_case(lambda side, t: l('Timeout') if (side == 'R' and t == 10) else l())
        self.assertEqual((cn['cap_sens_timeout_rerun'], cn.get('cap_sens_new_div', 0), cn.get('cap_sens_infra_match', 0)), (1, 0, 0))
        self.assertEqual(caps, [])

    def test_new_div_normal(self):
        cn, caps = self.run_case(lambda side, t: l(stdout='y') if side == 'R' else l())
        self.assertEqual((cn['cap_sens_new_div'], cn.get('cap_sens_infra_match', 0)), (1, 0))
        self.assertEqual(len(caps), 1); self.assertTrue(caps[0]['stable']); self.assertEqual(caps[0]['cap_sens']['outcome'], 'div')

    def test_stability_infra_not_new_div(self):
        n = {'R': 0}
        def big(side, t):
            if side == 'R': n['R'] += 1
            return (l(stdout='y') if n['R'] == 1 else l(k1='infra')) if side == 'R' else l()
        cn, caps = self.run_case(big)
        self.assertEqual((cn.get('cap_sens_new_div', 0), cn['cap_sens_infra_match']), (0, 1)); self.assertEqual(caps, [])


class ExeCaseCounters(unittest.TestCase):
    def run_case(self, script):
        """script(binary, timeout, cap) cho run_exe giả. Một input."""
        d = tempfile.mkdtemp(); div = f'{d}/out/div/P01_x__c__s0.jsonl'; os.makedirs(os.path.dirname(div))
        X = [([], '', 'seed', 'S', None)]
        with mock.patch.object(rq1.BD, 'build_c_exe', return_value=dict(ok=True, bin='/c', sha256='h', preset=None)), \
             mock.patch.object(rq1.BD, 'build_rust_exe', return_value=dict(ok=True, bin='/r', sha256='r')), \
             mock.patch.object(rq1.insensitive, 'check', return_value=(False, {})), \
             mock.patch.object(rq1, 'gen_exe', return_value=(X, {})), \
             mock.patch.object(rq1, '_exe_san', return_value=dict(status='no_report', markers=[], attempts=1)), \
             mock.patch.object(OB, 'run_exe', side_effect=FakeExe(script)):
            r = rq1.rq1_exe_case('/b', 'P01_x', 'c', [dict(system='a', harvest_case='c')], 0, {}, 10, div, 't')
        self.assertEqual(r['status'], 'done')
        divs = [json.loads(x) for x in open(div)] if os.path.exists(div) else []
        return r['counts']['a'], _caps(div), divs

    @staticmethod
    def primary(b, t, cap):
        return e('output_limit', out=b'a\n' * 4)        # lần chính: hai bên chạm trần, prefix trùng (khớp)

    def test_infra_not_new_div(self):
        cn, caps, _ = self.run_case(lambda b, t, cap: (e('invalid_input', out=b'') if b == '/r' else e()) if cap == BIG
                                    else self.primary(b, t, cap))
        self.assertEqual((cn['cap_hit_match'], cn['cap_sens_infra_match'], cn.get('cap_sens_new_div', 0)), (1, 1, 0))
        self.assertEqual(caps, [])

    def test_one_sided_nt_rerun_then_equal(self):
        cn, caps, _ = self.run_case(lambda b, t, cap: (e('timeout') if (b == '/r' and t == 10) else e()) if cap == BIG
                                    else self.primary(b, t, cap))
        self.assertEqual((cn['cap_sens_timeout_rerun'], cn.get('cap_sens_new_div', 0)), (1, 0)); self.assertEqual(caps, [])

    def test_confirmed_new_div_stability_at_rerun_timeout(self):
        seen = []
        def script(b, t, cap):
            if cap != BIG: return self.primary(b, t, cap)
            seen.append(t); return e('timeout') if b == '/r' else e()
        cn, caps, _ = self.run_case(script)
        self.assertEqual(cn['cap_sens_new_div'], 1); self.assertEqual(len(caps), 1)
        self.assertTrue(caps[0]['cap_sens']['timeout_confirmed']); self.assertTrue(caps[0]['stable'])
        self.assertEqual(seen, [10, 10] + [10 * F] * (2 + 2 * rq1.STAB_REPS))        # kiểm ổn định ở timeout gấp 10

    def test_div_branch_infra_counted(self):
        # Lần chính: C chạm trần, Rust dừng sớm (một bên NT, xác nhận ở gấp 10): divergence; trần lớn: Rust không quan sát được.
        def script(b, t, cap):
            if cap == BIG: return e('invalid_input', out=b'') if b == '/r' else e()
            return e('output_limit') if b == '/c' else e(out=b'z\n')
        cn, caps, divs = self.run_case(script)
        self.assertEqual((cn['div'], cn['cap_hit_div'], cn['cap_sens_infra_div']), (1, 1, 1))
        self.assertEqual(len(divs), 1); self.assertIsNone(divs[0]['cap_sens']['equal']); self.assertEqual(divs[0]['cap_sens']['outcome'], 'infra')

    def test_normal_equal_unchanged(self):
        cn, caps, _ = self.run_case(lambda b, t, cap: e() if cap == BIG else self.primary(b, t, cap))
        self.assertEqual((cn['cap_hit_match'], cn.get('cap_sens_new_div', 0), cn.get('cap_sens_infra_match', 0),
                          cn.get('cap_sens_timeout_rerun', 0)), (1, 0, 0, 0))


if __name__ == '__main__':
    unittest.main()
