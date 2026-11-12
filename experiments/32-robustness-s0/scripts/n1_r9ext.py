#!/usr/bin/env python3
"""exp 32 (README.md): N1 (độ nhạy library, hai phía cùng thất bại) và chọn mẫu R9 mở rộng. Đọc div theo luồng như exp 31 sample.py.
Dùng (từ gốc repo, đặt HARNESS_P_REP_LIB_* như exp 31):
  python3 experiments/32-robustness-s0/scripts/n1_r9ext.py --merged-exe DIR --merged-lib DIR --out experiments/32-robustness-s0/results"""
import argparse, ast, collections, importlib.util, json, os, random, sys

sys.path.insert(0, os.getcwd())
from harness import metrics as HM

_s = importlib.util.spec_from_file_location('s31', 'experiments/31-r9-check/scripts/sample.py')
S31 = importlib.util.module_from_spec(_s); _s.loader.exec_module(S31)

SEED = 20261104
FAIL = {'UnknownFailure', 'Panic', 'SegmentationFault', 'Timeout', 'MemLimit'}


def both_fail(d):
    c, r = d.get('c') or {}, d.get('r') or {}
    return (c.get('result') in FAIL and r.get('result') in FAIL and c.get('result') != r.get('result')
            and not c.get('state_out') and not r.get('state_out'))


def old_sample():
    out = collections.defaultdict(set)
    for l in open('experiments/31-r9-check/results/key.jsonl'):
        k = json.loads(l)['slot']
        t = ast.literal_eval(k[:k.rindex(')') + 1])
        out['lib' if t[1].endswith('_lib') else 'exe'].add(t)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--merged-exe', required=True); ap.add_argument('--merged-lib', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    seeds = [0, 1, 2]; old = old_sample(); res = {}; picks = {}
    for kind, d in (('exe', a.merged_exe), ('lib', a.merged_lib)):
        D, P, _ = S31.compute_D(d, kind, seeds)
        res[f'{kind}_D'] = len(D); res[f'{kind}_P_test'] = P
        with open(f'{a.out}/D-{kind}.jsonl', 'w') as f:
            for k in D: f.write(json.dumps(list(k)) + '\n')
        if kind == 'lib':
            new = [k for k in D if k not in old['lib']]
        else:
            cand = [k for k in D if k not in old['exe'] and k[2] != S31.FULL]
            by, alloc = S31.allocate(cand, 30)
            rng = random.Random(f'{SEED}/exe')
            new = [k for s in sorted(alloc) for k in sorted(rng.sample(sorted(by[s]), alloc[s]))]
        for k in new: picks[k] = kind
        res[f'{kind}_new_sample'] = len(new)
    # một lượt đọc: N1 (lib) và reservoir cho mẫu mới
    Dlib = set()
    D_lib, _, _ = S31.compute_D(a.merged_lib, 'lib', seeds); Dlib = set(D_lib)
    n_ret = collections.Counter(); n_bf = collections.Counter(); chosen = {}; seen = collections.Counter()
    for kind, d in (('exe', a.merged_exe), ('lib', a.merged_lib)):
        for r in S31.stream(d, kind):
            if not HM.retained(r): continue
            k = (r['bundle'], r['case'], r['system'])
            if kind == 'lib' and k in Dlib:
                n_ret[k] += 1; n_bf[k] += both_fail(r)
            if k in picks:
                seen[k] += 1
                if seen[k] == 1 or random.Random(f'{SEED}/{S31.tkey((k,))}/{seen[k]}').random() < 1.0 / seen[k]:
                    g, code = HM.bnu_rule(r)
                    chosen[k] = dict(kind=kind, part='R9ext', slot=S31.tkey((k,)), div=r, script_rule=code, script_group=g)
    only_bf = sorted(k for k in Dlib if n_ret[k] and n_bf[k] == n_ret[k])
    res['N1'] = dict(rule='README.md mục N1', lib_D=len(Dlib), translations_only_both_fail=len(only_bf), ids=[list(k) for k in only_bf],
                     D_without=len(Dlib) - len(only_bf), P_test=res['lib_P_test'],
                     translations_any_both_fail=sum(1 for k in Dlib if n_bf[k]))
    items = sorted(chosen.values(), key=lambda x: (x['kind'], x['slot']))
    with open(f'{a.out}/r9ext-items.jsonl', 'w') as f, open(f'{a.out}/r9ext-key.jsonl', 'w') as g:
        for i, it in enumerate(items):
            it['id'] = f'x{it["kind"]}-{i:03d}'
            f.write(json.dumps(dict(id=it['id'], kind=it['kind'], part=it['part'], div=it['div']), ensure_ascii=False) + '\n')
            g.write(json.dumps(dict(id=it['id'], slot=it['slot'], script_rule=it['script_rule'], script_group=it['script_group'])) + '\n')
    res['r9ext_items'] = len(items)
    json.dump(res, open(f'{a.out}/n1-r9ext.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in res.items() if k != 'N1'} | {'N1': {x: y for x, y in res['N1'].items() if x != 'ids'}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
