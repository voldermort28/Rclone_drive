import os
import threading
import logging
from flask import Flask, render_template, request, jsonify
from gdrivedl import GDriveDL

import sys

if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask(__name__)

# Global state to track download progress
download_state = {
    'status': 'idle',  # idle, downloading, completed, error
    'message': '',
    'progress': 0,
    'file': '',
    'total_size': 0,
    'downloaded_size': 0,
    'logs': []
}

current_thread = None
stop_event = threading.Event()

def progress_callback(file_path, downloaded, total):
    global download_state
    download_state['file'] = os.path.basename(file_path)
    download_state['downloaded_size'] = downloaded
    
    if total:
        download_state['total_size'] = total
        download_state['progress'] = (downloaded / total) * 100
    else:
        download_state['progress'] = -1 # Indeterminate

def log_callback(message, level):
    global download_state
    log_entry = {'message': message, 'level': logging.getLevelName(level)}
    download_state['logs'].append(log_entry)
    if level == logging.ERROR:
        download_state['status'] = 'error'
        download_state['message'] = message

def run_download(url, output_dir):
    global download_state
    download_state['status'] = 'downloading'
    download_state['logs'] = []
    download_state['progress'] = 0
    download_state['message'] = 'Starting download...'
    
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        gdrive = GDriveDL(
            quiet=True, 
            overwrite=True, 
            progress_callback=progress_callback,
            log_callback=log_callback
        )
        gdrive.process_url(url, output_dir, verbose=True)
        
        if download_state['status'] != 'error':
            download_state['status'] = 'completed'
            download_state['message'] = 'Download completed successfully!'
            download_state['progress'] = 100
            
    except Exception as e:
        download_state['status'] = 'error'
        download_state['message'] = str(e)
        log_callback(str(e), logging.ERROR)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/download', methods=['POST'])
def start_download():
    global current_thread
    data = request.json
    url = data.get('url')
    # Handle output directory
    user_output_dir = data.get('output_dir')
    if user_output_dir and user_output_dir.strip():
        # Expand user path (e.g. ~/Downloads)
        expanded_dir = os.path.expanduser(user_output_dir.strip())
        
        # If path is absolute, use it
        if os.path.isabs(expanded_dir):
            output_dir = expanded_dir
        else:
            # If relative, make it relative to User's Downloads/GDriveDL to avoid CWD issues
            # We don't want relative paths polluting the app bundle
            base_dir = os.path.join(os.path.expanduser('~'), 'Downloads', 'GDriveDL')
            output_dir = os.path.join(base_dir, expanded_dir)
    else:
        # Default path
        output_dir = os.path.join(os.path.expanduser('~'), 'Downloads', 'GDriveDL')

    # Ensure valid path and try to set permissions if needed
    try:
        os.makedirs(output_dir, exist_ok=True)
        # Try to make sure it's writable (rwx for user)
        # Note: This might fail if we don't own the dir, but os.makedirs usually handles ownership for new dirs
        current_perms = os.stat(output_dir).st_mode
        if not (current_perms & 0o200): # Write check
             os.chmod(output_dir, current_perms | 0o700)
    except Exception as e:
        return jsonify({'error': f'Cannot verify/create output directory: {str(e)}'}), 500

    print(f"DEBUG: Saving to {output_dir}") # Console debug
    log_callback(f"Target Directory: {output_dir}", logging.INFO) # UI Log
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
        
    if current_thread and current_thread.is_alive():
        return jsonify({'error': 'A download is already in progress'}), 409

    # Reset state
    global download_state
    download_state = {
        'status': 'initializing',
        'message': 'Initializing...',
        'progress': 0,
        'file': '',
        'total_size': 0,
        'downloaded_size': 0,
        'logs': []
    }

    current_thread = threading.Thread(target=run_download, args=(url, output_dir))
    current_thread.start()
    
    return jsonify({'message': 'Download started'})

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(download_state)

if __name__ == '__main__':
    import webview
    import sys

    # Find a free port dynamically
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('localhost', 0))
    port = sock.getsockname()[1]
    sock.close()
    
    # Start the Flask app in a daemon thread
    t = threading.Thread(target=app.run, kwargs={'port': port, 'threaded': True})
    t.daemon = True
    t.start()

    # Create the window
    webview.create_window('GDrive Downloader', f'http://127.0.0.1:{port}', width=600, height=750, resizable=True)
    
    # Start the GUI
    webview.start()
    sys.exit()
