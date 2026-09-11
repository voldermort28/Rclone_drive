# 💡 BRIEF: Tích hợp AkiraBox vào hệ thống Web UI

**Ngày tạo:** 2026-07-07
**Host:** https://akirabox.to/ (mirror: https://akirabox.com/)

---

## 1. VẤN ĐỀ CẦN GIẢI QUYẾT

Hiện tại hệ thống Web UI hỗ trợ tải file từ: Mediafire, Mega, 1Fichier, Fshare, Terabox và Google Drive.
Người dùng muốn mở rộng hệ thống để hỗ trợ thêm host **AkiraBox** — một dịch vụ lưu trữ file phổ biến trong cộng đồng chia sẻ game.

## 2. KẾT QUẢ NGHIÊN CỨU

### 🔍 Thông tin về AkiraBox

| Thuộc tính | Chi tiết |
|------------|---------|
| **Domain chính** | `akirabox.com` |
| **Domain mirror** | `akirabox.to` |
| **Loại dịch vụ** | File hosting ẩn danh |
| **Bảo vệ** | Cloudflare Turnstile (Challenge) |
| **API chính thức** | ✅ Có — tại `https://akirabox.com/api` |
| **Định dạng link** | `https://akirabox.to/{file_code}/file` hoặc `https://akirabox.com/{file_code}/file` |

### 📡 API Endpoints

AkiraBox cung cấp 3 endpoint API:

#### 1. `GET /api/files` — Kiểm tra file (KHÔNG cần API Key)
```
GET https://akirabox.com/api/files?url=https://akirabox.com/{file_code}/file
```
**Response thành công:**
```json
{
  "status": 200,
  "name": "example.pdf",
  "size": "1.2 MB",
  "type": "file",
  "mime": "application/pdf",
  "url": "https://akirabox.com/{id}/file"
}
```
> ⚠️ **Lưu ý:** Endpoint này chỉ trả về thông tin metadata (tên, kích thước, loại file).
> Nó KHÔNG trả về direct download link.

#### 2. `GET /api/files/list` — Liệt kê file (CẦN API Key)
```
GET https://akirabox.com/api/files/list?api_key=YOUR_API_KEY&page=1&per_page=10
```
**Response chứa trường `link`** nhưng đây chỉ là link trang tải (VD: `https://akirabox.com/8ifkke3kwpbc/file`), **không phải direct download link**.
> ⚠️ Endpoint này chỉ dành cho chủ sở hữu file, không dùng để tải file người khác.

#### 3. `POST /api/files/{id}/renew-link` — Đổi link chia sẻ (CẦN Bearer Token, chỉ cho chủ file)

### 🧪 Kết quả test từ VPS

| Test | Kết quả |
|------|---------|
| `curl` trực tiếp `akirabox.to/{id}/file` | ❌ **403 Forbidden** — Cloudflare Challenge (Turnstile) |
| API `GET /api/files?url=...` | ✅ Hoạt động (HTTP 200/404) — **Không bị Cloudflare chặn** |
| API trả direct download link? | ❌ **Không** — Chỉ trả metadata |

### ⚠️ Thách thức kỹ thuật

1. **Cloudflare Turnstile trên trang download:**
   - Domain `akirabox.to` được bảo vệ bởi Cloudflare Challenge level cao
   - Mọi request từ VPS đều bị chặn với HTTP 403 + Turnstile challenge
   - Không thể scrape trang download bằng `requests` hoặc `curl` thông thường

2. **API không cung cấp direct download link:**
   - API công khai (`/api/files`) chỉ trả metadata, không trả link tải trực tiếp
   - API liệt kê file (`/api/files/list`) cần API Key và chỉ liệt kê file của chính mình (chủ tài khoản upload)
   - **Không có endpoint nào cho phép lấy direct download link** từ file_code của người khác

3. **Không có chế độ Premium API cho người tải:**
   - Khác với 1fichier (có Premium API Key + CDN Credits), AkiraBox không cung cấp API để tải file cho người nhận link
   - Trang Premium chỉ dành cho người upload file

## 3. ĐÁNH GIÁ KHẢ THI

### 🔴 Kết luận: KHÔNG KHẢ THI để tích hợp trực tiếp

| Phương pháp | Khả thi? | Lý do |
|-------------|----------|-------|
| Scrape trang download từ VPS | ❌ | Cloudflare Turnstile chặn 100% VPS IP |
| Dùng API chính thức | ❌ | API không cung cấp direct download link cho file người khác |
| Dùng Premium API Key | ❌ | Không có endpoint premium download cho người nhận link |
| Headless browser (Puppeteer) trên VPS | ❌ | Cloudflare vẫn detect và chặn headless browser từ VPS |

### 🟡 Phương án thay thế khả thi

| Phương án | Mô tả | Nhược điểm |
|-----------|-------|-----------|
| **Tích hợp Real-Debrid/AllDebrid** | Gửi link AkiraBox sang dịch vụ Get Link trung gian | Cần tài khoản Real-Debrid ($4/tháng) |
| **Dùng JDownloader trên máy cá nhân** | Tải về máy tính cá nhân rồi upload lên Google Drive | Không tự động, tốn thời gian |
| **Chờ AkiraBox cập nhật API** | Nếu AkiraBox thêm endpoint download trong tương lai | Không biết khi nào |

## 4. BƯỚC TIẾP THEO

Dựa trên kết quả nghiên cứu, có 2 hướng đi:

1️⃣ **Bỏ qua AkiraBox** — Tập trung vào các host đã hỗ trợ tốt (Mediafire, Mega, Google Drive)
2️⃣ **Tích hợp Real-Debrid** — Đây là giải pháp tổng thể giúp hỗ trợ hàng chục host cùng lúc (bao gồm cả AkiraBox, ViKiNG FiLE, và nhiều host khác) chỉ với 1 API Key duy nhất
