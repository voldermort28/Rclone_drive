# -*- coding: utf-8 -*-
"""
DowncodeEngine - Resolver for https://downcode.org/
Decodes Downcode 8-digit codes (e.g. 2423-9499, 30868565) or URLs
into direct/real destination links (Google Drive, MediaFire, Terabox, Fshare, Mega, 1fichier, Pixeldrain, etc.).
Fully compatible with Python 3.6+ (CentOS 7).
"""

import os
import re
import json
import logging

try:
    import requests
except ImportError:
    requests = None

try:
    import urllib.request as urllib_request
    import urllib.error as urllib_error
except ImportError:
    import urllib2 as urllib_request
    import urllib2 as urllib_error


class DowncodeEngine(object):
    """Engine/Resolver for DownCode (downcode.org)."""

    API_ENDPOINT = "https://downcode.org/api/decode"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"

    @classmethod
    def get_headers(cls):
        return {
            "Content-Type": "application/json",
            "Origin": "https://downcode.org",
            "Referer": "https://downcode.org/",
            "User-Agent": cls.USER_AGENT,
            "Accept": "application/json, text/plain, */*"
        }

    @classmethod
    def is_downcode(cls, text):
        """Check if a string or URL represents a DownCode code or URL."""
        if not text:
            return False
        clean = str(text).strip()
        if not clean:
            return False
        clean_lower = clean.lower()
        if "downcode.org" in clean_lower:
            return True
        if clean_lower.startswith("downcode:") or clean_lower.startswith("dc:"):
            return True
        # 8 digits with hyphen: 1234-5678
        if re.match(r"^\d{4}-\d{4}$", clean):
            return True
        # 8 digits consecutive: 12345678
        if re.match(r"^\d{8}$", clean):
            return True
        return False

    @classmethod
    def extract_code(cls, text):
        """Extract and normalize 8-digit DownCode code as 'xxxx-xxxx'."""
        if not text:
            return None
        clean = str(text).strip()
        if not clean:
            return None

        # 1. URL parameter ?code=xxxx-xxxx or &code=...
        m = re.search(r"[?&]code=([0-9]{4}-?[0-9]{4})", clean, re.IGNORECASE)
        if m:
            digits = m.group(1).replace("-", "")
            return "{0}-{1}".format(digits[:4], digits[4:])

        # 2. URL path: downcode.org/xxxx-xxxx or downcode.org/xxxxxxxx
        m = re.search(r"downcode\.org/(?:[a-zA-Z0-9_\-]+/)*([0-9]{4}-?[0-9]{4})", clean, re.IGNORECASE)
        if m:
            digits = m.group(1).replace("-", "")
            return "{0}-{1}".format(digits[:4], digits[4:])

        # 3. downcode:xxxx-xxxx or dc:xxxxxxxx
        m = re.match(r"^(?:downcode|dc):\s*([0-9]{4}-?[0-9]{4})", clean, re.IGNORECASE)
        if m:
            digits = m.group(1).replace("-", "")
            return "{0}-{1}".format(digits[:4], digits[4:])

        # 4. Pure 8-digit code (with or without hyphen)
        m = re.match(r"^\s*([0-9]{4}-?[0-9]{4})\s*$", clean)
        if m:
            digits = m.group(1).replace("-", "")
            return "{0}-{1}".format(digits[:4], digits[4:])

        # 5. Fallback search anywhere in string for xxxx-xxxx
        m = re.search(r"\b([0-9]{4}-[0-9]{4})\b", clean)
        if m:
            digits = m.group(1).replace("-", "")
            return "{0}-{1}".format(digits[:4], digits[4:])

        return None

    @classmethod
    def decode(cls, code, timeout=15):
        """
        Send decode request to downcode.org API.
        Returns dict:
          - On success: {'success': True, 'url': target_url, 'code': code, 'text_note': ..., 'type': ...}
          - On failure: {'success': False, 'error': error_msg, 'code': code}
        """
        clean_code = cls.extract_code(code)
        if not clean_code:
            return {
                "success": False,
                "error": "Mã DownCode không đúng định dạng (yêu cầu 8 chữ số, ví dụ: 2423-9499).",
                "code": code
            }

        headers = cls.get_headers()
        payload = json.dumps({"code": clean_code})

        # Try requests first if available
        if requests is not None:
            try:
                resp = requests.post(
                    cls.API_ENDPOINT,
                    headers=headers,
                    data=payload,
                    timeout=timeout
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception as e:
                        return {
                            "success": False,
                            "error": "Phản hồi API DownCode không phải JSON hợp lệ: {0}".format(e),
                            "code": clean_code
                        }
                    if data.get("success"):
                        target_url = (data.get("success") or "").strip()
                        return {
                            "success": True,
                            "url": target_url,
                            "code": clean_code,
                            "text_note": data.get("text_note", ""),
                            "type": data.get("type", 0)
                        }
                    else:
                        err_msg = data.get("error") or "Không tìm thấy nội dung cho mã DownCode này."
                        return {
                            "success": False,
                            "error": err_msg,
                            "code": clean_code
                        }
                elif resp.status_code == 403:
                    return {
                        "success": False,
                        "error": "DownCode từ chối truy cập (403 Forbidden).",
                        "code": clean_code
                    }
                else:
                    return {
                        "success": False,
                        "error": "Lỗi máy chủ DownCode (HTTP {0}).".format(resp.status_code),
                        "code": clean_code
                    }
            except requests.Timeout:
                return {
                    "success": False,
                    "error": "Hết thời gian chờ phản hồi từ DownCode (Timeout).",
                    "code": clean_code
                }
            except Exception as e:
                logging.warning("Requests failed, falling back to urllib: %s", e)

        # Fallback to urllib
        try:
            req = urllib_request.Request(
                cls.API_ENDPOINT,
                data=payload.encode("utf-8"),
                headers=headers
            )
            with urllib_request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                if data.get("success"):
                    target_url = (data.get("success") or "").strip()
                    return {
                        "success": True,
                        "url": target_url,
                        "code": clean_code,
                        "text_note": data.get("text_note", ""),
                        "type": data.get("type", 0)
                    }
                else:
                    err_msg = data.get("error") or "Không tìm thấy nội dung cho mã DownCode này."
                    return {
                        "success": False,
                        "error": err_msg,
                        "code": clean_code
                    }
        except urllib_error.HTTPError as e:
            return {
                "success": False,
                "error": "Lỗi API DownCode (HTTP {0}).".format(e.code),
                "code": clean_code
            }
        except urllib_error.URLError as e:
            return {
                "success": False,
                "error": "Không thể kết nối tới DownCode: {0}.".format(e.reason),
                "code": clean_code
            }
        except Exception as e:
            return {
                "success": False,
                "error": "Lỗi giải mã DownCode: {0}.".format(str(e)),
                "code": clean_code
            }

    @classmethod
    def resolve(cls, text, timeout=15):
        """Convenience method: takes any text/URL, extracts code and decodes."""
        code = cls.extract_code(text)
        if not code:
            return {
                "success": False,
                "error": "Không nhận diện được mã DownCode hợp lệ.",
                "code": text
            }
        return cls.decode(code, timeout=timeout)
