import sys
import io
import os

# Set default encoding environment if not set
os.environ['LC_ALL'] = 'en_US.UTF-8'
os.environ['LANG'] = 'en_US.UTF-8'
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Force stdout/stderr to use UTF-8 regardless of locale
if hasattr(sys.stdout, 'buffer'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'buffer'):
    try:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

import threading
import logging
import json
import zipfile
import glob
import shutil
import time
import uuid
import re
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SA_DIR = os.path.join(BASE_DIR, 'sa')
HISTORY_FILE = os.path.join(BASE_DIR, 'history.json')
QUEUE_FILE = os.path.join(BASE_DIR, 'queue.json')
DEST_HISTORY_FILE = os.path.join(BASE_DIR, 'dest_history.json')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '28081988')
RCLONE_CONF_PATHS = [
    os.path.expanduser('~/.config/rclone/rclone.conf'),
    '/root/.config/rclone/rclone.conf',
]

def get_rclone_conf_path():
    for p in RCLONE_CONF_PATHS:
        if os.path.exists(p):
            return p
    default = RCLONE_CONF_PATHS[0]
    os.makedirs(os.path.dirname(default), exist_ok=True)
    return default

# Global state to track active download progress
download_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'file': '',
    'total_size': 0,
    'downloaded_size': 0,
    'logs': [],
    'files': [],
    'raw_urls': '',
    'output_dir': '',
    'job_id': None,
    'job_type': None
}

def sync_tool_progress_to_queue(tool_name, percent, message):
    if download_state.get('job_type') == tool_name and download_state.get('status') in ('downloading', 'initializing', 'waiting_cookie', 'waiting_ip'):
        download_state['progress'] = percent
        download_state['message'] = message
        if download_state['files']:
            download_state['files'][0]['progress'] = percent
            download_state['files'][0]['message'] = message
            if download_state['files'][0]['status'] not in ('waiting_cookie', 'waiting_ip'):
                download_state['files'][0]['status'] = 'downloading'

def sync_tool_state_update_to_queue(tool_name, values):
    if download_state.get('job_type') == tool_name and download_state.get('status') in ('downloading', 'initializing', 'waiting_cookie', 'waiting_ip'):
        if 'status' in values and values['status'] in ('waiting_cookie', 'waiting_ip', 'downloading'):
            download_state['status'] = values['status']
        if 'message' in values:
            download_state['message'] = values['message']
        if download_state['files']:
            if 'file_name' in values:
                download_state['files'][0]['name'] = values['file_name']
            if 'file_size_human' in values:
                download_state['files'][0]['message'] = "Size: {0}".format(values['file_size_human'])
            if 'status' in values and values['status'] in ('waiting_cookie', 'waiting_ip'):
                download_state['files'][0]['status'] = values['status']

def sync_tool_log_to_queue(tool_name, level, message):
    if download_state.get('job_type') == tool_name and download_state.get('status') in ('downloading', 'initializing', 'waiting_cookie', 'waiting_ip'):
        download_state['logs'].append({
            'level': logging.getLevelName(level),
            'message': "[{0}] {1}".format(tool_name.upper(), message)
        })
        if len(download_state['logs']) > 300:
            download_state['logs'] = download_state['logs'][-300:]

current_job_thread = None
stop_event = threading.Event()

verify_state = {
    'status': 'idle',
    'message': '',
    'stats': {
        'total_missing': 0,
        'total_differ': 0,
        'total_error': 0,
        'files': []
    }
}
verify_stop_event = threading.Event()

# ==================== QUEUE HELPERS ====================
def load_queue():
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []

def save_queue(q):
    try:
        with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(q, f, ensure_ascii=False)
    except Exception as e:
        print("Failed to save queue: {0}".format(e))

def detect_url_type(url):
    url_lower = url.lower().strip()
    if 'mediafire.com' in url_lower:
        return 'mediafire'
    if 'fshare.vn' in url_lower:
        return 'fshare'
    if 'mega.nz' in url_lower:
        return 'mega'
    if any(k in url_lower for k in [
        'terabox', '1024tera', 'nephobox', '4funbox', 'mirrobox', 'momerybox',
        'tibibox', 'tibabox', 'freeterabox', 'terasharelink', 'teraboxlink',
        'teraboxshare', 'dubox', 'momotera', 'miyauplat', 'funletu', 'ytbterabox'
    ]):
        return 'terabox'
    if any(dom in url_lower for dom in ['1fichier.com', '1fichier.fr', '1fichier.co', '1fichier.org', '1fichier.net']):
        return '1fichier'
    if 'pixeldrain.com' in url_lower:
        return 'pixeldrain'
    if any(k in url_lower for k in ['mypikpak.com', 'pikpak.me', 'mypikpak.net', 'api-drive.mypikpak.com']):
        return 'pikpak'
    if DowncodeEngine.is_downcode(url):
        return 'downcode'
    return 'rclone'

# ==================== BACKGROUND WORKER ====================
from rclone_engine import RcloneEngine
from downcode_engine import DowncodeEngine

def scrape_folder_name_from_url(url):
    """Helper to get folder name from GDrive page title."""
    try:
        import urllib.request
        # Strip tracking params
        clean_url = url.split('?')[0]
        logging.info(f"[WRAP] Scraping folder name from: {clean_url}")
        req = urllib.request.Request(clean_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        m = re.search(r'<title[^>]*>(.+?)</title>', html, re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()
            # Remove " - Google Drive" suffixes
            title = re.sub(r'\s*[-–]\s*Google\s+Drive\s*$', '', title, flags=re.I).strip()
            # Basic sanitization for paths
            title = re.sub(r'[\\/*?:"<>|]', '_', title)
            logging.info(f"[WRAP] Scraped folder name: '{title}'")
            return title
        logging.warning(f"[WRAP] No <title> tag found in page")
    except Exception as e:
        logging.warning(f"[WRAP] Scrape failed: {e}")
    return ""

def get_folder_name_via_rclone(gc_path):
    """Fallback: use rclone lsf to get folder name."""
    try:
        import subprocess
        rclone_bin = '/usr/bin/gclone'
        cmd = [rclone_bin, 'lsf', '--dirs-only', '-d', gc_path]
        cmd_bytes = [arg.encode('utf-8') if isinstance(arg, str) else arg for arg in cmd]
        # lsf -d shows the folder name itself
        result = subprocess.run(
            cmd_bytes,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15
        )
        name = result.stdout.decode('utf-8', errors='replace').strip().rstrip('/')
        if name:
            logging.info(f"[WRAP] rclone lsf got name: '{name}'")
            return re.sub(r'[\\/*?:"<>|]', '_', name)
        logging.warning(f"[WRAP] rclone lsf returned empty for {gc_path}")
    except Exception as e:
        logging.warning(f"[WRAP] rclone lsf failed: {e}")
    return ""

def run_real_rclone_job(job):
    global download_state, stop_event
    
    # Each job now only contains one source URL (split in start_download)
    source_list = [s.strip() for s in job['urls'].splitlines() if s.strip()]
    
    download_state.update({
        'status': 'initializing',
        'message': 'Initializing Rclone...',
        'progress': 0,
        'logs': [],
        'files': [{'path': src, 'name': src, 'status': 'pending', 'progress': 0, 'message': ''} for src in source_list],
        'raw_urls': job['urls'],
        'output_dir': job['dest'],
        'job_id': job['id']
    })
    
    stop_event.clear()
    quota_error_hit = False

    def progress_cb(percent, line):
        download_state['progress'] = percent
        download_state['message'] = line
        for f in download_state['files']:
            if f['status'] == 'pending' or f['status'] == 'downloading':
                f['status'] = 'downloading'
                f['progress'] = percent
                f['message'] = line
                break
        
    def log_cb(level, msg):
        nonlocal quota_error_hit
        if "downloadQuotaExceeded" in str(msg) or ("quota" in str(msg).lower() and "exceeded" in str(msg).lower()):
            quota_error_hit = True
        download_state['logs'].append({'level': logging.getLevelName(level), 'message': msg})
        if len(download_state['logs']) > 300:
            download_state['logs'] = download_state['logs'][-300:]
            
    def stop_check():
        return stop_event.is_set()
        
    engine = RcloneEngine(progress_cb, log_cb, stop_check)
    
    try:
        download_state['status'] = 'downloading'
        
        for i, src in enumerate(source_list):
            if stop_event.is_set() or quota_error_hit:
                break
            
            # Wrap parent logic: resolve folder name for wrapping
            final_dest = job['dest']
            if job.get('wrap'):
                folder_name = ""
                logging.info(f"[WRAP] Wrap=True for src={src}, original_url={job.get('original_url')}")
                
                # 1. Try scraping from original URL (src is gc:ID, not a URL)
                original_url = job.get('original_url', '')
                if original_url:
                    folder_name = scrape_folder_name_from_url(original_url)
                
                # 2. Fallback to rclone lsf -d
                if not folder_name:
                    folder_name = get_folder_name_via_rclone(src)
                
                # 3. Final fallback to engine.get_folder_name (lsjson)
                if not folder_name:
                    folder_name = engine.get_folder_name(src)
                
                logging.info(f"[WRAP] Resolved folder_name='{folder_name}' for {src}")
                if folder_name:
                    final_dest = final_dest.rstrip('/') + '/' + folder_name
            
            # Update recorder destination in state for final history recording
            download_state['output_dir'] = final_dest

            download_state['files'][i]['status'] = 'downloading'
            download_state['message'] = f"Copying to {final_dest}..."
            
            success = engine.run_copy(src, final_dest)
            
            if success and not quota_error_hit:
                download_state['files'][i]['status'] = 'completed'
                download_state['files'][i]['progress'] = 100
            else:
                download_state['files'][i]['status'] = 'stopped' if stop_event.is_set() else 'error'
                if not stop_event.is_set():
                    download_state['status'] = 'error'
                    download_state['message'] = f'Failed to copy {src}'
                    break
        else:
            if not stop_event.is_set() and not quota_error_hit and download_state['status'] != 'error':
                download_state['status'] = 'completed'
                download_state['message'] = 'Completed!'
                download_state['progress'] = 100
            
        return quota_error_hit

    except Exception as e:
        download_state['status'] = 'error'
        download_state['message'] = str(e)
        return False

def run_real_mediafire_job(job):
    global download_state, _mediafire_engine
    from mediafire_engine import MediaFireEngine
    
    download_state.update({
        'status': 'initializing',
        'message': 'Khởi tạo MediaFire...',
        'progress': 0,
        'logs': [],
        'files': [{'path': job['urls'], 'name': job['urls'], 'status': 'pending', 'progress': 0, 'message': ''}],
        'raw_urls': job['urls'],
        'output_dir': job['dest'],
        'job_id': job['id'],
        'job_type': 'mediafire'
    })
    
    mediafire_state.update({
        'status': 'fetching_info',
        'progress': 0,
        'message': 'Khởi tạo MediaFire...',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': 'info',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })
    
    _mediafire_engine = MediaFireEngine(_mediafire_progress, _mediafire_log, _mediafire_stop_checker, _mediafire_state_update)
    
    try:
        download_state['status'] = 'downloading'
        success = _mediafire_engine.run_full_pipeline(job['urls'], job['dest'])
        if _mediafire_stop_checker():
            mediafire_state['status'] = 'stopped'
            mediafire_state['message'] = 'Đã dừng bởi người dùng.'
            download_state['status'] = 'stopped'
            download_state['message'] = 'Đã dừng MediaFire job.'
        elif success:
            mediafire_state['status'] = 'done'
            mediafire_state['phase'] = 'done'
            mediafire_state['message'] = 'Hoàn tất! File từ MediaFire đã được copy lên Google Drive.'
            mediafire_state['progress'] = 100
            
            download_state['status'] = 'completed'
            download_state['message'] = 'Completed!'
            download_state['progress'] = 100
        else:
            mediafire_state['status'] = 'error'
            mediafire_state['phase'] = 'error'
            if not mediafire_state['message']:
                mediafire_state['message'] = 'Tải từ MediaFire thất bại.'
            download_state['status'] = 'error'
            download_state['message'] = mediafire_state['message']
    except Exception as e:
        mediafire_state['status'] = 'error'
        mediafire_state['phase'] = 'error'
        mediafire_state['message'] = 'Lỗi: {0}'.format(str(e))
        
        download_state['status'] = 'error'
        download_state['message'] = str(e)
        
    download_state['job_type'] = None
    return False

def run_real_fshare_job(job):
    global download_state, _fshare_engine
    from fshare_engine import FshareEngine
    
    download_state.update({
        'status': 'initializing',
        'message': 'Khởi tạo Fshare...',
        'progress': 0,
        'logs': [],
        'files': [{'path': job['urls'], 'name': job['urls'], 'status': 'pending', 'progress': 0, 'message': ''}],
        'raw_urls': job['urls'],
        'output_dir': job['dest'],
        'job_id': job['id'],
        'job_type': 'fshare'
    })
    
    fshare_state.update({
        'status': 'fetching_info',
        'progress': 0,
        'message': 'Khởi tạo Fshare...',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': 'info',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })
    
    config = _load_fshare_config(include_secret=True)
    _fshare_engine = FshareEngine(_fshare_progress, _fshare_log, _fshare_stop_checker, _fshare_state_update)
    
    try:
        download_state['status'] = 'downloading'
        success = _fshare_engine.run_full_pipeline(job['urls'], config, job['dest'], job.get('file_password', ''))
        if _fshare_stop_checker():
            fshare_state['status'] = 'stopped'
            fshare_state['message'] = 'Đã dừng bởi người dùng.'
            download_state['status'] = 'stopped'
            download_state['message'] = 'Đã dừng Fshare job.'
        elif success:
            fshare_state['status'] = 'done'
            fshare_state['phase'] = 'done'
            fshare_state['message'] = 'Hoàn tất! File Fshare đã được copy lên Google Drive.'
            fshare_state['progress'] = 100
            
            download_state['status'] = 'completed'
            download_state['message'] = 'Completed!'
            download_state['progress'] = 100
        else:
            fshare_state['status'] = 'error'
            fshare_state['phase'] = 'error'
            if not fshare_state['message']:
                fshare_state['message'] = 'Tải Fshare thất bại.'
            download_state['status'] = 'error'
            download_state['message'] = fshare_state['message']
    except Exception as e:
        fshare_state['status'] = 'error'
        fshare_state['phase'] = 'error'
        fshare_state['message'] = 'Lỗi: {0}'.format(str(e))
        
        download_state['status'] = 'error'
        download_state['message'] = str(e)
        
    download_state['job_type'] = None
    return False

def run_real_terabox_job(job):
    global download_state, _terabox_engine
    from terabox_engine import TeraboxEngine
    
    download_state.update({
        'status': 'initializing',
        'message': 'Khởi tạo Terabox...',
        'progress': 0,
        'logs': [],
        'files': [{'path': job['urls'], 'name': job['urls'], 'status': 'pending', 'progress': 0, 'message': ''}],
        'raw_urls': job['urls'],
        'output_dir': job['dest'],
        'job_id': job['id'],
        'job_type': 'terabox'
    })
    
    terabox_state.update({
        'status': 'fetching_info',
        'progress': 0,
        'message': 'Khởi tạo Terabox...',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': 'info',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })
    
    TERABOX_COOKIE_FILE = os.path.join(BASE_DIR, 'terabox_cookie.txt')
    if not os.path.exists(TERABOX_COOKIE_FILE):
        error_msg = 'Chưa cấu hình cookie Terabox.'
        terabox_state['status'] = 'error'
        terabox_state['message'] = error_msg
        download_state['status'] = 'error'
        download_state['message'] = error_msg
        download_state['job_type'] = None
        return False
        
    with open(TERABOX_COOKIE_FILE, 'r') as f:
        cookie = f.read().strip()
        
    if not cookie:
        error_msg = 'Cookie Terabox trống.'
        terabox_state['status'] = 'error'
        terabox_state['message'] = error_msg
        download_state['status'] = 'error'
        download_state['message'] = error_msg
        download_state['job_type'] = None
        return False
        
    _terabox_engine = TeraboxEngine(_terabox_progress, _terabox_log, _terabox_stop_checker, _terabox_state_update, cookie_file=TERABOX_COOKIE_FILE)
    
    try:
        download_state['status'] = 'downloading'
        success = _terabox_engine.run_full_pipeline(job['urls'], cookie, job['dest'])
        if _terabox_stop_checker():
            terabox_state['status'] = 'stopped'
            terabox_state['message'] = 'Đã dừng bởi người dùng.'
            download_state['status'] = 'stopped'
            download_state['message'] = 'Đã dừng Terabox job.'
        elif success:
            terabox_state['status'] = 'done'
            terabox_state['phase'] = 'done'
            terabox_state['message'] = 'Hoàn tất! File Terabox đã được copy lên Google Drive.'
            terabox_state['progress'] = 100
            
            download_state['status'] = 'completed'
            download_state['message'] = 'Completed!'
            download_state['progress'] = 100
        else:
            terabox_state['status'] = 'error'
            terabox_state['phase'] = 'error'
            if not terabox_state['message']:
                terabox_state['message'] = 'Tải Terabox thất bại.'
            download_state['status'] = 'error'
            download_state['message'] = terabox_state['message']
    except Exception as e:
        terabox_state['status'] = 'error'
        terabox_state['phase'] = 'error'
        terabox_state['message'] = 'Lỗi: {0}'.format(str(e))
        
        download_state['status'] = 'error'
        download_state['message'] = str(e)
        
    download_state['job_type'] = None
    return False

def run_real_mega_job(job):
    global download_state, _mega_engine
    from mega_engine import MegaEngine
    
    download_state.update({
        'status': 'initializing',
        'message': 'Khởi tạo Mega...',
        'progress': 0,
        'logs': [],
        'files': [{'path': job['urls'], 'name': job['urls'], 'status': 'pending', 'progress': 0, 'message': ''}],
        'raw_urls': job['urls'],
        'output_dir': job['dest'],
        'job_id': job['id'],
        'job_type': 'mega'
    })
    
    mega_state.update({
        'status': 'fetching_info',
        'progress': 0,
        'message': 'Khởi tạo Mega...',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': 'info',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })
    
    _mega_engine = MegaEngine(_mega_progress, _mega_log, _mega_stop_checker, _mega_state_update)
    
    try:
        download_state['status'] = 'downloading'
        success = _mega_engine.run_full_pipeline(job['urls'], job['dest'])
        if _mega_stop_checker():
            mega_state['status'] = 'stopped'
            mega_state['message'] = 'Đã dừng bởi người dùng.'
            download_state['status'] = 'stopped'
            download_state['message'] = 'Đã dừng Mega job.'
        elif success:
            mega_state['status'] = 'done'
            mega_state['phase'] = 'done'
            mega_state['message'] = 'Hoàn tất! File Mega đã được copy lên Google Drive.'
            mega_state['progress'] = 100
            
            download_state['status'] = 'completed'
            download_state['message'] = 'Completed!'
            download_state['progress'] = 100
        else:
            mega_state['status'] = 'error'
            mega_state['phase'] = 'error'
            if not mega_state['message']:
                mega_state['message'] = 'Tải Mega thất bại.'
            download_state['status'] = 'error'
            download_state['message'] = mega_state['message']
    except Exception as e:
        mega_state['status'] = 'error'
        mega_state['phase'] = 'error'
        mega_state['message'] = 'Lỗi: {0}'.format(str(e))
        
        download_state['status'] = 'error'
        download_state['message'] = str(e)
        
    download_state['job_type'] = None
    return False

def run_real_fichier_job(job):
    global download_state, _fichier_engine
    from fichier_engine import FichierEngine
    
    download_state.update({
        'status': 'initializing',
        'message': 'Khởi tạo 1fichier...',
        'progress': 0,
        'logs': [],
        'files': [{'path': job['urls'], 'name': job['urls'], 'status': 'pending', 'progress': 0, 'message': ''}],
        'raw_urls': job['urls'],
        'output_dir': job['dest'],
        'job_id': job['id'],
        'job_type': '1fichier'
    })
    
    fichier_state.update({
        'status': 'fetching_info',
        'progress': 0,
        'message': 'Khởi tạo 1fichier...',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': 'info',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })
    
    _fichier_engine = FichierEngine(_fichier_progress, _fichier_log, _fichier_stop_checker, _fichier_state_update)
    
    try:
        download_state['status'] = 'downloading'
        config = _load_fichier_config(include_secret=True)
        success = _fichier_engine.run_full_pipeline(job['urls'], config, job['dest'])
        if _fichier_stop_checker():
            fichier_state['status'] = 'stopped'
            fichier_state['message'] = 'Đã dừng bởi người dùng.'
            download_state['status'] = 'stopped'
            download_state['message'] = 'Đã dừng 1fichier job.'
        elif success:
            fichier_state['status'] = 'done'
            fichier_state['phase'] = 'done'
            fichier_state['message'] = 'Hoàn tất! File từ 1fichier đã được copy lên Google Drive.'
            fichier_state['progress'] = 100
            
            download_state['status'] = 'completed'
            download_state['message'] = 'Completed!'
            download_state['progress'] = 100
        else:
            fichier_state['status'] = 'error'
            fichier_state['phase'] = 'error'
            if not fichier_state['message']:
                fichier_state['message'] = 'Tải từ 1fichier thất bại.'
            download_state['status'] = 'error'
            download_state['message'] = fichier_state['message']
    except Exception as e:
        fichier_state['status'] = 'error'
        fichier_state['phase'] = 'error'
        fichier_state['message'] = 'Lỗi: {0}'.format(str(e))
        
        download_state['status'] = 'error'
        download_state['message'] = str(e)
        
    download_state['job_type'] = None
    return False


def run_real_pixeldrain_job(job):
    global download_state, _pixeldrain_engine
    from pixeldrain_engine import PixeldrainEngine
    
    download_state.update({
        'status': 'initializing',
        'message': 'Khởi tạo Pixeldrain...',
        'progress': 0,
        'logs': [],
        'files': [{'path': job['urls'], 'name': job['urls'], 'status': 'pending', 'progress': 0, 'message': ''}],
        'raw_urls': job['urls'],
        'output_dir': job['dest'],
        'job_id': job['id'],
        'job_type': 'pixeldrain'
    })
    
    pixeldrain_state.update({
        'status': 'fetching_info',
        'progress': 0,
        'message': 'Khởi tạo Pixeldrain...',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': 'info',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })
    
    _pixeldrain_engine = PixeldrainEngine(_pixeldrain_progress, _pixeldrain_log, _pixeldrain_stop_checker, _pixeldrain_state_update)
    
    try:
        download_state['status'] = 'downloading'
        config = _load_pixeldrain_config(include_secret=True)
        success = _pixeldrain_engine.run_full_pipeline(job['urls'], config, job['dest'])
        if _pixeldrain_stop_checker():
            pixeldrain_state['status'] = 'stopped'
            pixeldrain_state['message'] = 'Đã dừng bởi người dùng.'
            download_state['status'] = 'stopped'
            download_state['message'] = 'Đã dừng Pixeldrain job.'
        elif success:
            pixeldrain_state['status'] = 'done'
            pixeldrain_state['phase'] = 'done'
            pixeldrain_state['message'] = 'Hoàn tất! File từ Pixeldrain đã được copy lên Google Drive.'
            pixeldrain_state['progress'] = 100
            
            download_state['status'] = 'completed'
            download_state['message'] = 'Completed!'
            download_state['progress'] = 100
        else:
            pixeldrain_state['status'] = 'error'
            pixeldrain_state['phase'] = 'error'
            if not pixeldrain_state['message']:
                pixeldrain_state['message'] = 'Tải từ Pixeldrain thất bại.'
            download_state['status'] = 'error'
            download_state['message'] = pixeldrain_state['message']
    except Exception as e:
        pixeldrain_state['status'] = 'error'
        pixeldrain_state['phase'] = 'error'
        pixeldrain_state['message'] = 'Lỗi: {0}'.format(str(e))
        
        download_state['status'] = 'error'
        download_state['message'] = str(e)
        
    download_state['job_type'] = None
    return False


def run_real_pikpak_job(job):
    global download_state, _pikpak_engine
    from pikpak_engine import PikPakEngine
    
    download_state.update({
        'status': 'initializing',
        'message': 'Khởi tạo PikPak...',
        'progress': 0,
        'logs': [],
        'files': [{'path': job['urls'], 'name': job['urls'], 'status': 'pending', 'progress': 0, 'message': ''}],
        'raw_urls': job['urls'],
        'output_dir': job['dest'],
        'job_id': job['id'],
        'job_type': 'pikpak'
    })
    
    pikpak_state.update({
        'status': 'fetching_info',
        'progress': 0,
        'message': 'Khởi tạo PikPak...',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': 'info',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })
    
    _pikpak_engine = PikPakEngine(_pikpak_progress, _pikpak_log, _pikpak_stop_checker, _pikpak_state_update)
    
    try:
        download_state['status'] = 'downloading'
        config = _load_pikpak_config(include_secret=True)
        success = _pikpak_engine.run_full_pipeline(job['urls'], config, job['dest'], file_password=job.get('file_password', ''))
        if _pikpak_stop_checker():
            pikpak_state['status'] = 'stopped'
            pikpak_state['message'] = 'Đã dừng bởi người dùng.'
            download_state['status'] = 'stopped'
            download_state['message'] = 'Đã dừng PikPak job.'
        elif success:
            pikpak_state['status'] = 'done'
            pikpak_state['phase'] = 'done'
            pikpak_state['message'] = 'Hoàn tất! File từ PikPak đã được copy lên Google Drive.'
            pikpak_state['progress'] = 100
            
            download_state['status'] = 'completed'
            download_state['message'] = 'Completed!'
            download_state['progress'] = 100
        else:
            pikpak_state['status'] = 'error'
            pikpak_state['phase'] = 'error'
            err_msg = getattr(_pikpak_engine, '_last_error', '') or pikpak_state.get('message') or 'Tải từ PikPak thất bại.'
            pikpak_state['message'] = err_msg
            download_state['status'] = 'error'
            download_state['message'] = err_msg
    except Exception as e:
        pikpak_state['status'] = 'error'
        pikpak_state['phase'] = 'error'
        pikpak_state['message'] = 'Lỗi: {0}'.format(str(e))
        
        download_state['status'] = 'error'
        download_state['message'] = str(e)
        
    download_state['job_type'] = None
    return False


def run_real_downcode_job(job):
    global download_state
    from downcode_engine import DowncodeEngine

    code_input = job.get('urls', '')
    download_state.update({
        'status': 'initializing',
        'message': 'Đang giải mã DownCode: {0}...'.format(code_input),
        'progress': 0,
        'logs': [],
        'files': [{'path': code_input, 'name': code_input, 'status': 'pending', 'progress': 0, 'message': ''}],
        'raw_urls': code_input,
        'output_dir': job.get('dest', ''),
        'job_id': job.get('id', ''),
        'job_type': 'downcode'
    })

    logging.info("[DOWNCODE] Bắt đầu giải mã mã: %s", code_input)
    res = DowncodeEngine.resolve(code_input)
    if not res.get('success'):
        err_msg = res.get('error') or 'Giải mã DownCode thất bại.'
        download_state['status'] = 'error'
        download_state['message'] = 'Lỗi DownCode: {0}'.format(err_msg)
        logging.error("[DOWNCODE] Giải mã thất bại: %s", err_msg)
        download_state['job_type'] = None
        return False

    target_url = res.get('url')
    resolved_code = res.get('code') or code_input
    logging.info("[DOWNCODE] Giải mã thành công %s -> %s (host: %s)", resolved_code, target_url, res.get('text_note', ''))

    job['original_url'] = 'DownCode: {0}'.format(resolved_code)
    job['urls'] = target_url
    target_type = detect_url_type(target_url)
    job['type'] = target_type

    if target_type == 'rclone':
        if 'drive.google.com' in target_url:
            fid = extract_drive_id(target_url)
            if fid:
                job['urls'] = 'gc:{0}'.format(fid)
        return run_real_rclone_job(job)
    elif target_type == 'mediafire':
        return run_real_mediafire_job(job)
    elif target_type == 'fshare':
        return run_real_fshare_job(job)
    elif target_type == 'terabox':
        return run_real_terabox_job(job)
    elif target_type == 'mega':
        return run_real_mega_job(job)
    elif target_type == '1fichier':
        return run_real_fichier_job(job)
    elif target_type == 'pixeldrain':
        return run_real_pixeldrain_job(job)
    elif target_type == 'pikpak':
        return run_real_pikpak_job(job)
    else:
        return run_real_rclone_job(job)


def queue_worker_loop():
    global download_state
    while True:
        time.sleep(5)
        
        if download_state['status'] in ['downloading', 'initializing', 'waiting_cookie', 'waiting_ip']:
            continue
            
        q = load_queue()
        now = time.time()
        job_to_run = None
        
        for job in q:
            if job.get('execute_at', 0) <= now:
                job_to_run = job
                break
                
        if job_to_run:
            status_prev = download_state['status']
            job_type = job_to_run.get('type', 'rclone')
            
            if job_type == 'rclone':
                quota_hit = run_real_rclone_job(job_to_run)
            elif job_type == 'mediafire':
                quota_hit = run_real_mediafire_job(job_to_run)
            elif job_type == 'fshare':
                quota_hit = run_real_fshare_job(job_to_run)
            elif job_type == 'terabox':
                quota_hit = run_real_terabox_job(job_to_run)
            elif job_type == 'mega':
                quota_hit = run_real_mega_job(job_to_run)
            elif job_type == '1fichier':
                quota_hit = run_real_fichier_job(job_to_run)
            elif job_type == 'pixeldrain':
                quota_hit = run_real_pixeldrain_job(job_to_run)
            elif job_type == 'pikpak':
                quota_hit = run_real_pikpak_job(job_to_run)
            elif job_type == 'downcode':
                quota_hit = run_real_downcode_job(job_to_run)
            else:
                quota_hit = False
            
            q = load_queue()
            q = [j for j in q if j['id'] != job_to_run['id']]
            
            if quota_hit:
                job_to_run['status'] = 'delayed'
                job_to_run['execute_at'] = time.time() + (3 * 3600)
                q.append(job_to_run)
                download_state['status'] = 'error'
                download_state['message'] = 'Quota Exceeded. Dời lại 3 tiếng.'
            else:
                # Save to history
                try:
                    history_record = {
                        'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'urls': job_to_run.get('urls') or download_state.get('raw_urls', ''),
                        'dest': download_state.get('output_dir') or job_to_run.get('dest', ''),
                        'status': download_state.get('status', 'completed'),
                        'message': download_state.get('message', '')
                    }
                    histories = []
                    if os.path.exists(HISTORY_FILE):
                        try:
                            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                                histories = json.load(f)
                        except Exception:
                            histories = []
                    histories.append(history_record)
                    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                        json.dump(histories, f, ensure_ascii=False)
                except Exception as e:
                    print("Failed to save history: {0}".format(e))
            
            save_queue(q)
            time.sleep(5)
            download_state['status'] = 'idle'

# Start background worker
worker_thread = threading.Thread(target=queue_worker_loop, daemon=True)
worker_thread.start()

# ==================== TRANSFER API ====================

@app.route('/api/stop', methods=['POST'])
def stop_download():
    global stop_event, _terabox_engine, _fshare_engine, _mediafire_engine, _mega_engine, _fichier_engine, _pixeldrain_engine, _pikpak_engine
    if download_state['status'] in ['downloading', 'initializing', 'waiting_cookie', 'waiting_ip']:
        stop_event.set()
        
        terabox_state['stop_flag'] = True
        if _terabox_engine:
            try:
                _terabox_engine.stop()
            except:
                pass
                
        fshare_state['stop_flag'] = True
        if _fshare_engine:
            try:
                _fshare_engine.stop()
            except:
                pass
                
        mediafire_state['stop_flag'] = True
        if _mediafire_engine:
            try:
                _mediafire_engine.stop()
            except:
                pass
                
        mega_state['stop_flag'] = True
        if _mega_engine:
            try:
                _mega_engine.stop()
            except:
                pass
                
        fichier_state['stop_flag'] = True
        if _fichier_engine:
            try:
                _fichier_engine.stop()
            except:
                pass
                
        pixeldrain_state['stop_flag'] = True
        if _pixeldrain_engine:
            try:
                _pixeldrain_engine.stop()
            except:
                pass

        pikpak_state['stop_flag'] = True
        if _pikpak_engine:
            try:
                _pikpak_engine.stop()
            except:
                pass
                
        return jsonify({'message': 'Stopping process...'})
    return jsonify({'message': 'No process running'})

@app.route('/api/clear_temp', methods=['POST'])
def clear_temp():
    global stop_event, _terabox_engine, _fshare_engine, _mediafire_engine, _mega_engine, _fichier_engine, _pixeldrain_engine, _pikpak_engine
    # 1. Stop any currently running task
    stop_event.set()
    terabox_state['stop_flag'] = True
    if _terabox_engine:
        try: _terabox_engine.stop()
        except: pass
        
    fshare_state['stop_flag'] = True
    if _fshare_engine:
        try: _fshare_engine.stop()
        except: pass
        
    mediafire_state['stop_flag'] = True
    if _mediafire_engine:
        try: _mediafire_engine.stop()
        except: pass
        
    mega_state['stop_flag'] = True
    if _mega_engine:
        try: _mega_engine.stop()
        except: pass
        
    fichier_state['stop_flag'] = True
    if _fichier_engine:
        try: _fichier_engine.stop()
        except: pass
        
    pixeldrain_state['stop_flag'] = True
    if _pixeldrain_engine:
        try: _pixeldrain_engine.stop()
        except: pass

    pikpak_state['stop_flag'] = True
    if _pikpak_engine:
        try: _pikpak_engine.stop()
        except: pass
        
    # 2. Delete all temp folders
    deleted_paths = []
    for path, name in [
        (TERABOX_TMP_ROOT, 'Terabox'),
        (FSHARE_TMP_ROOT, 'Fshare'),
        (MEDIAFIRE_TMP_ROOT, 'MediaFire'),
        (MEGA_TMP_ROOT, 'Mega'),
        (FICHIER_TMP_ROOT, '1fichier'),
        (PIXELDRAIN_TMP_ROOT, 'Pixeldrain'),
        (PIKPAK_TMP_ROOT, 'PikPak')
    ]:
        if os.path.exists(path):
            try:
                shutil.rmtree(path, ignore_errors=True)
                deleted_paths.append(name)
            except Exception as e:
                logging.error("Error clearing {0} temp path: {1}".format(name, e))
                
    # 3. Reset states to idle
    _reset_terabox_state()
    _reset_fshare_state()
    _reset_mediafire_state()
    _reset_mega_state()
    _reset_fichier_state()
    _reset_pixeldrain_state()
    _reset_pikpak_state()
    
    # 4. Clear queue
    try:
        save_queue([])
    except Exception as e:
        logging.error("Error clearing queue on clear_temp: {0}".format(e))
        
    if deleted_paths:
        msg = "Đã dừng tiến trình và xóa thư mục tạm: {0}.".format(', '.join(deleted_paths))
    else:
        msg = "Đã dừng tiến trình và dọn dẹp trạng thái (không có thư mục tạm nào cần xóa)."
        
    return jsonify({'success': True, 'message': msg})


@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
        
    raw_text = data.get('url', '')
    output_dir_raw = data.get('output_dir', '')
    wrap = data.get('wrap', False)
    
    if not raw_text or not output_dir_raw:
        return jsonify({'error': 'Source and Destination are required'}), 400

    # Clean destination: normalize multiple/double slashes and keep nested paths
    dest_cleaned = output_dir_raw.strip()
    if 'drive.google.com' in dest_cleaned:
        fid = extract_drive_id(dest_cleaned)
        if fid: dest_cleaned = f'gc:{fid}'
    else:
        if ':' in dest_cleaned:
            parts = dest_cleaned.split(':', 1)
            remote = parts[0].strip()
            path = parts[1].strip()
            path = re.sub(r'/+', '/', path).strip('/')
            if path:
                dest_cleaned = f"{remote}:{path}"
            else:
                dest_cleaned = f"{remote}:"

    file_password = data.get('file_password', data.get('password', ''))

    q = load_queue()
    
    # Split by lines first, then process each line
    lines = [u.strip() for u in raw_text.splitlines() if u.strip()]
    links = []
    for line in lines:
        # If it's a Drive URL, extract just the URL part (strip ?fbclid etc)
        if 'drive.google.com' in line:
            links.append(line)
        elif line.startswith('gc:') or ':' in line or DowncodeEngine.is_downcode(line):
            # Already rclone format, URL with protocol, or DownCode code/link
            links.append(line)
    
    if not links and raw_text.strip():
        links = lines

    added_count = 0
    for line in links:
        source_path = line
        original_url = None
        
        job_type = detect_url_type(line)
        
        if job_type == 'downcode':
            res = DowncodeEngine.resolve(line)
            if res.get('success'):
                target_url = res.get('url')
                code_str = res.get('code') or line
                original_url = 'DownCode: {0}'.format(code_str)
                line = target_url
                source_path = target_url
                job_type = detect_url_type(target_url)
            else:
                original_url = 'DownCode: {0}'.format(line)
        
        if job_type == 'rclone':
            # Normalize source
            if 'drive.google.com' in line:
                if not original_url:
                    original_url = line
                fid = extract_drive_id(line)
                if fid:
                    source_path = 'gc:{0}'.format(fid)
        
        job = {
            'id': str(uuid.uuid4()),
            'urls': source_path,
            'original_url': original_url,
            'dest': dest_cleaned,
            'wrap': wrap,
            'type': job_type,
            'status': 'waiting',
            'execute_at': time.time() - 1,
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        if file_password:
            job['file_password'] = file_password
            
        q.append(job)
        added_count += 1
    
    save_queue(q)
    return jsonify({'message': 'Đã thêm {0} job vào hàng đợi!'.format(added_count)})

@app.route('/api/status', methods=['GET'])
def get_status():
    st = dict(download_state)
    q = load_queue()
    st['queue_count'] = len(q)
    return jsonify(st)

@app.route('/api/queue', methods=['GET'])
def get_queue():
    q = load_queue()
    return jsonify(q)

@app.route('/api/queue/remove', methods=['POST'])
def queue_remove():
    data = request.get_json(force=True, silent=True)
    job_id = data.get('id')
    q = load_queue()
    q = [j for j in q if j['id'] != job_id]
    save_queue(q)
    return jsonify({'message': 'Removed from queue'})

# ==================== VERIFY API ====================
def run_verify_job(source, dest):
    global verify_state, verify_stop_event
    
    verify_state['status'] = 'verifying'
    verify_state['message'] = f'Đang quét đối chiếu giữa {source} và {dest}...'
    verify_state['stats'] = {'total_missing': 0, 'total_differ': 0, 'total_error': 0, 'files': []}
    
    verify_stop_event.clear()
    
    def log_cb(level, msg):
        verify_state['message'] = str(msg)
        
    def stop_check():
        return verify_stop_event.is_set()
        
    def verify_cb(success, stats, err_msg=""):
        verify_state['stats'] = stats
        if success:
            verify_state['status'] = 'completed'
            verify_state['message'] = f"Hoàn thành kiểm tra. Thiếu {stats['total_missing']}, Lệch size {stats['total_differ']}."
        else:
            verify_state['status'] = 'error'
            verify_state['message'] = err_msg or "Có lỗi xảy ra"

    def prog_cb(pct, line):
        pass

    engine = RcloneEngine(prog_cb, log_cb, stop_check)
    engine.run_verify(source, dest, verify_cb)

@app.route('/api/verify', methods=['POST'])
def start_verify():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON data'}), 400
        
    source = data.get('source', '')
    dest = data.get('dest', '')
    
    if not source or not dest:
        return jsonify({'error': 'Source and Destination are required'}), 400
        
    if verify_state['status'] == 'verifying':
        return jsonify({'error': 'Một tiến trình kiểm tra đang chạy.'}), 400
        
    t = threading.Thread(target=run_verify_job, args=(source, dest), daemon=True)
    t.start()
    
    return jsonify({'message': 'Đã bắt đầu quét đối chiếu!'})

@app.route('/api/verify/status', methods=['GET'])
def get_verify_status():
    return jsonify(verify_state)

@app.route('/api/verify/stop', methods=['POST'])
def stop_verify():
    if verify_state['status'] == 'verifying':
        verify_stop_event.set()
        return jsonify({'message': 'Đang dừng...'})
    return jsonify({'message': 'Không có tiến trình nào đang chạy'})

# ==================== HISTORY API ====================
@app.route('/api/history', methods=['GET'])
def get_history():
    histories = []
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                histories = json.load(f)
    except Exception as e:
        print("Error reading history: {0}".format(e))
        
    if download_state.get('status') in ('downloading', 'initializing'):
        active_record = {
            'time': 'Đang chạy...',
            'urls': download_state.get('raw_urls', ''),
            'dest': download_state.get('output_dir', ''),
            'status': download_state.get('status', ''),
            'message': download_state.get('message', ''),
            'progress': download_state.get('progress', 0)
        }
        histories.append(active_record)
        
    return jsonify(list(reversed(histories)))

@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
    return jsonify({'message': 'History cleared'})

# ==================== CONFIG API ====================
@app.route('/api/config', methods=['GET'])
def get_config():
    conf_path = get_rclone_conf_path()
    try:
        if os.path.exists(conf_path):
            with open(conf_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        else:
            content = ''
        return jsonify({'content': content, 'path': conf_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['POST'])
def save_config():
    data = request.get_json(force=True, silent=True)
    if not data or 'content' not in data:
        return jsonify({'error': 'Missing content'}), 400
    
    conf_path = get_rclone_conf_path()
    try:
        os.makedirs(os.path.dirname(conf_path), exist_ok=True)
        with open(conf_path, 'w', encoding='utf-8') as f:
            f.write(data['content'])
        return jsonify({'message': 'Config saved', 'path': conf_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== SERVICE ACCOUNT API ====================
@app.route('/api/sa/upload', methods=['POST'])
def upload_sa():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Empty filename'}), 400
    os.makedirs(SA_DIR, exist_ok=True)
    try:
        if f.filename.endswith('.zip'):
            tmp_path = os.path.join(SA_DIR, '_upload.zip')
            f.save(tmp_path)
            with zipfile.ZipFile(tmp_path, 'r') as zf:
                json_count = 0
                for name in zf.namelist():
                    if name.endswith('.json') and not name.startswith('__MACOSX'):
                        basename = os.path.basename(name)
                        if basename:
                            target = os.path.join(SA_DIR, basename)
                            with zf.open(name) as src, open(target, 'wb') as dst:
                                dst.write(src.read())
                            json_count += 1
            os.remove(tmp_path)
            return jsonify({'message': f'Extracted {json_count} SA files', 'count': json_count})
        elif f.filename.endswith('.json'):
            f.save(os.path.join(SA_DIR, f.filename))
            return jsonify({'message': f'Uploaded {f.filename}', 'count': 1})
        return jsonify({'error': 'Invalid format'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sa/info', methods=['GET'])
def sa_info():
    sa_files = sorted(glob.glob(os.path.join(SA_DIR, '*.json')))
    return jsonify({'count': len(sa_files), 'files': [os.path.basename(f) for f in sa_files[:20]]})

@app.route('/api/sa/clear', methods=['POST'])
def clear_sa():
    if os.path.exists(SA_DIR):
        shutil.rmtree(SA_DIR)
        os.makedirs(SA_DIR, exist_ok=True)
    return jsonify({'message': 'Cleared'})

# ==================== AUTH API ====================
@app.route('/api/auth', methods=['POST'])
def auth_check():
    data = request.get_json(force=True, silent=True)
    pw = data.get('password', '') if data else ''
    if pw == ADMIN_PASSWORD:
        return jsonify({'success': True})
    return jsonify({'success': False}), 401

# ==================== UTILITY APIs ====================
def extract_drive_id(url):
    url = url.split('?')[0].split('#')[0]
    m = re.search(r'/folders/([A-Za-z0-9_-]{15,})', url)
    if m: return m.group(1)
    m = re.search(r'/d/([A-Za-z0-9_-]{15,})', url)
    if m: return m.group(1)
    m = re.search(r'[?&]id=([A-Za-z0-9_-]{15,})', url)
    if m: return m.group(1)
    return None

@app.route('/api/util/scrape_title', methods=['GET'])
def scrape_title_api():
    url = request.args.get('url', '')
    title = scrape_folder_name_from_url(url)
    return jsonify({'title': title})

@app.route('/api/util/parse_url', methods=['POST'])
def parse_url():
    data = request.get_json(force=True, silent=True)
    raw = data.get('url', '') if data else ''
    remote = data.get('remote', 'gc') if data else 'gc'
    results = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line: continue
        if DowncodeEngine.is_downcode(line):
            res = DowncodeEngine.resolve(line)
            if res.get('success'):
                target = res.get('url')
                fid = extract_drive_id(target)
                if fid:
                    results.append({'original': line, 'parsed': '{0}:{1}'.format(remote, fid), 'id': fid, 'target': target, 'resolved': True})
                else:
                    results.append({'original': line, 'parsed': target, 'id': None, 'target': target, 'resolved': True})
                continue
        if 'drive.google.com' in line:
            fid = extract_drive_id(line)
            if fid: results.append({'original': line, 'parsed': '{0}:{1}'.format(remote, fid), 'id': fid})
            else: results.append({'original': line, 'parsed': line, 'id': None})
        else:
            results.append({'original': line, 'parsed': line, 'id': None})
    return jsonify({'results': results})

# --- Explorer & Meta ---
def _make_engine():
    return RcloneEngine(lambda p, l: None, lambda lv, m: None, lambda: False)

@app.route('/api/explore', methods=['GET'])
def explore_drive():
    path = request.args.get('path', 'gc:')
    engine = _make_engine()
    items = engine.list_dir(path, dirs_only=True)
    # If no items found, try without --dirs-only to see if there's anything at all
    if not items:
        all_items = engine.list_dir(path, dirs_only=False)
        # Return debug info
        if request.args.get('debug'):
            return jsonify({
                'dirs': items,
                'all_items': len(all_items),
                'sa_dir': engine._get_sa_dir(),
                'config': engine._get_config_path(),
                'binary': engine._detect_binary(),
                'cmd': getattr(engine, '_last_cmd', ''),
                'stderr': getattr(engine, '_last_stderr', '')
            })
        # Filter to directories only from full listing
        items = [i for i in all_items if i.get('IsDir')]
    return jsonify(items)

@app.route('/api/mkdir', methods=['POST'])
def mkdir_drive():
    data = request.get_json(force=True, silent=True)
    path = data.get('path', '')
    if not path: return jsonify({'error': 'Missing path'}), 400
    if _make_engine().make_dir(path): return jsonify({'success': True})
    return jsonify({'error': 'Failed'}), 500

@app.route('/api/util/folder_name', methods=['GET'])
def get_folder_name_api():
    path = request.args.get('path', '')
    if not path: return jsonify({'name': ''}), 400
    name = _make_engine().get_folder_name(path)
    return jsonify({'name': name})

def _resolve_folder_name(gc_path):
    """Resolve a gc:ID path to its actual Google Drive folder name."""
    try:
        import subprocess
        rclone_bin = '/usr/bin/gclone'
        # Prepare the path with curly braces for gclone
        prepared = gc_path
        m = re.match(r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', gc_path)
        if m:
            prepared = f"{m.group(1)}:{{{m.group(2)}}}{m.group(3) or ''}"
        cmd = [rclone_bin, 'lsf', '--dirs-only', '-d', prepared]
        cmd_bytes = [arg.encode('utf-8') if isinstance(arg, str) else arg for arg in cmd]
        result = subprocess.run(
            cmd_bytes,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
        )
        name = result.stdout.decode('utf-8', errors='replace').strip().rstrip('/')
        if name:
            return name
    except Exception as e:
        logging.warning(f"[DEST_HISTORY] Folder name resolve failed: {e}")
    return ""

@app.route('/api/dest_history', methods=['GET', 'POST', 'DELETE'])
def handle_dest_history():
    if request.method == 'DELETE':
        data = request.get_json(force=True, silent=True)
        path = data.get('path') if data else None
        if not path: return jsonify({'error': 'Missing path'}), 400
        history = []
        if os.path.exists(DEST_HISTORY_FILE):
            try:
                with open(DEST_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except: pass
        history = [h for h in history if h.get('path') != path]
        with open(DEST_HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(history, f, ensure_ascii=False)
        return jsonify({'message': 'Deleted'})

    if request.method == 'POST':
        data = request.get_json(force=True, silent=True)
        path = data.get('path') if data else None
        if not path: return jsonify({'error': 'Missing path'}), 400
        history = []
        if os.path.exists(DEST_HISTORY_FILE):
            try:
                with open(DEST_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except: pass
        # Resolve folder name
        name = data.get('name', '')
        if not name or name == path:
            name = _resolve_folder_name(path)
        history = [h for h in history if h.get('path') != path]
        history.insert(0, {
            'path': path,
            'name': name or '',
            'used_at': datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        history = history[:20]
        with open(DEST_HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(history, f, ensure_ascii=False)
        return jsonify({'message': 'Saved'})
    else:
        if os.path.exists(DEST_HISTORY_FILE):
            try:
                with open(DEST_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                # Auto-resolve missing names for old entries
                updated = False
                for h in history:
                    if not h.get('name'):
                        resolved = _resolve_folder_name(h['path'])
                        if resolved:
                            h['name'] = resolved
                            updated = True
                if updated:
                    with open(DEST_HISTORY_FILE, 'w', encoding='utf-8') as f:
                        json.dump(history, f, ensure_ascii=False)
                return jsonify(history)
            except: pass
        return jsonify([])

@app.route('/')
def index():
    return render_template('index.html')

@app.errorhandler(500)
def handle_500(e):
    import traceback
    return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ==================== TERABOX MODULE (Completely Isolated) ====================
from terabox_engine import TeraboxEngine

TERABOX_COOKIE_FILE = os.path.join(BASE_DIR, 'terabox_cookie.txt')
TERABOX_TMP_ROOT = '/tmp/terabox_dl'
FSHARE_CONFIG_FILE = os.path.join(BASE_DIR, 'fshare_config.json')
FSHARE_TMP_ROOT = '/tmp/fshare_dl'
MEDIAFIRE_TMP_ROOT = '/tmp/mediafire_dl'

terabox_state = {
    'status': 'idle',
    'progress': 0,
    'message': '',
    'file_name': '',
    'file_size': 0,
    'file_size_human': '',
    'phase': '',
    'logs': [],
    'stop_flag': False,
    'current_index': 0,
    'total_items': 0
}
_terabox_engine = None


def _reset_terabox_state():
    terabox_state.update({
        'status': 'idle',
        'progress': 0,
        'message': '',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': '',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })


def _terabox_progress(percent, message):
    terabox_state['progress'] = percent
    terabox_state['message'] = message
    sync_tool_progress_to_queue('terabox', percent, message)


def _terabox_state_update(values):
    for key, value in values.items():
        if key in terabox_state:
            terabox_state[key] = value
    sync_tool_state_update_to_queue('terabox', values)


def _terabox_log(level, message):
    terabox_state['logs'].append({
        'time': datetime.now().strftime('%H:%M:%S'),
        'level': logging.getLevelName(level),
        'msg': message
    })
    if len(terabox_state['logs']) > 200:
        terabox_state['logs'] = terabox_state['logs'][-200:]
    logging.log(level, "[TERABOX] %s", message)
    sync_tool_log_to_queue('terabox', level, message)


def _terabox_stop_checker():
    return terabox_state.get('stop_flag', False)


@app.route('/api/terabox/cookie', methods=['GET', 'POST'])
def terabox_cookie():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        cookie_val = data.get('cookie', '').strip()
        if not cookie_val:
            return jsonify({'success': False, 'error': 'Cookie không được để trống'})
        try:
            with open(TERABOX_COOKIE_FILE, 'w', encoding='utf-8') as f:
                f.write(cookie_val)
            return jsonify({'success': True, 'message': 'Cookie đã lưu thành công'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    else:
        if os.path.exists(TERABOX_COOKIE_FILE):
            try:
                with open(TERABOX_COOKIE_FILE, 'r', encoding='utf-8') as f:
                    val = f.read().strip()
                if val:
                    # Mask cookie for display
                    if len(val) > 16:
                        masked = val[:8] + '...' + val[-8:]
                    else:
                        masked = '***'
                    return jsonify({'has_cookie': True, 'masked': masked})
            except Exception:
                pass
        return jsonify({'has_cookie': False})


# Removed obsolete individual Terabox routes


# ==================== FSHARE MODULE (Completely Isolated) ====================
from fshare_engine import FshareEngine

fshare_state = {
    'status': 'idle',
    'progress': 0,
    'message': '',
    'file_name': '',
    'file_size': 0,
    'file_size_human': '',
    'phase': '',
    'logs': [],
    'stop_flag': False,
    'current_index': 0,
    'total_items': 0
}
_fshare_engine = None


def _mask_secret(value):
    value = (value or '').strip()
    if not value:
        return ''
    if len(value) <= 8:
        return '***'
    return value[:4] + '...' + value[-4:]


def _load_fshare_config(include_secret=True):
    config = {
        'email': os.environ.get('FSHARE_USER_EMAIL', ''),
        'password': os.environ.get('FSHARE_PASSWORD', ''),
        'app_key': os.environ.get('FSHARE_APP_KEY', ''),
        'user_agent': os.environ.get('FSHARE_USER_AGENT', ''),
    }
    if os.path.exists(FSHARE_CONFIG_FILE):
        try:
            with open(FSHARE_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            for key in config:
                if saved.get(key):
                    config[key] = saved.get(key)
        except Exception:
            pass
    if not include_secret:
        return {
            'email': config.get('email', ''),
            'has_password': bool(config.get('password')),
            'password_masked': _mask_secret(config.get('password', '')),
            'complete': all(config.get(k) for k in ['email', 'password'])
        }
    return config


def _save_fshare_config(data):
    current = _load_fshare_config(include_secret=True)
    for key in ['email', 'password']:
        if key in data:
            val = (data.get(key) or '').strip()
            if key == 'password' and val == '__KEEP__':
                continue
            current[key] = val
    with open(FSHARE_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False)
    return current


def _reset_fshare_state():
    fshare_state.update({
        'status': 'idle',
        'progress': 0,
        'message': '',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': '',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })


def _fshare_progress(percent, message):
    fshare_state['progress'] = percent
    fshare_state['message'] = message
    sync_tool_progress_to_queue('fshare', percent, message)


def _fshare_state_update(values):
    for key, value in values.items():
        if key in fshare_state:
            fshare_state[key] = value
    sync_tool_state_update_to_queue('fshare', values)


def _fshare_log(level, message):
    fshare_state['logs'].append({
        'time': datetime.now().strftime('%H:%M:%S'),
        'level': logging.getLevelName(level),
        'msg': message
    })
    if len(fshare_state['logs']) > 200:
        fshare_state['logs'] = fshare_state['logs'][-200:]
    logging.log(level, "[FSHARE] %s", message)
    sync_tool_log_to_queue('fshare', level, message)


def _fshare_stop_checker():
    return fshare_state.get('stop_flag', False)


@app.route('/api/fshare/config', methods=['GET', 'POST'])
def fshare_config():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        try:
            config = _save_fshare_config(data)
            complete = all(config.get(k) for k in ['email', 'password'])
            return jsonify({'success': True, 'complete': complete, 'message': 'Đã lưu cấu hình Fshare'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify(_load_fshare_config(include_secret=False))


# Removed obsolete individual Fshare routes


# ==================== MEDIAFIRE MODULE (Completely Isolated) ====================
from mediafire_engine import MediaFireEngine

mediafire_state = {
    'status': 'idle',
    'progress': 0,
    'message': '',
    'file_name': '',
    'file_size': 0,
    'file_size_human': '',
    'phase': '',
    'logs': [],
    'stop_flag': False,
    'current_index': 0,
    'total_items': 0
}
_mediafire_engine = None


def _reset_mediafire_state():
    mediafire_state.update({
        'status': 'idle',
        'progress': 0,
        'message': '',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': '',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })


def _mediafire_progress(percent, message):
    mediafire_state['progress'] = percent
    mediafire_state['message'] = message
    sync_tool_progress_to_queue('mediafire', percent, message)


def _mediafire_state_update(values):
    for key, value in values.items():
        if key in mediafire_state:
            mediafire_state[key] = value
    sync_tool_state_update_to_queue('mediafire', values)


def _mediafire_log(level, message):
    mediafire_state['logs'].append({
        'time': datetime.now().strftime('%H:%M:%S'),
        'level': logging.getLevelName(level),
        'msg': message
    })
    if len(mediafire_state['logs']) > 200:
        mediafire_state['logs'] = mediafire_state['logs'][-200:]
    logging.log(level, "[MEDIAFIRE] %s", message)
    sync_tool_log_to_queue('mediafire', level, message)


def _mediafire_stop_checker():
    return mediafire_state.get('stop_flag', False)


# Removed obsolete individual MediaFire routes


# ==================== MEGA MODULE (Completely Isolated) ====================
from mega_engine import MegaEngine

MEGA_TMP_ROOT = '/tmp/mega_dl'

mega_state = {
    'status': 'idle',
    'progress': 0,
    'message': '',
    'file_name': '',
    'file_size': 0,
    'file_size_human': '',
    'phase': '',
    'logs': [],
    'stop_flag': False,
    'current_index': 0,
    'total_items': 0
}
_mega_engine = None


def _reset_mega_state():
    mega_state.update({
        'status': 'idle',
        'progress': 0,
        'message': '',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': '',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })


def _mega_progress(percent, message):
    mega_state['progress'] = percent
    mega_state['message'] = message
    sync_tool_progress_to_queue('mega', percent, message)


def _mega_state_update(values):
    for key, value in values.items():
        if key in mega_state:
            mega_state[key] = value
    sync_tool_state_update_to_queue('mega', values)


def _mega_log(level, message):
    mega_state['logs'].append({
        'time': datetime.now().strftime('%H:%M:%S'),
        'level': logging.getLevelName(level),
        'msg': message
    })
    if len(mega_state['logs']) > 200:
        mega_state['logs'] = mega_state['logs'][-200:]
    logging.log(level, "[MEGA] %s", message)
    sync_tool_log_to_queue('mega', level, message)


def _mega_stop_checker():
    return mega_state.get('stop_flag', False)


# Removed obsolete individual Mega routes


# ==================== FICHIER MODULE (Completely Isolated) ====================
from fichier_engine import FichierEngine

FICHIER_CONFIG_FILE = os.path.join(BASE_DIR, 'fichier_config.json')
FICHIER_TMP_ROOT = '/tmp/fichier_dl'

fichier_state = {
    'status': 'idle',
    'progress': 0,
    'message': '',
    'file_name': '',
    'file_size': 0,
    'file_size_human': '',
    'phase': '',
    'logs': [],
    'stop_flag': False,
    'current_index': 0,
    'total_items': 0
}
_fichier_engine = None


def _reset_fichier_state():
    fichier_state.update({
        'status': 'idle',
        'progress': 0,
        'message': '',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': '',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })


def _fichier_progress(percent, message):
    fichier_state['progress'] = percent
    fichier_state['message'] = message
    sync_tool_progress_to_queue('1fichier', percent, message)


def _fichier_state_update(values):
    for key, value in values.items():
        if key in fichier_state:
            fichier_state[key] = value
    sync_tool_state_update_to_queue('1fichier', values)


def _fichier_log(level, message):
    fichier_state['logs'].append({
        'time': datetime.now().strftime('%H:%M:%S'),
        'level': logging.getLevelName(level),
        'msg': message
    })
    if len(fichier_state['logs']) > 200:
        fichier_state['logs'] = fichier_state['logs'][-200:]
    logging.log(level, "[1FICHIER] %s", message)
    sync_tool_log_to_queue('1fichier', level, message)


def _fichier_stop_checker():
    return fichier_state.get('stop_flag', False)


def _load_fichier_config(include_secret=True):
    config = {
        'api_key': os.environ.get('FICHIER_API_KEY', '')
    }
    if os.path.exists(FICHIER_CONFIG_FILE):
        try:
            with open(FICHIER_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            if saved.get('api_key'):
                config['api_key'] = saved.get('api_key')
        except Exception:
            pass
    if not include_secret:
        return {
            'has_api_key': bool(config.get('api_key')),
            'api_key_masked': _mask_secret(config.get('api_key', '')),
            'complete': bool(config.get('api_key'))
        }
    return config


def _save_fichier_config(data):
    current = _load_fichier_config(include_secret=True)
    if 'api_key' in data:
        val = (data.get('api_key') or '').strip()
        if val == '__KEEP__':
            pass
        else:
            current['api_key'] = val
    with open(FICHIER_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False)
    return current


@app.route('/api/fichier/config', methods=['GET', 'POST'])
def fichier_config():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        try:
            config = _save_fichier_config(data)
            complete = bool(config.get('api_key'))
            return jsonify({'success': True, 'complete': complete, 'message': 'Đã lưu cấu hình 1fichier'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify(_load_fichier_config(include_secret=False))


# ==================== PIXELDRAIN MODULE ====================
from pixeldrain_engine import PixeldrainEngine

PIXELDRAIN_CONFIG_FILE = os.path.join(BASE_DIR, 'pixeldrain_config.json')
PIXELDRAIN_TMP_ROOT = '/tmp/pixeldrain_dl'

pixeldrain_state = {
    'status': 'idle',
    'progress': 0,
    'message': '',
    'file_name': '',
    'file_size': 0,
    'file_size_human': '',
    'phase': '',
    'logs': [],
    'stop_flag': False,
    'current_index': 0,
    'total_items': 0
}
_pixeldrain_engine = None


def _reset_pixeldrain_state():
    pixeldrain_state.update({
        'status': 'idle',
        'progress': 0,
        'message': '',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': '',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })


def _pixeldrain_progress(percent, message):
    pixeldrain_state['progress'] = percent
    pixeldrain_state['message'] = message
    sync_tool_progress_to_queue('pixeldrain', percent, message)


def _pixeldrain_state_update(values):
    for key, value in values.items():
        if key in pixeldrain_state:
            pixeldrain_state[key] = value
    sync_tool_state_update_to_queue('pixeldrain', values)


def _pixeldrain_log(level, message):
    pixeldrain_state['logs'].append({
        'time': datetime.now().strftime('%H:%M:%S'),
        'level': logging.getLevelName(level),
        'msg': message
    })
    if len(pixeldrain_state['logs']) > 200:
        pixeldrain_state['logs'] = pixeldrain_state['logs'][-200:]
    logging.log(level, "[PIXELDRAIN] %s", message)
    sync_tool_log_to_queue('pixeldrain', level, message)


def _pixeldrain_stop_checker():
    return pixeldrain_state.get('stop_flag', False)


def _load_pixeldrain_config(include_secret=True):
    config = {
        'api_key': os.environ.get('PIXELDRAIN_API_KEY', '')
    }
    if os.path.exists(PIXELDRAIN_CONFIG_FILE):
        try:
            with open(PIXELDRAIN_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            if saved.get('api_key'):
                config['api_key'] = saved.get('api_key')
        except Exception:
            pass
    if not include_secret:
        return {
            'has_api_key': bool(config.get('api_key')),
            'api_key_masked': _mask_secret(config.get('api_key', '')),
            'complete': bool(config.get('api_key'))
        }
    return config


def _save_pixeldrain_config(data):
    current = _load_pixeldrain_config(include_secret=True)
    if 'api_key' in data:
        val = (data.get('api_key') or '').strip()
        if val == '__KEEP__':
            pass
        else:
            current['api_key'] = val
    with open(PIXELDRAIN_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False)
    return current


@app.route('/api/pixeldrain/config', methods=['GET', 'POST'])
def pixeldrain_config():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        try:
            config = _save_pixeldrain_config(data)
            complete = bool(config.get('api_key'))
            return jsonify({'success': True, 'complete': complete, 'message': 'Đã lưu cấu hình Pixeldrain'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify(_load_pixeldrain_config(include_secret=False))


# ==================== PIKPAK ENGINE MODULE ====================
from pikpak_engine import PikPakEngine

PIKPAK_CONFIG_FILE = os.path.join(BASE_DIR, 'pikpak_config.json')
PIKPAK_TMP_ROOT = '/tmp/pikpak_dl'

pikpak_state = {
    'status': 'idle',
    'progress': 0,
    'message': '',
    'file_name': '',
    'file_size': 0,
    'file_size_human': '',
    'phase': '',
    'logs': [],
    'stop_flag': False,
    'current_index': 0,
    'total_items': 0
}
_pikpak_engine = None


def _reset_pikpak_state():
    pikpak_state.update({
        'status': 'idle',
        'progress': 0,
        'message': '',
        'file_name': '',
        'file_size': 0,
        'file_size_human': '',
        'phase': '',
        'logs': [],
        'stop_flag': False,
        'current_index': 0,
        'total_items': 0
    })


def _pikpak_progress(percent, message):
    pikpak_state['progress'] = percent
    pikpak_state['message'] = message
    sync_tool_progress_to_queue('pikpak', percent, message)


def _pikpak_state_update(values):
    for key, value in values.items():
        if key in pikpak_state:
            pikpak_state[key] = value
    sync_tool_state_update_to_queue('pikpak', values)


def _pikpak_log(level, message):
    pikpak_state['logs'].append({
        'time': datetime.now().strftime('%H:%M:%S'),
        'level': logging.getLevelName(level),
        'msg': message
    })
    if len(pikpak_state['logs']) > 200:
        pikpak_state['logs'] = pikpak_state['logs'][-200:]
    logging.log(level, "[PIKPAK] %s", message)
    sync_tool_log_to_queue('pikpak', level, message)


def _pikpak_stop_checker():
    return pikpak_state.get('stop_flag', False)


def _load_pikpak_config(include_secret=True):
    config = {
        'username': os.environ.get('PIKPAK_USERNAME', ''),
        'password': os.environ.get('PIKPAK_PASSWORD', ''),
        'refresh_token': os.environ.get('PIKPAK_REFRESH_TOKEN', ''),
        'access_token': '',
        'access_token_expiry': 0,
        'client_id': 'YvtoWO6GNHiuCl7x',
        'device_id': ''
    }
    if os.path.exists(PIKPAK_CONFIG_FILE):
        try:
            with open(PIKPAK_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            for key in config:
                if key in saved:
                    config[key] = saved.get(key)
        except Exception:
            pass
    if not include_secret:
        return {
            'username': config.get('username', ''),
            'has_password': bool(config.get('password')),
            'password_masked': _mask_secret(config.get('password', '')),
            'has_refresh_token': bool(config.get('refresh_token')),
            'refresh_token_masked': _mask_secret(config.get('refresh_token', '')),
            'complete': bool((config.get('username') and config.get('password')) or config.get('refresh_token') or config.get('access_token'))
        }
    return config


def _save_pikpak_config(data):
    current = _load_pikpak_config(include_secret=True)
    for key in ['username', 'password', 'refresh_token']:
        if key in data:
            val = (data.get(key) or '').strip()
            if key in ('password', 'refresh_token') and val == '__KEEP__':
                continue
            current[key] = val
    if 'password' in data and data['password'] != '__KEEP__':
        current['access_token'] = ''
        current['access_token_expiry'] = 0
    if 'refresh_token' in data and data['refresh_token'] != '__KEEP__':
        current['access_token'] = ''
        current['access_token_expiry'] = 0
    with open(PIKPAK_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False)
    return current


@app.route('/api/pikpak/config', methods=['GET', 'POST'])
def pikpak_config():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        try:
            config = _save_pikpak_config(data)
            complete = bool((config.get('username') and config.get('password')) or config.get('refresh_token'))
            return jsonify({'success': True, 'complete': complete, 'message': 'Đã lưu cấu hình PikPak'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify(_load_pikpak_config(include_secret=False))


# ==================== CLOUD UNPACK MODULE ====================
import base64
import requests

GITHUB_CONFIG_FILE = os.path.join(BASE_DIR, 'github_config.json')

active_unpack_job = {
    'run_id': None,
    'remote_path': None,
    'started_at': 0
}

active_cloud_download_job = {
    'run_id': None,
    'url': None,
    'destination': None,
    'started_at': 0
}

def _load_github_config():
    config = {'github_pat': '', 'github_repo': ''}
    if os.path.exists(GITHUB_CONFIG_FILE):
        try:
            with open(GITHUB_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                config['github_pat'] = saved.get('github_pat', '')
                config['github_repo'] = saved.get('github_repo', '')
        except Exception:
            pass
    return config

def _save_github_config(data):
    current = _load_github_config()
    pat = (data.get('github_pat') or '').strip()
    repo = (data.get('github_repo') or '').strip()
    
    if pat and pat != '__KEEP__':
        current['github_pat'] = pat
    if repo:
        current['github_repo'] = repo
        
    with open(GITHUB_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False)
    return current

@app.route('/api/github/config', methods=['GET', 'POST'])
def github_config():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        try:
            config = _save_github_config(data)
            complete = bool(config.get('github_pat') and config.get('github_repo'))
            return jsonify({'success': True, 'complete': complete, 'message': 'Đã lưu cấu hình GitHub'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
            
    config = _load_github_config()
    pat = config.get('github_pat', '')
    masked_pat = ''
    if pat:
        masked_pat = pat[:4] + '...' + pat[-4:] if len(pat) > 8 else '***'
    return jsonify({
        'github_repo': config.get('github_repo', ''),
        'has_pat': bool(pat),
        'pat_masked': masked_pat,
        'complete': bool(pat and config.get('github_repo'))
    })

@app.route('/api/cloud-unpack/start', methods=['POST'])
def cloud_unpack_start():
    data = request.get_json(force=True, silent=True) or {}
    remote_path = data.get('remote_path', '').strip()
    mode = data.get('mode', 'auto').strip()
    password = data.get('password', '').strip()
    
    if not remote_path:
        return jsonify({'success': False, 'error': 'Đường dẫn nguồn không được để trống'})
        
    config = _load_github_config()
    pat = config.get('github_pat')
    repo = config.get('github_repo')
    
    if not pat or not repo:
        return jsonify({'success': False, 'error': 'Chưa cấu hình GitHub Personal Access Token hoặc Repository'})
        
    # Read and encode rclone.conf
    conf_path = get_rclone_conf_path()
    rclone_conf_b64 = ""
    if os.path.exists(conf_path):
        try:
            with open(conf_path, 'rb') as f:
                rclone_conf_b64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            return jsonify({'success': False, 'error': f'Lỗi đọc rclone.conf: {str(e)}'})
            
    # Trigger repository dispatch
    url = f"https://api.github.com/repos/{repo}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    payload = {
        "event_type": "cloud_unpack",
        "client_payload": {
            "remote_path": remote_path,
            "mode": mode,
            "password": password,
            "rclone_conf": rclone_conf_b64
        }
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers)
        if resp.status_code == 204:
            active_unpack_job['run_id'] = None
            active_unpack_job['remote_path'] = remote_path
            active_unpack_job['started_at'] = time.time()
            return jsonify({'success': True, 'message': 'Đã gửi yêu cầu giải nén tới GitHub Actions'})
        else:
            return jsonify({'success': False, 'error': f'GitHub API Error ({resp.status_code}): {resp.text}'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Lỗi kết nối GitHub: {str(e)}'})

@app.route('/api/cloud-unpack/status', methods=['GET'])
def cloud_unpack_status():
    if not active_unpack_job['started_at']:
        return jsonify({'status': 'idle'})
        
    config = _load_github_config()
    pat = config.get('github_pat')
    repo = config.get('github_repo')
    
    if not pat or not repo:
        return jsonify({'success': False, 'error': 'Chưa cấu hình GitHub'})
        
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    # 1. If run_id is not yet resolved, query the latest workflow runs
    if not active_unpack_job['run_id']:
        url = f"https://api.github.com/repos/{repo}/actions/runs"
        params = {"event": "repository_dispatch", "per_page": 5}
        try:
            resp = requests.get(url, headers=headers, params=params)
            if resp.status_code == 200:
                runs = resp.json().get('workflow_runs', [])
                for run in runs:
                    # Convert GitHub ISO time to epoch
                    from datetime import datetime
                    created_dt = datetime.strptime(run['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                    created_epoch = created_dt.timestamp()
                    
                    # If this run was created around or after we started the trigger
                    if created_epoch >= (active_unpack_job['started_at'] - 30):
                        active_unpack_job['run_id'] = run['id']
                        break
            else:
                return jsonify({'status': 'initializing', 'message': 'Đang kết nối tới GitHub máy chủ...'})
        except Exception as e:
            return jsonify({'status': 'initializing', 'message': f'Đang kết nối... ({str(e)})'})
            
    # If still not found, we wait
    if not active_unpack_job['run_id']:
        # If it has been more than 45 seconds and no run is found, timeout
        if time.time() - active_unpack_job['started_at'] > 45:
            active_unpack_job['started_at'] = 0
            return jsonify({'status': 'idle', 'error': 'Không tìm thấy workflow khởi chạy trên GitHub. Vui lòng kiểm tra lại PAT hoặc Repo.'})
        return jsonify({'status': 'initializing', 'message': 'Đang đợi GitHub khởi động máy ảo...'})
        
    # 2. Get Run status & steps
    run_id = active_unpack_job['run_id']
    run_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
    jobs_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
    
    try:
        run_resp = requests.get(run_url, headers=headers)
        jobs_resp = requests.get(jobs_url, headers=headers)
        
        if run_resp.status_code == 200:
            run_data = run_resp.json()
            status = run_data.get('status') # queued, in_progress, completed
            conclusion = run_data.get('conclusion') # success, failure, etc.
            
            steps_data = []
            if jobs_resp.status_code == 200:
                for job in jobs_resp.json().get('jobs', []):
                    for step in job.get('steps', []):
                        steps_data.append({
                            'name': step['name'],
                            'status': step['status'],
                            'conclusion': step['conclusion']
                        })
                        
            return jsonify({
                'status': status,
                'conclusion': conclusion,
                'remote_path': active_unpack_job['remote_path'],
                'steps': steps_data,
                'html_url': run_data.get('html_url')
            })
        else:
            return jsonify({'status': 'error', 'error': f'Lỗi API GitHub: {run_resp.text}'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})

@app.route('/api/cloud-unpack/reset', methods=['POST'])
def cloud_unpack_reset():
    active_unpack_job['run_id'] = None
    active_unpack_job['remote_path'] = None
    active_unpack_job['started_at'] = 0
    return jsonify({'success': True})


# ==================== CLOUD DOWNLOAD (GITHUB ACTIONS) ====================

@app.route('/api/cloud-download/start', methods=['POST'])
def cloud_download_start():
    data = request.get_json(force=True, silent=True) or {}
    url = data.get('url', '').strip()
    destination = data.get('destination', '').strip()
    password = data.get('password', '').strip()

    if not url:
        return jsonify({'success': False, 'error': 'Vui lòng nhập link nguồn cần tải.'})
    if not destination:
        return jsonify({'success': False, 'error': 'Vui lòng chọn thư mục Google Drive đích.'})

    config = _load_github_config()
    pat = config.get('github_pat')
    repo = config.get('github_repo')

    if not pat or not repo:
        return jsonify({'success': False, 'error': 'Chưa cấu hình GitHub Personal Access Token hoặc Repository trong tab Cấu hình.'})

    conf_path = get_rclone_conf_path()
    rclone_conf_b64 = ""
    if os.path.exists(conf_path):
        try:
            with open(conf_path, 'rb') as f:
                rclone_conf_b64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            return jsonify({'success': False, 'error': 'Lỗi đọc rclone.conf: {0}'.format(str(e))})

    dispatch_url = "https://api.github.com/repos/{0}/dispatches".format(repo)
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer {0}".format(pat),
        "X-GitHub-Api-Version": "2022-11-28"
    }
    payload = {
        "event_type": "cloud_download",
        "client_payload": {
            "url": url,
            "destination": destination,
            "file_password": password,
            "rclone_conf": rclone_conf_b64
        }
    }

    try:
        resp = requests.post(dispatch_url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 204:
            active_cloud_download_job['run_id'] = None
            active_cloud_download_job['url'] = url
            active_cloud_download_job['destination'] = destination
            active_cloud_download_job['started_at'] = time.time()
            return jsonify({'success': True, 'message': 'Đã gửi yêu cầu tải tới GitHub Actions máy ảo!'})
        else:
            return jsonify({'success': False, 'error': 'Lỗi GitHub API ({0}): {1}'.format(resp.status_code, resp.text)})
    except Exception as e:
        return jsonify({'success': False, 'error': 'Lỗi kết nối GitHub: {0}'.format(str(e))})

@app.route('/api/cloud-download/status', methods=['GET'])
def cloud_download_status():
    if not active_cloud_download_job['started_at']:
        return jsonify({'status': 'idle'})

    config = _load_github_config()
    pat = config.get('github_pat')
    repo = config.get('github_repo')

    if not pat or not repo:
        return jsonify({'status': 'error', 'error': 'Chưa cấu hình GitHub'})

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer {0}".format(pat),
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # 1. If run_id is not yet resolved, query the latest workflow runs
    if not active_cloud_download_job['run_id']:
        url = "https://api.github.com/repos/{0}/actions/runs".format(repo)
        params = {"event": "repository_dispatch", "per_page": 5}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=12)
            if resp.status_code == 200:
                runs = resp.json().get('workflow_runs', [])
                for run in runs:
                    from datetime import datetime
                    created_dt = datetime.strptime(run['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                    created_epoch = created_dt.timestamp()
                    if created_epoch >= (active_cloud_download_job['started_at'] - 30):
                        active_cloud_download_job['run_id'] = run['id']
                        break
            else:
                return jsonify({'status': 'initializing', 'message': 'Đang kết nối tới GitHub Actions...'})
        except Exception as e:
            return jsonify({'status': 'initializing', 'message': 'Đang kết nối... ({0})'.format(str(e))})

    if not active_cloud_download_job['run_id']:
        if time.time() - active_cloud_download_job['started_at'] > 45:
            active_cloud_download_job['started_at'] = 0
            return jsonify({'status': 'idle', 'error': 'Không tìm thấy workflow khởi chạy trên GitHub. Vui lòng kiểm tra lại PAT hoặc Repo.'})
        return jsonify({'status': 'initializing', 'message': 'Đang đợi GitHub khởi động máy ảo (70GB NVMe)...'})

    # 2. Get Run status & steps
    run_id = active_cloud_download_job['run_id']
    run_url = "https://api.github.com/repos/{0}/actions/runs/{1}".format(repo, run_id)
    jobs_url = "https://api.github.com/repos/{0}/actions/runs/{1}/jobs".format(repo, run_id)

    try:
        run_resp = requests.get(run_url, headers=headers, timeout=12)
        jobs_resp = requests.get(jobs_url, headers=headers, timeout=12)

        if run_resp.status_code == 200:
            run_data = run_resp.json()
            status = run_data.get('status')
            conclusion = run_data.get('conclusion')

            steps_data = []
            if jobs_resp.status_code == 200:
                for job in jobs_resp.json().get('jobs', []):
                    for step in job.get('steps', []):
                        steps_data.append({
                            'name': step.get('name'),
                            'status': step.get('status'),
                            'conclusion': step.get('conclusion')
                        })

            return jsonify({
                'status': status,
                'conclusion': conclusion,
                'url': active_cloud_download_job['url'],
                'destination': active_cloud_download_job['destination'],
                'steps': steps_data,
                'html_url': run_data.get('html_url')
            })
        else:
            return jsonify({'status': 'error', 'error': 'Lỗi API GitHub: {0}'.format(run_resp.text)})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})

@app.route('/api/cloud-download/cancel', methods=['POST'])
def cloud_download_cancel():
    config = _load_github_config()
    pat = config.get('github_pat')
    repo = config.get('github_repo')
    run_id = active_cloud_download_job.get('run_id')

    if pat and repo and run_id:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer {0}".format(pat),
            "X-GitHub-Api-Version": "2022-11-28"
        }
        cancel_url = "https://api.github.com/repos/{0}/actions/runs/{1}/cancel".format(repo, run_id)
        try:
            requests.post(cancel_url, headers=headers, timeout=10)
        except Exception:
            pass

    active_cloud_download_job['run_id'] = None
    active_cloud_download_job['url'] = None
    active_cloud_download_job['destination'] = None
    active_cloud_download_job['started_at'] = 0
    return jsonify({'success': True, 'message': 'Đã hủy tiến trình Cloud Download.'})

@app.route('/api/cloud-download/reset', methods=['POST'])
def cloud_download_reset():
    active_cloud_download_job['run_id'] = None
    active_cloud_download_job['url'] = None
    active_cloud_download_job['destination'] = None
    active_cloud_download_job['started_at'] = 0
    return jsonify({'success': True})


# ==================== PENDING / TEMP FILES MANAGEMENT ====================
import pending_manager

@app.route('/api/pending/list', methods=['GET'])
def pending_list():
    active_job = download_state if download_state.get('status') in ('downloading', 'uploading') else None
    data = pending_manager.list_pending_items(active_job=active_job, base_dir=BASE_DIR)
    return jsonify(data)


@app.route('/api/pending/delete', methods=['POST'])
def pending_delete():
    data = request.get_json(force=True, silent=True) or {}
    path = data.get('path', '').strip()
    if not path:
        return jsonify({'success': False, 'error': 'Thiếu đường dẫn cần xóa.'}), 400
    active_job = download_state if download_state.get('status') in ('downloading', 'uploading') else None
    res = pending_manager.delete_pending_item(path, active_job=active_job)
    return jsonify(res)


@app.route('/api/pending/clear_all', methods=['POST'])
def pending_clear_all():
    active_job = download_state if download_state.get('status') in ('downloading', 'uploading') else None
    res = pending_manager.clear_all_pending(active_job=active_job, base_dir=BASE_DIR)
    return jsonify(res)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
