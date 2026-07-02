# Phase 02: Frontend Queue Button & UI Update
Status: ✅ Complete
Dependencies: Phase 01

## Objective
Thêm nút "Thêm vào hàng đợi" (Add to Queue) cho các công cụ tải bên thứ 3 (MediaFire, Fshare, Terabox, Mega) và cập nhật hiển thị bảng xếp hàng tải.

## Các thay đổi cần thực hiện:
1. **`templates/index.html`**:
   - Thêm nút bấm xếp hàng ở giao diện của từng tab tải.
2. **`static/js/app.js`**:
   - Bắt sự kiện click các nút xếp hàng và gửi payload phù hợp đến `/api/download`.
   - Cập nhật hàm `renderQueue` hiển thị nhãn màu badge tương ứng cho loại job (`rclone`, `mediafire`, `fshare`, `terabox`, `mega`).
