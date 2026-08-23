import os
import requests
from bs4 import BeautifulSoup
from discord_webhook import DiscordWebhook, DiscordEmbed
import sys
import re

# --- 設定區 ---
URL_FREESTEAM = "https://freesteam.games/category/free-games"
HISTORY_FILE = "posted_links.txt"

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true" or "--test" in sys.argv
TEST_URL = os.environ.get("TEST_URL", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

BASE_GAME_KEYWORDS = ["遊戲本體", "主遊戲", "base game", "本體", "steam頁面"]

ALLOWED_STORE_DOMAINS = [
    "store.steampowered.com",
    "gog.com",
    "epicgames.com",
    "humblebundle.com",
    "itch.io",
    "indiegala.com",
    "ubisod.com",
    "ea.com"
]

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for url in history:
            f.write(f"{url}\n")

def is_base_game_text(text):
    clean_text = text.strip().lower()
    return any(keyword in clean_text for keyword in BASE_GAME_KEYWORDS)

def get_store_display_name(url, original_text, article_title):
    """精準萃取純遊戲名稱並依平台命名"""
    url_lower = url.lower()
    clean_orig_text = original_text.strip() if original_text else ""
    
    if clean_orig_text and not clean_orig_text.startswith("http") and not any(k in clean_orig_text for k in ["登入", "點此", "連結", "這裡", "Login", "sign", "GALAXY"]):
        return clean_orig_text
        
    clean_title = article_title
    clean_title = re.sub(r'^(?:Steam[、與\s]*|GOG[、與\s]*|Epic[、與\s]*|商店[、與\s]*)+', '', clean_title, flags=re.IGNORECASE)
    clean_title = clean_title.replace("限時免費領取", "").replace("免費領取", "").replace("特惠", "")
    
    game_name = clean_title.replace("《", "").replace("》", "").replace("—", "-").strip()
    if not game_name:
        game_name = "限免遊戲"
        
    if "steampowered.com" in url_lower:
        return f"{game_name} (Steam)"
    elif "gog.com" in url_lower:
        return f"{game_name} (GOG)"
    elif "epicgames.com" in url_lower:
        return f"{game_name} (Epic)"
    elif "itch.io" in url_lower:
        return f"{game_name} (Itch.io)"
        
    return game_name

def extract_steam_appid(url):
    """從 Steam 網址中精準提取 App ID"""
    match = re.search(r'/app/(\d+)', url)
    return match.group(1) if match else None

def extract_all_store_links_and_pure_images(article_url):
    """解析單篇文章，並透過網址逆向生成官方高清遊戲封面圖"""
    try:
        res = requests.get(article_url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return "", [], [], False
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        content_area = soup.select_one('.entry-content, .post-content, .post, article, main')
        if not content_area:
            content_area = soup 
            
        full_text = content_area.text
        
        if "限時免費" not in full_text and "限免" not in full_text:
            return "", [], [], False
            
        title_tag = soup.select_one('h1.entry-title, h1.post-title, h1')
        article_title = title_tag.text.strip() if title_tag else "限時免費遊戲情報"
            
        raw_links = []
        seen_urls = set()
        
        for a in content_area.select('a'):
            href = a.get('href', '').strip()
            link_text = a.text.strip()
            href_lower = href.lower()
            
            black_keywords = [
                '/login', '/signin', '/signup', '/register', '/logout', 
                '/account', '/download', '/downloads', 'support.', 'help.', 
                'facebook.com', 'twitter.com', 'discord.gg', 'youtube.com', 
                '##', 'cart', 'checkout', 'galaxy'
            ]
            if any(x in href_lower for x in black_keywords):
                continue
            
            if "epicgames.com" in href_lower:
                if href_lower.rstrip('/') == "https://store.epicgames.com" or "/download" in href_lower:
                    continue

            if "gog.com" in href_lower:
                if href_lower.rstrip('/') in ["https://www.gog.com", "https://gog.com", "https://www.gog.com/en", "https://gog.com/en"]:
                    continue

            is_valid_store = any(domain in href_lower for domain in ALLOWED_STORE_DOMAINS)
            
            if href.startswith('http') and is_valid_store:
                if href not in seen_urls:
                    seen_urls.add(href)
                    raw_links.append({"text": link_text, "url": href})

        if not raw_links:
            return article_title, [], [], False

        formatted_items = []
        used_indices = set()
        images = []

        for i, current in enumerate(raw_links):
            if i in used_indices:
                continue

            current_text = current["text"]
            current_url = current["url"]
            current_url_lower = current_url.lower()

            # 逆向生成封面圖邏輯：
            # 1. 如果是 Steam 網址，直接組合官方 CDN 高清橫幅圖
            steam_appid = extract_steam_appid(current_url)
            if steam_appid:
                header_img = f"https://cdn.akamai.steamstatic.com/steam/apps/{steam_appid}/header.jpg"
                if header_img not in images:
                    images.append(header_img)

            if not is_base_game_text(current_text):
                matched_base_game = None
                
                if i + 1 < len(raw_links) and (i + 1) not in used_indices:
                    next_item = raw_links[i + 1]
                    if is_base_game_text(next_item["text"]):
                        matched_base_game = next_item
                        used_indices.add(i + 1)
                
                if not matched_base_game and i - 1 >= 0 and (i - 1) not in used_indices:
                    prev_item = raw_links[i - 1]
                    if is_base_game_text(prev_item["text"]):
                        matched_base_game = prev_item
                        used_indices.add(i - 1)

                display_name = get_store_display_name(current_url, current_text, article_title)

                formatted_items.append({
                    "title": display_name,
                    "url": current_url,
                    "base_game_url": matched_base_game["url"] if matched_base_game else None
                })
                used_indices.add(i)
            else:
                formatted_items.append({
                    "title": f"{article_title} (遊戲本體)",
                    "url": current_url,
                    "base_game_url": None
                })
                used_indices.add(i)

        # 如果文章內完全沒有 Steam 網址可提取圖片（例如純 Epic 或 GOG），嘗試撈取文章裡第一張正規的遊戲宣傳圖作為備用
        if not images:
            for img in content_area.select('img'):
                src = img.get('src')
                if src and src.startswith('http') and not any(x in src.lower() for x in ['avatar', 'icon', 'emoji', 'spacer', '1x1']):
                    images.append(src)
                    break

        return article_title, formatted_items, images, True
        
    except Exception as e:
        print(f"   ⚠️ 解析文章失敗: {e}")
        return "", [], [], False

def send_to_discord(title, formatted_items, images):
    if not DISCORD_WEBHOOK_URL:
        print("❌ 錯誤：未設定 DISCORD_WEBHOOK_URL")
        return False
        
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    desc = ""
    for item in formatted_items:
        item_title = item["title"]
        main_url = item["url"]
        base_game_url = item["base_game_url"]
        
        line = f"🔗 [{item_title}]({main_url})"
        if base_game_url:
            line += f" | 🎮 [遊戲本體]({base_game_url})"
        
        desc += line + "\n"
        
    # 主 Embed（放入文章標題、清單與第一張官方/精選大圖）
    embed = DiscordEmbed(title=title, description=desc, color="03b2f8")
    if images and len(images) > 0:
        embed.set_image(url=images[0])
        
    webhook.add_embed(embed)
    
    # 如果抓到多張官方遊戲圖片（多遊戲合輯），透過額外的 Embed 展開相簿多圖展示
    if images and len(images) > 1:
        for extra_img in images[1:3]: # 最多額外展示 2 張
            extra_embed = DiscordEmbed(color="03b2f8")
            extra_embed.set_image(url=extra_img)
            webhook.add_embed(extra_embed)
    
    response = webhook.execute()
    if response.status_code in [200, 204]:
        print("   🎉 Discord 發送成功！")
        return True
    else:
        print(f"   ❌ Discord 拒絕發送，狀態碼: {response.status_code}")
        return False

def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動 (官方 CDN 圖片逆向串聯版)...")
    
    if TEST_MODE:
        print("⚠️ 測試模式已開啟")
        if TEST_URL:
            print(f"🔍 正在強制測試指定網址: {TEST_URL}")
            title, formatted_items, images, is_valid = extract_all_store_links_and_pure_images(TEST_URL)
            print(f"   文章標題: {title}")
            print(f"   是否符合『限時免費』: {is_valid}")
            print(f"   串聯到的官方/精選圖片清單: {images}")
            print(f"   智慧解析後的資料結構:\n{formatted_items}")
            if is_valid and formatted_items:
                send_to_discord(title, formatted_items, images)
            else:
                print("   ⚠️ 該測試網址不符合條件或未找到領取連結！")
        else:
            print("   ⚠️ 未提供 TEST_URL")
        return

    history = load_history()
    print(f"📂 已載入歷史紀錄，目前共有 {len(history)} 筆已發送網址。")
    
    try:
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        print(f"📡 請求分類頁面 HTTP 狀態碼: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ 無法存取分類頁面 (HTTP {response.status_code})")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        
        main_container = soup.select_one('main, #primary, .site-main, .ast-container')
        if not main_container:
            main_container = soup
            
        for aside in main_container.select('aside, .sidebar'):
            aside.decompose()
            
        tags = main_container.select('h2 a, h3 a, .entry-title a, .post-title a')
        
        valid_articles = []
        seen_urls = set()
        
        for tag in tags:
            url = tag.get('href', '').strip()
            title = tag.text.strip()
            
            if (title and url.startswith("https://freesteam.games") 
                and url not in seen_urls 
                and "/category/" not in url 
                and "/page/" not in url 
                and "/tag/" not in url
                and url != "https://freesteam.games/"):
                
                valid_articles.append({"title": title, "url": url})
                seen_urls.add(url)

        print(f"📦 從分類頁面主區域成功抓取到的文章數量: {len(valid_articles)}")

        count = 0
        for article in reversed(valid_articles[:10]): 
            article_url = article["url"]
            title = article["title"]
            
            if article_url in history:
                continue
            
            print(f"\n   [檢查新文章] {title[:25]}...")
            title, formatted_items, images, is_valid = extract_all_store_links_and_pure_images(article_url)
            
            if is_valid and formatted_items:
                print(f"   ✅ 成功抓取並排版 {len(formatted_items)} 組連結，準備發送...")
                is_success = send_to_discord(title, formatted_items, images)
                if is_success:
                    history.add(article_url)
                    count += 1
            else:
                print("   ⚠️ 該文章非限時免費或無領取連結，已略過。")
                history.add(article_url)
                
        save_history(history)
        print(f"\n🎉 [FreeSteam] 自動排程處理完畢，共推播了 {count} 則全新限免！")
        
    except Exception as e:
        print(f"❌ 發生異常: {e}")

if __name__ == "__main__":
    main()
