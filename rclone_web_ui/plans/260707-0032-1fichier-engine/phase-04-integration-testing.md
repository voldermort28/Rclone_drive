# Phase 04: Integration & Testing
Status: ⬜ Pending
Dependencies: Phase 03

## Objective
Kiểm thử toàn bộ luồng hoạt động từ đầu đến cuối (End-to-End) của engine 1fichier để đảm bảo hệ thống chạy ổn định và không phát sinh lỗi bất ngờ.

## Requirements
- Kiểm thử luồng tải tệp Free (có đếm ngược 60 giây và tải thực tế).
- Kiểm thử luồng phát hiện tệp trùng lặp trên Google Drive.
- Kiểm thử nút dừng tải (Stop) giữa chừng.
- Kiểm thử dọn dẹp bộ nhớ tạm (Clear Temp) và giải phóng dung lượng ổ đĩa.

## Implementation Steps
1. [x] Khởi chạy Flask server phát triển.
2. [x] Truy cập giao diện và kiểm tra badge trạng thái `1fichier API: Tự động (Free)`.
3. [x] Thêm liên kết 1fichier thử nghiệm: `https://1fichier.com/?3z71it1si6n2z2fwt8t1&af=2899507`.
4. [x] Theo dõi phần logs hàng đợi:
    - [x] Hệ thống hiển thị "Đang lấy thong tin 1fichier..."
    - [x] Hệ thống hiển thị "Chờ 1fichier: 60s..." và đếm ngược dần về 1s.
    - [x] Hệ thống tải thành công tệp về VPS.
    - [x] Hệ thống tải lên thành công Google Drive.
    - [x] Hàng đợi kết thúc và báo trạng thái `completed`.
5. [x] Thực hiện tải lại cùng tệp đó, xác nhận hệ thống báo tệp đã có trên Google Drive và skip ngay lập tức (không cần chờ 60s hay tải lại).
6. [x] Thực hiện tải tệp và nhấn nút "Dừng tải" (Stop), xác nhận tiến trình dừng ngay lập tức và các file tạm được dọn dẹp sạch sẽ.

## Files to Create/Modify
- Không có (chỉ tiến hành kiểm thử và gỡ lỗi nếu có).

## Test Criteria
- Toàn bộ luồng hoạt động chạy trơn tru, không bị kẹt hàng đợi hay gây treo máy chủ.
- Báo cáo lỗi chi tiết bằng tiếng Việt nếu máy chủ 1fichier từ chối/bắt chờ.
