#!/usr/bin/env python3
"""Chạy lại census library trên máy đo chính (c7i.2xlarge) cho cùng môi trường với census executable EC2 (Le chọn 21/10).
Dùng nguyên census_lib.py và recheck_loss.py (không sửa hai file đó), chỉ đổi:
  - WORKERS do job đặt (1, tuần tự, như census-exe-ec2);
  - đầu ra ở $OUT (census-lib.jsonl, recheck-loss.jsonl); không ghi đè results/census-lib.jsonl gốc (giữ để đối chiếu);
  - tập kiểm lại hao hụt lấy từ census mới thay vì file gốc. Thủ tục kiểm lại giữ nguyên: tuần tự, 120 giây, 3 lần, alias .so
    khi lệch tên; gộp kết quả theo luật đăng ký trước docs/proposal/prereg-2026-10-20-retry-rule.md."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import census_lib as CL      # noqa: E402
import recheck_loss as RL    # noqa: E402

NEW = os.path.join(CL.OUT, 'census-lib.jsonl')


def targets():
    rows = [json.loads(l) for l in open(NEW)]
    return [r for r in rows if not r['pilot'] and not r['no_input'] and r.get('pub_passed') is True and not r.get('ours_passed')]


if __name__ == '__main__':
    CL.main()
    RL.targets = targets
    RL.main()
