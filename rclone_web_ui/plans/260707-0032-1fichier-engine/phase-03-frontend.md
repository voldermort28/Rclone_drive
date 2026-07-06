# Phase 03: Frontend UI Modifications
Status: 🟩 Completed
Dependencies: Phase 02

## Objective
Thiết lập giao diện người dùng để cấu hình API Key 1fichier và hiển thị trạng thái hoạt động trực quan.

## Requirements
### Functional
- Hiển thị Badge trạng thái của 1fichier ở Tab Transfer (Hiển thị "Tự động (Free)" nếu chưa cấu hình và "Đã cấu hình (Premium)" nếu đã nhập API Key).
- Thêm biểu mẫu nhập API Key 1fichier trong Tab Cấu hình.
- Xử lý lưu/tải cấu hình API Key bất đồng bộ (AJAX) không gây reload trang.

### Non-Functional
- Phù hợp với ngôn ngữ thiết kế của các khối Fshare/Terabox đã có sẵn.
- Trải nghiệm đếm ngược mượt mà ở màn hình logs hàng đợi.

## Implementation Steps
1. [x] Mở file `rclone_web_ui/templates/index.html` tìm vị trí của badge status box của Fshare/Terabox, chèn thêm badge status box cho `1fichier`.
2. [x] Tìm phần giao diện cấu hình của Fshare (`fshare` configuration card), chèn thêm card cấu hình cho `1fichier` ngay sau đó.
3. [x] Mở file `rclone_web_ui/static/js/app.js`, cập nhật hàm `checkConfigStatus` để gọi API `/api/fichier/config` cập nhật trạng thái hiển thị của badge và thông tin placeholder.
4. [x] Viết trình xử lý sự kiện click của nút lưu cấu hình 1fichier (`saveFichierConfigBtn`), thực hiện gửi POST tới `/api/fichier/config` và reload badge trạng thái.

## Files to Modify
- `rclone_web_ui/templates/index.html` [MODIFY] - Thêm badge và card cấu hình.
- `rclone_web_ui/static/js/app.js` [MODIFY] - Logic giao diện gọi API cấu hình.

## Test Criteria
- Giao diện không bị lỗi hiển thị hay lệch layout.
- Badge và cấu hình khởi chạy hiển thị đúng trạng thái ban đầu của hệ thống.
