# Phase 03: Testing & Verification
Status: 🟡 In Progress
Dependencies: Phase 02

## Objective
Kiểm thử tính năng tự động nhận diện link, thêm vào hàng đợi, hiển thị UI hàng đợi với các badge màu, chạy worker nền và cơ chế dừng các engine bên thứ ba.

## Kịch Bản Kiểm Thử
1. **Kiểm tra cú pháp**:
   - Chạy lệnh biên dịch Python trên app.py.
2. **Kiểm tra tự động nhận diện URL**:
   - Gửi request đến `/api/download` bằng curl với các loại link khác nhau và xác nhận loại job (`fshare`, `mediafire`, `terabox`, `mega`, `rclone`) được gán chính xác trong hàng đợi.
3. **Kiểm tra UI**:
   - Sử dụng trình duyệt Chrome kiểm tra hiển thị nút "Thêm hàng đợi" trên các tab tải.
   - Nhập link Fshare và nhấn "Thêm hàng đợi", kiểm tra hiển thị dòng hàng đợi mới với badge "Fshare" màu xanh dương.
