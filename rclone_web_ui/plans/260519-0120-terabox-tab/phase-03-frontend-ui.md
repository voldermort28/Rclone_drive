# Phase 03: Frontend UI (HTML/CSS)
Status: ⬜ Pending
Dependencies: Không (có thể làm song song với Phase 01-02)

## Objective
Thêm tab "Terabox" vào giao diện HTML, tái sử dụng CSS classes hiện có.
Giao diện đồng nhất với các tab khác.

## Requirements
### Functional
- [ ] Tab button "Terabox" trên thanh navigation
- [ ] Card cấu hình cookie (ẩn/hiện thông minh)
- [ ] Card nhập link Terabox + chọn đích Google Drive
- [ ] Card tiến trình (progress bar 2 giai đoạn + console)
- [ ] Responsive trên mobile

### Non-Functional
- [ ] Tái sử dụng 100% CSS classes hiện có (không thêm CSS mới)
- [ ] Tab mới không làm thay đổi layout các tab cũ

## Implementation Steps

### 1. [ ] Thêm tab button vào `<nav class="tabs-nav">`
Thêm trước nút "Lịch sử" (trước `data-tab="history"`):
```html
<button class="tab-btn" data-tab="terabox">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="17 8 12 3 7 8"/>
        <line x1="12" y1="3" x2="12" y2="15"/>
    </svg>
    Terabox
</button>
```

### 2. [ ] Tạo `<div id="tab-terabox">` — Container chính
```html
<!-- ========== TAB: TERABOX ========== -->
<div class="tab-content" id="tab-terabox">
    <!-- Card 1: Cookie Config -->
    <!-- Card 2: Tải từ Terabox -->
    <!-- Card 3: Tiến trình -->
</div>
```

### 3. [ ] Card 1: Cấu hình Cookie
```html
<section class="card input-section" id="teraboxCookieSection">
    <div class="config-header" style="margin-bottom: 15px;">
        <h3>🍪 Cấu hình Cookie Terabox</h3>
        <p class="config-desc">
            Cần cookie <code>ndus</code> từ tài khoản Terabox để tải file.
            Mở DevTools (F12) → Application → Cookies → terabox.com → copy giá trị <code>ndus</code>
        </p>
    </div>
    <div class="input-group">
        <label for="teraboxCookie">Cookie ndus</label>
        <input type="password" id="teraboxCookie" 
               placeholder="Paste giá trị ndus cookie ở đây...">
    </div>
    <div style="display: flex; gap: 10px; align-items: center;">
        <button id="teraboxSaveCookieBtn" class="btn-primary" 
                style="padding: 8px 20px;">
            💾 Lưu Cookie
        </button>
        <span id="teraboxCookieStatus" style="font-size: 0.85rem; color: var(--text-muted);">
        </span>
    </div>
</section>
```

### 4. [ ] Card 2: Form tải từ Terabox
```html
<section class="card input-section" id="teraboxInputSection">
    <div class="input-group">
        <label for="teraboxUrl">Link Terabox</label>
        <input type="text" id="teraboxUrl" 
               placeholder="https://www.terabox.app/s/... hoặc https://teraboxapp.com/s/...">
    </div>

    <!-- Thông tin file (ẩn, hiện sau khi check) -->
    <div id="teraboxFileInfo" style="display: none; padding: 12px; background: rgba(56,189,248,.1); 
         border: 1px solid rgba(56,189,248,.3); border-radius: 8px; margin-bottom: 15px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <div style="font-weight: 500;" id="teraboxFileName">—</div>
                <div style="font-size: 0.85rem; color: var(--text-muted);" id="teraboxFileSize">—</div>
            </div>
            <span style="color: #22c55e; font-size: 1.2rem;">✓</span>
        </div>
    </div>

    <div class="input-group">
        <label for="teraboxDest">Destination Google Drive</label>
        <input type="text" id="teraboxDest" 
               placeholder="gc:{folder_id} hoặc link Google Drive...">
    </div>

    <div style="display: flex; gap: 10px;">
        <button id="teraboxCheckBtn" class="btn-secondary" style="flex: 1;">
            🔍 Kiểm tra link
        </button>
        <button id="teraboxStartBtn" class="btn-primary" style="flex: 2;">
            🚀 Bắt đầu tải
        </button>
    </div>
</section>
```

### 5. [ ] Card 3: Tiến trình (ẩn mặc định)
```html
<section class="card status-section" id="teraboxStatusSection" style="display: none;">
    <div class="status-header">
        <h3 id="teraboxStatusText">Đang xử lý...</h3>
        <span id="teraboxPhaseText" class="file-name" 
              style="font-size: 0.85rem;"></span>
    </div>

    <!-- Progress bar -->
    <div class="progress-container">
        <div class="progress-bar-bg">
            <div class="progress-bar-fill" id="teraboxProgressBar"></div>
        </div>
        <div class="progress-info">
            <span id="teraboxProgressPercent">0%</span>
            <span id="teraboxProgressDetail"></span>
        </div>
    </div>

    <!-- Console output -->
    <div class="console-container"
         style="background-color: #0f172a; border-radius: 8px; margin-bottom: 15px; 
                border: 1px solid #1e293b; overflow: hidden;">
        <div style="background-color: #1e293b; padding: 6px 12px; font-size: 0.75rem; 
                    color: #94a3b8; font-family: monospace;">
            >_ Terabox Console
        </div>
        <div id="teraboxConsole"
             style="padding: 12px; font-family: 'Consolas','Monaco',monospace; 
                    font-size: 0.8rem; color: #a5b4fc; max-height: 200px; 
                    min-height: 80px; overflow-y: auto; white-space: pre-wrap; 
                    line-height: 1.4;">
            Đang chờ...
        </div>
    </div>

    <!-- Stop button -->
    <button id="teraboxStopBtn" class="btn-secondary" 
            style="width: 100%; border-color: #ef4444; color: #ef4444;">
        ⏹ Dừng tiến trình
    </button>
</section>
```

### 6. [ ] Đảm bảo CSS classes tái sử dụng đúng
Kiểm tra các class sau đã tồn tại trong `styles.css`:
- `.tab-btn`, `.tab-content`, `.active`
- `.card`, `.input-section`, `.status-section`
- `.input-group`, `.btn-primary`, `.btn-secondary`
- `.progress-container`, `.progress-bar-bg`, `.progress-bar-fill`
- `.status-header`, `.file-name`, `.progress-info`
- `.config-header`, `.config-desc`

### 7. [ ] Thêm style cho progress bar 2 giai đoạn
Trong card tiến trình, progress bar sẽ đổi màu:
- Đang tải từ Terabox (0-50%): Gradient xanh dương (`#3b82f6`)
- Đang upload lên Drive (50-100%): Gradient xanh lá (`#22c55e`)
→ Logic đổi màu sẽ xử lý bằng JS (Phase 04)

### 8. [ ] Đảm bảo tab switching hoạt động
Tab mới sẽ tự động hoạt động vì JS tab switching hiện tại dùng `data-tab` attribute.
Chỉ cần `data-tab="terabox"` khớp với `id="tab-terabox"` là đủ.

### 9. [ ] Test responsive
- Desktop: Card full width giống các tab khác
- Mobile: Các ô input stack dọc, nút bấm full width

## Files to Create/Modify
- `rclone_web_ui/templates/index.html` — **[MODIFY]** Thêm ~100 dòng HTML

## Test Criteria
- [ ] Tab "Terabox" hiển thị trên thanh nav
- [ ] Click tab → hiện đúng nội dung, tab khác ẩn
- [ ] Cookie card hiển thị đúng, có ô input + nút lưu
- [ ] Form tải hiển thị đúng: ô link + ô đích + 2 nút
- [ ] Card tiến trình ẩn mặc định
- [ ] Responsive trên mobile (không bể layout)
- [ ] Các tab cũ (Transfer, Verify, Config, History) không bị ảnh hưởng

---
Next Phase: [phase-04-frontend-js.md](./phase-04-frontend-js.md)
