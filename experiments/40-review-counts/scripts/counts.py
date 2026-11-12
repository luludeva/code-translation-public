#!/usr/bin/env python3
"""exp 40: MR-01 và MR-04 (README; post hoc, sơ bộ, chưa kiểm tay). Chỉ đọc bản ghi S₀ trên nhánh results.
  python3 experiments/40-review-counts/scripts/counts.py > experiments/40-review-counts/results/counts.json"""
import collections, gzip, io, json, os, sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, f'{ROOT}/experiments/39-prereg-backfill/scripts')
import v3c as V  # noqa: E402

RQ2 = ('rq2-main', 'b757f4d')
DFILE = f'{ROOT}/experiments/32-robustness-s0/results/D-{{}}.jsonl'


def mr01():
    fc = V.full(RQ2[1]); out = {}
    for kind in ('exe', 'lib'):
        n_agree = n_flag = n_cross = n_mismatch = 0; f_aff, f_tot = set(), set()
        for l in V.run('git', 'show', f'{fc}:ci-out/rq2-main/{kind}/rq2-{kind}.jsonl').decode().splitlines():
            if not l.strip(): continue
            r = json.loads(l)
            if r.get('outcome') == 'behavioral_agreement': f_tot.add(r['key'])
            for v in r.get('vectors') or []:
                if v.get('outcome') != 'agrees': continue
                n_agree += 1
                flag = v.get('c_stable') is not True
                runs = ((v.get('obs') or {}).get('runs')) or []
                # bỏ trường thời gian (secs): thời gian chạy luôn khác giữa các lần, không phải quan sát được so
                cs = [json.dumps({k: w for k, w in ((((x or {}).get('first') or {}).get('c')) or {}).items() if k != 'secs'}, sort_keys=True)
                      for x in runs]
                cross = len(set(cs)) > 1 if cs else None
                n_flag += flag; n_cross += bool(cross); n_mismatch += (cross is not None and cross != flag)
                if (flag or cross) and r.get('outcome') == 'behavioral_agreement': f_aff.add(r['key'])
        out[kind] = dict(agrees_vectors=n_agree, c_unstable_flag=n_flag, c_unstable_crosscheck=n_cross, flag_crosscheck_mismatch=n_mismatch,
                         F_translations=len(f_tot), F_affected=len(f_aff), F_keys=sorted(f_tot))
    return out


def unit(args):
    kind, blobs, want = args
    c = collections.Counter(); per = collections.defaultdict(collections.Counter)
    if not blobs: return c, {}
    with gzip.open(io.BytesIO(b''.join(V.run('git', 'cat-file', 'blob', x) for x in blobs)), 'rb') as f:
        for l in f:
            if not l.strip(): continue
            d = V.loads(l)
            s = d.get('system')
            if s not in want or not d.get('retained'): continue
            if kind == 'exe':
                mem = (d.get('c_status') == 'mem_limit') != (d.get('r_status') == 'mem_limit')
                xfsz = d.get('c_rc') == -25 or d.get('r_rc') == -25
            else:
                cc, rr = d.get('c') or {}, d.get('r') or {}
                mem = (cc.get('result') == 'MemLimit') != (rr.get('result') == 'MemLimit')
                xfsz = cc.get('rc') == -25 or rr.get('rc') == -25
            per[s]['retained'] += 1
            if mem: per[s]['mem_one_side'] += 1
            if xfsz: per[s]['sigxfsz'] += 1
            if mem or xfsz: per[s]['resource'] += 1
    return c, {s: dict(v) for s, v in per.items()}


def mr04(workers=2):
    out = {}
    for kind in ('exe', 'lib'):
        D = {tuple(json.loads(l)) for l in open(DFILE.format(kind)) if l.strip()}
        chosen, trees = {}, {}
        for job, cm in V.SHARDS[kind]:
            fc = V.full(cm); trees[job] = (fc, V.tree(fc, f'ci-out/{job}/div/'))
            for l in V.run('git', 'show', f'{fc}:ci-out/{job}/rq1-{kind}.jsonl').decode().splitlines():
                if not l.strip(): continue
                r = json.loads(l)
                if r.get('status') == 'harness_error': continue
                chosen.setdefault((r['bundle'], r['case'], r['seed']), (job, r))
        jobs, keys = [], []
        for (b, cs, sd), (job, r) in sorted(chosen.items()):
            want = {s for s, st in (r.get('pair_status') or {}).items() if st == 'P_test' and (b, cs, s) in D}
            if not want: continue
            fc, t = trees[job]; base = f'ci-out/{job}/div/{b}__{cs}__s{sd}.jsonl'
            blobs = ([t[base + '.gz']] if base + '.gz' in t else [t[p] for p in sorted(p for p in t if p.startswith(base + '.gz.part'))]
                     or [t[p] for p in sorted(p for p in t if p.startswith(base + '.part'))])
            jobs.append((kind, blobs, want)); keys.append((b, cs))
        agg = collections.defaultdict(collections.Counter)
        with ProcessPoolExecutor(workers) as ex:
            for (b, cs), (_, per) in zip(keys, ex.map(unit, jobs)):
                for s, v in per.items(): agg[(b, cs, s)].update(v)
        missing = sorted('/'.join(k) for k in D if not agg[k]['retained'])
        tot = collections.Counter()
        for k in D: tot.update(agg[k])
        only = sorted('/'.join(k) for k in D if agg[k]['retained'] and agg[k]['resource'] == agg[k]['retained'])
        out[kind] = dict(D=len(D), D_without_retained=missing, retained_div=tot['retained'], resource_div=tot['resource'],
                         mem_one_side_div=tot['mem_one_side'], sigxfsz_div=tot['sigxfsz'], translations_resource_only=len(only),
                         translations_resource_only_keys=only,
                         translations_any_resource=sum(1 for k in D if agg[k]['resource']))
    return out


if __name__ == '__main__':
    print(json.dumps(dict(rule='exp 40, MR-01 và MR-04 (README); post hoc, sơ bộ, chưa kiểm tay', mr01=mr01(), mr04=mr04(),
                          sources=[f'{j}@{V.full(c)}' for k in ('exe', 'lib') for j, c in V.SHARDS[k]] + [f'{RQ2[0]}@{V.full(RQ2[1])}']),
                     indent=1, ensure_ascii=False))
