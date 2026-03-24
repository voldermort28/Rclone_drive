# Deployment Guide - Rclone Web UI (CentOS 7)

Dưới đây là các bước để đưa bảng điều khiển này lên VPS CentOS 7 của anh.

## 1. Cài đặt môi trường
Chạy các lệnh sau trên terminal của VPS:
```bash
# Cập nhật hệ thống
sudo yum update -y

# Cài đặt Python 3 và Pip
sudo yum install python3 python3-pip -y

# Cài đặt Rclone (hoặc Gclone nếu anh có sẵn file binary)
sudo yum install rclone -y

# Copy thư mục rclone_web_ui lên VPS (dùng FileZilla hoặc SCP)
# Sau đó di chuyển vào thư mục đó:
cd /path/to/rclone_web_ui

# Cài đặt thư viện Python
pip3 install -r requirements.txt
```

## 2. Cấu hình Chạy ngầm (Systemd)
Tạo file service để app tự khởi động cùng VPS:
`sudo nano /etc/systemd/system/rclone-web.service`

Dán nội dung sau vào (nhớ sửa `/path/to/` thành đường dẫn thật):
```ini
[Unit]
Description=Rclone Web UI Controller
After=network.target

[Service]
User=root
WorkingDirectory=/path/to/rclone_web_ui
ExecStart=/usr/bin/python3 app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Kích hoạt:
```bash
sudo systemctl daemon-reload
sudo systemctl enable rclone-web
sudo systemctl start rclone-web
```

## 3. Cấu hình Tên miền (Nginx Reverse Proxy)
Cài đặt Nginx:
```bash
sudo yum install epel-release -y
sudo yum install nginx -y
sudo systemctl enable nginx
sudo systemctl start nginx
```

Tạo file cấu hình cho `rclone.laboon.vn`:
`sudo nano /etc/nginx/conf.d/rclone.conf`

```nginx
server {
    listen 80;
    server_name rclone.laboon.vn;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Kiểm tra và reload:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

## ⚠️ Lưu ý Bảo mật
Vì anh dùng nội bộ và đã bỏ qua các bước Fix bảo mật, anh nên:
1. Cấu hình **Firewall** của VPS chỉ cho phép IP của anh truy cập cổng 80/443.
2. Hoặc cấu hình **IP Whitelist** trong Nginx.
