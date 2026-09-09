"""
TeraboxEngine - Download files and folders from Terabox and upload to Google Drive.
Supports single files, multi-line URLs, and recursive folder downloads preserving directory hierarchy.
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


class TeraboxEngine:
    """Engine to handle Terabox download -> Google Drive upload pipeline."""

    TERABOX_API_BASE = "https://www.terabox.app"
    CHUNK_SIZE = 1024 * 1024  # 1MB chunk size
    PROGRESS_THROTTLE = 3  # seconds between progress updates

    def __init__(self, progress_callback, log_callback, stop_checker, state_callback=None):
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stop_checker = stop_checker
        self.state_callback = state_callback
        self._process = None
        self._response = None  # for cancelling download stream
        self._stopped = False
        self._download_error = ''
        self._progress_base = 0.0
        self._progress_span = 100.0

    def _emit_state(self, **kwargs):
        """Send structured state back to Flask without coupling this engine to app.py."""
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
        name = re.sub(r'[\\/*?:"<>|]', '_', name)
        return name or 'terabox_download'

    def _safe_remote_path(self, path):
        """Clean parts of a relative remote path."""
        parts = []
        for part in (path or '').split('/'):
            clean = self._safe_name(part)
            if clean and clean != 'terabox_download':
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
    # ==================== TERABOX API HELPERS ====================

    def _parse_share_url(self, url):
        """Clean up and normalize Terabox url."""
        url = (url or '').strip()
        if not url:
            return ""
        if re.match(r'^[A-Za-z0-9_-]{6,}$', url):
            return "https://www.terabox.app/s/" + url
        if not url.startswith('http://') and not url.startswith('https://'):
            url = 'https://' + url
        return url

    def _build_cookie_header(self, cookie_value):
        """Build cookie header string from ndus value."""
        cookie_value = (cookie_value or '').strip()
        if 'ndus=' in cookie_value:
            return cookie_value
        return "ndus={0}; lang=en".format(cookie_value)

    def _find_between(self, s, start, end):
        start_index = s.find(start)
        if start_index == -1: return ""
        start_index += len(start)
        end_index = s.find(end, start_index)
        if end_index == -1: return ""
        return s[start_index:end_index]

    def _extract_first(self, text, patterns):
        """Return the first regex capture found in text."""
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1)
        return ""

    def _extract_share_field(self, text, names, numeric=False):
        """Extract Terabox fields from quoted JSON, JS object, or escaped script blobs."""
        value_pattern = r'["\']?(\d+)["\']?' if numeric else r'["\']([^"\']+)["\']'
        patterns = []
        for name in names:
            patterns.extend([
                r'["\']{0}["\']\s*:\s*{1}'.format(re.escape(name), value_pattern),
                r'{0}\s*[:=]\s*{1}'.format(re.escape(name), value_pattern),
                r'%22{0}%22%3A%22([^%]+)%22'.format(re.escape(name)),
            ])
        return self._extract_first(text, patterns)

    def _pick_first(self, data, keys):
        for key in keys:
            val = data.get(key)
            if val is not None and val != "":
                return str(val)
        return ""

    def _validate_content_range(self, content_range, start, total_size):
        if not content_range:
            return False
        m = re.match(r'bytes\s+(\d+)-(\d+)/(\d+|\*)', content_range.strip(), re.I)
        if not m:
            return False
        if int(m.group(1)) != start:
            return False
        if total_size > 0 and m.group(3) != '*' and int(m.group(3)) != total_size:
            return False
        return True

    @staticmethod
    def _compute_sign(j, r):
        """RC4 cipher to compute Terabox 'sign' parameter.
        j = key (e.g. bdstoken), r = data (e.g. jsToken)
        """
        import base64
        a = []
        p = list(range(256))
        o_chars = []
        v = len(j)
        for q in range(256):
            a.append(ord(j[q % v]))
        u = 0
        for q in range(256):
            u = (u + p[q] + a[q]) % 256
            p[q], p[u] = p[u], p[q]
        i = u = 0
        for q in range(len(r)):
            i = (i + 1) % 256
            u = (u + p[i]) % 256
            p[i], p[u] = p[u], p[i]
            k = p[(p[i] + p[u]) % 256]
            o_chars.append(chr(ord(r[q]) ^ k))
        return base64.b64encode(''.join(o_chars).encode('latin-1')).decode()

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

    # ==================== RECURSIVE FOLDER & LISTING ====================

    def _list_folder_recursive(self, session, api_base, list_url, js_token, surl, current_dir, rel_path=""):
        """Recursively list all files and subfolders in a Terabox directory."""
        if self.stop_checker() or self._stopped:
            return []

        all_files = []
        page = 1
        page_size = 100

        while True:
            if self.stop_checker() or self._stopped:
                break

            folder_params = {
                "app_id": "250528",
                "web": "1",
                "channel": "dubox",
                "clienttype": "0",
                "jsToken": js_token,
                "shorturl": surl,
                "dir": current_dir,
                "page": str(page),
                "num": str(page_size),
            }

            try:
                r_sub = session.get(list_url, params=folder_params, timeout=30)
                sub_data = r_sub.json()
            except Exception as e:
                self.log_callback(logging.WARNING, "Lỗi quét thư mục {0}: {1}".format(current_dir, str(e)))
                break

            sub_items = sub_data.get("list", [])
            if not sub_items:
                break

            for item in sub_items:
                is_dir = str(item.get("isdir", "0"))
                name = self._safe_name(item.get("server_filename", "unknown"))
                item_path = item.get("path", "")
                item_rel = (rel_path.rstrip('/') + '/' + name).strip('/') if rel_path else name

                if is_dir == "1":
                    sub_files = self._list_folder_recursive(
                        session, api_base, list_url, js_token, surl, item_path, item_rel
                    )
                    all_files.extend(sub_files)
                else:
                    item_size = int(item.get("size", 0))
                    all_files.append({
                        "url": "https://www.terabox.app/s/" + surl,
                        "surl": surl,
                        "file_name": name,
                        "file_size": item_size,
                        "file_size_human": self._human_size(item_size),
                        "rel_dir": rel_path,
                        "path": item_path,
                        "fs_id": str(item.get("fs_id", "")),
                        "dlink": item.get("dlink", ""),
                    })

            if len(sub_items) < page_size:
                break
            page += 1

        return all_files

    def _expand_single_url(self, raw_url, cookie):
        """Expand a single Terabox URL to a list of file items."""
        if requests is None:
            return {"error": "Module 'requests' chưa được cài đặt."}

        full_url = self._parse_share_url(raw_url)
        if not full_url:
            return {"error": "Link Terabox không hợp lệ."}

        cookie_header = self._build_cookie_header(cookie)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "Cookie": cookie_header,
        }

        try:
            session = requests.Session()
            session.headers.update(headers)
            self.log_callback(logging.INFO, "Đang lấy thông tin xác thực từ trang...")

            # Extract surl first
            surl = ""
            parsed = urlparse(full_url)
            query = parse_qs(parsed.query)
            if "surl" in query:
                surl = query["surl"][0]
            else:
                m = re.search(r'/s/(?:1)?([A-Za-z0-9_-]+)', full_url)
                if m:
                    surl = m.group(1)

            candidates = [full_url]
            if surl:
                candidates.extend([
                    "https://www.terabox.app/s/1" + surl,
                    "https://www.terabox.com/sharing/link?surl=" + surl + "&clearCache=1",
                    "https://1024tera.com/s/1" + surl,
                    "https://dm.terabox.app/sharing/link?surl=" + surl + "&clearCache=1",
                ])

            js_token = ""
            bdstoken = ""
            sign = ""
            timestamp_val = ""
            shareid = ""
            uk = ""
            pcftoken = ""
            logid = ""
            api_base = "https://www.terabox.app"
            referer_url = full_url

            for cand_url in candidates:
                try:
                    r = session.get(cand_url, timeout=20)
                    if not r.ok:
                        continue
                    html = r.text
                    decoded_html = unquote(html)
                    combined_html = html + "\n" + decoded_html

                    cur_js = self._extract_first(combined_html, [
                        r'jsToken["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                        r'fn%28%22(.*?)%22%29',
                        r'"jsToken"\s*:\s*"([^"]+)"',
                        r'fn\("([^"]+)"\)',
                    ])

                    if cur_js:
                        js_token = cur_js
                        logid = self._find_between(html, 'dp-logid=', '&')

                        m_td = re.search(r'(?:var\s+)?templateData\s*=\s*(\{.*?\});', html)
                        if m_td:
                            try:
                                td = json.loads(m_td.group(1))
                                bdstoken = str(td.get('bdstoken', ''))
                                uk = str(td.get('uk', ''))
                            except Exception:
                                pass

                        if not bdstoken:
                            bdstoken = self._extract_share_field(combined_html, ['bdstoken'])
                        if not uk:
                            uk = self._extract_share_field(combined_html, ['uk', 'share_uk', 'shareUk'], numeric=True)
                        if not sign:
                            sign = self._extract_share_field(combined_html, ['sign'])
                        if not timestamp_val:
                            timestamp_val = self._extract_share_field(combined_html, ['timestamp', 'time'], numeric=True)
                        if not shareid:
                            shareid = self._extract_share_field(combined_html, ['shareid', 'share_id', 'shareId'], numeric=True)

                        m_pcf = re.search(r'pcftoken["\']?\s*[:=]\s*["\']([^"\']+)["\']', html)
                        if m_pcf:
                            pcftoken = m_pcf.group(1)

                        cand_parsed = urlparse(r.url)
                        api_base = "{0}://{1}".format(cand_parsed.scheme, cand_parsed.netloc)
                        referer_url = r.url
                        break
                except Exception:
                    pass

            if not surl:
                return {"error": "Không tìm thấy mã chia sẻ (surl) trong link."}

            if not js_token:
                return {"error": "Không lấy được jsToken. Cookie 'ndus' có thể đã hết hạn hoặc Terabox chặn IP."}

            self.log_callback(logging.INFO, "Đã lấy được jsToken. Đang lấy danh sách file...")

            list_url = "{0}/share/list".format(api_base)
            list_params = {
                "app_id": "250528",
                "web": "1",
                "channel": "dubox",
                "clienttype": "0",
                "jsToken": js_token,
                "page": "1",
                "num": "50",
                "by": "name",
                "order": "asc",
                "site_referer": referer_url,
                "shorturl": surl,
                "root": "1",
            }
            if logid:
                list_params["dp-logid"] = logid
            if pcftoken:
                list_params["pcftoken"] = pcftoken

            r2 = session.get(list_url, params=list_params, timeout=30)
            data2 = r2.json()

            if data2.get("errno") != 0:
                if api_base != "https://www.terabox.app":
                    r2 = session.get("https://www.terabox.app/share/list", params=list_params, timeout=30)
                    data2 = r2.json()
                    if data2.get("errno") == 0:
                        api_base = "https://www.terabox.app"
                        list_url = "{0}/share/list".format(api_base)

                if data2.get("errno") != 0:
                    errno = data2.get("errno")
                    if errno == -6:
                        return {"error": "Cookie 'ndus' hết hạn. Vui lòng cập nhật cookie mới."}
                    return {"error": "Terabox API list lỗi: {0} (errno: {1})".format(data2.get("errmsg", "Lỗi"), errno)}

            lst = data2.get("list", [])
            if not lst:
                return {"error": "Link này rỗng hoặc không có file nào."}

            if not shareid:
                shareid = self._pick_first(data2, ["share_id", "shareid", "shareId"])
            if not uk or uk == "0":
                api_uk = self._pick_first(data2, ["uk", "share_uk", "shareUk"])
                if api_uk and api_uk != "0":
                    uk = api_uk
            if not sign:
                sign = self._pick_first(data2, ["sign"])
            if not timestamp_val:
                timestamp_val = self._pick_first(data2, ["timestamp", "server_time"])
            if not sign and bdstoken and js_token:
                sign = self._compute_sign(bdstoken, js_token)

            if not timestamp_val:
                timestamp_val = str(int(time.time()))

            share_ctx = {
                "session": session,
                "api_base": api_base,
                "list_url": list_url,
                "js_token": js_token,
                "surl": surl,
                "shareid": shareid,
                "uk": uk,
                "sign": sign,
                "timestamp": timestamp_val,
                "logid": logid,
                "pcftoken": pcftoken,
            }

            expanded_files = []
            for root_item in lst:
                is_dir = str(root_item.get("isdir", "0"))
                name = self._safe_name(root_item.get("server_filename", "unknown"))
                root_path = root_item.get("path", "")
                root_size = int(root_item.get("size", 0))

                if is_dir == "1":
                    self.log_callback(logging.INFO, "Đang duyệt thư mục: {0}...".format(name))
                    sub_files = self._list_folder_recursive(
                        session, api_base, list_url, js_token, surl, root_path, name
                    )
                    for f in sub_files:
                        f["share_ctx"] = share_ctx
                    expanded_files.extend(sub_files)
                else:
                    expanded_files.append({
                        "url": full_url,
                        "surl": surl,
                        "file_name": name,
                        "file_size": root_size,
                        "file_size_human": self._human_size(root_size),
                        "rel_dir": "",
                        "path": root_path,
                        "fs_id": str(root_item.get("fs_id", "")),
                        "dlink": root_item.get("dlink", ""),
                        "share_ctx": share_ctx,
                    })

            return {"success": True, "items": expanded_files, "share_ctx": share_ctx}

        except Exception as e:
            return {"error": "Lỗi kết nối Terabox: {0}".format(str(e))}

    def expand_inputs(self, raw, cookie):
        """Parse raw multi-line or single URL inputs and expand all folders."""
        if isinstance(raw, list):
            raw_urls = [u.strip() for u in raw if u.strip()]
        else:
            raw_urls = [u.strip() for u in (raw or '').splitlines() if u.strip()]

        if not raw_urls:
            return {"error": "Không tìm thấy link Terabox hợp lệ trong danh sách."}

        all_items = []
        for url in raw_urls:
            if self.stop_checker() or self._stopped:
                break
            expanded = self._expand_single_url(url, cookie)
            if "error" in expanded:
                return expanded
            all_items.extend(expanded.get("items", []))

        if not all_items:
            return {"error": "Không tìm thấy file nào trong danh sách link Terabox."}

        return {
            "success": True,
            "items": all_items,
            "total_items": len(all_items),
        }

    def get_file_info(self, url, cookie):
        """Get file or folder metadata for UI check."""
        expanded = self.expand_inputs(url, cookie)
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
                "download_url": item.get("dlink", ""),
                "download_url_ready": bool(item.get("dlink")),
                "item_count": 1,
                "items": items,
            }
        else:
            total_size = sum(item.get("file_size", 0) for item in items)
            first_folder = items[0].get("rel_dir") or "Terabox Folder"
            return {
                "success": True,
                "file_name": "{0} ({1} files)".format(first_folder, total_items),
                "file_size": total_size,
                "file_size_human": self._human_size(total_size),
                "download_url_ready": True,
                "item_count": total_items,
                "items": items,
            }

    # ==================== DLINK RESOLUTION ====================

    def _get_fresh_dlink(self, item, cookie):
        """Get or refresh direct download link for an item."""
        if item.get("dlink"):
            return item["dlink"]

        share_ctx = item.get("share_ctx") or {}
        session = share_ctx.get("session")
        if not session:
            session = requests.Session()
            session.headers.update({
                "Cookie": self._build_cookie_header(cookie),
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            })

        api_base = share_ctx.get("api_base") or "https://www.terabox.app"
        js_token = share_ctx.get("js_token", "")
        surl = share_ctx.get("surl") or item.get("surl", "")
        item_path = item.get("path", "")

        # 1. Try /share/list for parent directory to get fresh dlink with expires=8h
        if item_path:
            parent_dir = os.path.dirname(item_path).replace('\\', '/')
            try:
                r_dir = session.get("{0}/share/list".format(api_base), params={
                    "app_id": "250528",
                    "web": "1",
                    "channel": "dubox",
                    "clienttype": "0",
                    "jsToken": js_token,
                    "shorturl": surl,
                    "dir": parent_dir,
                }, timeout=20)
                d_dir = r_dir.json()
                for sub in d_dir.get("list", []):
                    if str(sub.get("fs_id", "")) == str(item.get("fs_id", "")):
                        dlink = sub.get("dlink", "")
                        if dlink:
                            item["dlink"] = dlink
                            return dlink
            except Exception:
                pass

        # 2. Try /share/download with fid_list
        fs_id = item.get("fs_id")
        shareid = share_ctx.get("shareid")
        uk = share_ctx.get("uk")
        sign = share_ctx.get("sign")
        timestamp_val = share_ctx.get("timestamp")

        if fs_id and shareid and uk:
            dl_params = {
                "app_id": "250528",
                "web": "1",
                "channel": "dubox",
                "clienttype": "0",
                "jsToken": js_token,
                "sign": sign,
                "timestamp": timestamp_val,
                "shareid": shareid,
                "uk": uk,
                "primaryid": shareid,
                "fid_list": "[{0}]".format(fs_id),
            }
            try:
                r_dl = session.get("{0}/share/download".format(api_base), params=dl_params, timeout=20)
                data_dl = r_dl.json()
                if data_dl.get("errno") == 0:
                    dlink = data_dl.get("dlink", "")
                    if not dlink and data_dl.get("list"):
                        dlink = data_dl["list"][0].get("dlink", "")
                    if dlink:
                        item["dlink"] = dlink
                        return dlink
            except Exception:
                pass

        # 3. Try yt-dlp CLI fallback
        try:
            cmd = [
                'yt-dlp',
                '-g',
                '--no-warnings',
                '--add-header', 'Cookie: {0}'.format(self._build_cookie_header(cookie)),
                '--add-header', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
                item.get("url") or ("https://www.terabox.app/s/" + surl)
            ]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            out, err = process.communicate(timeout=30)
            if process.returncode == 0 and out.strip():
                urls = out.strip().split('\n')
                if urls:
                    dlink = urls[-1]
                    item["dlink"] = dlink
                    return dlink
        except Exception:
            pass

        return ""

    # ==================== DOWNLOAD ====================

    def download_to_vps(self, download_url, cookie, tmp_dir, file_name, file_size):
        """Download a file from Terabox to VPS temp directory with .part support."""
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

        cookie_header = self._build_cookie_header(cookie)
        headers = {
            "Cookie": cookie_header,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

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

            # Disk space check
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

            self._response = requests.get(download_url, headers=headers, stream=True, timeout=60)
            status_code = self._response.status_code

            if resume_from > 0:
                if status_code != 206:
                    self.log_callback(logging.WARNING,
                                      "Server không chấp nhận resume (HTTP {0}). Bắt đầu tải lại từ đầu.".format(status_code))
                    resume_from = 0
                    if "Range" in headers:
                        del headers["Range"]
                    self._response.close()
                    self._response = requests.get(download_url, headers=headers, stream=True, timeout=60)
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
                                dl_percent = min(int(downloaded * 50 / file_size), 50)  # 0-50%
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
            self.log_callback(logging.WARNING, "Kết nối tới Terabox bị timeout. Giữ file .part để resume.")
            self._download_error = 'retryable'
            return None
        except requests.exceptions.ConnectionError:
            self.log_callback(logging.WARNING, "Mất kết nối khi đang tải từ Terabox. Giữ file .part để resume.")
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

    def run_full_pipeline(self, url, cookie, drive_dest):
        """Run the complete Terabox -> Google Drive pipeline.
        Supports single files, folders, and multi-line URLs.
        """
        self._stopped = False
        max_attempts = 3

        try:
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO, "BƯỚC 1/3: Quét danh sách file & thư mục Terabox...")
            self._emit_state(status='fetching_info', phase='info')
            self._progress(0, "Đang lấy danh sách file Terabox...")

            expanded = self.expand_inputs(url, cookie)
            if "error" in expanded:
                self.log_callback(logging.ERROR, expanded["error"])
                return False

            items = expanded.get("items") or []
            total_items = len(items)
            if not total_items:
                self.log_callback(logging.ERROR, "Không có file Terabox nào để tải.")
                return False

            self._emit_state(total_items=total_items, current_index=0)
            self.log_callback(logging.INFO, "Đã tìm thấy {0} file trong link Terabox.".format(total_items))

            # Step 0: GDrive pre-scan
            self.log_callback(logging.INFO, "Kiểm tra file đã có trên Google Drive...")
            existing_files = self._scan_gdrive_existing(drive_dest)

            for index, item in enumerate(items, 1):
                if self.stop_checker() or self._stopped:
                    return False

                span = 100.0 / total_items
                self._progress_base = (index - 1) * span
                self._progress_span = span

                display_name = item.get("file_name") or "Terabox file"
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

                if item_size > 0 and ((check_path, item_size) in existing_files or (display_name, item_size) in existing_files):
                    self.log_callback(logging.INFO, "Đã có trên Google Drive, skip: {0}".format(check_path))
                    self._progress(100, "Skipped (đã có trên GDrive)")
                    continue

                # Step 2: Check VPS complete file
                resume_key = hashlib.sha1("{0}_{1}".format(item.get("surl", ""), item.get("fs_id") or display_name).encode('utf-8')).hexdigest()[:24]
                item_tmp_dir = os.path.join('/tmp', 'terabox_dl', resume_key)
                local_path = self._find_completed_in_dir(item_tmp_dir, item_size, display_name)

                if local_path:
                    self.log_callback(logging.INFO, "File đã tải đủ trên VPS, chuyển sang upload.")
                else:
                    self.log_callback(logging.INFO, "BƯỚC 2/3: Tải file về VPS...")
                    self._emit_state(status='downloading', phase='download')
                    self._progress(2, "Bắt đầu tải từ Terabox...")

                    for attempt in range(max_attempts):
                        if self.stop_checker() or self._stopped:
                            return False

                        download_url = self._get_fresh_dlink(item, cookie)
                        if not download_url:
                            self.log_callback(logging.WARNING, "Chưa lấy được link tải trực tiếp (lần {0}/{1})...".format(attempt + 1, max_attempts))
                            time.sleep(2)
                            continue

                        local_path = self.download_to_vps(download_url, cookie, item_tmp_dir, display_name, item_size)
                        if local_path:
                            break

                        if self.stop_checker() or self._stopped or self._download_error == 'stopped':
                            return False
                        if self._download_error != 'retryable':
                            return False

                        self.log_callback(logging.WARNING, "Link tải lỗi/hết hạn. Đang lấy link mới (lần {0}/{1})...".format(attempt + 1, max_attempts))
                        item["dlink"] = ""

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
            self.log_callback(logging.INFO, "HOÀN TẤT! Tất cả file Terabox đã được copy lên Google Drive.")
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
