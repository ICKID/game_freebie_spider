import time
import requests
from bs4 import BeautifulSoup
import os
import sys # 🎯 確保有載入 sys 模組

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
IS_TEST_MODE = os.environ.get("TEST_MODE") == "true" or "--test" in sys.argv
TEST_URL = os.environ.get("TEST_URL", "").strip() # 🎯 讀取環境變數中的指定測試網址

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
    try:
        time.sleep(0.3)
        res = requests.get(gog_url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            img_tag = soup.select_one('meta[property="og:image"]')
            if img_tag and img_tag.get('content'):
                return img_tag['content'].split('?')[0].strip()
    except: pass
    return None

def extract_all_store_links_and_pure_images(page_url):
    """提取商店連結與關聯網址，並分別撈出首頁圖與 Steam 小工具圖"""
    found_stores = set()
    widget_steam_urls = [] 
    all_game_urls_in_article = set()
    freesteam_main_image = None
    
    try:
        time.sleep(0.5)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return [], [], None
        inner_soup = BeautifulSoup(res.text, 'html.parser')

        og_img = inner_soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get('content'):
            freesteam_main_image = og_img['content'].split('?')[0].strip()

        content_area = inner_soup.select_one('.entry-content') or inner_soup

        iframes = content_area.find_all('iframe', src=True)
        for iframe in iframes:
            src = iframe['src']
            if "store.steampowered.com/widget/" in src:
                try:
                    app_id = src.split('/widget/')[1].split('/')[0]
                    widget_url = f"https://store.steampowered.com/app/{app_id}"
                    if widget_url not in widget_steam_urls:
                        widget_steam_urls.append(widget_url)
                except: pass

        links = content_area.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            
            if "store.steampowered.com/app/" in href:
                if "agecheck" not in href:
                    all_game_urls_in_article.add(href)
                    found_stores.add(href)
            elif "epicgames.com" in href:
                if "id/login" not in href and "download" not in href and "privacy" not in href:
                    if href != "https://store.epicgames.com" and href != "https://www.epicgames.com":
                        found_stores.add(href)
                        all_game_urls_in_article.add(href)
            elif "gog.com" in href:
                if "##openlogin" in href:
                    href = href.split("##")[0].rstrip('/')
                if "account/login" not in href and href != "https://www.gog.com":
                    found_stores.add(href)
                    all_game_urls_in_article.add(href)

    except: pass
    
    if not widget_steam_urls:
        widget_steam_urls = [x for x in all_game_urls_in_article if "store.steampowered.com" in x]
        
    return list(found_stores), widget_steam_urls, freesteam_main_image

def send_to_discord_clean_images(title, store_links, widget_steam_urls, freesteam_main_image):
    """大放送專用智慧除噪發送演算法（多圖相簿強化版）"""
    if not store_links: return
    if not DISCORD_WEBHOOK_URL: return
    
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    links_str = "".join(store_links).lower()
    card_color = "00c0ff" if "steam" in links_str else "1a1a1a" if "epic" in links_str else "f1c40f"
    
    collected_covers = []
    
    if len(store_links) == 1:
        if freesteam_main_image:
            collected_covers.append(freesteam_main_image)
    else:
        for widget_url in widget_steam_urls:
            try:
                app_id = widget_url.split('/app/')[1].split('/')[0]
                img_url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg"
                if img_url not in collected_covers:
                    collected_covers.append(img_url)
            except: pass
            
        if not collected_covers and freesteam_main_image:
            collected_covers.append(freesteam_main_image)

    links_text = ""
    for link in store_links:
        platform = "Steam" if "steam" in link else "Epic Games" if "epic" in link else "GOG"
        links_text += f"🎮 [{platform} 直達傳送門]({link})\n"

    main_embed = DiscordEmbed(title=title, color=card_color)
    main_embed.add_embed_field(name="🎁 領取網址", value=links_text, inline=False)
    
    if collected_covers:
        main_embed.set_image(url=collected_covers[0])
    main_embed.set_timestamp()
    webhook.add_embed(main_embed)
    
    if collected_covers and len(collected_covers) > 1:
        for extra_img in collected_covers[1:4]:
            sub_embed = DiscordEmbed(color=card_color)
            sub_embed.set_image(url=extra_img)
            webhook.add_embed(sub_embed)

    try:
        webhook.execute()
        print("   🎉 Discord 測試發送成功！")
    except Exception as e:
        print(f"❌ Discord 發送失敗: {e}")

def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動（測試網址修正版）...")
    
    # 🎯 核心修正：如果設定了 TEST_URL，直接優先針對該網址進行測試發送！
    if TEST_MODE and TEST_URL:
        print(f"⚠️ 【強制指定測試網址】正在解析: {TEST_URL}")
        try:
            # 為了抓到文章標題，我們可以直接請求該網頁
            res = requests.get(TEST_URL, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            title_tag = soup.select_one('h1.entry-title, h1')
            title = title_tag.text.strip() if title_tag else "測試限免遊戲"
            
            links, widget_urls, main_img = extract_all_store_links_and_pure_images(TEST_URL)
            print(f"   抓到的商店連結: {links}")
            print(f"   抓到的 Widget Steam 網址: {widget_urls}")
            
            if links:
                send_to_discord_clean_images(title, links, widget_urls, main_img)
            else:
                print("   ⚠️ 該測試網址未抓取到任何有效商店連結！")
        except Exception as e:
            print(f"   ❌ 測試執行發生異常: {e}")
        return

    # 以下維持原本的自動排程邏輯
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
                links, widget_urls, main_img = extract_all_store_links_and_pure_images(article_url)
                
                if links:
                    send_to_discord_clean_images(title, links, widget_urls, main_img)
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
