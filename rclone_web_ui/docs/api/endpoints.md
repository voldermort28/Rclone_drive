# GDriveDL API Documentation

Base URL: `http://rclone.laboon.vn/` (Internal: `http://127.0.0.1:8080/`)

---

## 📂 Transfer & Queue

### POST `/api/download`
Adds a new transfer job to the persistent queue.
**Body:** `{ "url": "...", "output_dir": "..." }`
**Response:** `{"message": "Job added to queue", "job_id": "..."}`

### GET `/api/status`
Returns the current active job state, file list, and queue counts.
**Response:** `{"status": "downloading", "message": "...", "progress": 85, "files": [...], "queue_count": 5}`

### POST `/api/stop`
Terminates the current active Rclone process.
**Response:** `{"message": "Stopped"}`

### POST `/api/queue/remove`
Removes a job from the queue.
**Body:** `{"id": "..."}`

---

## 🔍 Verification (Verify & Sync)

### POST `/api/verify`
Triggers an asynchronous `rclone check` match scan.
**Body:** `{"source": "...", "dest": "..." }`

### GET `/api/verify/status`
Polls the result stats of the verification process.
**Response:** `{"status": "completed", "stats": {"total_missing": 0, "total_differ": 2, "files": [...]}}`

### POST `/api/verify/stop`
Kills the verification subprocess.

---

## 🛠️ System Config

### GET `/api/config`
Reads the content of `rclone.conf`.

### POST `/api/config`
Updates the content of `rclone.conf`.
**Body:** `{"content": "..."}`

### POST `/api/sa/upload`
Uploads service account JSON files to the `sa/` directory. (Multipart FormData)
