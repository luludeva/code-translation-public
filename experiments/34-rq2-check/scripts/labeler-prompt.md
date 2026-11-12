# Prompt cố định cho người gán nhãn (exp 34, RQ2), ba lượt độc lập

Mỗi mục trong `experiments/34-rq2-check/results/evidence.md` là một vector kiểm thử mà bản dịch Rust bị chấm trượt trong evaluation gốc:
quan sát phía C (chương trình gốc) và phía Rust trên cùng input. Đọc thêm `docs/proposal/reporting-rules.md` (R14, R21) và
`docs/proposal/bnu-rules-v0.md` (chuẩn hoá N cho stderr, R-NaN; library so số thực sai số tương đối 1e-6, NaN bằng NaN). Không đọc
`key.jsonl`, kết quả đo khác hay nhãn của lượt khác.

Trả về đúng một dòng JSON mỗi mục, đủ mọi mục:
{"id": "...", "q1": "yes|no|unclear", "q2": ["status", "stdout", "stderr", "state"], "q3": "yes|no|unclear", "why": "<một câu>"}
- q1: sau luật so và chuẩn hoá đã đăng ký, quan sát Rust có khác C ở ít nhất một kênh được so không (yes = ủng hộ quyết định chấm trượt).
  Executable so trạng thái kết thúc, stdout, stderr; library so result, state ra, stdout, stderr.
- q2: các kênh khác nhau (rỗng nếu q1 là no).
- q3: có bằng chứng khác biệt đến từ harness hoặc môi trường (output bị cắt, giá trị phụ thuộc thời gian, PID, địa chỉ, đường dẫn, lỗi
  hạ tầng, C không ổn định qua các lần chạy) thay vì hành vi chương trình không.
- Không chắc thì unclear, ghi lý do.
