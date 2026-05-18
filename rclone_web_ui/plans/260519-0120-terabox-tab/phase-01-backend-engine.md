# Phase 01: Backend Engine - TeraboxEngine
Status: ⬜ Pending
Dependencies: Không

## Objective
Tạo file `terabox_engine.py` — engine độc lập xử lý toàn bộ logic Terabox.
Hoàn toàn tách biệt khỏi `rclone_engine.py`.

## Requirements
### Functional
- [ ] Lấy thông tin file từ link Terabox (tên, dung lượng)
- [ ] Tải file từ Terabox về thư mục tạm trên VPS
- [ ] Đẩy file từ VPS lên Google Drive bằng gclone
- [ ] Tự động xóa file tạm sau khi upload xong
- [ ] Báo tiến trình 2 giai đoạn (download 0-50%, upload 50-100%)
- [ ] Có thể dừng giữa chừng (stop)

### Non-Functional
- [ ] Tương thích Python 3.6 (VPS CentOS 7)
- [ ] Xử lý tên file Unicode (tiếng Việt, tiếng Trung) — dùng bytes mode giống fix trước đó

## Implementation Steps

### 1. [ ] Tạo file `terabox_engine.py` với class `TeraboxEngine`
```python
class TeraboxEngine:
    def __init__(self, progress_callback, log_callback, stop_checker):
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stop_checker = stop_checker
        self._process = None  # cho gclone upload subprocess
```

### 2. [ ] Implement `get_file_info(url, cookie)` 
- Gọi Terabox API (qua requests) để lấy metadata file
- Input: link chia sẻ Terabox + cookie ndus
- Output: dict `{ "file_name": "...", "file_size": 12345, "download_url": "..." }`
- Xử lý lỗi: link sai, cookie hết hạn, file bị xóa
- **Lưu ý Python 3.6:** Không dùng f-string walrus operator, dùng `.format()` nếu cần

### 3. [ ] Implement `download_to_vps(download_url, cookie, tmp_dir, file_name)`
- Dùng `requests.get(..., stream=True)` để tải file lớn
- Lưu vào `/tmp/terabox_dl/<uuid>/file_name`
- Stream progress: đọc từng chunk (8KB), tính % dựa trên Content-Length
- Gọi `self.progress_callback(percent, message)` mỗi 1s (throttle)
- Kiểm tra `self.stop_checker()` mỗi chunk để dừng sớm
- Xử lý lỗi: disk full, network timeout, connection reset

### 4. [ ] Implement `upload_to_drive(local_path, drive_dest)`
- Gọi gclone/rclone copy từ VPS lên Google Drive
- Tái sử dụng logic `_detect_binary()` và `_get_sa_dir()` từ RcloneEngine
- **QUAN TRỌNG:** Dùng bytes mode cho Popen (giống fix encoding trước đó)
- Parse progress từ stdout rclone (regex `(\d+)%`)
- Map progress: rclone 0-100% → overall 50-100%

### 5. [ ] Implement `cleanup(tmp_dir)`
- `shutil.rmtree(tmp_dir, ignore_errors=True)`
- Log kết quả cleanup

### 6. [ ] Implement `run_full_pipeline(url, cookie, drive_dest)`
- Orchestrate: get_info → download → upload → cleanup
- Cập nhật trạng thái qua callback ở mỗi bước
- Catch exception ở mỗi bước, cleanup dù có lỗi (try/finally)
- Return `True/False` cho thành công/thất bại

### 7. [ ] Implement `stop()`
- Set flag để stop_checker trả True
- Nếu đang download → close response stream
- Nếu đang upload → terminate gclone process

### 8. [ ] Test import trên Python 3.6
- Đảm bảo không dùng syntax Python 3.7+ (dataclass, walrus, typing mới)
- Kiểm tra import `requests` (đã có trong requirements.txt)

## Files to Create/Modify
- `rclone_web_ui/terabox_engine.py` — **[NEW]** Engine class chính

## Test Criteria
- [ ] `TeraboxEngine` import thành công trên Python 3.6
- [ ] `get_file_info()` trả về metadata đúng cho 1 link Terabox thật
- [ ] `download_to_vps()` tải file nhỏ (~10MB) thành công, progress callback được gọi
- [ ] `upload_to_drive()` đẩy file lên GDrive thành công
- [ ] `cleanup()` xóa sạch thư mục tạm
- [ ] `stop()` dừng được tiến trình giữa chừng

## Notes
- **KHÔNG** import hay kế thừa từ `rclone_engine.py` — copy logic cần thiết (detect_binary, get_sa_dir) vào file mới
- Thư viện `terabox-downloader` trên PyPI có thể không tương thích Python 3.6. Nếu vậy, tự viết logic get_file_info bằng `requests` thuần (reverse-engineer API Terabox đơn giản hơn nhiều so với dùng thư viện)
- Dùng `uuid.uuid4()` để tạo tên thư mục tạm duy nhất, tránh xung đột

---
Next Phase: [phase-02-api-endpoints.md](./phase-02-api-endpoints.md)
