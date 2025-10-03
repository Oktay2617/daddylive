#!/usr/bin/env python3
# scraper.py (Network Dinleme Metodu ile Güçlendirilmiş Versiyon)
# Gerekli kütüphaneler: requests, beautifulsoup4, selenium, webdriver-manager, selenium-wire

import os, re, json, time
from typing import Optional, Tuple, List, Dict
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
FAST_MODE       = os.getenv("FAST", "1") == "1"
MAX_CHANNELS    = int(os.getenv("MAX_CHANNELS", "25" if FAST_MODE else "999999"))
CONCURRENCY     = int(os.getenv("CONCURRENCY", "2" if FAST_MODE else "2")) 
FOLDERS_ENV     = os.getenv("FOLDERS", "stream" if FAST_MODE else "stream,player,cast,watch,plus,casting")
PLAYER_FOLDERS  = [f.strip() for f in FOLDERS_ENV.split(",") if f.strip()]

CHANNELS_HTML   = "247channels.html"
OUT_M3U         = "out.m3u8"
CACHE_FILE      = "url_cache.json"

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
def load_url_cache() -> Dict[str, str]:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            try: return json.load(f)
            except json.JSONDecodeError: return {}
    return {}

def save_url_cache(cache: Dict[str, str]):
    with open(CACHE_FILE, "w") as f: json.dump(cache, f, indent=2)

def get_channels_list() -> List[Tuple[str, str, Optional[str]]]:
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

def resolve_channel_with_selenium(channel: Tuple[str, str, Optional[str]]) -> Tuple[str, str, Optional[str]]:
    display_name, channel_id, hls_url = channel
    if hls_url: return channel

    player_urls = [f"https://daddylivestream.com/{folder}/stream-{channel_id}.php" for folder in PLAYER_FOLDERS]
    
    # Selenium-wire için tarayıcı seçenekleri
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    chrome_options.add_argument('--mute-audio')


    # Selenium-wire'a özel ayarlar
    seleniumwire_options = {
        'suppress_connection_errors': True,
        'disable_capture': True # Performans için başlangıçta network yakalamayı kapat
    }
    
    driver = None
    try:
        print(f"[{display_name}] Tarayıcı (network modda) başlatılıyor...", flush=True)
        # Selenium-wire'dan webdriver'ı başlatıyoruz
        driver = webdriver.Chrome(
            service=ChromeService(ChromeDriverManager().install()), 
            options=chrome_options, 
            seleniumwire_options=seleniumwire_options
        )
        driver.set_page_load_timeout(40)

        for url in player_urls:
            print(f"[{display_name}] URL deneniyor: {url}", flush=True)
            try:
                # Network yakalamayı temizle ve sadece m3u8 için başlat
                del driver.requests
                driver.scopes = [
                    '.*\\.m3u8.*'
                ]
                
                driver.get(url)

                # Sayfanın .m3u8 dosyası için bir network isteği yapmasını bekle (30 saniye)
                hls_request = driver.wait_for_request(r'\.m3u8', timeout=30)
                hls = hls_request.url

                if hls:
                    print(f"BAŞARILI (Network): {display_name} ({channel_id}) -> {hls}", flush=True)
                    return (display_name, channel_id, hls)

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
        out.write("#EXTM3U\\n")
        for display_name, ch_id, hls in results_sorted:
            logo_path = pick_logo_path(display_name, payload)
            logo_url = f"https://raw.githubusercontent.com{initial_raw_prefix}{logo_path}" if logo_path else ""
            line = (
                f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{display_name}" tvg-logo="{logo_url}" '
                f'group-title="Daddylive", {display_name}\\n'
                f'{hls}\\n'
            )
            out.write(line)

    end_time = time.time()
    print(f"İşlem tamamlandı. {len(results_sorted)} kanal '{OUT_M3U}' dosyasına yazıldı.", flush=True)
    print(f"Toplam süre: {end_time - start_time:.2f} saniye.", flush=True)
