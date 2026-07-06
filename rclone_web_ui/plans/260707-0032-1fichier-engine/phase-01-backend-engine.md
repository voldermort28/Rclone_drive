# Phase 01: Backend Engine
Status: ⬜ Pending
Dependencies: None

## Objective
Xây dựng lớp `FichierEngine` chịu trách nhiệm xử lý các tác vụ tải file từ 1fichier về VPS và đồng bộ lên Google Drive.

## Requirements
### Functional
- Hỗ trợ tải khoản Premium bằng API của 1fichier.
- Hỗ trợ tài khoản Free bằng cách tự động đếm ngược 60 giây và gửi POST request lấy link tải trực tiếp.
- Trích xuất được tên file và kích thước file bằng HEAD/GET request để đối chiếu với file đã có trên Google Drive trước khi tải.
- Tự động bỏ qua tệp đã có trên Google Drive hoặc tệp đã tải xong trên VPS.
- Hỗ trợ nút Stop để dừng khẩn cấp và dọn dẹp thư mục tạm.

### Non-Functional
- Đảm bảo xử lý lỗi kết nối, lỗi timeout.
- Cache link tải để tránh thực hiện đếm ngược 60 giây hai lần cho một tệp.

## Implementation Steps
1. [ ] Khởi tạo tệp `rclone_web_ui/fichier_engine.py` và import các thư viện cần thiết (`requests`, `re`, `subprocess`, `shutil`, `time`, `hashlib`, `os`).
2. [ ] Viết hàm `_file_id_from_url` tách file ID từ link (ví dụ: `3z71it1si6n2z2fwt8t1`).
3. [ ] Triển khai `get_direct_link` với logic:
    - Nếu cấu hình có API Key → Dùng Premium API (`/download/get_token.cgi`).
    - Nếu không → Dùng chế độ Free: Tải trang, tìm thời gian chờ (`var ct = (\d+);`), đếm ngược qua `_progress`, sau đó POST lấy link.
    - Lưu link đã lấy vào dictionary `self._cache` của engine.
4. [ ] Triển khai `get_file_info` để lấy dung lượng, tên file bằng cách gọi HEAD request tới direct link.
5. [ ] Triển khai `download_to_vps` tải file về `/tmp/fichier_dl/{hash}` dạng chunk-by-chunk, cập nhật progress lên UI, đổi tên từ `.part` thành file gốc.
6. [ ] Triển khai `upload_to_drive` chạy lệnh `gclone copy` hoặc `rclone copy` đẩy lên Drive (hỗ trợ SA rotation).
7. [ ] Triển khai `run_full_pipeline` kết nối các bước tuần tự.

## Files to Create/Modify
- `rclone_web_ui/fichier_engine.py` [NEW] - Chứa class `FichierEngine`.

## Test Criteria
- Code biên dịch và import thành công.
- Hàm `get_direct_link` chạy thử nghiệm lấy được link trực tiếp của tài khoản Free sau 60s chờ.
