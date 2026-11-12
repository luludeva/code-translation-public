#!/usr/bin/env python3
"""exp 36: trích số theo (unit, seed, bản dịch đích) từ đầu ra held-out để generator macro chỉ đọc file đã commit (sơ bộ, chưa kiểm tay).
Mỗi dòng: trạng thái bản ghi case của seed, số input của seed, số divergence giữ lại trên input sinh (nguồn khác seed, vector) và số
trong đó không chỉ khác ở stderr. Divergence của seed có bản ghi khác 'done' vẫn ghi ra (cột status cho biết) để không mất thông tin;
phép tính số chính, độ bền và tỉ lệ trần ở writing/scripts/gen-extra-macros.py tự chọn seed.
  python3 experiments/36-heldout/scripts/per_seed.py PLAN OUT > experiments/36-heldout/results/per-seed.json"""
import json, os, sys

sys.path.insert(0, os.getcwd())
from harness import metrics as HM  # noqa: E402

GEN = lambda d: HM.retained(d) and d.get('source') not in ('seed', 'vector')


def main(plan, out):
    P = json.load(open(plan)); rows = []
    for u in P['units']:
        cases, divs, _ = HM.load_rq1(f"{out}/{u['unit']}", u['kind'])
        for r in sorted((r for r in cases if (r['bundle'], r['case']) == (u['bundle'], u['case'])), key=lambda r: r['seed']):
            for s in u['systems']:
                g = [d for d in divs.get((u['bundle'], u['case'], s, r['seed']), []) if GEN(d)]
                rows.append(dict(unit=u['unit'], kind=u['kind'], case=f"{u['bundle']}/{u['case']}", system=s, seed=r['seed'],
                                 status=r['status'], pair_status=(r.get('pair_status') or {}).get(s), n_inputs=r.get('n_inputs'),
                                 gen_retained=len(g), gen_retained_not_stderr_only=sum(1 for d in g if d.get('channels') != ['stderr'])))
    print(json.dumps(dict(rule='exp 36 theo seed; nguồn: đầu ra run_local_v2.sh (OUT không commit), sơ bộ, chưa kiểm tay', rows=rows),
                     indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
