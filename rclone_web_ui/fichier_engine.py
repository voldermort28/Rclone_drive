"""
FichierEngine - Download 1fichier files (Free or Premium) and upload to Google Drive.
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


class FichierEngine:
    CHUNK_SIZE = 1024 * 1024
    USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36")
    FICHIER_DOMAINS = ('1fichier.com', '1fichier.fr', '1fichier.co',
                       '1fichier.org', '1fichier.net')
    API_BASE = "https://api.1fichier.com/v1"

    def __init__(self, progress_callback, log_callback, stop_checker,
                 state_callback=None):
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stop_checker = stop_checker
        self.state_callback = state_callback
        self._process = None
        self._response = None
        self._stopped = False
        self._progress_base = 0
        self._progress_span = 100
        self._cache = {}

    # ── helpers ────────────────────────────────────────────

    def _emit_state(self, **kwargs):
        if not self.state_callback:
            return
        try:
            self.state_callback(kwargs)
        except Exception:
            pass

    def _progress(self, percent, message):
        overall = int(self._progress_base +
                      (percent * self._progress_span / 100.0))
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
            result = subprocess.run(
                ['which', 'gclone'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            p = result.stdout.decode('utf-8', errors='replace').strip()
            if p and os.path.isfile(p):
                return p
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
            return [arg.encode('utf-8') if isinstance(arg, str) else arg
                    for arg in cmd]
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
            'Accept': ('text/html,application/xhtml+xml,'
                       'application/xml;q=0.9,*/*;q=0.8'),
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
        return name or 'fichier_download'

    # ── URL parsing ────────────────────────────────────────

    def _file_id_from_url(self, url):
        """Extract file ID from 1fichier URL."""
        m = re.search(r'1fichier\.\w+/?\?([A-Za-z0-9]+)', url or '')
        if m:
            return m.group(1)
        return ''

    def _clean_url(self, url):
        """Normalize URL, strip affiliate params."""
        raw = (url or '').strip()
        if not raw:
            return ''
        fid = self._file_id_from_url(raw)
        if fid:
            return 'https://1fichier.com/?{0}'.format(fid)
        return raw

    def _resume_dir_for_url(self, url):
        key = hashlib.sha1((url or '').encode('utf-8')).hexdigest()[:24]
        return os.path.join('/tmp', 'fichier_dl', key)

    # ── direct link acquisition ────────────────────────────

    def _get_direct_link_premium(self, url, api_key):
        """Use 1fichier Premium API to get direct download link."""
        try:
            self.log_callback(logging.INFO,
                              "Dung API Premium de lay link tai...")
            resp = requests.post(
                self.API_BASE + "/download/get_token.cgi",
                json={"url": url, "single": 1},
                headers={
                    "Authorization": "Bearer " + api_key,
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'OK' and data.get('url'):
                    return {'success': True, 'url': data['url']}
                return {'error': 'API 1fichier: {0}'.format(
                    data.get('message', 'Unknown error'))}
            return {'error': 'API 1fichier HTTP {0}'.format(resp.status_code)}
        except Exception as e:
            return {'error': 'Loi ket noi API 1fichier: {0}'.format(e)}

    def _get_direct_link_free(self, url):
        """Scrape 1fichier download page for free users."""
        clean = self._clean_url(url)
        if not clean:
            return {'error': 'Link 1fichier khong hop le.'}

        # Check cache first
        if clean in self._cache:
            self.log_callback(logging.INFO, "Dung link da cache truoc do.")
            return self._cache[clean]

        try:
            session = requests.Session()
            session.cookies.set("AF", "0", domain="1fichier.com")
            self.log_callback(logging.INFO,
                              "Dang tai trang 1fichier (Free)...")
            resp = session.get(clean, headers=self._headers(), timeout=30)
        except Exception as e:
            return {'error': 'Khong ket noi duoc 1fichier: {0}'.format(e)}

        if resp.status_code != 200:
            return {'error': '1fichier HTTP {0}'.format(resp.status_code)}

        html = resp.text or ''

        # Check: file not found
        if 'The requested file does not exist' in html or \
           'could be deleted' in html.lower():
            return {'error': 'File 1fichier khong ton tai hoac da bi xoa.'}

        # Check: IP block / professional infrastructure
        if 'Accès restreint' in html or \
           'professional infrastructure detected' in html or \
           'unauthorized personal VPN' in html or \
           'belonging to a server' in html.lower():
            return {'error': 'IP VPS bi 1fichier chan (professional infrastructure/VPN detected). Ban can dung Premium API Key co CDN Credits.'}

        # Check: rate limit / must wait between downloads
        wait_match = re.search(
            r'You must wait (\d+) minutes?', html, re.I)
        if wait_match:
            mins = wait_match.group(1)
            return {'error': (
                'Gioi han 1fichier: Ban phai cho {0} phut '
                'moi co the tai tiep (tai khoan Free gioi han '
                'thoi gian giua cac luot tai).').format(mins)}

        # Extract file info from page
        name_match = re.search(
            r'<span style="font-weight:bold">(.*?)</span>', html)
        file_name = self._safe_name(
            name_match.group(1) if name_match else '')

        size_match = re.search(
            r'<span style="font-size:0\.9em;font-style:italic">'
            r'([\d.,]+\s*\w+)</span>', html)
        size_text = size_match.group(1) if size_match else ''

        # Find countdown timer
        ct_match = re.search(r'var ct = (\d+);', html)
        wait_time = int(ct_match.group(1)) if ct_match else 0

        if wait_time > 0:
            self.log_callback(logging.INFO,
                               "Can cho {0} giay (tai khoan Free)...".format(
                                   wait_time))
            for remaining in range(wait_time, 0, -1):
                if self.stop_checker() or self._stopped:
                    return {'error': 'Da dung boi nguoi dung.'}
                self._progress(
                    int((wait_time - remaining) * 20 / wait_time),
                    "Cho 1fichier: {0}s...".format(remaining))
                time.sleep(1)
            self._progress(20, "Het thoi gian cho, dang lay link...")

        # POST to get direct link
        post_url = clean
        try:
            resp2 = session.post(post_url, data={},
                                 headers=self._headers(), timeout=30)
        except Exception as e:
            return {'error': 'Loi POST 1fichier: {0}'.format(e)}

        html2 = resp2.text or ''

        # Extract direct download link
        links = re.findall(
            r'href="(https?://[a-z0-9\-]+\.1fichier\.com/[^"]+)"',
            html2, re.I)
        
        # Filter out static assets
        direct_url = None
        for link in links:
            if not any(link.lower().endswith(ext) for ext in ['.css', '.ico', '.png', '.jpg', '.jpeg', '.js', '.gif', '.svg']):
                direct_url = link
                break

        if not direct_url:
            return {'error': 'Không tìm thấy link tải trực tiếp từ 1fichier.'}

        result = {
            'success': True,
            'url': direct_url,
            'file_name': file_name,
            'file_size_text': size_text,
        }
        self._cache[clean] = result
        return result

    def get_direct_link(self, url, api_key=''):
        """Get direct download link (Premium or Free)."""
        if api_key:
            result = self._get_direct_link_premium(url, api_key)
            if 'error' not in result:
                return result
            self.log_callback(logging.WARNING,
                               "API Premium that bai, thu che do Free...")
        return self._get_direct_link_free(url)

    # ── file info ──────────────────────────────────────────

    def get_file_info(self, url, api_key=''):
        direct = self.get_direct_link(url, api_key)
        if 'error' in direct:
            return direct

        info = {
            'success': True,
            'file_name': direct.get('file_name') or 'fichier_download',
            'file_size': 0,
            'file_size_human': direct.get('file_size_text', ''),
            'download_url_ready': True,
        }

        try:
            # Try HEAD first
            r = requests.head(direct['url'], allow_redirects=True,
                              timeout=20,
                              headers=self._headers({'Accept': '*/*'}))
            # Fallback to GET stream if HEAD fails or doesn't return Content-Length
            if not r.ok or not r.headers.get('Content-Length'):
                r = requests.get(direct['url'], stream=True, allow_redirects=True,
                                 timeout=20,
                                 headers=self._headers({'Accept': '*/*'}))
            if r.ok:
                size = int(r.headers.get('Content-Length') or 0)
                cd = r.headers.get('Content-Disposition', '')
                m = re.search(r'filename="?([^";]+)"?', cd, re.I)
                if m:
                    info['file_name'] = self._safe_name(m.group(1))
                info['file_size'] = size
                info['file_size_human'] = self._human_size(size)
                try:
                    r.close()
                except Exception:
                    pass
        except Exception:
            pass

        return info

    # ── download ───────────────────────────────────────────

    def download_to_vps(self, url, tmp_dir, api_key=''):
        direct = self.get_direct_link(url, api_key)
        if 'error' in direct:
            self.log_callback(logging.ERROR, direct['error'])
            return None

        os.makedirs(tmp_dir, exist_ok=True)
        part_path = os.path.join(tmp_dir, 'download.part')
        part_io = self._path_for_io(part_path)
        existing = (os.path.getsize(part_io)
                    if os.path.exists(part_io) else 0)
        headers = self._headers({'Accept': '*/*'})
        if existing > 0:
            headers['Range'] = 'bytes={0}-'.format(existing)
            self.log_callback(logging.INFO,
                              "Resume 1fichier tu {0}".format(
                                  self._human_size(existing)))

        try:
            self._response = requests.get(
                direct['url'], headers=headers, stream=True, timeout=60)

            # If resume rejected, restart
            if self._response.status_code not in (200, 206) and existing > 0:
                try:
                    self._response.close()
                except Exception:
                    pass
                if os.path.exists(part_io):
                    os.remove(part_io)
                existing = 0
                headers.pop('Range', None)
                self._response = requests.get(
                    direct['url'], headers=headers, stream=True, timeout=60)

            if self._response.status_code not in (200, 206):
                self.log_callback(
                    logging.ERROR,
                    "1fichier download HTTP {0}".format(
                        self._response.status_code))
                return None

            if existing > 0 and self._response.status_code == 200:
                existing = 0
                if os.path.exists(part_io):
                    os.remove(part_io)

            # Determine file name
            file_name = direct.get('file_name') or 'fichier_download'
            cd = self._response.headers.get('Content-Disposition', '')
            m = re.search(r'filename="?([^";]+)"?', cd, re.I)
            if m:
                file_name = self._safe_name(m.group(1))

            total_header = int(
                self._response.headers.get('Content-Length') or 0)
            total_size = (total_header + existing
                          if self._response.status_code == 206
                          else total_header)
            final_path = os.path.join(tmp_dir, file_name)
            final_io = self._path_for_io(final_path)
            mode = ('ab' if self._response.status_code == 206
                    and existing > 0 else 'wb')

            self._emit_state(file_name=file_name, file_size=total_size,
                             file_size_human=self._human_size(total_size))
            downloaded = existing
            last_emit = 0

            with open(part_io, mode) as f:
                for chunk in self._response.iter_content(
                        chunk_size=self.CHUNK_SIZE):
                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING,
                                          "Download 1fichier bi dung.")
                        return None
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last_emit >= 1:
                        pct = (int(downloaded * 50 / total_size)
                               if total_size else 5)
                        pct = max(2, min(50, pct))
                        self._progress(
                            pct,
                            "Downloading: {0}".format(
                                self._human_size(downloaded)))
                        last_emit = now

            if os.path.exists(final_io):
                os.remove(final_io)
            os.rename(part_io, final_io)
            self._progress(50, "Tai 1fichier hoan tat")
            self.log_callback(logging.INFO,
                              "Da tai ve VPS: {0}".format(final_path))
            return final_io
        except Exception as e:
            self.log_callback(logging.ERROR,
                              "Loi tai 1fichier: {0}".format(e))
            return None
        finally:
            self._response = None

    # ── upload ─────────────────────────────────────────────

    def upload_to_drive(self, local_path, drive_dest):
        binary = self._detect_binary()
        dest = drive_dest
        m = re.match(
            r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', drive_dest)
        if m:
            dest = "{0}:{{{1}}}{2}".format(
                m.group(1), m.group(2), m.group(3) or '')

        cmd = [binary, "copy", local_path, dest,
               "--verbose", "--stats=1s", "--stats-one-line"]
        sa_dir = self._get_sa_dir()
        if sa_dir:
            sa_count = len(glob.glob(os.path.join(sa_dir, '*.json')))
            cmd.extend(["--drive-service-account-file-path", sa_dir])
            self.log_callback(logging.INFO,
                              "SA rotation: {0} accounts".format(sa_count))

        self.log_callback(logging.INFO,
                          "Uploading to Google Drive: {0}".format(dest))

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
                        rp = int(match.group(1))
                        overall = 50 + int(rp * 50 / 100)
                        self._progress(overall,
                                       "Uploading: {0}%".format(rp))
                    if self.stop_checker() or self._stopped:
                        self.log_callback(logging.WARNING,
                                          "Upload bi dung boi nguoi dung.")
                        self._process.terminate()
                        return False

                self._process.wait()
                if self._process.returncode == 0:
                    self.log_callback(logging.INFO,
                                      "Upload len Google Drive thanh cong!")
                    return True
                self.log_callback(
                    logging.ERROR,
                    "Rclone exited with code {0}".format(
                        self._process.returncode))
                return False
        except FileNotFoundError:
            self.log_callback(logging.ERROR,
                              "Khong tim thay gclone/rclone.")
            return False
        except Exception as e:
            self.log_callback(logging.ERROR,
                              "Upload error: {0}".format(e))
            return False
        finally:
            self._process = None

    # ── cleanup ────────────────────────────────────────────

    def cleanup(self, tmp_dir):
        try:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
                self.log_callback(logging.INFO,
                                  "Da don dep: {0}".format(tmp_dir))
        except Exception as e:
            self.log_callback(logging.WARNING,
                              "Loi don dep: {0}".format(e))

    # ── GDrive scan ────────────────────────────────────────

    def _scan_gdrive_existing(self, drive_dest):
        existing = set()
        try:
            dest = drive_dest
            m = re.match(
                r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', drive_dest)
            if m:
                dest = "{0}:{{{1}}}{2}".format(
                    m.group(1), m.group(2), m.group(3) or '')
            binary = self._detect_binary()
            cmd = [binary, "lsjson", "-R", "--files-only", dest]
            sa_dir = self._get_sa_dir()
            if sa_dir:
                cmd.extend(["--drive-service-account-file-path", sa_dir])
            p = subprocess.Popen(
                self._cmd_for_subprocess(cmd),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, _ = p.communicate(timeout=60)
            if p.returncode == 0:
                import json
                data = json.loads(
                    stdout.decode('utf-8', errors='replace'))
                for item in data:
                    path = item.get('Path', '')
                    size = item.get('Size', 0)
                    if path:
                        norm = path.replace('\\', '/').strip('/')
                        existing.add((norm, size))
                self.log_callback(
                    logging.INFO,
                    "GDrive scan: {0} file da co.".format(len(existing)))
        except Exception as e:
            self.log_callback(logging.WARNING,
                              "Khong the quet GDrive: {0}".format(e))
        return existing

    # ── full pipeline ──────────────────────────────────────

    def run_full_pipeline(self, url, config, drive_dest):
        self._stopped = False
        self._cache = {}
        api_key = (config or {}).get('api_key', '')

        try:
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO,
                              "BUOC 1/3: Lay thong tin file 1fichier...")
            self._emit_state(status='fetching_info', phase='info')
            self._progress(0, "Dang lay thong tin 1fichier...")

            info = self.get_file_info(url, api_key)
            if 'error' in info:
                self.log_callback(logging.ERROR, info['error'])
                return False

            file_name = info.get('file_name', 'fichier_download')
            file_size = info.get('file_size', 0)
            self._emit_state(
                file_name=file_name,
                file_size=file_size,
                file_size_human=info.get('file_size_human', ''))
            self.log_callback(
                logging.INFO,
                "File: {0} ({1})".format(
                    file_name,
                    info.get('file_size_human', 'unknown')))

            # Check GDrive existing
            self.log_callback(logging.INFO,
                              "Kiem tra file da co tren Google Drive...")
            existing = self._scan_gdrive_existing(drive_dest)
            check_path = file_name.replace('\\', '/').strip('/')
            if file_size > 0 and (check_path, file_size) in existing:
                self.log_callback(
                    logging.INFO,
                    "Da co tren GDrive, skip: {0}".format(file_name))
                self._emit_state(status='done', phase='done')
                self._progress(100, "Skipped (da co tren GDrive)")
                return True

            # Check VPS completed file
            tmp_dir = self._resume_dir_for_url(url)
            try:
                from pending_manager import save_pending_meta
                save_pending_meta(tmp_dir, url=url, file_name=file_name,
                                  file_size=file_size, dest=drive_dest, engine='fichier')
            except Exception:
                pass
            completed = None
            try:
                tmp_io = self._path_for_io(tmp_dir)
                if os.path.isdir(tmp_io):
                    for fname in os.listdir(tmp_io):
                        if fname == 'download.part':
                            continue
                        fpath = os.path.join(tmp_dir, fname)
                        fpath_io = self._path_for_io(fpath)
                        if (os.path.isfile(fpath_io) and file_size > 0
                                and os.path.getsize(fpath_io) == file_size):
                            completed = fpath_io
                            break
            except Exception:
                pass

            if completed:
                self.log_callback(logging.INFO,
                                  "File da tai du tren VPS, upload luon.")
                local_path = completed
            else:
                self.log_callback(logging.INFO,
                                  "BUOC 2/3: Tai file 1fichier ve VPS...")
                self._emit_state(status='downloading', phase='download')
                local_path = self.download_to_vps(url, tmp_dir, api_key)
                if not local_path:
                    return False

            if self.stop_checker() or self._stopped:
                return False

            self.log_callback(logging.INFO,
                              "BUOC 3/3: Day file len Google Drive...")
            self._emit_state(status='uploading', phase='upload')
            self._progress(50, "Bat dau upload len Google Drive...")
            success = self.upload_to_drive(local_path, drive_dest)
            if not success:
                return False

            self.cleanup(tmp_dir)
            self._emit_state(status='done', phase='done')
            self._progress(100, "Hoan tat!")
            return True
        except Exception as e:
            self.log_callback(logging.ERROR,
                              "Pipeline error: {0}".format(e))
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
