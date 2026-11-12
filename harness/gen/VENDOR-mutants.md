# Module sinh mutant chép từ thí nghiệm (kế hoạch A3, A7 mục 2.3, Le duyệt 25/10)

Cùng quy ước với `VENDOR.md`: chép nguyên văn các khối dùng lại; thí nghiệm cũ giữ nguyên. Khối được cắt bằng `ast` theo dòng của file
nguồn; `tests/test_mutants.py` (lớp `Vendored`) kiểm mỗi hàm và hằng chép vẫn trùng nguyên văn file nguồn trong repo.

| Module | Nguồn | Git blob của nguồn lúc chép (`main` `7ff87fd`) | Khối chép nguyên văn |
|---|---|---|---|
| `mutants_v1.py` | `experiments/04-coverage-pilot/scripts/mutants_v1.py` (commit cuối `ba662ef`) | `5acf0c5509ddc8fbab22a3fac9732de90ac7725f` | `OPS`, `LIT`, `sites_of`, `vec_fails` |
| `mutants_lib.py` | `experiments/07-library-controls/scripts/mutants_lib.py` (commit cuối `a062995`) | `b2485145b969d7f6fb3c28bc9f305fc92f029554` | `OPS`, `LIT`, dòng `TOOLS`, `sites_of`, `vec_fails`, `coverage` |
| `mutants_cov_exe.py` | `experiments/08-harness-v2/scripts/accept_exe.py` (commit cuối `7f17883`) | `6fda82954605889b39815abb1c17c2305b1921ac` | `covered_lines`, `sites_cov` |

Phần khác nguồn, ngoài các khối chép:
- Import: bỏ import của thí nghiệm (`diffharness_v0`, `harness_v1`, `spike_lib`, `libtypes`, `mutate_state`). `mutants_cov_exe` lấy
  `run` từ `gen/v1.py` (bản chép nguyên văn `harness_v1.py`) và `TOOLS` từ `mutants_lib`; `harness/mutants.py` lấy seed vector từ
  `gen/v0.load_vectors` như exp 08.
- Biến module thay hằng của script: `mutants_v1.SEED` (nguồn: dòng `N, SEED, LAYER_BUDGET, TIMEOUT = 12, 0, 3000, 2`), `RUNNER` (biến
  môi trường RUNNER vẫn thắng; mặc định đổi sang `$CORPUS/cando2/target/release/cando_binrunner` mà `ci/setup-corpus.sh` dựng);
  `mutants_lib.B`, `SEED`; `mutants_cov_exe.B`, `H`, `HCASE`, `MUT_SEED`. `harness/mutants.py` gán trước mỗi lần gọi và trả seed về như cũ.
- `mutants_lib.make_root`: nguồn dựng thư mục gốc kiểu exp 05 (`B/c/<case>`, thêm tên vào `S.SYSTEMS`); thay bằng hàm cùng chữ ký gọi
  `build.lib_root(B, _INFO[tp], 'c', rust_dir, tag=name)`. Chỉ `coverage` gọi hàm này (tag `cov-<hệ>`).
- `mutants_lib.TOOLS`: dòng nguồn đặt trong `try`, máy không có rustc thì bằng chuỗi rỗng (module vẫn import được).

Hành vi giữ nguyên có chủ ý (để bộ `a7-seed1` sinh lại trùng exp 08):
- Executable xáo mọi vị trí rồi mới lọc dòng được chạy (`sites_cov`); library lọc rồi xáo (`mutants_lib.sites_of`).
- Coverage build bản gốc luôn với `RUSTC_BOOTSTRAP=1` (như exp 08). Build mutant thì theo `build._cargo` (chỉ khi có `#![feature`).
