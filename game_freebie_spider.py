import time
import requests
from bs4 import BeautifulSoup
import os

# 讀取 GitHub Secrets 保險箱
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def extract_all_store_links(page_url, news_title=""):
    """精準提取內頁的遊戲商店領取網址，並過濾雜訊"""
    found_stores = set()
    title_lower = news_title.lower()
    is_epic_news = "epic" in title_lower
    is_steam_news = "steam" in title_lower
    
    try:
        time.sleep(0.5)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return []
        inner_soup = BeautifulSoup(res.text, 'html.parser')

        links = inner_soup.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            
            # 1. 處理 Steam 網址 (如果標題表明是 Epic 限免，就過濾掉無關的 Steam 網址)
            if "store.steampowered.com/app/" in href and not is_epic_news:
                if "agecheck" not in href: 
                    found_stores.add(href)
                    
            # 2. 處理 Epic 網址 (過濾掉登入、下載、主首頁等無效連結)
            elif "epicgames.com" in href and not is_steam_news:
                if "id/login" not in href and "download" not in href and "privacy" not in href:
                    if href != "https://store.epicgames.com" and href != "https://www.epicgames.com":
                        found_stores.add(href)
                    
            # 3. 處理 GOG 網址
            elif "gog.com" in href and not is_epic_news:
                found_stores.add(href)
    except: 
        pass
    return list(found_stores)

def send_to_discord(title, store_links, source):
    """將結果打包發送到 Discord 頻道"""
    if not store_links: return
    if not DISCORD_WEBHOOK_URL: 
        print("❌ 找不到 Discord Webhook 網址，請檢查 GitHub Secrets！")
        return
    
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    # 根據平台動態調整卡片顏色 (Steam=藍色, Epic=灰色/黑色, GOG=金色)
    links_str = "".join(store_links).lower()
    card_color = "00c0ff" if "steam" in links_str else "1a1a1a" if "epic" in links_str else "f1c40f"
    
    embed = DiscordEmbed(title=title, description=f"📰 資訊來源: {source}", color=card_color)
    links_text = ""
    for link in store_links:
        platform = "Steam" if "steam" in link else "Epic Games" if "epic" in link else "GOG"
        links_text += f"🎮 [{platform} 直達傳送門]({link})\n"
        
    embed.add_embed_field(name="🎁 領取網址", value=links_text, inline=False)
    embed.set_timestamp()
    webhook.add_embed(embed)
    webhook.execute()

def main():
    print("🚀 GitHub Actions 穩定版限免爬蟲啟動（目標：FreeSteam）...")
    
    try:
        print("🔎 正在檢查 FreeSteam 最新限免情報...")
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        print(f"   FreeSteam 回應狀態碼: {response.status_code}")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')
        print(f"   成功撈取到 {len(articles)} 則最新情報，準備解析前 3 篇...")
        
        count = 0
        for article in articles[:3]: # 每次推播最新的前 3 篇
            tag = article.select_one('.entry-title a, h2 a, h3 a')
            if tag:
                title = tag.text.strip()
                print(f"   [FreeSteam] 正在解析內頁: {title[:30]}...")
                links = extract_all_store_links(tag['href'], title)
                
                if links:
                    send_to_discord(title, links, "FreeSteam")
                    count += 1
                else:
                    print("   ⚠️ 該文章內未偵測到有效的商店直達連結，跳過推播。")
                    
        print(f"   [FreeSteam] 處理完畢，共成功推播了 {count} 則新聞至 Discord！")
        
    except Exception as e: 
        print(f"❌ FreeSteam 流程發生異常: {e}")

    print("\n🎉 全數流程執行完畢！")

if __name__ == "__main__":
    main()
