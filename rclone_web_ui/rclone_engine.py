import subprocess
import threading
import logging
import re
import os
import glob
import shutil
import sys

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
        If path matches 'remote:ID[/subfolder]', wrap the ID in curly braces
        like 'remote:{ID}/subfolder' for gclone to treat it as a root folder.
        """
        if not path:
            return path
            
        # Match 'name:id' or 'name:id/subfolder' where id is likely a GDrive ID
        match = re.match(r'^([^:,]+):([A-Za-z0-9\-_]{15,})(/.*)?$', path)
        if match:
            remote_name = match.group(1)
            folder_id = match.group(2)
            subpath = match.group(3) or ""
            
            # If the user already added curly braces, ignore
            if folder_id.startswith('{') and folder_id.endswith('}'):
                return path
                
            # transform to gclone connection string syntax
            new_path = f"{remote_name}:{{{folder_id}}}{subpath}"
            self.log_callback(logging.INFO, f"Transformed {path} -> {new_path}")
            return new_path
            
        return path

    def _cmd_for_subprocess(self, cmd):
        """Use bytes argv to bypass ASCII filesystem encoding on old CentOS/Python."""
        return [arg.encode('utf-8') if isinstance(arg, str) else arg for arg in cmd]

    def _safe_print(self, message):
        """Print diagnostics without crashing when stdout is ASCII-only."""
        try:
            print(message)
        except UnicodeEncodeError:
            try:
                sys.stdout.buffer.write((message + "\n").encode('utf-8', errors='replace'))
                sys.stdout.flush()
            except Exception:
                pass

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

            # Use raw bytes mode to bypass Python's filesystem encoding (ASCII on CentOS 7)
            cmd_bytes = self._cmd_for_subprocess(cmd)

            self.process = subprocess.Popen(
                cmd_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )

            progress_regex = re.compile(r'(\d+)%')
            
            # Use self.process explicitly to satisfy lint and logic
            if self.process and self.process.stdout:
                for raw_line in self.process.stdout:
                    line = raw_line.decode('utf-8', errors='replace').strip()
                    if not line:
                        continue
                        
                    # Print to system logs for debugging. Do not let ASCII stdout kill the job.
                    self._safe_print(f"[RCLONE RAW] {line}")
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

    def run_verify(self, source, destination, verify_callback):
        """
        Runs `rclone check` and streams results to verify_callback.
        It parses the output of `--combined -` to detect missing/differing files.
        """
        binary = self._detect_binary()
        source = self._prepare_remote(source)
        destination = self._prepare_remote(destination)
        
        cmd = [
            binary, "check", source, destination,
            "--size-only",
            "--stats=1s",
            "--stats-one-line",
            "--combined", "-"
        ]
        
        sa_dir = self._get_sa_dir()
        if sa_dir:
            cmd.extend(["--drive-service-account-file-path", sa_dir])
            
        self.log_callback(logging.INFO, f"Executing VERIFY command: {' '.join(cmd)}")
        
        stats = {
            'total_missing': 0,
            'total_differ': 0,
            'total_error': 0,
            'files': []
        }
        
        try:
            # Use raw bytes mode to bypass Python's filesystem encoding (ASCII on CentOS 7)
            cmd_bytes = self._cmd_for_subprocess(cmd)

            self.process = subprocess.Popen(
                cmd_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )

            if self.process and self.process.stdout:
                for raw_line in self.process.stdout:
                    line = raw_line.decode('utf-8', errors='replace').strip()
                    if not line:
                        continue
                        
                    # Parse combined combined log format
                    if line.startswith('+ '):
                        stats['total_missing'] += 1
                        if len(stats['files']) < 150:
                            stats['files'].append({"type": "missing", "path": line[2:]})
                    elif line.startswith('* '):
                        stats['total_differ'] += 1
                        if len(stats['files']) < 150:
                            stats['files'].append({"type": "differ", "path": line[2:]})
                    elif line.startswith('! '):
                        stats['total_error'] += 1
                        if len(stats['files']) < 150:
                            stats['files'].append({"type": "error", "path": line[2:]})
                    elif line.startswith('= ') or line.startswith('- '):
                        pass # Ignore identical or missing on source
                    else:
                        self.log_callback(logging.DEBUG, f"[VERIFY] {line}")
                        
                    if self.stop_checker():
                        if self.process:
                            self.process.terminate()
                        break
                        
                self.process.wait()
                
                # After completion
                if self.process.returncode == 0 or self.process.returncode == 1:
                    # rclone check returns 1 if differences were found, which is expected
                    self.log_callback(logging.INFO, f"Verify completed with missing: {stats['total_missing']}, differ: {stats['total_differ']}")
                    verify_callback(True, stats)
                    return True
                elif self.stop_checker():
                    verify_callback(False, stats, "Bị dừng bởi người dùng")
                    return False
                else:
                    verify_callback(False, stats, f"Lỗi hệ thống (Mã lỗi {self.process.returncode})")
                    return False
            return False

        except Exception as e:
            self.log_callback(logging.ERROR, f"Failed to run verify: {e}")
            verify_callback(False, stats, str(e))
            return False
        finally:
            self.process = None

    def _get_config_path(self):
        """Find the rclone config file."""
        for p in [
            os.path.expanduser('~/.config/rclone/rclone.conf'),
            '/root/.config/rclone/rclone.conf',
        ]:
            if os.path.exists(p):
                return p
        return os.path.expanduser('~/.config/rclone/rclone.conf')

    def _base_cmd(self, subcmd, *args):
        """Build a base command with binary, config, and SA flags."""
        binary = self._detect_binary()
        config_path = self._get_config_path()
        cmd = [binary, subcmd] + list(args) + ["--config", config_path]
        sa_dir = self._get_sa_dir()
        if sa_dir:
            cmd.extend(["--drive-service-account-file-path", sa_dir])
        return cmd

    def list_dir(self, path, dirs_only=True):
        """Run rclone lsjson to list directory contents."""
        import json as _json
        path = self._prepare_remote(path)
        cmd = self._base_cmd("lsjson", path)
        if dirs_only:
            cmd.append("--dirs-only")
        self._last_cmd = ' '.join(cmd)
        self._last_stderr = ''
        try:
            self._safe_print(f"[EXPLORER] Running: {' '.join(cmd)}")
            result = subprocess.run(self._cmd_for_subprocess(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            stdout_text = result.stdout.decode('utf-8', errors='replace')
            stderr_text = result.stderr.decode('utf-8', errors='replace')
            self._last_stderr = stderr_text
            if result.returncode == 0:
                return _json.loads(stdout_text)
            else:
                self._safe_print(f"[EXPLORER] stderr: {stderr_text}")
                return []
        except Exception as e:
            self._last_stderr = str(e)
            self._safe_print(f"[EXPLORER] Error: {e}")
            return []

    def make_dir(self, path):
        """Run rclone mkdir to create a directory on the remote."""
        path = self._prepare_remote(path)
        cmd = self._base_cmd("mkdir", path)
        try:
            self._safe_print(f"[MKDIR] Running: {' '.join(cmd)}")
            result = subprocess.run(self._cmd_for_subprocess(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            return result.returncode == 0
        except Exception as e:
            self._safe_print(f"[MKDIR] Error: {e}")
            return False

    def get_folder_name(self, remote_path):
        """Get the display name of a remote folder using rclone lsjson --stat."""
        import json as _json
        path = self._prepare_remote(remote_path)
        cmd = self._base_cmd("lsjson", path, "--stat")
        try:
            self._safe_print(f"[FOLDER_NAME] Running: {' '.join(cmd)}")
            result = subprocess.run(self._cmd_for_subprocess(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            if result.returncode == 0:
                data = _json.loads(result.stdout.decode('utf-8', errors='replace'))
                # lsjson --stat returns a single object or array with one item
                if isinstance(data, list) and len(data) > 0:
                    return data[0].get('Name', '')
                elif isinstance(data, dict):
                    return data.get('Name', '')
            return ''
        except Exception as e:
            self._safe_print(f"[FOLDER_NAME] Error: {e}")
            return ''
