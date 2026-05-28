import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os
import traceback # 🎯 引入追蹤工具

# 讀取 GitHub Secrets 保險箱
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"
URL_4GAMERS_API = "https://www.4gamers.com.tw/site/api/news/by-tag?tag=%E9%99%90%E6%99%82%E5%85%8D%E8%B2%BB&nextStart=0&pageSize=25"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/json",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/"
}

def extract_all_store_links(page_url):
    found_stores = set()
    try:
        time.sleep(0.3)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return []
        inner_soup = BeautifulSoup(res.text, 'html.parser')
        
        if "4gamers.com.tw" in page_url:
            iframes = inner_soup.find_all('iframe', src=True)
            for iframe in iframes:
                src = iframe['src']
                if "store.steampowered.com/widget/" in src:
                    found_stores.add(src.replace('/widget/', '/app/').split('?')[0])

        links = inner_soup.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            if "store.steampowered.com/app/" in href or "epicgames.com" in href or "gog.com" in href:
                if "agecheck" not in href and "privacy" not in href and href != "https://store.epicgames.com":
                    found_stores.add(href)
    except: pass
    return list(found_stores)

def send_to_discord(title, store_links, source):
    if not store_links: return
    if not DISCORD_WEBHOOK_URL:
        print(f"❌ 錯誤：找不到 Discord Webhook 網址，請檢查 GitHub Secrets 設定！")
        return
        
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    card_color = "00c0ff" if "steam" in "".join(store_links) else "1a1a1a"
    
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
    print("🚀 GitHub Actions 爬蟲開始執行...")
    
    if not DISCORD_WEBHOOK_URL:
        print("🚨 [嚴重錯誤] GitHub Secrets 中的 DISCORD_WEBHOOK_URL 沒有讀取到！請確認保險箱名稱是否完全正確。")
    
    # 1. FreeSteam
    try:
        print("🔎 正在檢查 FreeSteam...")
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        print(f"   FreeSteam 回應狀態碼: {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        for article in soup.find_all('article')[:3]:
            tag = article.select_one('.entry-title a, h2 a, h3 a')
            if tag:
                links = extract_all_store_links(tag['href'])
                send_to_discord(tag.text.strip(), links, "FreeSteam")
    except Exception as e:
        print(f"❌ FreeSteam 流程發生異常:")
        traceback.print_exc() # 🎯 印出死在哪一行

    # 2. 4Gamers
    try:
        print("🔎 正在檢查 4Gamers...")
        response = requests.get(URL_4GAMERS_API, headers=HEADERS, timeout=15)
        print(f"   4Gamers 回應狀態碼: {response.status_code}")
        news_list = response.json().get('data', {}).get('list', [])[:3]
        for news in news_list:
            title = news.get('title', '').strip()
            url = f"https://www.4gamers.com.tw/news/detail/{news.get('id')}"
            if title and url:
                links = extract_all_store_links(url)
                send_to_discord(title, links, "4Gamers")
    except Exception as e:
        print(f"❌ 4Gamers 流程發生異常:")
        traceback.print_exc() # 🎯 印出死在哪一行

    print("\n🎉 全數流程執行完畢！")

if __name__ == "__main__":
    main()
