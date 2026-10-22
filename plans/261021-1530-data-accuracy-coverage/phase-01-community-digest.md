# Phase 1: Tóm tắt cộng đồng không mất tin, số đếm do code tính

Files: `radar/ai/community.py`, `config/prompts/community_digest.txt`, `tests/test_community.py`.

1. `render` trả thêm danh sách id thực sự được đưa vào. Digest lưu `included_ids`.
2. Chọn tin cho digest mới: tin trong `digest_hours` gần nhất mà chưa có trong digest nào (`included_ids`; digest cũ không có trường này thì dùng `all_item_ids`). Bỏ `stored_after`.
3. Prompt ghi "Đang xem {shown}/{count} tin"; digest lưu `shown`, `total`. Tin chưa vào được sẽ có ở bản sau (trong giới hạn `digest_hours`).
4. Schema topic thêm `related_ids` (mọi tin nói về chủ đề). `mentions` = số tin trong `related_ids ∪ item_ids` cộng chuỗi trả lời của chúng trong digest; `people` = số tác giả khác nhau trong tập đó. Không dùng số Claude tự đếm.

Test: tin bị cắt vì `max_chars` xuất hiện ở digest kế tiếp; digest cũ chỉ có `all_item_ids` vẫn được coi là đã tóm tắt; mentions/people tính đúng.
