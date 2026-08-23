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
    """判斷超連結文字是否屬於『遊戲本體』這類附屬說明文字"""
    clean_text = text.strip().lower()
    return any(keyword in clean_text for keyword in BASE_GAME_KEYWORDS)

def extract_all_store_links_and_pure_images(article_url):
    """解析單篇文章，並進行智慧語義結構化解析"""
    try:
        res = requests.get(article_url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return "", [], "", False
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        content_area = soup.select_one('.entry-content, .post-content, .post, article, main')
        if not content_area:
            content_area = soup 
            
        full_text = content_area.text
        
        # 1. 確認是否為「限時免費」
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
        
        # 抓取內文中所有有效的外部領取/商店連結
        for a in content_area.select('a'):
            href = a.get('href', '').strip()
            link_text = a.text.strip()
            href_lower = href.lower()
            
            # 過濾無關的社交或功能性連結
            if any(x in href_lower for x in ['/login', '/download', '/signin', 'support.', 'help.', 'facebook.com', 'twitter.com', 'discord.gg', 'youtube.com']):
                continue
            
            if href.startswith('http') and 'freesteam.games' not in href:
                if href not in seen_urls:
                    seen_urls.add(href)
                    raw_links.append({"text": link_text, "url": href})

        if not raw_links:
            return article_title, [], main_img, False

        # 2. 智慧語義比對與組合處理
        formatted_items = []
        used_indices = set()

        for i, current in enumerate(raw_links):
            if i in used_indices:
                continue

            current_text = current["text"]
            current_url = current["url"]

            # 情境 A：當前項目是普通遊戲/DLC 名稱
            if not is_base_game_text(current_text):
                matched_base_game = None
                
                # 向後探測 1 個位置，檢查是否緊跟著「遊戲本體」連結
                if i + 1 < len(raw_links) and (i + 1) not in used_indices:
                    next_item = raw_links[i + 1]
                    if is_base_game_text(next_item["text"]):
                        matched_base_game = next_item
                        used_indices.add(i + 1)
                
                # 如果後面沒有，向前探測 1 個位置（防止先寫『遊戲本體』再寫名稱的情況）
                if not matched_base_game and i - 1 >= 0 and (i - 1) not in used_indices:
                    prev_item = raw_links[i - 1]
                    if is_base_game_text(prev_item["text"]):
                        matched_base_game = prev_item
                        used_indices.add(i - 1)

                formatted_items.append({
                    "title": current_text if current_text else article_title,
                    "url": current_url,
                    "base_game_url": matched_base_game["url"] if matched_base_game else None
                })
                used_indices.add(i)

            # 情境 B：當前項目本身就是「遊戲本體」（且未被前方遊戲名稱綁定）
            else:
                # 嘗試尋找前後未被使用的遊戲名稱
                matched_main_game = None
                if i + 1 < len(raw_links) and (i + 1) not in used_indices and not is_base_game_text(raw_links[i + 1]["text"]):
                    matched_main_game = raw_links[i + 1]
                    used_indices.add(i + 1)
                elif i - 1 >= 0 and (i - 1) not in used_indices and not is_base_game_text(raw_links[i - 1]["text"]):
                    matched_main_game = raw_links[i - 1]
                    used_indices.add(i - 1)

                if matched_main_game:
                    formatted_items.append({
                        "title": matched_main_game["text"],
                        "url": matched_main_game["url"],
                        "base_game_url": current_url
                    })
                else:
                    # 孤立的「遊戲本體」連結，直接將其作為獨立連結呈現
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
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動 (動態語義配對版)...")
    
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
                print(f"   ✅ 成功抓取並配對 {len(formatted_items)} 組連結，準備發送...")
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
