# Prompt cố định cho người gán nhãn LLM (R9/R18), ba lượt độc lập

Bạn kiểm một mẫu divergence giữa binary C gốc và binary Rust dịch từ nó. Mỗi mục trong file phiếu là một lần chạy cùng input trên hai phía.
Chỉ dựa vào bằng chứng trong phiếu và hai tài liệu luật: `docs/proposal/bnu-rules-v0.md` (luật B/N/U, khớp đầu tiên thắng; chuẩn hoá N
cho stderr và R-NaN) và `docs/proposal/reporting-rules.md`. Không đọc file khoá, không đọc nhãn của lượt khác, không đoán nhãn của script.

Với mỗi mục, trả lời đúng một dòng JSON:
{"id": "...", "q1": "yes|no|unclear", "q2": "<mã luật, ví dụ N3-line>", "q3": "yes|no|unclear", "why": "<một câu căn cứ cho q1 và q3>"}

- q1 (khác biệt thật): sau khi áp các luật chuẩn hoá đã đăng ký, hai phía có khác nhau ở ít nhất một kênh được so (trạng thái kết thúc,
  stdout, stderr; library thêm k1 và state_out) không.
- q2 (luật B/N/U): duyệt bảng luật theo thứ tự trong bnu-rules-v0.md (mục 2 cho executable, mục 3 cho library), ghi mã của luật đầu tiên
  khớp. Mục đã được lọc: sanitizer phía C không báo UB, khác biệt ổn định qua lần chạy lại.
- q3 (hiện vật harness): có bằng chứng khác biệt đến từ harness hoặc môi trường thay vì hành vi chương trình không: output bị cắt
  (`truncated`), vượt ngân sách một phía mà không xác nhận, giá trị phụ thuộc thời gian, PID, địa chỉ bộ nhớ, đường dẫn, lỗi hạ tầng của
  runner. Hành vi khác do bản dịch (kể cả do UB phía Rust) là `no`.
- Không chắc thì `unclear`, ghi lý do. Không bỏ mục nào.
