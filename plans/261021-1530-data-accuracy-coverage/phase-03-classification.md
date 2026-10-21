# Phase 3: Phân loại đọc đủ, mọi item có lý do

Files: `radar/ai/classifier.py`, `config/prompts/classify.txt`, `config/sources.yaml`, `tests/test_pipeline.py`.

1. B1: `ai.platform_content_chars` (mặc định 4000) cho item nguồn `platform`; nguồn khác giữ `content_chars`.
2. B2: prompt yêu cầu trả kết quả cho MỌI item, item không liên quan chọn mảng nhóm none kèm lý do. Code giữ hành vi cũ khi Claude vẫn bỏ sót item không phải platform (đánh dấu đã phân tích, không khớp).

Test: nội dung platform dài hơn 500 ký tự được gửi tới 4000; item không phải platform được trả về với mảng none thì lưu reason và không hiển thị.
