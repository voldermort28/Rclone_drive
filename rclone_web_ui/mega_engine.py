"""
MegaEngine - Download public Mega.nz folders and upload to Google Drive.
Uses raw Mega API + pycryptodome for decryption.
Compatible with Python 3.6+.
"""

import base64
import glob
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import time

try:
    import requests
except ImportError:
    requests = None

try:
    from Crypto.Cipher import AES
    from Crypto.Util import Counter
except ImportError:
    AES = None


class MegaEngine:
    CHUNK_SIZE = 1024 * 1024
    USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/135.0.0.0 Safari/537.36")
    API_URL = "https://g.api.mega.co.nz/cs"

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
        self._seq_id = int(time.time())

    # ==================== HELPERS ====================

    def _emit_state(self, **kwargs):
        if self.state_callback:
            try:
                self.state_callback(kwargs)
            except Exception:
                pass

    def _progress(self, percent, message):
        overall = int(self._progress_base + (percent * self._progress_span / 100.0))
        overall = max(0, min(100, overall))
        self.progress_callback(overall, message)

    @staticmethod
    def _b64_url_decode(data):
        data += '=' * ((4 - len(data) % 4) % 4)
        return base64.urlsafe_b64decode(data)

    @staticmethod
    def _b64_url_encode(data):
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

    @staticmethod
    def _a32_to_str(a):
        return struct.pack('>%dI' % len(a), *a)

    @staticmethod
    def _str_to_a32(b):
        if isinstance(b, str):
            b = b.encode('latin-1')
        if len(b) % 4:
            b += b'\x00' * (4 - len(b) % 4)
        return list(struct.unpack('>%dI' % (len(b) // 4), b))

    def _decrypt_key(self, enc_key_a32, master_key_a32):
        """AES-ECB decrypt node key using folder master key."""
        result = []
        mk = self._a32_to_str(master_key_a32)
        # Process in 4-int (16-byte) blocks
        for i in range(0, len(enc_key_a32), 4):
            block = enc_key_a32[i:i + 4]
            if len(block) < 4:
                # Pad short blocks
                block = list(block) + [0] * (4 - len(block))
            cipher = AES.new(mk, AES.MODE_ECB)
            dec = self._str_to_a32(cipher.decrypt(self._a32_to_str(block)))
            result.extend(dec)
        return result

    def _decrypt_attr(self, attr_b64, key_a32):
        """AES-CBC decrypt node attributes to get filename etc."""
        try:
            attr_bytes = self._b64_url_decode(attr_b64)
        except Exception:
            return {}
        # For file nodes: key is 8 ints, derive AES key by XOR
        if len(key_a32) >= 8:
            aes_key = [
                key_a32[0] ^ key_a32[4], key_a32[1] ^ key_a32[5],
                key_a32[2] ^ key_a32[6], key_a32[3] ^ key_a32[7]
            ]
        else:
            aes_key = list(key_a32[:4])
        try:
            cipher = AES.new(self._a32_to_str(aes_key), AES.MODE_CBC, b'\x00' * 16)
            attr_dec = cipher.decrypt(attr_bytes)
            attr_str = attr_dec.decode('utf-8', errors='ignore')
        except Exception:
            return {}
        if 'MEGA{' in attr_str:
            start = attr_str.index('MEGA{') + 4
            try:
                depth = 0
                end = start
                for i in range(start, len(attr_str)):
                    if attr_str[i] == '{':
                        depth += 1
                    elif attr_str[i] == '}':
                        depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
                return json.loads(attr_str[start:end])
            except Exception:
                return {}
        return {}

    def _api_request(self, data, folder_id=None):
        """Send request to Mega API."""
        params = {'id': self._seq_id}
        self._seq_id += 1
        if folder_id:
            params['n'] = folder_id
        resp = requests.post(self.API_URL, params=params,
                             data=json.dumps([data]),
                             headers={'Content-Type': 'application/json'},
                             timeout=60)
        result = resp.json()
        if isinstance(result, int):
            raise Exception("Mega API error code: {0}".format(result))
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        return result

    @staticmethod
    def _human_size(size):
        try:
            size = float(size)
        except Exception:
            return ''
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return "{0:.2f} {1}".format(size, unit)
            size /= 1024.0
        return "{0:.2f} PB".format(size)

    @staticmethod
    def _safe_name(name):
        name = (name or '').strip()
        name = re.sub(r'[\\/*?:"<>|]', '_', name)
        return name or 'mega_download'

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

    # ==================== MEGA FOLDER PARSING ====================

    def parse_url(self, url):
        """Parse mega URL into (type, id, key_a32).
        type is 'folder', 'folder_file', or 'file'.
        """
        url = (url or '').strip()
        
        # New folder format with specific file or keyword: mega.nz/folder/ID#KEY/file/SPEC
        m = re.match(r'https?://(?:www\.)?mega\.(?:nz|co\.nz|io)/folder/([^#]+)#([^/]+)/file/(.+)', url, re.I)
        if m:
            folder_id = m.group(1)
            key_bytes = self._b64_url_decode(m.group(2))
            spec = m.group(3).split('?')[0].split('#')[0].rstrip('/')
            return 'folder_file', (folder_id, spec), self._str_to_a32(key_bytes)
            
        # Old folder format with specific file or keyword: mega.nz/#F!ID!KEY/file/SPEC
        m = re.match(r'https?://(?:www\.)?mega\.(?:nz|co\.nz|io)/#F!([^!]+)!([^/!]+)/file/(.+)', url, re.I)
        if m:
            folder_id = m.group(1)
            key_bytes = self._b64_url_decode(m.group(2))
            spec = m.group(3).split('?')[0].split('#')[0].rstrip('/')
            return 'folder_file', (folder_id, spec), self._str_to_a32(key_bytes)

        # New folder format: mega.nz/folder/ID#KEY
        m = re.match(r'https?://(?:www\.)?mega\.(?:nz|co\.nz|io)/folder/([^#]+)#(.+)', url, re.I)
        if m:
            folder_id = m.group(1)
            key_bytes = self._b64_url_decode(m.group(2))
            return 'folder', folder_id, self._str_to_a32(key_bytes)
            
        # Old folder format: mega.nz/#F!ID!KEY
        m = re.match(r'https?://(?:www\.)?mega\.(?:nz|co\.nz|io)/#F!([^!]+)!(.+)', url, re.I)
        if m:
            folder_id = m.group(1)
            key_bytes = self._b64_url_decode(m.group(2))
            return 'folder', folder_id, self._str_to_a32(key_bytes)
            
        # New file format: mega.nz/file/ID#KEY
        m = re.match(r'https?://(?:www\.)?mega\.(?:nz|co\.nz|io)/file/([^#]+)#(.+)', url, re.I)
        if m:
            file_id = m.group(1)
            key_bytes = self._b64_url_decode(m.group(2))
            return 'file', file_id, self._str_to_a32(key_bytes)
            
        # Old file format: mega.nz/#!ID!KEY
        m = re.match(r'https?://(?:www\.)?mega\.(?:nz|co\.nz|io)/#?!([^!]+)!(.+)', url, re.I)
        if m:
            file_id = m.group(1)
            key_bytes = self._b64_url_decode(m.group(2))
            return 'file', file_id, self._str_to_a32(key_bytes)
            
        return None, None, None

    def parse_folder_url(self, url):
        """Parse mega folder URL into (folder_id, folder_key_a32)."""
        url_type, node_id, node_key = self.parse_url(url)
        if url_type == 'folder':
            return node_id, node_key
        elif url_type == 'folder_file':
            return node_id[0], node_key
        return None, None

    def get_folder_info(self, url):
        """Get folder contents: list of files with names, sizes, tree structure."""
        if requests is None:
            return {'error': "Module 'requests' not installed."}
        if AES is None:
            return {'error': "Module 'pycryptodome' not installed."}

        url_type, node_id, node_key = self.parse_url(url)
        if not url_type or not node_id or not node_key:
            return {'error': 'Link Mega.nz không hợp lệ. Cần dạng https://mega.nz/folder/ID#KEY hoặc https://mega.nz/file/ID#KEY'}

        if url_type == 'file':
            # Handle single file info query
            try:
                data = self._api_request({'a': 'g', 'g': 1, 'p': node_id})
            except Exception as e:
                return {'error': 'Mega API lỗi: {0}'.format(str(e))}

            if not isinstance(data, dict):
                return {'error': 'Mega API trả về dữ liệu không hợp lệ.'}

            try:
                at_str = data.get('at', '')
                size = data.get('s', 0)
                attrs = self._decrypt_attr(at_str, node_key)
                filename = attrs.get('n', 'file_{0}'.format(node_id))
            except Exception as e:
                filename = 'file_{0}'.format(node_id)
                size = data.get('s', 0)

            safe_filename = self._safe_name(filename)
            files = [{
                'handle': node_id,
                'name': safe_filename,
                'size': size,
                'size_human': self._human_size(size) if size else '',
                'rel_dir': '',
                'key_a32': node_key,
                'is_file_only': True,
            }]
            return {
                'success': True,
                'folder_name': safe_filename,
                'folder_id': node_id,
                'folder_key': node_key,
                'file_count': 1,
                'total_size': size,
                'total_size_human': self._human_size(size),
                'files': files,
            }

        if url_type == 'folder_file':
            folder_id, target_spec = node_id
            try:
                import urllib.parse
                target_spec = urllib.parse.unquote(target_spec).strip()
            except Exception:
                target_spec = str(target_spec).strip()

            try:
                data = self._api_request({'a': 'f', 'c': 1, 'ca': 1, 'r': 1}, folder_id)
            except Exception as e:
                return {'error': 'Mega API lỗi: {0}'.format(str(e))}

            if not isinstance(data, dict) or 'f' not in data:
                return {'error': 'Mega API trả về dữ liệu không hợp lệ.'}

            raw_nodes = data['f']
            node_ids = {n.get('h') for n in raw_nodes if n.get('h')}
            root_handle = None
            for n in raw_nodes:
                if n.get('t') == 2 or (n.get('p') not in node_ids):
                    root_handle = n.get('h')
                    break

            target_node = None
            node_key_dec = None
            safe_filename = None

            # 1. Try exact handle/node ID match first
            for n in raw_nodes:
                if n.get('h') == target_spec:
                    target_node = n
                    break

            if target_node:
                k_str = target_node.get('k', '')
                a_str = target_node.get('a', '')
                enc_key_b64 = ''
                if k_str:
                    parts = k_str.split('/')
                    for part in parts:
                        if ':' in part:
                            h_part, k_part = part.split(':', 1)
                            if h_part == root_handle:
                                enc_key_b64 = k_part
                                break
                    if not enc_key_b64:
                        first_part = parts[0]
                        enc_key_b64 = first_part.split(':', 1)[1] if ':' in first_part else first_part
                enc_key_bytes = self._b64_url_decode(enc_key_b64)
                enc_key_a32 = self._str_to_a32(enc_key_bytes)
                node_key_dec = self._decrypt_key(enc_key_a32, node_key)
                attrs = self._decrypt_attr(a_str, node_key_dec)
                name = attrs.get('n', 'file_{0}'.format(target_node.get('h', '')))
                safe_filename = self._safe_name(name)
            else:
                # 2. If not found by handle, search by filename or keyword
                spec_lower = target_spec.lower()
                for n in raw_nodes:
                    if n.get('t') == 1 or n.get('t') == 2:
                        continue
                    k_str = n.get('k', '')
                    if not k_str:
                        continue
                    enc_key_b64 = ''
                    parts = k_str.split('/')
                    for part in parts:
                        if ':' in part:
                            h_part, k_part = part.split(':', 1)
                            if h_part == root_handle:
                                enc_key_b64 = k_part
                                break
                    if not enc_key_b64:
                        first_part = parts[0]
                        enc_key_b64 = first_part.split(':', 1)[1] if ':' in first_part else first_part
                    try:
                        enc_key_bytes = self._b64_url_decode(enc_key_b64)
                        enc_key_a32 = self._str_to_a32(enc_key_bytes)
                        n_key_dec = self._decrypt_key(enc_key_a32, node_key)
                        attrs = self._decrypt_attr(n.get('a', ''), n_key_dec)
                        fname = attrs.get('n', '')
                        if spec_lower in fname.lower():
                            target_node = n
                            node_key_dec = n_key_dec
                            safe_filename = self._safe_name(fname)
                            break
                    except Exception:
                        continue

            if not target_node:
                return {'error': 'Không tìm thấy file khớp với "{0}" trong folder Mega.'.format(target_spec)}

            s = target_node.get('s', 0)
            files = [{
                'handle': target_node.get('h', ''),
                'name': safe_filename,
                'size': s,
                'size_human': self._human_size(s) if s else '',
                'rel_dir': '',
                'key_a32': node_key_dec,
                'is_file_only': False,
            }]
            return {
                'success': True,
                'folder_name': safe_filename,
                'folder_id': folder_id,
                'folder_key': node_key,
                'file_count': 1,
                'total_size': s,
                'total_size_human': self._human_size(s),
                'files': files,
            }

        # Handle folder info query
        try:
            data = self._api_request({'a': 'f', 'c': 1, 'ca': 1, 'r': 1}, node_id)
        except Exception as e:
            return {'error': 'Mega API lỗi: {0}'.format(str(e))}

        if not isinstance(data, dict) or 'f' not in data:
            return {'error': 'Mega API trả về dữ liệu không hợp lệ.'}

        raw_nodes = data['f']
        nodes = []
        
        # Detect the root node of this shared folder structure.
        # The root node is either type 2 (root share), or a node whose parent is not in the list of returned nodes.
        node_ids = {n.get('h') for n in raw_nodes if n.get('h')}
        root_handle = None
        for n in raw_nodes:
            if n.get('t') == 2 or (n.get('p') not in node_ids):
                root_handle = n.get('h')
                break

        for node in raw_nodes:
            h = node.get('h', '')
            t = node.get('t', -1)
            s = node.get('s', 0)
            k_str = node.get('k', '')
            a_str = node.get('a', '')
            p = node.get('p', '')

            if t == 2:
                continue

            name = ''
            node_key_dec = []
            try:
                enc_key_b64 = ''
                if k_str:
                    parts = k_str.split('/')
                    for part in parts:
                        if ':' in part:
                            h_part, k_part = part.split(':', 1)
                            if h_part == root_handle:
                                enc_key_b64 = k_part
                                break
                    if not enc_key_b64:
                        first_part = parts[0]
                        enc_key_b64 = first_part.split(':', 1)[1] if ':' in first_part else first_part

                enc_key_bytes = self._b64_url_decode(enc_key_b64)
                enc_key_a32 = self._str_to_a32(enc_key_bytes)
                node_key_dec = self._decrypt_key(enc_key_a32, node_key)
                attrs = self._decrypt_attr(a_str, node_key_dec)
                name = attrs.get('n', '')
            except Exception:
                name = 'file_{0}'.format(h)

            nodes.append({
                'handle': h,
                'parent': p,
                'type': 'dir' if t == 1 else 'file',
                'name': self._safe_name(name) if name else 'file_{0}'.format(h),
                'size': s,
                'size_human': self._human_size(s) if s else '',
                'key_a32': node_key_dec,
            })

        # Build tree paths
        handle_map = {n['handle']: n for n in nodes}
        if root_handle:
            handle_map[root_handle] = {'handle': root_handle, 'type': 'root', 'name': '', 'parent': ''}

        def get_path(node):
            parts = []
            current = node
            seen = set()
            while current:
                if current['handle'] in seen:
                    break
                seen.add(current['handle'])
                if current.get('type') == 'root':
                    break
                parts.append(current['name'])
                current = handle_map.get(current.get('parent'))
            parts.reverse()
            return '/'.join(parts[:-1]) if len(parts) > 1 else ''

        # Find root folder name
        root_name = 'Mega Folder'
        for n in nodes:
            if n['parent'] == root_handle and n['type'] == 'dir':
                root_name = n['name']
                break
        if root_handle:
            for n in nodes:
                if n['parent'] == root_handle and n['type'] == 'file':
                    root_name = 'Mega Folder'
                    break

        files = []
        for n in nodes:
            if n['type'] == 'file':
                rel_dir = get_path(n)
                files.append({
                    'handle': n['handle'],
                    'name': n['name'],
                    'size': n['size'],
                    'size_human': n['size_human'],
                    'rel_dir': rel_dir,
                    'key_a32': n['key_a32'],
                })

        total_size = sum(f['size'] for f in files)
        return {
            'success': True,
            'folder_name': root_name,
            'folder_id': node_id,
            'folder_key': node_key,
            'file_count': len(files),
            'total_size': total_size,
            'total_size_human': self._human_size(total_size),
            'files': files,
        }

    # ==================== DOWNLOAD ====================

    def _get_download_url(self, node_handle, folder_id, is_file_only=False):
        """Get temporary download URL for a file node."""
        if is_file_only:
            data = self._api_request({'a': 'g', 'g': 1, 'p': node_handle})
        else:
            data = self._api_request({'a': 'g', 'g': 1, 'n': node_handle}, folder_id)
        if isinstance(data, dict) and 'g' in data:
            return data['g']
        if isinstance(data, int) and data == -18:
            raise Exception("Mega quota exceeded. Chờ vài giờ rồi thử lại.")
        raise Exception("Không lấy được link tải Mega: {0}".format(data))

    def _download_and_decrypt(self, dl_url, key_a32, dest_path, file_size=0):
        """Download file from Mega, decrypt with AES-CTR, save to disk."""
        # For file nodes with 8-int key: derive AES key and IV
        if len(key_a32) >= 8:
            aes_key = [key_a32[0] ^ key_a32[4], key_a32[1] ^ key_a32[5],
                       key_a32[2] ^ key_a32[6], key_a32[3] ^ key_a32[7]]
            iv = [key_a32[4], key_a32[5]]
        else:
            aes_key = list(key_a32[:4])
            iv = [0, 0]

        # Build AES-CTR cipher
        iv_bytes = self._a32_to_str(iv)
        initial_value = struct.unpack('>Q', iv_bytes)[0] << 64
        ctr = Counter.new(128, initial_value=initial_value)
        cipher = AES.new(self._a32_to_str(aes_key), AES.MODE_CTR, counter=ctr)

        dest_io = self._path_for_io(dest_path)
        os.makedirs(os.path.dirname(dest_io), exist_ok=True)

        self._response = requests.get(dl_url, stream=True, timeout=60,
                                      headers={'User-Agent': self.USER_AGENT})
        if not self._response.ok:
            raise Exception("Download HTTP {0}".format(self._response.status_code))

        downloaded = 0
        last_emit = 0
        with open(dest_io, 'wb') as f:
            for chunk in self._response.iter_content(chunk_size=self.CHUNK_SIZE):
                if self.stop_checker() or self._stopped:
                    return False
                if not chunk:
                    continue
                decrypted = cipher.decrypt(chunk)
                f.write(decrypted)
                downloaded += len(chunk)
                now = time.time()
                if now - last_emit >= 1:
                    pct = int(downloaded * 50 / file_size) if file_size else 5
                    pct = max(2, min(50, pct))
                    self._progress(pct, "Downloading: {0}".format(self._human_size(downloaded)))
                    last_emit = now

        # Truncate to actual file size (AES padding may add extra bytes)
        if file_size > 0:
            actual = os.path.getsize(dest_io)
            if actual > file_size:
                with open(dest_io, 'r+b') as f:
                    f.truncate(file_size)

        self._response = None
        return True

    # ==================== UPLOAD ====================

    def upload_to_drive(self, local_path, drive_dest):
        """Upload local file/dir to Google Drive via rclone/gclone."""
        binary = self._detect_binary()
        dest = drive_dest
        m = re.match(r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', drive_dest)
        if m:
            dest = "{0}:{{{1}}}{2}".format(m.group(1), m.group(2), m.group(3) or '')

        cmd = [binary, "copy", local_path, dest, "--verbose", "--stats=1s", "--stats-one-line"]
        sa_dir = self._get_sa_dir()
        if sa_dir:
            if self._is_team_drive_target(drive_dest):
                sa_count = len(glob.glob(os.path.join(sa_dir, '*.json')))
                cmd.extend(["--drive-service-account-file-path", sa_dir])
                self.log_callback(logging.INFO, "SA rotation enabled: {0} accounts in {1} (Shared Drive target)".format(sa_count, sa_dir))
            else:
                self.log_callback(logging.INFO, "Destination is Personal Google Drive (My Drive). SA rotation disabled to prevent Google API 403/404 quota errors.")

        self.log_callback(logging.INFO, "Uploading to Google Drive: {0}".format(dest))

        try:
            self._process = subprocess.Popen(
                self._cmd_for_subprocess(cmd),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
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
                        self.log_callback(logging.WARNING, "Upload stopped by user.")
                        self._process.terminate()
                        return False
                self._process.wait()
                if self._process.returncode == 0:
                    self.log_callback(logging.INFO, "Upload Google Drive OK!")
                    return True
                self.log_callback(logging.ERROR, "Rclone exit code {0}".format(self._process.returncode))
                return False
        except FileNotFoundError:
            self.log_callback(logging.ERROR, "gclone/rclone not found.")
            return False
        except Exception as e:
            self.log_callback(logging.ERROR, "Upload error: {0}".format(str(e)))
            return False
        finally:
            self._process = None

    def cleanup(self, path):
        try:
            path_io = self._path_for_io(path)
            if os.path.isfile(path_io):
                os.remove(path_io)
            elif os.path.isdir(path_io):
                shutil.rmtree(path_io, ignore_errors=True)
            self.log_callback(logging.INFO, "Cleaned: {0}".format(path))
        except Exception as e:
            self.log_callback(logging.WARNING, "Cleanup error: {0}".format(str(e)))

    # ==================== FULL PIPELINE ====================

    def run_full_pipeline(self, url, drive_dest):
        """Download entire Mega folder → upload to GDrive file by file."""
        self._stopped = False
        try:
            self.log_callback(logging.INFO, "=" * 50)
            self.log_callback(logging.INFO, "STEP 1/3: Fetching Mega folder info...")
            self._emit_state(status='fetching_info', phase='info')
            self._progress(0, "Reading Mega folder...")

            info = self.get_folder_info(url)
            if 'error' in info:
                self.log_callback(logging.ERROR, info['error'])
                return False

            files = info.get('files', [])
            total_items = len(files)
            folder_name = info.get('folder_name', 'Mega Folder')
            folder_id = info.get('folder_id', '')
            if not total_items:
                self.log_callback(logging.ERROR, "Folder is empty.")
                return False

            self._emit_state(total_items=total_items, current_index=0)
            self.log_callback(logging.INFO, "Folder: {0} ({1} files, {2})".format(
                folder_name, total_items, info.get('total_size_human', '')))

            # Check existing files on Google Drive destination to skip already completed ones
            self.log_callback(logging.INFO, "Checking existing files on Google Drive to enable resume...")
            existing_files = set()
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
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, stderr = p.communicate(timeout=30)
                if p.returncode == 0:
                    import json
                    data = json.loads(stdout.decode('utf-8', errors='replace'))
                    for item in data:
                        path = item.get('Path', '')
                        size = item.get('Size', 0)
                        if path:
                            norm_path = path.replace('\\', '/').strip('/')
                            existing_files.add((norm_path, size))
                    self.log_callback(logging.INFO, "Found {0} files already on GDrive destination.".format(len(existing_files)))
            except Exception as e:
                self.log_callback(logging.WARNING, "Cannot check existing files on GDrive: {0}".format(e))

            for index, fobj in enumerate(files, 1):
                if self.stop_checker() or self._stopped:
                    return False

                span = 100.0 / total_items
                self._progress_base = (index - 1) * span
                self._progress_span = span

                fname = fobj.get('name', 'file')
                fsize = fobj.get('size', 0)
                rel_dir = fobj.get('rel_dir', '')

                # Check if this file was already uploaded to GDrive
                if rel_dir:
                    rel_path = rel_dir.replace('\\', '/').strip('/') + '/' + fname
                else:
                    rel_path = fname
                rel_path_norm = rel_path.replace('\\', '/').strip('/')

                if (rel_path_norm, fsize) in existing_files:
                    self.log_callback(logging.INFO, "File {0}/{1}: {2} ({3}) - Already exists on GDrive, skipping.".format(
                        index, total_items, fname, fobj.get('size_human', '')))
                    self._progress(100, "Skipped (already exists)")
                    continue

                self._emit_state(current_index=index, total_items=total_items,
                                 file_name=fname, file_size=fsize,
                                 file_size_human=fobj.get('size_human', ''))
                self.log_callback(logging.INFO, "=" * 50)
                self.log_callback(logging.INFO, "File {0}/{1}: {2} ({3})".format(
                    index, total_items, fname, fobj.get('size_human', '')))

                # Step 2: Download + decrypt
                self.log_callback(logging.INFO, "STEP 2/3: Downloading from Mega...")
                self._emit_state(status='downloading', phase='download')

                try:
                    dl_url = self._get_download_url(fobj['handle'], folder_id, is_file_only=fobj.get('is_file_only', False))
                except Exception as e:
                    self.log_callback(logging.ERROR, str(e))
                    return False

                # Build local path preserving folder structure
                if rel_dir:
                    tmp_dir = os.path.join('/tmp', 'mega_dl', rel_dir)
                else:
                    tmp_dir = os.path.join('/tmp', 'mega_dl')
                local_path = os.path.join(tmp_dir, fname)

                try:
                    from pending_manager import save_pending_meta
                    save_pending_meta(tmp_dir, url=mega_url, file_name=fname,
                                      file_size=fsize, dest=drive_dest, engine='mega')
                except Exception:
                    pass

                # Step 2b: Check if file already fully downloaded on VPS
                local_path_io = self._path_for_io(local_path)
                skip_dl = False
                if fsize > 0 and os.path.exists(local_path_io):
                    if os.path.getsize(local_path_io) == fsize:
                        self.log_callback(logging.INFO,
                            "File already complete on VPS, skip Mega download.")
                        skip_dl = True

                if not skip_dl:
                    ok = self._download_and_decrypt(dl_url, fobj['key_a32'], local_path, fsize)
                    if not ok:
                        return False
                    self.log_callback(logging.INFO, "Downloaded to VPS: {0}".format(local_path))

                if self.stop_checker() or self._stopped:
                    return False

                # Step 3: Upload to GDrive
                self.log_callback(logging.INFO, "STEP 3/3: Uploading to Google Drive...")
                self._emit_state(status='uploading', phase='upload')
                self._progress(50, "Starting upload...")

                if rel_dir:
                    item_dest = drive_dest.rstrip('/') + '/' + rel_dir
                else:
                    item_dest = drive_dest

                success = self.upload_to_drive(local_path, item_dest)
                if not success:
                    return False

                # Cleanup this file immediately to save disk
                self.cleanup(local_path)

            # Final cleanup
            mega_tmp = '/tmp/mega_dl'
            if os.path.exists(mega_tmp):
                self.cleanup(mega_tmp)

            self._progress_base = 0
            self._progress_span = 100
            self._emit_state(status='done', phase='done',
                             current_index=total_items, total_items=total_items)
            self._progress(100, "Done!")
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
