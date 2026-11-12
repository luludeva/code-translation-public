# Module sinh input chép từ thí nghiệm (decision-log 2026-10-21, Q1)

Chép nguyên văn; chỉ đổi dòng import sang import tương đối trong package. Thí nghiệm cũ giữ nguyên.
V7 (hồi quy pilot) kiểm việc gom code không đổi kết quả.

| Module | Nguồn | Git blob của nguồn lúc chép (`main` `777db40`) |
|---|---|---|
| `v0.py` | `experiments/04-coverage-pilot/scripts/diffharness_v0.py` | `f46404bc0bbb1de4d6c8bdc0639b3a71a4880d3b` |
| `v1.py` | `experiments/04-coverage-pilot/scripts/harness_v1.py` | `56723996e894920f730cd70cf0c71f631fb2de62` |
| `v2_exe.py` | `experiments/08-harness-v2/scripts/harness_v2_exe.py` | `30781601c63218a6e1bf487aabe8db339ff2c41d` |
| `cdict.py` | `experiments/08-harness-v2/scripts/cdict.py` | `d1dea5829c6f71227ae8d8e3d61fe4517561d96a` |
| `libtypes.py` | `experiments/05-library-spike/scripts/libtypes.py` | `162e2fc109ced08dd16a44c83659feafb97c4bf1` |
| `mutate_state.py` | `experiments/05-library-spike/scripts/mutate_state.py` | `4e102b4288b4f457d73e88f815618ab6393eca93` |
| `stategen_v2.py` | `experiments/08-harness-v2/scripts/stategen_v2.py` | `86b21ab89f6aee3d05fa867178402bb008c3189e` |

Hàm `run`, `same`, `encode` trong `v0.py`, `v1.py` không được package dùng: thực thi và so sánh nằm ở `harness/observe.py`.
