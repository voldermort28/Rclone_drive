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

### [2026-04-07]
### Added
- **Destination History Management**: Added `DELETE` method to `/api/dest_history` and folder name resolution in the dropdown.
- **Drive Explorer Upgrades**: Redesigned the Explorer modal to be opaque, larger, and support "Smart Browse" starting from the current input path.

### Changed
- **Python 3.6 Compatibility**: Replaced `capture_output=True` (Python 3.7+) with `stdout/stderr=PIPE` to support older VPS environments.
- **Folder Wrapping Logic**: Hardened multi-link parent folder wrapping using a 3-tier name resolution fallback.

### Fixed
- Fixed `#destDropdown` transparency issue.
- Fixed modal screen flickering by replacing native `confirm()` with custom modal.
- Fixed `gclone lsjson` silent failures on VPS due to Python version mismatch.

---
*Created by Antigravity AI*
