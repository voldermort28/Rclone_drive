# Phase 04: Integration & Testing
Status: ✅ Complete
Dependencies: phase-03-frontend.md

## Objective
Test the full loop from UI -> API -> Subprocess -> Rclone Output -> UI Update.

## Requirements
### Functional
- [ ] Clicking "Start" executes the rclone process on the backend.
- [ ] Progress bar fills up based on total transferred bytes parsed from rclone output.
- [ ] Stop button cleanly terminates the rclone subprocess (`SIGTERM`).

## Implementation Steps
1. [ ] Finalize `stop` logic in `app.py`.
2. [ ] Test run with a mock transfer.
3. [ ] Clean up logs and UI edge cases.

## Files to Create/Modify
- `rclone_web_ui/app.py`
- `rclone_web_ui/rclone_engine.py`

---
Next Phase: None
