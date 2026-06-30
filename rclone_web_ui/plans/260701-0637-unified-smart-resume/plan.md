# Plan: Unified Multi-Link & Smart Resume Flow
Created: 2026-07-01 06:37
Status: 🟡 In Progress

## Overview
Đồng nhất luồng xử lý tải xuống (download pipeline) trên **tất cả 4 tab** (Mega, Terabox, MediaFire, Fshare) với 2 mục tiêu chính:

1. **Multi-Link Input**: Tất cả các tab đều hỗ trợ nhập nhiều link (file đơn, folder, hoặc hỗn hợp) trong 1 lần chạy.
2. **3-Step Smart Resume & Skip**: Trước mỗi file trong danh sách tải, thực hiện 3 bước kiểm tra tuần tự để tránh tải lại file đã hoàn thành, tiết kiệm băng thông VPS và tài khoản VIP.

## Tech Stack
- Frontend: Vanilla JS (textarea multi-line input)
- Backend: Python 3.6.8 + Flask
- Transfer Engine: gclone (subprocess)

## Hiện trạng (AS-IS)

### Bảng so sánh khả năng Resume/Skip hiện tại:
| Engine | Multi-Link | GDrive Pre-scan (Bước 1) | VPS Complete Check (Bước 2) | VPS .part Resume (Bước 3) |
|--------|:---:|:---:|:---:|:---:|
| **Mega** | ❌ (chỉ 1 folder link) | ✅ `lsjson` | ❌ | ✅ (qua decrypt stream) |
| **Terabox** | ❌ (1 link) | ❌ | ✅ | ✅ HTTP Range |
| **MediaFire** | ✅ (textarea, folder expand) | ❌ | ❌ | ✅ HTTP Range |
| **Fshare** | ❌ (1 link) | ❌ | ❌ | ✅ HTTP Range |

### Mục tiêu (TO-BE):
| Engine | Multi-Link | GDrive Pre-scan (Bước 1) | VPS Complete Check (Bước 2) | VPS .part Resume (Bước 3) |
|--------|:---:|:---:|:---:|:---:|
| **Mega** | ✅ | ✅ (giữ nguyên) | ✅ | ✅ |
| **Terabox** | ✅ | ✅ | ✅ (giữ nguyên) | ✅ |
| **MediaFire** | ✅ (giữ nguyên) | ✅ | ✅ | ✅ |
| **Fshare** | ✅ | ✅ | ✅ | ✅ |

## Phases

| Phase | Name | Status | Progress | Dependencies |
|-------|------|--------|----------|--------------|
| 01 | Backend Engines - GDrive Pre-scan & VPS Check | ⬜ Pending | 0% | — |
| 02 | Backend Routes - Multi-Link Parsing | ⬜ Pending | 0% | Phase 01 |
| 03 | Frontend UI - Textarea & Multi-Link UX | ⬜ Pending | 0% | Phase 02 |
| 04 | Integration Testing & Deploy | ⬜ Pending | 0% | Phase 03 |

## Quick Commands
- Start Phase 1: `/code phase-01`
- Check progress: `/next`
- Save context: `/save-brain`

## Ghi chú quan trọng
- **Python 3.6 ONLY**: Không dùng f-string, walrus operator (:=), dataclasses.
- **VPS disk nhỏ**: Luôn xóa file tạm trên VPS ngay sau khi upload thành công.
- **Mega đặc biệt**: File Mega được mã hóa AES-CTR, không thể resume HTTP Range thông thường. Bước 2 (VPS check) sẽ kiểm tra file đã giải mã hoàn chỉnh.
