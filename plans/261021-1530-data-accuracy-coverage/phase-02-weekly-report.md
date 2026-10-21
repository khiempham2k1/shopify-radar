# Phase 2: Báo cáo tuần và tóm tắt Tổng quan đủ dữ liệu

Files: `radar/ai/insights.py`, `radar/ai/brief.py`, `radar/pipeline.py`, `config/prompts/weekly_report.txt`, `web/components/views/ReportView.tsx`, `web/lib/types.ts`, `api/main.py` (nếu cần), `tests/test_pipeline.py`, `tests/test_brief.py`.

1. A5: `_matched_items` và `post_candidates` bỏ item có `ItemStatus.status == "dismissed"`.
2. B5: prompt ghi "Claude đang xem X/Y item".
3. A2: thêm mục "Thảo luận cộng đồng trong tuần" vào prompt từ các digest có `created_at` trong tuần (topics, open_questions).
4. A3: `weekly_report` chạy `classify` trước khi viết; đếm item khớp từ khóa/platform trong tuần chưa được phân tích, lưu `unclassified` vào content và nói trong prompt.
5. A4: `coverage` theo nguồn đang bật: số lần chạy, số lần lỗi, số item mới trong tuần (từ `source_status`, `items`). Prompt nhận danh sách nguồn có lỗi hoặc 0 item; báo cáo hiển thị bảng "Độ phủ dữ liệu".
6. B3b: `deadlines` lấy từ DB (`AIResult.deadline` của item chính thức trong tuần và hạn chót sắp tới), hiển thị bảng "Hạn chót" trên trang báo cáo.

Test: item dismissed không vào báo cáo/brief; prompt chứa X/Y, phần cộng đồng, nguồn lỗi; content có `coverage`, `deadlines`, `unclassified`.
