# 💡 BRIEF: Smart Queue & Auto-Retry Rclone

**Ngày tạo:** 2026-03-25
**Brainstorm cùng:** Sếp / Product Owner

---

## 1. VẤN ĐỀ CẦN GIẢI QUYẾT
Hiện tại khi rclone gặp lỗi `downloadQuotaExceeded` (Do Google khóa file public tải quá nhiều lần), tiến trình copy sẽ văng lỗi ngay và làm đứt gãy luồng công việc. User phải tự lên VPS canh thời gian để bấm tải lại thủ công.

## 2. GIẢI PHÁP ĐỀ XUẤT
Phát triển hệ thống **Hàng đợi thông minh (Smart Queue) + Auto-Retry** cho tính năng copy:
- Bắt được đúng "bệnh" Quota Exceeded của Google.
- Nếu gặp bệnh này: Không chết cứng hệ thống, mà **tự động bế link đó ném về cuối hàng đợi**, và đánh dấu "Hẹn 3 tiếng sau gọi lại".
- Rảnh tay lấy các link khác trong hàng đợi (Queue) ra tải tiếp để không lãng phí tài nguyên máy chủ.

## 3. ĐỐI TƯỢNG SỬ DỤNG
- **Primary:** Admin hệ thống Rclone Web UI (Sử dụng trực tiếp trên VPS).

## 4. TÍNH NĂNG

### 🚀 MVP (Bắt buộc có để chạy ngay):
- [ ] **Queue (Hàng đợi lưu trữ):** Cơ chế lưu nhiều link cùng lúc (thay vì chỉ lưu 1 link như hiện tại) vào một tệp `queue.json`.
- [ ] **Error Parser (Dò lỗi thông minh):** Trình đọc log của Rclone để bắt chính xác từ khóa `downloadQuotaExceeded`.
- [ ] **Retry Scheduler (Lập lịch vòng lặp 3 tiếng):** Hẹn lặp lại tiến trình bị lỗi định kỳ mỗi 3 giờ đồng hồ. Ném link lỗi xuống cuối hàng.
- [ ] **UI Monitor (Giao diện giám sát):** Hiển thị rõ ràng trên Tab Lịch Sử / Tab Copy các trạng thái: `Đang tải` / `Lỗi Quota (Chờ thử lại sau X phút)` / `Chờ tới lượt xếp hàng`.

## 5. ƯỚC TÍNH SƠ BỘ
- **Độ phức tạp:** Trung bình - Khó. (Đòi hỏi đập lại một phần kiến trúc "Single-task" hiện tại của backend Python để chuyển thành "Queue Worker" chạy đa nhiệm ngầm).
- **Rủi ro kỹ thuật:** Việc hẹn giờ 3 tiếng cần lưu trạng thái đàng hoàng xuống ổ cứng. Nếu VPS sập hoặc kẹt CPU giữa chừng thì khi khởi động lại nó phải đọc được cái hàng đợi đó để chạy tiếp chứ không được xóa trắng.

## 6. BƯỚC TIẾP THEO
→ Vui lòng chạy lệnh `@[/plan]` để em thiết kế ngay Sơ đồ Cấu trúc Logic (luồng Queue chạy như thế nào, đổi Database ra sao) trước khi mình bổ luống code nhé!
