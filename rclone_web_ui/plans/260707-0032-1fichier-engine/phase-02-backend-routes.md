# Phase 02: Backend API Integration
Status: ⬜ Pending
Dependencies: Phase 01

## Objective
Tích hợp `FichierEngine` vào Flask backend `app.py`, cấu hình lưu trữ API Key và xử lý tác vụ nền.

## Requirements
### Functional
- Cấp API `/api/fichier/config` (GET/POST) để đọc và lưu API Key 1fichier.
- Cập nhật hàm `detect_url_type` nhận dạng link 1fichier.
- Tích hợp job-type `1fichier` vào queue worker thread.
- Hỗ trợ dừng khẩn cấp và dọn dẹp thư mục tạm qua `/api/stop` và `/api/clear_temp`.

### Non-Functional
- API Key trả về ở phương thức GET phải được làm mờ (masked) để bảo mật.
- Thực hiện lưu file cấu hình `fichier_config.json` an toàn.

## Implementation Steps
1. [ ] Khai báo `FICHIER_CONFIG_FILE` và `FICHIER_TMP_ROOT = '/tmp/fichier_dl'` ở đầu `app.py`.
2. [ ] Định nghĩa cấu trúc `fichier_state` chứa các biến trạng thái tải ngầm và hàm reset.
3. [ ] Viết hàm cấu hình: `_load_fichier_config` (đọc & làm mờ API Key) và `_save_fichier_config` (lưu vào file json).
4. [ ] Khởi tạo các hàm callback: `_fichier_progress`, `_fichier_log`, `_fichier_stop_checker`, `_fichier_state_update`.
5. [ ] Tạo route `/api/fichier/config` xử lý GET và POST cấu hình.
6. [ ] Cập nhật hàm `detect_url_type` để nhận diện các link chứa `1fichier.com`, `1fichier.fr`, `1fichier.co`, `.org`, `.net`.
7. [ ] Triển khai hàm `run_real_fichier_job` để điều phối pipeline của `FichierEngine`.
8. [ ] Cập nhật vòng lặp hàng đợi `queue_worker_loop` để khi gặp job type `1fichier` sẽ chạy `run_real_fichier_job`.
9. [ ] Cập nhật `/api/stop` và `/api/clear_temp` để truyền biến dừng `_fichier_engine.stop()` và xóa thư mục tạm `/tmp/fichier_dl`.

## Files to Modify
- `rclone_web_ui/app.py` [MODIFY] - Cấu hình định dạng link, API lưu trữ và queue worker.

## Test Criteria
- Gọi thử `/api/fichier/config` trả về cấu hình trống lúc đầu.
- Gửi yêu cầu POST lưu API Key, xác nhận ghi thành công và GET trả về chuỗi đã được làm mờ.
- Gọi hàm `detect_url_type` với link 1fichier, trả về kết quả `'1fichier'`.
