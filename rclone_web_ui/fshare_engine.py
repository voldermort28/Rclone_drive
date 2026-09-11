"""
FshareEngine - Download Fshare files with a VIP account and upload to Google Drive.
Isolated from the existing Drive-to-Drive and Terabox flows.
Compatible with Python 3.6+.
"""

import glob
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import time

try:
    import requests
except ImportError:
    requests = None


class FshareEngine:
    API_BASE = "https://api2.fshare.vn/api"
    DEFAULT_APP_KEY = "L2S7R6ZMagggC5wWkQhX2+aDi467PPuftWUMRFSn"
    DEFAULT_USER_AGENT = "Fshare/1 CFNetwork/1209 Darwin/20.2.0"
    CHUNK_SIZE = 1024 * 1024

    def __init__(self, progress_callback, log_callback, stop_checker, state_callback=None):
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stop_checker = stop_checker
        self.state_callback = state_callback
        self._process = None
        self._response = None
        self._stopped = False
        self._token = ""
        self._session_id = ""
        self._progress_base = 0.0
        self._progress_span = 100.0

    def _progress(self, percent, message):
        overall = self._progress_base + (float(percent) * self._progress_span / 100.0)
        self.progress_callback(overall, message)

    def _emit_state(self, **kwargs):
        if not self.state_callback:
            return
        try:
            self.state_callback(kwargs)
        except Exception:
            pass

    def _detect_binary(self):
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
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sa_dir = os.path.join(base_dir, 'sa')
        if os.path.isdir(sa_dir) and glob.glob(os.path.join(sa_dir, '*.json')):
            return sa_dir
        return None

    def _cmd_for_subprocess(self, cmd):
        if sys.getfilesystemencoding().lower() == 'ascii':
            return [arg.encode('utf-8') if isinstance(arg, str) else arg for arg in cmd]
        return cmd

    def _path_for_io(self, path):
        if isinstance(path, bytes):
            return path
        if sys.getfilesystemencoding().lower() == 'ascii':
            return path.encode('utf-8')
        return path

    def _safe_name(self, name):
        name = (name or '').strip()
        name = re.sub(r'[\\/*?:"<>|]', '_', name)
        return name or 'fshare_download'

    def _file_id_from_url(self, url):
        raw = (url or '').strip()
        m = re.search(r'fshare\.vn/file/([A-Za-z0-9]+)', raw, re.I)
        if m:
            return m.group(1)
        if re.match(r'^[A-Za-z0-9]{8,}$', raw):
            return raw
        return ""

    def _file_url(self, file_id):
        return "https://www.fshare.vn/file/{0}".format(file_id)

    def _headers(self, config, with_cookie=True):
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': config.get('user_agent') or self.DEFAULT_USER_AGENT,
        }
        if with_cookie and self._session_id:
            headers['Cookie'] = 'session_id={0}'.format(self._session_id)
        return headers

    def _human_size(self, size):
        try:
            size = float(size)
        except Exception:
            return ''
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return "{0:.2f} {1}".format(size, unit)
            size /= 1024.0
        return "{0:.2f} PB".format(size)

    def _guess_name_from_response(self, response, fallback):
        cd = response.headers.get('Content-Disposition', '') if response else ''
        m = re.search(r'filename\*=UTF-8\'\'([^;]+)', cd, re.I)
        if m:
            try:
                from urllib.parse import unquote
                return self._safe_name(unquote(m.group(1).strip('"')))
            except Exception:
                return self._safe_name(m.group(1).strip('"'))
        m = re.search(r'filename="?([^";]+)"?', cd, re.I)
        if m:
            return self._safe_name(m.group(1))
        return self._safe_name(fallback)

    def _resume_dir_for_url(self, url):
        key = hashlib.sha1((url or '').encode('utf-8')).hexdigest()[:24]
        return os.path.join('/tmp', 'fshare_dl', key)

    def _scan_gdrive_existing(self, drive_dest):
        """Scan GDrive destination, return set((filename, size))."""
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
                import json
                data = json.loads(stdout.decode('utf-8', errors='replace'))
                for item in data:
                    path = item.get('Path', '')
                    size = item.get('Size', 0)
                    if path:
                        norm = path.replace('\\', '/').strip('/')
                        existing.add((norm, size))
                self.log_callback(logging.INFO,
                    "GDrive scan: tim thay {0} file da co.".format(len(existing)))
        except Exception as e:
            self.log_callback(logging.WARNING,
                "Khong the quet GDrive: {0}".format(e))
        return existing

    def _find_completed_in_dir(self, tmp_dir, expected_size):
        """Find a completed (non-.part) file in tmp_dir matching expected_size."""
        try:
            if not os.path.isdir(tmp_dir):
                return None
            for fname in os.listdir(tmp_dir):
                if fname == 'download.part':
                    continue
                fpath = os.path.join(tmp_dir, fname)
                if os.path.isfile(fpath) and expected_size > 0:
                    if os.path.getsize(fpath) == expected_size:
                        return fpath
        except Exception:
            pass
        return None

    def login(self, config):
        if requests is None:
            return {'error': "Module 'requests' chưa được cài. Chạy: pip install requests"}

        missing = []
        for key in ['email', 'password']:
            if not config.get(key):
                missing.append(key)
        if missing:
            return {'error': 'Thiếu cấu hình Fshare: {0}'.format(', '.join(missing))}

        body = {
            'user_email': config.get('email'),
            'password': config.get('password'),
            'app_key': config.get('app_key') or self.DEFAULT_APP_KEY,
        }
        try:
            self.log_callback(logging.INFO, "Đăng nhập Fshare...")
            resp = requests.post(
                self.API_BASE + '/user/login',
                json=body,
                headers=self._headers(config, with_cookie=False),
                timeout=20,
            )
        except Exception as e:
            return {'error': 'Không kết nối được Fshare: {0}'.format(str(e))}

        if resp.status_code != 200:
            return {'error': 'Đăng nhập Fshare thất bại ({0}): {1}'.format(resp.status_code, resp.text[:300])}

        try:
            data = resp.json()
        except Exception:
            return {'error': 'Fshare trả về dữ liệu đăng nhập không hợp lệ.'}

        token = data.get('token') or ''
        session_id = data.get('session_id') or ''
        if not token or not session_id:
            return {'error': 'Không lấy được token/session_id từ Fshare.'}

        self._token = token
        self._session_id = session_id
        return {'success': True}

    def get_direct_link(self, url, config, file_password=''):
        file_id = self._file_id_from_url(url)
        if not file_id:
            return {'error': 'Link Fshare không hợp lệ. Cần dạng https://www.fshare.vn/file/...'}

        logged = self.login(config)
        if 'error' in logged:
            return logged

        body = {
            'zipflag': 0,
            'url': self._file_url(file_id),
            'password': file_password or '',
            'token': self._token,
        }
        try:
            self.log_callback(logging.INFO, "Đang lấy direct link Fshare...")
            resp = requests.post(
                self.API_BASE + '/session/download',
                json=body,
                headers=self._headers(config),
                timeout=20,
            )
        except Exception as e:
            return {'error': 'Không lấy được direct link: {0}'.format(str(e))}

        if resp.status_code != 200:
            return {'error': 'Fshare không cấp direct link ({0}): {1}'.format(resp.status_code, resp.text[:300])}

        try:
            data = resp.json()
        except Exception:
            return {'error': 'Direct link response không hợp lệ.'}

        location = data.get('location') or data.get('url') or ''
        if not location:
            return {'error': 'Không tìm thấy direct link trong phản hồi Fshare.'}
        return {'success': True, 'file_id': file_id, 'url': location}

    def get_file_info(self, url, config, file_password=''):
        direct = self.get_direct_link(url, config, file_password)
        if 'error' in direct:
            return direct

        file_id = direct.get('file_id') or self._file_id_from_url(url)
        info = {
            'success': True,
            'file_id': file_id,
            'file_name': file_id,
            'file_size': 0,
            'file_size_human': '',
            'download_url_ready': True,
        }

        try:
            r = requests.head(direct['url'], allow_redirects=True, timeout=20, headers={
                'User-Agent': config.get('user_agent') or self.DEFAULT_USER_AGENT
            })
            if r.ok:
                size = int(r.headers.get('Content-Length') or 0)
                name = self._guess_name_from_response(r, file_id)
                info.update({
                    'file_name': name,
                    'file_size': size,
                    'file_size_human': self._human_size(size),
                })
        except Exception:
            pass
        return info

    def download_to_vps(self, url, config, tmp_dir, file_password=''):
        direct = self.get_direct_link(url, config, file_password)
        if 'error' in direct:
            self.log_callback(logging.ERROR, direct['error'])
            return None

        os.makedirs(tmp_dir, exist_ok=True)
        headers = {'User-Agent': config.get('user_agent') or self.DEFAULT_USER_AGENT}
        part_path = os.path.join(tmp_dir, 'download.part')
        meta_name = direct.get('file_id') or 'fshare_download'
        existing = os.path.getsize(part_path) if os.path.exists(part_path) else 0
        if existing > 0:
            headers['Range'] = 'bytes={0}-'.format(existing)
            self.log_callback(logging.INFO, "Resume Fshare từ {0}".format(self._human_size(existing)))

        try:
            self._response = requests.get(direct['url'], headers=headers, stream=True, timeout=30)
            if self._response.status_code not in (200, 206):
                self.log_callback(logging.ERROR, "Fshare download HTTP {0}".format(self._response.status_code))
                return None

            file_name = self._guess_name_from_response(self._response, meta_name)
            total_header = int(self._response.headers.get('Content-Length') or 0)
            total_size = total_header + existing if self._response.status_code == 206 else total_header
            final_path = os.path.join(tmp_dir, file_name)
            part_path_io = self._path_for_io(part_path)
            final_path_io = self._path_for_io(final_path)
            mode = 'ab' if self._response.status_code == 206 and existing > 0 else 'wb'

            if mode == 'wb' and os.path.exists(part_path_io):
                os.remove(part_path_io)
                existing = 0

            self._emit_state(file_name=file_name, file_size=total_size,
                             file_size_human=self._human_size(total_size))
            downloaded = existing
            last_emit = 0
            with open(part_path_io, mode) as f:
                for chunk in self._response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING, "Download Fshare bị dừng.")
                        return None
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last_emit >= 1:
                        pct = int(downloaded * 50 / total_size) if total_size else 5
                        pct = max(2, min(50, pct))
                        self._progress(pct, "Downloading: {0}".format(self._human_size(downloaded)))
                        last_emit = now

            try:
                if os.path.exists(final_path_io):
                    os.remove(final_path_io)
                os.rename(part_path_io, final_path_io)
            except Exception:
                # If unicode rename fails on ascii filesystem, fallback to ascii-safe name
                import unicodedata
                ascii_name = unicodedata.normalize('NFKD', file_name).encode('ascii', 'ignore').decode('ascii')
                if not ascii_name:
                    ascii_name = "fshare_file_" + str(int(time.time()))
                final_path = os.path.join(tmp_dir, ascii_name)
                final_path_io = self._path_for_io(final_path)
                if os.path.exists(final_path_io):
                    os.remove(final_path_io)
                os.rename(part_path_io, final_path_io)

            self._progress(50, "Tải Fshare hoàn tất")
            self.log_callback(logging.INFO, "Đã tải về VPS: {0}".format(file_name))
            return final_path_io
        except Exception as e:
            self.log_callback(logging.ERROR, "Lỗi tải Fshare: {0}".format(str(e)))
            return None
        finally:
            self._response = None

    def upload_to_drive(self, local_path, drive_dest):
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
            self._process = subprocess.Popen(
                self._cmd_for_subprocess(cmd),
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
                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING, "Upload bị dừng bởi người dùng.")
                        self._process.terminate()
                        return False

                self._process.wait()
                if self._process.returncode == 0:
                    self.log_callback(logging.INFO, "Upload lên Google Drive thành công!")
                    return True
                self.log_callback(logging.ERROR, "Rclone exited with code {0}".format(self._process.returncode))
                return False
        except FileNotFoundError:
            self.log_callback(logging.ERROR, "Không tìm thấy gclone/rclone.")
            return False
        except Exception as e:
            self.log_callback(logging.ERROR, "Upload error: {0}".format(str(e)))
            return False
        finally:
            self._process = None

    def cleanup(self, tmp_dir):
        try:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
                self.log_callback(logging.INFO, "Đã dọn dẹp file tạm: {0}".format(tmp_dir))
        except Exception as e:
            self.log_callback(logging.WARNING, "Lỗi dọn dẹp: {0}".format(str(e)))

    def run_full_pipeline(self, url, config, drive_dest, file_password=''):
        self._stopped = False
        try:
            # Parse multi-URL input (textarea: moi dong 1 link)
            if isinstance(url, list):
                urls = [u.strip() for u in url if u.strip()]
            else:
                urls = [u.strip() for u in (url or '').splitlines() if u.strip()]
            if not urls:
                self.log_callback(logging.ERROR, "Khong co link Fshare nao.")
                return False

            total_urls = len(urls)
            self._emit_state(total_items=total_urls, current_index=0)

            # Step 0: GDrive pre-scan (1 lan duy nhat)
            self.log_callback(logging.INFO, "Kiem tra file da co tren Google Drive...")
            existing_files = self._scan_gdrive_existing(drive_dest)

            for idx, single_url in enumerate(urls, 1):
                if self.stop_checker() or self._stopped:
                    return False

                span = 100.0 / total_urls
                self._progress_base = (idx - 1) * span
                self._progress_span = span

                tmp_dir = self._resume_dir_for_url(single_url)

                self.log_callback(logging.INFO, "=" * 50)
                if total_urls > 1:
                    self.log_callback(logging.INFO, "File {0}/{1}".format(idx, total_urls))
                self.log_callback(logging.INFO, "BUOC 1/3: Lay direct link Fshare...")
                self._emit_state(status='fetching_info', phase='info',
                                 current_index=idx, total_items=total_urls)
                self.progress_callback(0, "Dang lay thong tin Fshare...")

                info = self.get_file_info(single_url, config, file_password)
                if 'error' in info:
                    self.log_callback(logging.ERROR, info['error'])
                    return False

                file_name = info.get('file_name', '')
                file_size = info.get('file_size', 0)
                file_id = info.get('file_id', '')
                self._emit_state(file_name=file_name,
                                 file_size=file_size,
                                 file_size_human=info.get('file_size_human', ''))

                # Step 1: Check GDrive skip
                if file_name and file_name != file_id and file_size > 0:
                    if (file_name, file_size) in existing_files:
                        self.log_callback(logging.INFO,
                            "File da co tren GDrive, skip hoan toan: {0}".format(file_name))
                        self._progress(100, "Skipped (da co tren GDrive)")
                        continue

                if self.stop_checker() or self._stopped:
                    return False

                # Save pending metadata
                try:
                    from pending_manager import save_pending_meta
                    save_pending_meta(tmp_dir, url=single_url, file_name=file_name,
                                      file_size=file_size, dest=drive_dest, engine='fshare')
                except Exception:
                    pass

                # Step 2: Check VPS complete file
                local_path = self._find_completed_in_dir(tmp_dir, file_size)
                if local_path:
                    self.log_callback(logging.INFO,
                        "File da tai du tren VPS tu lan truoc, chuyen sang upload.")
                else:
                    self.log_callback(logging.INFO, "=" * 50)
                    self.log_callback(logging.INFO, "BUOC 2/3: Tai file Fshare ve VPS...")
                    self._emit_state(status='downloading', phase='download')
                    local_path = self.download_to_vps(single_url, config, tmp_dir, file_password)
                    if not local_path:
                        return False

                if self.stop_checker() or self._stopped:
                    return False

                self.log_callback(logging.INFO, "=" * 50)
                self.log_callback(logging.INFO, "BUOC 3/3: Day file len Google Drive...")
                self._emit_state(status='uploading', phase='upload')
                self._progress(50, "Bat dau upload len Google Drive...")
                success = self.upload_to_drive(local_path, drive_dest)
                if not success:
                    return False
                self.cleanup(tmp_dir)

            self._progress_base = 0
            self._progress_span = 100
            self._emit_state(status='done', phase='done',
                             current_index=total_urls, total_items=total_urls)
            self.progress_callback(100, "Hoan tat!")
            return True
        except Exception as e:
            self.log_callback(logging.ERROR, "Pipeline error: {0}".format(str(e)))
            return False

    def stop(self):
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
