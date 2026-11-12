# Prompt cố định cho người gán nhãn LLM (exp 32 B3), ba lượt độc lập

Bạn xét từng case trong `experiments/32-robustness-s0/results/b3-cases.json`: một chương trình C (executable hoặc library) của corpus TRACTOR.
Mã nguồn ở thư mục gốc `TRACTOR_ROOT/<bundle>/<case>/` (đường dẫn file liệt kê trong trường `files`, tương đối với TRACTOR_ROOT). Đọc mã C và
mọi mô tả kèm theo (README, chú thích đầu file, tên case). Không đọc thư mục `test_vectors`, không đọc kết quả đo hay file nào ngoài corpus.

Câu hỏi: case có được thiết kế quanh hành vi C không xác định (undefined behavior), implementation-defined hoặc unspecified (UB-themed) không,
tức là hành vi được kiểm thử của chương trình phụ thuộc vào một trong các loại hành vi đó theo C11?
- `yes`: mục đích rõ ràng của case (tên, chú thích, cấu trúc) là thể hiện hoặc kích hoạt hành vi như vậy, hoặc đường chạy chính của chương
  trình với input hợp lệ phụ thuộc vào nó.
- `no`: chương trình có hành vi xác định trên input hợp lệ; UB chỉ có thể xảy ra như lỗi thông thường (ví dụ input sai định dạng).
- `unclear`: không đủ căn cứ.

Trả về đúng một dòng JSON cho mỗi case, đủ mọi case:
{"id": "...", "ub_themed": "yes|no|unclear", "kind_of_behavior": "undefined|implementation-defined|unspecified|none|mixed", "c11": "<điều khoản, ví dụ 6.5.6p8, hoặc rỗng>", "why": "<một câu căn cứ>"}
