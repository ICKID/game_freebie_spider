import time
import requests
from bs4 import BeautifulSoup
import os
import sys

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
IS_TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true" or "--test" in sys.argv
TEST_URL = os.environ.get("TEST_URL", "").strip()

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

def extract_all_store_links_and_pure_images(page_url):
    """精準提取每一個商店連結與其對應的原始按鈕文字"""
    found_stores = []  
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

        # 抓取所有超連結，保留文章中的先後順序與個別文字
        links = content_area.find_all('a', href=True)
        seen_links = set()
        
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/')
            raw_text = tag.get_text().strip()
            
            platform = None
            if "store.steampowered.com/app/" in href:
                if "agecheck" not in href:
                    platform = "Steam"
            elif "epicgames.com" in href:
                if any(bad in href for bad in ["id/login", "download", "privacy", "/login", "/u/"]):
                    continue
                if href in ["https://store.epicgames.com", "https://www.epicgames.com", "https://store.epicgames.com/en-US"]:
                    continue
                platform = "Epic Games"
            elif "gog.com" in href:
                if "##openlogin" in href:
                    href = href.split("##")[0].rstrip('/')
                if "account/login" not in href and href != "https://www.gog.com":
                    platform = "GOG"

            # 允許相同網址或多個連結獨立存在（不使用 seen_links 過濾掉文章中不同的按鈕，確保有幾個連結就抓幾個）
            if platform:
                all_game_urls_in_article.add(href)
                
                clean_name = " ".join(raw_text.split())
                
                # 如果文字太短或無意義，才用網址補足
                if not clean_name or len(clean_name) <= 1 or "http" in clean_name or "點擊" in clean_name or "這裡" in clean_name:
                    try:
                        slug = href.rstrip('/').split('/')[-1]
                        clean_name = slug.replace('-', ' ').replace('_', ' ').title()
                    except:
                        clean_name = f"{platform} 遊戲"
                
                found_stores.append({
                    "link": href,
                    "name": clean_name,
                    "platform": platform
                })

    except: pass
    
    if not widget_steam_urls:
        widget_steam_urls = [x for x in all_game_urls_in_article if "store.steampowered.com" in x]
        
    return found_stores, widget_steam_urls, freesteam_main_image

def send_to_discord_clean_images(title, store_items, widget_steam_urls, freesteam_main_image):
    """維持文章中原本的連結數量與各別行數"""
    if not store_items: return
    if not DISCORD_WEBHOOK_URL: return
    
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    links_str = "".join([item["link"] for item in store_items]).lower()
    card_color = "00c0ff" if "steam" in links_str else "1a1a1a" if "epic" in links_str else "f1c40f"
    
    collected_covers = []
    
    if len(store_items) == 1:
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

    # 🎯 忠於原文：有幾個超連結就逐一印出幾行，各自保有自己的文字與網址
    links_text = ""
    for item in store_items:
        game_name = item["name"]
        link = item["link"]
        links_text += f"[{game_name}]({link})\n"

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
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動（原始連結忠實呈現版）...")
    
    if IS_TEST_MODE and TEST_URL:
        print(f"⚠️ 【強制指定測試網址】正在解析: {TEST_URL}")
        try:
            res = requests.get(TEST_URL, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            title_tag = soup.select_one('h1.entry-title, h1')
            title = title_tag.text.strip() if title_tag else "測試限免遊戲"
            
            store_items, widget_urls, main_img = extract_all_store_links_and_pure_images(TEST_URL)
            print(f"   抓到的商店項目: {store_items}")
            
            if store_items:
                send_to_discord_clean_images(title, store_items, widget_urls, main_img)
            else:
                print("   ⚠️ 該測試網址未抓取到任何有效商店連結！")
        except Exception as e:
            print(f"   ❌ 測試執行發生異常: {e}")
        return

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
                store_items, widget_urls, main_img = extract_all_store_links_and_pure_images(article_url)
                
                if store_items:
                    send_to_discord_clean_images(title, store_items, widget_urls, main_img)
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
