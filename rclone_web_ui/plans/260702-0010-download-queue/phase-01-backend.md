# Phase 01: Backend API & Queue Worker Integration
Status: ✅ Complete
Dependencies: None

## Objective
Hỗ trợ tự động nhận diện liên kết tải và định tuyến đến đúng engine xử lý trong luồng chạy tuần tự của worker nền.

## Những thay đổi đã thực hiện:
1. **`app.py`**:
   - Thêm trường `job_type` vào `download_state`.
   - Khai báo hàm `detect_url_type(url)` nhận diện loại link: MediaFire, Fshare, Mega, Terabox, Rclone.
   - Thêm các hàm helper đồng bộ callback: `sync_tool_progress_to_queue`, `sync_tool_state_update_to_queue`, `sync_tool_log_to_queue`.
   - Đăng ký gọi hàm helper trong các callback chính thức của Terabox, Fshare, MediaFire, Mega.
   - Viết các hàm chạy đồng bộ wrapper: `run_real_mediafire_job`, `run_real_fshare_job`, `run_real_terabox_job`, `run_real_mega_job`.
   - Cập nhật `/api/download` để chạy auto-detection và gán `type` tương ứng cho job trong `queue.json`, đồng thời hỗ trợ tham số `file_password` cho Fshare.
   - Cập nhật `/api/stop` để gửi tín hiệu dừng khẩn cấp cho cả rclone và các engine bên thứ ba.
   - Cập nhật `queue_worker_loop` để định tuyến chạy wrapper tương ứng với `job_type`.
