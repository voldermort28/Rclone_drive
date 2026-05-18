# Phase 02: API Endpoints
Status: ⬜ Pending
Dependencies: Phase 01 (TeraboxEngine)

## Objective
Thêm 5 API endpoints vào `app.py` để frontend giao tiếp với TeraboxEngine.
Code thêm vào **cuối file**, không sửa code cũ.

## Requirements
### Functional
- [ ] Endpoint lưu/đọc cookie Terabox
- [ ] Endpoint lấy thông tin file từ link
- [ ] Endpoint bắt đầu pipeline tải
- [ ] Endpoint polling trạng thái (giống /api/status hiện tại)
- [ ] Endpoint dừng tiến trình

### Non-Functional
- [ ] JSON response format thống nhất: `{ "success": bool, "data": ..., "error": ... }`
- [ ] Thread-safe: pipeline chạy trong background thread
- [ ] Không block Flask request

## Implementation Steps

### 1. [ ] Thêm import và state vào đầu phần Terabox trong app.py
```python
# ==================== TERABOX MODULE ====================
from terabox_engine import TeraboxEngine

TERABOX_COOKIE_FILE = os.path.join(BASE_DIR, 'terabox_cookie.txt')
TERABOX_TMP_DIR = '/tmp/terabox_dl'

terabox_state = {
    'status': 'idle',      # idle | fetching_info | downloading | uploading | done | error
    'progress': 0,         # 0-100
    'message': '',
    'file_name': '',
    'file_size': 0,
    'phase': '',           # 'info' | 'download' | 'upload' | 'cleanup'
    'logs': [],
    'stop_flag': False
}
terabox_thread = None
```

### 2. [ ] Implement `GET/POST /api/terabox/cookie`
- **GET:** Đọc file `terabox_cookie.txt`, trả về cookie (mask giữa, chỉ hiện 8 ký tự đầu + cuối)
- **POST:** Nhận `{ "cookie": "ndus=xxx" }`, validate format, lưu vào file
- Xử lý: file chưa tồn tại → trả `{ "has_cookie": false }`
```python
@app.route('/api/terabox/cookie', methods=['GET', 'POST'])
def terabox_cookie():
    ...
```

### 3. [ ] Implement `POST /api/terabox/info`
- Nhận `{ "url": "https://terabox.app/s/..." }`
- Đọc cookie từ file
- Gọi `TeraboxEngine.get_file_info(url, cookie)`
- Trả về `{ "file_name": "...", "file_size": 12345, "file_size_human": "12.3 MB" }`
- Lỗi: cookie hết hạn → `{ "error": "Cookie hết hạn, vui lòng cập nhật lại" }`
```python
@app.route('/api/terabox/info', methods=['POST'])
def terabox_info():
    ...
```

### 4. [ ] Implement `POST /api/terabox/start`
- Nhận `{ "url": "...", "destination": "gc:{folder_id}" }`
- Kiểm tra: có cookie không? Có đang chạy job khác không?
- Reset terabox_state
- Tạo TeraboxEngine instance với callbacks
- Chạy `run_full_pipeline()` trong `threading.Thread`
- Trả về `{ "success": true, "message": "Đã bắt đầu tải" }`
```python
@app.route('/api/terabox/start', methods=['POST'])
def terabox_start():
    ...
```

### 5. [ ] Implement `GET /api/terabox/status`
- Trả về toàn bộ `terabox_state` hiện tại
- Frontend sẽ polling endpoint này mỗi 2s
- Logs chỉ trả 50 dòng cuối cùng (tránh response quá lớn)
```python
@app.route('/api/terabox/status', methods=['GET'])
def terabox_status():
    return jsonify(terabox_state)
```

### 6. [ ] Implement `POST /api/terabox/stop`
- Set `terabox_state['stop_flag'] = True`
- Gọi `engine.stop()` nếu engine đang chạy
- Trả về `{ "success": true }`
```python
@app.route('/api/terabox/stop', methods=['POST'])
def terabox_stop():
    ...
```

### 7. [ ] Implement callback functions cho TeraboxEngine
```python
def _terabox_progress(percent, message):
    terabox_state['progress'] = percent
    terabox_state['message'] = message

def _terabox_log(level, message):
    terabox_state['logs'].append({
        'time': datetime.now().strftime('%H:%M:%S'),
        'level': logging.getLevelName(level),
        'msg': message
    })
    # Giữ tối đa 200 dòng log
    if len(terabox_state['logs']) > 200:
        terabox_state['logs'] = terabox_state['logs'][-200:]

def _terabox_stop_checker():
    return terabox_state.get('stop_flag', False)
```

## Files to Create/Modify
- `rclone_web_ui/app.py` — **[MODIFY]** Thêm ~120 dòng code ở cuối file

## Test Criteria
- [ ] `GET /api/terabox/cookie` trả về `has_cookie: false` khi chưa có cookie
- [ ] `POST /api/terabox/cookie` lưu cookie thành công, GET lại thấy `has_cookie: true`
- [ ] `POST /api/terabox/info` trả về tên + size file đúng
- [ ] `POST /api/terabox/start` trả về success, polling status thấy progress tăng
- [ ] `POST /api/terabox/stop` dừng pipeline thành công
- [ ] Các API cũ (`/api/status`, `/api/download`, `/api/stop`) không bị ảnh hưởng

## Notes
- Convert destination URL (Google Drive link → gc:{id}) tái sử dụng logic `_extract_drive_id()` hiện có trong app.py
- Đảm bảo `terabox_state['logs']` là list mới mỗi lần start (tránh leak log cũ)
- Cookie file path dùng `BASE_DIR` để nằm cùng thư mục app

---
Next Phase: [phase-03-frontend-ui.md](./phase-03-frontend-ui.md)
