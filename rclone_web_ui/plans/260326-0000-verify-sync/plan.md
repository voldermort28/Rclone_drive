# Plan: Tính năng Check & Sync (Kiểm tra & Chép bù)
Created: 2026-03-26
Status: 🟡 In Progress

## Overview
Dựa theo `BRIEF_VERIFY.md`, tính năng này cho phép user nhập Nguồn/Đích, bấm "Quét" để xem file thiếu (do rớt mạng/quota) và bấm "Chép bù" để ném thẳng vào Smart Queue tải tiếp.
Đây là tính năng thêm vào dự án `GDriveDL - Rclone Web UI` đã có sẵn.

## Tech Stack
- Frontend: Vanilla JS + HTML/CSS
- Backend: Python (Flask) + `rclone check` CLI
- Khác: SystemD trên VPS CentOS 7

## Phases

| Phase | Name | Status | Progress |
|-------|------|--------|----------|
| 01 | Backend API & Rclone Subprocess | ⬜ Pending | 0% |
| 02 | Frontend UI (Tab Verify) | ⬜ Pending | 0% |
| 03 | API & UI Integration | ⬜ Pending | 0% |
| 04 | VPS Deployment | ⬜ Pending | 0% |

## Quick Commands
- Bắt đầu Phase 1: `@/code phase-01`
- Chốt tiến độ: `@/next`
