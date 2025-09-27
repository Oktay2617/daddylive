from bs4 import BeautifulSoup
import os
import json
import requests

# ----------------------
# Configuration
# ----------------------
daddyLiveChannelsFileName = '247channels.html'
daddyLiveChannelsURL = 'https://thedaddy.to/24-7-channels.php'

tvLogosFilename = 'tvlogos.html'
tvLogosURL = 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/united-states'

matches = []

# ----------------------
# Utility Functions
# ----------------------
def fetchHTML(filename, url):
    if os.path.isfile(filename):
        print(f"File exists, not downloading new version {filename}.")
        return
    print(f"Fetching {url} ...")
    r = requests.get(url)
    r.raise_for_status()
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(r.text)

def search_streams(file_path, keyword):
    """Search HTML for channels containing keyword"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
            soup = BeautifulSoup(content, 'html.parser')
            links = soup.find_all('a', href=True)

            for link in links:
                if keyword.lower() in link.text.lower():
                    href = link['href']
                    stream_number = href.split('-')[-1].replace('.php', '')
                    stream_name = link.text.strip()
                    match = (stream_number, stream_name)
                    if match not in matches:
                        matches.append(match)
    except FileNotFoundError:
        print(f"The file {file_path} does not exist.")
    return matches

def fetch_tvlogos_html(url, filename):
    if os.path.isfile(filename):
        print(f"File exists, not download new version {filename}.")
        return
    print(f"Fetching TV logos from {url} ...")
    r = requests.get(url)
    if r.status_code != 200:
        raise Exception(f"Failed to fetch {url}, status code {r.status_code}")
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(r.text)

def extract_tvlogos(filename):
    """Extract logos from local HTML"""
    payload = {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            items = soup.find_all('img')
            payload['items'] = [{'path': img.get('src', '')} for img in items]
            payload['initial_path'] = ''
    except Exception as e:
        print("Error extracting TV logos:", e)
    return payload

# ----------------------
# Remove old files
# ----------------------
for f in ['out.m3u8', 'tvg-ids.txt']:
    if os.path.isfile(f):
        os.remove(f)

# ----------------------
# Fetch HTML
# ----------------------
fetchHTML(daddyLiveChannelsFileName, daddyLiveChannelsURL)
fetch_tvlogos_html(tvLogosURL, tvLogosFilename)
payload = extract_tvlogos(tvLogosFilename)

# ----------------------
# Define search terms
# ----------------------
search_terms = [
    "nfl network"
]

# ----------------------
# Search channels
# ----------------------
for term in search_terms:
    search_streams(daddyLiveChannelsFileName, term)

# ----------------------
# Write M3U playlist
# ----------------------
for channel in matches:
    with open("out.m3u8", 'a', encoding='utf-8') as file:
        file.write(
            f"#EXTINF:-1 tvg-id=\"{channel[1]}\" tvg-name=\"{channel[1]}\" "
            f"tvg-logo=\"https://raw.githubusercontent.com{payload['initial_path']}{payload['items'][0]['path']}\" "
            f"group-title=\"USA (DADDY LIVE)\", {channel[1]}\n"
        )
        file.write(f"https://xyzdddd.mizhls.ru/lb/premium{channel[0]}/index.m3u8\n\n")

    with open("tvg-ids.txt", 'a', encoding='utf-8') as file:
        file.write(f"{channel[1]}\n")

print("Number of Streams: ", len(matches))
