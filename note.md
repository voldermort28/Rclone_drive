# GDriveDL - Hệ thống Rclone VPS Web Controller

Tài liệu này lưu trữ toàn bộ thông tin quan trọng của hệ thống để đồng nhất quy trình làm việc và ghi nhớ cấu trúc dự án qua các phiên làm việc.

---

## 1. THÔNG TIN HỆ THỐNG & VPS

* **Tên dự án**: GDriveDL - Rclone VPS Web Controller
* **VPS IP**: `116.118.48.68` (Port `8080` cho Web UI, Webroot `/www/wwwroot/rclone.laboon.vn/`)
* **Python Version**: `3.6.8` (CentOS 7)
* **Gclone Binary**: `/usr/bin/gclone` hoặc `/usr/local/bin/gclone`
* **Service Accounts (SA)**: Thư mục chứa các file JSON của SA ở `/www/wwwroot/rclone.laboon.vn/sa` (hiện có 27 tài khoản dùng để xoay vòng vượt giới hạn sao chép 750GB/ngày của Google Drive).
* **Quy trình Deploy (CI/CD)**: Hệ thống đã được thiết lập tự động hóa deployment thông qua **GitHub Actions** (`.github/workflows/deploy.yml`). Khi thực hiện `git push` lên branch `main`, workflow sẽ:
  1. Tự động SCP toàn bộ code từ thư mục `rclone_web_ui/` lên VPS `/www/wwwroot/rclone.laboon.vn/`.
  2. Tự động kill tiến trình Flask cũ và restart tiến trình Flask mới (`python3 app.py`).
  * *Lưu ý*: Không cần deploy thủ công. Chỉ cần commit và push lên nhánh `main`.
* **Lệnh khởi động/khởi động lại Backend thủ công (khi cần)**:
  ```bash
  kill -9 $(lsof -t -i:8080); cd /www/wwwroot/rclone.laboon.vn && nohup env LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 python3 app.py > app_run.log 2>&1 &
  ```

---

## 2. KIẾN TRÚC & LUỒNG XỬ LÝ (FLOW)

Dự án gồm các công cụ tải chính tương ứng với các pipeline:
1. **Mega** (`mega_engine.py`)
2. **Terabox** (`terabox_engine.py`)
3. **MediaFire** (`mediafire_engine.py`)
4. **Fshare** (`fshare_engine.py`)
5. **1fichier** (`fichier_engine.py`)
6. **Pixeldrain** (`pixeldrain_engine.py`)
7. **PikPak** (`pikpak_engine.py`)
8. **DownCode** (`downcode_engine.py`)

### Quy trình tải & giải mã:
* **Tải gián tiếp qua VPS**: Link nguồn $\rightarrow$ Tải và giải mã về thư mục tạm `/tmp/[engine]_dl/` trên VPS $\rightarrow$ Đẩy lên Google Drive đích thông qua `gclone` $\rightarrow$ Xóa file tạm trên VPS ngay khi upload thành công để tránh đầy ổ cứng.

---

## 3. THIẾT KẾ ĐỒNG NHẤT LUỒNG TẢI THÔNG MINH (UNIFIED SMART-RESUME FLOW)

Tất cả các Engine tải file (đơn và thư mục) phải tuân thủ nghiêm ngặt quy trình kiểm tra 3 bước (Smart-Resume & Skip) trước khi bắt đầu tải:

### Bước 1: Kiểm tra Google Drive (Tránh tải về VPS)
* Trước khi download bất kỳ file nào từ nguồn về VPS, Engine phải chạy `rclone lsjson` trên thư mục đích GDrive để lập danh sách các file đã có sẵn.
* Nếu file đã tồn tại trên GDrive với **đúng tên** và **đúng kích thước (dung lượng)** $\rightarrow$ **Skip hoàn toàn** (không download về VPS, không upload lại).

### Bước 2: Kiểm tra File hoàn chỉnh trên VPS (Tránh tải lại khi lỗi upload)
* Nếu file chưa có trên GDrive, kiểm tra xem file hoàn chỉnh đã được tải về thành công trước đó trên ổ đĩa tạm của VPS chưa (kiểm tra file thật, không phải file `.part`, khớp kích thước).
* Nếu file hoàn chỉnh đã tồn tại trên VPS $\rightarrow$ **Skip download từ nguồn**, chuyển thẳng sang bước **Upload lên GDrive**.

### Bước 3: Kiểm tra File dở dang trên VPS (Tải tiếp tục - HTTP Range)
* Nếu file chưa hoàn chỉnh trên VPS, kiểm tra xem có file `.part` dở dang hay không.
* Nếu có file `.part` $\rightarrow$ Gửi request HTTP với header `Range: bytes=[dung_luong_hien_tai]-` để **tải tiếp phần còn lại** về VPS.
* Nếu không có $\rightarrow$ Tiến hành tải mới từ đầu.

---

## 4. QUY TẮC PHÁT TRIỂN & CODE

* **Tính tương thích Python 3.6**: VPS chạy Python `3.6.8`. Tránh dùng các cú pháp Python hiện đại như `f-strings` (dùng `.format()`), `dataclasses`, `asyncio.run()`, hoặc các toán tử gán mới (`:=` - Walrus operator).
* **Hỗ trợ Đa liên kết & Thư mục**:
  * Các ô nhập link (URL) ở UI sẽ được đổi thành `<textarea>` cho phép nhập nhiều link (mỗi dòng 1 link).
  * Backend phải bóc tách danh sách link, mở rộng các link thư mục thành danh sách file riêng biệt, sau đó chạy tải tuần tự qua vòng lặp.
* **Xử lý tên file mã hóa**: Đặc biệt đối với tab **Mega**, cần giải mã đúng khóa phân quyền (`k_str`) bằng cách phân tách dấu `/` trước để tìm đúng phân quyền của `root_handle`, tránh sinh ra các file lỗi bắt đầu bằng `file_`.

---

## 5. CẤU HÌNH HỆ THỐNG ĐỒNG NHẤT (UNIFIED CONFIGURATION)

Để giữ cho giao diện tải sạch sẽ, trực quan và tập trung hoàn toàn vào việc hiển thị tiến trình tải/log:
* **Gom cụm cấu hình**: Tất cả các phần thiết lập thông tin xác thực, tài khoản hay khóa kết nối (bao gồm Rclone config, Service Accounts zip, Tài khoản VIP Fshare, và Cookie Terabox ndus) phải được quy hoạch gọn gàng trong duy nhất tab **Cấu hình** (`tab-config`).
* **Không đặt input cấu hình ở tab tải**: Các tab tải tương ứng (như Fshare, Terabox) tuyệt đối không chứa form nhập liệu hoặc nút lưu cấu hình. Thay vào đó, chúng chỉ hiển thị một block thông tin nhỏ báo trạng thái cấu hình hiện tại (ví dụ: đã nhận diện cấu hình hay chưa) để hướng dẫn người dùng qua tab Cấu hình nếu cần cấu hình lại.

