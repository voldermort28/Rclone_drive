import os
import threading
import logging
import json
import zipfile
import glob
import shutil
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SA_DIR = os.path.join(BASE_DIR, 'sa')
HISTORY_FILE = os.path.join(BASE_DIR, 'history.json')
RCLONE_CONF_PATHS = [
    os.path.expanduser('~/.config/rclone/rclone.conf'),
    '/root/.config/rclone/rclone.conf',
]

def get_rclone_conf_path():
    for p in RCLONE_CONF_PATHS:
        if os.path.exists(p):
            return p
    # Default: create if not exists
    default = RCLONE_CONF_PATHS[0]
    os.makedirs(os.path.dirname(default), exist_ok=True)
    return default

# Global state to track download progress
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
    'output_dir': ''
}

current_thread = None
stop_event = threading.Event()

# ==================== PAGES ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.errorhandler(500)
def handle_500(e):
    import traceback
    return jsonify({'error': f"Internal Server Error: {str(e)}", 'trace': traceback.format_exc()}), 500

# ==================== TRANSFER API ====================

@app.route('/api/stop', methods=['POST'])
def stop_download():
    global current_thread, stop_event
    if current_thread and current_thread.is_alive():
        stop_event.set()
        return jsonify({'message': 'Stopping process...'})
    return jsonify({'message': 'No process running'})

@app.route('/api/download', methods=['POST'])
def start_download():
    global current_thread, download_state, stop_event
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid or missing JSON data'}), 400
        
    urls = data.get('url', '')
    output_dir = data.get('output_dir', '')
    
    if not urls or not output_dir:
        return jsonify({'error': 'Source and Destination are required'}), 400

    if current_thread and current_thread.is_alive():
        return jsonify({'error': 'A process is already running'}), 409

    download_state = {
        'status': 'initializing',
        'message': 'Initializing Rclone...',
        'progress': 0,
        'file': '',
        'total_size': 0,
        'downloaded_size': 0,
        'logs': [],
        'files': [],
        'raw_urls': urls,
        'output_dir': output_dir
    }
    
    stop_event.clear()

    from rclone_engine import RcloneEngine

    def run_real_rclone(sources, dest):
        global download_state, current_thread
        
        def progress_cb(percent, line):
            download_state['progress'] = percent
            download_state['message'] = line
            for f in download_state['files']:
                if f['status'] == 'downloading':
                    f['progress'] = percent
                    f['message'] = line
                    break
            
        def log_cb(level, msg):
            print(f"[{logging.getLevelName(level)}] {msg}")
            if level == logging.ERROR:
                download_state['logs'].append({'level': 'ERROR', 'message': msg})
                download_state['status'] = 'error'
                download_state['message'] = msg
            elif level == logging.WARNING:
                download_state['logs'].append({'level': 'WARNING', 'message': msg})
                
        def stop_check():
            return stop_event.is_set()
            
        engine = RcloneEngine(progress_cb, log_cb, stop_check)
        
        try:
            download_state['status'] = 'downloading'
            
            source_list = [s.strip() for s in sources.splitlines() if s.strip()]
            download_state['files'] = []
            
            for src in source_list:
                download_state['files'].append({
                    'path': src,
                    'name': src,
                    'status': 'pending',
                    'progress': 0,
                    'message': ''
                })
            
            for i, src in enumerate(source_list):
                if stop_event.is_set():
                    break
                
                download_state['files'][i]['status'] = 'downloading'
                download_state['message'] = f"Copying from {src}..."
                
                success = engine.run_copy(src, dest)
                
                if success:
                    download_state['files'][i]['status'] = 'completed'
                    download_state['files'][i]['progress'] = 100
                else:
                    download_state['files'][i]['status'] = 'stopped' if stop_event.is_set() else 'error'
                    if not stop_event.is_set():
                        download_state['status'] = 'error'
                        download_state['message'] = f'Failed to copy {src}'
                        break
            else:
                if not stop_event.is_set() and download_state['status'] != 'error':
                    download_state['status'] = 'completed'
                    download_state['message'] = 'All copies completed!'
                    download_state['progress'] = 100
                
            if stop_event.is_set():
                download_state['status'] = 'error'
                download_state['message'] = 'Stopped by user'
                
            # Log to History
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
                
        finally:
            current_thread = None

    current_thread = threading.Thread(target=run_real_rclone, args=(urls, output_dir))
    current_thread.start()
    
    return jsonify({'message': 'Process started'})

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(download_state)

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
    """Read rclone.conf and return its content."""
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
    """Save rclone.conf content."""
    data = request.get_json(force=True, silent=True)
    if not data or 'content' not in data:
        return jsonify({'error': 'Missing config content'}), 400
    
    conf_path = get_rclone_conf_path()
    try:
        os.makedirs(os.path.dirname(conf_path), exist_ok=True)
        with open(conf_path, 'w') as f:
            f.write(data['content'])
        return jsonify({'message': 'Config saved successfully', 'path': conf_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== SERVICE ACCOUNT API ====================

@app.route('/api/sa/upload', methods=['POST'])
def upload_sa():
    """Upload and extract Service Account ZIP file."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Empty filename'}), 400
    
    os.makedirs(SA_DIR, exist_ok=True)
    
    try:
        if f.filename.endswith('.zip'):
            # Save temp zip
            tmp_path = os.path.join(SA_DIR, '_upload.zip')
            f.save(tmp_path)
            
            # Extract
            with zipfile.ZipFile(tmp_path, 'r') as zf:
                json_count = 0
                for name in zf.namelist():
                    if name.endswith('.json') and not name.startswith('__MACOSX'):
                        # Extract to flat folder (no nested dirs)
                        basename = os.path.basename(name)
                        if basename:
                            target = os.path.join(SA_DIR, basename)
                            with zf.open(name) as src, open(target, 'wb') as dst:
                                dst.write(src.read())
                            json_count += 1
            
            # Cleanup temp
            os.remove(tmp_path)
            
            return jsonify({
                'message': f'Uploaded and extracted {json_count} SA files',
                'count': json_count,
                'path': SA_DIR
            })
        
        elif f.filename.endswith('.json'):
            target = os.path.join(SA_DIR, f.filename)
            f.save(target)
            return jsonify({
                'message': f'Uploaded SA file: {f.filename}',
                'count': 1,
                'path': SA_DIR
            })
        
        else:
            return jsonify({'error': 'Only .zip or .json files are accepted'}), 400
    
    except zipfile.BadZipFile:
        return jsonify({'error': 'Invalid ZIP file'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sa/info', methods=['GET'])
def sa_info():
    """Get info about uploaded Service Accounts."""
    if not os.path.exists(SA_DIR):
        return jsonify({'count': 0, 'files': [], 'path': SA_DIR})
    
    sa_files = sorted(glob.glob(os.path.join(SA_DIR, '*.json')))
    return jsonify({
        'count': len(sa_files),
        'files': [os.path.basename(f) for f in sa_files[:20]],  # Show first 20
        'path': SA_DIR
    })

@app.route('/api/sa/clear', methods=['POST'])
def clear_sa():
    """Remove all SA files."""
    if os.path.exists(SA_DIR):
        shutil.rmtree(SA_DIR)
        os.makedirs(SA_DIR, exist_ok=True)
    return jsonify({'message': 'All SA files cleared'})

# ==================== MAIN ====================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
