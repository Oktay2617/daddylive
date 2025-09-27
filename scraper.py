#!/usr/bin/env python3
# scraper.py — single-file fast version (concurrent HLS extraction + logo overrides)
# Requires: requests, beautifulsoup4

import os, re, json, difflib, time, base64
from typing import Optional, Tuple, List
import concurrent.futures as cf

import requests
from requests.exceptions import SSLError, RequestException
from bs4 import BeautifulSoup

# ==============================
# Speed-focused defaults (env)
# ==============================
FAST_MODE       = os.getenv("FAST", "1") == "1"
MAX_CHANNELS    = int(os.getenv("MAX_CHANNELS", "100" if FAST_MODE else "999999"))
CONCURRENCY     = int(os.getenv("CONCURRENCY", "12" if FAST_MODE else "6"))
FOLDERS_ENV     = os.getenv("FOLDERS", "stream" if FAST_MODE else "stream,player,cast,watch,plus,casting")
PLAYER_FOLDERS  = [f.strip() for f in FOLDERS_ENV.split(",") if f.strip()]
DLHD_INSECURE   = os.getenv("DLHD_INSECURE", "1") == "1"   # skip verify for dlhd.dad by default
REQ_TIMEOUT     = float(os.getenv("REQ_TIMEOUT", "10" if FAST_MODE else "20"))
RETRIES         = int(os.getenv("RETRIES", "1" if FAST_MODE else "3"))
IFRAME_HOPS     = int(os.getenv("IFRAME_HOPS", "1" if FAST_MODE else "2"))

CHANNELS_ENV = [t.strip() for t in os.getenv("CHANNELS", "").split(",") if t.strip()]
OUT_M3U      = "out.m3u8"

CHANNEL_ENDPOINTS = [
    "https://dlhd.dad/daddy.json",
    "https://daddylivestream.com/daddy.json",
    "http://dlhd.dad/daddy.json",
]

TV_LOGOS_ENDPOINTS = [
    "https://github.com/tv-logo/tv-logos/tree/main/countries/united-states",
]

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

def _sess() -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s

def http_get_text(url: str, *, referer: Optional[str] = None, verify: Optional[bool] = None) -> str:
    sess = _sess()
    headers = dict(DEFAULT_HEADERS)
    if referer: headers["Referer"] = referer

    # fast path: dlhd.dad often fails TLS — skip verify immediately if DLHD_INSECURE
    if verify is None:
        verify = not (DLHD_INSECURE and "dlhd.dad" in url)

    last = None
    for i in range(RETRIES):
        try:
            r = sess.get(url, headers=headers, timeout=REQ_TIMEOUT, verify=verify, allow_redirects=True)
            if 200 <= r.status_code < 300:
                return r.text
            last = f"HTTP {r.status_code}"
        except (SSLError, RequestException) as e:
            last = str(e)
        # no exponential backoff to keep it snappy, just a tiny sleep
        time.sleep(0.2)
    raise RuntimeError(f"GET failed: {url} ({last})")

# ---------- GitHub tv-logos parsing ----------
def extract_payload_from_github_tree_html(html: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    script_tag = soup.find('script', {
        'type': 'application/json',
        'data-target': 'react-app.embeddedData'
    })
    if not script_tag or not script_tag.string:
        return {}
    data = json.loads(script_tag.string)
    payload = data.get('payload', {}) or {}

    repo = payload.get('repo', {}) or payload.get('repository', {})
    owner_login = (repo.get('ownerLogin') or repo.get('owner', {}).get('login') or 'tv-logo')
    repo_name   = repo.get('name') or 'tv-logos'
    branch      = payload.get('refInfo', {}).get('name') or payload.get('ref', 'main') or 'main'
    current_path= (payload.get('path') or payload.get('currentPath') or 'countries/united-states').lstrip('/')

    payload['initial_path'] = f"/{owner_login}/{repo_name}/{branch}/"
    payload['current_path'] = current_path
    return payload

def search_tree_items(search_string: str, json_obj: dict) -> List[dict]:
    matches, search_words = [], (search_string or "").lower().split()
    for item in json_obj.get('tree', {}).get('items', []):
        name = (item.get('name') or '').lower()
        if name and any(w in name for w in search_words):
            path = item.get('path') or json_obj.get('current_path', '') + '/' + item.get('name', '')
            matches.append({'id': {'path': path}, 'source': ''})
    return matches

# ---------- Logo helpers ----------
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

def normalize_name(s: str) -> str:
    return (s or "").lower().replace("&", "and").replace("+", "plus").strip()

def tokens(s: str):
    return re.findall(r'[a-z0-9]+', normalize_name(s))

def best_fuzzy(needle: str, candidates: List[str]) -> Optional[str]:
    n = normalize_name(needle)
    cand_norm = [normalize_name(c) for c in candidates]
    for i, c in enumerate(cand_norm):
        if c == n: return candidates[i]
    nt = set(tokens(n))
    best_i, best_score = None, 0
    for i, c in enumerate(cand_norm):
        inter = len(nt & set(tokens(c)))
        if inter > best_score:
            best_i, best_score = i, inter
    if best_i is not None and best_score >= 1:
        return candidates[best_i]
    import difflib as dl
    m = dl.get_close_matches(n, cand_norm, n=1, cutoff=0.72)
    if m:
        j = cand_norm.index(m[0])
        return candidates[j]
    return None

def pick_logo_path(channel_name: str, payload: dict) -> str:
    if channel_name in LOGO_OVERRIDES:
        return LOGO_OVERRIDES[channel_name]
    word = normalize_name(channel_name)
    matches = search_tree_items(word, payload)
    if not matches:
        cleaned = re.sub(r'\b(network|channel|hd|tv|usa)\b', '', word).strip()
        if cleaned and cleaned != word:
            matches = search_tree_items(cleaned, payload)
    if not matches:
        return ""
    def score(m):
        base = os.path.basename((m.get('id') or {}).get('path','')).lower()
        base = re.sub(r'\.(png|svg|jpg|jpeg)$', '', base)
        return (len(set(tokens(base)) & set(tokens(channel_name))), -abs(len(base) - len(channel_name)))
    matches.sort(key=score, reverse=True)
    return (matches[0].get('id') or {}).get('path','')

# ---------- HLS extraction (fast) ----------
M3U8_PATTERNS = [
    re.compile(r'https?://[^\s\'"]+\.m3u8[^\s\'"]*', re.I),
    re.compile(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', re.I),
]
B64_PAT = re.compile(r'(?:atob\(|btoa\()["\']([A-Za-z0-9+/=]{12,})["\']\)?', re.I)

def decode_possible_b64(s: str) -> List[str]:
    found = []
    for m in B64_PAT.findall(s or ""):
        try:
            dec = base64.b64decode(m + "===")
            dec = dec.decode("utf-8", errors="ignore")
            if ".m3u8" in dec:
                found.append(dec)
        except Exception:
            pass
    return found

def parse_m3u8_from_html(html: str) -> Optional[str]:
    for pat in M3U8_PATTERNS:
        hit = pat.search(html or "")
        if hit:
            return hit.group(0).strip('"\'')
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
        if s: srcs.append(s)
    # de-dup
    seen, uniq = set(), []
    for u in srcs:
        if u.startswith("//"): u = "https:" + u
        if u not in seen:
            seen.add(u); uniq.append(u)
    return uniq[:2]  # cap to 2 iframes per page (speed)

def resolve_hls_for_channel_id(ch_id: str) -> Optional[str]:
    # Try configured folders; minimal retries/timeouts
    for folder in PLAYER_FOLDERS:
        page = f"https://dlhd.dad/{folder}/stream-{ch_id}.php"
        try:
            html = http_get_text(page, referer="https://dlhd.dad/")
            m3u8 = parse_m3u8_from_html(html)
            if m3u8:
                return m3u8
            # one hop into iframes (capped by IFRAME_HOPS)
            if IFRAME_HOPS > 0:
                for i, iframe_url in enumerate(find_iframe_srcs(html)):
                    if i >= IFRAME_HOPS: break
                    try:
                        iframe_html = http_get_text(iframe_url, referer=page)
                        m3u8 = parse_m3u8_from_html(iframe_html)
                        if m3u8: return m3u8
                    except Exception:
                        pass
        except Exception:
            pass
    return None

# ---------- Utility ----------
def nuke(path: str):
    if os.path.isfile(path):
        os.remove(path)

def fetch_first_ok_text(urls: List[str]) -> Tuple[str, str]:
    last_err = None
    for u in urls:
        try:
            txt = http_get_text(u)
            return u, txt
        except Exception as e:
            last_err = e
    raise SystemExit(f"All endpoints failed. Last error: {last_err}")

# ---------- Main ----------
def main():
    nuke(OUT_M3U)

    # Channels JSON (first working endpoint)
    used_url, channels_text = fetch_first_ok_text(CHANNEL_ENDPOINTS)
    try:
        channels_data = json.loads(channels_text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Failed to parse channels JSON from {used_url}: {e}")
    if not isinstance(channels_data, list):
        raise SystemExit("Channels JSON is not a list.")

    # Logos payload (GitHub)
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
    all_names = [c.get("channel_name","") for c in channels_data if "channel_name" in c and "channel_id" in c]
    name_to_id = {c["channel_name"]: c["channel_id"] for c in channels_data if "channel_name" in c and "channel_id" in c}

    def iter_targets():
        picked = []
        if targets:
            for want in targets:
                got = best_fuzzy(want, all_names)
                if got and got in name_to_id: picked.append(got)
        else:
            picked = all_names[:]
        # cap to MAX_CHANNELS
        return [(nm, name_to_id[nm]) for nm in picked[:MAX_CHANNELS]]

    todo = iter_targets()

    # Resolve HLS in parallel
    results = []
    with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as exe:
        futs = {exe.submit(resolve_hls_for_channel_id, ch_id): (name, ch_id) for name, ch_id in todo}
        for fut in cf.as_completed(futs):
            name, ch_id = futs[fut]
            hls = None
            try:
                hls = fut.result()
            except Exception:
                pass
            results.append((name, ch_id, hls))

    # Write M3U
    written = 0
    with open(OUT_M3U, "w", encoding="utf-8") as m3u:
        for display_name, ch_id, hls in results:
            final_url = hls or f"https://dlhd.dad/stream/stream-{ch_id}.php"
            logo_rel = pick_logo_path(display_name, payload)
            logo_url = f"https://raw.githubusercontent.com{initial_raw_prefix}{logo_rel}" if logo_rel else ""
            m3u.write(
                f"#EXTINF:-1 tvg-name=\"{display_name}\" "
                f"tvg-logo=\"{logo_url}\" group-title=\"USA (DADDY LIVE)\", {display_name}\n"
            )
            m3u.write(final_url + "\n\n")
            written += 1

    print(f"Channels processed (capped): {len(results)} / Max={MAX_CHANNELS}")
    print(f"Playlist entries written: {written}")
    if written == 0:
        raise SystemExit("No entries written — endpoints blocked or names didn’t match.")

if __name__ == "__main__":
    main()
