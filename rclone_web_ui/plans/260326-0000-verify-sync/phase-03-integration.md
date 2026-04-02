# Phase 03: API & UI Integration
Status: ⬜ Pending
Dependencies: Phase 01, Phase 02

## Objective
Kết nối Giao diện Javascript tới các API Python đã viết, để báo lỗi, nhận JSON danh sách thiếu và update progress bar "Quét" realtime.

## Requirements
### Functional
- [ ] Lắng nghe Click Nút Quét -> Bắn API Scan.
- [ ] JS `setInterval` poll data báo cáo check.
- [ ] Bấm Nút "Chép Bù" -> Gọi API ném list vô `Queue` y hệt tính năng transfer thường.

## Implementation Steps
1. [ ] Viết thêm logic xử lý DOM cho Tab mới trong `app.js`.
2. [ ] Xử lý error handler khi Nguồn = Rỗng.

## Files to Modify
- `static/js/app.js`

---
Next Phase: phase-04-vps.md
