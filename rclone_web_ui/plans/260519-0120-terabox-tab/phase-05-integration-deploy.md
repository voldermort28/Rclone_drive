# Phase 05: Integration & Deploy
Status: ⬜ Pending
Dependencies: Phase 01-04 (tất cả)

## Objective
Kết nối tất cả components, cập nhật dependencies, deploy lên VPS, và kiểm tra end-to-end.

## Requirements
### Functional
- [ ] Toàn bộ pipeline chạy E2E: link Terabox → file xuất hiện trên Google Drive
- [ ] File tạm trên VPS được xóa sạch sau khi xong
- [ ] Các tab cũ (Transfer, Verify, Config, History) không bị ảnh hưởng
- [ ] Deploy qua GitHub Actions tự động

### Non-Functional
- [ ] VPS phải cài được thư viện Terabox (pip install)
- [ ] Không crash khi cookie hết hạn (báo lỗi rõ ràng)
- [ ] Không crash khi ổ cứng VPS đầy (báo lỗi rõ ràng)

## Implementation Steps

### 1. [ ] Cập nhật `requirements.txt`
Thêm dependency mới (nếu dùng thư viện, hoặc chỉ cần `requests` đã có):
```
flask
requests
```
*Lưu ý:* Nếu `terabox-downloader` PyPI không tương thích Python 3.6, ta tự viết logic bằng `requests` thuần (đã có) → không cần thêm dependency.

### 2. [ ] Kiểm tra tương thích Python 3.6
- Chạy `python3 -c "import terabox_engine"` trên local
- Nếu có lỗi syntax (f-string, walrus, etc.) → sửa
- Đặc biệt kiểm tra: dataclasses, typing extensions, async/await patterns

### 3. [ ] Cập nhật `deploy.yml` (nếu cần)
Nếu thêm dependency mới, đảm bảo bước `pip install -r requirements.txt` trong deploy workflow sẽ cài nó.
Kiểm tra file `.github/workflows/deploy.yml`:
- Có bước `pip install` không?
- Có restart service (gunicorn/supervisord) không?

### 4. [ ] Test trên local (macOS)
- Chạy `python app.py`
- Mở browser → Tab Terabox
- Kiểm tra giao diện hiển thị đúng
- Kiểm tra API cookie hoạt động
- (Không test tải thật vì local không có gclone)

### 5. [ ] Commit, push và deploy lên VPS
```bash
git add .
git commit -m "feat: add Terabox download tab with VPS relay"
git push origin main
```
- Chờ GitHub Actions deploy
- SSH vào VPS kiểm tra:
  - `pip3 list | grep -i tera` (nếu dùng thư viện)
  - `systemctl status gdrivedl` (hoặc supervisord)
  - `ls /tmp/terabox_dl/` (thư mục tạm chưa tồn tại = đúng)

### 6. [ ] Test End-to-End trên VPS (Production)
**Bước 6.1:** Mở browser → Tab Terabox
- [ ] Tab hiển thị đúng
- [ ] Các tab cũ vẫn hoạt động

**Bước 6.2:** Cấu hình cookie
- [ ] Paste cookie ndus → Lưu → Status hiện "✅ Cookie đã lưu"

**Bước 6.3:** Kiểm tra link
- [ ] Dán 1 link Terabox file nhỏ (~20-50MB)
- [ ] Bấm "Kiểm tra" → Hiện tên file + dung lượng

**Bước 6.4:** Tải + Upload
- [ ] Nhập đích Google Drive (gc:{folder_id})
- [ ] Bấm "Bắt đầu tải"
- [ ] Quan sát progress bar: xanh dương (downloading) → xanh lá (uploading)
- [ ] Console hiện log realtime
- [ ] Hoàn tất → thông báo thành công

**Bước 6.5:** Kiểm tra kết quả
- [ ] File xuất hiện trong Google Drive đích (đúng tên, đúng size)
- [ ] `ls /tmp/terabox_dl/` → thư mục tạm đã bị xóa
- [ ] VPS disk usage không tăng (`df -h`)

**Bước 6.6:** Test edge cases
- [ ] Thử tải với cookie sai → báo lỗi rõ ràng
- [ ] Thử dán link Terabox sai → báo lỗi
- [ ] Thử bấm "Dừng" giữa chừng → dừng + cleanup
- [ ] Tab Transfer (Google Drive) vẫn hoạt động bình thường sau khi dùng Terabox

## Files to Create/Modify
- `rclone_web_ui/requirements.txt` — **[MODIFY]** Thêm dependency nếu cần
- `.github/workflows/deploy.yml` — **[MODIFY]** Thêm bước cài nếu cần

## Test Criteria
- [ ] Pipeline E2E: Link Terabox → File trên Google Drive ✅
- [ ] File tạm VPS đã xóa ✅
- [ ] Tab cũ không bị ảnh hưởng ✅
- [ ] Cookie hết hạn → báo lỗi thân thiện ✅
- [ ] Dừng giữa chừng → cleanup đúng ✅

## Notes
- Nếu gặp lỗi `terabox-downloader` không tương thích Python 3.6:
  → Fallback: tự viết `_get_terabox_info()` và `_download_terabox()` bằng `requests`
  → Reverse-engineer API Terabox khá đơn giản: chỉ cần 2 HTTP requests
- Kiểm tra disk space trước khi tải: `shutil.disk_usage('/tmp')` → nếu < file_size → báo lỗi
- Sau khi deploy thành công, chạy `/save-brain` để lưu context

---
🏁 **HOÀN TẤT PLAN**
