#!/usr/bin/env python3
"""exp 36: chạy harness.rq1 --pilot trên đúng các bản dịch đích của một unit held-out (README, Thay đổi 2026-11-05, sửa khung).

Lý do: `harness.rq1.pilot_pairs` lấy P_rep trên case pilot (`harness.pairs.p_rep`, đòi pub_passed True), nên bản dịch bị evaluation
gốc chấm trượt không bao giờ được chạy; lượt đầu của exp 36 vì vậy không đo bản dịch đích nào. File này thay `pilot_pairs` bằng dòng
census pilot của các cặp (case, hệ) đích trong plan.json (đòi build_ok True, không lọc pub_passed), rồi gọi `harness.rq1.main` với
mọi tham số còn lại giữ nguyên. Không sửa harness/.
  python3 experiments/36-heldout/scripts/rq1_targets.py PLAN UNIT <tham số harness.rq1 ...>"""
import json, os, sys

sys.path.insert(0, os.getcwd())
from harness import pairs as PR  # noqa: E402
from harness import rq1 as R  # noqa: E402


def target_pairs(plan, unit):
    u = next(x for x in json.load(open(plan))['units'] if x['unit'] == unit)
    want = {(u['bundle'], u['case'], s) for s in u['systems']}
    rows = [dict(r, pilot=False, pilot_case=True, via='heldout_target') for r in PR.load(PR.DEFAULT[u['kind']]['census'])
            if r['pilot'] and (r['bundle'], r['tractor_case'], r['system']) in want]
    for r in rows: r['no_input'] = bool(r.get('no_input'))
    got = {(r['bundle'], r['tractor_case'], r['system']) for r in rows}
    assert got == want, f'thiếu dòng census cho {sorted(want - got)}'
    assert all(r.get('build_ok') for r in rows), 'bản dịch đích không build_ok trong census'
    return u['kind'], rows


def main():
    plan, unit, argv = sys.argv[1], sys.argv[2], sys.argv[3:]
    kind, rows = target_pairs(plan, unit)
    R.pilot_pairs = lambda k: rows if k == kind else []
    R.main(argv)


if __name__ == '__main__':
    main()
