# B0: 36 marker C-san (ref ac5a1c595403941e619c0495075bdb7202eaf8e1, run 42451406530)

Sinh bởi `scripts/b0_extract.py`. Không sửa tay. Cột: có `R_X86_64_PC32`, có `recompile with -fPIC`, có `libsphincs_core.so`, các dòng `FAILED:`, số dòng "Auto packing" của git trong 2000 ký tự cuối.

| Case | ok | PC32 | -fPIC | lib | FAILED | git noise |
|---|---|---|---|---|---|---|
| 005_sphincs_PQCgenKAT_sign_blake_128f_simple | False | 1 | 1 | 0 | libsphincs_core_det.so | 0 |
| 006_sphincs_PQCgenKAT_sign_blake_128f_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 007_sphincs_PQCgenKAT_sign_blake_128s_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 008_sphincs_PQCgenKAT_sign_blake_128s_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 009_sphincs_PQCgenKAT_sign_blake_192f_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 010_sphincs_PQCgenKAT_sign_blake_192f_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 011_sphincs_PQCgenKAT_sign_blake_192s_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 012_sphincs_PQCgenKAT_sign_blake_192s_robust | False | 1 | 1 | 0 | libsphincs_core_det.so | 0 |
| 013_sphincs_PQCgenKAT_sign_blake_256f_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 014_sphincs_PQCgenKAT_sign_blake_256f_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 015_sphincs_PQCgenKAT_sign_blake_256s_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 016_sphincs_PQCgenKAT_sign_blake_256s_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 029_sphincs_PQCgenKAT_sign_shake_128f_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 030_sphincs_PQCgenKAT_sign_shake_128f_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 031_sphincs_PQCgenKAT_sign_shake_128s_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 032_sphincs_PQCgenKAT_sign_shake_128s_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 033_sphincs_PQCgenKAT_sign_shake_192f_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 034_sphincs_PQCgenKAT_sign_shake_192f_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 035_sphincs_PQCgenKAT_sign_shake_192s_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 036_sphincs_PQCgenKAT_sign_shake_192s_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 037_sphincs_PQCgenKAT_sign_shake_256f_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 038_sphincs_PQCgenKAT_sign_shake_256f_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 039_sphincs_PQCgenKAT_sign_shake_256s_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 040_sphincs_PQCgenKAT_sign_shake_256s_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 041_sphincs_PQCgenKAT_sign_haraka_128f_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 042_sphincs_PQCgenKAT_sign_haraka_128f_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 043_sphincs_PQCgenKAT_sign_haraka_128s_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 044_sphincs_PQCgenKAT_sign_haraka_128s_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 045_sphincs_PQCgenKAT_sign_haraka_192f_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 046_sphincs_PQCgenKAT_sign_haraka_192f_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 047_sphincs_PQCgenKAT_sign_haraka_192s_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 048_sphincs_PQCgenKAT_sign_haraka_192s_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 049_sphincs_PQCgenKAT_sign_haraka_256f_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 050_sphincs_PQCgenKAT_sign_haraka_256f_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 051_sphincs_PQCgenKAT_sign_haraka_256s_simple | False | 1 | 1 | 1 | libsphincs_core.so | 0 |
| 052_sphincs_PQCgenKAT_sign_haraka_256s_robust | False | 1 | 1 | 1 | libsphincs_core.so | 0 |

- ref: ac5a1c595403941e619c0495075bdb7202eaf8e1
- run_id: 42451406530
- markers_san: 36
- san_ok_false: 36
- markers_c: 36
- c_ok_true: 36
- sig: 36
- sig_lib: 34
- sig_no_lib: 2
- sig_no_lib_noise: 0
- sig_no_lib_det_only: 2
- ninja_stopped: 36
- sig_no_lib_trunc: 2
- log_cap: 2000
- target_cases: 36
- target_with_san_marker: 36
- đối chiếu: summary_sig=True, summary_lib=True, branch_c=True, machine=True, all_targets=True
