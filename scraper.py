from bs4 import BeautifulSoup
import os
import requests

# ----------------------
# Filenames and URLs
# ----------------------
daddyLiveChannelsFileName = '247channels.html'
daddyLiveChannelsURL = 'https://thedaddy.to/24-7-channels.php'

tvLogosAPI = 'https://api.github.com/repos/tv-logo/tv-logos/contents/countries/united-states'

matches = []

# ----------------------
# Helper functions
# ----------------------
def fetch_html(url, filename):
    """Fetch HTML and save locally"""
    if os.path.isfile(filename):
        print(f"File exists, not downloading: {filename}")
        return
    response = requests.get(url)
    if response.status_code == 200:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"Fetched {filename} from {url}")
    else:
        raise Exception(f"Failed to fetch {url}, status {response.status_code}")

def delete_file_if_exists(file_path):
    if os.path.isfile(file_path):
        os.remove(file_path)
        print(f"Deleted {file_path}")

def search_streams(file_path, keyword):
    """Search channels HTML for keyword"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
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
        print(f"{file_path} not found")
    return matches

def fetch_github_logos(api_url):
    """Fetch all logo PNG URLs from GitHub API"""
    response = requests.get(api_url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch logos from GitHub API: {response.status_code}")
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
# Fetch required files
# ----------------------
fetch_html(daddyLiveChannelsURL, daddyLiveChannelsFileName)

# Fetch logos dynamically
tv_logos = fetch_github_logos(tvLogosAPI)

# ----------------------
# Define search terms
# ----------------------
search_terms = ["nfl network"]  # Add more keywords if needed

# ----------------------
# Search channels
# ----------------------
for term in search_terms:
    search_streams(daddyLiveChannelsFileName, term)

# ----------------------
# Generate M3U playlist
# ----------------------
for channel in matches:
    key = channel[1].lower().replace('channel','').replace('tv','').replace('hd','').strip()
    tvicon_url = ''
    for logo_name, logo_url in tv_logos.items():
        if logo_name in key:
            tvicon_url = logo_url
            break

    # Write M3U entry
    with open("out.m3u8", 'a', encoding='utf-8') as f:
        f.write(
            f"#EXTINF:-1 tvg-name=\"{channel[1]}\" "
            f"tvg-logo=\"{tvicon_url}\" "
            f"group-title=\"USA (DADDY LIVE)\",{channel[1]}\n"
        )
        f.write(f"https://xyzdddd.mizhls.ru/lb/premium{channel[0]}/index.m3u8\n\n")

    # Write channel ID
    with open("tvg-ids.txt", 'a', encoding='utf-8') as f:
        f.write(f"{channel[0]}\n")

print("Number of streams:", len(matches))
