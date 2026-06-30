# Phase 02: Backend Routes - Multi-Link Parsing & Loop
Status: ⬜ Pending
Dependencies: Phase 01

## Objective
Cập nhật các API route trong `app.py` và các engine để hỗ trợ nhập **nhiều link cùng lúc** (mỗi dòng 1 link trong textarea). Backend sẽ tách chuỗi, mở rộng folder link, và chạy tuần tự từng item.

---

## Phân tích hiện trạng

### Cách frontend gửi URL hiện tại:
| Tab | Element ID | Loại | Gửi qua API |
|-----|-----------|------|-------------|
| Mega | `megaUrl` | `<input type="text">` | `data.url` (1 string) |
| Terabox | `teraboxUrl` | `<input type="text">` | `data.url` (1 string) |
| Fshare | `fshareUrl` | `<input type="text">` | `data.url` (1 string) |
| MediaFire | `mediafireUrl` | `<textarea rows="8">` | `data.url` (1 string, nhiều dòng) |

### Cách engine xử lý URL hiện tại:
| Engine | Hỗ trợ folder | Hỗ trợ multi-link |
|--------|:---:|:---:|
| Mega | ✅ (`get_folder_info` expand folder) | ❌ |
| Terabox | ❌ (chỉ 1 file/1 share link) | ❌ |
| MediaFire | ✅ (`expand_inputs` tách folder → file list) | ✅ (đã parse multi-line) |
| Fshare | ❌ (chỉ 1 file link) | ❌ |

---

## Implementation Steps

### 1. Sửa `app.py` — Route `/api/mega/start` (dòng 1526)
- [ ] Thay `url = data.get('url', '').strip()` bằng logic tách nhiều dòng:
```python
raw_urls = data.get('url', '').strip()
urls = [u.strip() for u in raw_urls.splitlines() if u.strip()]
if not urls:
    return jsonify({'success': False, 'error': 'Vui lòng nhập link Mega.nz'})
```
- [ ] Truyền danh sách `urls` vào engine thay vì 1 string.
- [ ] Sửa `_run_pipeline()` để gọi `run_full_pipeline()` với từng URL trong vòng lặp, hoặc truyền list vào engine và để engine tự loop.

#### Chiến lược:
**Option A** (Đơn giản — Loop ở `app.py`):
```python
def _run_pipeline():
    for url in urls:
        success = _mega_engine.run_full_pipeline(url, dest_converted)
        if not success and _mega_stop_checker():
            break
```
**Option B** (Sạch hơn — Loop ở engine):
```python
# Trong mega_engine.py, sửa run_full_pipeline() nhận list URLs
def run_full_pipeline(self, urls, drive_dest):
    if isinstance(urls, str):
        urls = [urls]
    for url in urls:
        ...
```

> **Khuyến nghị:** Option B để giữ logic tập trung trong engine. `app.py` chỉ gửi raw text.

---

### 2. Sửa `app.py` — Route `/api/terabox/start` (dòng 869)
- [ ] Tương tự mega, tách multi-line URLs.
- [ ] Sửa `run_full_pipeline()` trong `terabox_engine.py` để nhận list URLs và loop tuần tự.
- [ ] Mỗi URL là 1 share link Terabox (chứa 1 file hoặc 1 folder).

#### Lưu ý đặc biệt cho Terabox:
- Terabox share link có thể chứa **nhiều file trong 1 share link** (folder share).
- Hiện tại `get_file_info()` chỉ trả về file đầu tiên.
- **SCOPE**: Trong phase này, mỗi share link vẫn xử lý 1 file (giữ nguyên behavior). Hỗ trợ folder share sẽ là improvement riêng sau.

---

### 3. Sửa `app.py` — Route `/api/fshare/start` (dòng 1136)
- [ ] Tách multi-line URLs.
- [ ] Sửa `run_full_pipeline()` trong `fshare_engine.py` để nhận list URLs.
- [ ] Fshare chỉ hỗ trợ file link (`fshare.vn/file/...`), không có folder link.
- [ ] Loop tuần tự qua từng file URL.

---

### 4. Sửa `app.py` — Route `/api/mediafire/start` (dòng 1331)
- [ ] **Đã hỗ trợ multi-line** (textarea + `expand_inputs()` trong engine).
- [ ] Không cần sửa thêm.

---

### 5. Sửa `mega_engine.py` — `run_full_pipeline()`
- [ ] Nhận `urls` (str hoặc list).
- [ ] Nếu là list, loop qua từng URL, gọi `get_folder_info(url)` cho mỗi URL.
- [ ] Gộp tất cả files từ tất cả folder URLs vào 1 danh sách chung `all_files`.
- [ ] Thực hiện GDrive pre-scan 1 lần duy nhất cho `drive_dest`.
- [ ] Loop tải từng file trong `all_files`.

---

### 6. Sửa `terabox_engine.py` — `run_full_pipeline()`
- [ ] Nhận `urls` (str hoặc list).
- [ ] Loop qua từng URL:
  - Gọi `get_file_info(url, cookie)` cho mỗi URL.
  - Chạy quy trình tải + upload cho file đó.
  - Skip nếu đã có trên GDrive (Phase 01 đã tích hợp).
- [ ] Cập nhật `_emit_state()` với `current_index` và `total_items` để UI hiển thị tiến trình "File 2/5".

---

### 7. Sửa `fshare_engine.py` — `run_full_pipeline()`
- [ ] Nhận `urls` (str hoặc list) + `config` + `drive_dest`.
- [ ] Loop qua từng URL:
  - Gọi `get_file_info(url, config)` cho mỗi URL.
  - Chạy quy trình tải + upload cho file đó.
  - Skip nếu đã có trên GDrive (Phase 01 đã tích hợp).
- [ ] Cập nhật `_emit_state()` với `current_index` và `total_items`.

---

## Files to Create/Modify
| File | Thay đổi |
|------|----------|
| `app.py` | Sửa routes `/api/mega/start`, `/api/terabox/start`, `/api/fshare/start` để tách multi-line URLs |
| `mega_engine.py` | Sửa `run_full_pipeline()` nhận list URLs, gộp files |
| `terabox_engine.py` | Sửa `run_full_pipeline()` nhận list URLs, loop tuần tự |
| `fshare_engine.py` | Sửa `run_full_pipeline()` nhận list URLs, loop tuần tự, thêm `current_index`/`total_items` tracking |

## Test Criteria
- [ ] Gửi 3 link Fshare (mỗi dòng 1 link) → API parse ra 3 URLs → Engine loop tải tuần tự 3 file
- [ ] Gửi 2 link Mega folder → Engine gộp file list → Tải tuần tự, hiển thị "File X/Y" trên UI
- [ ] Gửi 1 link Terabox → Behavior giữ nguyên (backward compatible)
- [ ] Gửi link trống hoặc toàn khoảng trắng → Trả lỗi validation

---
Next Phase: [phase-03-frontend-ui.md](./phase-03-frontend-ui.md)
