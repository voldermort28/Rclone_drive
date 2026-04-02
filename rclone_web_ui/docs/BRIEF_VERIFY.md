# 💡 BRIEF: Tính năng Kiểm tra & Chép bù (Verify & Sync)

**Ngày tạo:** 2026-03-26
**Cùng với:** Anh User

---

## 1. VẤN ĐỀ CẦN GIẢI QUYẾT
Khi copy lượng dữ liệu lớn (hàng trăm GB, hàng ngàn file), do quá trình chạy kéo dài dễ bị dính lỗi (Quota, rớt mạng, v.v.). Người dùng hoang mang không biết file nào đã qua, file nào bị rớt lại dọc đường.

## 2. GIẢI PHÁP ĐỀ XUẤT
Tạo một quy trình **Kiểm tra (Verify)**:
- Cho phép user nhập Nguồn và Đích.
- Hệ thống chạy đối chiếu (cả Tên file + Kích thước) giữa 2 bên.
- Xuất ra danh sách liệt kê chính xác những file đang vắng mặt ở Đích, hoặc có nhưng sai dung lượng (chưa tải xong).
- Cung cấp nút bấm **"Copy Bù" (Resume/Sync)** để chỉ tải đúng những file bị thiếu đó.

*(Lưu ý: Thực chất lệnh `rclone copy` mặc định đã tự động phân biệt và bỏ qua file gốc đã tồn tại, nhưng tính năng này giúp user **nhìn thấy** sự thiếu hụt trước khi quyết định chạy lệnh copy bù, mang lại cảm giác an tâm tuyệt đối).*

## 3. ĐỐI TƯỢNG SỬ DỤNG
- Người dùng thường xuyên "kéo" thư mục hàng chục GB giữa các ổ Drive lớn.

## 4. TÍNH NĂNG (Features)

### 🚀 MVP (Bắt buộc có):
- [ ] Giao diện **Tab Kiểm Tra (Verify)** riêng biệt, hoặc tích hợp gọn vào Tab Transfer hiện tại.
- [ ] Flow 1: Nút **"Quét (Check)"** -> Trả về danh sách file thiếu (Báo cáo số lượng & dung lượng bị hụt).
- [ ] Flow 2: Nút **"Chép bù (Fix/Sync)"** -> Ném tác vụ chép bù vào Smart Queue để chạy ngầm như 1 job bình thường.

## 5. ƯỚC TÍNH SƠ BỘ
- **Độ phức tạp:** Trung bình 🟡 (Cần viết lệnh phân tích log JSON của `rclone check` để map lên giao diện).
- **Rủi ro:** Lệnh `check` trên thư mục hàng triệu file có thể tốn tài nguyên RAM của VPS để so sánh.

## 6. BƯỚC TIẾP THEO
→ Chạy `@[/plan]` để lên thiết kế API & Giao diện chi tiết cho Tab Verify này.
