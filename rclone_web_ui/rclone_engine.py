import subprocess
import threading
import logging
import re
import os
import glob
import shutil

class RcloneEngine:
    def __init__(self, progress_callback, log_callback, stop_checker):
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stop_checker = stop_checker
        self.process = None  # type: subprocess.Popen[str] | None

    def _detect_binary(self):
        """Detect gclone (preferred) or fall back to rclone."""
        env_binary = os.environ.get('RCLONE_BINARY', '')
        if env_binary:
            return env_binary
        
        # Check if gclone is available (preferred for SA rotation)
        for path in ['/usr/local/bin/gclone', '/usr/bin/gclone', shutil.which('gclone') or '']:
            if path and os.path.isfile(path):
                return path
        
        return 'rclone'

    def _get_sa_dir(self):
        """Get the Service Account directory path."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sa_dir = os.path.join(base_dir, 'sa')
        if os.path.isdir(sa_dir) and glob.glob(os.path.join(sa_dir, '*.json')):
            return sa_dir
        return None

    def _prepare_remote(self, path):
        """
        Special handling for Google Drive IDs in gclone.
        If path matches 'remote:ID' (no slashes), wrap the ID in curly braces
        like 'remote:{ID}' for gclone to treat it as a root folder.
        """
        if not path:
            return path
            
        # Match 'name:id' where id is likely a GDrive ID (alphanumeric, -, _, ~)
        # and doesn't contain sub-paths (no /)
        match = re.match(r'^([^:,]+):([A-Za-z0-9\-_]{15,})$', path)
        if match:
            remote_name = match.group(1)
            folder_id = match.group(2)
            
            # If the user already added curly braces, ignore
            if folder_id.startswith('{') and folder_id.endswith('}'):
                return path
                
            # transform to gclone connection string syntax
            new_path = f"{remote_name}:{{{folder_id}}}"
            self.log_callback(logging.INFO, f"Transformed {path} -> {new_path}")
            return new_path
            
        return path

    def run_copy(self, source, destination):
        binary = self._detect_binary()
        
        # Prepare remotes (ID handling)
        source = self._prepare_remote(source)
        destination = self._prepare_remote(destination)
        
        cmd = [
            binary, "copy", source, destination,
            "--verbose",
            "--stats=1s",
            "--stats-one-line"
        ]
        
        # Auto-add SA rotation flags if SA directory exists
        sa_dir = self._get_sa_dir()
        if sa_dir:
            sa_count = len(glob.glob(os.path.join(sa_dir, '*.json')))
            cmd.extend([
                "--drive-service-account-file-path", sa_dir,
            ])
            self.log_callback(logging.INFO, f"SA rotation enabled: {sa_count} accounts in {sa_dir}")
        
        self.log_callback(logging.INFO, f"Executing command: {' '.join(cmd)}")
        
        try:
            # Check if config file exists
            config_path = os.path.expanduser('~/.config/rclone/rclone.conf')
            if not os.path.exists(config_path):
                self.log_callback(logging.ERROR, f"Rclone config NOT FOUND at {config_path}")
            else:
                self.log_callback(logging.INFO, f"Using rclone config: {config_path}")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace'
            )

            progress_regex = re.compile(r'(\d+)%')
            
            # Use self.process explicitly to satisfy lint and logic
            if self.process and self.process.stdout:
                for line in self.process.stdout:
                    line = line.strip()
                    if not line:
                        continue
                        
                    # Print to system logs for debugging
                    print(f"[RCLONE RAW] {line}")
                    self.log_callback(logging.DEBUG, line)
                    
                    match = progress_regex.search(line)
                    if match:
                        percent = int(match.group(1))
                        self.progress_callback(percent, line)
                    elif "Transferred:" in line and " / " in line:
                        self.log_callback(logging.INFO, line)
                    elif "Errors:" in line:
                        self.log_callback(logging.ERROR, f"RCLONE ERROR: {line}")

                    if self.stop_checker():
                        self.log_callback(logging.WARNING, "Stop signal received. Terminating process.")
                        if self.process:
                            self.process.terminate()
                        break
                        
                self.process.wait()
                
                if self.process.returncode == 0:
                    self.log_callback(logging.INFO, "Rclone copy completed successfully.")
                    return True
                elif self.stop_checker():
                    self.log_callback(logging.WARNING, "Rclone copy was stopped.")
                    return False
                else:
                    self.log_callback(logging.ERROR, f"Rclone exited with code {self.process.returncode}")
                    return False
            else:
                self.log_callback(logging.ERROR, "Failed to initialize rclone process stdout.")
                return False

        except FileNotFoundError:
            self.log_callback(logging.ERROR, f"Binary '{binary}' not found. Please install rclone/gclone.")
            return False
        except Exception as e:
            self.log_callback(logging.ERROR, f"Failed to run rclone: {e}")
            return False
        finally:
            self.process = None
