# Phase 01: Backend API Enhancements
Status: ⬜ Pending

## Objective
Provide the necessary routing and logic for scraping titles from URLs, executing directory listings from Rclone, creating new folders on the remote, and authenticating configuration access.

## Implementation Steps
1. [ ] **Title Scraping Tool**: Implement `GET /api/util/scrape_title?url=...` that downloads the HTML and extracts the `<title>`.
2. [ ] **Drive Explorer API**: Implement `GET /api/explore?path=...` that shells out to `rclone lsjson --dirs-only`. Return the JSON directly.
3. [ ] **Create Folder API**: Implement `POST /api/mkdir` that shells out to `rclone mkdir {remote}:{path}`.
4. [ ] **Auth Route**: Add an `ADMIN_PASSWORD` variable in `app.py`. Implement `POST /api/auth` to return a short-lived token or simply true/false. Protect the config saving routes.

## Files to Modify
- `app.py`
- `rclone_engine.py` (add support for `lsjson` and `mkdir` methods)
