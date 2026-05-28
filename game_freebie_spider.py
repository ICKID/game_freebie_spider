import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os
import traceback

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"
URL_4GAMERS_API = "https://www.4gamers.com.tw/site/api/news/by-tag?tag=%E9%99%90%E6%99%82%E5%85%8D%E8%B2%BB&nextStart=0&pageSize=25"
# 🎯 新增海外備用網頁路徑
URL_4GAMERS_WEB = "https://www.4gamers.com.tw/news/tag/%E9%99%90%E6%99%82%E5%85%8D%E8%B2%BB"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

def extract_all_store_links(page_url, news_title=""):
    found_stores = set()
    title_lower = news_title.lower()
    is_epic_news = "epic" in title_lower
    is_steam_news = "steam" in title_lower
    
    try:
        time.sleep(0.5)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return []
        inner_soup = BeautifulSoup(res.text, 'html.parser')
        
        if "4gamers.com.tw" in page_url and not is_epic_news:
            iframes = inner_soup.find_all('iframe', src=True)
            for iframe in iframes:
                src = iframe['src']
                if "store.steampowered.com/widget/" in src:
                    found_stores.add(src.replace('/widget/', '/app/').split('?')[0])

        links = inner_soup.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            if "store.steampowered.com/app/" in href and not is_epic_news:
                if "agecheck" not in href: found_stores.add(href)
            elif "epicgames.com" in href and not is_steam_news:
                if "privacy" not in href and href != "https://store.epicgames.com": found_stores.add(href)
            elif "gog.com" in href and not is_epic_news:
                found_stores.add(href)
    except: pass
    return list(found_stores)

def send_to_discord(title, store_links, source):
    if not store_links: return
    if not DISCORD_WEBHOOK_URL: return
    
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
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
    print("🚀 GitHub Actions 跨國雙軌版爬蟲啟動...")
    
    # 1. FreeSteam
    try:
        print("🔎 正在檢查 FreeSteam...")
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        for article in soup.find_all('article')[:3]:
            tag = article.select_one('.entry-title a, h2 a, h3 a')
            if tag:
                title = tag.text.strip()
                links = extract_all_store_links(tag['href'], title)
                send_to_discord(title, links, "FreeSteam")
    except Exception as e: print(f"❌ FreeSteam 異常: {e}")

    # 2. 4Gamers (備用雙軌偵測)
    try:
        print("🔎 正在檢查 4Gamers (API 模式)...")
        response = requests.get(URL_4GAMERS_API, headers=HEADERS, timeout=15)
        
        # 判斷如果被海外阻擋 (例如狀態碼非 200 或無資料)，自動切換成網頁模式
        if response.status_code == 200 and "data" in response.json():
            news_list = response.json().get('data', {}).get('list', [])
            print(f"   [API] 成功在雲端撈取到 {len(news_list)} 則標題")
            for news in news_list[:3]:
                title = news.get('title', '').strip()
                url = f"https://www.4gamers.com.tw/news/detail/{news.get('id')}"
                links = extract_all_store_links(url, title)
                send_to_discord(title, links, "4Gamers(API)")
        else:
            print("   ⚠️ API 模式遭海外IP限制，啟動【備用網頁無痕爬蟲】技術...")
            web_res = requests.get(URL_4GAMERS_WEB, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(web_res.text, 'html.parser')
            
            # 精準抓取 4Gamers 標籤頁面的文章區塊
            articles = soup.select('div.news_tags_list div.news-card, div.posts-row a, a.news-card')
            if not articles:
                # 泛用型抓取超連結
                articles = [a for a in soup.find_all('a', href=True) if "/news/detail/" in a['href']][:4]
                
            count = 0
            for a in articles:
                url_path = a['href']
                url = url_path if url_path.startswith('http') else f"https://www.4gamers.com.tw{url_path}"
                
                title = a.get_text().strip()
                title = title.split('\n')[0] # 只要第一行，過濾雜訊
                
                if title and "/news/detail/" in url:
                    links = extract_all_store_links(url, title)
                    send_to_discord(title, links, "4Gamers(網頁版)")
                    count += 1
                    if count >= 3: break
            print(f"   [網頁版] 成功繞過限制，處理了 {count} 則新聞")
            
    except Exception as e:
        print(f"❌ 4Gamers 雙軌流程皆發生異常: {e}")

    print("\n🎉 全數流程執行完畢！")

if __name__ == "__main__":
    main()
