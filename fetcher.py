# fetcher.py (hardened)
import gzip
import io
import os
import time
import requests
from typing import Optional

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
    "Connection": "keep-alive",
}

def _session(timeout: float = 20.0) -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    s.timeout = timeout  # type: ignore[attr-defined]
    return s

def _retry_get(url: str, *, tries: int = 4, sleep: float = 1.0, allow_4xx: bool = False) -> requests.Response:
    sess = _session()
    last_exc: Optional[Exception] = None
    for i in range(tries):
        try:
            resp = sess.get(url, timeout=30)
            # Accept 2xx; optionally accept 4xx if the site sometimes 403s but returns content
            if 200 <= resp.status_code < 300 or (allow_4xx and 400 <= resp.status_code < 500):
                return resp
            print(f"[fetcher] GET {url} -> {resp.status_code}; retrying...")
        except Exception as e:
            last_exc = e
            print(f"[fetcher] GET {url} failed: {e}; retrying...")
        time.sleep(sleep * (2 ** i))
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to GET {url}")

def _looks_blocked_or_tiny(text: str) -> bool:
    if not text or len(text) < 1500:  # too small to be a real page
        return True
    # obvious block/rate-limit keywords
    needles = [
        "just a moment",            # cloudflare
        "rate limit",               # github
        "access denied",
        "captcha",
        "request blocked",
        "attention required!",
        "you have been blocked",
    ]
    low = text.lower()
    return any(n in low for n in needles)

def saveFile(filename, content):
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

def saveFileAsBytes(filename, content: bytes):
    with open(filename, 'wb') as f:
        f.write(content)

def doesFileExist(filename):
    if os.path.isfile(filename):
        print(f'File exists, not downloading new version: {filename}')
        return True
    return False

def fetchXML(filename, url):
    """
    Downloads (and gunzips if needed) an XML file once.
    """
    if doesFileExist(filename):
        return

    resp = _retry_get(url, tries=4, sleep=1.0)
    if url.endswith('.gz'):
        try:
            # Some servers already send decompressed content; try gzip and fall back to raw
            try:
                data = gzip.decompress(resp.content)
            except OSError:
                # not actually gzipped; try as-is
                data = resp.content
            saveFileAsBytes(filename, data)
        except Exception as e:
            print(f"Failed to decompress {url}: {e}")
    else:
        saveFileAsBytes(filename, resp.content)

def fetchHTML(filename, url):
    """
    Downloads an HTML page once, with UA/timeout/retries and a sanity check.
    """
    if doesFileExist(filename):
        return

    # GitHub sometimes returns 4xx with useful body; allow_4xx True improves resilience
    resp = _retry_get(url, tries=4, sleep=1.0, allow_4xx=True)
    text = resp.text

    if _looks_blocked_or_tiny(text):
        # Don’t poison the cache; write a diagnostic file and raise
        diag = filename + ".blocked.html"
        saveFile(diag, text)
        raise SystemExit(
            f"[fetcher] {url} looks blocked/empty; saved response to {diag}. "
            f"Add a stronger UA, try later, or fetch from a mirror."
        )

    saveFile(filename, text)
    print(f'Webpage downloaded and saved to {filename}')
