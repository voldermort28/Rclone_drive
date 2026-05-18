# Phase 04: Frontend JavaScript Logic
Status: ⬜ Pending
Dependencies: Phase 02 (API Endpoints), Phase 03 (Frontend UI)

## Objective
Thêm logic JavaScript vào `app.js` để điều khiển tab Terabox.
Code thêm vào **cuối file**, không sửa code cũ.

## Requirements
### Functional
- [ ] Load cookie status khi mở tab
- [ ] Lưu cookie qua API
- [ ] Kiểm tra link Terabox → hiển thị tên/size file
- [ ] Bắt đầu pipeline tải → polling progress
- [ ] Cập nhật UI realtime (progress bar, console, trạng thái)
- [ ] Dừng tiến trình
- [ ] Đổi màu progress bar theo giai đoạn (download vs upload)

### Non-Functional
- [ ] Vanilla JS (ES5 compatible — VPS Python 3.6 đi kèm browser cũ của user)
- [ ] Không conflict với biến/function hiện tại trong app.js
- [ ] Auto-scroll console output

## Implementation Steps

### 1. [ ] Khai báo DOM elements cho tab Terabox
```javascript
// ==================== TERABOX TAB ====================
var teraboxCookieInput = document.getElementById('teraboxCookie');
var teraboxSaveCookieBtn = document.getElementById('teraboxSaveCookieBtn');
var teraboxCookieStatus = document.getElementById('teraboxCookieStatus');
var teraboxUrl = document.getElementById('teraboxUrl');
var teraboxDest = document.getElementById('teraboxDest');
var teraboxCheckBtn = document.getElementById('teraboxCheckBtn');
var teraboxStartBtn = document.getElementById('teraboxStartBtn');
var teraboxStopBtn = document.getElementById('teraboxStopBtn');
var teraboxFileInfo = document.getElementById('teraboxFileInfo');
var teraboxFileName = document.getElementById('teraboxFileName');
var teraboxFileSize = document.getElementById('teraboxFileSize');
var teraboxStatusSection = document.getElementById('teraboxStatusSection');
var teraboxStatusText = document.getElementById('teraboxStatusText');
var teraboxPhaseText = document.getElementById('teraboxPhaseText');
var teraboxProgressBar = document.getElementById('teraboxProgressBar');
var teraboxProgressPercent = document.getElementById('teraboxProgressPercent');
var teraboxProgressDetail = document.getElementById('teraboxProgressDetail');
var teraboxConsole = document.getElementById('teraboxConsole');
var isTeraboxPolling = false;
```

### 2. [ ] Implement `teraboxLoadCookie()`
- Gọi `GET /api/terabox/cookie`
- Nếu có cookie → hiển thị "✅ Cookie đã lưu (ndus=ABCD...WXYZ)"
- Nếu chưa có → hiển thị "⚠️ Chưa có cookie, vui lòng nhập"
- Gọi khi trang load (trong DOMContentLoaded hoặc khi switch tab)

### 3. [ ] Implement `teraboxSaveCookie()`
- Đọc giá trị từ input cookie
- Validate: không rỗng, chứa ký tự hợp lệ
- Gọi `POST /api/terabox/cookie` với `{ "cookie": value }`
- Thành công → cập nhật status text, xóa input
- Lỗi → hiển thị thông báo lỗi

### 4. [ ] Implement `teraboxCheckInfo()`
- Đọc link từ ô input
- Validate: phải chứa "terabox" hoặc "teraboxapp" trong URL
- Gọi `POST /api/terabox/info` với `{ "url": link }`
- Thành công → hiển thị card thông tin file (tên + size)
- Lỗi → alert thông báo (cookie hết hạn, link sai, ...)
- Disable nút "Kiểm tra" khi đang gọi API (tránh spam)

### 5. [ ] Implement `teraboxStart()`
- Validate: có link + có đích
- Convert destination URL → gc:{id} (tái sử dụng `convertSingleUrl()` hiện có)
- Gọi `POST /api/terabox/start` với `{ "url": link, "destination": dest }`
- Thành công → hiện card tiến trình, ẩn form, bắt đầu polling
- Lỗi → alert thông báo

### 6. [ ] Implement `teraboxPollStatus()`
- Gọi `GET /api/terabox/status` mỗi 2 giây
- Cập nhật UI:
  - `progress` → width của progress bar + text phần trăm
  - `phase` → đổi màu progress bar:
    - `download`: gradient `#3b82f6 → #60a5fa` (xanh dương)
    - `upload`: gradient `#22c55e → #4ade80` (xanh lá)
  - `message` → status text
  - `logs` → render vào console div (auto-scroll xuống dưới)
  - `status === 'done'` → dừng polling, hiện thông báo thành công
  - `status === 'error'` → dừng polling, hiện thông báo lỗi
- Log rendering: colorize theo level (ERROR=đỏ, WARNING=vàng, INFO=xanh)

### 7. [ ] Implement `teraboxStop()`
- Gọi `POST /api/terabox/stop`
- Cập nhật UI: status text = "Đã dừng"
- Dừng polling

### 8. [ ] Bind event listeners
```javascript
if (teraboxSaveCookieBtn) {
    teraboxSaveCookieBtn.addEventListener('click', teraboxSaveCookie);
}
if (teraboxCheckBtn) {
    teraboxCheckBtn.addEventListener('click', teraboxCheckInfo);
}
if (teraboxStartBtn) {
    teraboxStartBtn.addEventListener('click', teraboxStart);
}
if (teraboxStopBtn) {
    teraboxStopBtn.addEventListener('click', teraboxStop);
}
// Load cookie khi trang load xong
teraboxLoadCookie();
```

## Files to Create/Modify
- `rclone_web_ui/static/js/app.js` — **[MODIFY]** Thêm ~180 dòng JS ở cuối file

## Test Criteria
- [ ] Mở tab Terabox → cookie status hiển thị đúng
- [ ] Nhập + lưu cookie → status cập nhật "✅ Cookie đã lưu"
- [ ] Dán link Terabox + bấm "Kiểm tra" → hiện tên + size file
- [ ] Bấm "Bắt đầu tải" → progress bar chạy, console hiện log
- [ ] Progress bar đổi màu xanh dương → xanh lá khi chuyển sang upload
- [ ] Console auto-scroll khi có log mới
- [ ] Bấm "Dừng" → tiến trình dừng, UI cập nhật
- [ ] Khi done → hiện thông báo thành công, form reset
- [ ] Tab Transfer/Verify/History vẫn hoạt động bình thường

## Notes
- Tất cả biến đều dùng prefix `terabox` để tránh conflict
- Dùng `var` thay vì `let/const` cho tương thích browser cũ
- Auto-scroll console: `teraboxConsole.scrollTop = teraboxConsole.scrollHeight`
- Polling interval: `setInterval` 2000ms, clear khi done/error/stop

---
Next Phase: [phase-05-integration-deploy.md](./phase-05-integration-deploy.md)
