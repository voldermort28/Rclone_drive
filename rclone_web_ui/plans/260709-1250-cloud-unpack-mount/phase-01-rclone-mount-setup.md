# Phase 01: Cấu hình Mount FUSE & Xác minh
Status: ✅ Complete
Dependencies: Không có

## Mục tiêu
Thiết lập hệ thống FUSE (Filesystem in Userspace) trên GitHub Actions Runner và thực hiện mount thành công thư mục nguồn (chứa file nén) và thư mục đích (nơi giải nén) từ Google Drive về Runner thông qua `rclone mount`.

## Yêu cầu kỹ thuật
* Cài đặt `fuse3` trên GitHub Runner không gây lỗi.
* Mount thành công thư mục nguồn dạng **chỉ đọc (Read-only)** để bảo vệ file gốc.
* Mount thư mục đích với chế độ ghi cache **VFS writes** (`--vfs-cache-mode writes`) để `7z` có thể ghi tuần tự và đẩy trực tiếp lên Cloud.
* Có bước kiểm tra (Verification) để đảm bảo mount thành công trước khi chuyển sang bước giải nén.

## Các bước thực hiện

### 1. Cài đặt các công cụ bổ sung
Trong step `Install Rclone & Extraction Tools` của file `cloud_unpack.yml`, thêm việc cài đặt `fuse3`:
```bash
sudo apt-get update
sudo apt-get install p7zip-full unrar fuse3 -y
```

### 2. Thiết kế lệnh Mount trong workflow
Cấu hình các lệnh mount trong step `Download, Unpack and Upload`:
* Khai báo thư mục mount:
  ```bash
  MNT_SOURCE="/home/runner/mnt_source"
  MNT_DEST="/home/runner/mnt_dest"
  mkdir -p "$MNT_SOURCE" "$MNT_DEST"
  ```
* Thực hiện chạy `rclone mount` ở chế độ nền (daemon):
  ```bash
  echo "=== Mounting Source (Read-Only) ==="
  rclone mount "$PARENT_PATH/" "$MNT_SOURCE" --read-only --daemon
  
  echo "=== Mounting Destination (VFS Writes) ==="
  rclone mount "$DEST_PATH/" "$MNT_DEST" --vfs-cache-mode writes --daemon
  ```
* Chờ mount sẵn sàng (Timeout 15 giây):
  ```bash
  echo "=== Waiting for mount points to stabilize ==="
  for i in {1..15}; do
    if mountpoint -q "$MNT_SOURCE" && mountpoint -q "$MNT_DEST"; then
      echo "Mount thành công cả Nguồn và Đích!"
      break
    fi
    sleep 1
  done
  ```

---

## Tiêu chí xác minh (Test Criteria)
- [x] Chạy lệnh `mountpoint -q /home/runner/mnt` trả về mã thoát `0`.
- [x] Thư mục mount hiển thị đúng danh sách các file nén (`ls -la /home/runner/mnt`).

---
Next Phase: [Phase 02: Giải nén trực tiếp qua Mount](phase-02-direct-extraction.md)
