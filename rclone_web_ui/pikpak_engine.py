# -*- coding: utf-8 -*-
"""
PikPakEngine - Download files and folders from PikPak (https://mypikpak.com/) and upload to Google Drive.
Supports single files, shared folders (recursive), multi-line URLs, and password-protected shares.
Fully compatible with Python 3.6+ (CentOS 7).
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
import uuid
import random

try:
    from urllib.parse import urlparse, parse_qs, unquote
except ImportError:
    from urlparse import urlparse, parse_qs
    from urllib import unquote

try:
    import requests
except ImportError:
    requests = None


class PikPakEngine:
    """Engine to handle PikPak download -> Google Drive upload pipeline."""

    API_BASE = "https://api-drive.mypikpak.com/drive/v1"
    API_FALLBACK = "https://api-drive.mypikpak.net/drive/v1"
    USER_BASE = "https://user.mypikpak.com/v1"
    USER_FALLBACK = "https://user.mypikpak.net/v1"
    AUTH_BASE = "https://user.mypikpak.com/v1/auth"
    AUTH_FALLBACK = "https://user.mypikpak.net/v1/auth"
    DEFAULT_CLIENT_ID = "YvtoWO6GNHiuCl7x"
    WEB_CLIENT_ID = "YUMx5nI8ZU8Ap8pm"
    WEB_PACKAGE_NAME = "drive.mypikpak.com"
    SHIELD_SALTS = [
        "fyZ4+p77W1U4zcWBUwefAIFhFxvADWtT1wzolCxhg9q7etmGUjXr",
        "uSUX02HYJ1IkyLdhINEFcCf7l2",
        "iWt97bqD/qvjIaPXB2Ja5rsBWtQtBZZmaHH2rMR41",
        "3binT1s/5a1pu3fGsN",
        "8YCCU+AIr7pg+yd7CkQEY16lDMwi8Rh4WNp5",
        "DYS3StqnAEKdGddRP8CJrxUSFh",
        "crquW+4",
        "ryKqvW9B9hly+JAymXCIfag5Z",
        "Hr08T/NDTX1oSJfHk90c",
        "i"
    ]
    CHUNK_SIZE = 1024 * 1024  # 1MB chunk size
    PROGRESS_THROTTLE = 2  # seconds between progress updates
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
        self._last_error = ''
        self._progress_base = 0.0
        self._progress_span = 100.0
        self._shield_device_id = uuid.uuid4().hex
        self._cached_captcha_token = None
        self._cached_captcha_expiry = 0

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
            return sa_dir if sa_dir.endswith('/') else sa_dir + '/'
        return None

    def _is_team_drive_target(self, destination):
        """
        Check if destination remote is a Shared Drive (Team Drive).
        Google Service Accounts have 0 personal storage quota and can ONLY write to Shared Drives.
        Writing to Personal My Drive with Service Accounts causes Google API to return 404 / 403 storageQuotaExceeded.
        """
        if not destination:
            return False
        remote_name = destination.split(':')[0] if ':' in destination else ''
        if not remote_name:
            return False
        config_path = os.path.expanduser('~/.config/rclone/rclone.conf')
        if not os.path.exists(config_path):
            return False
        try:
            try:
                import configparser
            except ImportError:
                import ConfigParser as configparser
            config = configparser.ConfigParser()
            config.read(config_path)
            if config.has_section(remote_name):
                if config.has_option(remote_name, 'team_drive') and config.get(remote_name, 'team_drive').strip():
                    return True
        except Exception:
            pass
        return False

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
        return name or 'pikpak_download'

    def _safe_remote_path(self, path):
        """Clean parts of a relative remote path."""
        parts = []
        for part in (path or '').split('/'):
            clean = self._safe_name(part)
            if clean and clean != 'pikpak_download':
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
            if sa_dir and self._is_team_drive_target(drive_dest):
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
        """Find a completed (non-.part) file in tmp_dir matching expected_size (or >=45% for files >=6GB)."""
        try:
            tmp_io = self._path_for_io(tmp_dir)
            if not os.path.isdir(tmp_io):
                return None
            safe_name = self._safe_name(file_name)
            target_path = os.path.join(tmp_dir, safe_name)
            target_path_io = self._path_for_io(target_path)
            if os.path.isfile(target_path_io) and expected_size > 0:
                sz = os.path.getsize(target_path_io)
                LIMIT_6GB = 6 * 1024 * 1024 * 1024
                if sz == expected_size or (expected_size >= LIMIT_6GB and sz >= int(0.45 * expected_size)):
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
            return "{0}s".format(int(seconds))
        elif seconds < 3600:
            return "{0}m {1}s".format(int(seconds // 60), int(seconds % 60))
        else:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return "{0}h {1}m".format(h, m)

    # ==================== PIKPAK API ====================

    def _parse_url(self, raw_url):
        """
        Extract share_id, parent_id, pass_code, and file_spec (keyword, index, or node ID) from PikPak URL.
        Supported formats:
        - https://mypikpak.com/s/VNxxxxxx
        - https://mypikpak.com/s/VNxxxxxx/folder_id
        - https://mypikpak.com/s/VNxxxxxx#1 or #KEYWORD
        - https://mypikpak.com/s/VNxxxxxx/file/1 or /file/KEYWORD
        - Query parameters ?pwd=xxxx, ?pass_code=xxxx, ?file=KEYWORD
        """
        url = (raw_url or '').strip()
        if not url:
            return None, None, '', ''

        pwd = ''
        file_spec = ''
        query_share_id = ''
        query_parent_id = ''
        try:
            parsed = urlparse(url)
            if parsed.fragment:
                file_spec = unquote(parsed.fragment).strip()
            qs = parse_qs(parsed.query)
            if 'pwd' in qs:
                pwd = qs['pwd'][0].strip()
            elif 'pass_code' in qs:
                pwd = qs['pass_code'][0].strip()
            if 'file' in qs:
                file_spec = qs['file'][0].strip()
            elif 'filter' in qs:
                file_spec = qs['filter'][0].strip()
            if 'share_id' in qs:
                query_share_id = qs['share_id'][0].strip()
            elif 'id' in qs:
                query_share_id = qs['id'][0].strip()
            if 'parent_id' in qs:
                query_parent_id = qs['parent_id'][0].strip()
        except Exception:
            pass

        url_clean = url.split('?')[0].split('#')[0].rstrip('/')

        # Check /file/SPEC in url path
        m_file = re.search(r'/file/(.+)$', url_clean)
        if m_file:
            file_spec = unquote(m_file.group(1)).strip()
            url_clean = url_clean[:m_file.start()].rstrip('/')

        if query_share_id:
            return query_share_id, query_parent_id, pwd, file_spec

        # Check /s/{share_id}/{parent_id} or /drive/s/{share_id}/{parent_id}
        m = re.search(r'/(?:s|drive/s)/([A-Za-z0-9_-]+)(?:/([A-Za-z0-9_-]+))?', url_clean)
        if m:
            share_id = m.group(1)
            parent_id = m.group(2) or ''
            return share_id, parent_id, pwd, file_spec

        # Match raw share_id length 6-32
        if re.match(r'^[A-Za-z0-9_-]{6,32}$', url_clean):
            return url_clean, '', pwd, file_spec

        return None, None, pwd, file_spec

    def _get_device_id(self, config):
        """Get or generate a persistent device ID."""
        device_id = ''
        if isinstance(config, dict):
            device_id = config.get('device_id', '').strip()
        if not device_id:
            device_id = hashlib.md5(str(uuid.getnode()).encode('utf-8')).hexdigest()
        return device_id

    def _compute_captcha_sign(self, client_id, client_version, package_name, device_id, timestamp):
        """Compute reverse-engineered PikPak multi-stage MD5 salt signature."""
        s = "{0}{1}{2}{3}{4}".format(client_id, client_version, package_name, device_id, timestamp)
        current = s
        for salt in self.SHIELD_SALTS:
            current = hashlib.md5((current + salt).encode('utf-8')).hexdigest()
        return "1." + current

    def _get_shield_captcha_token(self):
        """
        Dynamically obtain a valid PikPak captcha_token via reverse-engineered shield API.
        Caches token for 4 minutes to minimize network roundtrips.
        """
        now = time.time()
        cached = getattr(self, '_cached_captcha_token', None)
        expiry = getattr(self, '_cached_captcha_expiry', 0)
        if cached and expiry > (now + 30):
            return cached

        if requests is None:
            return None

        device_id = getattr(self, '_shield_device_id', None)
        if not device_id:
            device_id = uuid.uuid4().hex
            self._shield_device_id = device_id

        timestamp = str(int(now * 1000))
        captcha_sign = self._compute_captcha_sign(
            self.WEB_CLIENT_ID, "undefined", self.WEB_PACKAGE_NAME, device_id, timestamp
        )
        device_sign = "wdi10." + device_id + ("x" * 32)

        headers = {
            "User-Agent": self.USER_AGENT,
            "x-client-id": self.WEB_CLIENT_ID,
            "x-device-id": device_id,
            "x-device-sign": device_sign,
            "Content-Type": "application/json;charset=utf-8"
        }
        body = {
            "client_id": self.WEB_CLIENT_ID,
            "action": "POST:/config/v1/activity_operation",
            "device_id": device_id,
            "meta": {
                "captcha_sign": captcha_sign,
                "client_version": "undefined",
                "package_name": self.WEB_PACKAGE_NAME,
                "user_id": "",
                "timestamp": timestamp
            }
        }

        urls = [
            "{0}/shield/captcha/init".format(self.USER_BASE),
            "{0}/shield/captcha/init".format(self.USER_FALLBACK)
        ]
        for u in urls:
            try:
                r = requests.post(u, headers=headers, json=body, timeout=12)
                if r.ok:
                    data = r.json()
                    token = data.get('captcha_token')
                    expires_in = int(data.get('expires_in', 300) or 300)
                    if token:
                        self._cached_captcha_token = token
                        self._cached_captcha_expiry = now + expires_in
                        return token
            except Exception as e:
                self.log_callback(logging.DEBUG, "Shield captcha init failed on {0}: {1}".format(u, e))

        return None

    def _get_headers(self, config=None, access_token=None, use_web_client=False):
        """Build standard headers required by PikPak backend."""
        if use_web_client:
            client_id = self.WEB_CLIENT_ID
            device_id = getattr(self, '_shield_device_id', None) or self._get_device_id(config)
        else:
            client_id = self.DEFAULT_CLIENT_ID
            if isinstance(config, dict) and config.get('client_id'):
                client_id = config.get('client_id')
            device_id = self._get_device_id(config)

        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=utf-8",
            "x-client-id": client_id,
            "x-device-id": device_id,
            "x-client-version": "2.3.2.4101" if not use_web_client else "1.0.0",
            "x-os-version": "Win32" if not use_web_client else "MacIntel",
            "x-protocol-version": "301",
            "x-sdk-version": "6.0.0" if not use_web_client else "8.1.4",
        }
        if use_web_client:
            headers["x-device-sign"] = "wdi10." + device_id + ("x" * 32)
        if access_token:
            headers["Authorization"] = "Bearer " + access_token
        return headers

    def _api_request(self, method, path, config=None, access_token=None, params=None, json_data=None, timeout=20):
        """Execute API request trying primary host then fallback."""
        if requests is None:
            return None

        is_share_path = (path or '').startswith('/share')
        headers = self._get_headers(config, access_token, use_web_client=is_share_path)

        if is_share_path:
            token = self._get_shield_captcha_token()
            if token:
                headers['x-captcha-token'] = token

        urls = [
            "{0}{1}".format(self.API_BASE, path),
            "{0}{1}".format(self.API_FALLBACK, path)
        ]

        for u in urls:
            try:
                if method.upper() == 'GET':
                    r = requests.get(u, headers=headers, params=params, timeout=timeout)
                elif method.upper() == 'POST':
                    r = requests.post(u, headers=headers, json=json_data, params=params, timeout=timeout)
                elif method.upper() == 'DELETE':
                    r = requests.delete(u, headers=headers, json=json_data, params=params, timeout=timeout)
                else:
                    r = requests.request(method, u, headers=headers, json=json_data, params=params, timeout=timeout)
                return r
            except Exception as e:
                self.log_callback(logging.DEBUG, "PikPak API request failed on {0}: {1}".format(u, e))
                continue
        return None

    def _load_config_file(self, config=None):
        """Load pikpak_config.json from disk if config is empty."""
        if isinstance(config, dict) and config:
            return config
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            cfg_path = os.path.join(base_dir, 'pikpak_config.json')
            if os.path.isfile(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        return loaded
        except Exception:
            pass
        return config if isinstance(config, dict) else {}

    def _get_valid_access_token(self, config):
        """
        Verify or refresh user access token.
        Supports refresh_token or username + password.
        """
        config = self._load_config_file(config)
        if not isinstance(config, dict):
            return None

        access_token = config.get('access_token', '').strip()
        expiry = float(config.get('access_token_expiry', 0) or 0)
        now = time.time()

        # If current access_token is valid for at least 5 more minutes, use it
        if access_token and expiry > (now + 300):
            return access_token

        client_id = config.get('client_id') or self.DEFAULT_CLIENT_ID
        refresh_token = config.get('refresh_token', '').strip()
        username = config.get('username', '').strip()
        password = config.get('password', '').strip()

        # Try refresh token first
        if refresh_token:
            headers = self._get_headers(config)
            auth_urls = [
                "{0}/token".format(self.AUTH_BASE),
                "{0}/token".format(self.AUTH_FALLBACK)
            ]
            payload = {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
            for u in auth_urls:
                try:
                    r = requests.post(u, headers=headers, json=payload, timeout=15)
                    if r.ok:
                        data = r.json()
                        new_access = data.get('access_token')
                        new_refresh = data.get('refresh_token') or refresh_token
                        expires_in = int(data.get('expires_in', 3600) or 3600)
                        if new_access:
                            config['access_token'] = new_access
                            config['refresh_token'] = new_refresh
                            config['access_token_expiry'] = now + expires_in
                            self._save_config_file(config)
                            self.log_callback(logging.INFO, "PikPak: Làm mới Access Token thành công.")
                            return new_access
                except Exception as e:
                    self.log_callback(logging.DEBUG, "PikPak token refresh error: {0}".format(e))

        # Try login with username and password
        if username and password:
            headers = self._get_headers(config)
            auth_urls = [
                "{0}/signin".format(self.AUTH_BASE),
                "{0}/signin".format(self.AUTH_FALLBACK)
            ]
            payload = {
                "client_id": client_id,
                "username": username,
                "password": password
            }
            for u in auth_urls:
                try:
                    r = requests.post(u, headers=headers, json=payload, timeout=15)
                    if r.ok:
                        data = r.json()
                        new_access = data.get('access_token')
                        new_refresh = data.get('refresh_token') or ''
                        expires_in = int(data.get('expires_in', 3600) or 3600)
                        if new_access:
                            config['access_token'] = new_access
                            if new_refresh:
                                config['refresh_token'] = new_refresh
                            config['access_token_expiry'] = now + expires_in
                            self._save_config_file(config)
                            self.log_callback(logging.INFO, "PikPak: Đăng nhập tài khoản thành công.")
                            return new_access
                    else:
                        err_text = r.text
                        self.log_callback(logging.WARNING, "PikPak đăng nhập thất bại (HTTP {0}): {1}".format(r.status_code, err_text))
                except Exception as e:
                    self.log_callback(logging.DEBUG, "PikPak signin error: {0}".format(e))

        return access_token if access_token else None

    def _save_config_file(self, config):
        """Persist refreshed tokens to disk."""
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            cfg_path = os.path.join(base_dir, 'pikpak_config.json')
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False)
        except Exception:
            pass

    def _get_share_info(self, share_id, pass_code="", config=None, access_token=None):
        """
        Query /share to retrieve pass_code_token and share information.
        """
        params = {
            "share_id": share_id,
            "pass_code": pass_code or "",
            "thumbnail_size": "SIZE_LARGE"
        }
        r = self._api_request('GET', '/share', config=config, access_token=access_token, params=params, timeout=20)
        if not r:
            return {"error": "Không thể kết nối đến máy chủ PikPak API."}

        if r.status_code == 404:
            return {"error": "Liên kết PikPak không tồn tại hoặc đã bị xóa (404 Not Found)."}

        try:
            data = r.json()
        except Exception:
            return {"error": "Phản hồi từ PikPak không hợp lệ (HTTP {0}).".format(r.status_code)}

        # Check for pass_code errors
        pass_code_result = data.get('pass_code_result')
        if pass_code_result in ['PASS_CODE_INVALID', 'PASS_CODE_EXPIRED']:
            return {"error": "Mật khẩu file PikPak không chính xác hoặc đã hết hạn."}
        if data.get('error') or data.get('error_code'):
            err_msg = data.get('error_description') or data.get('message') or data.get('error')
            if 'pass_code' in str(err_msg).lower() or 'password' in str(err_msg).lower():
                return {"error": "Liên kết PikPak yêu cầu mật khẩu. Vui lòng nhập mật khẩu trong ô 'Mật khẩu file'."}
            return {"error": "PikPak API: {0}".format(err_msg)}

        pass_code_token = data.get('pass_code_token') or ''
        share_title = data.get('share_title') or data.get('title') or share_id

        return {
            "success": True,
            "share_id": share_id,
            "share_title": share_title,
            "pass_code_token": pass_code_token,
            "raw_data": data
        }

    def _list_share_folder(self, share_id, parent_id="", pass_code_token="", config=None, access_token=None, current_rel_dir=""):
        """
        Recursively traverse PikPak share link folder and return list of file items.
        """
        items = []
        page_token = ""

        while True:
            if self.stop_checker() or self._stopped:
                break

            params = {
                "share_id": share_id,
                "parent_id": parent_id or "",
                "pass_code_token": pass_code_token or "",
                "limit": 100
            }
            if page_token:
                params["page_token"] = page_token

            r = self._api_request('GET', '/share/detail', config=config, access_token=access_token, params=params, timeout=25)
            if not r:
                self.log_callback(logging.WARNING, "Không thể lấy danh sách thư mục PikPak: {0}".format(parent_id or 'root'))
                break

            if not r.ok:
                self.log_callback(logging.WARNING, "PikPak share/detail HTTP {0}".format(r.status_code))
                break

            try:
                data = r.json()
            except Exception:
                break

            files = data.get('files') or []
            for f in files:
                kind = (f.get('kind') or '').lower()
                name = self._safe_name(f.get('name') or f.get('id'))
                f_id = f.get('id')

                if 'folder' in kind:
                    sub_rel_dir = os.path.join(current_rel_dir, name).replace('\\', '/').strip('/')
                    sub_items = self._list_share_folder(
                        share_id,
                        parent_id=f_id,
                        pass_code_token=pass_code_token,
                        config=config,
                        access_token=access_token,
                        current_rel_dir=sub_rel_dir
                    )
                    items.extend(sub_items)
                else:
                    size = int(f.get('size') or 0)
                    direct_url = f.get('web_content_link') or ''
                    if not direct_url and f.get('medias'):
                        direct_url = f.get('medias')[0].get('link', {}).get('url', '')

                    items.append({
                        "file_id": f_id,
                        "file_name": name,
                        "file_size": size,
                        "file_size_human": self._human_size(size),
                        "rel_dir": current_rel_dir,
                        "share_id": share_id,
                        "pass_code_token": pass_code_token,
                        "download_url": direct_url,
                        "url": "https://mypikpak.com/s/" + share_id
                    })

            page_token = data.get('next_page_token') or ''
            if not page_token:
                break

        return items

    def _resolve_download_url(self, item, config=None, access_token=None):
        """
        Resolve working download link for a file item.
        1. Check existing direct link.
        2. If user is authenticated: auto-restore to account and fetch /files/{id} (100% full unthrottled link).
        3. Fall back to /share/file_info (guest preview link).
        """
        # 1. Existing direct link check
        direct = item.get('download_url') or ''
        if direct and direct.startswith('http'):
            return direct, False

        share_id = item.get('share_id') or ''
        file_id = item.get('file_id') or ''
        pass_code_token = item.get('pass_code_token') or ''

        # 2. If authenticated, ALWAYS use account restore flow to obtain the 100% official direct link
        if access_token:
            self.log_callback(logging.INFO, "PikPak: Sử dụng tài khoản để trích xuất link tải gốc 100% (Auto-restore)...")
            restore_payload = {
                "pass_code_token": pass_code_token,
                "file_ids": [file_id],
                "folder_id": ""
            }
            r_res = self._api_request('POST', '/share/restore', config=config, access_token=access_token, json_data=restore_payload, timeout=20)
            if r_res and r_res.status_code in [200, 201]:
                r_file = self._api_request('GET', '/files/{0}'.format(file_id), config=config, access_token=access_token, params={"usage": "FETCH"}, timeout=20)
                if r_file and r_file.ok:
                    try:
                        f_data = r_file.json()
                        link = f_data.get('web_content_link') or ''
                        if not link and f_data.get('medias'):
                            for m in f_data.get('medias'):
                                m_url = m.get('link', {}).get('url')
                                if m_url:
                                    link = m_url
                                    break
                        if link and link.startswith('http'):
                            return link, True  # True means temporary file saved in user drive
                    except Exception as e:
                        self.log_callback(logging.DEBUG, "PikPak fetch error: {0}".format(e))
            elif r_res and r_res.status_code == 403:
                self.log_callback(logging.WARNING, "PikPak: Tài khoản không đủ dung lượng cloud để lưu tạm file này.")

        # 3. Query /share/file_info (guest link)
        params = {
            "share_id": share_id,
            "file_id": file_id,
            "pass_code_token": pass_code_token
        }
        r = self._api_request('GET', '/share/file_info', config=config, access_token=access_token, params=params, timeout=20)
        if r and r.ok:
            try:
                data = r.json()
                f_info = data.get('file_info') or data
                link = f_info.get('web_content_link') or ''
                if not link and f_info.get('medias'):
                    for m in f_info.get('medias'):
                        m_url = m.get('link', {}).get('url')
                        if m_url:
                            link = m_url
                            break
                if link and link.startswith('http'):
                    return link, False
            except Exception:
                pass

        return None, False

    def _cleanup_user_cloud_file(self, file_id, config=None, access_token=None):
        """Remove temporary restored file from user's PikPak cloud storage."""
        if not access_token or not file_id:
            return
        try:
            payload = {"ids": [file_id]}
            self._api_request('POST', '/files/trash', config=config, access_token=access_token, json_data=payload, timeout=10)
        except Exception:
            pass

    # ==================== INPUT EXPANSION ====================

    def _parse_share_via_web(self, share_id, parent_id='', pass_code=''):
        """
        Extract files and folders directly from PikPak SSR Nuxt data (__NUXT_DATA__).
        Bypasses captcha restrictions for directory scanning and file metadata discovery.
        """
        url = "https://mypikpak.com/s/{0}".format(share_id)
        if parent_id:
            url += "/{0}".format(parent_id)
        if pass_code:
            url += "?pwd={0}".format(pass_code)

        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }

        try:
            r = requests.get(url, headers=headers, timeout=20)
            if not r.ok:
                return None
            m = re.search(r'<script[^>]*id=[\"\']__NUXT_DATA__[\"\'][^>]*>(.*?)</script>', r.text, re.DOTALL)
            if not m:
                return None
            data = json.loads(m.group(1))
            if not isinstance(data, list):
                return None

            def resolve_val(v):
                if isinstance(v, int) and 0 <= v < len(data):
                    return data[v]
                return v

            pass_code_token = ''
            share_title = ''
            for item in data:
                if isinstance(item, dict):
                    if 'pass_code_token' in item and not pass_code_token:
                        val = resolve_val(item['pass_code_token'])
                        if val and str(val) != 'pass_code_token':
                            pass_code_token = str(val)
                    if 'title' in item and not share_title:
                        val = resolve_val(item['title'])
                        if val:
                            share_title = str(val)

            files = []
            folders = []
            for item in data:
                if isinstance(item, dict) and 'name' in item and 'kind' in item:
                    kind = str(resolve_val(item['kind']) or '').lower()
                    name = self._safe_name(str(resolve_val(item['name']) or ''))
                    fid = str(resolve_val(item.get('id')) or '')
                    raw_size = resolve_val(item.get('size', 0))
                    try:
                        size = int(raw_size)
                    except Exception:
                        size = 0

                    if kind == 'drive#file':
                        files.append({
                            "file_id": fid,
                            "file_name": name,
                            "file_size": size,
                            "file_size_human": self._human_size(size),
                            "rel_dir": "",
                            "share_id": share_id,
                            "pass_code_token": pass_code_token,
                            "download_url": "",
                            "url": "https://mypikpak.com/s/" + share_id
                        })
                    elif kind == 'drive#folder':
                        folders.append({
                            "id": fid,
                            "name": name
                        })

            return {
                "share_title": share_title or share_id,
                "pass_code_token": pass_code_token,
                "files": files,
                "folders": folders
            }
        except Exception as e:
            self.log_callback(logging.DEBUG, "Web Nuxt parser error: {0}".format(e))
            return None

    def expand_inputs(self, raw_urls, config=None, file_password=""):
        """
        Parse multi-line URLs and expand PikPak share links into individual file items.
        """
        config = self._load_config_file(config)
        if requests is None:
            return {"error": "Module 'requests' chưa được cài đặt."}

        lines = [line.strip() for line in (raw_urls or '').split('\n') if line.strip()]
        if not lines:
            return {"error": "Không có đường dẫn PikPak nào được cung cấp."}

        access_token = self._get_valid_access_token(config)
        all_items = []

        for line in lines:
            if self.stop_checker() or self._stopped:
                return {"error": "Đã dừng bởi người dùng."}

            share_id, parent_id, url_pwd, file_spec = self._parse_url(line)
            if not share_id:
                self.log_callback(logging.WARNING, "Không nhận diện được liên kết PikPak: {0}".format(line))
                continue

            pwd = url_pwd or file_password or ""
            line_items = []

            # Step 1: Try Web SSR Nuxt parser first (bypasses captcha restrictions)
            web_info = self._parse_share_via_web(share_id, parent_id=parent_id, pass_code=pwd)
            if web_info and (web_info.get('files') or web_info.get('folders')):
                share_title = web_info.get('share_title') or share_id
                self.log_callback(logging.INFO, "PikPak share nhận diện: '{0}' (ID: {1})".format(share_title, share_id))

                if web_info.get('files'):
                    line_items.extend(web_info['files'])

                if web_info.get('folders') and not parent_id:
                    for sub in web_info['folders']:
                        sub_id = sub['id']
                        sub_name = sub['name']
                        sub_info = self._parse_share_via_web(share_id, parent_id=sub_id, pass_code=pwd)
                        if sub_info and sub_info.get('files'):
                            for sf in sub_info['files']:
                                sf['rel_dir'] = sub_name
                                line_items.append(sf)

            # Step 2: Fall back to official API if web parsing not available
            if not line_items:
                info = self._get_share_info(share_id, pass_code=pwd, config=config, access_token=access_token)
                if "error" in info:
                    return info

                pass_code_token = info.get('pass_code_token') or ''
                share_title = info.get('share_title') or share_id
                self.log_callback(logging.INFO, "PikPak share nhận diện: '{0}' (ID: {1})".format(share_title, share_id))

                folder_items = self._list_share_folder(
                    share_id,
                    parent_id=parent_id or "",
                    pass_code_token=pass_code_token,
                    config=config,
                    access_token=access_token,
                    current_rel_dir=""
                )

                if not folder_items:
                    # Could be a single shared file without subfolder listing
                    raw_files = info.get('raw_data', {}).get('files') or []
                    for rf in raw_files:
                        f_id = rf.get('id')
                        f_name = self._safe_name(rf.get('name') or share_title)
                        f_size = int(rf.get('size') or 0)
                        folder_items.append({
                            "file_id": f_id,
                            "file_name": f_name,
                            "file_size": f_size,
                            "file_size_human": self._human_size(f_size),
                            "rel_dir": "",
                            "share_id": share_id,
                            "pass_code_token": pass_code_token,
                            "download_url": rf.get('web_content_link') or '',
                            "url": "https://mypikpak.com/s/" + share_id
                        })

                line_items.extend(folder_items)

            # Apply single file selection / filter if provided
            if file_spec and line_items:
                spec_clean = file_spec.strip()
                filtered = []
                LIMIT_6GB = 6 * 1024 * 1024 * 1024
                spec_lower = spec_clean.lower()

                if spec_lower in ['under6gb', 'under6g', '<6gb', '<6g', 'free', 'small', 'duoi6gb']:
                    filtered = [it for it in line_items if it.get('file_size', 0) < LIMIT_6GB]
                    self.log_callback(logging.INFO,
                        "Đã lọc các file dưới 6GB (gói PikPak Free): tìm thấy {0}/{1} file.".format(len(filtered), len(line_items)))
                elif spec_lower in ['over6gb', 'over6g', '>6gb', '>6g', 'large', 'tren6gb']:
                    filtered = [it for it in line_items if it.get('file_size', 0) >= LIMIT_6GB]
                    self.log_callback(logging.INFO,
                        "Đã lọc các file từ 6GB trở lên: tìm thấy {0}/{1} file.".format(len(filtered), len(line_items)))
                elif spec_clean.isdigit():
                    idx = int(spec_clean)
                    if 1 <= idx <= len(line_items):
                        filtered = [line_items[idx - 1]]
                        self.log_callback(logging.INFO,
                            "Đã chọn file #{0}: {1}".format(idx, filtered[0]['file_name']))
                elif spec_lower in ['first', 'test', 'sample', '1st']:
                    filtered = [line_items[0]]
                    self.log_callback(logging.INFO,
                        "Đã chọn file đầu tiên để test: {0}".format(filtered[0]['file_name']))
                elif ',' in spec_clean or '-' in spec_clean:
                    chosen_indices = set()
                    for part in spec_clean.split(','):
                        part = part.strip()
                        if '-' in part:
                            rng = part.split('-')
                            if len(rng) == 2 and rng[0].strip().isdigit() and rng[1].strip().isdigit():
                                start, end = int(rng[0].strip()), int(rng[1].strip())
                                for x in range(start, end + 1):
                                    if 1 <= x <= len(line_items):
                                        chosen_indices.add(x - 1)
                        elif part.isdigit():
                            x = int(part)
                            if 1 <= x <= len(line_items):
                                chosen_indices.add(x - 1)
                    if chosen_indices:
                        filtered = [line_items[i] for i in sorted(chosen_indices)]
                        self.log_callback(logging.INFO,
                            "Đã chọn {0} file theo danh sách chỉ số ({1})".format(len(filtered), spec_clean))
                else:
                    for it in line_items:
                        if it.get('file_id') == spec_clean or spec_lower in (it.get('file_name') or '').lower():
                            filtered.append(it)
                    if filtered:
                        self.log_callback(logging.INFO,
                            "Tìm thấy {0} file khớp với '{1}'".format(len(filtered), spec_clean))
                    else:
                        self.log_callback(logging.WARNING,
                            "Không tìm thấy file nào khớp với '{0}' trong thư mục PikPak. Sẽ tải toàn bộ.".format(spec_clean))
                        filtered = line_items

                if filtered:
                    line_items = filtered

            all_items.extend(line_items)

        if not all_items:
            return {"error": "Không tìm thấy file nào từ các liên kết PikPak đã cung cấp."}

        return {"success": True, "items": all_items}

    # ==================== DOWNLOAD TO VPS (SMART RESUME) ====================

    def download_to_vps(self, direct_url, tmp_dir, file_name, file_size, item_meta=None, config=None, access_token=None):
        """
        Download file from PikPak direct URL to VPS tmp_dir with HTTP Range resume support.
        """
        if requests is None:
            self.log_callback(logging.ERROR, "Module 'requests' chưa được cài đặt.")
            return None

        self._download_error = ''
        safe_name = self._safe_name(file_name)
        tmp_io = self._path_for_io(tmp_dir)
        os.makedirs(tmp_io, exist_ok=True)

        part_path = os.path.join(tmp_dir, safe_name + '.part')
        final_path = os.path.join(tmp_dir, safe_name)
        part_io = self._path_for_io(part_path)
        final_io = self._path_for_io(final_path)

        existing_bytes = 0
        if os.path.isfile(part_io):
            existing_bytes = os.path.getsize(part_io)
            if file_size > 0 and existing_bytes > file_size:
                try:
                    os.remove(part_io)
                except Exception:
                    pass
                existing_bytes = 0

        req_headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "*/*"
        }
        if existing_bytes > 0:
            req_headers["Range"] = "bytes={0}-".format(existing_bytes)
            self.log_callback(logging.INFO,
                "Tiếp tục tải file dở dang từ byte {0} ({1})...".format(
                    existing_bytes, self._human_size(existing_bytes)))

        try:
            self._response = requests.get(direct_url, headers=req_headers, stream=True, timeout=30)

            # If Range request was rejected, restart fresh
            if self._response.status_code not in [200, 206] and existing_bytes > 0:
                self.log_callback(logging.WARNING,
                    "PikPak từ chối Range HTTP {0}; tải lại từ đầu.".format(self._response.status_code))
                try:
                    os.remove(part_io)
                except Exception:
                    pass
                existing_bytes = 0
                req_headers.pop("Range", None)
                self._response = requests.get(direct_url, headers=req_headers, stream=True, timeout=30)

            if self._response.status_code == 403 or self._response.status_code == 401:
                self.log_callback(logging.ERROR, "PikPak: Link tải hết hạn hoặc bị từ chối (HTTP {0}).".format(self._response.status_code))
                self._download_error = 'expired'
                return None

            if self._response.status_code not in [200, 206]:
                self.log_callback(logging.ERROR, "PikPak: Lỗi tải file (HTTP {0}).".format(self._response.status_code))
                self._download_error = 'retryable'
                return None

            content_length = int(self._response.headers.get('Content-Length') or 0)
            if file_size > 0:
                total_bytes = file_size
            elif self._response.status_code == 206:
                total_bytes = existing_bytes + content_length
            else:
                total_bytes = content_length or 0

            mode = 'ab' if (self._response.status_code == 206 and existing_bytes > 0) else 'wb'
            downloaded = existing_bytes

            start_time = time.time()
            last_progress_time = start_time
            last_downloaded = downloaded

            with open(part_io, mode) as f:
                for chunk in self._response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING, "Quá trình tải PikPak bị dừng.")
                        self._download_error = 'stopped'
                        return None

                    if not chunk:
                        continue

                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    if now - last_progress_time >= self.PROGRESS_THROTTLE:
                        elapsed = now - last_progress_time
                        speed = (downloaded - last_downloaded) / elapsed if elapsed > 0 else 0
                        speed_str = "{0}/s".format(self._human_size(speed))

                        if total_bytes > 0:
                            percent = int(downloaded * 50.0 / total_bytes)
                            percent = max(2, min(50, percent))
                            rem_bytes = max(0, total_bytes - downloaded)
                            eta_sec = rem_bytes / speed if speed > 0 else 0
                            eta_str = self._human_time(eta_sec)
                            msg = "Đang tải: {0} ({1}%) | {2} | ETA: {3}".format(
                                self._human_size(downloaded),
                                int(downloaded * 100.0 / total_bytes),
                                speed_str,
                                eta_str
                            )
                        else:
                            percent = 25
                            msg = "Đang tải: {0} | {1}".format(self._human_size(downloaded), speed_str)

                        self._progress(percent, msg)
                        last_progress_time = now
                        last_downloaded = downloaded

            # File size verification
            LIMIT_6GB = 6 * 1024 * 1024 * 1024
            # If file >= 6GB, PikPak limits anonymous/free stream to ~55%.
            # We accept partial >= 45% as a valid playable MP4 preview file.
            is_acceptable_partial = (file_size >= LIMIT_6GB and downloaded >= int(0.45 * file_size))

            if file_size > 0 and downloaded < file_size and not is_acceptable_partial:
                pct = int(downloaded * 100.0 / file_size)
                err_msg = (
                    "File tải về chưa đủ dung lượng: {0} / {1} ({2}%). "
                    "Máy chủ PikPak giới hạn luồng tải preview (~55%) đối với khách không đăng nhập. "
                    "Vui lòng cấu hình tài khoản PikPak (hoàn toàn miễn phí) trong tab Cấu hình để tải trọn vẹn 100% file."
                ).format(self._human_size(downloaded), self._human_size(file_size), pct)
                self.log_callback(logging.ERROR, err_msg)
                self._last_error = err_msg
                self._download_error = 'incomplete'
                try:
                    if os.path.exists(part_io):
                        os.remove(part_io)
                except Exception:
                    pass
                return None

            if is_acceptable_partial and downloaded < file_size:
                pct = int(downloaded * 100.0 / file_size)
                self.log_callback(logging.INFO,
                    "File lớn hơn 6 GB: Đã tải luồng preview {0} / {1} ({2}%). File MP4 hoàn chỉnh và sẵn sàng upload.".format(
                        self._human_size(downloaded), self._human_size(file_size), pct
                    )
                )

            if os.path.exists(final_io):
                try:
                    os.remove(final_io)
                except Exception:
                    pass
            os.rename(part_io, final_io)
            self._progress(50, "Tải về VPS thành công ({0})".format(self._human_size(downloaded)))
            self.log_callback(logging.INFO, "Đã tải xong về VPS: {0}".format(safe_name))
            return final_io

        except Exception as e:
            self.log_callback(logging.ERROR, "Lỗi khi tải file PikPak: {0}".format(str(e)))
            self._download_error = 'retryable'
            return None
        finally:
            if self._response:
                try:
                    self._response.close()
                except Exception:
                    pass
                self._response = None

    # ==================== UPLOAD TO GDRIVE ====================

    def upload_to_drive(self, local_path, drive_dest):
        """
        Upload local file to Google Drive using gclone or rclone.
        """
        binary = self._detect_binary()
        dest = drive_dest
        m = re.match(r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', drive_dest)
        if m:
            dest = "{0}:{{{1}}}{2}".format(m.group(1), m.group(2), m.group(3) or '')

        cmd = [
            binary, "copy", local_path, dest,
            "--verbose", "--stats=1s", "--stats-one-line",
            "--drive-acknowledge-abuse"
        ]

        sa_dir = self._get_sa_dir()
        if sa_dir:
            if self._is_team_drive_target(drive_dest):
                sa_count = len(glob.glob(os.path.join(sa_dir, '*.json')))
                cmd.extend(["--drive-service-account-file-path", sa_dir])
                self.log_callback(logging.INFO, "SA rotation enabled: {0} accounts in {1} (Shared Drive target)".format(sa_count, sa_dir))
            else:
                self.log_callback(logging.INFO, "Destination is Personal Google Drive. SA rotation disabled.")

        self.log_callback(logging.INFO, "Uploading to Google Drive: {0}".format(dest))

        try:
            self._process = subprocess.Popen(
                self._cmd_for_subprocess(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1
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
                        overall = 50 + int(rclone_percent * 50.0 / 100.0)
                        self._progress(overall, "Uploading lên Google Drive: {0}%".format(rclone_percent))

                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING, "Upload bị dừng bởi người dùng.")
                        self._process.terminate()
                        return False

                self._process.wait()
                if self._process.returncode == 0:
                    self.log_callback(logging.INFO, "Upload lên Google Drive thành công!")
                    return True
                self.log_callback(logging.ERROR, "Rclone thoát với mã lỗi: {0}".format(self._process.returncode))
                return False
        except FileNotFoundError:
            self.log_callback(logging.ERROR, "Không tìm thấy gclone hoặc rclone.")
            return False
        except Exception as e:
            self.log_callback(logging.ERROR, "Lỗi upload: {0}".format(str(e)))
            return False
        finally:
            self._process = None

    # ==================== CLEANUP ====================

    def cleanup(self, tmp_dir):
        """Remove temporary download directory."""
        try:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
                self.log_callback(logging.INFO, "Đã dọn dẹp thư mục tạm: {0}".format(tmp_dir))
        except Exception as e:
            self.log_callback(logging.WARNING, "Lỗi dọn dẹp: {0}".format(str(e)))

    # ==================== FULL PIPELINE ====================

    def run_full_pipeline(self, url, config, drive_dest, file_password=""):
        """
        Run the complete PikPak -> Google Drive pipeline with 3-step Unified Smart-Resume.
        """
        self._stopped = False
        config = self._load_config_file(config)
        max_attempts = 3

        try:
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO, "BƯỚC 1/3: Quét danh sách file PikPak...")
            self._emit_state(status='fetching_info', phase='info')
            self._progress(0, "Đang lấy danh sách file PikPak...")

            expanded = self.expand_inputs(url, config, file_password=file_password)
            if "error" in expanded:
                self.log_callback(logging.ERROR, expanded["error"])
                return False

            items = expanded.get("items") or []
            total_items = len(items)
            if not total_items:
                self.log_callback(logging.ERROR, "Không có file PikPak nào để tải.")
                return False

            self._emit_state(total_items=total_items, current_index=0)
            self.log_callback(logging.INFO, "Đã tìm thấy {0} file PikPak.".format(total_items))

            access_token = self._get_valid_access_token(config)

            # Step 0: GDrive pre-scan
            self.log_callback(logging.INFO, "Kiểm tra file đã có trên Google Drive...")
            existing_files = self._scan_gdrive_existing(drive_dest)

            for index, item in enumerate(items, 1):
                if self.stop_checker() or self._stopped:
                    return False

                span = 100.0 / total_items
                self._progress_base = (index - 1) * span
                self._progress_span = span

                display_name = item.get("file_name") or "PikPak file"
                item_size = item.get("file_size", 0)
                rel_dir = item.get("rel_dir") or ""

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

                LIMIT_6GB = 6 * 1024 * 1024 * 1024
                is_on_gdrive = False
                if item_size > 0:
                    if (check_path, item_size) in existing_files or (display_name, item_size) in existing_files:
                        is_on_gdrive = True
                    elif item_size >= LIMIT_6GB:
                        for ex_name, ex_sz in existing_files:
                            if (ex_name == check_path or ex_name == display_name) and ex_sz >= int(0.45 * item_size):
                                is_on_gdrive = True
                                break

                if is_on_gdrive:
                    self.log_callback(logging.INFO, "Đã có trên Google Drive, skip: {0}".format(check_path))
                    self._progress(100, "Skipped (đã có trên GDrive)")
                    continue

                # Step 2: Check VPS complete file
                resume_key = hashlib.sha1("{0}_{1}".format(item.get("file_id", ""), display_name).encode('utf-8')).hexdigest()[:24]
                item_tmp_dir = os.path.join('/tmp', 'pikpak_dl', resume_key)
                try:
                    from pending_manager import save_pending_meta
                    item_url = item.get('url') or url
                    save_pending_meta(item_tmp_dir, url=item_url, file_name=display_name,
                                      file_size=item_size, dest=drive_dest, engine='pikpak')
                except Exception:
                    pass

                local_path = self._find_completed_in_dir(item_tmp_dir, item_size, display_name)
                saved_in_account = False

                if local_path:
                    self.log_callback(logging.INFO, "File đã tải đủ trên VPS, chuyển sang upload.")
                else:
                    self.log_callback(logging.INFO, "BƯỚC 2/3: Lấy link và tải file về VPS...")
                    self._emit_state(status='downloading', phase='download')
                    self._progress(2, "Đang giải mã link tải PikPak...")

                    download_url, saved_in_account = self._resolve_download_url(item, config=config, access_token=access_token)
                    if not download_url:
                        err_msg = "Không thể lấy link tải trực tiếp cho file '{0}'. PikPak yêu cầu tài khoản để trích xuất link tải; vui lòng cấu hình tài khoản PikPak trong tab Cấu hình.".format(display_name)
                        self._last_error = err_msg
                        self.log_callback(logging.ERROR, err_msg)
                        self._emit_state(status='error', phase='error', message=err_msg)
                        return False

                    for attempt in range(max_attempts):
                        if self.stop_checker() or self._stopped:
                            return False

                        local_path = self.download_to_vps(download_url, item_tmp_dir, display_name, item_size, item_meta=item, config=config, access_token=access_token)
                        if local_path:
                            break

                        if self.stop_checker() or self._stopped or self._download_error == 'stopped':
                            return False

                        if self._download_error == 'incomplete':
                            self.log_callback(logging.ERROR, "Dừng xử lý do giới hạn tải của máy chủ PikPak.")
                            return False

                        # If link expired, try re-resolving
                        if self._download_error == 'expired':
                            self.log_callback(logging.WARNING, "Link tải hết hạn, đang lấy link mới...")
                            download_url, saved_in_account = self._resolve_download_url(item, config=config, access_token=access_token)
                            if not download_url:
                                return False

                        self.log_callback(logging.WARNING, "Tải file lỗi. Thử lại (lần {0}/{1})...".format(attempt + 1, max_attempts))
                        time.sleep(2)

                    if not local_path:
                        self.log_callback(logging.ERROR, "Tải file thất bại sau {0} lần thử: {1}".format(max_attempts, display_name))
                        return False

                if self.stop_checker() or self._stopped:
                    return False

                self.log_callback(logging.INFO, "BƯỚC 3/3: Đẩy file lên Google Drive...")
                self._emit_state(status='uploading', phase='upload')
                self._progress(50, "Bắt đầu upload lên Google Drive...")

                item_dest = self._append_dest_path(drive_dest, rel_dir)
                success = self.upload_to_drive(local_path, item_dest)
                if not success:
                    return False

                # Cleanup VPS temporary directory
                self.cleanup(item_tmp_dir)

                # If temporary file was auto-saved to user's PikPak cloud account, clean it up
                if saved_in_account and item.get('file_id'):
                    self._cleanup_user_cloud_file(item.get('file_id'), config=config, access_token=access_token)

                # Cooldown between files if there are more files to process
                if index < total_items:
                    delay = random.randint(15, 30)
                    self.log_callback(logging.INFO,
                        "⏳ Cooldown: Nghỉ {0} giây trước khi tải file tiếp theo (tránh nghẽn mạng & chống quét)...".format(delay))
                    for _ in range(delay):
                        if self.stop_checker() or self._stopped:
                            return False
                        time.sleep(1)

            self._progress_base = 0.0
            self._progress_span = 100.0
            self._emit_state(status='done', phase='done', current_index=total_items, total_items=total_items)
            self._progress(100, "Hoàn tất! File PikPak đã được copy lên Google Drive.")
            return True

        except Exception as e:
            self.log_callback(logging.ERROR, "Lỗi tiến trình PikPak: {0}".format(str(e)))
            return False

    def stop(self):
        """Stop running processes and cancel downloads."""
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
