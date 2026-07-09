# Phase 03: Kiểm thử hồi quy & Triển khai an toàn
Status: 🟡 In Progress
Dependencies: [Phase 02](phase-02-direct-extraction.md)

## Mục tiêu
Kiểm thử toàn diện luồng giải nén mới để đảm bảo tính ổn định, an toàn và không làm gián đoạn bất kỳ tính năng nào đang hoạt động trên Web UI.

## Các kịch bản kiểm thử (Test Scenarios)

### Kịch bản 1: Giải nén 1 file nén đơn nhỏ (.zip hoặc .rar)
* **Mục đích:** Đảm bảo các file nén thông thường, dung lượng nhỏ vẫn chạy đúng cơ chế mount mới.
* **Cách thực hiện:** Chọn 1 file nén khoảng 5-10MB trên Google Drive và kích hoạt giải nén từ Web UI.
* **Kết quả mong đợi:** 
  - Workflow GitHub Actions kết thúc thành công (Success).
  - File giải nén xuất hiện đúng thư mục đích trên Drive.
  - Dung lượng ổ cứng local của Runner không thay đổi đáng kể.

### Kịch bản 2: Giải nén file chia nhỏ WinRAR (.part1.rar) dung lượng lớn
* **Mục đích:** Xác minh việc sửa lỗi đầy đĩa cho các bộ file game dung lượng lớn.
* **Cách thực hiện:** Chạy lại tiến trình giải nén cho bộ file `[GM]DCLB(v1.28)[EU]` (hoặc bộ file > 30GB tương tự).
* **Kết quả mong đợi:**
  - `7z` chạy tuần tự qua cả 17 file nén.
  - Quá trình chạy kết thúc thành công mà không gặp lỗi đĩa đầy `errno=28`.
  - Toàn bộ nội dung game đã giải nén hiển thị trên Google Drive đích.

### Kịch bản 3: Giải nén file zip chia nhỏ dạng .001
* **Mục đích:** Đảm bảo `7z` tự động đọc file dạng `.002`, `.003`... qua mount mà không cần ghép file `cat`.
* **Cách thực hiện:** Chọn file `.zip.001` trên Drive và kích hoạt giải nén.
* **Kết quả mong đợi:** Giải nén thành công, dữ liệu đầy đủ.

### Kịch bản 4: Kiểm tra khả năng xử lý mật khẩu
* **Mục đích:** Đảm bảo các file nén có mật khẩu vẫn giải nén bình thường.
* **Cách thực hiện:** Giải nén file nén có password bảo vệ.
* **Kết quả mong đợi:** `7z` nhận đúng tham số password và giải nén thành công.

---

## Tiêu chí hoàn thành (Definition of Done)
- [ ] Tất cả 4 kịch bản kiểm thử trên đều đạt kết quả tốt.
- [ ] Logic cũ không bị ảnh hưởng, không phát sinh lỗi trên giao diện Web UI hiện tại.
- [ ] Không rò rỉ (leak) mountpoint trên runner (lệnh `umount` chạy sạch sẽ ở bước cuối).
