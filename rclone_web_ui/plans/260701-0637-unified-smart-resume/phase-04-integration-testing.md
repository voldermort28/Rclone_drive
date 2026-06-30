# Phase 04: Integration Testing & Deploy
Status: ⬜ Pending
Dependencies: Phase 01, 02, 03

## Objective
Kiểm thử toàn diện hệ thống sau khi tích hợp Smart Resume & Multi-Link, sau đó deploy lên VPS production.

---

## Implementation Steps

### 1. Kiểm tra cú pháp Python 3.6
- [ ] Chạy `python3 -m py_compile` cho tất cả engine files
- [ ] Chạy `python3 -m py_compile app.py`
- [ ] Đảm bảo không có f-string, walrus operator, hoặc cú pháp Python 3.7+

### 2. Test cục bộ (trên máy dev)
- [ ] Khởi động Flask server local
- [ ] Mở Web UI, kiểm tra 4 tab hiển thị textarea đúng
- [ ] Kiểm tra placeholder text rõ ràng, hướng dẫn nhập nhiều link

### 3. Test trên VPS (Production)
#### 3.1. Deploy
- [ ] Upload files đã sửa lên VPS (`/www/wwwroot/rclone.laboon.vn/`)
- [ ] Restart Flask server:
```bash
kill -9 $(lsof -t -i:8080); cd /www/wwwroot/rclone.laboon.vn && nohup env LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 python3 app.py > app_run.log 2>&1 &
```

#### 3.2. Test Smart Resume — Tab Mega
- [ ] Tải 1 folder Mega (3-5 file nhỏ) → Thành công
- [ ] Tải lại cùng folder đó → Tất cả file phải skip ("Already exists on GDrive")
- [ ] Ngắt giữa chừng (bấm Stop) ở file thứ 2 → Tải lại → File 1 skip, file 2 resume/retry, file 3 tải mới

#### 3.3. Test Smart Resume — Tab MediaFire
- [ ] Tải 1 folder MediaFire (2-3 file) → Thành công
- [ ] Tải lại cùng folder → Tất cả file phải skip ("Đã có trên GDrive")
- [ ] Kiểm tra log console: phải thấy dòng "GDrive scan: tìm thấy X file đã có"

#### 3.4. Test Smart Resume — Tab Fshare
- [ ] Tải 1 file Fshare → Thành công
- [ ] Tải lại cùng link → Phải skip ("File đã có trên GDrive, skip hoàn toàn")
- [ ] Tải 3 file Fshare (3 dòng trong textarea) → Tải tuần tự, UI hiển thị "File 1/3", "File 2/3", "File 3/3"

#### 3.5. Test Smart Resume — Tab Terabox
- [ ] Tải 1 file Terabox → Thành công
- [ ] Tải lại cùng link → Phải skip ("File đã có trên GDrive, skip hoàn toàn")
- [ ] Ngắt giữa chừng download → Tải lại → File .part phải resume (không tải lại từ đầu)

#### 3.6. Test Edge Cases
- [ ] Nhập link trống (toàn khoảng trắng) → Báo lỗi validation
- [ ] Nhập 1 link hợp lệ + 1 link rác → Engine log warning cho link rác, tiếp tục link hợp lệ
- [ ] Nhập link đã tải thành công nhưng file trên GDrive bị xóa tay → Phải tải lại (không skip)

---

## Verification Checklist

| Test Case | Expected | Actual | Pass? |
|-----------|----------|--------|:---:|
| Mega: Tải folder → Tải lại | Skip all files | | ⬜ |
| Mega: Ngắt giữa → Tải lại | File 1 skip, file 2+ retry | | ⬜ |
| MediaFire: Tải folder → Tải lại | Skip all files | | ⬜ |
| Fshare: Tải 1 file → Tải lại | Skip file | | ⬜ |
| Fshare: Nhập 3 link | Tải tuần tự 3 file | | ⬜ |
| Terabox: Tải 1 file → Tải lại | Skip file | | ⬜ |
| Terabox: Ngắt download → Tải lại | Resume .part | | ⬜ |
| All tabs: Textarea hiển thị đúng | Consistent styling | | ⬜ |
| All tabs: Link trống | Error message | | ⬜ |

---

## Rollback Plan
Nếu có lỗi nghiêm trọng:
1. Giữ backup file gốc trước khi deploy (copy thành `*.bak`)
2. Rollback bằng cách restore file gốc
3. Restart Flask server

---

## Notes
- Sau phase này, cập nhật `note.md` và `CHANGELOG.md` với version mới.
- Cập nhật `.brain/brain.json` nếu cần (thêm feature "Unified Smart Resume").
