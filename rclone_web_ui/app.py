import os
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
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Pokemon@2808')
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
    'job_id': None
}

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
            with open(QUEUE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return []

def save_queue(q):
    with open(QUEUE_FILE, 'w') as f:
        json.dump(q, f)

# ==================== BACKGROUND WORKER ====================
from rclone_engine import RcloneEngine

def scrape_folder_name_from_url(url):
    """Helper to get folder name from GDrive page title."""
    try:
        import urllib.request
        # Strip tracking params
        clean_url = url.split('?')[0]
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
            return title
    except:
        pass
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
                # 1. Try scraping from URL
                if "http" in src:
                    folder_name = scrape_folder_name_from_url(src)
                
                # 2. Fallback to rclone lsjson (even if often fails on this VPS version)
                if not folder_name:
                    folder_name = engine.get_folder_name(src)
                
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

def queue_worker_loop():
    global download_state
    while True:
        time.sleep(5)
        
        if download_state['status'] in ['downloading', 'initializing']:
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
            quota_hit = run_real_rclone_job(job_to_run)
            
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
                        'urls': download_state['raw_urls'],
                        'dest': download_state['output_dir'],
                        'status': download_state['status'],
                        'message': download_state['message']
                    }
                    histories = []
                    if os.path.exists(HISTORY_FILE):
                        with open(HISTORY_FILE, 'r') as f:
                            histories = json.load(f)
                    histories.append(history_record)
                    with open(HISTORY_FILE, 'w') as f:
                        json.dump(histories, f)
                except Exception as e:
                    print(f"Failed to save history: {e}")
            
            save_queue(q)
            time.sleep(5)
            download_state['status'] = 'idle'

# Start background worker
worker_thread = threading.Thread(target=queue_worker_loop, daemon=True)
worker_thread.start()

# ==================== TRANSFER API ====================

@app.route('/api/stop', methods=['POST'])
def stop_download():
    global stop_event
    if download_state['status'] in ['downloading', 'initializing']:
        stop_event.set()
        return jsonify({'message': 'Stopping process...'})
    return jsonify({'message': 'No process running'})

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
        
    raw_text = data.get('url', '')
    output_dir = data.get('output_dir', '')
    wrap = data.get('wrap', False)
    
    if not raw_text or not output_dir:
        return jsonify({'error': 'Source and Destination are required'}), 400

    q = load_queue()
    lines = [u.strip() for u in raw_text.splitlines() if u.strip()]
    
    # Process each line
    added_count = 0
    for line in lines:
        source_path = line
        original_url = None
        
        # Determine if it's a URL or needs conversion
        if 'drive.google.com' in line or line.startswith('http'):
            original_url = line
            fid = extract_drive_id(line)
            if fid:
                source_path = f'gc:{fid}'
        
        job = {
            'id': str(uuid.uuid4()),
            'urls': source_path,  # The path rclone will actually use
            'original_url': original_url,
            'dest': output_dir,
            'wrap': wrap,
            'status': 'waiting',
            'execute_at': time.time() - 1,
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        q.append(job)
        added_count += 1
    
    save_queue(q)
    return jsonify({'message': f'Đã thêm {added_count} job vào hàng đợi!'})

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
            with open(HISTORY_FILE, 'r') as f:
                histories = json.load(f)
    except Exception as e:
        print(f"Error reading history: {e}")
        
    if download_state['status'] in ('downloading', 'initializing'):
        active_record = {
            'time': 'Đang chạy...',
            'urls': download_state['raw_urls'],
            'dest': download_state['output_dir'],
            'status': download_state['status'],
            'message': download_state['message'],
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
            with open(conf_path, 'r') as f:
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
        with open(conf_path, 'w') as f:
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
        if 'drive.google.com' in line:
            fid = extract_drive_id(line)
            if fid: results.append({'original': line, 'parsed': f'{remote}:{fid}', 'id': fid})
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
    items = _make_engine().list_dir(path, dirs_only=True)
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

@app.route('/api/dest_history', methods=['GET', 'POST'])
def handle_dest_history():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True)
        path = data.get('path') if data else None
        if not path: return jsonify({'error': 'Missing path'}), 400
        history = []
        if os.path.exists(DEST_HISTORY_FILE):
            try:
                with open(DEST_HISTORY_FILE, 'r') as f:
                    history = json.load(f)
            except: pass
        history = [h for h in history if h.get('path') != path]
        history.insert(0, {'path': path, 'used_at': datetime.now().strftime("%Y-%m-%d %H:%M")})
        history = history[:20]
        with open(DEST_HISTORY_FILE, 'w') as f: json.dump(history, f)
        return jsonify({'message': 'Saved'})
    else:
        if os.path.exists(DEST_HISTORY_FILE):
            try:
                with open(DEST_HISTORY_FILE, 'r') as f: return jsonify(json.load(f))
            except: pass
        return jsonify([])

@app.route('/')
def index():
    return render_template('index.html')

@app.errorhandler(500)
def handle_500(e):
    import traceback
    return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
