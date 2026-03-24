# Plan: Cấu hình Web & Vượt giới hạn 750GB
Created: 2026-03-24 23:40
Status: 🟡 In Progress

## Overview
Nâng cấp Rclone Web UI để hỗ trợ quản lý tài khoản Google Drive trực tiếp trên web và tự động xoay vòng Service Account để vượt giới hạn 750GB/ngày.

## Tech Stack
- Frontend: HTML/Vanilla CS/JS (Tabbed UI)
- Backend: Flask (Config Editor & SA Manager)
- Engine: Rclone/Gclone subprocess with SA rotation

## Phases

| Phase | Name | Status | Progress |
|-------|------|--------|----------|
| 01 | [Giao diện Tab & Layout](phase-01-ui.md) | ⬜ Pending | 0% |
| 02 | [API Cấu hình & Upload SA](phase-02-backend.md) | ⬜ Pending | 0% |
| 03 | [Tối ưu Engine (750GB Bypass)](phase-03-engine.md) | ⬜ Pending | 0% |
| 04 | [Triển khai & Kiểm thử VPS](phase-04-vps.md) | ⬜ Pending | 0% |

## Quick Commands
- Start Phase 1: `/code phase-01`
- Check progress: `/next`
- Save context: `/save-brain`
