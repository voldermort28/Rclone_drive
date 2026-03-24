# Phase 04: Triển khai & Kiểm thử VPS
Status: ⬜ Pending
Dependencies: phase-03-engine

## Objective
Triển khai phiên bản nâng cấp lên VPS CentOS 7 và kiểm tra thực tế.

## Requirements
### Functional
- [ ] Đồng bộ code mới lên `/www/wwwroot/rclone.laboon.vn`.
- [ ] Restart lại `rclone-web.service`.
- [ ] Kiểm tra khả năng truy cập SSL và Proxy.

### Non-Functional
- [ ] Đảm bảo không làm mất file `rclone.conf` hiện có của người dùng.

## Implementation Steps
1. [ ] Dùng `scp` hoặc `git` để đẩy code mới lên VPS.
2. [ ] Chạy lệnh `systemctl restart rclone-web`.
3. [ ] Kiểm tra UI mới trên trình duyệt.
4. [ ] Thử nghiệm upload SA và sửa config.

## Files to Create/Modify
- `rclone_web_ui/docs/deploy_centos7.md` - Cập nhật hướng dẫn nếu có thay đổi.

## Test Criteria
- [ ] Web hoạt động mượt mà tại `https://rclone.laboon.vn`.
- [ ] Các tính năng Tab, Config, SA upload hoạt động đúng thực tế.

---
**Hoàn thành dự án! 🥂**
