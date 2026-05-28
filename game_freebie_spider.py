import time
import requests
from bs4 import BeautifulSoup
import os

# 讀取 GitHub Secrets 保險箱
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"
HISTORY_FILE = "posted_links.txt" # 記憶已發送網址的檔案

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def load_history():
    """讀取過去已經發送過的網址歷史紀錄"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_history(history_set):
    """將發送過的網址更新回檔案中"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for link in sorted(history_set):
            f.write(f"{link}\n")

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
            
            # 處理 Steam 網址
            if "store.steampowered.com/app/" in href and not is_epic_news:
                if "agecheck" not in href: found_stores.add(href)
                    
            # 處理 Epic 網址 (過濾掉登入、下載、主首頁等無效連結)
            elif "epicgames.com" in href and not is_steam_news:
                if "id/login" not in href and "download" not in href and "privacy" not in href:
                    if href != "https://store.epicgames.com" and href != "https://www.epicgames.com":
                        found_stores.add(href)
                    
            # 處理 GOG 網址
            elif "gog.com" in href and not is_epic_news:
                found_stores.add(href)
    except: 
        pass
    return list(found_stores)

def send_to_discord(title, store_links):
    """將結果打包發送到 Discord 頻道"""
    if not store_links: return
    if not DISCORD_WEBHOOK_URL: return
    
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    # 根據平台動態調整卡片顏色 (Steam=藍色, Epic=黑色, GOG=金色)
    links_str = "".join(store_links).lower()
    card_color = "00c0ff" if "steam" in links_str else "1a1a1a" if "epic" in links_str else "f1c40f"
    
    # 🎯 已刪除 description 欄位，卡片標題下方不再顯示「資訊來源」
    embed = DiscordEmbed(title=title, color=card_color)
    links_text = ""
    for link in store_links:
        platform = "Steam" if "steam" in link else "Epic Games" if "epic" in link else "GOG"
        links_text += f"🎮 [{platform} 直達傳送門]({link})\n"
        
    embed.add_embed_field(name="🎁 領取網址", value=links_text, inline=False)
    embed.set_timestamp()
    webhook.add_embed(embed)
    webhook.execute()

def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動（單一源純淨版）...")
    
    history = load_history()
    print(f"📋 載入歷史紀錄，目前已記憶了 {len(history)} 個網址。")
    
    try:
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')
        
        count = 0
        # 從舊到新比對
        for article in reversed(articles[:5]): 
            tag = article.select_one('.entry-title a, h2 a, h3 a')
            if tag:
                article_url = tag['href'].strip()
                title = tag.text.strip()
                
                if article_url in history:
