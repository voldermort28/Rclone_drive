# Plan: Terabox → Google Drive Tab
Created: 2026-05-19T01:22
Status: 🟡 In Progress

## Overview
Thêm tab **"Terabox"** độc lập vào GDriveDL để tải file từ Terabox → VPS → Google Drive.
Hoàn toàn tách biệt khỏi các tab hiện tại (Transfer, Verify, Config, History).

## Context
- User có tài khoản Terabox **free** (tốc độ tải ~100-200 KB/s, file lớn sẽ tải lâu)
- Chỉ hỗ trợ tải **1 file/link** mỗi lần
- VPS làm trạm trung chuyển (download → upload → cleanup)
- Cookie `ndus` lưu trên VPS, nhập 1 lần qua giao diện

## Tech Stack
- Backend: Python 3.6 + Flask (giữ nguyên stack hiện tại)
- Terabox: Custom `requests`-based API client (Python 3.6 compatible)
- Upload: `gclone copy` (tái sử dụng SA rotation hiện tại)
- Frontend: Vanilla JS + CSS (tái sử dụng design system)

## Phases

| Phase | Name | Status | Tasks | Progress |
|-------|------|--------|-------|----------|
| 01 | Backend Engine | ✅ Complete | 8 | 100% |
| 02 | API Endpoints | ✅ Complete | 7 | 100% |
| 03 | Frontend UI | ✅ Complete | 9 | 100% |
| 04 | Frontend JS Logic | ✅ Complete | 8 | 100% |
| 05 | Integration & Deploy | 🟡 In Progress | 6 | 50% |

**Tổng: 38 tasks** — Local tests passed ✅

## Files Changed
- `terabox_engine.py` — **[NEW]** Engine class (320 lines)
- `app.py` — **[MODIFIED]** +5 API endpoints (~190 lines added)
- `templates/index.html` — **[MODIFIED]** Tab button + tab content (~100 lines added)
- `static/js/app.js` — **[MODIFIED]** Terabox JS logic (~275 lines added)

## Test Results (Local)
- ✅ TeraboxEngine imports successfully
- ✅ URL parsing works (extracts share key)
- ✅ Human size formatting works (1073741824 → "1.0 GB")
- ✅ Cookie GET/POST API works
- ✅ Status API returns correct initial state
- ⬜ E2E test with real Terabox link (requires VPS)

## Quick Commands
- Deploy: `git push origin main`
- Check progress: `/next`
