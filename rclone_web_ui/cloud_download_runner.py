# -*- coding: utf-8 -*-
"""
Cloud Download Runner for GitHub Actions.
Executes download engines (PikPak, Mega, Terabox, Fshare, MediaFire, 1fichier, Pixeldrain, Downcode, Direct)
on a GitHub Actions runner with 70GB+ NVMe SSD and uploads directly to Google Drive via gclone.
"""

import sys
import os
import argparse
import logging
import subprocess

# Ensure engine modules in the same directory can be imported
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def log_cb(level, msg):
    logging.log(level, msg)

def progress_cb(percent, msg):
    print("[PROGRESS {0}%] {1}".format(percent, msg), flush=True)

def detect_url_type(url):
    """Detect engine type from URL string."""
    url_lower = (url or '').lower().strip()
    if 'mediafire.com' in url_lower:
        return 'mediafire'
    if 'fshare.vn' in url_lower:
        return 'fshare'
    if any(m in url_lower for m in ['mega.nz', 'mega.co.nz', 'mega.io']):
        return 'mega'
    if any(k in url_lower for k in [
        'terabox', '1024tera', 'nephobox', '4funbox', 'mirrobox', 'momerybox',
        'tibibox', 'tibabox', 'freeterabox', 'terasharelink', 'teraboxlink',
        'teraboxshare', 'dubox', 'momotera', 'miyauplat', 'funletu', 'ytbterabox'
    ]):
        return 'terabox'
    if any(dom in url_lower for dom in ['1fichier.com', '1fichier.fr', '1fichier.co', '1fichier.org', '1fichier.net']):
        return '1fichier'
    if 'pixeldrain.com' in url_lower:
        return 'pixeldrain'
    if any(k in url_lower for k in ['mypikpak.com', 'pikpak.me', 'mypikpak.net', 'api-drive.mypikpak.com']):
        return 'pikpak'
    if 'downcode.org' in url_lower:
        return 'downcode'
    return 'rclone'

def main():
    parser = argparse.ArgumentParser(description="GDriveDL Cloud Download Runner")
    parser.add_argument("--url", required=True, help="Source URL or multiline URLs")
    parser.add_argument("--dest", required=True, help="Google Drive destination (e.g. gc:FIM/Uncen)")
    parser.add_argument("--password", default="", help="File password if required")
    args = parser.parse_args()

    raw_urls = args.url.strip()
    dest = args.dest.strip()
    pwd = args.password.strip()

    print("=" * 60)
    print("🚀 GDriveDL Cloud Download Runner (GitHub Actions)")
    print("Destination:", dest)
    print("Password:", "[PROTECTED]" if pwd else "None")
    print("=" * 60)

    lines = [line.strip() for line in raw_urls.split('\n') if line.strip()]
    if not lines:
        print("❌ Lỗi: Không có đường dẫn nguồn nào được cung cấp.")
        sys.exit(1)

    overall_success = True

    for i, line in enumerate(lines, 1):
        print("\n" + "=" * 50)
        print("Đang xử lý mục {0}/{1}: {2}".format(i, len(lines), line))
        print("=" * 50)

        url_type = detect_url_type(line)
        print("Loại URL phát hiện: [{0}]".format(url_type))

        success = False
        try:
            if url_type == 'pikpak':
                from pikpak_engine import PikPakEngine
                engine = PikPakEngine(progress_callback=progress_cb, log_callback=log_cb)
                pikpak_cfg = {}
                cfg_file = os.path.join(BASE_DIR, 'pikpak_config.json')
                if os.path.isfile(cfg_file):
                    try:
                        import json
                        with open(cfg_file, 'r', encoding='utf-8') as f:
                            pikpak_cfg = json.load(f)
                    except Exception:
                        pass
                success = engine.run_full_pipeline(line, config=pikpak_cfg, drive_dest=dest, file_password=pwd)

            elif url_type == 'mega':
                from mega_engine import MegaEngine
                engine = MegaEngine(progress_callback=progress_cb, log_callback=log_cb)
                success = engine.run_full_pipeline(line, drive_dest=dest, password=pwd)

            elif url_type == 'terabox':
                from terabox_engine import TeraBoxEngine
                engine = TeraBoxEngine(progress_callback=progress_cb, log_callback=log_cb)
                success = engine.run_full_pipeline(line, drive_dest=dest, password=pwd)

            elif url_type == 'fshare':
                from fshare_engine import FshareEngine
                engine = FshareEngine(progress_callback=progress_cb, log_callback=log_cb)
                success = engine.run_full_pipeline(line, drive_dest=dest, password=pwd)

            elif url_type == 'mediafire':
                from mediafire_engine import MediaFireEngine
                engine = MediaFireEngine(progress_callback=progress_cb, log_callback=log_cb)
                success = engine.run_full_pipeline(line, drive_dest=dest, password=pwd)

            elif url_type == '1fichier':
                from fichier_engine import FichierEngine
                engine = FichierEngine(progress_callback=progress_cb, log_callback=log_cb)
                success = engine.run_full_pipeline(line, drive_dest=dest, password=pwd)

            elif url_type == 'pixeldrain':
                from pixeldrain_engine import PixelDrainEngine
                engine = PixelDrainEngine(progress_callback=progress_cb, log_callback=log_cb)
                success = engine.run_full_pipeline(line, drive_dest=dest, password=pwd)

            elif url_type == 'downcode':
                from downcode_engine import DowncodeEngine
                engine = DowncodeEngine(progress_callback=progress_cb, log_callback=log_cb)
                success = engine.run_full_pipeline(line, drive_dest=dest, password=pwd)

            else:
                # Direct Google Drive or standard remote copy via gclone
                binary = '/usr/bin/gclone' if os.path.exists('/usr/bin/gclone') else 'rclone'
                cmd = [binary, "copy", line, dest, "--verbose", "--stats=5s", "--stats-one-line", "--drive-acknowledge-abuse"]
                print("Chạy lệnh:", " ".join(cmd))
                res = subprocess.run(cmd)
                success = (res.returncode == 0)

        except Exception as e:
            logging.error("Lỗi khi chạy tải: {0}".format(str(e)))
            success = False

        if not success:
            overall_success = False
            print("❌ Thất bại khi xử lý mục: {0}".format(line))
        else:
            print("✅ Thành công xử lý mục: {0}".format(line))

        if i < len(lines):
            import random, time
            delay = random.randint(15, 30)
            print("\n⏳ Cooldown: Nghỉ {0} giây trước khi chuyển sang link tiếp theo...".format(delay))
            time.sleep(delay)

    if overall_success:
        print("\n🎉 Tất cả tiến trình Cloud Download & Upload đã hoàn thành thành công!")
        sys.exit(0)
    else:
        print("\n⚠️ Một số hoặc toàn bộ tiến trình tải bị lỗi.")
        sys.exit(1)

if __name__ == "__main__":
    main()
