# 🎨 DESIGN: Smart Queue & Quota Auto-Retry

Ngày tạo: 2026-03-25
Dựa trên: `docs/specs/smart_queue_spec.md`

---

## 1. Cách Lưu Thông Tin (Database)

📦 **SƠ ĐỒ LƯU TRỮ (Hàng Đợi - Queue):**

Chúng ta bắt buộc phải có một "Cuốn sổ tay" lưu trên ổ cứng VPS để VPS nhớ đang phải làm gì dù cho có bị khởi động lại. Tên nó là `queue.json`.

```
┌─────────────────────────────────────────────────────────────┐
│  📑 QUEUE.JSON (Sổ tay Hàng Đợi)                             │
│                                                             │
│  [Job 1] ─────────────────────────────────────────────────┐ │
│  ├── ID: "job_1710000001" (Mã số vé)                      │ │
│  ├── Nguồn: "gc:1glGX..."                                 │ │
│  ├── Đích: "gc_dest:Folder_A"                             │ │
│  ├── Trạng thái: "waiting" (Đang đợi) / "delayed" (Lỗi)   │ │
│  └── Hẹn giờ chạy: 12:00 PM (Lúc ném vào là chạy luôn)    │ │
│                                                             │
│  [Job 2] (Bị Google Khóa) ────────────────────────────────┐ │
│  ├── ID: "job_1710000002"                                 │ │
│  ├── Nguồn: "Kho Sách Chữ V2"                             │ │
│  ├── Trạng thái: "delayed" (Bị văng 403)                  │ │
│  └── Hẹn giờ chạy: 15:00 PM (Bị cộng thêm 3 tiếng)        │ │
└─────────────────────────────────────────────────────────────┘
```

## 2. Danh Sách Màn Hình Thay Đổi

| # | Chỗ Thay Đổi | Mục đích |
|---|-----|----------|
| 1 | **Nút Copy (Tab Transfer)** | Thay vì báo "Đang có tiến trình chạy", nó sẽ báo: "Đã ném vào hàng đợi thành công!" |
| 2 | **Bảng Status (Tab Transfer)** | Thay vì chỉ hiện "Đang chạy", nó hiện thêm: `Đang đợi trong hàng (Còn X job)` |
| 3 | **Tab History / Monitor** | Hiển thị Bảng Hàng Đợi (Queue) ngay bên trên Bảng Lịch Sử. Hiện rõ Job nào đang đếm ngược 3 tiếng, Job nào đang chờ bốc. Có thêm nút **[Xóa khỏi Hàng Đợi]** để anh hủy lệnh lỡ tay. |

## 3. Luồng Hoạt Động (Hành trình người dùng & Hệ thống)

🚶 **Người dùng:**
1️⃣ Nhập Link Nguồn -> Nơi Đích (Như cũ).
2️⃣ Bấm "Start Transfer".
3️⃣ Hệ thống báo xanh: "Đã thêm vào Hàng Đợi". (Chấm hết, phần còn lại VPS tự lo).

🤖 **Hệ thống (Con kiến thợ - Background Worker):**
1️⃣ Nó thức dậy mỗi 5 giây, giở sổ `queue.json` ra xem.
2️⃣ Có Job nào đến giờ chạy không? (Ví dụ 12:00). Có -> Lôi ra đưa cho Rclone.
3️⃣ Rclone chạy...
   - Nếu XONG: Xóa khỏi `queue.json`, ghi chiến tích vào `history.json`.
   - Nếu LỖI Quota (`downloadQuotaExceeded`): Rclone văng. Con kiến thợ bắt được lỗi này -> Lấy cái bút đỏ sửa giờ chạy của Job đó thành `Hiện tại + 3 Tiếng`, vứt xuống đáy sổ. Lặp lại bước 1.

## 4. Checklist Kiểm Tra (Acceptance Criteria)

### Tính năng: Hàng Đợi Thông Minh
- [ ] Bấm Copy 5 lần liên tục với 5 link khác nhau -> Hệ thống phải lưu đủ 5 Job vào `queue.json` mà không báo lỗi "Đang chạy".
- [ ] Job đầu tiên phải tự động chui vào máy chạy Rclone.
- [ ] Tab Lịch Sử phải vẽ ra được 1 cái Bảng chứa 4 Job còn lại đang "Đứng chờ".
- [ ] Bấm nút "Xóa" trên 1 Job chờ -> Xóa cái rụp.
- [ ] **Test Quota Lỗi:** Cố tình cho 1 link bậy (hoặc link khóa) vào chạy. Nó phải tự bắt được chữ `downloadQuotaExceeded` và update lại thời gian hẹn giờ (Current Time + 3h) trên giao diện.

---
*Tạo bởi AWF 2.1 - Design Phase*
