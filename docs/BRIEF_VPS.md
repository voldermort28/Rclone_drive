# 💡 BRIEF: GDrive VPS Auto Backup (CLI)

**Ngày tạo:** 24/03/2026
**Brainstorm cùng:** User
**Môi trường:** VPS CentOS 7 (x86_64)

---

## 1. VẤN ĐỀ CẦN GIẢI QUYẾT
Cần sao lưu số lượng lớn dữ liệu từ nhiều link Google Drive phân tán về 1 tài khoản Drive tập trung. Máy tính cá nhân không tiện treo máy 24/7 và Google có giới hạn sao chép 750GB/ngày.

## 2. GIẢI PHÁP ĐỀ XUẤT
Sử dụng công cụ nâng cao chạy ngầm trên máy chủ VPS (dòng lệnh) để thực hiện "server-side copy" (Google tự copy cho nhau, không kéo dữ liệu qua VPS).
- Đọc hàng loạt link cần tải từ file `links.txt`.
- Cho phép xem tiến trình copy real-time theo ý muốn.
- Tự động luân chuyển các tài khoản ảo (Service Accounts - SA) để vượt giới hạn 750GB, cho phép copy hàng TB mỗi ngày mà không bị chặn.

## 3. ĐỐI TƯỢNG SỬ DỤNG
- **Primary:** Quản trị viên thao tác qua Terminal/SSH.

## 4. NGHIÊN CỨU & LỰA CHỌN CÔNG NGHỆ
### Các công cụ tiêu biểu trên Linux:
| Tool | Điểm mạnh | Nhược điểm |
|-----|-----------|----------|
| **AutoRclone** (Python) | Công cụ kinh điển, chuyên trị giới hạn 750GB bằng cách tự đổi 100+ SA. | Yêu cầu setup Python tương đối rườm rà. |
| **gclone / fclone** (Go) | Chuyên dụng, cực kỳ gọn nhẹ (1 file nhị phân chạy được luôn trên CentOS), đổi SA tự động siêu nhanh. | Cấu hình ban đầu hơi đặc thù. |
| **Rclone + Bash Script** | Dễ custom 100% theo ý mình. | Phải tự viết logic xử lý lỗi 750GB. |

### Hướng đi tối ưu cho mình:
- Dùng **fclone** hoặc **gclone** vì tải phát ăn ngay trên hệ điều hành CentOS. 
- Sử dụng lệnh `screen` hoặc `tmux` để cho phép phiên làm việc chạy ngầm (anh có thể tắt máy tính đi ngủ, lúc khác mở VPS lên xem lại tiến trình bình thường).

## 5. TÍNH NĂNG

### 🚀 MVP (Bắt buộc có nhanh nhất để chạy):
- [ ] Cấu hình chuẩn Google Cloud Console (Tạo Project, sinh 100 file JSON Service Accounts).
- [ ] Script cài đặt công cụ (gclone/rclone) vào CentOS 7.
- [ ] Cấu hình file `links.txt` và vòng lặp bash script xử lý lần lượt.
- [ ] Tính năng chạy ngầm và mở lại giao diện để xem `%` tiến trình.

### 🎁 Phase 2 (Làm sau):
- [ ] Báo cáo kết quả "Xong link nào" gửi trực tiếp về tin nhắn Telegram.
- [ ] Tự động lọc các folder bị lỗi (Link hỏng, mất quyền truy cập) ra một file riêng `error_links.txt`.

## 6. ƯỚC TÍNH SƠ BỘ
- **Độ phức tạp:** Trung Bình (Code nhẹ nhưng công đoạn hướng dẫn anh thao tác tạo Service Account trên Google mất chút xíu thời gian).
- **Rủi ro kỹ thuật:** Rất ít, đây là giải pháp được giới data hoarder sử dụng rộng rãi và cực kỳ ổn định.

## 7. BƯỚC TIẾP THEO
→ Chạy lệnh `/plan` để lên thiết kế chi tiết (chia nhỏ các bước cài đặt và code bash script).
