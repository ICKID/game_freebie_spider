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

def get_gog_cover_via_api(gog_url):
    try:
        slug = gog_url.split('/game/')[-1].split('/')[0]
        if slug:
            api_url = f"https://catalog.gog.com/v1/catalog?slug={slug}"
            res = requests.get(api_url, headers=HEADERS, timeout=5)
            if res.status_code == 200:
                products = res.json().get('products', [])
                if products:
                    return products[0].get('coverHorizontal') or products[0].get('coverVertical')
    except: pass
    return None

def extract_all_store_links_and_fallback_image(page_url, news_title=""):
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

        img_tag = inner_soup.select_one('meta[property="og:image"]') or inner_soup.select_one('.entry-content img')
        if img_tag:
            fallback_image = img_tag.get('content') or img_tag.get('src')

        links = inner_soup.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            if "store.steampowered.com/app/" in href and not is_epic_news:
                if "agecheck" not in href: found_stores.add(href)
            elif "epicgames.com" in href and not is_steam_news:
                if "id/login" not in href and "download" not in href and "privacy" not in href:
                    if href != "https://store.epicgames.com" and href != "https://www.epicgames.com":
                        found_stores.add(href)
            elif "gog.com" in href and not is_epic_news:
                if "##openlogin" in href:
                    href = href.split("##")[0].rstrip('/')
                if "account/login" not in href and href != "https://www.gog.com":
                    found_stores.add(href)
    except: pass
    return list(found_stores), fallback_image

def send_to_discord(title, store_links, fallback_image):
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
        
        if "store.steampowered.com/app/" in link and not final_image_url:
            try:
                parts = link.split('/app/')
                if len(parts) > 1:
                    app_id = parts[1].split('/')[0]
                    final_image_url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg"
            except: pass
        elif "gog.com" in link and not final_image_url:
            final_image_url = get_gog_cover_via_api(link)
            
    if not final_image_url and fallback_image:
        final_image_url = fallback_image
        
    embed.add_embed_field(name="🎁 領取網址", value=links_text, inline=False)
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
        
        # 🎯 核心測試邏輯：如果開啟測試模式，我們用計數器強抓三大平台各 2 個
        if IS_TEST_MODE:
            print("⚠️ 【測試強制推播模式】開啟！將在歷史文章中各挖出 2 篇 Steam/Epic/GOG 進行圖片測試。")
            steam_count, epic_count, gog_count = 0, 0, 0
            
            # 測試模式下多搜尋一點歷史文章（前30篇），確保撈得到足夠的平台樣本
            for article in articles[:30]: 
                tag = article.select_one('.entry-title a, h2 a, h3 a')
                if tag:
                    title = tag.text.strip().lower()
                    
                    # 分流判定當前文章屬於哪個平台
                    is_steam = "steam" in title
                    is_epic = "epic" in title
                    is_gog = "gog" in title
                    
                    # 如果該平台已經集滿 2 個，就跳過
                    if is_steam and steam_count >= 2: continue
                    if is_epic and epic_count >= 2: continue
                    if is_gog and gog_count >= 2: continue
                    if not (is_steam or is_epic or is_gog): continue # 沒寫平台的不抓
                    
                    article_url = tag['href'].strip()
                    print(f"   [測試模式] 正在強力解析: {tag.text.strip()[:20]}...")
                    links, fallback_img = extract_all_store_links_and_fallback_image(article_url, tag.text.strip())
                    
                    if links:
                        send_to_discord(tag.text.strip(), links, fallback_img)
                        # 更新計數器
                        if is_steam: steam_count += 1
                        if is_epic: epic_count += 1
                        if is_gog: gog_count += 1
                        
                # 如果三大平台都各自集滿 2 篇，就提早收工
                if steam_count >= 2 and epic_count >= 2 and gog_count >= 2:
                    break
                    
            print(f"   🎉 測試發送完畢！(Steam: {steam_count}/2, Epic: {epic_count}/2, GOG: {gog_count}/2)")
            
        else:
            # 🟢 正常自動排程模式（維持原樣，嚴格守護去重防線，不重發）
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
                    links, fallback_img = extract_all_store_links_and_fallback_image(article_url, title)
                    
                    if links:
                        send_to_discord(title, links, fallback_img)
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
