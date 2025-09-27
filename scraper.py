import os
import re
import json
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

import tvlogo
import fetcher

CI_MODE = os.getenv("CI") == "1" or os.getenv("AUTO") == "1"

daddyLiveChannelsFileName = '247channels.html'
daddyLiveChannelsURL = 'https://thedaddy.to/24-7-channels.php'

tvLogosFilename = 'tvlogos.html'
tvLogosURL = 'https://github.com/tv-logo/tv-logos/tree/main/countries/united-states'

matches = []

def nonempty_file(path):
    return os.path.isfile(path) and os.path.getsize(path) > 2000  # ~2KB min

def parse_stream_number(href: str) -> str:
    # try original pattern first
    tail = href.split('-')[-1]
    if tail.endswith('.php'):
        return tail.replace('.php', '')
    # fallback: last run of digits in the href
    m = re.findall(r'(\d+)(?!.*\d)', href)
    return m[0] if m else ''

def search_streams(file_path, keyword):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        soup = BeautifulSoup(content, 'html.parser')
        links = soup.find_all('a', href=True)
        for link in links:
            text = (link.text or '').strip()
            if keyword.lower() in text.lower():
                href = link['href']
                num = parse_stream_number(href)
                if not num:
                    continue
                match = (num, text)
                if match not in matches:
                    matches.append(match)
    except FileNotFoundError:
        print(f"The file {file_path} does not exist.")
    return matches

def search_channel_ids(file_path, search_string, idMatches):
    search_words = search_string.lower().split()
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        for channel in root.findall('.//channel'):
            cid = channel.get('id')
            if not cid:
                continue
            low = cid.lower()
            if any(w in low for w in search_words):
                if cid not in [c['id'] for c in idMatches]:
                    idMatches.append({'id': cid, 'source': file_path})
    except FileNotFoundError:
        print(f"The file {file_path} does not exist.")
    except ET.ParseError:
        print(f"The file {file_path} is not a valid XML file.")
    return idMatches

def pick_best_match(options, needle_lower):
    """Return the dict with 'id' key best matching needle_lower."""
    if not options:
        return None
    # score by: contains full needle, length (prefer longer, often more specific)
    def score(opt):
        s = opt['id'].lower()
        return (1 if needle_lower in s else 0, len(s))
    return sorted(options, key=score, reverse=True)[0]

def pick_best_logo(options, needle_lower):
    if not options:
        return None
    def score(opt):
        # tvlogo returns {'id': {'path': ...}}; use path text for scoring
        p = (opt.get('id') or {}).get('path', '')
        low = p.lower()
        return (1 if needle_lower in low else 0, len(low))
    return sorted(options, key=score, reverse=True)[0]

def delete_file_if_exists(file_path):
    if os.path.isfile(file_path):
        os.remove(file_path)
        print(f"File {file_path} deleted.")

# Delete old files
delete_file_if_exists('out.m3u8')
delete_file_if_exists('tvg-ids.txt')

# EPGs
epgs = [
    {'filename': 'epgShare1.xml', 'url': 'https://epgshare01.online/epgshare01/epg_ripper_US1.xml.gz'},
    {'filename': 'epgShare2.xml', 'url': 'https://epgshare01.online/epgshare01/epg_ripper_US_LOCALS2.xml.gz'},
    {'filename': 'epgShare3.xml', 'url': 'https://epgshare01.online/epgshare01/epg_ripper_CA1.xml.gz'},
    {'filename': 'epgShare4.xml', 'url': 'https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz'},
    {'filename': 'epgShare5.xml', 'url': 'https://epgshare01.online/epgshare01/epg_ripper_AU1.xml.gz'},
    {'filename': 'epgShare6.xml', 'url': 'https://epgshare01.online/epgshare01/epg_ripper_IE1.xml.gz'},
    {'filename': 'epgShare7.xml', 'url': 'https://epgshare01.online/epgshare01/epg_ripper_DE1.xml.gz'},
    {'filename': 'epgShare8.xml', 'url': 'https://epgshare01.online/epgshare01/epg_ripper_ZA1.xml.gz'},
    {'filename': 'epgShare9.xml', 'url': 'https://epgshare01.online/epgshare01/epg_ripper_IL1.xml.gz'},
    {'filename': 'bevyCustom.xml', 'url': 'https://www.bevy.be/generate/8TbvgWSctM.xml.gz'},
]

# Fetch HTML pages (ensure UA/retries inside fetcher)
fetcher.fetchHTML(daddyLiveChannelsFileName, daddyLiveChannelsURL)
fetcher.fetchHTML(tvLogosFilename, tvLogosURL)

if not nonempty_file(daddyLiveChannelsFileName):
    raise SystemExit("DaddyLive HTML looks empty/blocked. Add a desktop User-Agent & retries in fetcher.fetchHTML.")

# Fetch EPG files
for epg in epgs:
    fetcher.fetchXML(epg['filename'], epg['url'])

# TERMS: from env CHANNELS or channels.txt, else fallback list
env_terms = [t.strip() for t in os.getenv("CHANNELS","").split(",") if t.strip()]
file_terms = []
if os.path.isfile("channels.txt"):
    with open("channels.txt","r",encoding="utf-8") as f:
        file_terms = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]

search_terms = env_terms or file_terms or [
    "NFL Network","ESPN","ESPN2","TNT","NBA TV","FS1","NBC","ABC","CBS","FOX"
]

# TV logo payload
payload = tvlogo.extract_payload_from_file(tvLogosFilename)
print(json.dumps({"logo_index_len": len(payload.get("tree_items", []))}, indent=2))

# Collect matches
for term in search_terms:
    search_streams(daddyLiveChannelsFileName, term)

# Normalize helper
def normalize(name: str) -> str:
    return (name.lower()
            .replace('channel','')
            .replace('hdtv','')
            .replace('tv','')
            .replace(' hd','')
            .replace('sports','')
            .replace('usa','')
            .replace('2','')
            .replace('1','')
            .strip())

added = 0
initialPath = payload.get('initial_path', '')

for channel in matches:
    stream_num, display_name = channel
    word = normalize(display_name)
    possibleIds = []

    # Search EPG IDs
    for epg in epgs:
        search_channel_ids(epg['filename'], word, possibleIds)

    # Pick best EPG id
    channelID = pick_best_match(possibleIds, word)

    # Find logos
    logo_matches = tvlogo.search_tree_items(word, payload)
    tvicon = pick_best_logo(logo_matches, word)
    logo_path = ""
    if tvicon and isinstance(tvicon.get('id'), dict):
        logo_path = tvicon['id'].get('path','')

    if channelID:
        with open("out.m3u8", 'a', encoding='utf-8') as f:
            f.write(
                f"#EXTINF:-1 tvg-id=\"{channelID['id']}\" tvg-name=\"{display_name}\" "
                f"tvg-logo=\"https://raw.githubusercontent.com{initialPath}{logo_path}\" "
                f"group-title=\"USA (DADDY LIVE)\", {display_name}\n"
            )
            f.write(f"https://xyzdddd.mizhls.ru/lb/premium{stream_num}/index.m3u8\n\n")
        with open("tvg-ids.txt", 'a', encoding='utf-8') as f:
            f.write(f"{channelID['id']}\n")
        added += 1
    else:
        print(f"No EPG id found for: {display_name}")

print("Number of Streams Found on page: ", len(matches))
print("Number of Channels Added: ", added)

if added == 0:
    raise SystemExit("No channels added: check fetcher (blocked HTML?) or broaden CHANNELS.")
