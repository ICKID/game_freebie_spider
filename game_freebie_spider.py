import time
import requests
from bs4 import BeautifulSoup
import re
import os
import sys

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
IS_TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true" or "--test" in sys.argv
TEST_URL = os.environ.get("TEST_URL", "").strip()

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"
HISTORY_FILE = "posted_links.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_history(history_set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for link in sorted(history_set):
            f.write(f"{link}\n")

def check_image_exists(img_url):
    try:
        response = requests.head(img_url, headers=HEADERS, timeout=5)
        if response.status_code == 200:
            return True
    except:
        pass
    return False

def get_valid_steam_image(app_id):
    official_img = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg"
    if check_image_exists(official_img):
        return official_img
        
    library_img = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/library_600x900.jpg"
    if check_image_exists(library_img):
        return library_img

    steamdb_img = f"https://steamdb.info/static/appid/header/{app_id}.jpg"
    if check_image_exists(steamdb_img):
        return steamdb_img
        
    return None

def fetch_game_name_from_steamdb(app_id):
    """當只有純數字 ID 時，連線至 SteamDB 抓取真實遊戲名稱"""
    try:
        url = f"https://steamdb.info/app/{app_id}/"
        # SteamDB 需要比較像真實瀏覽器的 User-Agent 避免阻擋
        db_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=db_headers, timeout=8)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # SteamDB 通常將遊戲名稱放在 h1 標籤中
            h1_tag = soup.select_one('div.container h1')
            if h1_tag:
                # 移除可能包含的額外 tag 文字
                game_name = h1_tag.get_text().strip()
                if game_name:
                    return game_name
    except Exception as e:
        print(f"   ⚠️ 從 SteamDB 抓取 App ID {app_id} 名稱失敗: {e}")
    return None

def extract_all_store_links_and_pure_images(page_url):
    found_stores = []  
    widget_steam_urls = [] 
    all_game_urls_in_article = set()
    freesteam_main_image = None
    
    try:
        time.sleep(0.5)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return [], [], None
        inner_soup = BeautifulSoup(res.text, 'html.parser')

        og_img = inner_soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get('content'):
            freesteam_main_image = og_img['content'].split('?')[0].strip()

        content_area = inner_soup.select_one('.entry-content') or inner_soup

        iframes = content_area.find_all('iframe', src=True)
        for iframe in iframes:
            src = iframe['src']
            if "store.steampowered.com/widget/" in src:
                try:
                    app_id = src.split('/widget/')[1].split('/')[0]
                    widget_url = f"https://store.steampowered.com/app/{app_id}"
                    if widget_url not in widget_steam_urls:
                        widget_steam_urls.append(widget_url)
                except: pass

        page_text = content_area.get_text()
        found_ids = re.findall(r'#\s*(\d{5,7})', page_text)
        for app_id in found_ids:
            widget_url = f"https://store.steampowered.com/app/{app_id}"
            if widget_url not in widget_steam_urls:
                widget_steam_urls.append(widget_url)

        links = content_area.find_all('a', href=True)
        
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            raw_text = tag.get_text().strip()
            
            lower_href = href.lower()
            if any(bad in lower_href for bad in ["galaxy", "login", "support", "privacy", "download", "u/"]):
                continue
            
            platform = None
            if "store.steampowered.com/app/" in href:
                if "agecheck" not in href:
                    platform = "Steam"
            elif "epicgames.com" in href:
                if href in ["https://store.epicgames.com", "https://www.epicgames.com", "https://store.epicgames.com/en-US"]:
                    continue
                platform = "Epic Games"
            elif "gog.com" in href:
                if href != "https://www.gog.com":
                    platform = "GOG"

            if platform:
                all_game_urls_in_article.add(href)
                clean_name = " ".join(raw_text.split())
                
                # 🎯 關鍵升級：如果抓到的名稱是純數字，自動向 SteamDB 查詢真實名稱！
                if not clean_name or len(clean_name) <= 1 or clean_name.isdigit() or "http" in clean_name or "點擊" in clean_name or "這裡" in clean_name or "商店頁面" in clean_name:
                    if clean_name.isdigit():
                        app_id = clean_name
                        print(f"   🔍 發現純數字 ID [{app_id}]，正在向 SteamDB 查詢真實遊戲名稱...")
                        db_name = fetch_game_name_from_steamdb(app_id)
                        clean_name = db_name if db_name else f"Steam 限免遊戲 ({app_id})"
                    else:
                        try:
                            slug = href.rstrip('/').split('/')[-1]
                            clean_name = slug.replace('-', ' ').replace('_', ' ').title()
                        except:
                            clean_name = f"{platform} 遊戲"
                
                found_stores.append({
                    "link": href,
                    "name": clean_name,
                    "platform": platform
                })

    except: pass
    
    if not widget_steam_urls:
        widget_steam_urls = [x for x in all_game_urls_in_article if "store.steampowered.com" in x]
        
    return found_stores, widget_steam_urls, freesteam_main_image

def send_to_discord_clean_images(title, store_items, widget_steam_urls, freesteam_main_image):
    if not store_items: return
    if not DISCORD_WEBHOOK_URL: return
    
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    links_str = "".join([item["link"] for item in store_items]).lower()
    card_color = "00c0ff" if "steam" in links_str else "1a1a1a" if "epic" in links_str else "f1c40f"
    
    collected_covers = []
    
    for widget_url in widget_steam_urls:
        try:
            app_id = widget_url.split('/app/')[1].split('/')[0]
            valid_img = get_valid_steam_image(app_id)
            if valid_img and valid_img not in collected_covers:
                collected_covers.append(valid_img)
        except: pass
        
    if not collected_covers and freesteam_main_image:
        if check_image_exists(freesteam_main_image):
            collected_covers.append(freesteam_main_image)

    # 組合排版：處理「遊戲本體」合併在同一行，並加上平台標籤
    processed_lines = []
    skip_next = False
    
    for i in range(len(store_items)):
        if skip_next:
            skip_next = False
            continue
            
        current = store_items[i]
        platform_label = f"[{current['platform']}] "
        
        if i + 1 < len(store_items) and store_items[i+1]["name"] == "遊戲本體":
            next_item = store_items[i+1]
            combined_line = f"{platform_label}[{current['name']}]({current['link']}) ([遊戲本體]({next_item['link']}))"
            processed_lines.append(combined_line)
            skip_next = True
        else:
            processed_lines.append(f"{platform_label}[{current['name']}]({current['link']})")

    links_text = "\n".join(processed_lines) + "\n"

    main_embed = DiscordEmbed(title=title, color=card_color)
    main_embed.add_embed_field(name="🎁 領取網址", value=links_text, inline=False)
    
    if collected_covers:
        main_embed.set_image(url=collected_covers[0])
    main_embed.set_timestamp()
    webhook.add_embed(main_embed)
    
    if collected_covers and len(collected_covers) > 1:
        for extra_img in collected_covers[1:4]:
            sub_embed = DiscordEmbed(color=card_color)
            sub_embed.set_image(url=extra_img)
            webhook.add_embed(sub_embed)

    try:
        webhook.execute()
        print("   🎉 Discord 測試發送成功！")
    except Exception as e:
        print(f"❌ Discord 發送失敗: {e}")

def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動（SteamDB 名稱查詢版）...")
    
    if IS_TEST_MODE and TEST_URL:
        print(f"⚠️ 【強制指定測試網址】正在解析: {TEST_URL}")
        try:
            res = requests.get(TEST_URL, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            title_tag = soup.select_one('h1.entry-title, h1')
            title = title_tag.text.strip() if title_tag else "測試限免遊戲"
            
            store_items, widget_urls, main_img = extract_all_store_links_and_pure_images(TEST_URL)
            print(f"   抓到的商店項目: {store_items}")
            
            if store_items:
                send_to_discord_clean_images(title, store_items, widget_urls, main_img)
            else:
                print("   ⚠️ 該測試網址未抓取到任何有效商店連結！")
        except Exception as e:
            print(f"   ❌ 測試執行發生異常: {e}")
        return

    history = load_history()
    print(f"📋 載入歷史紀錄，目前已記憶了 {len(history)} 個網址。")
    
    try:
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')
        
        count = 0
        for article in reversed(articles[:5]): 
            tag = article.select_one('.entry-title a, h2 a, h3 a')
            if tag:
                article_url = tag['href'].strip()
                title = tag.text.strip()
                
                if article_url in history:
                    print(f"   Skip: {title[:20]}...")
                    continue
                
                print(f"   New Article: {title[:20]}...")
                store_items, widget_urls, main_img = extract_all_store_links_and_pure_images(article_url)
                
                if store_items:
                    send_to_discord_clean_images(title, store_items, widget_urls, main_img)
                    history.add(article_url)
                    count += 1
                else:
                    print("   ⚠️ 無有效商店連結，標記為已讀。")
                    history.add(article_url)
                    
        save_history(history)
        print(f"   [FreeSteam] 自動排程處理完畢，共推播了 {count} 則全新限免！")
        
    except Exception as e:
        print(f"❌ 發生異常: {e}")

    print("\n🎉 全數流程執行完畢！")

if __name__ == "__main__":
    main()
