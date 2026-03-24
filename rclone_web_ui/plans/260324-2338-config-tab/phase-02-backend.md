# Phase 02: API Cấu hình & Upload SA
Status: ⬜ Pending
Dependencies: phase-01-ui

## Objective
Xây dựng các endpoint Backend để xử lý file cấu hình rclone và tài khoản Service Account.

## Requirements
### Functional
- [ ] API đọc/ghi file `rclone.conf`.
- [ ] API upload file ZIP/JSON của Service Account (SA).
- [ ] Logic giải nén file ZIP vào thư mục `sa/`.

### Non-Functional
- [ ] Bảo vệ file cấu hình (không để lộ thông tin nhạy cảm qua log).
- [ ] Xử lý lỗi khi file cấu hình không tồn tại.

## Implementation Steps
1. [ ] Cập nhật `app.py`: Thêm route `/api/config` (GET/POST).
2. [ ] Cập nhật `app.py`: Thêm route `/api/sa/upload` (POST).
3. [ ] Viết hàm `save_rclone_config` để lưu an toàn.
4. [ ] Viết hàm `handle_sa_upload` xử lý file ZIP (dùng `zipfile` module).

## Files to Create/Modify
- `rclone_web_ui/app.py` - Core API logic.
- `rclone_web_ui/requirements.txt` - Thêm `zipfile` (built-in) hoặc các lib cần thiết.

## Test Criteria
- [ ] Web hiển thị đúng nội dung file rclone.conf hiện tại.
- [ ] Lưu thay đổi trên web, file trên VPS được cập nhật.
- [ ] Upload file ZIP SA thành công và giải nén đúng folder `sa/`.

---
Next Phase: [Phase 03: Tối ưu Engine (750GB Bypass)](phase-03-engine.md)
