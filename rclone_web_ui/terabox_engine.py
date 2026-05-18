"""
TeraboxEngine - Download files from Terabox and upload to Google Drive.
Completely independent from rclone_engine.py.
Compatible with Python 3.6+.
"""

import subprocess
import threading
import logging
import os
import re
import glob
import shutil
import time
import uuid
import json

try:
    import requests
except ImportError:
    requests = None


class TeraboxEngine:
    """Engine to handle Terabox download -> Google Drive upload pipeline."""

    TERABOX_API_BASE = "https://www.terabox.app"
    CHUNK_SIZE = 8192  # 8KB chunks for streaming download
    PROGRESS_THROTTLE = 5  # seconds between progress updates (slow download)

    def __init__(self, progress_callback, log_callback, stop_checker):
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stop_checker = stop_checker
        self._process = None
        self._response = None  # for cancelling download stream
        self._stopped = False

    # ==================== BINARY DETECTION (copied from rclone_engine) ====================

    def _detect_binary(self):
        """Detect gclone (preferred) or fall back to rclone."""
        env_binary = os.environ.get('RCLONE_BINARY', '')
        if env_binary:
            return env_binary
        for path in ['/usr/local/bin/gclone', '/usr/bin/gclone']:
            if os.path.isfile(path):
                return path
        # Try which
        try:
            result = subprocess.run(['which', 'gclone'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            path = result.stdout.decode('utf-8', errors='replace').strip()
            if path and os.path.isfile(path):
                return path
        except Exception:
            pass
        return 'rclone'

    def _get_sa_dir(self):
        """Get the Service Account directory path."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sa_dir = os.path.join(base_dir, 'sa')
        if os.path.isdir(sa_dir) and glob.glob(os.path.join(sa_dir, '*.json')):
            return sa_dir
        return None

    # ==================== TERABOX API ====================

    def _parse_share_url(self, url):
        """Extract short URL key from Terabox share link.
        
        Supports formats:
        - https://www.terabox.app/s/1xxxxxx
        - https://teraboxapp.com/s/1xxxxxx
        - https://www.terabox.com/s/1xxxxxx
        - https://1024terabox.com/s/1xxxxxx
        """
        url = url.strip()
        # Match /s/ pattern
        m = re.search(r'/s/([A-Za-z0-9_-]+)', url)
        if m:
            return m.group(1)
        # Maybe user pasted just the key
        if re.match(r'^[A-Za-z0-9_-]{6,}$', url):
            return url
        return None

    def _build_cookie_header(self, cookie_value):
        """Build cookie header string from ndus value."""
        cookie_value = cookie_value.strip()
        # If user pasted full cookie string with ndus=
        if 'ndus=' in cookie_value:
            return cookie_value
        # Just the value
        return "ndus={0}; lang=en".format(cookie_value)

    def get_file_info(self, url, cookie):
        """Get file information from a Terabox share link.
        
        Returns dict: { "file_name": str, "file_size": int, "file_size_human": str, 
                        "download_url": str, "fs_id": str }
        Or dict with "error" key on failure.
        """
        if requests is None:
            return {"error": "Module 'requests' not installed. Run: pip install requests"}

        surl = self._parse_share_url(url)
        if not surl:
            return {"error": "Link Terabox không hợp lệ. Cần link dạng: https://www.terabox.app/s/..."}

        cookie_header = self._build_cookie_header(cookie)
        headers = {
            "Cookie": cookie_header,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }

        try:
            # Step 1: Get share info (file list)
            api_url = "{0}/api/shorturlinfo?shorturl={1}&root=1".format(
                self.TERABOX_API_BASE, surl
            )
            self.log_callback(logging.INFO, "Fetching file info from Terabox...")
            resp = requests.get(api_url, headers=headers, timeout=30)
            data = resp.json()

            if data.get('errno', -1) != 0:
                err_msg = data.get('errmsg', 'Unknown error')
                if data.get('errno') == -6:
                    return {"error": "Cookie hết hạn hoặc không hợp lệ. Vui lòng cập nhật cookie ndus."}
                if data.get('errno') == -9:
                    return {"error": "Link Terabox không tồn tại hoặc đã bị xóa."}
                return {"error": "Terabox API error ({0}): {1}".format(data.get('errno'), err_msg)}

            file_list = data.get('list', [])
            if not file_list:
                return {"error": "Không tìm thấy file nào trong link này."}

            # Get first file (we only support 1 file at a time)
            file_info = file_list[0]
            file_name = file_info.get('server_filename', 'unknown')
            file_size = int(file_info.get('size', 0))
            fs_id = str(file_info.get('fs_id', ''))
            is_dir = int(file_info.get('isdir', 0))

            if is_dir:
                return {"error": "Link này là thư mục (folder). Hiện tại chỉ hỗ trợ tải 1 file."}

            # Step 2: Get download link (dlink)
            shareid = str(data.get('shareid', ''))
            uk = str(data.get('uk', ''))
            sign = data.get('sign', '')
            timestamp_val = str(data.get('timestamp', ''))

            dlink_url = ("{0}/api/filemetas?shareid={1}&uk={2}&sign={3}"
                         "&timestamp={4}&fid_list=[{5}]").format(
                self.TERABOX_API_BASE, shareid, uk, sign, timestamp_val, fs_id
            )
            resp2 = requests.get(dlink_url, headers=headers, timeout=30)
            data2 = resp2.json()

            download_url = ""
            if data2.get('errno', -1) == 0:
                info_list = data2.get('info', [])
                if info_list:
                    download_url = info_list[0].get('dlink', '')

            if not download_url:
                # Fallback: try from first API response
                download_url = file_info.get('dlink', '')

            return {
                "file_name": file_name,
                "file_size": file_size,
                "file_size_human": self._human_size(file_size),
                "download_url": download_url,
                "fs_id": fs_id,
                "shareid": shareid,
                "uk": uk,
            }

        except requests.exceptions.Timeout:
            return {"error": "Kết nối tới Terabox bị timeout. Vui lòng thử lại."}
        except requests.exceptions.ConnectionError:
            return {"error": "Không thể kết nối tới Terabox. Kiểm tra kết nối mạng VPS."}
        except Exception as e:
            return {"error": "Lỗi không xác định: {0}".format(str(e))}

    # ==================== DOWNLOAD ====================

    def download_to_vps(self, download_url, cookie, tmp_dir, file_name, file_size):
        """Download a file from Terabox to VPS temp directory.
        
        Returns: path to downloaded file, or None on failure.
        """
        if requests is None:
            self.log_callback(logging.ERROR, "Module 'requests' not installed.")
            return None

        # Check disk space
        try:
            disk = shutil.disk_usage(os.path.dirname(tmp_dir) or '/tmp')
            if file_size > 0 and disk.free < file_size * 1.1:  # 10% margin
                self.log_callback(logging.ERROR,
                                  "Không đủ dung lượng ổ cứng! Cần {0}, còn trống {1}".format(
                                      self._human_size(file_size), self._human_size(disk.free)))
                return None
        except Exception:
            pass  # If disk check fails, try anyway

        os.makedirs(tmp_dir, exist_ok=True)
        # Sanitize filename
        safe_name = re.sub(r'[\\/*?:"<>|]', '_', file_name)
        file_path = os.path.join(tmp_dir, safe_name)

        cookie_header = self._build_cookie_header(cookie)
        headers = {
            "Cookie": cookie_header,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        try:
            self.log_callback(logging.INFO,
                              "Bắt đầu tải: {0} ({1})".format(safe_name, self._human_size(file_size)))

            self._response = requests.get(download_url, headers=headers, stream=True, timeout=60)
            self._response.raise_for_status()

            # Get actual file size from Content-Length if available
            content_length = int(self._response.headers.get('Content-Length', file_size) or file_size)
            if content_length > 0:
                file_size = content_length

            downloaded = 0
            last_progress_time = time.time()
            last_downloaded = 0

            with open(file_path, 'wb') as f:
                for chunk in self._response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING, "Tải bị dừng bởi người dùng.")
                        self._response.close()
                        return None

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Throttle progress updates (every 5s for slow downloads)
                        now = time.time()
                        if now - last_progress_time >= self.PROGRESS_THROTTLE:
                            if file_size > 0:
                                dl_percent = min(int(downloaded * 50 / file_size), 50)  # 0-50%
                            else:
                                dl_percent = 0

                            # Calculate speed
                            elapsed = now - last_progress_time
                            speed = (downloaded - last_downloaded) / elapsed if elapsed > 0 else 0
                            speed_str = self._human_size(int(speed)) + "/s"

                            eta_str = ""
                            if speed > 0 and file_size > 0:
                                remaining = file_size - downloaded
                                eta_seconds = int(remaining / speed)
                                eta_str = " | ETA: {0}".format(self._human_time(eta_seconds))

                            msg = "Đang tải: {0}/{1} ({2}){3}".format(
                                self._human_size(downloaded),
                                self._human_size(file_size),
                                speed_str, eta_str
                            )
                            self.progress_callback(dl_percent, msg)
                            self.log_callback(logging.DEBUG, msg)

                            last_progress_time = now
                            last_downloaded = downloaded

            self.log_callback(logging.INFO,
                              "Tải xong: {0} ({1})".format(safe_name, self._human_size(downloaded)))
            return file_path

        except requests.exceptions.Timeout:
            self.log_callback(logging.ERROR, "Kết nối tới Terabox bị timeout khi tải.")
            return None
        except requests.exceptions.ConnectionError:
            self.log_callback(logging.ERROR, "Mất kết nối khi đang tải từ Terabox.")
            return None
        except IOError as e:
            self.log_callback(logging.ERROR, "Lỗi ghi file: {0}".format(str(e)))
            return None
        except Exception as e:
            self.log_callback(logging.ERROR, "Lỗi tải file: {0}".format(str(e)))
            return None

    # ==================== UPLOAD TO GOOGLE DRIVE ====================

    def upload_to_drive(self, local_path, drive_dest):
        """Upload a local file to Google Drive using gclone/rclone.
        
        Returns: True on success, False on failure.
        """
        binary = self._detect_binary()

        # Prepare destination (handle Drive IDs with curly braces for gclone)
        dest = drive_dest
        m = re.match(r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', drive_dest)
        if m:
            dest = "{0}:{{{1}}}{2}".format(m.group(1), m.group(2), m.group(3) or '')

        cmd = [binary, "copy", local_path, dest, "--verbose", "--stats=1s", "--stats-one-line"]

        # Add SA rotation if available
        sa_dir = self._get_sa_dir()
        if sa_dir:
            sa_count = len(glob.glob(os.path.join(sa_dir, '*.json')))
            cmd.extend(["--drive-service-account-file-path", sa_dir])
            self.log_callback(logging.INFO,
                              "SA rotation enabled: {0} accounts".format(sa_count))

        self.log_callback(logging.INFO, "Uploading to Google Drive: {0}".format(dest))

        try:
            # Use bytes mode to bypass ASCII filesystem encoding (CentOS 7 fix)
            cmd_bytes = [arg.encode('utf-8') if isinstance(arg, str) else arg for arg in cmd]

            self._process = subprocess.Popen(
                cmd_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )

            progress_regex = re.compile(r'(\d+)%')

            if self._process and self._process.stdout:
                for raw_line in self._process.stdout:
                    line = raw_line.decode('utf-8', errors='replace').strip()
                    if not line:
                        continue

                    self.log_callback(logging.DEBUG, line)

                    match = progress_regex.search(line)
                    if match:
                        rclone_percent = int(match.group(1))
                        # Map rclone 0-100% to overall 50-100%
                        overall = 50 + int(rclone_percent * 50 / 100)
                        self.progress_callback(overall, "Uploading: {0}%".format(rclone_percent))
                    elif "Transferred:" in line and " / " in line:
                        self.log_callback(logging.INFO, line)
                    elif "Errors:" in line:
                        self.log_callback(logging.ERROR, "RCLONE: {0}".format(line))

                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING, "Upload bị dừng bởi người dùng.")
                        if self._process:
                            self._process.terminate()
                        return False

                self._process.wait()

                if self._process.returncode == 0:
                    self.log_callback(logging.INFO, "Upload lên Google Drive thành công!")
                    return True
                else:
                    self.log_callback(logging.ERROR,
                                      "Rclone exited with code {0}".format(self._process.returncode))
                    return False

        except FileNotFoundError:
            self.log_callback(logging.ERROR,
                              "Binary '{0}' not found. Install gclone/rclone.".format(binary))
            return False
        except Exception as e:
            self.log_callback(logging.ERROR, "Upload error: {0}".format(str(e)))
            return False
        finally:
            self._process = None

    # ==================== CLEANUP ====================

    def cleanup(self, tmp_dir):
        """Remove temporary download directory."""
        try:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
                self.log_callback(logging.INFO, "Đã dọn dẹp file tạm: {0}".format(tmp_dir))
        except Exception as e:
            self.log_callback(logging.WARNING, "Lỗi dọn dẹp: {0}".format(str(e)))

    # ==================== FULL PIPELINE ====================

    def run_full_pipeline(self, url, cookie, drive_dest):
        """Run the complete Terabox -> Google Drive pipeline.
        
        Returns: True on success, False on failure.
        """
        self._stopped = False
        tmp_dir = os.path.join('/tmp', 'terabox_dl', str(uuid.uuid4()))

        try:
            # Phase 1: Get file info
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO, "BƯỚC 1/3: Lấy thông tin file...")
            self.progress_callback(0, "Đang lấy thông tin file...")

            info = self.get_file_info(url, cookie)
            if "error" in info:
                self.log_callback(logging.ERROR, info["error"])
                return False

            file_name = info["file_name"]
            file_size = info["file_size"]
            download_url = info.get("download_url", "")

            self.log_callback(logging.INFO,
                              "File: {0} ({1})".format(file_name, info["file_size_human"]))

            if not download_url:
                self.log_callback(logging.ERROR,
                                  "Không lấy được link tải. Cookie có thể hết hạn.")
                return False

            if self.stop_checker() or self._stopped:
                return False

            # Phase 2: Download to VPS
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO, "BƯỚC 2/3: Tải file về VPS...")
            self.progress_callback(2, "Bắt đầu tải từ Terabox...")

            local_path = self.download_to_vps(download_url, cookie, tmp_dir, file_name, file_size)
            if not local_path:
                return False

            if self.stop_checker() or self._stopped:
                return False

            # Phase 3: Upload to Google Drive
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO, "BƯỚC 3/3: Đẩy file lên Google Drive...")
            self.progress_callback(50, "Bắt đầu upload lên Google Drive...")

            success = self.upload_to_drive(local_path, drive_dest)

            if success:
                self.progress_callback(100, "Hoàn tất!")
                self.log_callback(logging.INFO, "=" * 50)
                self.log_callback(logging.INFO,
                                  "HOÀN TẤT! File '{0}' đã được copy lên Google Drive.".format(file_name))
            return success

        except Exception as e:
            self.log_callback(logging.ERROR, "Pipeline error: {0}".format(str(e)))
            return False
        finally:
            # Always cleanup
            self.cleanup(tmp_dir)

    # ==================== STOP ====================

    def stop(self):
        """Stop the current pipeline."""
        self._stopped = True
        # Close download stream
        if self._response:
            try:
                self._response.close()
            except Exception:
                pass
        # Terminate upload process
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass

    # ==================== HELPERS ====================

    @staticmethod
    def _human_size(size_bytes):
        """Convert bytes to human-readable size."""
        if size_bytes <= 0:
            return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        size = float(size_bytes)
        while size >= 1024 and i < len(units) - 1:
            size /= 1024
            i += 1
        if i == 0:
            return "{0} B".format(int(size))
        return "{0:.1f} {1}".format(size, units[i])

    @staticmethod
    def _human_time(seconds):
        """Convert seconds to human-readable time."""
        if seconds < 60:
            return "{0}s".format(seconds)
        elif seconds < 3600:
            return "{0}m {1}s".format(seconds // 60, seconds % 60)
        else:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return "{0}h {1}m".format(h, m)
