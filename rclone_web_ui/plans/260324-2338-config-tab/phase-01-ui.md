# Phase 01: Giao diện Tab & Layout
Status: ⬜ Pending

## Objective
Chuyển đổi giao diện hiện tại sang dạng Tab để tách biệt phần "Điều khiển Copy" và "Cấu hình Tài khoản".

## Requirements
### Functional
- [ ] Thiết kế Thanh điều hướng Tab (Tabs Navigation).
- [ ] Tab "Transfer": Chứa giao diện copy hiện có.
- [ ] Tab "Accounts": Chứa form chỉnh sửa config và quản lý SA.

### Non-Functional
- [ ] Đảm bảo hiệu ứng chuyển tab mượt mà.
- [ ] Giữ nguyên phong cách Glashmorphism hiện tại.

## Implementation Steps
1. [ ] Cập nhật `index.html`: Thêm cấu trúc `tabs-nav` và `tabs-content`.
2. [ ] Cập nhật `styles.css`: Thêm style cho tab (active, hover) và ẩn hiện nội dung.
3. [ ] Cập nhật `app.js`: Viết logic chuyển đổi tab bằng JavaScript.

## Files to Create/Modify
- `templates/index.html` - Thêm cấu trúc Tab.
- `static/css/styles.css` - UI hoàn thiện.
- `static/js/app.js` - Logic chuyển tab.

## Test Criteria
- [ ] Nhấn vào các tab chuyển đổi đúng nội dung.
- [ ] Trạng thái copy ở tab Transfer vẫn được duy trì khi chuyển sang tab Accounts.

---
Next Phase: [Phase 02: API Cấu hình & Upload SA](phase-02-backend.md)
