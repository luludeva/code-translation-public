# Prompt cố định cho người gán nhãn (exp 33, Q-N1), ba lượt độc lập

Gán mỗi cặp trong `experiments/33-nonrep-evidence/results/population.json` vào đúng một nhóm theo Phụ lục A
(`writing/appendices/A-reproduction.tex`, mục "Groups of Non-Reproduced Decisions"): `oracle_drift`, `translation`, `undetected_ub`, `unknown`.
- `path` accepted: bản công bố đỗ nhưng tái lập trượt. `path` rejected: bản công bố trượt ở bước test nhưng tái lập đỗ.
- `translation` chỉ hợp lệ cho `path` accepted.
- `undetected_ub` chỉ khi đủ cả ba điều kiện của Phụ lục A, trong đó điều kiện 3 phải có kết quả chạy ma trận cấu hình bộ nhớ trong repo cho
  đúng cặp đó và cho thấy biến thiên; không có hoặc không biến thiên thì không được gán nhóm này.
- Không đủ căn cứ cho nhóm nào thì `unknown`.

Chỉ đọc các tài liệu sau (đường dẫn tương đối gốc repo /home/claude/wt-main) và file census/kết quả mà chúng dẫn tới:
writing/appendices/A-reproduction.tex; experiments/06-library-census/loss-and-reverse-analysis.md; experiments/06-library-census/notes.md;
experiments/06-library-census/task-manager-mechanism.md; experiments/06-library-census/results/ub-cond3-betagamma/ (nếu cần);
experiments/02-harvest-repro/output-differs-3-pairs.md; experiments/02-harvest-repro/census-notes.md;
experiments/02-harvest-repro/vectors-failed-check.md; experiments/07-library-controls/notes.md; docs/decision-log.md (các mục nhắc case).
Không đọc kết quả đo lượt chính (experiments/30-*, 31-*, 32-*) hay nhãn của lượt khác.

Trả về đúng một dòng JSON mỗi cặp, đủ 24 cặp:
{"kind": "exe|lib", "path": "accepted|rejected", "bundle": "...", "case": "...", "system": "...", "group": "...", "source": "<file:dòng hoặc mục làm căn cứ>", "why": "<một câu>"}
