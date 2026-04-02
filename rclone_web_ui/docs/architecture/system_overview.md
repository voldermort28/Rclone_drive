# GDriveDL System Architecture

## Architecture Overview
GDriveDL resides as a lightweight Flask-based wrapper around the Rclone binary. It is designed to manage high-volume file transfers on a VPS with persistent queueing and smart error handling.

### Core Components
1. **Flask API Handler (`app.py`)**: Manages web requests, triggers asynchronous threads for Rclone jobs, and maintains the global state dictionary (`download_state`, `verify_state`).
2. **Persistence Layer (`queue.json`, `history.json`)**: Simple JSON-based storage for transfer queues and history to survive application restarts.
3. **Rclone Engine (`rclone_engine.py`)**: Wraps `subprocess.Popen` to call `rclone copy` or `rclone check`. It parses `stdout` in real-time to extract progress percentages and discrepancy lists.
4. **Queue Worker**: A background thread in `app.py` that continuously monitors `queue.json` and executes the next job in line.

## Error Handling Design
### 403 Google Quota Retry
When the worker detects `downloadQuotaExceeded` in Rclone's output:
- It marks the job as `delayed`.
- Sets `execute_at` timestamp to `current_time + 3 hours`.
- Pauses the queue for that specific source until the timer expires.

### Subprocess Management
- Every Rclone process is tracked via `self.process`.
- The `stop()` command signals `SIGTERM` followed by a cleanup wait to ensure no zombie processes on the VPS.

---
*Created by Antigravity AI*
