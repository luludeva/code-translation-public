#!/usr/bin/env python3
"""Bộ sinh input library cho harness v2 (`docs/proposal/harness-v2-design.md` mục 2): StateGen cộng L1a và L2a.

Chia ngân sách N input mỗi case:
  - `random` 50%: đúng các input đầu tiên mà StateGen v1 sinh với cùng seed (v2 chứa một tiền tố của v1, nên so sánh v1 với v2
    chỉ khác ở phần thay thế);
  - `dict` 30%: như phép đột biến của StateGen nhưng giá trị lá kiểu số lấy từ dictionary hằng số (cdict.py), chuỗi lấy từ chuỗi hằng;
  - `sweep` 20%: quét đều trường số nguyên có miền ≤ 64 giá trị (runner có `self.f %= N`, hoặc ràng buộc R-bound/R-size đã suy ra);
    các trường khác lấy từ seed rồi đột biến như cũ. Case không có trường như vậy: phần này trả về `random`.
Nếu dict hoặc sweep không sinh đủ input khác nhau (ví dụ case không có hằng số nào), phần thiếu bù bằng các input tiếp theo của v1,
để v1 và v2 luôn có cùng ngân sách.
Mỗi input mang nhãn nguồn `source`. Tất định theo (seed, dictionary)."""
import copy, json, math, os, random, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
from .mutate_state import StateGen, int_range, clip
from .libtypes import eval_len

P_DICT, P_SWEEP, SMALL_MAX = 0.3, 0.2, 64


def small_fields(gen, parsed):
    """{trường: (lo, hi, nguồn)} cho trường số nguyên có miền hiệu dụng ≤ SMALL_MAX giá trị."""
    out = {}
    for m in re.finditer(r'self\.(\w+)\s*%=\s*([^;]+);', parsed.get('run_fn', '')):
        f, expr = m.group(1), m.group(2).split(' as ')[0].strip()
        n = eval_len(expr, parsed.get('consts', {}))
        if f in gen.fields and gen.fields[f][0] == 'int' and n and 0 < n <= SMALL_MAX:
            out[f] = (0, n - 1, f'mod:{expr}')
    for f, (lo, hi, origin) in gen.bound.items():
        if f not in out and f in gen.mutable and hi - lo + 1 <= SMALL_MAX:
            out[f] = (lo, hi, origin)
    return out


class StateGenV2(StateGen):
    def __init__(self, parsed, seeds, rng, cdict):
        super().__init__(parsed, seeds, rng)
        self.parsed = parsed
        self.nums = [x['v'] for x in cdict.get('values', [])]
        self.strs = list(cdict.get('strings', []))
        self.small = small_fields(self, parsed)

    # ---- giá trị lá lấy từ dictionary ----
    def dict_leaf(self, ty, v, bound=None):
        r = self.rng; k = ty[0]
        if k == 'int' and self.nums:
            lo, hi = int_range(ty)
            if bound: lo, hi = max(lo, bound[0]), min(hi, bound[1])
            x = r.choice(self.nums)
            if isinstance(x, float):
                if not math.isfinite(x): return self.mutate(ty, v, bound)
                x = int(x)
            return clip(x, lo, hi)
        if k == 'float' and self.nums:
            lim = 3.0e38 if ty[2] == 32 else 1.0e300
            return clip(float(r.choice(self.nums)), -lim, lim)
        if k in ('cstring', 'string') and self.strs:
            return r.choice(self.strs)
        return None

    def mutate_dict(self, ty, v, bound=None):
        """Như StateGen.mutate, nhưng tới lá kiểu số hoặc chuỗi thì lấy từ dictionary."""
        r = self.rng; k = ty[0]
        leaf = self.dict_leaf(ty, v, bound)
        if leaf is not None: return leaf
        if k == 'vec':
            lst = list(v or [])
            if lst and r.random() < 0.7:
                i = r.randrange(len(lst)); lst[i] = self.mutate_dict(ty[1], lst[i]); return lst
            lst.insert(r.randint(0, len(lst)), self.mutate_dict(ty[1], self.fresh(ty[1], 1))); return lst
        if k == 'array':
            lst = list(v or [])
            if lst: i = r.randrange(len(lst)); lst[i] = self.mutate_dict(ty[1], lst[i])
            return lst
        if k == 'option':
            return self.mutate_dict(ty[1], v if v is not None else self.fresh(ty[1]))
        if k == 'box': return self.mutate_dict(ty[1], v)
        if k == 'struct':
            d = dict(v or {}); f, ft = r.choice(ty[2]); d[f] = self.mutate_dict(ft, d.get(f)); return d
        return self.mutate(ty, v, bound)

    def one_dict(self, seed_state):
        st = copy.deepcopy(seed_state); ops = []
        for _ in range(self.rng.choice([1, 1, 2, 3])):
            f = self.rng.choice(self.mutable)
            st[f] = self.mutate_dict(self.fields[f], st.get(f), self.bound.get(f)); ops.append(f)
        return self.apply_constraints(st), ops

    def one_sweep(self, seed_state, f, value):
        st = copy.deepcopy(seed_state); ops = [f]
        others = [g for g in self.mutable if g != f]
        if others:
            for _ in range(self.rng.choice([0, 1, 1, 2])):
                g = self.rng.choice(others); st[g] = self.mutate(self.fields[g], st.get(g), self.bound.get(g)); ops.append(g)
        st[f] = value
        return self.apply_constraints(st), ops

    def generate_v2(self, n, v1_seed):
        """n input: tiền tố StateGen v1 (seed v1_seed) cho phần random, cộng phần dict và sweep sinh bằng self.rng."""
        if not self.mutable or not self.seeds: return []
        n_sweep = round(P_SWEEP * n) if self.small else 0
        n_dict = round(P_DICT * n); n_rand = n - n_dict - n_sweep
        v1 = StateGen(self.parsed, self.seeds, random.Random(v1_seed)).generate(n_rand)
        out = [dict(x, source='random') for x in v1]
        seen = {json.dumps(s, sort_keys=True) for s in self.seeds} | {json.dumps(x['state'], sort_keys=True) for x in out}

        def push(st, si, ops, src):
            key = json.dumps(st, sort_keys=True)
            if key in seen: return False
            seen.add(key); out.append(dict(state=st, seed_index=si, mutated=ops, source=src)); return True

        got, tries = 0, 0
        while got < n_dict and tries < n_dict * 20:
            tries += 1; si = self.rng.randrange(len(self.seeds))
            st, ops = self.one_dict(self.seeds[si]); got += push(st, si, ops, 'dict')
        plan = [(f, v) for f, (lo, hi, _) in sorted(self.small.items()) for v in range(lo, hi + 1)]
        got, k, tries = 0, 0, 0
        while plan and got < n_sweep and tries < n_sweep * 20:
            tries += 1; f, v = plan[k % len(plan)]; k += 1
            si = self.rng.randrange(len(self.seeds))
            st, ops = self.one_sweep(self.seeds[si], f, v); got += push(st, si, ops, 'sweep')
        if len(out) < n:   # dict hoặc sweep không đủ input khác nhau (ví dụ case không có hằng số): bù bằng phần tiếp theo của v1
            for x in StateGen(self.parsed, self.seeds, random.Random(v1_seed)).generate(n * 2)[n_rand:]:
                if len(out) >= n: break
                push(x['state'], x['seed_index'], x['mutated'], 'random')
        return out


def typed_seed(parsed, seed):
    """Một state dựng từ kiểu của từng trường (StateGen.fresh), tất định theo seed (dãy riêng seed + 2000)."""
    g = StateGen(parsed, [], random.Random(seed + 2000))
    return {f: g.fresh(g.fields[f]) for f in g.order}


def generate(parsed, seeds, cdict, n, seed):
    """API dùng chung: trả về danh sách {state, seed_index, mutated, source}. v1 dùng seed, phần mới dùng seed + 1000.
    Không có vector (decision-log 2026-10-14, Le giữ 25/10): bộ sinh sinh từ kiểu dữ liệu. Input đầu là một state dựng từ kiểu (nguồn
    'typed'), làm seed duy nhất cho phần còn lại; mọi input mang seed_index None (không có stdin, env của vector để giữ)."""
    if seeds:
        return StateGenV2(parsed, seeds, random.Random(seed + 1000), cdict).generate_v2(n, seed)
    if not parsed.get('fields') or n <= 0: return []
    ts = typed_seed(parsed, seed)
    g = StateGenV2(parsed, [ts], random.Random(seed + 1000), cdict)
    if not g.mutable: return []
    rest = g.generate_v2(n - 1, seed)
    return [dict(state=ts, seed_index=None, mutated=list(g.order), source='typed')] + [dict(x, seed_index=None) for x in rest]
