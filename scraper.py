# scraper.py (EPG-free + logo overrides)
import os
import json
import re
import difflib

import fetcher
import tvlogo

# ---- Config ----
CI_MODE = os.getenv("CI") == "1" or os.getenv("AUTO") == "1"
CHANNELS_ENV = [t.strip() for t in os.getenv("CHANNELS", "").split(",") if t.strip()]

DADDY_CHANNELS_JSON = "daddy.json"
DADDY_CHANNELS_URL  = "https://dlhd.dad/daddy.json"

TVLOGOS_HTML = "tvlogos.html"
TVLOGOS_URL  = "https://github.com/tv-logo/tv-logos/tree/main/countries/united-states"

OUT_M3U = "out.m3u8"

# ---------- Logo overrides ----------
# Key: exact channel display name from daddy.json
# Value: path relative to repo root (works with initial_path prefix), e.g.
#        "countries/united-states/espn.png"
LOGO_OVERRIDES = {
    "NFL Network": "countries/united-states/nfl-network.png",
    "ESPN": "countries/united-states/espn.png",
    "ESPN2": "countries/united-states/espn2.png",
    "ABC": "countries/united-states/abc.png",
    "NBC": "countries/united-states/nbc.png",
    "CBS": "countries/united-states/cbs.png",
    "FOX": "countries/united-states/fox.png",
    "FS1": "countries/united-states/fox-sports-1.png",   # adjust if different in repo
    "TNT": "countries/united-states/tnt.png",
    "NBA TV": "countries/united-states/nba-tv.png",
    # add more exact names as needed...
}

def nuke(path):
    if os.path.isfile(path):
        os.remove(path)

def normalize_name(s: str) -> str:
    return (s or "").lower().replace("&", "and").replace("+", "plus").strip()

def tokens(s: str):
    return re.findall(r'[a-z0-9]+', normalize_name(s))

def best_fuzzy(needle: str, candidates: list[str]) -> str | None:
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
    """Prefer overrides; else fuzzy-find in tv-logos tree."""
    override = LOGO_OVERRIDES.get(channel_name)
    if override:
        return override

    word = normalize_name(channel_name)
    matches = tvlogo.search_tree_items(word, payload)
    if not matches:
        cleaned = re.sub(r'\b(network|channel|hd|tv|usa)\b', '', word).strip()
        if cleaned and cleaned != word:
            matches = tvlogo.search_tree_items(cleaned, payload)
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

# ---- Start fresh ----
nuke(OUT_M3U)

# ---- Fetch channels JSON ----
fetcher.fetchHTML(DADDY_CHANNELS_JSON, DADDY_CHANNELS_URL)
with open(DADDY_CHANNELS_JSON, 'r', encoding='utf-8') as f:
    channels_data = json.load(f)
if not isinstance(channels_data, list):
    raise SystemExit("daddy.json is not a list.")

# ---- Fetch logos tree ----
fetcher.fetchHTML(TVLOGOS_HTML, TVLOGOS_URL)
payload = tvlogo.extract_payload_from_file(TVLOGOS_HTML)
initial_raw_prefix = payload.get('initial_path', '')  # e.g. "/tv-logo/tv-logos/main/"

# ---- Target selection ----
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
            got = best_fuzzy(want, all_names) or None
            if got and got in name_to_id:
                yield got, name_to_id[got]
            else:
                print(f"[warn] Could not match requested channel: {want}")

# ---- Write M3U ----
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
    raise SystemExit("No channels added. Check CHANNELS/channels.txt or API availability.")
