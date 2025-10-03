#!/usr/bin/env python3
# scraper.py (Her Kanal İçin Özel Header Ekleyen Son Versiyon)
# Gerekli kütüphaneler: requests, beautifulsoup4, selenium, webdriver-manager, selenium-wire, blinker==1.7.0

import os
import re
import json
import time
from typing import Optional, Tuple, List, Dict, Any
import concurrent.futures as cf

import requests
from bs4 import BeautifulSoup

# Selenium-wire'dan webdriver'ı import ediyoruz
from seleniumwire import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, WebDriverException

# =============================
# Ayarlar ve Sabitler
# =============================
FAST_MODE = os.getenv("FAST", "1") == "1"
MAX_CHANNELS = int(os.getenv("MAX_CHANNELS", "25" if FAST_MODE else "999999"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "2" if FAST_MODE else "2"))
FOLDERS_ENV = os.getenv("FOLDERS", "stream" if FAST_MODE else "stream,player,cast,watch,plus,casting")
PLAYER_FOLDERS = [f.strip() for f in FOLDERS_ENV.split(",") if f.strip()]

CHANNELS_HTML = "247channels.html"
OUT_M3U = "out.m3u8"
CACHE_FILE = "url_cache.json"

# =============================
# Logo Eşleştirme Fonksiyonları
# =============================
def extract_payload_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            html = f.read()
        soup = BeautifulSoup(html, 'html.parser')
        script_tag = soup.find('script', {'type': 'application/json', 'data-target': 'react-app.embeddedData'})
        if not script_tag or not script_tag.string: return {}
        data = json.loads(script_tag.string)
        payload = data.get('payload', {})
        repo = payload.get('repo', {})
        owner_login = repo.get('ownerLogin') or 'tv-logo'
        repo_name = repo.get('name') or 'tv-logos'
        branch = payload.get('refInfo', {}).get('name') or 'main'
        initial_path = f"/{owner_login}/{repo_name}/{branch}/"
        payload['initial_path'] = initial_path
        return payload
    except Exception:
        return {}

def pick_logo_path(display_name, payload):
    tree = payload.get("tree", {})
    items = tree.get("items", [])
    if not items: return ""

    search_words = [word for word in re.split(r'[^a-zA-Z0-9]+', display_name.lower()) if word]
    best_match = None
    highest_score = 0

    for item in items:
        path = item.get("path", "")
        name_lower = item.get("name", "").lower()
        if not any(ext in name_lower for ext in [".png", ".svg", ".jpg"]):
            continue

        score = 0
        for word in search_words:
            if word in name_lower:
                score += 1

        if score > highest_score:
            highest_score = score
            best_match = path

    return best_match if highest_score > 0 else ""

# =============================
# Ana Scraper Fonksiyonları
# =============================
def load_url_cache() -> Dict[str, Any]:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_url_cache(cache: Dict[str, Any]):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

def get_channels_list() -> List[Tuple[str, str, Optional[Dict[str, Any]]]]:
    if not os.path.exists(CHANNELS_HTML):
        print(f"'{CHANNELS_HTML}' dosyası bulunamadı.", flush=True)
        return []

    with open(CHANNELS_HTML, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    links = soup.select("a[href*='stream-']")
    channels = []
    for link in links:
        href = link.get("href", "")
        match = re.search(r"stream-(\d+)\.php", href)
        if match:
            channel_id = match.group(1)
            display_name = link.text.strip()
            channels.append((display_name, channel_id, None))
    return channels

def resolve_channel_with_selenium(channel: Tuple[str, str, Optional[Dict[str, Any]]]) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    display_name, channel_id, stream_info = channel
    if stream_info: return channel

    player_urls = [f"https://daddylivestream.com/{folder}/stream-{channel_id}.php" for folder in PLAYER_FOLDERS]

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    chrome_options.add_argument('--mute-audio')

    seleniumwire_options = {
        'suppress_connection_errors': True,
        'disable_capture': True
    }

    driver = None
    try:
        print(f"[{display_name}] Tarayıcı (network modda) başlatılıyor...", flush=True)
        driver = webdriver.Chrome(
            service=ChromeService(ChromeDriverManager().install()),
            options=chrome_options,
            seleniumwire_options=seleniumwire_options
        )
        driver.set_page_load_timeout(40)

        for url in player_urls:
            print(f"[{display_name}] URL deneniyor: {url}", flush=True)
            try:
                del driver.requests
                driver.scopes = ['.*\\.m3u8.*']
                
                driver.get(url)

                hls_request = driver.wait_for_request(r'\.m3u8', timeout=30)
                
                stream_info = {
                    "url": hls_request.url,
                    "referer": hls_request.headers.get('Referer'),
                    "user_agent": hls_request.headers.get('User-Agent')
                }

                if stream_info["url"]:
                    print(f"BAŞARILI (Network): {display_name} ({channel_id}) -> {stream_info['url']}", flush=True)
                    return (display_name, channel_id, stream_info)

            except TimeoutException:
                print(f"[{display_name}] {url} adresinde m3u8 network isteği zaman aşımına uğradı.", flush=True)
                continue
            except WebDriverException as e:
                print(f"[{display_name}] WebDriver hatası: {e}", flush=True)
                break
            except Exception as e:
                print(f"[{display_name}] {url} işlenirken hata oluştu: {e}", flush=True)
                continue

    except Exception as e:
        print(f"[{display_name}] Selenium'da kritik bir hata oluştu: {e}", flush=True)
    finally:
        if driver:
            driver.quit()
            print(f"[{display_name}] Tarayıcı kapatıldı.", flush=True)

    print(f"BAŞARISIZ: {display_name} ({channel_id}) çözümlenemedi.", flush=True)
    return (display_name, channel_id, None)

# =============================
# Ana Çalıştırma Bloğu
# =============================
if __name__ == "__main__":
    start_time = time.time()
    
    all_channels = get_channels_list()
    channels_to_resolve = all_channels[:MAX_CHANNELS]
    print(f"Toplam {len(all_channels)} kanal bulundu, {len(channels_to_resolve)} tanesi işlenecek.", flush=True)
    
    payload = extract_payload_from_file("tvlogos.html")
    initial_raw_prefix = payload.get('initial_path', '')
    print(f"Logo veritabanı yüklendi. Logo kök yolu: {initial_raw_prefix}", flush=True)

    url_cache = load_url_cache()
    resolved_from_cache = []
    unresolved = []
    for ch in channels_to_resolve:
        display_name, ch_id, _ = ch
        if ch_id in url_cache: resolved_from_cache.append((display_name, ch_id, url_cache[ch_id]))
        else: unresolved.append(ch)
            
    print(f"{len(resolved_from_cache)} kanal önbellekten yüklendi. {len(unresolved)} kanal çözümlenecek.", flush=True)

    results = resolved_from_cache
    with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        future_to_channel = {executor.submit(resolve_channel_with_selenium, ch): ch for ch in unresolved}
        for future in cf.as_completed(future_to_channel):
            channel = future_to_channel[future]
            try:
                resolved_channel = future.result()
                if resolved_channel:
                    results.append(resolved_channel)
                    if resolved_channel[2]: url_cache[resolved_channel[1]] = resolved_channel[2]
            except Exception as exc:
                print(f'{channel[0]} oluşturulurken bir istisna oluştu: {exc}', flush=True)

    save_url_cache(url_cache)

    results_sorted = sorted([r for r in results if r and r[2]], key=lambda r: r[0])
    
    with open(OUT_M3U, "w", encoding="utf-8") as out:
        out.write("#EXTM3U\n")
        for display_name, ch_id, stream_info in results_sorted:
            logo_path = pick_logo_path(display_name, payload)
            logo_url = f"https://raw.githubusercontent.com{initial_raw_prefix}{logo_path}" if logo_path else ""
            
            # Kanal bilgilerini yaz
            out.write(
                f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{display_name}" tvg-logo="{logo_url}" '
                f'group-title="Daddylive", {display_name}\n'
            )
            
            # Her kanal için özel başlıkları (headers) yazıyoruz
            if stream_info.get('referer'):
                out.write(f'#EXTVLCOPT:http-referrer={stream_info["referer"]}\n')
            if stream_info.get('user_agent'):
                out.write(f'#EXTVLCOPT:http-user-agent={stream_info["user_agent"]}\n')
            
            # Son olarak kanal linkini yaz
            out.write(f'{stream_info.get("url")}\n')

    end_time = time.time()
    print(f"İşlem tamamlandı. {len(results_sorted)} kanal '{OUT_M3U}' dosyasına yazıldı.", flush=True)
    print(f"Toplam süre: {end_time - start_time:.2f} saniye.", flush=True)
