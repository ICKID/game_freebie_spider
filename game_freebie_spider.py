import time
import requests
from bs4 import BeautifulSoup
import os

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
IS_TEST_MODE = os.environ.get("TEST_MODE") == "true"

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

def get_gog_cover_via_web(gog_url):
    """【GOG 精準拿圖】進網頁拔標準分享圖"""
    try:
        time.sleep(0.3)
        res = requests.get(gog_url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            img_tag = soup.select_one('meta[property="og:image"]')
            if img_tag and img_tag.get('content'):
                return img_tag['content']
    except: pass
    return None

def extract_all_store_links_and_pure_images(page_url):
    """只抓內文的領取網址和關聯商店網址，並透過這些網址精準生圖，徹底排除側欄雜訊"""
    found_stores = set()
    all_game_urls_in_article = set() # 儲存文章裡出現過的所有商店網址（包含延伸對比連結）
    
    try:
        time.sleep(0.5)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return [], []
        inner_soup = BeautifulSoup(res.text, 'html.parser')

        # 🎯 只鎖定文章主體區塊，避開整個網站的側邊欄、頁尾等髒資料
        content_area = inner_soup.select_one('.entry-content') or inner_soup

        links = content_area.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            
            # A. 收集 Steam 連結
            if "store.steampowered.com/app/" in href:
                if "agecheck" not in href:
                    all_game_urls_in_article.add(href)
                    # 只有在非 Epic 專場時，它才作為主要直達領取門
                    found_stores.add(href)
                    
            # B. 收集 Epic 連結
            elif "epicgames.com" in href:
                if "id/login" not in href and "download" not in href and "privacy" not in href:
                    if href != "https://store.epicgames.com" and href != "https://www.epicgames.com":
                        found_stores.add(href)
                        all_game_urls_in_article.add(href)
                        
            # C. 收集 GOG 連結
            elif "gog.com" in href:
                if "##openlogin" in href:
                    href = href.split("##")[0].rstrip('/')
                if "account/login" not in href and href != "https://www.gog.com":
                    found_stores.add(href)
                    all_game_urls_in_article.add(href)
                    
        # 🎯 檢查有沒有嵌入的 Steam Widget <iframe> 遊戲小工具大圖
        iframes = content_area.find_all('iframe', src=True)
        for iframe in iframes:
            src = iframe['src']
            if "store.steampowered.com/widget/" in src:
                try:
                    app_id = src.split('/widget/')[1].split('/')[0]
                    widget_steam_url = f"https://store.steampowered.com/app/{app_id}"
                    all_game_urls_in_article.add(widget_steam_url)
                except: pass

    except: pass
    return list(found_stores), list(all_game_urls_in_article)

def send_to_discord_clean_images(title, store_links, all_game_urls):
    """透過嚴格篩選的網址清單，來生成 100% 精準的 Discord 多圖相簿"""
    if not store_links: return
    if not DISCORD_WEBHOOK_URL: return
    
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    links_str = "".join(store_links).lower()
    card_color = "00c0ff" if "steam" in links_str else "1a1a1a" if "epic" in links_str else "f1c40f"
    
    # 🕵️‍♂️ 核心精準圖片生成演算法
    collected_covers = []
    
    # 對文章內出現的所有關聯網址進行掃描，抓取它們的官方封面
    for game_url in all_game_urls:
        if "store.steampowered.com/app/" in game_url:
            try:
                app_id = game_url.split('/app/')[1].split('/')[0]
                img_url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg"
                if img_url not in collected_covers:
                    collected_covers.append(img_url)
            except: pass
        elif "gog.com" in game_url:
            gog_cover = get_gog_cover_via_web(game_url)
            if gog_cover and gog_cover not in collected_covers:
                collected_covers.append(gog_cover)

    # 建立傳送門清單文字
    links_text = ""
    for link in store_links:
        platform = "Steam" if "steam" in link else "Epic Games" if "epic" in link else "GOG"
        links_text += f"🎮 [{platform} 直達傳送門]({link})\n"

    # 打包發送 Discord Embed Group
    main_embed = DiscordEmbed(title=title, color=card_color)
    main_embed.add_embed_field(name="🎁 領取網址", value=links_text, inline=False)
    
    if collected_covers:
        main_embed.set_image(url=collected_covers[0])
    main_embed.set_timestamp()
    webhook.add_embed(main_embed)
    
    # 如果有複數遊戲（例如 Epic 同時送兩款且都有附帶 Steam 網址），自動排成相簿
    for extra_img in collected_covers[1:4]:
        sub_embed = DiscordEmbed(color=card_color)
        sub_embed.set_image(url=extra_img)
        webhook.add_embed(sub_embed)

    try:
        webhook.execute()
    except Exception as e:
        print(f"❌ Discord 發送失敗: {e}")

def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動（網址追蹤純淨版）...")
    
    history = load_history()
    print(f"📋 載入歷史紀錄，目前已記憶了 {len(history)} 個網址。")
    
    try:
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')
        
        if IS_TEST_MODE:
            print("⚠️ 【測試強制推播模式】開啟！三大平台各挖出 2 篇進行網址純淨多圖測試。")
            steam_count, epic_count, gog_count = 0, 0, 0
            
            for article in articles[:30]: 
                tag = article.select_one('.entry-title a, h2 a, h3 a')
                if tag:
                    title = tag.text.strip().lower()
                    is_steam = "steam" in title
                    is_epic = "epic" in title
                    is_gog = "gog" in title
                    
                    if is_steam and steam_count >= 2: continue
                    if is_epic and epic_count >= 2: continue
                    if is_gog and gog_count >= 2: continue
                    if not (is_steam or is_epic or is_gog): continue
                    
                    article_url = tag['href'].strip()
                    print(f"   [測試模式] 正在解析: {tag.text.strip()[:20]}...")
                    
                    # 🎯 這裡改回傳商店連結以及關聯網址
                    links, all_game_urls = extract_all_store_links_and_pure_images(article_url)
                    
                    if links:
                        send_to_discord_clean_images(tag.text.strip(), links, all_game_urls)
                        if is_steam: steam_count += 1
                        if is_epic: epic_count += 1
                        if is_gog: gog_count += 1
                        
                if steam_count >= 2 and epic_count >= 2 and gog_count >= 2:
                    break
            print(f"   🎉 測試發送完畢！(Steam: {steam_count}/2, Epic: {epic_count}/2, GOG: {gog_count}/2)")
            
        else:
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
                    links, all_game_urls = extract_all_store_links_and_pure_images(article_url)
                    
                    if links:
                        send_to_discord_clean_images(title, links, all_game_urls)
                        history.add(article_url)
                        count += 1
                    else:
                        print("   ⚠️ 無有效商店連結，標記為已讀。")
                        history.add(article_url)
                        
            save_history(history)
            print(f"   [FreeSteam] 自動排程處理完畢，共推播了 {count} 則全新限免！")
        
    except Exception as e:
        print(f"❌ 發生異常: {e}")

    print("\n🎉 全數流程執行完畢！")

if __name__ == "__main__":
    main()
