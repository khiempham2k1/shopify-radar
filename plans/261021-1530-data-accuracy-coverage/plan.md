---
title: Độ chính xác và độ đầy đủ của dữ liệu tổng hợp
status: done
created: 2026-10-21
branch: claude/project-thread-7ndd6h
---

# Độ chính xác và độ đầy đủ của dữ liệu tổng hợp

Nguồn: báo cáo đánh giá https://claude.ai/artifact/VeweQSuZAdLBhUKAqXbaBr (bước 1–3).

## Outcome

Bản tóm tắt cộng đồng, phần tóm tắt Tổng quan và báo cáo tuần không còn bỏ mất hay dùng nhầm dữ liệu một cách im lặng; báo cáo tự nói mình đang thiếu gì; phân loại đọc đủ nội dung thay đổi chính thức và để lại lý do cho mọi item.

## Constraints

- API chỉ thêm trường, không đổi trường cũ. Bản tóm tắt cũ (chỉ có `all_item_ids`) vẫn tính là đã tóm tắt hết.
- Không cần migration (dữ liệu mới nằm trong `Report.content` JSON).
- Test chạy trên SQLite; giao diện tiếng Việt.

## Non-goals

Nhóm C (nút phản hồi, `radar eval`, trang chất lượng dữ liệu), lấy mẫu tin bị lọc từ khóa (A6), kiểm tra hạn chót (B4), gộp chủ đề giữa các nguồn (B6).

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | [Tóm tắt cộng đồng không mất tin, số đếm do code tính](phase-01-community-digest.md) | done |
| 2 | [Báo cáo tuần và tóm tắt Tổng quan đủ dữ liệu](phase-02-weekly-report.md) | done |
| 3 | [Phân loại đọc đủ, mọi item có lý do](phase-03-classification.md) | done |

## Acceptance

- Test mới cho từng mục, cùng toàn bộ test cũ, qua trên SQLite.
- `npm run lint`, `npx tsc --noEmit`, `npm run build` trong `web/` qua.
- PR mở trên `claude/project-thread-7ndd6h`.
