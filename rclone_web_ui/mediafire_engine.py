"""
MediaFireEngine - Download public MediaFire files and upload to Google Drive.
Isolated from the existing Drive-to-Drive, Terabox, and Fshare flows.
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
    from urllib.parse import unquote_plus
except ImportError:
    from urllib import unquote_plus

try:
    import requests
except ImportError:
    requests = None


class MediaFireEngine:
    CHUNK_SIZE = 1024 * 1024
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"

    def __init__(self, progress_callback, log_callback, stop_checker, state_callback=None):
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stop_checker = stop_checker
        self.state_callback = state_callback
        self._process = None
        self._response = None
        self._stopped = False
        self._progress_base = 0
        self._progress_span = 100

    def _emit_state(self, **kwargs):
        if not self.state_callback:
            return
        try:
            self.state_callback(kwargs)
        except Exception:
            pass

    def _progress(self, percent, message):
        overall = int(self._progress_base + (percent * self._progress_span / 100.0))
        overall = max(0, min(100, overall))
        self.progress_callback(overall, message)

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

    def _headers(self, extra=None):
        headers = {
            'User-Agent': self.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        if extra:
            headers.update(extra)
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

    def _safe_name(self, name):
        name = (name or '').strip()
        name = re.sub(r'[\\/*?:"<>|]', '_', name)
        return name or 'mediafire_download'

    def _safe_remote_path(self, path):
        parts = []
        for part in (path or '').split('/'):
            clean = self._safe_name(part)
            if clean and clean != 'mediafire_download':
                parts.append(clean)
        return '/'.join(parts)

    def _append_dest_path(self, drive_dest, rel_dir):
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
            tmp_io = self._path_for_io(tmp_dir)
            if not os.path.isdir(tmp_io):
                return None
            for fname in os.listdir(tmp_io):
                if fname == 'download.part':
                    continue
                fpath = os.path.join(tmp_dir, fname)
                fpath_io = self._path_for_io(fpath)
                if os.path.isfile(fpath_io) and expected_size > 0:
                    if os.path.getsize(fpath_io) == expected_size:
                        return fpath_io
        except Exception:
            pass
        return None

    def _normalize_url(self, url):
        raw = (url or '').strip()
        if not raw:
            return ''
        if re.match(r'^[A-Za-z0-9]{8,}$', raw):
            return 'https://www.mediafire.com/file/{0}/file'.format(raw)
        if raw.startswith('http://') or raw.startswith('https://'):
            return raw
        return ''

    def _file_key_from_url(self, url):
        m = re.search(r'mediafire\.com/file/([A-Za-z0-9]+)', url or '', re.I)
        if m:
            return m.group(1)
        return ''

    def _folder_key_from_url(self, url):
        m = re.search(r'mediafire\.com/folder/([A-Za-z0-9]+)', url or '', re.I)
        if m:
            return m.group(1)
        return ''

    def _folder_name_from_api(self, folder_key):
        try:
            resp = requests.get(
                'https://www.mediafire.com/api/1.5/folder/get_info.php',
                params={
                    'folder_key': folder_key,
                    'response_format': 'json',
                },
                headers=self._headers({'Accept': 'application/json'}),
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                name = data.get('response', {}).get('folder_info', {}).get('name')
                if name:
                    return self._safe_name(name)
        except Exception:
            pass
        return None

    def _folder_name_from_url(self, url, fallback):
        try:
            tail = (url or '').split('/folder/', 1)[1].split('/', 1)[1]
            tail = tail.split('?', 1)[0].split('#', 1)[0]
            if tail:
                return self._safe_name(unquote_plus(tail))
        except Exception:
            pass
        if fallback:
            api_name = self._folder_name_from_api(fallback)
            if api_name:
                return api_name
        return self._safe_name(fallback)

    def _resolve_ambiguous_url(self, url):
        try:
            self.log_callback(logging.INFO, "Đang kiểm tra loại link (file/folder): {0}".format(url))
            session = requests.Session()
            resp = session.get(url, headers=self._headers(), timeout=20)
            if resp.status_code == 200:
                final_url = resp.url
                folder_key = self._folder_key_from_url(final_url)
                if folder_key:
                    return 'folder', folder_key, final_url
                
                file_key = self._file_key_from_url(final_url)
                if file_key:
                    return 'file', file_key, final_url

                html = resp.text or ''
                m = re.search(r'afI\s*=\s*["\']([A-Za-z0-9]+)["\']', html)
                if m:
                    return 'folder', m.group(1), final_url
                
                if self._extract_direct_link(html):
                    return 'file', None, final_url
        except Exception as e:
            self.log_callback(logging.WARNING, "Lỗi khi kiểm tra loại link: {0}".format(e))
        return 'unknown', None, url

    def parse_input_urls(self, raw):
        text = (raw or '').strip()
        if not text:
            return []
        text = re.sub(r'(https?://(?:www\.)?mediafire\.com/)', r'\n\1', text, flags=re.I)
        urls = []
        seen = set()
        for token in re.split(r'[\r\n\t ]+', text):
            token = token.strip().strip('\'"<>')
            if not token:
                continue
            if re.match(r'^[A-Za-z0-9]{8,}$', token):
                url = 'https://www.mediafire.com/file/{0}/file'.format(token)
            elif 'mediafire.com' not in token.lower():
                continue
            else:
                folder_key = self._folder_key_from_url(token)
                file_key = self._file_key_from_url(token)
                if folder_key:
                    url = 'https://www.mediafire.com/folder/{0}/{1}'.format(
                        folder_key, self._folder_name_from_url(token, folder_key))
                elif file_key:
                    url = 'https://www.mediafire.com/file/{0}/file'.format(file_key)
                else:
                    url = token
            key = url.lower()
            if key not in seen:
                seen.add(key)
                urls.append(url)
        return urls

    def _resume_dir_for_url(self, url):
        key = hashlib.sha1((url or '').encode('utf-8')).hexdigest()[:24]
        return os.path.join('/tmp', 'mediafire_dl', key)

    def _folder_content(self, folder_key, content_type):
        if requests is None:
            return {'error': "Module 'requests' chưa được cài. Chạy: pip install requests"}
        items = []
        chunk = 1
        while True:
            try:
                resp = requests.get(
                    'https://www.mediafire.com/api/1.5/folder/get_content.php',
                    params={
                        'folder_key': folder_key,
                        'content_type': content_type,
                        'response_format': 'json',
                        'chunk': chunk,
                    },
                    headers=self._headers({'Accept': 'application/json'}),
                    timeout=30,
                )
            except Exception as e:
                return {'error': 'Không đọc được folder MediaFire {0}: {1}'.format(folder_key, str(e))}
            if resp.status_code != 200:
                return {'error': 'MediaFire folder API trả HTTP {0}'.format(resp.status_code)}
            try:
                data = resp.json()
            except Exception:
                return {'error': 'MediaFire folder API trả dữ liệu không hợp lệ.'}
            response = data.get('response') or {}
            if response.get('result') != 'Success':
                return {'error': response.get('message') or 'Không đọc được folder MediaFire.'}
            content = response.get('folder_content') or {}
            items.extend(content.get(content_type) or [])
            if content.get('more_chunks') != 'yes':
                break
            chunk += 1
        return {'success': True, 'items': items}

    def _expand_folder(self, folder_key, rel_dir, visited):
        if folder_key in visited:
            return {'success': True, 'items': []}
        visited.add(folder_key)

        files_resp = self._folder_content(folder_key, 'files')
        if 'error' in files_resp:
            return files_resp

        result = []
        for file_item in files_resp.get('items', []):
            links = file_item.get('links') or {}
            url = links.get('normal_download') or ''
            quickkey = file_item.get('quickkey') or ''
            if not url and quickkey:
                url = 'https://www.mediafire.com/file/{0}/file'.format(quickkey)
            if not url:
                continue
            size = int(file_item.get('size') or 0)
            result.append({
                'url': url,
                'file_name': self._safe_name(file_item.get('filename') or quickkey or 'mediafire_download'),
                'file_size': size,
                'file_size_human': self._human_size(size),
                'rel_dir': rel_dir,
            })

        folders_resp = self._folder_content(folder_key, 'folders')
        if 'error' in folders_resp:
            return folders_resp
        for folder_item in folders_resp.get('items', []):
            child_key = folder_item.get('folderkey') or folder_item.get('folder_key') or folder_item.get('key') or ''
            child_name = self._safe_name(folder_item.get('name') or folder_item.get('foldername') or child_key)
            if not child_key:
                continue
            child_rel = (rel_dir.rstrip('/') + '/' + child_name).strip('/')
            child_resp = self._expand_folder(child_key, child_rel, visited)
            if 'error' in child_resp:
                return child_resp
            result.extend(child_resp.get('items', []))

        return {'success': True, 'items': result}

    def expand_inputs(self, raw):
        urls = self.parse_input_urls(raw)
        if not urls:
            return {'error': 'Không tìm thấy link MediaFire hợp lệ trong danh sách.'}
        items = []
        folder_count = 0
        file_count = 0
        for url in urls:
            folder_key = self._folder_key_from_url(url)
            file_key = self._file_key_from_url(url)

            # Phân giải động nếu không rõ link là file hay folder (ví dụ link dạng query ?)
            if not folder_key and not file_key:
                url_type, resolved_key, resolved_url = self._resolve_ambiguous_url(url)
                if url_type == 'folder':
                    folder_key = resolved_key
                    url = resolved_url
                elif url_type == 'file':
                    file_key = resolved_key
                    url = resolved_url

            if folder_key:
                folder_count += 1
                root_name = self._folder_name_from_url(url, folder_key)
                self.log_callback(logging.INFO, "Đang expand folder MediaFire: {0}".format(root_name))
                expanded = self._expand_folder(folder_key, root_name, set())
                if 'error' in expanded:
                    return expanded
                items.extend(expanded.get('items', []))
            else:
                file_count += 1
                items.append({
                    'url': url,
                    'file_name': '',
                    'file_size': 0,
                    'file_size_human': '',
                    'rel_dir': '',
                })
        if not items:
            return {'error': 'Không tìm thấy file nào trong danh sách MediaFire.'}
        return {
            'success': True,
            'items': items,
            'input_count': len(urls),
            'folder_count': folder_count,
            'direct_file_count': file_count,
        }

    def get_input_info(self, raw):
        expanded = self.expand_inputs(raw)
        if 'error' in expanded:
            return expanded
        items = expanded.get('items', [])
        total_size = sum(int(item.get('file_size') or 0) for item in items)
        return {
            'success': True,
            'file_name': 'MediaFire batch ({0} file)'.format(len(items)),
            'file_size': total_size,
            'file_size_human': self._human_size(total_size),
            'download_url_ready': True,
            'item_count': len(items),
            'folder_count': expanded.get('folder_count', 0),
            'direct_file_count': expanded.get('direct_file_count', 0),
        }

    def _html_unescape(self, value):
        try:
            import html
            return html.unescape(value)
        except Exception:
            return value.replace('&amp;', '&')

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
        try:
            from urllib.parse import urlparse, unquote
            path_name = os.path.basename(urlparse(response.url).path)
            if path_name:
                return self._safe_name(unquote(path_name))
        except Exception:
            pass
        return self._safe_name(fallback)

    def _extract_page_name(self, html, fallback):
        patterns = [
            r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
            r'<div[^>]+class=["\'][^"\']*filename[^"\']*["\'][^>]*>(.*?)</div>',
            r'<title>\s*([^<]+?)\s*(?:-|Download|MediaFire).*?</title>',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.I | re.S)
            if m:
                value = re.sub(r'<[^>]+>', '', m.group(1))
                value = self._html_unescape(value).strip()
                if value:
                    return self._safe_name(value)
        return self._safe_name(fallback)

    def _extract_direct_link(self, html):
        patterns = [
            r'id=["\']downloadButton["\'][^>]+href=["\']([^"\']+)["\']',
            r'href=["\']([^"\']+)["\'][^>]+id=["\']downloadButton["\']',
            r'href=["\'](https?://download[^"\']+mediafire\.com/[^"\']+)["\']',
            r'["\'](https?://download[^"\']+mediafire\.com/[^"\']+)["\']',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.I | re.S)
            if m:
                return self._html_unescape(m.group(1))
        return ''

    def get_direct_link(self, url):
        if requests is None:
            return {'error': "Module 'requests' chưa được cài. Chạy: pip install requests"}

        full_url = self._normalize_url(url)
        if not full_url or 'mediafire.com' not in full_url.lower():
            return {'error': 'Link MediaFire không hợp lệ. Cần dạng https://www.mediafire.com/file/...'}

        if re.search(r'https?://download[^/]*\.mediafire\.com/', full_url, re.I):
            return {
                'success': True,
                'url': full_url,
                'file_name': 'mediafire_download',
            }

        try:
            self.log_callback(logging.INFO, "Đang lấy trang MediaFire...")
            session = requests.Session()
            resp = session.get(full_url, headers=self._headers(), timeout=30)
        except Exception as e:
            return {'error': 'Không kết nối được MediaFire: {0}'.format(str(e))}

        if resp.status_code != 200:
            return {'error': 'MediaFire trả HTTP {0}'.format(resp.status_code)}

        html = resp.text or ''
        if re.search(r'(file you requested has been deleted|invalid or deleted file|permission denied)', html, re.I):
            return {'error': 'File MediaFire không tồn tại, đã bị xóa hoặc không có quyền tải.'}

        direct = self._extract_direct_link(html)
        if not direct:
            return {'error': 'Không tìm thấy direct link trong trang MediaFire.'}

        return {
            'success': True,
            'url': direct,
            'file_name': self._extract_page_name(html, 'mediafire_download'),
        }

    def get_file_info(self, url):
        direct = self.get_direct_link(url)
        if 'error' in direct:
            return direct

        info = {
            'success': True,
            'file_name': direct.get('file_name') or 'MediaFire file',
            'file_size': 0,
            'file_size_human': '',
            'download_url_ready': True,
        }

        try:
            r = requests.head(direct['url'], allow_redirects=True, timeout=20,
                              headers=self._headers({'Accept': '*/*'}))
            if r.ok:
                size = int(r.headers.get('Content-Length') or 0)
                name = self._guess_name_from_response(r, info['file_name'])
                info.update({
                    'file_name': name,
                    'file_size': size,
                    'file_size_human': self._human_size(size),
                })
                return info
        except Exception:
            pass

        try:
            r = requests.get(direct['url'], stream=True, timeout=20,
                             headers=self._headers({'Accept': '*/*', 'Range': 'bytes=0-0'}))
            if r.status_code in (200, 206):
                size = int(r.headers.get('Content-Range', '').split('/')[-1] or 0) if r.headers.get('Content-Range') else int(r.headers.get('Content-Length') or 0)
                name = self._guess_name_from_response(r, info['file_name'])
                info.update({
                    'file_name': name,
                    'file_size': size,
                    'file_size_human': self._human_size(size),
                })
            r.close()
        except Exception:
            pass
        return info

    def download_to_vps(self, url, tmp_dir):
        direct = self.get_direct_link(url)
        if 'error' in direct:
            self.log_callback(logging.ERROR, direct['error'])
            return None

        os.makedirs(tmp_dir, exist_ok=True)
        part_path = os.path.join(tmp_dir, 'download.part')
        part_path_for_io = self._path_for_io(part_path)
        existing = os.path.getsize(part_path_for_io) if os.path.exists(part_path_for_io) else 0
        headers = self._headers({'Accept': '*/*'})
        if existing > 0:
            headers['Range'] = 'bytes={0}-'.format(existing)
            self.log_callback(logging.INFO, "Resume MediaFire từ {0}".format(self._human_size(existing)))

        try:
            self._response = requests.get(direct['url'], headers=headers, stream=True, timeout=30)
            if self._response.status_code not in (200, 206) and existing > 0:
                status_code = self._response.status_code
                try:
                    self._response.close()
                except Exception:
                    pass
                self.log_callback(
                    logging.WARNING,
                    "Resume MediaFire bị từ chối HTTP {0}; xóa .part và tải lại file này từ đầu.".format(status_code)
                )
                try:
                    if os.path.exists(part_path_for_io):
                        os.remove(part_path_for_io)
                except Exception:
                    pass
                existing = 0
                headers.pop('Range', None)
                self._response = requests.get(direct['url'], headers=headers, stream=True, timeout=30)

            if self._response.status_code not in (200, 206):
                self.log_callback(logging.ERROR, "MediaFire download HTTP {0}".format(self._response.status_code))
                return None

            if existing > 0 and self._response.status_code == 200:
                self.log_callback(logging.WARNING, "MediaFire không resume bằng Range; tải lại file này từ đầu.")
                existing = 0
                if os.path.exists(part_path_for_io):
                    os.remove(part_path_for_io)

            file_name = self._guess_name_from_response(self._response, direct.get('file_name') or 'mediafire_download')
            total_header = int(self._response.headers.get('Content-Length') or 0)
            total_size = total_header + existing if self._response.status_code == 206 else total_header
            final_path = os.path.join(tmp_dir, file_name)
            final_path_for_io = self._path_for_io(final_path)
            mode = 'ab' if self._response.status_code == 206 and existing > 0 else 'wb'

            self._emit_state(file_name=file_name, file_size=total_size,
                             file_size_human=self._human_size(total_size))
            downloaded = existing
            last_emit = 0
            with open(part_path_for_io, mode) as f:
                for chunk in self._response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING, "Download MediaFire bị dừng.")
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

            if os.path.exists(final_path_for_io):
                os.remove(final_path_for_io)
            os.rename(part_path_for_io, final_path_for_io)
            self._progress(50, "Tải MediaFire hoàn tất")
            self.log_callback(logging.INFO, "Đã tải về VPS: {0}".format(final_path))
            return final_path_for_io
        except Exception as e:
            self.log_callback(logging.ERROR, "Lỗi tải MediaFire: {0}".format(str(e)))
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

    def run_full_pipeline(self, url, drive_dest):
        self._stopped = False
        try:
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO, "BƯỚC 1/3: Expand danh sách MediaFire...")
            self._emit_state(status='fetching_info', phase='info')
            self._progress(0, "Đang lấy danh sách MediaFire...")

            expanded = self.expand_inputs(url)
            if 'error' in expanded:
                self.log_callback(logging.ERROR, expanded['error'])
                return False

            items = expanded.get('items') or []
            total_items = len(items)
            if not total_items:
                self.log_callback(logging.ERROR, "Không có file MediaFire nào để tải.")
                return False
            self._emit_state(total_items=total_items, current_index=0)
            self.log_callback(logging.INFO, "Đã tìm thấy {0} file MediaFire.".format(total_items))

            # Step 0: GDrive pre-scan (1 lan duy nhat)
            self.log_callback(logging.INFO, "Kiem tra file da co tren Google Drive...")
            existing_files = self._scan_gdrive_existing(drive_dest)

            for index, item in enumerate(items, 1):
                if self.stop_checker() or self._stopped:
                    return False

                span = 100.0 / total_items
                self._progress_base = (index - 1) * span
                self._progress_span = span

                display_name = item.get('file_name') or 'MediaFire file'
                item_size = item.get('file_size', 0)
                self._emit_state(current_index=index, total_items=total_items,
                                 file_name=display_name,
                                 file_size=item_size,
                                 file_size_human=item.get('file_size_human', ''))
                self.log_callback(logging.INFO, "=" * 50)
                self.log_callback(logging.INFO, "File {0}/{1}: {2}".format(index, total_items, display_name))
                if item.get('rel_dir'):
                    self.log_callback(logging.INFO, "Thư mục đích con: {0}".format(item.get('rel_dir')))

                # Step 1: Check GDrive skip
                item_rel = item.get('rel_dir', '')
                if item_rel:
                    check_path = item_rel.replace('\\', '/').strip('/') + '/' + display_name
                else:
                    check_path = display_name
                check_path = check_path.replace('\\', '/').strip('/')
                if item_size > 0 and (check_path, item_size) in existing_files:
                    self.log_callback(logging.INFO, "Da co tren GDrive, skip: {0}".format(display_name))
                    self._progress(100, "Skipped (da co tren GDrive)")
                    continue

                # Step 2: Check VPS complete file
                item_tmp_dir = self._resume_dir_for_url(item.get('url') or display_name)
                local_path = self._find_completed_in_dir(item_tmp_dir, item_size)
                if local_path:
                    self.log_callback(logging.INFO,
                        "File da tai du tren VPS, chuyen sang upload.")
                else:
                    self.log_callback(logging.INFO, "BUOC 2/3: Tai file MediaFire ve VPS...")
                    self._emit_state(status='downloading', phase='download')
                    local_path = self.download_to_vps(item.get('url'), item_tmp_dir)
                    if not local_path:
                        return False

                if self.stop_checker() or self._stopped:
                    return False

                self.log_callback(logging.INFO, "BUOC 3/3: Day file len Google Drive...")
                self._emit_state(status='uploading', phase='upload')
                self._progress(50, "Bat dau upload len Google Drive...")
                item_dest = self._append_dest_path(drive_dest, item.get('rel_dir') or '')
                success = self.upload_to_drive(local_path, item_dest)
                if not success:
                    return False
                self.cleanup(item_tmp_dir)

            self._progress_base = 0
            self._progress_span = 100
            self._emit_state(status='done', phase='done',
                             current_index=total_items, total_items=total_items)
            self._progress(100, "Hoàn tất!")
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
