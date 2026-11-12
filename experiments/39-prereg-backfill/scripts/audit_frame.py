#!/usr/bin/env python3
"""exp 39 B: khung, mẫu và phiếu cho library audit chạy bù (README mục B; post hoc, †). Không gán nhãn: Le đọc tay phiếu.
Chọn bản ghi theo L5 như harness.main_merge_v2 (bản ghi khác harness_error đầu tiên theo thứ tự shard; file div đi theo shard được chọn).
Với mỗi bản dịch D library (experiments/32-robustness-s0/results/D-lib.jsonl): lấy mọi divergence giữ lại của hệ đó ở các seed có
pair_status P_test. Khung: bản dịch mà mọi divergence giữ lại có nguồn khác `vector`. Kiểm: mọi bản dịch D có ít nhất một divergence giữ
lại (không thì dừng). Mẫu: toàn khung nếu không quá 50, không thì 50 phân tầng theo nhóm (B01, B02, P00, P01) theo tỉ lệ, phần dư chia
theo phần lẻ lớn nhất, chọn trong nhóm bằng random.Random(20261110). Mỗi bản dịch: 3 divergence đầu theo sha256 của
json.dumps(input, sort_keys=True, separators=(',', ':'), ensure_ascii=False), bỏ trùng input.
  python3 experiments/39-prereg-backfill/scripts/audit_frame.py RESULTS_DIR
Ghi RESULTS_DIR/audit-frame.json, audit-form.md (phiếu, trường dài bị cắt) và audit-items.jsonl.gz (bản đầy đủ từng mục)."""
import collections, gzip, hashlib, io, json, math, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v3c as V  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DLIB = f'{ROOT}/experiments/32-robustness-s0/results/D-lib.jsonl'
GROUPS = ('B01', 'B02', 'P00', 'P01')
SEED, CAP, PER = 20261110, 50, 3


def ih(inp): return hashlib.sha256(json.dumps(inp, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def short(x, n=600):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f' …[cắt, {len(s)} ký tự]'


def main(outdir):
    D = {tuple(json.loads(l)) for l in open(DLIB) if l.strip()}
    chosen, trees = {}, {}
    for job, cm in V.SHARDS['lib']:
        fc = V.full(cm); trees[job] = (fc, V.tree(fc, f'ci-out/{job}/div/'))
        for l in V.run('git', 'show', f'{fc}:ci-out/{job}/rq1-lib.jsonl').decode().splitlines():
            if not l.strip(): continue
            r = json.loads(l)
            if r.get('status') == 'harness_error': continue
            chosen.setdefault((r['bundle'], r['case'], r['seed']), (job, r))
    divs = collections.defaultdict(list)
    for (b, cs, sd), (job, r) in sorted(chosen.items()):
        want = {s for s, st in (r.get('pair_status') or {}).items() if st == 'P_test' and (b, cs, s) in D}
        if not want: continue
        fc, t = trees[job]; base = f'ci-out/{job}/div/{b}__{cs}__s{sd}.jsonl'
        blobs = ([t[base + '.gz']] if base + '.gz' in t else [t[p] for p in sorted(p for p in t if p.startswith(base + '.gz.part'))]
                 or [t[p] for p in sorted(p for p in t if p.startswith(base + '.part'))])
        if not blobs: continue
        with gzip.open(io.BytesIO(b''.join(V.run('git', 'cat-file', 'blob', x) for x in blobs)), 'rt') as f:
            for l in f:
                if not l.strip(): continue
                d = json.loads(l)
                if d.get('system') in want and d.get('retained'): divs[(b, cs, d['system'])].append(d)
    missing = sorted(D - set(divs))
    if missing: raise SystemExit(f'bản dịch D không có divergence giữ lại trong bản ghi chọn theo L5: {missing}')
    frame, excluded = [], {}
    for k in sorted(D):
        src = collections.Counter(d.get('source') for d in divs[k])
        if src.get('vector'): excluded['/'.join(k)] = dict(src)
        else: frame.append(k)
    grp = lambda k: k[0][:3]
    if len(frame) <= CAP: sample = list(frame)
    else:
        by = {g: [k for k in frame if grp(k) == g] for g in GROUPS}
        quota = {g: CAP * len(v) / len(frame) for g, v in by.items()}
        n = {g: math.floor(q) for g, q in quota.items()}
        for g in sorted(GROUPS, key=lambda g: -(quota[g] - n[g]))[:CAP - sum(n.values())]: n[g] += 1
        rng = random.Random(SEED); sample = []
        for g in GROUPS: sample += rng.sample(by[g], n[g])
        sample.sort()
    items = {}
    for k in sample:
        seen, out = set(), []
        for d in sorted(divs[k], key=lambda d: (ih(d.get('input')), d.get('key'))):
            h = ih(d.get('input'))
            if h in seen: continue
            seen.add(h); out.append(d)
            if len(out) == PER: break
        items[k] = out
    os.makedirs(outdir, exist_ok=True)
    json.dump(dict(rule='exp 39 B, library audit chạy bù (README); post hoc', n_D=len(D), n_frame=len(frame), n_sample=len(sample),
                   seed=SEED if len(frame) > CAP else None, frame=['/'.join(k) for k in frame], excluded_with_vector_source=excluded,
                   sample=['/'.join(k) for k in sample],
                   items={'/'.join(k): [dict(key=d['key'], input_sha256=ih(d.get('input')), source=d.get('source'), channels=d.get('channels'))
                                        for d in v] for k, v in items.items()},
                   sources=[f'{j}@{V.full(c)}' for j, c in V.SHARDS['lib']]),
              open(f'{outdir}/audit-frame.json', 'w'), indent=1, ensure_ascii=False)
    with gzip.open(f'{outdir}/audit-items.jsonl.gz', 'wt') as g:      # bản đầy đủ của từng mục (input, quan sát C, Rust không cắt)
        for k in sample:
            for d in items[k]: g.write(json.dumps(dict(translation='/'.join(k), **{x: d.get(x) for x in ('key', 'source', 'channels', 'input', 'c', 'r')}),
                                                  ensure_ascii=False) + '\n')
    with open(f'{outdir}/audit-form.md', 'w') as f:
        f.write('# Phiếu library audit (exp 39 B, post hoc, †)\n\n'
                f'Khung {len(frame)} trên |D| = {len(D)} bản dịch library; mẫu {len(sample)}. Đọc từng bản dịch theo thứ tự mục; với mỗi '
                'divergence trả lời một câu: input có thoả điều kiện ngầm của hàm C (tiền điều kiện mà code C giả định nhưng không kiểm) '
                'không? Ghi `có`, `không` hoặc `không rõ`, kèm dòng code C làm căn cứ. Gặp `có` thì dừng bản dịch đó. Bản dịch không có '
                'divergence nào `có` là "chưa thấy input hợp lệ". Không dùng LLM để gán nhãn.\n\n'
                'Mã nguồn C: `corpus/tractor/Public-Tests/<bundle>/<case>/` ở TRACTOR `37960ee`.\n\n')
        for i, k in enumerate(sample, 1):
            f.write(f'## {i}. {k[0]}/{k[1]}, hệ {k[2]}\n\n')
            for j, d in enumerate(items[k], 1):
                c, r = d.get('c') or {}, d.get('r') or {}
                cs_, rs_ = c.get('state_out') or {}, r.get('state_out') or {}
                dif = sorted(x for x in set(cs_) | set(rs_) if cs_.get(x) != rs_.get(x)) if isinstance(cs_, dict) and isinstance(rs_, dict) else '?'
                f.write(f'**{i}.{j}** `{d["key"]}` nguồn `{d.get("source")}`, kênh {d.get("channels")}, trường state khác nhau: {dif}\n\n'
                        f'- Input: `{short(d.get("input"))}`\n'
                        f'- C: result `{c.get("result")}`, state `{short(c.get("state_out"), 300)}`, stdout `{short(c.get("stdout"), 300)}`\n'
                        f'- Rust: result `{r.get("result")}`, state `{short(r.get("state_out"), 300)}`, stdout `{short(r.get("stdout"), 300)}`\n'
                        '- Thoả điều kiện ngầm (có/không/không rõ): \n- Căn cứ (file:dòng): \n\n')
    print(f'D={len(D)} khung={len(frame)} mẫu={len(sample)} loại vì có nguồn vector={len(excluded)} mục={sum(len(v) for v in items.values())}')


if __name__ == '__main__':
    main(sys.argv[1])
