# Phase 01: Backend Engines - GDrive Pre-scan & VPS Check
Status: ⬜ Pending
Dependencies: Không

## Objective
Tích hợp cơ chế kiểm tra 3 bước (Smart Resume & Skip) vào tất cả 4 engine, đảm bảo mọi engine đều có hành vi đồng nhất khi retry.

---

## Bước 1: Tạo hàm helper dùng chung — `_scan_gdrive_existing()`

### Mục đích
Quét thư mục đích trên Google Drive bằng `gclone lsjson -R --files-only` để lập danh sách file đã tải thành công. Trả về `set()` chứa `(relative_path, file_size)`.

### Pattern tham khảo (đã có sẵn trong `mega_engine.py` dòng 519-550)
```python
def _scan_gdrive_existing(self, drive_dest):
    """Quét thư mục đích trên GDrive, trả về set((rel_path, size))."""
    existing = set()
    try:
        dest = drive_dest
        m = re.match(r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', drive_dest)
        if m:
            dest = "{0}:{{{1}}}{2}".format(m.group(1), m.group(2), m.group(3) or '')
        binary = self._detect_binary()
        cmd = [binary, "lsjson", "-R", "--files-only", dest]
        sa_dir = self._get_sa_dir()
        if sa_dir:
            cmd.extend(["--drive-service-account-file-path", sa_dir])
        p = subprocess.Popen(
            self._cmd_for_subprocess(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = p.communicate(timeout=30)
        if p.returncode == 0:
            import json
            data = json.loads(stdout.decode('utf-8', errors='replace'))
            for item in data:
                path = item.get('Path', '')
                size = item.get('Size', 0)
                if path:
                    norm = path.replace('\\', '/').strip('/')
                    existing.add((norm, size))
            self.log_callback(logging.INFO,
                "GDrive scan: tìm thấy {0} file đã có.".format(len(existing)))
    except Exception as e:
        self.log_callback(logging.WARNING,
            "Không thể quét GDrive: {0}".format(e))
    return existing
```

### Lưu ý
- Hàm `_detect_binary()`, `_get_sa_dir()`, `_cmd_for_subprocess()` đã có sẵn trong cả 4 engine (pattern giống nhau).
- Timeout 30s đủ cho folder < 10.000 file. Nếu folder quá lớn, warning sẽ được log và skip GDrive check (fallback sang tải bình thường).

---

## Bước 2: Tạo hàm helper — `_check_vps_complete()`

### Mục đích
Kiểm tra xem file hoàn chỉnh đã tồn tại trên VPS (trong thư mục tạm `/tmp/...`) chưa. Nếu có và khớp kích thước → skip download, chuyển thẳng upload.

### Pattern tham khảo (đã có sẵn trong `terabox_engine.py` dòng 632-636)
```python
def _check_vps_complete(self, file_path, expected_size):
    """Kiểm tra file hoàn chỉnh trên VPS. Trả True nếu đã đủ."""
    path_io = self._path_for_io(file_path)
    if os.path.exists(path_io):
        actual = os.path.getsize(path_io)
        if expected_size > 0 and actual == expected_size:
            self.log_callback(logging.INFO,
                "File đã tải đủ từ lần trước trên VPS, chuyển sang upload.")
            return True
    return False
```

---

## Implementation Steps

### 1. Sửa `mega_engine.py`
- [ ] **Bước 1 (GDrive scan)**: Đã có sẵn (dòng 519-550). Giữ nguyên.
- [ ] **Bước 2 (VPS complete check)**: Thêm kiểm tra `os.path.exists(local_path)` và so sánh `os.path.getsize()` với `fsize` trước khi gọi `_download_and_decrypt()`. Nếu file đã hoàn chỉnh trên VPS → skip download, log thông báo, chuyển thẳng sang `upload_to_drive()`.

#### Vị trí chèn code:
```
File: mega_engine.py
Trước dòng 601: ok = self._download_and_decrypt(dl_url, fobj['key_a32'], local_path, fsize)
Thêm:
    # Bước 2: Check VPS complete
    local_path_io = self._path_for_io(local_path)
    if os.path.exists(local_path_io) and fsize > 0:
        actual = os.path.getsize(local_path_io)
        if actual == fsize:
            self.log_callback(logging.INFO,
                "File đã có đủ trên VPS từ lần trước, skip download Mega.")
            # Jump to upload step
            ...
```

---

### 2. Sửa `mediafire_engine.py`
- [ ] **Bước 1 (GDrive scan)**: Thêm hàm `_scan_gdrive_existing()`. Gọi 1 lần trước vòng lặp `for index, item in enumerate(items, 1)` ở dòng 638. Trong vòng lặp, kiểm tra `(rel_path, file_size) in existing_files` → skip nếu đã tồn tại.
- [ ] **Bước 2 (VPS complete check)**: Thêm kiểm tra trước khi gọi `download_to_vps()`. Kiểm tra tên file cuối cùng trong `tmp_dir` (cần biết filename trước khi download). MediaFire engine đã có `file_name` từ `item.get('file_name')`.

#### Vị trí chèn code:
```
File: mediafire_engine.py

1) Thêm GDrive scan TRƯỚC dòng 638 (trước vòng lặp):
    existing_files = self._scan_gdrive_existing(drive_dest)

2) Trong vòng lặp (dòng 638), SAU khi có display_name, TRƯỚC dòng 656:
    # Check GDrive skip
    item_rel = item.get('rel_dir', '')
    if item_rel:
        check_path = item_rel.strip('/') + '/' + display_name
    else:
        check_path = display_name
    check_path = check_path.replace('\\', '/').strip('/')
    check_size = item.get('file_size', 0)
    if (check_path, check_size) in existing_files:
        self.log_callback(logging.INFO, "Đã có trên GDrive, skip.")
        continue
```

---

### 3. Sửa `fshare_engine.py`
- [ ] **Bước 1 (GDrive scan)**: Thêm hàm `_scan_gdrive_existing()`. Gọi trong `run_full_pipeline()` TRƯỚC bước download. Kiểm tra file đích `(file_name, file_size) in existing_files`.
- [ ] **Bước 2 (VPS complete check)**: Thêm hàm `_check_vps_complete()`. Kiểm tra trước khi gọi `download_to_vps()`. Fshare engine sử dụng `info.get('file_name')` và `info.get('file_size')` có sẵn.

#### Vị trí chèn code:
```
File: fshare_engine.py

1) Sau dòng 387 (sau khi có file info), TRƯỚC dòng 392:
    # Bước 1: Check GDrive
    existing_files = self._scan_gdrive_existing(drive_dest)
    file_name = info.get('file_name', '')
    file_size = info.get('file_size', 0)
    if file_name and (file_name, file_size) in existing_files:
        self.log_callback(logging.INFO, "File đã có trên GDrive, skip hoàn toàn.")
        self._emit_state(status='done', phase='done')
        self.progress_callback(100, "Hoàn tất! (file đã có trên GDrive)")
        return True

2) Sau check GDrive, TRƯỚC dòng 395:
    # Bước 2: Check VPS complete
    # Kiểm tra trong tmp_dir nếu file hoàn chỉnh đã tồn tại
    expected_local = os.path.join(tmp_dir, file_name)
    if self._check_vps_complete(expected_local, file_size):
        local_path = expected_local
        # Skip download, jump to upload
    else:
        local_path = self.download_to_vps(url, config, tmp_dir, file_password)
```

---

### 4. Sửa `terabox_engine.py`
- [ ] **Bước 1 (GDrive scan)**: Thêm hàm `_scan_gdrive_existing()`. Gọi trong `run_full_pipeline()` SAU khi có `file_name` và `file_size` (dòng 891-892). Kiểm tra `(file_name, file_size) in existing_files`.
- [ ] **Bước 2 (VPS complete check)**: Đã có sẵn (dòng 632-636). Giữ nguyên.

#### Vị trí chèn code:
```
File: terabox_engine.py

Sau dòng 902 (sau khi log file info), TRƯỚC dòng 904:
    # Bước 1: Check GDrive
    existing_files = self._scan_gdrive_existing(drive_dest)
    if file_name and (file_name, file_size) in existing_files:
        self.log_callback(logging.INFO, "File đã có trên GDrive, skip hoàn toàn.")
        self._emit_state(status='done', phase='done')
        self.progress_callback(100, "Hoàn tất! (file đã có trên GDrive)")
        return True
```

---

## Files to Create/Modify
| File | Thay đổi |
|------|----------|
| `mega_engine.py` | + `_check_vps_complete()`, sửa `run_full_pipeline()` thêm VPS check |
| `mediafire_engine.py` | + `_scan_gdrive_existing()`, + `_check_vps_complete()`, sửa `run_full_pipeline()` |
| `fshare_engine.py` | + `_scan_gdrive_existing()`, + `_check_vps_complete()`, sửa `run_full_pipeline()` |
| `terabox_engine.py` | + `_scan_gdrive_existing()`, sửa `run_full_pipeline()` |

## Test Criteria
- [ ] `python3 -m py_compile mega_engine.py` thành công trên Python 3.6
- [ ] `python3 -m py_compile mediafire_engine.py` thành công trên Python 3.6
- [ ] `python3 -m py_compile fshare_engine.py` thành công trên Python 3.6
- [ ] `python3 -m py_compile terabox_engine.py` thành công trên Python 3.6
- [ ] Test thủ công: Tải 1 file Fshare → Tải lại link đó → Phải thấy log "File đã có trên GDrive, skip hoàn toàn"
- [ ] Test thủ công: Tải 1 folder MediaFire 3 file, ngắt giữa file thứ 2 → Tải lại → File 1 skip, file 2 resume, file 3 tải mới

---
Next Phase: [phase-02-backend-routes.md](./phase-02-backend-routes.md)
