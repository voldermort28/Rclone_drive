# Changelog

## [2026-03-26]
### Added
- **Smart Queue Core**: Persistent asynchronous queuing for high-volume transfers.
- **Auto-Retry Mechanism**: Detects Google Drive 403 quota errors and schedules retries with 3-hour backoff.
- **Verify & Sync**: New tab for comparing source/dest using `rclone check`. Supports real-time stats and one-click sync.
- **Transfer Console**: Real-time terminal output streaming for live Rclone visibility on the web UI.

### Changed
- Refactored `app.py` UI polling to handle both Transfer and Verify states independently.
- Improved Rclone process isolation to prevent hanging or zombie processes on VPS.

### Fixed
- Fixed 403 quota hanging by implementing forced wait states in the background worker.
- Fixed UI freeze during large directory scans by using non-blocking subprocess streaming.

---
*Created by Antigravity AI*
