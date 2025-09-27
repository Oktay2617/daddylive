import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import os
import json
import yaml   # pip install pyyaml

# Local filenames
daddyLiveChannelsFileName = '247channels.html'
daddyLiveChannelsURL = 'https://thedaddy.to/24-7-channels.php'

tvLogosFilename = 'tvlogos.html'
tvLogosURL = 'https://github.com/tv-logo/tv-logos/tree/main/countries/united-states'

# Ensure output directory exists
os.makedirs("output", exist_ok=True)

def fetch_html(url, local_filename):
    """Fetch and cache HTML to a local file"""
    if not os.path.exists(local_filename):
        print(f"Fetching {url} ...")
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        with open(local_filename, "w", encoding="utf-8") as f:
            f.write(resp.text)
    else:
        print(f"Using cached {local_filename}")
    return open(local_filename, encoding="utf-8").read()


def scrape_daddylive_channels():
    """Scrape channel list from daddylive 24/7 page"""
    html = fetch_html(daddyLiveChannelsURL, daddyLiveChannelsFileName)
    soup = BeautifulSoup(html, "html.parser")

    channels = []
    for link in soup.select("a"):
        href = link.get("href", "")
        name = link.text.strip()
        if "24-7-" in href.lower() or "channel" in href.lower():
            channels.append({
                "name": name,
                "url": href
            })
    return channels


def scrape_tvlogos():
    """Scrape available logo list from GitHub directory HTML"""
    html = fetch_html(tvLogosURL, tvLogosFilename)
    soup = BeautifulSoup(html, "html.parser")

    logos = []
    for a in soup.select("a.js-navigation-open"):
        href = a.get("href", "")
        if href.endswith((".png", ".jpg", ".svg")):
            logos.append({
                "logo_name": a.text.strip(),
                "logo_url": "https://raw.githubusercontent.com" + href.replace("/blob/", "/")
            })
    return logos


def save_json(data, filename):
    with open(os.path.join("output", filename), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved {filename}")


def save_xml(data, filename, root_tag="channels", item_tag="channel"):
    root = ET.Element(root_tag)
    for item in data:
        ch = ET.SubElement(root, item_tag)
        for k, v in item.items():
            el = ET.SubElement(ch, k)
            el.text = v
    tree = ET.ElementTree(root)
    tree.write(os.path.join("output", filename), encoding="utf-8", xml_declaration=True)
    print(f"Saved {filename}")


def save_yaml(data, filename):
    with open(os.path.join("output", filename), "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)
    print(f"Saved {filename}")


if __name__ == "__main__":
    # Scrape both sources
    daddylive_channels = scrape_daddylive_channels()
    tvlogos = scrape_tvlogos()

    # Save outputs
    save_json(daddylive_channels, "daddylive_channels.json")
    save_xml(daddylive_channels, "daddylive_channels.xml")
    save_yaml(daddylive_channels, "daddylive_channels.yml")

    save_json(tvlogos, "tvlogos.json")
    save_xml(tvlogos, "tvlogos.xml")
    save_yaml(tvlogos, "tvlogos.yml")
