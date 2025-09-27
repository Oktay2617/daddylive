from bs4 import BeautifulSoup
import os
import json
import tvlogo
import fetcher

# Filenames and URLs
daddyLiveChannelsFileName = '247channels.html'
daddyLiveChannelsURL = 'https://thedaddy.to/24-7-channels.php'

tvLogosFilename = 'tvlogos.html'
tvLogosURL = 'https://github.com/tv-logo/tv-logos/tree/main/countries/united-states'

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

# ----------------------
# Cleanup old files
# ----------------------
delete_file_if_exists('out.m3u8')
delete_file_if_exists('tvg-ids.txt')

# ----------------------
# Fetch HTML pages
# ----------------------
fetcher.fetchHTML(daddyLiveChannelsFileName, daddyLiveChannelsURL)
fetcher.fetchHTML(tvLogosFilename, tvLogosURL)

# ----------------------
# Define search terms
# ----------------------
search_terms = [
    "nfl network"  # Add more channel keywords here if needed
]

# ----------------------
# Extract payload from TV logos HTML
# ----------------------
payload = tvlogo.extract_payload_from_file(tvLogosFilename)
print(json.dumps(payload, indent=2))

# ----------------------
# Search for channels locally
# ----------------------
for term in search_terms:
    search_streams(daddyLiveChannelsFileName, term)

# ----------------------
# Generate M3U playlist
# ----------------------
for channel in matches:
    # Ask user whether to include this channel
    user_input = int(input(f"Do you want this channel? 0 = no, 1 = yes ({channel[1]}): "))
    if user_input == 0:
        continue

    # Search for matching logos
    word = channel[1].lower().replace('channel','').replace('tv','').replace('hd','').strip()
    logo_matches = tvlogo.search_tree_items(word, payload)

    # Let user pick a logo
    tvicon = None
    if logo_matches:
        tvicon = logo_matches[0]  # Auto pick first match (optional: add interactive selection)

    # Write M3U entry
    initialPath = payload.get('initial_path', '')
    with open("out.m3u8", 'a', encoding='utf-8') as file:
        file.write(
            f"#EXTINF:-1 tvg-name=\"{channel[1]}\" "
            f"tvg-logo=\"https://raw.githubusercontent.com{initialPath}{tvicon['id']['path'] if tvicon else ''}\" "
            f"group-title=\"USA (DADDY LIVE)\",{channel[1]}\n"
        )
        file.write(f"https://xyzdddd.mizhls.ru/lb/premium{channel[0]}/index.m3u8\n\n")

    # Write the channel ID (stream number) to tvg-ids.txt
    with open("tvg-ids.txt", 'a', encoding='utf-8') as file:
        file.write(f"{channel[0]}\n")

print("Number of Streams:", len(matches))
