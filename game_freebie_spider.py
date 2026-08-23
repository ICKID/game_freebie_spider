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

# 允許的遊戲商店網域（確保只抓真正能領遊戲的商店）
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
    """智慧判斷商店顯示名稱"""
    url_lower = url.lower()
    
    # 如果原始文字夠長且不是泛用詞，優先使用原始文字
    if original_text and len(original_text) > 2 and not any(k in original_text for k in ["登入", "點此", "連結", "這裡", "Login", "sign"]):
        return original_text
        
    # 依據網址判斷屬於哪個平台
    if "steampowered.com" in url_lower:
        if "app/" in url_lower:
            return article_title.replace("限時免費領取", "").replace("《", "").replace("》", "").strip()
        return "Steam 商店"
    elif "gog.com" in url_lower:
        return "GOG 商店"
    elif "epicgames.com" in url_lower:
        return "Epic Games 商店"
    elif "itch.io" in url_lower:
        return "Itch.io 商店"
        
    return article_title if article_title else "點此前往領取"

def extract_all_store_links_and_pure_images(article_url):
    """解析單篇文章，嚴格過濾登入連結與雜訊"""
    try:
        res = requests.get(article_url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return "", [], "", False
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        content_area = soup.select_one('.entry-content, .post-content, .post, article, main')
        if not content_area:
            content_area = soup 
            
        full_text = content_area.text
        
        if "限時免費" not in full_text and "限免" not in full_text:
            return "", [], "", False
            
        main_img = ""
        img_tag = content_area.select_one('img')
        if img_tag and img_tag.get('src'):
            main_img = img_tag['src']
            
        title_tag = soup.select_one('h1.entry-title, h1.post-title, h1')
        article_title = title_tag.text.strip() if title_tag else "限時免費遊戲情報"
            
        raw_links = []
        seen_urls = set()
        
        for a in content_area.select('a'):
            href = a.get('href', '').strip()
            link_text = a.text.strip()
            href_lower = href.lower()
            
            # 嚴格黑名單：排除登入、註冊、登出、幫助、社交媒體等非商店連結
            black_keywords = [
                '/login', '/signin', '/signup', '/register', '/logout', 
                'support.', 'help.', 'facebook.com', 'twitter.com', 
                'discord.gg', 'youtube.com', '##', 'cart', 'checkout'
            ]
            if any(x in href_lower for x in black_keywords):
                continue
            
            # 檢查是否為支援的商店網域
            is_valid_store = any(domain in href_lower for domain in ALLOWED_STORE_DOMAINS)
            
            if href.startswith('http') and is_valid_store:
                if href not in seen_urls:
                    seen_urls.add(href)
                    raw_links.append({"text": link_text, "url": href})

        if not raw_links:
            return article_title, [], main_img, False

        # 智慧語義與配對處理
        formatted_items = []
        used_indices = set()

        for i, current in enumerate(raw_links):
            if i in used_indices:
                continue

            current_text = current["text"]
            current_url = current["url"]

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
                # 獨立本體處理
                formatted_items.append({
                    "title": f"{article_title} (遊戲本體)",
                    "url": current_url,
                    "base_game_url": None
                })
                used_indices.add(i)

        return article_title, formatted_items, main_img, True
        
    except Exception as e:
        print(f"   ⚠️ 解析文章失敗: {e}")
        return "", [], "", False

def send_to_discord(title, formatted_items, main_img):
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
        
    embed = DiscordEmbed(title=title, description=desc, color="03b2f8")
    if main_img:
        embed.set_image(url=main_img)
        
    webhook.add_embed(embed)
    
    response = webhook.execute()
    if response.status_code in [200, 204]:
        print("   🎉 Discord 發送成功！")
        return True
    else:
        print(f"   ❌ Discord 拒絕發送，狀態碼: {response.status_code}")
        return False

def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動 (商店白名單過濾版)...")
    
    if TEST_MODE:
        print("⚠️ 測試模式已開啟")
        if TEST_URL:
            print(f"🔍 正在強制測試指定網址: {TEST_URL}")
            title, formatted_items, main_img, is_valid = extract_all_store_links_and_pure_images(TEST_URL)
            print(f"   文章標題: {title}")
            print(f"   是否符合『限時免費』: {is_valid}")
            print(f"   智慧解析後的資料結構:\n{formatted_items}")
            if is_valid and formatted_items:
                send_to_discord(title, formatted_items, main_img)
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
            title, formatted_items, main_img, is_valid = extract_all_store_links_and_pure_images(article_url)
            
            if is_valid and formatted_items:
                print(f"   ✅ 成功抓取並過濾 {len(formatted_items)} 組商店連結，準備發送...")
                is_success = send_to_discord(title, formatted_items, main_img)
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
