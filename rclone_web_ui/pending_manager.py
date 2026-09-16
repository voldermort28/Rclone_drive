# -*- coding: utf-8 -*-
"""
pending_manager.py - Quản lý file tạm và các tiến trình download dở dang trên VPS.
Tương thích hoàn toàn với Python 3.6+ (không dùng f-strings).
"""

import os
import re
import json
import time
import shutil
import hashlib
from datetime import datetime

TEMP_ROOTS = [
    '/tmp/fshare_dl',
    '/tmp/terabox_dl',
    '/tmp/mediafire_dl',
    '/tmp/mega_dl',
    '/tmp/fichier_dl',
    '/tmp/pixeldrain_dl'
]

ENGINE_NAMES = {
    'fshare': 'Fshare',
    'terabox': 'Terabox',
    'mediafire': 'MediaFire',
    'mega': 'Mega',
    'fichier': '1fichier',
    'pixeldrain': 'Pixeldrain',
    'downcode': 'DownCode'
}


def format_size(size_bytes):
    """Định dạng byte thành dung lượng dễ đọc."""
    try:
        size = float(size_bytes or 0)
    except (ValueError, TypeError):
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return "{0:.2f} {1}".format(size, unit)
        size /= 1024.0
    return "{0:.2f} PB".format(size)


def save_pending_meta(tmp_dir, url='', file_name='', file_size=0, dest='', engine=''):
    """Lưu thông tin metadata vào thư mục tạm khi bắt đầu tải."""
    if not tmp_dir:
        return
    try:
        if not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir, exist_ok=True)
        meta_path = os.path.join(tmp_dir, 'meta.json')
        data = {
            'url': url or '',
            'file_name': file_name or '',
            'file_size': file_size or 0,
            'dest': dest or '',
            'engine': engine or '',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _build_url_hash_map(base_dir=None):
    """
    Xây dựng bảng tra cứu hash SHA1 từ history.json và queue.json.
    Giúp tự động tìm ra URL gốc của các thư mục tạm cũ chưa có meta.json.
    """
    hash_map = {}
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    files_to_check = [
        os.path.join(base_dir, 'history.json'),
        os.path.join(base_dir, 'queue.json')
    ]

    for fpath in files_to_check:
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                records = json.load(f)
                if isinstance(records, list):
                    for rec in records:
                        urls_val = rec.get('urls') or rec.get('url') or ''
                        if not urls_val:
                            continue
                        for u in urls_val.splitlines():
                            u_str = u.strip()
                            if not u_str:
                                continue
                            # Full url hash (first 24 chars)
                            h1 = hashlib.sha1(u_str.encode('utf-8')).hexdigest()[:24]
                            hash_map[h1] = {'url': u_str, 'dest': rec.get('dest', '')}
                            # URL without query parameters hash
                            u_clean = u_str.split('?')[0]
                            if u_clean != u_str:
                                h2 = hashlib.sha1(u_clean.encode('utf-8')).hexdigest()[:24]
                                hash_map[h2] = {'url': u_str, 'dest': rec.get('dest', '')}
        except Exception:
            pass
    return hash_map


def _detect_engine_from_path(path):
    """Nhận diện tên engine từ đường dẫn thư mục."""
    p = path.lower()
    for eng in ENGINE_NAMES:
        if eng in p:
            return eng
    return 'unknown'


def _get_dir_size_and_mtime(dir_path):
    """Tính tổng dung lượng và thời gian sửa đổi mới nhất trong thư mục."""
    total_size = 0
    latest_mtime = 0
    file_list = []
    has_part = False

    try:
        for root, _, files in os.walk(dir_path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    st = os.stat(fp)
                    total_size += st.st_size
                    if st.st_mtime > latest_mtime:
                        latest_mtime = st.st_mtime
                    if f.endswith('.part'):
                        has_part = True
                    if f != 'meta.json':
                        file_list.append((f, st.st_size))
                except OSError:
                    pass
    except Exception:
        pass

    if latest_mtime == 0:
        try:
            latest_mtime = os.path.getmtime(dir_path)
        except OSError:
            latest_mtime = time.time()

    return total_size, latest_mtime, file_list, has_part


def list_pending_items(active_job=None, base_dir=None):
    """
    Quét và liệt kê tất cả các mục download dở dang hoặc file tạm trong /tmp/*_dl.
    """
    url_hash_map = _build_url_hash_map(base_dir)
    items = []
    total_waste_bytes = 0

    active_urls = []
    if active_job:
        raw_urls = active_job.get('raw_urls') or active_job.get('urls') or ''
        active_urls = [u.strip() for u in raw_urls.splitlines() if u.strip()]

    for root_dir in TEMP_ROOTS:
        if not os.path.exists(root_dir) or not os.path.isdir(root_dir):
            continue

        try:
            subdirs = os.listdir(root_dir)
        except OSError:
            continue

        for sub in subdirs:
            item_path = os.path.join(root_dir, sub)
            if not os.path.isdir(item_path):
                # Trường hợp file nằm trực tiếp dưới thư mục gốc
                try:
                    fsize = os.path.getsize(item_path)
                    mtime = os.path.getmtime(item_path)
                    engine = _detect_engine_from_path(root_dir)
                    items.append({
                        'path': item_path,
                        'name': sub,
                        'engine': engine,
                        'engine_display': ENGINE_NAMES.get(engine, engine.capitalize()),
                        'url': '',
                        'size_bytes': fsize,
                        'size_human': format_size(fsize),
                        'status': 'dangling_file',
                        'status_display': 'File tạm đơn lẻ',
                        'is_active': False,
                        'modified_at': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S'),
                        'dest': ''
                    })
                    total_waste_bytes += fsize
                except OSError:
                    pass
                continue

            # Xử lý thư mục con (thường là mã hash SHA1 hoặc tên thư mục tải)
            dir_size, latest_mtime, file_list, has_part = _get_dir_size_and_mtime(item_path)
            if dir_size == 0 and not file_list:
                # Thư mục rỗng
                try:
                    shutil.rmtree(item_path, ignore_errors=True)
                except Exception:
                    pass
                continue

            engine = _detect_engine_from_path(root_dir)
            meta_file = os.path.join(item_path, 'meta.json')
            url = ''
            dest = ''
            file_name = ''
            created_at = None

            if os.path.exists(meta_file):
                try:
                    with open(meta_file, 'r', encoding='utf-8') as mf:
                        mdata = json.load(mf)
                        url = mdata.get('url') or ''
                        dest = mdata.get('dest') or ''
                        file_name = mdata.get('file_name') or ''
                        created_at = mdata.get('created_at')
                        if mdata.get('engine'):
                            engine = mdata['engine']
                except Exception:
                    pass

            # Nếu chưa có meta.json, kiểm tra hash_map đối chiếu từ history/queue
            if not url and sub in url_hash_map:
                url = url_hash_map[sub].get('url', '')
                dest = url_hash_map[sub].get('dest', '')

            # Nếu chưa có file_name, lấy tên file thật trong thư mục
            if not file_name:
                non_part_files = [f[0] for f in file_list if not f[0].endswith('.part')]
                if non_part_files:
                    file_name = non_part_files[0]
                elif file_list:
                    file_name = file_list[0][0]
                else:
                    file_name = sub

            # Kiểm tra xem có phải tiến trình đang chạy hay không
            is_active = False
            if active_urls:
                if url and any(url in au or au in url for au in active_urls):
                    is_active = True
                # Check SHA1 of active URLs
                for au in active_urls:
                    if hashlib.sha1(au.encode('utf-8')).hexdigest()[:24] == sub:
                        is_active = True
                        break

            # Xác định trạng thái hiển thị
            if is_active:
                status = 'active'
                status_display = 'Đang tải (Active)'
            elif has_part:
                status = 'incomplete'
                status_display = 'Tải dở dang (.part)'
            else:
                status = 'completed_unuploaded'
                status_display = 'Tồn đọng (Chưa upload)'

            time_str = created_at or datetime.fromtimestamp(latest_mtime).strftime('%Y-%m-%d %H:%M:%S')

            items.append({
                'path': item_path,
                'name': file_name,
                'folder_key': sub,
                'engine': engine,
                'engine_display': ENGINE_NAMES.get(engine, engine.capitalize()),
                'url': url,
                'size_bytes': dir_size,
                'size_human': format_size(dir_size),
                'status': status,
                'status_display': status_display,
                'is_active': is_active,
                'modified_at': time_str,
                'dest': dest
            })

            if not is_active:
                total_waste_bytes += dir_size

    # Sắp xếp mục mới nhất lên đầu
    items.sort(key=lambda x: x.get('modified_at', ''), reverse=True)

    return {
        'success': True,
        'count': len(items),
        'total_size_bytes': total_waste_bytes,
        'total_size_human': format_size(total_waste_bytes),
        'items': items
    }


def delete_pending_item(target_path, active_job=None):
    """
    Xóa một mục pending an toàn.
    Chỉ cho phép xóa bên trong các thư mục TEMP_ROOTS đã định nghĩa.
    """
    if not target_path:
        return {'success': False, 'error': 'Đường dẫn không hợp lệ.'}

    abs_path = os.path.abspath(target_path)

    # Security check: Đường dẫn phải nằm trong một trong các TEMP_ROOTS
    is_safe = False
    for root in TEMP_ROOTS:
        abs_root = os.path.abspath(root)
        # Phải là thư mục con, không được xóa chính root (ví dụ: không được xóa /tmp/fshare_dl)
        if abs_path.startswith(abs_root + os.sep) and len(abs_path) > len(abs_root):
            is_safe = True
            break

    if not is_safe:
        return {'success': False, 'error': 'Từ chối truy cập: Đường dẫn không thuộc vùng file tạm cho phép.'}

    if not os.path.exists(abs_path):
        return {'success': False, 'error': 'Mục không tồn tại hoặc đã được xóa trước đó.'}

    # Tính dung lượng trước khi xóa để báo cáo
    freed_bytes = 0
    try:
        if os.path.isdir(abs_path):
            dir_size, _, _, _ = _get_dir_size_and_mtime(abs_path)
            freed_bytes = dir_size
            shutil.rmtree(abs_path, ignore_errors=True)
        else:
            freed_bytes = os.path.getsize(abs_path)
            os.remove(abs_path)
    except Exception as e:
        return {'success': False, 'error': 'Lỗi khi xóa: {0}'.format(str(e))}

    return {
        'success': True,
        'message': 'Đã xóa thành công.',
        'freed_bytes': freed_bytes,
        'freed_human': format_size(freed_bytes)
    }


def clear_all_pending(active_job=None, base_dir=None):
    """
    Xóa tất cả các file/thư mục tạm không thuộc tiến trình đang chạy.
    """
    data = list_pending_items(active_job=active_job, base_dir=base_dir)
    items = data.get('items', [])
    deleted_count = 0
    total_freed = 0

    for item in items:
        if item.get('is_active'):
            continue
        res = delete_pending_item(item.get('path'), active_job=active_job)
        if res.get('success'):
            deleted_count += 1
            total_freed += res.get('freed_bytes', 0)

    return {
        'success': True,
        'deleted_count': deleted_count,
        'freed_bytes': total_freed,
        'freed_human': format_size(total_freed)
    }
