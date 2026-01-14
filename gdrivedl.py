#!/usr/bin/env python
from __future__ import unicode_literals
import os
import re
import sys
import unicodedata
import argparse
import logging
from contextlib import contextmanager
import time
from datetime import datetime, timedelta

try:
    # Python3
    from urllib.request import Request, build_opener, HTTPCookieProcessor
    from urllib.error import HTTPError, URLError
    from html.parser import HTMLParser
    from http.cookiejar import CookieJar
except ImportError:
    # Python2
    from HTMLParser import HTMLParser
    from urllib2 import Request, build_opener, HTTPCookieProcessor, HTTPError, URLError
    from cookielib import CookieJar

try:
    from html import unescape
except ImportError:
    html = HTMLParser()
    unescape = html.unescape

ITEM_URL = "https://drive.google.com/open?id={id}"
FILE_URL = "https://drive.usercontent.google.com/download?id={id}&export=download&authuser=0"
FOLDER_URL = "https://drive.google.com/embeddedfolderview?id={id}#list"
CHUNKSIZE = 64 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

ID_PATTERNS = [
    re.compile("/file/d/([0-9A-Za-z_-]{10,})(?:[/?]|$)", re.IGNORECASE),
    re.compile("/folders/([0-9A-Za-z_-]{10,})(?:[/?]|$)", re.IGNORECASE),
    re.compile("id=([0-9A-Za-z_-]{10,})(?:&|$)", re.IGNORECASE),
    re.compile("([0-9A-Za-z_-]{10,})", re.IGNORECASE),
]
FOLDER_PATTERN = re.compile(
    '<a href="(https://drive.google.com/.*?)".*?<div class="flip-entry-title">(.*?)</div>.*?<div class="flip-entry-last-modified"><div>(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
CONFIRM_PATTERNS = [
    re.compile(b"confirm=([0-9A-Za-z_-]+)", re.IGNORECASE),
    re.compile(b"name=\"confirm\"\\s+value=\"([0-9A-Za-z_-]+)\"", re.IGNORECASE),
]
UUID_PATTERN = re.compile(b"name=\"uuid\"\\s+value=\"([0-9A-Za-z_-]+)\"", re.IGNORECASE)

FILENAME_PATTERN = re.compile('filename="(.*?)"', re.IGNORECASE)


def output(text):
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.write(text.encode("utf8"))


# Big thanks to leo_wallentin for below sanitize function (modified slightly for this script)
# https://gitlab.com/jplusplus/sanitize-filename/-/blob/master/sanitize_filename/sanitize_filename.py
def sanitize(filename):
    blacklist = ["\\", "/", ":", "*", "?", '"', "<", ">", "|", "\0"]
    reserved = [
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    ]

    filename = unescape(filename).encode("utf8").decode("utf8")
    filename = unicodedata.normalize("NFKD", filename)

    filename = "".join(c for c in filename if c not in blacklist)
    filename = "".join(c for c in filename if 31 < ord(c))
    filename = filename.rstrip(". ")
    filename = filename.strip()

    if all([x == "." for x in filename]):
        filename = "_" + filename
    if filename in reserved:
        filename = "_" + filename
    if len(filename) == 0:
        filename = "_"
    if len(filename) > 255:
        parts = re.split(r"/|\\", filename)[-1].split(".")
        if len(parts) > 1:
            ext = "." + parts.pop()
            filename = filename[: -len(ext)]
        else:
            ext = ""
        if filename == "":
            filename = "_"
        if len(ext) > 254:
            ext = ext[254:]
        maxl = 255 - len(ext)
        filename = filename[:maxl]
        filename = filename + ext
        filename = filename.rstrip(". ")
        if len(filename) == 0:
            filename = "_"

    return filename


def url_to_id(url):
    for pattern in ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)


class GDriveDL(object):
    def __init__(self, quiet=False, overwrite=False, mtimes=False, continue_on_errors=False, progress_callback=None, log_callback=None, status_callback=None, stop_callback=None):
        self._quiet = quiet
        self._overwrite = overwrite
        self._mtimes = mtimes
        self._continue_on_errors = continue_on_errors
        self._create_empty_dirs = True
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._processed = []
        self._errors = []
        self._progress_callback = progress_callback
        self._log_callback = log_callback
        self._status_callback = status_callback
        self._stop_callback = stop_callback

    def _log(self, message, level=logging.INFO):
        if self._log_callback:
            self._log_callback(message, level)
        else:
            if level == logging.ERROR:
                logging.error(message)
            elif level == logging.WARNING:
                logging.warning(message)
            elif level == logging.DEBUG:
                logging.debug(message)
            else:
                logging.info(message)

    def _error(self, message):
        self._log(message, logging.ERROR)
        if self._status_callback:
             # Try to extract filename if possible, otherwise generic
             self._status_callback('error', 'error', 0, message)

        self._errors.append(message)
        if not self._continue_on_errors:
            if not self._log_callback: # Don't exit if we are in a library context
               sys.exit(1)
            else:
               raise Exception(message)

    @property
    def errors(self):
        return self._errors

    @contextmanager
    def _request(self, url):
        self._log("Requesting: {}".format(url), logging.DEBUG)
        req = Request(url, headers={"User-Agent": USER_AGENT})

        f = None
        retries = 6
        delay = 2
        last_error = None

        for attempt in range(retries):
            try:
                f = self._opener.open(req)
                break # Success
            except HTTPError as e:
                # 429: Too Many Requests, 5xx: Server Errors
                if e.code == 429 or 500 <= e.code < 600:
                    if attempt < retries - 1:
                        self._log("HTTP Error {} requesting {}. Retrying in {}s... (Attempt {}/{})".format(e.code, url, delay, attempt + 1, retries), logging.WARNING)
                        time.sleep(delay)
                        delay *= 2
                        last_error = e
                        continue
                raise e
            except URLError as e:
                if attempt < retries - 1:
                    self._log("Connection error requesting {}: {}. Retrying in {}s... (Attempt {}/{})".format(url, str(e), delay, attempt + 1, retries), logging.WARNING)
                    time.sleep(delay)
                    delay *= 2
                    last_error = e
                    continue
                raise e
            except Exception as e:
                 # Generic fallback for temporary network hiccups
                 if attempt < retries - 1:
                    self._log("Error requesting {}: {}. Retrying in {}s...".format(url, str(e), delay), logging.WARNING)
                    time.sleep(delay)
                    delay *= 2
                    last_error = e
                    continue
                 raise e

        if f is None:
             if last_error:
                 raise last_error
             else:
                 raise Exception("Failed to open URL: {}".format(url))

        try:
            yield f
        finally:
            f.close()

    def process_url(self, url, directory, verbose, filename=None):
        id = url_to_id(url)
        if not id:
            self._error("{}: Unable to find ID from url".format(url))
            return

        url = url.lower()

        if "://" not in url:
            with self._request(ITEM_URL.format(id=id)) as resp:
                url = resp.geturl()

        if "/file/" in url or "/uc?" in url:
            self.process_file(id, directory, verbose, filename=filename)
        elif "/folders/" in url:
            if filename:
                self._log("Ignoring --output-document option for folder download", logging.WARNING)
            self.process_folder(id, directory, verbose, create_subdir=True)
        else:
            self._error("{}: returned an unknown url {}".format(id, url))
            return

    def process_folder(self, id, directory, verbose, create_subdir=False):
        if id in self._processed:
            self._log('Skipping already processed folder: {}'.format(id), logging.DEBUG)
            return

        self._processed.append(id)
        with self._request(FOLDER_URL.format(id=id)) as resp:
            html = resp.read().decode("utf-8")

        if verbose:
            self._log("HTML page contents:\n\n{}\n\n".format(html), logging.DEBUG)

        if create_subdir:
            # Extract folder name from title or og:title
            # <meta property="og:title" content="FOLDER_NAME">
            title_match = re.search(r'<meta property="og:title" content="(.*?)">', html)
            if title_match:
                folder_name = sanitize(title_match.group(1))
                directory = os.path.join(directory, folder_name)
                self._log("Found folder name: '{}', creating subdirectory".format(folder_name))
            else:
                 # Fallback to <title>
                title_match = re.search(r'<title>(.*?)</title>', html)
                if title_match:
                    raw_title = title_match.group(1)
                    # Remove " - Google Drive" suffix if present
                    if " - Google Drive" in raw_title:
                        folder_name = sanitize(raw_title.replace(" - Google Drive", ""))
                    else:
                        folder_name = sanitize(raw_title)
                    
                    directory = os.path.join(directory, folder_name)
                    self._log("Found folder name: '{}', creating subdirectory".format(folder_name))
        
        matches = re.findall(FOLDER_PATTERN, html)

        if not matches and "ServiceLogin" in html:
            self._error("{}: does not have link sharing enabled".format(id))
            return

        for match in matches:
            url, item_name, modified = match
            id = url_to_id(url)
            if not id:
                self._error("{}: Unable to find ID from url".format(url))
                continue

            try:
                if "/file/" in url.lower():
                    self.process_file(
                        id, directory, verbose, filename=sanitize(item_name), modified=modified
                    )
                elif "/folders/" in url.lower():
                    self.process_folder(id, os.path.join(directory, sanitize(item_name)), verbose, create_subdir=False)
            except Exception as e:
                self._error("Error processing item {}: {}".format(url, str(e)))
                if not self._continue_on_errors:
                    raise

        if self._create_empty_dirs and not os.path.exists(directory):
            os.makedirs(directory)
            self._log("Directory: {directory} [Created]".format(directory=directory))

    def _get_modified(self, modified):
        if not modified or not self._mtimes:
            return None

        try:
            if ":" in modified:
                hour, minute = modified.lower().split(":")
                if "pm" in minute:
                    hour = int(hour) + 12
                hour = int(hour)+7  # modified is UTC-7 so +7 to utc time
                minute = minute.split(" ")[0]
                now = datetime.utcnow().replace(hour=0, minute=int(minute), second=0, microsecond=0)
                modified = now + timedelta(hours=hour)
            elif "/" in modified:
                modified = datetime.strptime(modified, "%m/%d/%y")
            else:
                now = datetime.utcnow()
                modified = datetime.strptime(modified, "%b %d")
                modified = modified.replace(year=now.year)
        except:
            self._log("Failed to convert mtime: {}".format(modified), logging.DEBUG)
            return None

        return int((modified - datetime(1970, 1, 1)).total_seconds())

    def _set_modified(self, file_path, timestamp):
        if not timestamp:
            return

        try:
            os.utime(file_path, (timestamp, timestamp))
        except:
            self._log("Failed to set mtime", logging.DEBUG)

    def _exists(self, file_path, modified, remote_size=None):
        if self._overwrite or not os.path.exists(file_path):
            return False

        if remote_size is not None:
            try:
                local_size = os.path.getsize(file_path)
                if local_size != remote_size:
                    self._log("Size mismatch: Local={}, Remote={}. Redownloading.".format(local_size, remote_size), logging.INFO)
                    return False
            except:
                self._log("Failed to get local size", logging.DEBUG)

        if modified:
            try:
                return int(os.path.getmtime(file_path)) == modified
            except:
                self._log("Failed to get mtime", logging.DEBUG)

        return True

    def process_file(self, id, directory, verbose, filename=None, modified=None, confirm="", uuid=""):
        file_path = None
        modified_ts = self._get_modified(modified)

        if filename:
            file_path = (
                filename
                if os.path.isabs(filename)
                else os.path.join(directory, filename)
            )
            # Integrity check moved to after headers are received


        url = FILE_URL.format(id=id)
        if confirm:
            url += '&confirm={}'.format(confirm)
        if uuid:
            url += '&uuid={}'.format(uuid)

        self._log("Requesting: {}".format(url), logging.DEBUG)
        with self._request(url) as resp:
            if "ServiceLogin" in resp.url:
                self._error("{}: does not have link sharing enabled".format(id))
                return

            if verbose:
                headers = "\n".join(["{}: {}".format(h, resp.headers.get(h)) for h in resp.headers])
                self._log("Headers:\n{}".format(headers), logging.DEBUG)

            content_disposition = resp.headers.get("content-disposition")
            if not content_disposition:
                if confirm:
                    # The content-disposition header is an indication that the download confirmation worked
                    self._error("{}: content-disposition not found and confirm={} did not work".format(id, confirm))
                    return

                html = resp.read(CHUNKSIZE)
                if verbose:
                    self._log("HTML:\n{}".format(html), logging.DEBUG)

                if b"Google Drive - Quota exceeded" in html:
                    self._error("{}: Quota exceeded for this file".format(id))
                    return

                for pattern in CONFIRM_PATTERNS:
                    confirm = pattern.search(html)
                    if confirm:
                        break

                uuid = UUID_PATTERN.search(html)
                uuid = uuid.group(1).decode() if uuid else ''

                if confirm:
                    confirm = confirm.group(1).decode()
                    self._log("Found confirmation '{}', trying it".format(confirm), logging.DEBUG)
                    return self.process_file(
                        id, directory, verbose, filename=filename, modified=modified, confirm=confirm, uuid=uuid
                    )
                else:
                    self._log("Trying confirmation 't' as a last resort", logging.DEBUG)
                    return self.process_file(
                        id, directory, verbose, filename=filename, modified=modified, confirm='t', uuid=uuid
                    )

            if not file_path:
                filename = FILENAME_PATTERN.search(content_disposition).group(1)
                file_path = os.path.join(directory, sanitize(filename))
                # _exists check will happen below after determining file_size if possible, 
                # or we can check here if we don't care about size yet, but we do.
                # actually we should wait to check specific logic below using headers.


            directory = os.path.dirname(file_path)
            if not os.path.exists(directory):
                os.makedirs(directory)
                self._log("Directory: {directory} [Created]".format(directory=directory))

            try:
                # Get file size if available
                file_size = resp.headers.get("Content-Length")
                file_size = int(file_size) if file_size else None
                
                # Check existence with size validation
                if self._exists(file_path, modified_ts, file_size):
                    self._log("{file_path} [Exists]".format(file_path=file_path))
                    if self._status_callback:
                        self._status_callback(file_path, 'exists', file_size)
                    return
                
                if self._status_callback:
                    self._status_callback(file_path, 'started', file_size)

                with open(file_path, "wb") as f:
                    dl = 0
                    last_out = 0
                    while True:
                        if self._stop_callback and self._stop_callback():
                            self._log("Download stopped by user.", logging.INFO)
                            if self._status_callback:
                                self._status_callback(file_path, 'stopped', file_size)
                            return

                        chunk = resp.read(CHUNKSIZE)
                        if not chunk:
                            break

                        if (
                            b"Too many users have viewed or downloaded this file recently"
                            in chunk
                        ):
                            self._error("{}: Quota exceeded for this file".format(id))
                            return

                        dl += len(chunk)
                        f.write(chunk)
                        
                        if self._progress_callback:
                            self._progress_callback(file_path, dl, file_size)
                        
                        if not self._quiet and not self._progress_callback and (
                            not last_out or dl - last_out > 1048576
                        ):
                             output(
                                "\r{} {:.2f}MB".format(
                                    file_path,
                                    dl / 1024 / 1024,
                                )
                            )
                             last_out = dl
                             sys.stdout.flush()
            except Exception as e:
                if self._status_callback:
                    self._status_callback(file_path, 'error', file_size, str(e))
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise
            else:
                self._set_modified(file_path, modified_ts)
                if self._status_callback:
                    self._status_callback(file_path, 'completed', file_size)

        if not self._quiet and not self._progress_callback:
            output("\n")


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Download Google Drive files & folders"
    )
    parser.add_argument("url", help="Shared Google Drive URL(s)", nargs="*")
    parser.add_argument(
        "-P",
        "--directory-prefix",
        default=".",
        help="Output directory (default is current directory)",
    )
    parser.add_argument(
        "-O",
        "--output-document",
        help="Output filename. Defaults to the GDrive filename. Only valid when downloading a single file.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        help="Disable console output",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-m",
        "--mtimes",
        help="Try use modified times to check for changed files",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-d",
        "--debug",
        help="Debug level logging",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Debug level logging and also print HTML contents and HTTP headers",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-e",
        "--continue-on-errors",
        help="If any errors processing files/folder then log and continue to next",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-f",
        "--urlfile",
        help="Text file containing Google Drive URLS to download (one per line)",
    )
    args = parser.parse_args(args)

    if args.verbose:
        args.debug = True

    if args.debug:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.WARN
    else:
        level = logging.INFO

    logging.basicConfig(format="%(levelname)s: %(message)s", level=level)

    if args.output_document and len(args.url) > 1:
        logging.warning("Ignoring --output-document option for multiple url download")
        args.output_document = None

    gdrive = GDriveDL(
        quiet = args.quiet,
        overwrite = args.output_document is not None,
        mtimes = args.mtimes,
        continue_on_errors = args.continue_on_errors,
    )

    if args.urlfile:
        with open(args.urlfile, 'r') as f:
            args.url.extend(f.readlines())

    args.url = [x.strip() for x in args.url if x.strip()]
    if len(args.url) > 1:
        logging.info('Processing {} urls'.format(len(args.url)))

    for url in args.url:
        gdrive.process_url(
            url, directory=args.directory_prefix, verbose=args.verbose, filename=args.output_document
        )

    if gdrive.errors:
        sys.exit(1)

if __name__ == "__main__":
    main()
