# Phase 03: Frontend UI - Textarea & Multi-Link UX
Status: ⬜ Pending
Dependencies: Phase 02

## Objective
Cập nhật giao diện frontend để tất cả các tab tải đều sử dụng `<textarea>` cho ô nhập URL, cho phép paste nhiều link cùng lúc. Đồng thời cập nhật JavaScript để gửi đúng format về API.

---

## Implementation Steps

### 1. Sửa `templates/index.html`

#### 1.1. Tab Mega (dòng 761)
- [ ] Thay `<input type="text" id="megaUrl">` bằng `<textarea>`:
```html
<label for="megaUrl">Link Mega.nz</label>
<textarea id="megaUrl" rows="6"
    placeholder="Mỗi dòng 1 link Mega folder/file...&#10;https://mega.nz/folder/ID#KEY&#10;https://mega.nz/file/ID#KEY"
    autocomplete="off"></textarea>
```

#### 1.2. Tab Terabox (dòng 473)
- [ ] Thay `<input type="text" id="teraboxUrl">` bằng `<textarea>`:
```html
<label for="teraboxUrl">Link Terabox</label>
<textarea id="teraboxUrl" rows="6"
    placeholder="Mỗi dòng 1 link Terabox...&#10;https://www.terabox.app/s/...&#10;https://teraboxapp.com/s/..."
    autocomplete="off"></textarea>
```

#### 1.3. Tab Fshare (dòng 570)
- [ ] Thay `<input type="text" id="fshareUrl">` bằng `<textarea>`:
```html
<label for="fshareUrl">Link Fshare</label>
<textarea id="fshareUrl" rows="6"
    placeholder="Mỗi dòng 1 link Fshare file...&#10;https://www.fshare.vn/file/ABC123&#10;https://www.fshare.vn/file/DEF456"
    autocomplete="off"></textarea>
```

#### 1.4. Tab MediaFire
- [ ] Đã là `<textarea>`. Giữ nguyên.

---

### 2. Sửa CSS (`static/css/styles.css`)
- [ ] Đảm bảo textarea styling nhất quán cho tất cả các tab:
```css
/* Nếu chưa có rule chung cho textarea trong .input-section */
.input-section textarea {
    width: 100%;
    resize: vertical;
    min-height: 80px;
    max-height: 300px;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 0.9rem;
    line-height: 1.5;
}
```

---

### 3. Sửa `static/js/app.js`

#### 3.1. Tab Mega — Hàm gọi start (dòng ~1207)
- [ ] Thay `megaUrlInput.value.trim()` (lấy `.value` giống textarea):
```javascript
// Không cần thay đổi logic JS vì .value hoạt động giống nhau cho cả input và textarea
// Chỉ cần đảm bảo backend parse multi-line
var url = megaUrlInput.value.trim();
```

#### 3.2. Tab Terabox — Hàm gọi start (dòng ~2280)
- [ ] Tương tự, `.value` hoạt động giống nhau. Không cần sửa logic JS.

#### 3.3. Tab Fshare — Hàm gọi start (dòng ~510)
- [ ] Tương tự.

#### 3.4. Cập nhật UI hiển thị tiến trình multi-file
- [ ] Thêm hiển thị "File X/Y" cho các tab Terabox và Fshare (giống Mega và MediaFire đã có):
```javascript
// Trong hàm poll status cho Terabox/Fshare:
if (data.current_index && data.total_items) {
    phaseText.textContent = 'File ' + data.current_index + '/' + data.total_items + ': ' + data.file_name;
}
```

---

### 4. Cập nhật localStorage save/restore
- [ ] Kiểm tra các hàm save/restore localStorage cho mega, terabox, fshare có hoạt động đúng với textarea (`.value` assignment).
- [ ] Không cần thay đổi vì `.value` hoạt động giống nhau cho cả `<input>` và `<textarea>`.

---

## Files to Create/Modify
| File | Thay đổi |
|------|----------|
| `templates/index.html` | Đổi 3 input thành textarea (Mega, Terabox, Fshare) |
| `static/css/styles.css` | Thêm/cập nhật styling cho textarea trong input-section |
| `static/js/app.js` | Thêm hiển thị "File X/Y" cho Terabox và Fshare status polling |

## Test Criteria
- [ ] Mở Web UI → 4 tab đều hiển thị textarea nhất quán (cùng chiều cao, font, border style)
- [ ] Paste 3 link (mỗi dòng 1 link) vào textarea Mega → Bấm tải → Chạy đúng
- [ ] Paste 1 link vào textarea Fshare → Backward compatible, chạy đúng
- [ ] Resize textarea bằng cách kéo góc dưới phải → Hoạt động mượt
- [ ] localStorage lưu/khôi phục nội dung textarea sau khi refresh trang

---
Next Phase: [phase-04-integration-testing.md](./phase-04-integration-testing.md)
