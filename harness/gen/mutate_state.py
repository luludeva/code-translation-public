#!/usr/bin/env python3
"""Bộ sinh input cho library (K2): đột biến `lib_state_in` của vector gốc theo cây kiểu, giữ các ràng buộc suy ra được.

Ràng buộc (K2b), suy ra trước khi sinh và ghi lại cho từng case:
  R-out:   trường được gán trong `run` (`self.x = ...`) là output; không đột biến, giữ giá trị của vector gốc.
  R-len:   trường nguyên f bằng độ dài của trường chứa g (Vec, Option<Vec>, CString, String) ở mọi vector gốc,
           và f > 0 ở ít nhất một vector -> f luôn đặt bằng len(g) sau khi đột biến g; không đột biến f độc lập.
  R-bound: trường nguyên f có 0 <= f <= N ở mọi vector gốc và f > 0 ở ít nhất một vector, với N là độ dài của
           một mảng cố định phần tử vô hướng cùng tầng -> f giới hạn trong [0, N].
  R-size:  trường nguyên f xuất hiện trong `run` dưới dạng `self.f as usize` (dùng làm kích thước cấp phát)
           -> f giới hạn trong [0, max(4 * max giá trị gốc, 64)].
Ràng buộc chỉ dựa trên một vector gốc được đánh dấu weak. Ràng buộc không suy ra được thì không lọc; hậu quả
(runner từ chối, C crash, sanitizer phía C báo lỗi) được đếm theo case ở bước chạy."""
import copy, json, random, re
from .libtypes import INTS

SIZE_CAP_MIN = 64
PRINTABLE = [chr(c) for c in range(0x20, 0x7f)] + ['\n', '\t']


def int_range(ty):
    bits, signed = ty[2], ty[3]
    return (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)


def clip(v, lo, hi): return max(lo, min(hi, v))


def length_of(v):
    if v is None: return 0
    if isinstance(v, (list, str)): return len(v)
    return None


def is_container(ty):
    k = ty[0]
    if k in ('vec', 'cstring', 'string'): return True
    if k == 'option': return ty[1][0] in ('vec', 'cstring', 'string')
    return False


class StateGen:
    def __init__(self, parsed, seeds, rng):
        self.fields = {f: ty for f, _, ty in parsed['fields']}
        self.order = [f for f, _, _ in parsed['fields']]
        self.seeds = seeds; self.rng = rng
        run = parsed.get('run_fn', '')
        self.constraints = []
        weak = len(seeds) < 2
        self.output = sorted({m.group(1) for m in re.finditer(r'self\.(\w+)\s*=(?!=)', run)} & set(self.fields))
        for f in self.output: self.constraints.append(dict(rule='R-out', field=f))
        self.len_of = {}   # f -> g
        self.bound = {}    # f -> (lo, hi, origin)
        ints = [f for f in self.order if self.fields[f][0] == 'int' and f not in self.output]
        for f in ints:
            for g in self.order:
                if g == f or not is_container(self.fields[g]): continue
                if (all(isinstance(s.get(f), int) and length_of(s.get(g)) == s.get(f) for s in seeds)
                        and any(s.get(f) > 0 for s in seeds)):
                    self.len_of[f] = g
                    self.constraints.append(dict(rule='R-len', field=f, container=g, weak=weak)); break
        for f in ints:
            if f in self.len_of: continue
            for g in self.order:
                ty = self.fields[g]
                if (ty[0] == 'array' and ty[1][0] in ('int', 'float', 'bool')
                        and all(isinstance(s.get(f), int) and 0 <= s[f] <= ty[2] for s in seeds) and any(s.get(f) > 0 for s in seeds)):
                    self.bound[f] = (0, ty[2], 'R-bound:' + g)
                    self.constraints.append(dict(rule='R-bound', field=f, array=g, hi=ty[2], weak=weak)); break
        for f in ints:
            if f in self.len_of or f in self.bound: continue
            if re.search(rf'self\.{re.escape(f)}\s+as\s+usize', run):
                mx = max([s.get(f, 0) for s in seeds if isinstance(s.get(f), int)] or [0])
                hi = max(4 * mx, SIZE_CAP_MIN)
                self.bound[f] = (0, hi, 'R-size')
                self.constraints.append(dict(rule='R-size', field=f, hi=hi))
        self.mutable = [f for f in self.order if f not in self.output and f not in self.len_of]

    # ---- giá trị mới theo kiểu ----
    def fresh(self, ty, depth=0):
        r = self.rng; k = ty[0]
        if k == 'int':
            lo, hi = int_range(ty); return r.choice([0, 1, clip(-1, lo, hi), lo, hi, r.randint(lo, hi), r.randint(clip(-100, lo, hi), 100)])
        if k == 'float': return r.choice([0.0, 1.0, -1.0, 0.5, r.uniform(-1e3, 1e3), r.uniform(-1, 1)])
        if k == 'bool': return r.random() < 0.5
        if k == 'enum': return r.choice(ty[2])
        if k in ('cstring', 'string'): return ''.join(r.choice(PRINTABLE) for _ in range(r.randint(0, 16)))
        if k == 'vec': return [self.fresh(ty[1], depth + 1) for _ in range(r.randint(0, 8 if depth else 16))]
        if k == 'option': return None if r.random() < 0.3 else self.fresh(ty[1], depth + 1)
        if k == 'box': return self.fresh(ty[1], depth + 1)
        if k == 'array': return [self.fresh(ty[1], depth + 1) for _ in range(ty[2])]
        if k == 'struct': return {f: self.fresh(ft, depth + 1) for f, ft in ty[2]}
        raise ValueError('kiểu không hỗ trợ: %r' % (ty,))

    # ---- đột biến một giá trị đã có ----
    def mutate(self, ty, v, bound=None):
        r = self.rng; k = ty[0]
        if k == 'int':
            lo, hi = int_range(ty)
            if bound: lo, hi = max(lo, bound[0]), min(hi, bound[1])
            v0 = v if isinstance(v, int) else 0
            return clip(r.choice([v0 + 1, v0 - 1, 0, 1, -1, lo, hi, r.randint(lo, hi), v0 * 2, v0 // 2]), lo, hi)
        if k == 'float':
            lim = 3.0e38 if ty[2] == 32 else 1.0e300
            v0 = float(v) if isinstance(v, (int, float)) else 0.0
            return clip(r.choice([v0 * 2, -v0, 0.0, -0.0, v0 + 1, v0 - 1, v0 / 3, 1e-30, 1e30, r.uniform(-1e3, 1e3)]), -lim, lim)
        if k == 'bool': return not v
        if k == 'enum': return r.choice([x for x in ty[2] if x != v] or ty[2])
        if k in ('cstring', 'string'):
            s = v if isinstance(v, str) else ''.join(chr(c & 0x7f) for c in (v or []) if c & 0x7f)
            op = r.choice(['ins', 'del', 'rep', 'empty', 'dup', 'fresh'])
            i = r.randint(0, len(s))
            if op == 'ins': return s[:i] + r.choice(PRINTABLE) + s[i:]
            if op == 'del' and s: return s[:i] + s[i + 1:]
            if op == 'rep' and s: i = min(i, len(s) - 1); return s[:i] + r.choice(PRINTABLE) + s[i + 1:]
            if op == 'empty': return ''
            if op == 'dup': return s + s
            return self.fresh(ty)
        if k == 'vec':
            lst = list(v or [])
            op = r.choice(['elem', 'append', 'delete', 'empty', 'dup'] if lst else ['append', 'fresh'])
            if op == 'elem': i = r.randrange(len(lst)); lst[i] = self.mutate(ty[1], lst[i]); return lst
            if op == 'append': lst.insert(r.randint(0, len(lst)), self.fresh(ty[1], 1)); return lst
            if op == 'delete': del lst[r.randrange(len(lst))]; return lst
            if op == 'empty': return []
            if op == 'dup': return lst + copy.deepcopy(lst)
            return self.fresh(ty)
        if k == 'option':
            if v is None: return self.fresh(ty[1])
            return None if r.random() < 0.3 else self.mutate(ty[1], v)
        if k == 'box': return self.mutate(ty[1], v)
        if k == 'array':
            lst = list(v); i = r.randrange(len(lst)) if lst else None
            if i is not None: lst[i] = self.mutate(ty[1], lst[i])
            return lst
        if k == 'struct':
            d = dict(v); f, ft = r.choice(ty[2]); d[f] = self.mutate(ft, d.get(f)); return d
        raise ValueError('kiểu không hỗ trợ: %r' % (ty,))

    def apply_constraints(self, st):
        for f, g in self.len_of.items(): st[f] = length_of(st.get(g))
        return st

    def one(self, seed_state):
        st = copy.deepcopy(seed_state); ops = []
        for _ in range(self.rng.choice([1, 1, 2, 3])):
            f = self.rng.choice(self.mutable)
            st[f] = self.mutate(self.fields[f], st.get(f), self.bound.get(f)); ops.append(f)
        return self.apply_constraints(st), ops

    def generate(self, n, max_attempts_factor=20):
        if not self.mutable or not self.seeds: return []
        out, seen = [], {json.dumps(s, sort_keys=True) for s in self.seeds}
        for _ in range(n * max_attempts_factor):
            if len(out) >= n: break
            si = self.rng.randrange(len(self.seeds))
            st, ops = self.one(self.seeds[si])
            key = json.dumps(st, sort_keys=True)
            if key in seen: continue
            seen.add(key); out.append(dict(state=st, seed_index=si, mutated=ops))
        return out
