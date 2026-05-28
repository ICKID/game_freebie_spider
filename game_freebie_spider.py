import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os
import traceback

# 讀取 GitHub Secrets 保險箱
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"
URL_4GAMERS_API = "https://www.4gamers.com.tw/site/api/news/by-tag?tag=%E9%99%90%E6%99%82%E5%85%8D%E8%B2%BB&nextStart=0&pageSize=25"

# 🎯 升級 Header：加入更嚴格的瀏覽器偽裝，防止 4Gamers 阻擋海外雲端 IP
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.4gamers.com.tw/news/tag/%E9%99%90%E6%99%82%E5%85%8D%E8%B2%BB"
}

def extract_all_store_links(page_url, news_title=""):
    """【精準過濾版】深入內頁，並根據新聞標題進行平台交叉比對過濾"""
    found_stores = set()
    
    # 🎯 判斷這篇新聞到底是講什麼平台
    title_lower = news_title.lower()
    is_epic_news = "epic" in title_lower
    is_steam_news = "steam" in title_lower
    
    try:
        time.sleep(0.5)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return []
        inner_soup = BeautifulSoup(res.text, 'html.parser')
        
        # 🕵️‍♂️ 策略一：拆解 4Gamers 的 Steam 內嵌框框 (如果是 Epic 新聞就直接跳過不抓 Steam widget)
        if "4gamers.com.tw" in page_url and not is_epic_news:
            iframes = inner_soup.find_all('iframe', src=True)
            for iframe in iframes:
                src = iframe['src']
                if "store.steampowered.com/widget/" in src:
                    found_stores.add(src.replace('/widget/', '/app/').split('?')[0])

        # 🕵️‍♂️ 策略二：掃描內文所有的 <a> 標籤超連結
        links = inner_soup.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            
            # 1. 處理 Steam 網址 (只有在非 Epic 新聞，或者明確是 Steam 新聞時才抓)
            if "store.steampowered.com/app/" in href and not is_epic_news:
                if "agecheck" not in href:
                    found_stores.add(href)
                    
            # 2. 處理 Epic 網址 (只有在非 Steam 新聞，或者明確是 Epic 新聞時才抓)
            elif "epicgames.com" in href and not is_steam_news:
                if "privacy" not in href and href != "https://store.epicgames.com":
                    found_stores.add(href)
                    
            # 3. 處理 GOG 網址
            elif "gog.com" in href and not is_epic_news:
                found_stores.add(href)
    except:
        pass
    return list(found_stores)

def send_to_discord(title, store_links, source):
    if not store_links: return
    if not DISCORD_WEBHOOK_URL:
        print(f"❌ 找不到 Discord Webhook 網址")
        return
        
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    # 判斷卡片顏色
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
    print("🚀 GitHub Actions 終極優化版爬蟲開始執行...")
    
    # 1. 檢查 FreeSteam
    try:
        print("🔎 正在檢查 FreeSteam...")
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        print(f"   FreeSteam 回應狀態碼: {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        for article in soup.find_all('article')[:3]:
            tag = article.select_one('.entry-title a, h2 a, h3 a')
            if tag:
                title = tag.text.strip()
                links = extract_all_store_links(tag['href'], title)
                send_to_discord(title, links, "FreeSteam")
    except Exception as e:
        print(f"❌ FreeSteam 流程發生異常: {e}")

    # 2. 檢查 4Gamers
    try:
        print("🔎 正在檢查 4Gamers...")
        response = requests.get(URL_4GAMERS_API, headers=HEADERS, timeout=15)
        print(f"   4Gamers 回應狀態碼: {response.status_code}")
        
        # 檢查是否成功取得 JSON
        data = response.json()
        news_list = data.get('data', {}).get('list', [])
        if not news_list:
            news_list = data.get('list', [])
            
        print(f"   成功撈取到 {len(news_list)} 則 4Gamers 新聞標題")
        
        for news in news_list[:3]:
            title = news.get('title', '').strip()
            url = f"https://www.4gamers.com.tw/news/detail/{news.get('id')}"
            if title and url:
                links = extract_all_store_links(url, title)
                send_to_discord(title, links, "4Gamers")
    except Exception as e:
        print(f"❌ 4Gamers 流程發生異常: {e}")

    print("\n🎉 全數流程執行完畢！")

if __name__ == "__main__":
    main()
