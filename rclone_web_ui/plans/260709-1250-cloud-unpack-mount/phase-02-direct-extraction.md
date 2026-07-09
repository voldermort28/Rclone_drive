# Phase 02: Giải nén trực tiếp qua Mount (Split & Single)
Status: ✅ Complete
Dependencies: [Phase 01](phase-01-rclone-mount-setup.md)

## Mục tiêu
Cập nhật và tối ưu hóa logic giải nén trong `cloud_unpack.yml` để đọc file nén từ `/home/runner/mnt_source` và giải nén trực tiếp vào thư mục `/home/runner/mnt_dest`.

## Các thay đổi chính trong logic giải nén

### 1. Loại bỏ các bước copy và ghép file thủ công
* Loại bỏ bước tải file nén về máy local (bước `2. Download files to download dir` cũ).
* Loại bỏ hoàn toàn bước chạy `cat` để ghép file `.001` (vì `7z` tự động xử lý khi được chỉ định file `.001`).

### 2. Xử lý giải nén trực tiếp bằng `7z` trên Mount Points

Chúng ta sẽ phân loại và gọi giải nén trực tiếp như sau:

* **Trường hợp 1: File nén chia nhỏ dạng `.001` (Split zip/rar/7z):**
  Nếu file đích chỉ định là `.001` (hoặc trong folder có chứa file `.001`):
  ```bash
  # Chỉ cần chạy trực tiếp file .001, 7z tự tìm các phần .002, .003 trong cùng thư mục mount
  7z x "$MNT_SOURCE/$BASENAME" -p"$PASSWORD" -o"$MNT_DEST" -y
  ```

* **Trường hợp 2: File nén chia nhỏ dạng `.part1.rar` (WinRAR Multivolume):**
  Nếu file đích chỉ định là `.part1.rar` (hoặc `.part01.rar`):
  ```bash
  # 7z tự tìm các part còn lại trong cùng thư mục mount
  7z x "$MNT_SOURCE/$BASENAME" -p"$PASSWORD" -o"$MNT_DEST" -y
  ```

* **Trường hợp 3: Thư mục (IS_FOLDER = true):**
  Nếu người dùng chọn giải nén cả thư mục, chúng ta quét thư mục mount và giải nén từng file:
  * Quét tất cả các file có đuôi `.001` hoặc `.part1.rar` hoặc `.part01.rar` để giải nén làm đại diện.
  * Quét các file `.zip`, `.rar`, `.7z` đơn lẻ (không chứa từ khóa `part` đi kèm số lớn hơn 1) để giải nén.
  * Tất cả lệnh `7z x` đều xuất thẳng dữ liệu sang `$MNT_DEST`.

* **Trường hợp 4: File đơn lẻ tiêu chuẩn:**
  ```bash
  7z x "$MNT_SOURCE/$BASENAME" -p"$PASSWORD" -o"$MNT_DEST" -y
  ```

---

## Code triển khai cụ thể cho step `Download, Unpack and Upload`

Thay thế toàn bộ nội dung xử lý file trong file `.github/workflows/cloud_unpack.yml` bằng đoạn script sau:

```bash
          # 3. Tiến hành giải nén trực tiếp
          echo "=== Processing Extraction ==="
          
          # Thiết lập mật khẩu cho 7z
          P_ARG="-p-"
          if [ -n "$PASSWORD" ]; then
            P_ARG="-p$PASSWORD"
          fi

          if [ "$IS_FOLDER" = "true" ]; then
            echo "=== Processing folder extraction ==="
            cd "$MNT_SOURCE"
            
            # A. Tìm và giải nén các file split .001 trước
            SPLIT_FILES=$(find . -maxdepth 2 -name "*.001" | sort)
            for f in $SPLIT_FILES; do
              echo "Extracting split archive: $f"
              7z x "$f" "$P_ARG" -o"$MNT_DEST" -y
            done
            
            # B. Tìm và giải nén các file multipart WinRAR .part1.rar
            PART_RAR_FILES=$(find . -maxdepth 2 -regextype posix-extended -iregex '.*part0*1\.rar' | sort)
            for f in $PART_RAR_FILES; do
              echo "Extracting multipart RAR: $f"
              7z x "$f" "$P_ARG" -o"$MNT_DEST" -y
            done
            
            # C. Tìm và giải nén các file đơn lẻ tiêu chuẩn
            STANDARD_ARCHIVES=$(find . -maxdepth 2 -type f \( -name "*.zip" -o -name "*.rar" -o -name "*.7z" \) | sort)
            for f in $STANDARD_ARCHIVES; do
              # Bỏ qua nếu là file part phía sau (ví dụ part2.rar, part02.rar...)
              if [[ "$f" =~ [pP]art[0-9]+ ]]; then
                if [[ ! "$f" =~ [pP]art0*1\.rar ]]; then
                  echo "Skipping multipart file: $f"
                  continue
                fi
              fi
              # Bỏ qua nếu là file zip.001 đã giải nén
              if [[ "$f" =~ \.[0-9]+$ ]]; then
                continue
              fi
              echo "Extracting standard archive: $f"
              7z x "$f" "$P_ARG" -o"$MNT_DEST" -y
            done
          else
            # Giải nén 1 file đích duy nhất được chọn
            echo "=== Extracting single target archive ==="
            7z x "$MNT_SOURCE/$BASENAME" "$P_ARG" -o"$MNT_DEST" -y
          fi
          
          # Đợi dữ liệu VFS đồng bộ lên Google Drive hoàn tất
          echo "=== Waiting for sync to complete ==="
          sync
          sleep 10
          echo "=== Unmounting ==="
          sudo umount -f "$MNT_SOURCE" || true
          sudo umount -f "$MNT_DEST" || true
          echo "=== Done ==="
```

---

## Tiêu chí xác minh (Test Criteria)
- [x] Lệnh giải nén chạy thành công mà không phát sinh thêm file tạm dung lượng lớn trên SSD của runner.
- [x] File được giải nén thành công xuất hiện đầy đủ trên Google Drive đích.
