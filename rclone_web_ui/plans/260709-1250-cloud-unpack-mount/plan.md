# Plan: Tối ưu hóa Giải nén & Ghép file bằng Rclone Mount trên GitHub Actions
Created: 2026-07-09T12:50:00Z
Status: 🟡 In Progress

## Overview
Kế hoạch này thay đổi cách xử lý giải nén file trên GitHub Actions runner từ **Tải về SSD local -> Giải nén -> Upload** sang **Mount ổ đĩa Google Drive -> Giải nén trực tiếp qua mạng**. 

Phương pháp này giải quyết triệt để vấn đề hết dung lượng ổ cứng trên runner (đặc biệt khi file nén lớn hơn 15GB) và loại bỏ bước ghép file `cat` tốn tài nguyên.

## Nguyên tắc an toàn hệ thống (Critical Safety)
Hệ thống hiện tại đang chạy ổn định qua Web UI. Để đảm bảo không ảnh hưởng đến hệ thống đang chạy:
1. **Giữ nguyên API Input/Output:** Các tham số trigger từ Web UI (`remote_path`, `mode`, `password`, `rclone_conf`) được giữ nguyên 100%. Không cần sửa code Flask hay JavaScript hiện có trên VPS.
2. **Không đổi cấu trúc thư mục GDrive:** Sau khi giải nén, các file mới sẽ xuất hiện ở đúng thư mục đích mà người dùng yêu cầu, giống như cơ chế cũ.
3. **Cô lập môi trường chạy:** Toàn bộ quá trình mount và giải nén chỉ diễn ra bên trong môi trường chạy ảo của GitHub Actions Runner, hoàn toàn không chạm đến tài nguyên đĩa hay tiến trình của VPS.

---

## Các Giai đoạn triển khai (Phases)

| Phase | Tên Giai đoạn | Trạng thái | Tiến độ |
|-------|--------------|------------|---------|
| 01 | [Cấu hình Mount FUSE & Xác minh](phase-01-rclone-mount-setup.md) | ✅ Complete | 100% |
| 02 | [Giải nén trực tiếp qua Mount (Split & Single)](phase-02-direct-extraction.md) | ✅ Complete | 100% |
| 03 | [Kiểm thử hồi quy & Triển khai an toàn](phase-03-testing.md) | 🟡 In Progress | 0% |

## Quick Commands
- Bắt đầu Phase 1: `/code phase-01`
- Kiểm tra tiến độ: `/next`
- Lưu context: `/save-brain`
