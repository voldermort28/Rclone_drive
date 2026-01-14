import os
import threading
import logging
from flask import Flask, render_template, request, jsonify
from gdrivedl import GDriveDL
import socket
from urllib.error import URLError, HTTPError

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
    'total_size': 0,
    'downloaded_size': 0,
    'logs': [],
    'files': [] # List of {id, name, status, size, progress, message}
}

current_thread = None
stop_event = threading.Event()

def progress_callback(file_path, downloaded, total):
    global download_state
    download_state['file'] = file_path
    download_state['downloaded_size'] = downloaded
    
    if total:
        download_state['total_size'] = total
        download_state['progress'] = (downloaded / total) * 100
    else:
        download_state['progress'] = -1 # Indeterminate

def log_callback(message, level):
    global download_state
    # Only log errors or major info to logs
    if level == logging.ERROR:
        log_entry = {'message': message, 'level': logging.getLevelName(level)}
        download_state['logs'].append(log_entry)
        download_state['status'] = 'error'
        download_state['message'] = message
    elif level == logging.INFO and "processing url" in message:
         log_entry = {'message': message, 'level': logging.getLevelName(level)}
         download_state['logs'].append(log_entry)

def file_status_listener(file_path, status, size=0, message=''):
    global download_state
    
    # We use file_path as a key or search for it
    # file_path might be absolute, we want relative for display
    # But filtering the list every time is slow.
    # We will append new files, update existing.
    
    # Simple strategy: Find by path
    target = None
    for f in download_state['files']:
        if f['path'] == file_path:
            target = f
            break
            
    if not target:
        import os
        name = os.path.basename(file_path)
        target = {
            'path': file_path,
            'name': name,
            'status': status,
            'size': size,
            'progress': 0,
            'message': message
        }
        download_state['files'].append(target)
    else:
        target['status'] = status
        if size: target['size'] = size
        if message: target['message'] = message
        if status == 'completed':
            target['progress'] = 100
        elif status == 'exists':
            target['status'] = 'skipped'
            target['progress'] = 100

def run_download(url, output_dir):
    global download_state
    download_state['status'] = 'downloading'
    download_state['logs'] = []
    download_state['files'] = []
    download_state['progress'] = 0
    download_state['message'] = 'Starting download...'
    
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        gdrive = GDriveDL(
            quiet=True, 
            overwrite=True, 
            continue_on_errors=True,
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

@app.errorhandler(500)
def handle_500(e):
    import traceback
    return jsonify({'error': f"Internal Server Error: {str(e)}", 'trace': traceback.format_exc()}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    # Pass through HTTP errors
    if isinstance(e, HTTPError):
        return jsonify({'error': str(e)}), e.code
    return jsonify({'error': f"Unhandled Exception: {str(e)}", 'trace': traceback.format_exc()}), 500

@app.route('/api/stop', methods=['POST'])
def stop_download():
    if current_thread and current_thread.is_alive():
        stop_event.set()
        return jsonify({'message': 'Stopping download...'})
    return jsonify({'message': 'No download running'})

@app.route('/api/download', methods=['POST'])
def start_download():
    global current_thread
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid or missing JSON data'}), 400
        
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
    # Ensure valid path and try to set permissions if needed
    try:
        os.makedirs(output_dir, exist_ok=True)
        
        # Check if writable using access() instead of stat mode
        if not os.access(output_dir, os.W_OK):
             # Try to fix permissions, but don't fail if we can't (e.g. FAT32/ExFAT drives)
             try:
                current_perms = os.stat(output_dir).st_mode
                os.chmod(output_dir, current_perms | 0o700)
             except Exception as e:
                log_callback(f"Warning: Could not chdir permissions for {output_dir}: {e}", logging.WARNING)
    except Exception as e:
        return jsonify({'error': f'Cannot verify/create output directory: {str(e)}'}), 500

    print(f"DEBUG: Saving to {output_dir}") # Console debug
    log_callback(f"Target Directory: {output_dir}", logging.INFO) # UI Log
    
    # Parse URLs (input can be a single string with multiple lines)
    raw_url_input = data.get('url', '')
    urls = [u.strip() for u in raw_url_input.splitlines() if u.strip()]

    if not urls:
        return jsonify({'error': 'No valid URLs provided'}), 400

    if current_thread and current_thread.is_alive():
        return jsonify({'error': 'A download is already in progress'}), 409

    # Reset state
    global download_state
    download_state = {
        'status': 'initializing',
        'message': 'Initializing batch...',
        'progress': 0,
        'file': '',
        'total_size': 0,
        'downloaded_size': 0,
        'logs': [],
        'files': []
    }

    # Stop route moved to global scope

    def run_batch_download(urls, output_dir):
        global download_state, current_thread
        
        # Reset stop event
        stop_event.clear()
        
        # Callback to check if we should stop
        def should_stop():
            return stop_event.is_set()
        
        # Custom progress callback to show relative path
        # Custom progress callback to show relative path
        def batch_progress_callback(file_path, downloaded, total):
            relative_path = os.path.relpath(file_path, output_dir)
            
            # Update global progress (legacy support for simple bar if needed)
            progress_callback(relative_path, downloaded, total)
            
            # Update individual file progress
            for f in download_state['files']:
                if f['path'] == file_path:
                    f['status'] = 'downloading'
                    if total:
                        f['progress'] = (downloaded / total) * 100
                    break
        
        def batch_status_callback(file_path, status, size=0, message=''):
             # Determine relative path for better display name if possible, 
             # but we keep absolute path as ID to match progress callback
             file_status_listener(file_path, status, size, message)

        # GDriveDL instance
        gdrive = GDriveDL(
            quiet=True, 
            overwrite=False, 
            continue_on_errors=True,
            progress_callback=batch_progress_callback,
            log_callback=log_callback,
            status_callback=batch_status_callback,
            stop_callback=should_stop
        )

        try:
            total_urls = len(urls)
            download_state['status'] = 'downloading'
            
            for i, url in enumerate(urls):
                if stop_event.is_set():
                    log_callback("Batch stopped by user", logging.WARNING)
                    break

                log_callback(f"processing url {i+1}/{total_urls}: {url}", logging.INFO)
                download_state['message'] = "Downloading..."
                
                try:
                    gdrive.process_url(url, directory=output_dir, verbose=False)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = str(e)
                    # Try to map to friendly name
                    if "Permission denied" in error_msg:
                        error_msg = "Write Permission Denied (Check Folder Access)"
                    elif "nodename nor servname" in error_msg or "timed out" in error_msg:
                        error_msg = "Network Connection Error"
                        
                    log_callback(f"Failed to process {url}: {error_msg}", logging.ERROR)
                    
                    # Ensure UI reflects error if callback didn't catch it (e.g. early failure)
                    # We try to find the file entry or create a dummy one
                    found = False
                    for f in download_state['files']:
                        # We don't have exact path handy easily if process_url failed early, 
                        # but usually it fails inside.
                        # If process_url failed, likely no file entry created if it failed BEFORE status_callback 'started'.
                        pass
                    
                    # We can't easily update the specific file row without the path, 
                    # but log_callback logic above adds to logs.
                    # Let's update global message
                    download_state['message'] = f"Error: {error_msg}"

            download_state['status'] = 'completed'
            download_state['message'] = 'All downloads finished'
            download_state['progress'] = 100
            
        except Exception as e:
            download_state['status'] = 'error'
            download_state['message'] = f"Batch Error: {str(e)}"
            logging.error(f"Batch Error: {e}")
        finally:
            current_thread = None

    current_thread = threading.Thread(target=run_batch_download, args=(urls, output_dir))
    current_thread.start()
    
    return jsonify({'message': 'Batch download started'})

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
    
    # Define JS API
    class JSApi:
        def choose_directory(self):
            # Open folder dialog
            # window is available globally via webview.windows[0] or passed context if set up
            if not webview.windows:
                return None
            window = webview.windows[0]
            result = window.create_file_dialog(webview.FOLDER_DIALOG)
            return result[0] if result and len(result) > 0 else None

    # Start the Flask app in a daemon thread
    t = threading.Thread(target=app.run, kwargs={'port': port, 'threaded': True})
    t.daemon = True
    t.start()

    # Create the window
    # Height increased to 1200 as requested (approx 1.5x of previous 800)
    webview.create_window('GDrive Downloader', f'http://127.0.0.1:{port}', width=1200, height=1200, resizable=True, js_api=JSApi())
    
    # Start the GUI
    webview.start()
    sys.exit()
