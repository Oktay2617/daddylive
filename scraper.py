#!/usr/bin/env python3
# scraper.py — single-file (fetcher + tvlogo + scraper) with HLS extraction
# Requires: requests, beautifulsoup4

import os
import re
import json
import difflib
import time
import base64
from typing import Optional, Tuple, List

import requests
from requests.exceptions import SSLError
from bs4 import BeautifulSoup

# ============================================================
# =============== Fetcher (hardened HTTP client) =============
# ============================================================

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

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s

def _looks_blocked_or_tiny(text: str) -> bool:
    if not text or len(text) < 600:  # allow small player pages; will still parse
        return False
    needles = [
        "just a moment", "rate limit", "access denied", "captcha",
        "request blocked", "attention required!", "you have been blocked"
    ]
    low = text.lower()
    return any(n in low for n in needles)

def http_get_text(url: str, *, tries: int = 4, sleep: float = 1.0,
                  allow_4xx: bool = True, verify: bool = True,
                  referer: Optional[str] = None) -> str:
    sess = _session()
    last_exc: Optional[Exception] = None
    headers = dict(DEFAULT_HEADERS)
    if referer:
        headers["Referer"] = referer
    for i in range(tries):
        try:
            resp = sess.get(url, timeout=30, verify=verify, headers=headers, allow_redirects=True)
            if 200 <= resp.status_code < 300 or (allow_4xx and 400 <= resp.status_code < 500):
                return resp.text
            print(f"[fetcher] GET {url} -> {resp.status_code}; retrying...")
        except SSLError as e:
            last_exc = e
            print(f"[fetcher] GET {url} SSL error: {e}; retrying...")
        except Exception as e:
            last_exc = e
            print(f"[fetcher] GET {url} failed: {e}; retrying...")
        time.sleep(sleep * (2 ** i))
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to GET {url}")

def fetch_first_ok_text(urls: List[str], *, referer: Optional[str] = None) -> Tuple[str, str]:
    """
    Try a list of URLs; return (used_url, response_text).
    For dlhd.dad, if TLS fails, retry once with verify=False (loudly).
    """
    last_err = None
    for u in urls:
        print(f"[scraper] Trying {u}")
        try:
            try:
                text = http_get_text(u, tries=4, sleep=1.0, allow_4xx=True, verify=True, referer=referer)
            except SSLError as e:
                if "dlhd.dad" in u or os.getenv("DLHD_INSECURE") == "1":
                    print(f"[fetcher] TLS verify failed for {u}. Retrying ONCE with verify=False (insecure).")
                    text = http_get_text(u, tries=1, sleep=0.5, allow_4xx=True, verify=False, referer=referer)
                else:
                    raise
            if _looks_blocked_or_tiny(text):
                print(f"[scraper] Page looks potentially blocked (but will try to parse anyway): {u}")
            print(f"[scraper] OK -> {u}")
            return u, text
        except Exception as e:
            last_err = e
            print(f"[scraper] Failed {u}: {e}")
    raise SystemExit(f"All endpoints failed. Last error: {last_err}")

# ============================================================
# ================= TV Logos (GitHub tree) ===================
# ============================================================

def extract_payload_from_github_tree_html(html: str) -> dict:
    """
    Extract GitHub embedded payload JSON and build a raw.githubusercontent.com prefix.
    """
    soup = BeautifulSoup(html, 'html.parser')

    script_tag = soup.find('script', {
        'type': 'application/json',
        'data-target': 'react-app.embeddedData'
    })
    if not script_tag or not script_tag.string:
        print('Script tag with the payload not found.')
        return {}

    data = json.loads(script_tag.string)
    payload = data.get('payload', {})

    repo = payload.get('repo', {}) or payload.get('repository', {})
    owner_login = (repo.get('ownerLogin')
                   or repo.get('owner', {}).get('login')
                   or 'tv-logo')
    repo_name = repo.get('name') or 'tv-logos'
    branch = (
        payload.get('refInfo', {}).get('name')
        or payload.get('ref', 'main')
        or 'main'
    )
    current_path = (
        payload.get('path')
        or payload.get('currentPath')
        or 'countries/united-states'
    ).lstrip('/')

    initial_path = f"/{owner_login}/{repo_name}/{branch}/"
    payload['initial_path'] = initial_path
    payload['current_path'] = current_path
    return payload

def search_tree_items(search_string: str, json_obj: dict) -> List[dict]:
    """
    Searches payload.tree.items[] for filenames containing parts of search_string.
    Returns list of {'id': {'path': <path>}, 'source': ''}.
    """
    matches = []
    search_words = (search_string or "").lower().split()
    tree = json_obj.get('tree', {})
    items = tree.get('items', [])
    for item in items:
        name = (item.get('name') or '').lower()
        if not name:
            continue
        if any(w in name for w in search_words):
            path = item.get('path') or json_obj.get('current_path', '') + '/' + item.get('name', '')
            matches.append({'id': {'path': path}, 'source': ''})
    return matches

# ============================================================
# ======================= Scraper main =======================
# ============================================================

CI_MODE = os.getenv("CI") == "1" or os.getenv("AUTO") == "1"
CHANNELS_ENV = [t.strip() for t in os.getenv("CHANNELS", "").split(",") if t.strip()]
OUT_M3U = "out.m3u8"

CHANNEL_ENDPOINTS = [
    "https://dlhd.dad/daddy.json",
    "https://daddylivestream.com/daddy.json",
    "http://dlhd.dad/daddy.json",
]

TV_LOGOS_ENDPOINTS = [
    "https://github.com/tv-logo/tv-logos/tree/main/countries/united-states",
]

# folders where stream-<id>.php can live
PLAYER_FOLDERS = ["stream", "cast", "watch", "plus", "casting", "player"]

# logo overrides (exact names from API)
LOGO_OVERRIDES = {
    "NFL Network": "countries/united-states/nfl-network.png",
    "ESPN": "countries/united-states/espn.png",
    "ESPN2": "countries/united-states/espn2.png",
    "ABC USA": "countries/united-states/abc-us.png",
    "NBC": "countries/united-states/nbc.png",
    "CBS": "countries/united-states/cbs.png",
    "FOX": "countries/united-states/fox.png",
    "FS1": "countries/united-states/fox-sports-1.png",
    "TNT": "countries/united-states/tnt.png",
    "NBA TV": "countries/united-states/nba-tv.png",
}

def nuke(path: str):
    if os.path.isfile(path):
        os.remove(path)

def normalize_name(s: str) -> str:
    return (s or "").lower().replace("&", "and").replace("+", "plus").strip()

def tokens(s: str):
    return re.findall(r'[a-z0-9]+', normalize_name(s))

def best_fuzzy(needle: str, candidates: List[str]) -> Optional[str]:
    n = normalize_name(needle)
    cand_norm = [normalize_name(c) for c in candidates]
    for i, c in enumerate(cand_norm):
        if c == n:
            return candidates[i]
    nt = set(tokens(n))
    best_i, best_score = None, 0
    for i, c in enumerate(cand_norm):
        ct = set(tokens(c))
        inter = len(nt & ct)
        if inter > best_score:
            best_i, best_score = i, inter
    if best_i is not None and best_score >= 1:
        return candidates[best_i]
    m = difflib.get_close_matches(n, cand_norm, n=1, cutoff=0.72)
    if m:
        j = cand_norm.index(m[0])
        return candidates[j]
    return None

def pick_logo_path(channel_name: str, payload: dict) -> str:
    override = LOGO_OVERRIDES.get(channel_name)
    if override:
        return override

    word = normalize_name(channel_name)
    matches = search_tree_items(word, payload)
    if not matches:
        cleaned = re.sub(r'\b(network|channel|hd|tv|usa)\b', '', word).strip()
        if cleaned and cleaned != word:
            matches = search_tree_items(cleaned, payload)
    if not matches:
        return ""
    def score(m):
        path = (m.get('id') or {}).get('path', '')
        base = os.path.basename(path).lower()
        base = re.sub(r'\.(png|svg|jpg|jpeg)$', '', base)
        base_tokens = set(tokens(base))
        name_tokens = set(tokens(channel_name))
        return (
            100 if base_tokens == name_tokens else 0,
            len(base_tokens & name_tokens),
            -abs(len(base) - len(channel_name)),
        )
    matches.sort(key=score, reverse=True)
    return (matches[0].get('id') or {}).get('path', '')

# ---------- HLS Extraction ----------

M3U8_PATTERNS = [
    re.compile(r'https?://[^\s\'"]+\.m3u8[^\s\'"]*', re.I),
    re.compile(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', re.I),
]

B64_PAT = re.compile(r'(?:atob\(|btoa\()["\']([A-Za-z0-9+/=]{12,})["\']\)?', re.I)
SRC_PAT = re.compile(r'(?:src|data-src)\s*=\s*["\'](https?://[^"\']+)["\']', re.I)

def decode_possible_b64(s: str) -> List[str]:
    found = []
    for m in B64_PAT.findall(s or ""):
        try:
            dec = base64.b64decode(m + "===")  # tolerate missing padding
            dec = dec.decode("utf-8", errors="ignore")
            if ".m3u8" in dec:
                found.append(dec)
        except Exception:
            pass
    return found

def parse_m3u8_from_html(html: str) -> Optional[str]:
    # 1) direct .m3u8 in page
    for pat in M3U8_PATTERNS:
        hit = pat.search(html or "")
        if hit:
            return hit.group(0).strip('"\'')
    # 2) base64-encoded URLs commonly used in scripts
    for dec in decode_possible_b64(html or ""):
        for pat in M3U8_PATTERNS:
            hit = pat.search(dec)
            if hit:
                return hit.group(0).strip('"\'')
    return None

def find_iframe_srcs(html: str) -> List[str]:
    srcs = []
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all("iframe"):
        s = tag.get("src") or tag.get("data-src")
        if s:
            srcs.append(s)
    # also check generic src/data-src in raw HTML
    srcs += SRC_PAT.findall(html or "")
    # de-dup while preserving order
    seen = set()
    uniq = []
    for u in srcs:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq

def resolve_hls_for_channel_id(ch_id: str) -> Optional[str]:
    """
    Try each folder; parse page, follow iframes (one hop), look for .m3u8.
    Returns HLS URL or None.
    """
    # Try folders in order; some may be blocked, others work
    for folder in PLAYER_FOLDERS:
        page = f"https://dlhd.dad/{folder}/stream-{ch_id}.php"
        try:
            # first load the player page
            _, html = fetch_first_ok_text([page], referer="https://dlhd.dad/")
            # look for direct .m3u8
            m3u8 = parse_m3u8_from_html(html)
            if m3u8:
                return m3u8

            # follow first-level iframes and scan them too
            for iframe_url in find_iframe_srcs(html):
                # normalize protocol-less // URLs
                if iframe_url.startswith("//"):
                    iframe_url = "https:" + iframe_url
                try:
                    _, iframe_html = fetch_first_ok_text([iframe_url], referer=page)
                    m3u8 = parse_m3u8_from_html(iframe_html)
                    if m3u8:
                        return m3u8
                except Exception as e:
                    print(f"[hls] iframe fetch failed {iframe_url}: {e}")
        except Exception as e:
            print(f"[hls] page fetch failed {page}: {e}")
    return None

# ---------- Main ----------

def main():
    nuke(OUT_M3U)

    # Channels JSON
    used_url, channels_text = fetch_first_ok_text(CHANNEL_ENDPOINTS)
    print(f"[scraper] Using channels source: {used_url}")
    try:
        channels_data = json.loads(channels_text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Failed to parse channels JSON from {used_url}: {e}")
    if not isinstance(channels_data, list):
        raise SystemExit("Channels JSON is not a list.")

    # Logos payload
    _, logos_html = fetch_first_ok_text(TV_LOGOS_ENDPOINTS)
    payload = extract_payload_from_github_tree_html(logos_html)
    initial_raw_prefix = payload.get('initial_path', '')

    # Targets
    targets = set(CHANNELS_ENV)
    if os.path.isfile("channels.txt"):
        with open("channels.txt", "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    targets.add(s)
    process_all = (len(targets) == 0)

    all_names = [c.get("channel_name","") for c in channels_data if "channel_name" in c and "channel_id" in c]
    name_to_id = {c["channel_name"]: c["channel_id"] for c in channels_data if "channel_name" in c and "channel_id" in c}

    def iter_target_channels():
        if process_all:
            for nm in all_names:
                yield nm, name_to_id[nm]
        else:
            for want in targets:
                got = best_fuzzy(want, all_names)
                if got and got in name_to_id:
                    yield got, name_to_id[got]
                else:
                    print(f"[warn] Could not match requested channel: {want}")

    # Write M3U
    added = 0
    with open(OUT_M3U, "a", encoding="utf-8") as m3u:
        for display_name, ch_id in iter_target_channels():
            # try to resolve HLS
            hls = resolve_hls_for_channel_id(ch_id)
            if hls:
                final_url = hls
            else:
                # fallback: player page
                final_url = f"https://dlhd.dad/stream/stream-{ch_id}.php"

            logo_rel = pick_logo_path(display_name, payload)
            logo_url = f"https://raw.githubusercontent.com{initial_raw_prefix}{logo_rel}" if logo_rel else ""

            m3u.write(
                f"#EXTINF:-1 tvg-name=\"{display_name}\" "
                f"tvg-logo=\"{logo_url}\" group-title=\"USA (DADDY LIVE)\", {display_name}\n"
            )
            m3u.write(final_url + "\n\n")
            added += 1

    print(f"Total channels in API: {len(all_names)}")
    print(f"Channels added: {added}")

    if added == 0:
        raise SystemExit("No channels added. Check CHANNELS/channels.txt or endpoint availability.")

if __name__ == "__main__":
    main()
