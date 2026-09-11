"""
PixeldrainEngine - Download files and albums from Pixeldrain and upload to Google Drive.
Supports single files, lists/albums, and multi-line URLs.
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
import json
import sys
import hashlib

try:
    from urllib.parse import urlparse, parse_qs, unquote
except ImportError:
    from urlparse import urlparse, parse_qs
    from urllib import unquote

try:
    import requests
except ImportError:
    requests = None


class PixeldrainEngine:
    """Engine to handle Pixeldrain download -> Google Drive upload pipeline."""

    API_BASE = "https://pixeldrain.com/api"
    CHUNK_SIZE = 1024 * 1024  # 1MB chunk size
    PROGRESS_THROTTLE = 3  # seconds between progress updates
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"

    def __init__(self, progress_callback=None, log_callback=None, stop_checker=None, state_callback=None):
        self.progress_callback = progress_callback or (lambda p, m: None)
        self.log_callback = log_callback or (lambda l, m: logging.log(l, m))
        self.stop_checker = stop_checker or (lambda: False)
        self.state_callback = state_callback
        self._process = None
        self._response = None
        self._stopped = False
        self._download_error = ''
        self._progress_base = 0.0
        self._progress_span = 100.0

    def _emit_state(self, **kwargs):
        """Send structured state back to Flask without coupling engine to app.py."""
        if not self.state_callback:
            return
        try:
            self.state_callback(kwargs)
        except Exception:
            pass

    def _progress(self, percent, message):
        overall = self._progress_base + (float(percent) * self._progress_span / 100.0)
        overall = max(0.0, min(100.0, overall))
        self.progress_callback(int(overall), message)

    # ==================== BINARY & SA DETECTION ====================

    def _detect_binary(self):
        """Detect gclone (preferred) or fall back to rclone."""
        env_binary = os.environ.get('RCLONE_BINARY', '')
        if env_binary:
            return env_binary
        for path in ['/usr/local/bin/gclone', '/usr/bin/gclone']:
            if os.path.isfile(path):
                return path
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

    # ==================== PATH & SYSTEM ENCODING FIXES ====================

    def _cmd_for_subprocess(self, cmd):
        """Encode cmd args for CentOS 7 ASCII filesystem encoding."""
        if sys.getfilesystemencoding().lower() == 'ascii':
            return [arg.encode('utf-8') if isinstance(arg, str) else arg for arg in cmd]
        return cmd

    def _path_for_io(self, path):
        """Return a path suitable for CentOS 7 ASCII filesystem encoding."""
        if isinstance(path, bytes):
            return path
        if sys.getfilesystemencoding().lower() == 'ascii':
            return path.encode('utf-8')
        return path

    def _safe_name(self, name):
        """Clean invalid characters from filename or folder name."""
        name = (name or '').strip()
        name = re.sub(r'[\/*?:"<>|]', '_', name)
        return name or 'pixeldrain_download'

    def _safe_remote_path(self, path):
        """Clean parts of a relative remote path."""
        parts = []
        for part in (path or '').split('/'):
            clean = self._safe_name(part)
            if clean and clean != 'pixeldrain_download':
                parts.append(clean)
        return '/'.join(parts)

    def _append_dest_path(self, drive_dest, rel_dir):
        """Append subfolder relative path to Google Drive destination."""
        rel_dir = self._safe_remote_path(rel_dir)
        if not rel_dir:
            return drive_dest
        return drive_dest.rstrip('/') + '/' + rel_dir

    def _scan_gdrive_existing(self, drive_dest):
        """Scan GDrive destination, return set((rel_path, size))."""
        existing = set()
        try:
            dest = drive_dest
            m = re.match(r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', drive_dest)
            if m:
                dest = "{0}:{{{1}}}{2}".format(m.group(1), m.group(2), m.group(3) or '')
            binary = self._detect_binary()
            cmd = [binary, "lsjson", "-R", "--files-only", dest]
            sa_dir = self._get_sa_dir()
            if sa_dir:
                cmd.extend(["--drive-service-account-file-path", sa_dir])
            p = subprocess.Popen(
                self._cmd_for_subprocess(cmd),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, stderr = p.communicate(timeout=60)
            if p.returncode == 0:
                data = json.loads(stdout.decode('utf-8', errors='replace'))
                for item in data:
                    path = item.get('Path', '')
                    size = item.get('Size', 0)
                    if path:
                        norm = path.replace('\\', '/').strip('/')
                        existing.add((norm, size))
                        base_name = os.path.basename(norm)
                        if base_name != norm:
                            existing.add((base_name, size))
                self.log_callback(logging.INFO,
                    "GDrive scan: tìm thấy {0} file đã có.".format(len(existing)))
        except Exception as e:
            self.log_callback(logging.WARNING,
                "Không thể quét GDrive: {0}".format(e))
        return existing

    def _find_completed_in_dir(self, tmp_dir, expected_size, file_name):
        """Find a completed (non-.part) file in tmp_dir matching expected_size."""
        try:
            tmp_io = self._path_for_io(tmp_dir)
            if not os.path.isdir(tmp_io):
                return None
            safe_name = self._safe_name(file_name)
            target_path = os.path.join(tmp_dir, safe_name)
            target_path_io = self._path_for_io(target_path)
            if os.path.isfile(target_path_io) and expected_size > 0:
                if os.path.getsize(target_path_io) == expected_size:
                    return target_path_io
        except Exception:
            pass
        return None

    @staticmethod
    def _human_size(size_bytes):
        """Convert bytes to human-readable size."""
        try:
            size_bytes = float(size_bytes)
        except Exception:
            return "0 B"
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
        return "{0:.2f} {1}".format(size, units[i])

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

    # ==================== PIXELDRAIN API ====================

    def _parse_url(self, raw_url):
        """Extract type ('file' or 'list') and ID from Pixeldrain URL."""
        url = (raw_url or '').strip()
        if not url:
            return None, None

        # Clean query parameters or anchors
        url_clean = url.split('?')[0].split('#')[0].strip()

        # Match List/Album: /l/{id}, /list/{id}, /api/list/{id}
        m_list = re.search(r'/(?:l|list|api/list)/([A-Za-z0-9_-]+)', url_clean)
        if m_list:
            return 'list', m_list.group(1)

        # Match Single File: /u/{id}, /file/{id}, /api/file/{id}
        m_file = re.search(r'/(?:u|file|api/file)/([A-Za-z0-9_-]+)', url_clean)
        if m_file:
            return 'file', m_file.group(1)

        # Match raw ID (alphanumeric length 6-12)
        if re.match(r'^[A-Za-z0-9_-]{6,12}$', url_clean):
            return 'file', url_clean

        return None, None

    def _get_auth_headers(self, api_key):
        """Generate headers and optional auth for Pixeldrain."""
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
        }
        auth = None
        api_key = (api_key or '').strip()
        if api_key:
            auth = ('', api_key)
        return headers, auth

    def _get_file_info(self, file_id, api_key=""):
        """Query metadata for a single Pixeldrain file."""
        if requests is None:
            return {"error": "Module 'requests' chưa được cài đặt."}

        headers, auth = self._get_auth_headers(api_key)
        info_url = "{0}/file/{1}/info".format(self.API_BASE, file_id)

        try:
            r = requests.get(info_url, headers=headers, auth=auth, timeout=15)
            if r.status_code == 404:
                return {"error": "File không tồn tại trên Pixeldrain (404 Not Found)."}
            if r.status_code == 401 or r.status_code == 403:
                return {"error": "Truy cập bị từ chối (403 Forbidden). Cần API Key Pixeldrain hợp lệ."}
            if not r.ok:
                return {"error": "Lỗi API Pixeldrain (HTTP {0})".format(r.status_code)}

            data = r.json()
            if not data.get("success", True):
                msg = data.get("message") or data.get("value") or "Không lấy được thông tin file"
                return {"error": "Pixeldrain: {0}".format(msg)}

            file_name = self._safe_name(data.get("name") or file_id)
            file_size = int(data.get("size") or 0)
            can_download = data.get("can_download", True)

            if not can_download:
                avail_msg = data.get("availability_message") or "File bị giới hạn tải xuống."
                return {"error": "Không thể tải: {0}".format(avail_msg)}

            return {
                "success": True,
                "file_id": file_id,
                "file_name": file_name,
                "file_size": file_size,
                "file_size_human": self._human_size(file_size),
                "download_url": "{0}/file/{1}".format(self.API_BASE, file_id),
                "rel_dir": "",
                "url": "https://pixeldrain.com/u/" + file_id,
            }
        except Exception as e:
            return {"error": "Lỗi kết nối Pixeldrain: {0}".format(str(e))}

    def _get_list_info(self, list_id, api_key=""):
        """Query metadata for a Pixeldrain album/list."""
        if requests is None:
            return {"error": "Module 'requests' chưa được cài đặt."}

        headers, auth = self._get_auth_headers(api_key)
        list_url = "{0}/list/{1}".format(self.API_BASE, list_id)

        try:
            r = requests.get(list_url, headers=headers, auth=auth, timeout=20)
            if r.status_code == 404:
                return {"error": "Album/Danh sách không tồn tại trên Pixeldrain (404)."}
            if not r.ok:
                return {"error": "Lỗi API Pixeldrain List (HTTP {0})".format(r.status_code)}

            data = r.json()
            if not data.get("success", True):
                msg = data.get("message") or "Không lấy được thông tin album"
                return {"error": "Pixeldrain: {0}".format(msg)}

            title = self._safe_name(data.get("title") or ("Pixeldrain_List_" + list_id))
            files_raw = data.get("files") or []

            if not files_raw:
                return {"error": "Album này rỗng (không có file nào)."}

            items = []
            for f in files_raw:
                fid = f.get("id")
                if not fid:
                    continue
                name = self._safe_name(f.get("name") or fid)
                size = int(f.get("size") or 0)
                items.append({
                    "url": "https://pixeldrain.com/u/" + fid,
                    "file_id": fid,
                    "file_name": name,
                    "file_size": size,
                    "file_size_human": self._human_size(size),
                    "download_url": "{0}/file/{1}".format(self.API_BASE, fid),
                    "rel_dir": title,
                })

            return {
                "success": True,
                "list_id": list_id,
                "title": title,
                "items": items,
                "total_items": len(items),
            }
        except Exception as e:
            return {"error": "Lỗi kết nối Album Pixeldrain: {0}".format(str(e))}

    # ==================== EXPAND INPUTS ====================

    def expand_inputs(self, raw, api_key=""):
        """Parse raw multi-line or single URL inputs and expand all files/lists."""
        if isinstance(raw, list):
            raw_urls = [u.strip() for u in raw if u.strip()]
        else:
            raw_urls = [u.strip() for u in (raw or '').splitlines() if u.strip()]

        if not raw_urls:
            return {"error": "Không tìm thấy link Pixeldrain hợp lệ trong danh sách."}

        all_items = []
        for url in raw_urls:
            if self.stop_checker() or self._stopped:
                break

            url_type, item_id = self._parse_url(url)
            if not url_type or not item_id:
                return {"error": "Link Pixeldrain không hợp lệ: {0}".format(url)}

            if url_type == 'file':
                self.log_callback(logging.INFO, "Đang lấy thông tin file {0}...".format(item_id))
                info = self._get_file_info(item_id, api_key)
                if "error" in info:
                    return info
                all_items.append(info)
            elif url_type == 'list':
                self.log_callback(logging.INFO, "Đang lấy danh sách album {0}...".format(item_id))
                list_info = self._get_list_info(item_id, api_key)
                if "error" in list_info:
                    return list_info
                all_items.extend(list_info.get("items", []))

        if not all_items:
            return {"error": "Không tìm thấy file nào trong danh sách link Pixeldrain."}

        return {
            "success": True,
            "items": all_items,
            "total_items": len(all_items),
        }

    def get_file_info(self, url, api_key=""):
        """Get file or album metadata for UI info check."""
        expanded = self.expand_inputs(url, api_key)
        if "error" in expanded:
            return expanded

        items = expanded.get("items", [])
        total_items = len(items)

        if total_items == 1:
            item = items[0]
            return {
                "success": True,
                "file_name": item["file_name"],
                "file_size": item["file_size"],
                "file_size_human": item["file_size_human"],
                "download_url": item["download_url"],
                "download_url_ready": True,
                "item_count": 1,
                "items": items,
            }
        else:
            total_size = sum(item.get("file_size", 0) for item in items)
            first_folder = items[0].get("rel_dir") or "Pixeldrain Album"
            return {
                "success": True,
                "file_name": "{0} ({1} files)".format(first_folder, total_items),
                "file_size": total_size,
                "file_size_human": self._human_size(total_size),
                "download_url_ready": True,
                "item_count": total_items,
                "items": items,
            }

    # ==================== DOWNLOAD ====================

    def download_to_vps(self, download_url, api_key, tmp_dir, file_name, file_size):
        """Download a file from Pixeldrain to VPS temp directory with .part support."""
        self._download_error = ''
        if requests is None:
            self.log_callback(logging.ERROR, "Module 'requests' chưa được cài đặt.")
            self._download_error = 'fatal'
            return None

        os.makedirs(tmp_dir, exist_ok=True)
        safe_name = self._safe_name(file_name)
        file_path = os.path.join(tmp_dir, safe_name)
        part_path = file_path + '.part'
        file_path_for_io = self._path_for_io(file_path)
        part_path_for_io = self._path_for_io(part_path)

        headers, auth = self._get_auth_headers(api_key)

        try:
            if os.path.exists(file_path_for_io):
                existing_size = os.path.getsize(file_path_for_io)
                if file_size > 0 and existing_size == file_size:
                    self.log_callback(logging.INFO, "File đã tải đủ trên VPS, chuyển sang upload.")
                    return file_path_for_io

            resume_from = 0
            if os.path.exists(part_path_for_io):
                resume_from = os.path.getsize(part_path_for_io)
                if file_size > 0 and resume_from > file_size:
                    self.log_callback(logging.WARNING, "File .part lớn hơn metadata, xóa và tải lại.")
                    try:
                        os.remove(part_path_for_io)
                    except Exception:
                        pass
                    resume_from = 0
                elif file_size > 0 and resume_from == file_size:
                    os.rename(part_path_for_io, file_path_for_io)
                    self.log_callback(logging.INFO, "File .part đã đủ size, đổi tên thành file hoàn chỉnh.")
                    return file_path_for_io

            # Check disk space
            try:
                disk = shutil.disk_usage(os.path.dirname(tmp_dir) or '/tmp')
                remaining_size = max((file_size or 0) - resume_from, 0)
                if remaining_size > 0 and disk.free < remaining_size * 1.1:
                    self.log_callback(logging.ERROR,
                                      "Không đủ dung lượng ổ cứng! Cần thêm {0}, còn trống {1}".format(
                                          self._human_size(remaining_size), self._human_size(disk.free)))
                    self._download_error = 'fatal'
                    return None
            except Exception:
                pass

            if resume_from > 0:
                headers["Range"] = "bytes={0}-".format(resume_from)
                self.log_callback(logging.INFO, "Resume từ {0}".format(self._human_size(resume_from)))

            self._response = requests.get(download_url, headers=headers, auth=auth, stream=True, timeout=60)
            status_code = self._response.status_code

            if resume_from > 0:
                if status_code != 206:
                    self.log_callback(logging.WARNING,
                                      "Server không chấp nhận resume (HTTP {0}). Tải lại từ đầu.".format(status_code))
                    resume_from = 0
                    if "Range" in headers:
                        del headers["Range"]
                    self._response.close()
                    self._response = requests.get(download_url, headers=headers, auth=auth, stream=True, timeout=60)
                    if self._response.status_code != 200:
                        self.log_callback(logging.ERROR, "HTTP tải file lỗi: {0}".format(self._response.status_code))
                        self._download_error = 'retryable'
                        return None
            else:
                if status_code != 200:
                    self.log_callback(logging.ERROR, "HTTP tải file lỗi: {0}".format(status_code))
                    self._download_error = 'retryable'
                    return None

            content_length = int(self._response.headers.get('Content-Length', file_size) or file_size)
            if content_length > 0 and resume_from == 0:
                file_size = content_length

            downloaded = resume_from
            last_progress_time = time.time()
            last_downloaded = resume_from
            mode = 'ab' if resume_from > 0 else 'wb'

            with open(part_path_for_io, mode) as f:
                for chunk in self._response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING, "Tải bị tạm dừng. File .part được giữ để resume.")
                        self._response.close()
                        self._download_error = 'stopped'
                        return None

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        now = time.time()
                        if now - last_progress_time >= self.PROGRESS_THROTTLE:
                            if file_size > 0:
                                dl_percent = min(int(downloaded * 50 / file_size), 50)
                            else:
                                dl_percent = 0

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
                            self._progress(dl_percent, msg)
                            last_progress_time = now
                            last_downloaded = downloaded

            actual_size = os.path.getsize(part_path_for_io)
            if file_size > 0 and actual_size != file_size:
                self.log_callback(logging.WARNING,
                                  "Download chưa đủ size ({0}/{1}), giữ file .part để resume.".format(
                                      self._human_size(actual_size), self._human_size(file_size)))
                self._download_error = 'retryable'
                return None

            os.rename(part_path_for_io, file_path_for_io)
            self.log_callback(logging.INFO,
                              "Tải xong về VPS: {0} ({1})".format(safe_name, self._human_size(actual_size)))
            return file_path_for_io

        except requests.exceptions.Timeout:
            self.log_callback(logging.WARNING, "Kết nối tới Pixeldrain bị timeout. Giữ file .part để resume.")
            self._download_error = 'retryable'
            return None
        except requests.exceptions.ConnectionError:
            self.log_callback(logging.WARNING, "Mất kết nối khi đang tải từ Pixeldrain. Giữ file .part để resume.")
            self._download_error = 'retryable'
            return None
        except IOError as e:
            self.log_callback(logging.ERROR, "Lỗi ghi file: {0}".format(str(e)))
            self._download_error = 'fatal'
            return None
        except Exception as e:
            self.log_callback(logging.ERROR, "Lỗi tải file: {0}".format(str(e)))
            self._download_error = 'retryable'
            return None

    # ==================== UPLOAD TO GOOGLE DRIVE ====================

    def upload_to_drive(self, local_path, drive_dest):
        """Upload a local file to Google Drive using gclone/rclone."""
        binary = self._detect_binary()

        dest = drive_dest
        m = re.match(r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', drive_dest)
        if m:
            dest = "{0}:{{{1}}}{2}".format(m.group(1), m.group(2), m.group(3) or '')

        cmd = [binary, "copy", local_path, dest, "--verbose", "--stats=1s", "--stats-one-line"]

        sa_dir = self._get_sa_dir()
        if sa_dir:
            sa_count = len(glob.glob(os.path.join(sa_dir, '*.json')))
            cmd.extend(["--drive-service-account-file-path", sa_dir])
            self.log_callback(logging.INFO, "SA rotation enabled: {0} accounts".format(sa_count))

        self.log_callback(logging.INFO, "Uploading to Google Drive: {0}".format(dest))

        try:
            cmd_bytes = self._cmd_for_subprocess(cmd)
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
                        overall = 50 + int(rclone_percent * 50 / 100)
                        self._progress(overall, "Uploading: {0}%".format(rclone_percent))
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
            self.log_callback(logging.ERROR, "Binary '{0}' not found. Install gclone/rclone.".format(binary))
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

    def run_full_pipeline(self, url, config, drive_dest):
        """Run the complete Pixeldrain -> Google Drive pipeline."""
        self._stopped = False
        max_attempts = 3

        api_key = ''
        if isinstance(config, dict):
            api_key = config.get('api_key', '')
        elif isinstance(config, str):
            api_key = config

        try:
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO, "BƯỚC 1/3: Quét danh sách file Pixeldrain...")
            self._emit_state(status='fetching_info', phase='info')
            self._progress(0, "Đang lấy danh sách file Pixeldrain...")

            expanded = self.expand_inputs(url, api_key)
            if "error" in expanded:
                self.log_callback(logging.ERROR, expanded["error"])
                return False

            items = expanded.get("items") or []
            total_items = len(items)
            if not total_items:
                self.log_callback(logging.ERROR, "Không có file Pixeldrain nào để tải.")
                return False

            self._emit_state(total_items=total_items, current_index=0)
            self.log_callback(logging.INFO, "Đã tìm thấy {0} file Pixeldrain.".format(total_items))

            # Step 0: GDrive pre-scan
            self.log_callback(logging.INFO, "Kiểm tra file đã có trên Google Drive...")
            existing_files = self._scan_gdrive_existing(drive_dest)

            for index, item in enumerate(items, 1):
                if self.stop_checker() or self._stopped:
                    return False

                span = 100.0 / total_items
                self._progress_base = (index - 1) * span
                self._progress_span = span

                display_name = item.get("file_name") or "Pixeldrain file"
                item_size = item.get("file_size", 0)
                rel_dir = item.get("rel_dir") or ""
                download_url = item.get("download_url") or ("{0}/file/{1}".format(self.API_BASE, item.get("file_id")))

                self._emit_state(
                    current_index=index,
                    total_items=total_items,
                    file_name=display_name,
                    file_size=item_size,
                    file_size_human=item.get("file_size_human", ""),
                )

                self.log_callback(logging.INFO, "=" * 50)
                self.log_callback(logging.INFO, "File {0}/{1}: {2} ({3})".format(
                    index, total_items, display_name, item.get("file_size_human", "")))
                if rel_dir:
                    self.log_callback(logging.INFO, "Thư mục đích con: {0}".format(rel_dir))

                # Step 1: Check GDrive skip
                if rel_dir:
                    check_path = (rel_dir.replace('\\', '/').strip('/') + '/' + display_name).strip('/')
                else:
                    check_path = display_name
                check_path = check_path.replace('\\', '/').strip('/')

                if item_size > 0 and ((check_path, item_size) in existing_files or (display_name, item_size) in existing_files):
                    self.log_callback(logging.INFO, "Đã có trên Google Drive, skip: {0}".format(check_path))
                    self._progress(100, "Skipped (đã có trên GDrive)")
                    continue

                # Step 2: Check VPS complete file
                resume_key = hashlib.sha1("{0}_{1}".format(item.get("file_id", ""), display_name).encode('utf-8')).hexdigest()[:24]
                item_tmp_dir = os.path.join('/tmp', 'pixeldrain_dl', resume_key)
                local_path = self._find_completed_in_dir(item_tmp_dir, item_size, display_name)

                if local_path:
                    self.log_callback(logging.INFO, "File đã tải đủ trên VPS, chuyển sang upload.")
                else:
                    self.log_callback(logging.INFO, "BƯỚC 2/3: Tải file về VPS...")
                    self._emit_state(status='downloading', phase='download')
                    self._progress(2, "Bắt đầu tải từ Pixeldrain...")

                    for attempt in range(max_attempts):
                        if self.stop_checker() or self._stopped:
                            return False

                        local_path = self.download_to_vps(download_url, api_key, item_tmp_dir, display_name, item_size)
                        if local_path:
                            break

                        if self.stop_checker() or self._stopped or self._download_error == 'stopped':
                            return False
                        if self._download_error != 'retryable':
                            return False

                        self.log_callback(logging.WARNING, "Tải file lỗi. Thử lại (lần {0}/{1})...".format(attempt + 1, max_attempts))
                        time.sleep(2)

                    if not local_path:
                        self.log_callback(logging.ERROR, "Tải file '{0}' thất bại sau các lần thử.".format(display_name))
                        return False

                if self.stop_checker() or self._stopped:
                    return False

                # Step 3: Upload to Google Drive
                self.log_callback(logging.INFO, "BƯỚC 3/3: Đẩy file lên Google Drive...")
                self._emit_state(status='uploading', phase='upload')
                self._progress(50, "Bắt đầu upload lên Google Drive...")

                item_dest = self._append_dest_path(drive_dest, rel_dir)
                success = self.upload_to_drive(local_path, item_dest)
                if not success:
                    return False

                self.cleanup(item_tmp_dir)

            self._progress_base = 0.0
            self._progress_span = 100.0
            self._emit_state(status='done', phase='done', current_index=total_items, total_items=total_items)
            self._progress(100, "Hoàn tất!")
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO, "HOÀN TẤT! Tất cả file Pixeldrain đã được copy lên Google Drive.")
            return True

        except Exception as e:
            self.log_callback(logging.ERROR, "Pipeline error: {0}".format(str(e)))
            return False

    # ==================== STOP ====================

    def stop(self):
        """Stop the current pipeline."""
        self._stopped = True
        if self._response:
            try:
                self._response.close()
            except Exception:
                pass
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
