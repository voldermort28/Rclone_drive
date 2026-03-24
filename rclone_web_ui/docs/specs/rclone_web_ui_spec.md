# Rclone Web UI - Detailed Specs

## 1. Executive Summary
A web wrapper for rclone to manage GDrive server-side copying on VPS. Re-uses the frontend structural design from the `gdrivedl` project but replaces the core engine.

## 2. API Contract
- `POST /api/download`: 
  - Request: `{ "urls": "...", "output_dir": "gc:{dest_id}" }` (reusing old keys but handling them differently).
  - Response: `{ "message": "Started" }`
- `GET /api/status`: 
  - Response: `{ "status": "running", "progress": 45, "message": "Transferred: ...", "downloaded_size": 100, "total_size": 200, "files": [] }`
- `POST /api/stop`: 
  - Kills `rclone` subprocess.

## 3. Core Engine (rclone_engine.py)
- Runs `subprocess.Popen` with `rclone copy` or `gclone copy`.
- Reads `proc.stdout.readline()`.
- Uses Regex to extract `Transferred:` strings.
- Sets global state variables safely using threading locks.

## 4. UI Components
- **Input Area:** Textarea for source links. Text input for Destination Remote.
- **Controls:** Start / Stop buttons.
- **Progress:** Global progress bar and detailed log terminal area (reusing the table view from `gdrivedl` or modifying it to a terminal output view for `rclone` logs).
