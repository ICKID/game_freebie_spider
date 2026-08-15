import os
import requests
from bs4 import BeautifulSoup
from discord_webhook import DiscordWebhook, DiscordEmbed
import sys

# --- 設定區 ---
URL_FREESTEAM = "https://freesteam.games/"
HISTORY_FILE = "posted_links.txt"

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true" or "--test" in sys.argv
TEST_URL = os.environ.get("TEST_URL", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

VALID_STORES = [
    "steampowered.com",
    "epicgames.com",
    "gog.com"
]

EXCLUDE_KEYWORDS = [
    "/login",
    "/signin",
    "/download",
    "/cart",
    "/checkout",
    "support.",
    "help.",
    "#openlogin"
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

def extract_all_store_links_and_pure_images(article_url):
    """解析單篇文章，精準抓取 Steam / Epic / GOG 主遊戲連結"""
    try:
        res = requests.get(article_url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return "", [], ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        content_area = soup.select_one('.entry-content, .post-content, .post, article, main')
        if not content_area:
            content_area = soup 
            
        main_img = ""
        img_tag = content_area.select_one('img')
        if img_tag and img_tag.get('src'):
            main_img = img_tag['src']
            
        title_tag = soup.select_one('h1.entry-title, h1.post-title, h1')
        title = title_tag.text.strip() if title_tag else "限免遊戲情報"
            
        links = []
        for a in content_area.select('a'):
            href = a.get('href', '').strip()
            href_lower = href.lower()
            
            # 1. 必須符合三大平台白名單
            if not any(store in href_lower for store in VALID_STORES):
                continue
                
            # 2. 通過排除清單檢查 (不能包含 login, download, #openlogin 等字眼)
            if any(exclude in href_lower for exclude in EXCLUDE_KEYWORDS):
                continue
                
            # 3. 嚴格鎖定三大平台的「主遊戲頁面」結構
            if "epicgames.com" in href_lower and "/p/" not in href_lower:
                continue
            if "steampowered.com" in href_lower and "/app/" not in href_lower:
                continue
            if "gog.com" in href_lower and "/game/" not in href_lower:
                continue
                
            links.append(href)
                
        links = list(dict.fromkeys(links))
        return title, links, main_img
        
    except Exception as e:
        print(f"   ⚠️ 解析文章失敗: {e}")
        return "", [], ""

def send_to_discord(title, links, main_img):
    if not DISCORD_WEBHOOK_URL:
        print("❌ 錯誤：未設定 DISCORD_WEBHOOK_URL")
        return False
        
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    desc = ""
    for i, link in enumerate(links):
        desc += f"🔗 [點此前往領取遊戲 ({i+1})]({link})\n"
        
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
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動...")
    
    if TEST_MODE:
        print("⚠️ 測試模式已開啟")
        if TEST_URL:
            print(f"🔍 正在強制測試指定網址: {TEST_URL}")
            title, links, main_img = extract_all_store_links_and_pure_images(TEST_URL)
            print(f"   標題: {title}")
            print(f"   過濾後的有效連結: {links}")
            if links:
                send_to_discord(title, links, main_img)
            else:
                print("   ⚠️ 該測試網址內沒有找到有效的遊戲主連結！")
        else:
            print("   ⚠️ 未提供 TEST_URL")
        return

    history = load_history()
    
    try:
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        tags = soup.select('h2 a, h3 a, .entry-title a, .post-title a')
        
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

        count = 0
        for article in reversed(valid_articles[:5]): 
            article_url = article["url"]
            title = article["title"]
            
            if article_url in history:
                continue
            
            print(f"\n   [發現新文章] {title[:25]}...")
            title, links, main_img = extract_all_store_links_and_pure_images(article_url)
            
            if links:
                is_success = send_to_discord(title, links, main_img)
                if is_success:
                    history.add(article_url)
                    count += 1
            else:
                print("   ⚠️ 內文無有效遊戲主連結，跳過發送。")
                history.add(article_url)
                
        save_history(history)
        print(f"\n🎉 [FreeSteam] 自動排程處理完畢，共推播了 {count} 則全新限免！")
        
    except Exception as e:
        print(f"❌ 發生異常: {e}")

if __name__ == "__main__":
    main()
