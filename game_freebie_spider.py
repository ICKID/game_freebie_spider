import time
import requests
from bs4 import BeautifulSoup
import os

# 讀取 GitHub Secrets 保險箱
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"
HISTORY_FILE = "posted_links.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_history(history_set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for link in sorted(history_set):
            f.write(f"{link}\n")

def get_gog_cover_via_api(gog_url):
    """【GOG 黑魔法】透過隱藏 API 獲取 GOG 高清遊戲封面"""
    try:
        # 從網址提取遊戲代號，例如 /game/cyberpunk_2077 -> cyberpunk_2077
        slug = gog_url.split('/game/')[-1].split('/')[0]
        if slug:
            api_url = f"https://api.gog.com/products?product_id={slug}"
            # 如果是英文別名，改用這個產品細節 API
            api_url = f"https://catalog.gog.com/v1/catalog?slug={slug}"
            res = requests.get(api_url, headers=HEADERS, timeout=5)
            if res.status_code == 200:
                data = res.json()
                # 提取型錄中的特大封面圖
                products = data.get('products', [])
                if products:
                    return products[0].get('coverHorizontal') or products[0].get('coverVertical')
    except: pass
    return None

def extract_all_store_links_and_fallback_image(page_url, news_title=""):
    """精準提取商店連結，同時『順手』把網頁裡面的精美宣傳圖撈出來備用"""
    found_stores = set()
    fallback_image = None
    title_lower = news_title.lower()
    is_epic_news = "epic" in title_lower
    is_steam_news = "steam" in title_lower
    
    try:
        time.sleep(0.5)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return [], None
        inner_soup = BeautifulSoup(res.text, 'html.parser')

        # 🎯 為了 Epic！先抓取這篇 FreeSteam 文章裡的主圖或大張宣傳圖
        img_tag = inner_soup.select_one('meta[property="og:image"]') or inner_soup.select_one('.entry-content img')
        if img_tag:
            fallback_image = img_tag.get('content') or img_tag.get('src')

        links = inner_soup.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            
            # 1. Steam
            if "store.steampowered.com/app/" in href and not is_epic_news:
                if "agecheck" not in href: found_stores.add(href)
                    
            # 2. Epic Games
            elif "epicgames.com" in href and not is_steam_news:
                if "id/login" not in href and "download" not in href and "privacy" not in href:
                    if href != "https://store.epicgames.com" and href != "https://www.epicgames.com":
                        found_stores.add(href)
                    
            # 3. GOG
            elif "gog.com" in href and not is_epic_news:
                if "##openlogin" in href:
                    href = href.split("##")[0].rstrip('/')
                if "account/login" not in href and href != "https://www.gog.com":
                    found_stores.add(href)
    except: 
        pass
    return list(found_stores), fallback_image

def send_to_discord(title, store_links, fallback_image):
    """將結果打包發送到 Discord 頻道（全平台智慧封面判定）"""
    if not store_links: return
    if not DISCORD_WEBHOOK_URL: return
    
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    links_str = "".join(store_links).lower()
    card_color = "00c0ff" if "steam" in links_str else "1a1a1a" if "epic" in links_str else "f1c40f"
    
    embed = DiscordEmbed(title=title, color=card_color)
    links_text = ""
    final_image_url = None
    
    for link in store_links:
        platform = "Steam" if "steam" in link else "Epic Games" if "epic" in link else "GOG"
        links_text += f"🎮 [{platform} 直達傳送門]({link})\n"
        
        # 🎯 封面圖智慧優先級判定：
        # 1. 如果是 Steam -> 用 ID 拼出 Steam 官方高清大圖
        if "store.steampowered.com/app/" in link and not final_image_url:
            try:
                parts = link.split('/app/')
                if len(parts) > 1:
                    app_id = parts[1].split('/')[0]
                    final_image_url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg"
            except: pass
            
        # 2. 如果是 GOG -> 戳 API 拿官方封面
        elif "gog.com" in link and not final_image_url:
            final_image_url = get_gog_cover_via_api(link)
            
    # 3. 如果是 Epic（或者是 GOG 沒抓到 API 封面）-> 使用 FreeSteam 內文撈出來的宣傳大圖
    if not final_image_url and fallback_image:
        final_image_url = fallback_image
        
    embed.add_embed_field(name="🎁 領取網址", value=links_text, inline=False)
    
    # 如果有任何管道拿到封面圖，就塞進卡片
    if final_image_url:
        embed.set_image(url=final_image_url)
        
    embed.set_timestamp()
    webhook.add_embed(embed)
    webhook.execute()

def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動（全平台封面旗艦版）...")
    
    history = load_history()
    print(f"📋 載入歷史紀錄，目前已記憶了 {len(history)} 個網址。")
    
    try:
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')
        
        count = 0
        for article in reversed(articles[:5]): 
            tag = article.select_one('.entry-title a, h2 a, h3 a')
            if tag:
                article_url = tag['href'].strip()
                title = tag.text.strip()
                
                if article_url in history:
                    print(f"   Skip: {title[:20]}...")
                    continue
                
                print(f"   New Article: {title[:20]}...")
                # 同時回傳商店連結與內文備用大圖
                links, fallback_img = extract_all_store_links_and_fallback_image(article_url, title)
                
                if links:
                    send_to_discord(title, links, fallback_img)
                    history.add(article_url)
                    count += 1
                else:
                    print("   ⚠️ 無有效商店連結，標記為已讀。")
                    history.add(article_url)
                    
        save_history(history)
        print(f"   [FreeSteam] 處理完畢，共推播了 {count} 則全新限免！")
        
    except Exception as e:
        print(f"❌ 發生異常: {e}")

    print("\n🎉 全數流程執行完畢！")

if __name__ == "__main__":
    main()
