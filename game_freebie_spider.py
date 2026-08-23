import os
import requests
from bs4 import BeautifulSoup
from discord_webhook import DiscordWebhook, DiscordEmbed
import sys

# --- 設定區 ---
URL_FREESTEAM = "https://freesteam.games/category/free-games"
HISTORY_FILE = "posted_links.txt"

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true" or "--test" in sys.argv
TEST_URL = os.environ.get("TEST_URL", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for url in history:
            f.write(f"{url}\n")

def extract_all_store_links_and_pure_images(article_url):
    """解析單篇文章，保留網頁上的結構與所有領取連結"""
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
        title = title_tag.text.strip() if title_tag else "限時免費遊戲情報"
            
        link_items = []
        
        # 2. 依照段落/行來擷取連結，確保同一行的連結能被歸納在一起
        # WordPress 文章通常是以 <p> 或是 <div> 區塊來分行的
        paragraphs = content_area.select('p, li, div')
        if not paragraphs:
            paragraphs = [content_area]

        seen_urls = set()
        
        for p in paragraphs:
            row_links = []
            for a in p.select('a'):
                href = a.get('href', '').strip()
                link_text = a.text.strip()
                href_lower = href.lower()
                
                # 排除不相關的外部連結或登入頁面
                if any(x in href_lower for x in ['/login', '/download', '/signin', 'support.', 'help.', 'facebook.com', 'twitter.com', 'discord.gg']):
                    continue
                if href.startswith('http') and 'freesteam.games' not in href:
                    if href not in seen_urls:
                        seen_urls.add(href)
                        display_text = link_text if link_text and len(link_text) > 1 and link_text not in ["領取連結:", "領取連結：", "領取連結"] else "點此前往領取"
                        row_links.append({"text": display_text, "url": href})
            
            if row_links:
                link_items.append(row_links)
                
        if not link_items:
            return title, [], main_img, False
            
        return title, link_items, main_img, True
        
    except Exception as e:
        print(f"   ⚠️ 解析文章失敗: {e}")
        return "", [], "", False

def send_to_discord(title, link_rows, main_img):
    if not DISCORD_WEBHOOK_URL:
        print("❌ 錯誤：未設定 DISCORD_WEBHOOK_URL")
        return False
        
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    # 🎯 依照網頁原本的同行結構組裝 Discord 訊息
    desc = ""
    for row in link_rows:
        row_str_parts = []
        for item in row:
            row_str_parts.append(f"🔗 [{item['text']}]({item['url']})")
        # 如果同一行有多個連結，用空格或分隔符號串起來
        desc += " | ".join(row_str_parts) + "\n"
        
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
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動 (全連結與同行排版版)...")
    
    if TEST_MODE:
        print("⚠️ 測試模式已開啟")
        if TEST_URL:
            print(f"🔍 正在強制測試指定網址: {TEST_URL}")
            title, link_rows, main_img, is_valid = extract_all_store_links_and_pure_images(TEST_URL)
            print(f"   標題: {title}")
            print(f"   是否符合『限時免費』: {is_valid}")
            print(f"   抓取到的連結結構: {link_rows}")
            if is_valid and link_rows:
                send_to_discord(title, link_rows, main_img)
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
            title, link_rows, main_img, is_valid = extract_all_store_links_and_pure_images(article_url)
            
            if is_valid and link_rows:
                print(f"   ✅ 成功抓取所有連結群組，準備發送...")
                is_success = send_to_discord(title, link_rows, main_img)
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
