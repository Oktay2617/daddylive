from bs4 import BeautifulSoup
import os
import json
import requests
import tvlogo
import fetcher

# Filenames and URLs
daddyLiveChannelsFileName = '247channels.html'
daddyLiveChannelsURL = 'https://thedaddy.to/24-7-channels.php'

tvLogosFilename = 'tvlogos.html'
tvLogosAPI = 'https://api.github.com/repos/tv-logo/tv-logos/contents/countries/united-states'

matches = []

# ----------------------
# Helper functions
# ----------------------
def search_streams(file_path, keyword):
    """Search local HTML file for channels matching keyword"""
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

def delete_file_if_exists(file_path):
    """Delete a file if it exists"""
    if os.path.isfile(file_path):
        os.remove(file_path)
        print(f"File {file_path} deleted.")

def fetch_github_logos(api_url):
    """Fetch all logo URLs from GitHub API"""
    response = requests.get(api_url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch logos from GitHub API, status {response.status_code}")
    
    data = response.json()
    logos = {}
    for item in data:
        if item['name'].lower().endswith('.png'):
            channel_name = item['name'].rsplit('.', 1)[0].lower()
            logos[channel_name] = item['download_url']
    return logos

# ----------------------
# Cleanup old files
# ----------------------
delete_file_if_exists('out.m3u8')
delete_file_if_exists('tvg-ids.txt')

# ----------------------
# Fetch HTML pages
# ----------------------
fetcher.fetchHTML(daddyLiveChannelsFileName, daddyLiveChannelsURL)

# ----------------------
# Fetch TV logos dynamically via GitHub API
# ----------------------
tv_logos = fetch_github_logos(tvLogosAPI)

# ----------------------
# Define search terms
# ----------------------
search_terms = [
    "nfl network"  # Add more channel keywords here
]

# ----------------------
# Search for channels locally
# ----------------------
for term in search_terms:
    search_streams(daddyLiveChannelsFileName, term)

# ----------------------
# Generate M3U playlist
# ----------------------
for channel in matches:
    # Auto-include all found channels
    key = channel[1].lower().replace('channel','').replace('tv','').replace('hd','').strip()
    
    # Match a logo if exists
    tvicon_url = ''
    for logo_name, logo_url in tv_logos.items():
        if logo_name in key:
            tvicon_url = logo_url
            break

    # Write M3U entry
    with open("out.m3u8", 'a', encoding='utf-8') as file:
        file.write(
            f"#EXTINF:-1 tvg-name=\"{channel[1]}\" "
            f"tvg-logo=\"{tvicon_url}\" "
            f"group-title=\"USA (DADDY LIVE)\",{channel[1]}\n"
        )
        file.write(f"https://xyzdddd.mizhls.ru/lb/premium{channel[0]}/index.m3u8\n\n")

    # Write the channel ID to tvg-ids.txt
    with open("tvg-ids.txt", 'a', encoding='utf-8') as file:
        file.write(f"{channel[0]}\n")

print("Number of Streams:", len(matches))
