import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"
# 🎯 改用對海外 IP 超友善、資訊更狂的巴哈姆特 GNN 「限時免費」新聞關鍵字頁面
URL_BAHA_GNN = "https://gnn.gamer.com.tw/search.php?kw=%B9%A5%AE%C9%A5%C2%B0%EA" # "限時免費" 的 Big5 編碼

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

def extract_all_store_links(page_url, news_title=""):
    found_stores = set()
    title_lower = news_title.lower()
    is_epic_news = "epic" in title_lower or "了解更多" in title_lower
    is_steam_news = "steam" in title_lower
    
    try:
        time.sleep(0.5)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return []
        inner_soup = BeautifulSoup(res.text, 'html.parser')

        links = inner_soup.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            
            # 1. 處理 Steam 網址
            if "store.steampowered.com/app/" in href and not is_epic_news:
                if "agecheck" not in href: found_stores.add(href)
                    
            # 2. 處理 Epic 網址
            elif "epicgames.com" in href and not is_steam_news:
                if "privacy" not in href and href != "https://store.epicgames.com": found_stores.add(href)
                    
            # 3. 處理 GOG 網址
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
    print("🚀 GitHub Actions 跨國終極版爬蟲啟動...")
    
    # 1. 檢查 FreeSteam
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

    # 2. 檢查 巴哈姆特 GNN 新聞 (完美暢通無阻)
    try:
        print("🔎 正在檢查 巴哈姆特 GNN 新聞...")
        response = requests.get(URL_BAHA_GNN, headers=HEADERS, timeout=15)
        print(f"   巴哈姆特回應狀態碼: {response.status_code}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # 抓取巴哈搜尋頁面的新聞區塊
            news_blocks = soup.select('div.GN-lbox2 p.GN-lbox2B a')
            if not news_blocks:
                # 備用選擇器
                news_blocks = [a for a in soup.find_all('a', href=True) if "sn=" in a['href']]
                
            print(f"   [巴哈姆特] 成功在雲端撈取到 {len(news_blocks)} 則相關限免新聞！")
            
            count = 0
            seen_urls = set()
            for a in news_blocks:
                url_path = a['href']
                url = url_path if url_path.startswith('http') else f"https:{url_path}"
                
                if url in seen_urls: continue
                seen_urls.add(url)
                
                title = a.get_text().strip()
                # 過濾掉太短的無效文字（例如點擊次數或作者名）
                if len(title) < 8: continue
                
                print(f"   [巴哈姆特] 正在解析: {title[:18]}...")
                links = extract_all_store_links(url, title)
                send_to_discord(title, links, "巴哈姆特 GNN")
                
                count += 1
                if count >= 3: break
            print(f"   [巴哈姆特] 處理完畢，共推播了 {count} 則新聞")
        else:
            print(f"   ❌ 巴哈姆特回傳錯誤碼: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 巴哈姆特流程發生異常: {e}")

    print("\n🎉 全數流程執行完畢！")

if __name__ == "__main__":
    main()
