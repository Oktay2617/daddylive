#!/usr/bin/env python3
# scraper.py — single-file version (fetcher + tvlogo + scraper)
# Requires: requests, beautifulsoup4

import os
import re
import json
import difflib
import time
import requests
from typing import Optional
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

def _session(timeout: float = 20.0) -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    # note: requests doesn't use a session-wide timeout argument directly; we'll pass per-call
    return s

def _looks_blocked_or_tiny(text: str) -> bool:
    if not text or len(text) < 1500:
        return True
    needles = [
        "just a moment", "rate limit", "access denied", "captcha",
        "request blocked", "attention required!", "you have been blocked"
    ]
    low = text.lower()
    return any(n in low for n in needles)

def http_get_text(url: str, *, tries: int = 4, sleep: float = 1.0, allow_4xx: bool = True, verify: bool = True) -> str:
    """
    GET URL and return response.text. Retries, optional TLS verify control.
    """
    sess = _session()
    last_exc: Optional[Exception] = None
    for i in range(tries):
        try:
            resp = sess.get(url, timeout=30, verify=verify)
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

def fetch_first_ok_text(urls: list[str]) -> tuple[str, str]:
    """
    Try a list of URLs; return (used_url, response_text).
    For dlhd.dad, if TLS fails, retry once with verify=False (loudly).
    """
    last_err = None
    for u in urls:
        print(f"[scraper] Trying {u}")
        try:
            try:
                text = http_get_text(u, tries=4, sleep=1.0, allow_4xx=True, verify=True)
            except SSLError as e:
                if "dlhd.dad" in u or os.getenv("DLHD_INSECURE") == "1":
                    print(f"[fetcher] TLS verify failed for {u}. Retrying ONCE with verify=False (insecure).")
                    text = http_get_text(u, tries=1, sleep=0.5, allow_4xx=True, verify=False)
                else:
                    raise
            if _looks_blocked_or_tiny(text):
                raise SystemExit(f"[fetcher] {u} looks blocked/empty.")
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
    )
    current_path = current_path.lstrip('/')

    # Compose a raw content prefix
    initial_path = f"/{owner_login}/{repo_name}/{branch}/"

    payload['initial_path'] = initial_path
    payload['current_path'] = current_path
    return payload

def search_tree_items(search_string: str, json_obj: dict) -> list[dict]:
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

# ---- Config ----
CI_MODE = os.getenv("CI") == "1" or os.getenv("AUTO") == "1"
CHANNELS_ENV = [t.strip() for t in os.getenv("CHANNELS", "").split(",") if t.strip()]

OUT_M3U = "out.m3u8"

# Channel list endpoints (try in order)
CHANNEL_ENDPOINTS = [
    "https://dlhd.dad/daddy.json",               # may fail TLS occasionally
    "https://daddylivestream.com/daddy.json",    # mirror domain noted in docs
    "http://dlhd.dad/daddy.json",                # last-resort (plain HTTP)
]

# GitHub tree (US logos)
TV_LOGOS_ENDPOINTS = [
    "https://github.com/tv-logo/tv-logos/tree/main/countries/united-states",
]

# ---------- Logo overrides ----------
# Key: exact channel display name from daddy.json
# Value: path relative to tv-logos repo root
LOGO_OVERRIDES = {
    "NFL Network": "countries/united-states/nfl-network.png",
    "ESPN": "countries/united-states/espn.png",
    "ESPN2": "countries/united-states/espn2.png",
    "ABC": "countries/united-states/abc.png",
    "NBC": "countries/united-states/nbc.png",
    "CBS": "countries/united-states/cbs.png",
    "FOX": "countries/united-states/fox.png",
    "FS1": "countries/united-states/fox-sports-1.png",  # adjust if different in repo
    "TNT": "countries/united-states/tnt.png",
    "NBA TV": "countries/united-states/nba-tv.png",
    # Add more exact-name overrides as you like...
}

def nuke(path: str):
    if os.path.isfile(path):
        os.remove(path)

def normalize_name(s: str) -> str:
    return (s or "").lower().replace("&", "and").replace("+", "plus").strip()

def tokens(s: str):
    return re.findall(r'[a-z0-9]+', normalize_name(s))

def best_fuzzy(needle: str, candidates: list[str]) -> Optional[str]:
    n = normalize_name(needle)
    cand_norm = [normalize_name(c) for c in candidates]
    # exact
    for i, c in enumerate(cand_norm):
        if c == n:
            return candidates[i]
    # token overlap
    nt = set(tokens(n))
    best_i, best_score = None, 0
    for i, c in enumerate(cand_norm):
        ct = set(tokens(c))
        inter = len(nt & ct)
        if inter > best_score:
            best_i, best_score = i, inter
    if best_i is not None and best_score >= 1:
        return candidates[best_i]
    # difflib
    m = difflib.get_close_matches(n, cand_norm, n=1, cutoff=0.72)
    if m:
        j = cand_norm.index(m[0])
        return candidates[j]
    return None

def pick_logo_path(channel_name: str, payload: dict) -> str:
    """Prefer overrides; else fuzzy-find in tv-logos tree."""
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

def main():
    # Start fresh
    nuke(OUT_M3U)

    # Fetch channels JSON from first working endpoint
    used_url, channels_text = fetch_first_ok_text(CHANNEL_ENDPOINTS)
    print(f"[scraper] Using channels source: {used_url}")
    try:
        channels_data = json.loads(channels_text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Failed to parse channels JSON from {used_url}: {e}")
    if not isinstance(channels_data, list):
        raise SystemExit("Channels JSON is not a list.")

    # Fetch tv-logos GitHub tree and extract payload
    _, logos_html = fetch_first_ok_text(TV_LOGOS_ENDPOINTS)
    payload = extract_payload_from_github_tree_html(logos_html)
    initial_raw_prefix = payload.get('initial_path', '')  # e.g. "/tv-logo/tv-logos/main/"

    # Targets: env CHANNELS and/or channels.txt; if empty, process all
    targets = set(CHANNELS_ENV)
    if os.path.isfile("channels.txt"):
        with open("channels.txt", "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    targets.add(s)
    process_all = (len(targets) == 0)

    # Build mapping
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
            logo_rel = pick_logo_path(display_name, payload)
            logo_url = f"https://raw.githubusercontent.com{initial_raw_prefix}{logo_rel}" if logo_rel else ""
            playable = f"https://dlhd.dad/stream/stream-{ch_id}.php"
            m3u.write(
                f"#EXTINF:-1 tvg-name=\"{display_name}\" "
                f"tvg-logo=\"{logo_url}\" group-title=\"USA (DADDY LIVE)\", {display_name}\n"
            )
            m3u.write(playable + "\n\n")
            added += 1

    print(f"Total channels in API: {len(all_names)}")
    print(f"Channels added: {added}")

    if added == 0:
        raise SystemExit("No channels added. Check CHANNELS/channels.txt or endpoint availability.")

if __name__ == "__main__":
    main()
