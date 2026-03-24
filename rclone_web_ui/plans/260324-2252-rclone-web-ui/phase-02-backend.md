# Phase 02: Backend (Rclone Subprocess)
Status: ✅ Complete
Dependencies: phase-01-setup.md

## Objective
Implement `rclone_engine.py` to wrap `subprocess.Popen` and parse standard output from `rclone` to get global progress metrics.

## Requirements
### Functional
- [ ] Construct shell commands based on Source/Dest parameters.
- [ ] Parse `Transferred:`, `Errors:`, `Checks:` strings via Regex.
- [ ] Send parsed data to a globally accessible state for polling.

## Implementation Steps
1. [ ] Create `rclone_engine.py` with parsing logic.
2. [ ] Integrate `rclone_engine.py` into `app.py`'s `/api/download` route.

## Files to Create/Modify
- `rclone_web_ui/rclone_engine.py`
- `rclone_web_ui/app.py`

---
Next Phase: phase-03-frontend.md
