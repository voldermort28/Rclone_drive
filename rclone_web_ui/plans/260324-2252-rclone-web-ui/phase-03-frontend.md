# Phase 03: Frontend UI Adaptations
Status: ✅ Complete
Dependencies: phase-02-backend.md

## Objective
Adapt the input fields on the web UI to accept Rclone Remotes instead of local folder paths.

## Requirements
### Functional
- [ ] Change "Download into Folder" UI element to "Destination Remote (e.g., gc:{id})".
- [ ] Pass the new payload format to the backend API.
- [ ] Adapt the status table to show Rclone log lines or a summary string.

## Implementation Steps
1. [ ] Update `index.html` inputs.
2. [ ] Update `app.js` API call payload and polling display logic.

## Files to Create/Modify
- `rclone_web_ui/templates/index.html`
- `rclone_web_ui/static/js/app.js`

---
Next Phase: phase-04-integration.md
