# Phase 03: Tối ưu Engine (750GB Bypass)
Status: ⬜ Pending
Dependencies: phase-02-backend

## Objective
Cập nhật `rclone_engine.py` để hỗ trợ tự động xoay vòng Service Account khi thư mục `sa/` được cấu hình.

## Requirements
### Functional
- [ ] Tự động nhận diện thư mục `sa/` nếu tồn tại.
- [ ] Tích hợp logic `--drive-service-account-file-path`.
- [ ] Tự động chuyển mã lệnh thành `gclone` nếu binary `gclone` tồn tại trên VPS.

### Non-Functional
- [ ] Xử lý trường hợp thư mục SA rỗng.
- [ ] Chỉ thêm cờ SA khi dùng Google Drive remotes.

## Implementation Steps
1. [ ] Cập nhật `rclone_engine.py`: Thêm kiểm tra thư mục `sa/`.
2. [ ] Thêm logic kiểm tra kiểu binary (`rclone` vs `gclone`).
3. [ ] Cập nhật command builder để chèn cờ SA đúng vị trí.

## Files to Create/Modify
- `rclone_web_ui/rclone_engine.py` - Core execution logic.

## Test Criteria
- [ ] Thực hiện lệnh copy, terminal log hiển thị đúng cờ `--drive-service-account-file-path`.
- [ ] Copy file lớn (thử nghiệm bằng cách dùng nhiều SA ảo) hệ thống không báo lỗi.

---
Next Phase: [Phase 04: Triển khai & Kiểm thử VPS](phase-04-vps.md)
