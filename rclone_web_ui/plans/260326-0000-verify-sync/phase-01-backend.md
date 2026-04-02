# Phase 01: Backend API & Rclone Subprocess
Status: ✅ Complete

## Objective
Tạo các hàm trong backend Python để gọi lệnh `rclone check`, đọc log dạng JSON xuất ra, và định tuyến nó qua API (`/api/verify`).

## Requirements
### Functional
- [ ] Hàm `run_rclone_check(src, dst)` chạy ngầm không block process chính.
- [ ] Flask Route `POST /api/verify` kích hoạt tiến trình check.
- [ ] Flask Route `GET /api/verify/status` trả về trạng thái check (đang chạy, lỗi, tổng file thiếu, ds file).

## Implementation Steps
1. [ ] Cập nhật `rclone_engine.py`: Thêm hàm parse lệnh `rclone check --json`.
2. [ ] Thiết kế cơ chế lưu kết quả Check tạm thời (trong bộ nhớ hoặc file `verify_status.json`).
3. [ ] Viết API trên `app.py`.

## Files to Modify
- `rclone_engine.py` - Viết hàm logic Rclone.
- `app.py` - Tạo các endpoints.

---
Next Phase: phase-02-frontend.md
