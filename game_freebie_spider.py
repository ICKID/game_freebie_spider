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
    """解析單篇文章，同時抓取『領取連結』的網址以及它原本的文字"""
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
        
        # 2. 尋找內文中的「領取連結」相關超連結，並保留其顯示文字
        for a in content_area.select('a'):
            href = a.get('href', '').strip()
            link_text = a.text.strip()
            parent_text = a.parent.text if a.parent else ""
            
            if "領取連結" in parent_text or "領取連結" in link_text:
                if href.startswith('http') and 'freesteam.games' not in href:
                    # 如果超連結本身有文字且不等於「領取連結:」，就用它當顯示名稱
                    display_text = link_text if link_text and link_text not in ["領取連結:", "領取連結：", "領取連結"] else title
                    link_items.append({"text": display_text, "url": href})
                    
        # 3. 如果透過文字找不到，退一步檢查一般外網超連結
        if not link_items:
            for a in content_area.select('a'):
                href = a.get('href', '').strip()
                link_text = a.text.strip()
                href_lower = href.lower()
                
                if any(x in href_lower for x in ['/login', '/download', '/signin', 'support.', 'help.']):
                    continue
                if href.startswith('http') and 'freesteam.games' not in href:
                    display_text = link_text if link_text and len(link_text) > 3 else title
                    link_items.append({"text": display_text, "url": href})
                    
        # 去除重複的網址
        seen_urls = set()
        unique_links = []
        for item in link_items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                unique_links.append(item)
                
        unique_links = unique_links[:4] # 最多取 4 個
        
        if not unique_links:
            return title, [], main_img, False
            
        return title, unique_links, main_img, True
        
    except Exception as e:
        print(f"   ⚠️ 解析文章失敗: {e}")
        return "", [], "", False

def send_to_discord(title, link_items, main_img):
    if not DISCORD_WEBHOOK_URL:
        print("❌ 錯誤：未設定 DISCORD_WEBHOOK_URL")
        return False
        
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    # 🎯 使用原本網頁上的文字來組裝 Discord 訊息
    desc = ""
    for item in link_items:
        link_text = item["text"]
        link_url = item["url"]
        desc += f"🔗 [{link_text}]({link_url})\n"
        
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
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動 (原始文字保留版)...")
    
    if TEST_MODE:
        print("⚠️ 測試模式已開啟")
        if TEST_URL:
            print(f"🔍 正在強制測試指定網址: {TEST_URL}")
            title, link_items, main_img, is_valid = extract_all_store_links_and_pure_images(TEST_URL)
            print(f"   標題: {title}")
            print(f"   是否符合『限時免費』: {is_valid}")
            print(f"   抓取到的連結與文字: {link_items}")
            if is_valid and link_items:
                send_to_discord(title, link_items, main_img)
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
            title, link_items, main_img, is_valid = extract_all_store_links_and_pure_images(article_url)
            
            if is_valid and link_items:
                print(f"   ✅ 成功抓取到 {len(link_items)} 個帶文字的領取連結，準備發送...")
                is_success = send_to_discord(title, link_items, main_img)
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
