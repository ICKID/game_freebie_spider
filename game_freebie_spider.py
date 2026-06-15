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
    """【GOG 100%精準拿圖】直接進網頁拔標準分享圖，絕對不會抓錯遊戲"""
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

def extract_all_store_links_and_all_images(page_url, news_title=""):
    """提取網址，並把內文的所有宣傳圖通通撈出來準備做成相簿"""
    found_stores = set()
    article_images = []
    title_lower = news_title.lower()
    is_epic_news = "epic" in title_lower
    is_steam_news = "steam" in title_lower
    
    try:
        time.sleep(0.5)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return [], []
        inner_soup = BeautifulSoup(res.text, 'html.parser')

        # 🎯 收集這篇 FreeSteam 文章內所有可能的大圖 (過濾掉 logo 或是頭像等小圖)
        img_tags = inner_soup.find_all('img')
        for img in img_tags:
            src = img.get('src') or img.get('data-src') or img.get('content')
            if src and "http" in src and not any(x in src.lower() for x in ["avatar", "logo", "gravatar", "icon"]):
                if src not in article_images:
                    article_images.append(src)

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
    return list(found_stores), article_images

def send_to_discord_multi_images(title, store_links, article_images):
    """【相簿發送演算法】將多張圖片綁定至同一個訊息組，完美呈現複數遊戲"""
    if not store_links: return
    if not DISCORD_WEBHOOK_URL: return
    
    from discord_webhook import DiscordWebhook, DiscordEmbed
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    links_str = "".join(store_links).lower()
    card_color = "00c0ff" if "steam" in links_str else "1a1a1a" if "epic" in links_str else "f1c40f"
    
    # 🕵️‍♂️ 第一步：動態收集全平台的所有遊戲封面
    collected_covers = []
    
    for link in store_links:
        # Steam 封面
        if "store.steampowered.com/app/" in link:
            try:
                parts = link.split('/app/')
                if len(parts) > 1:
                    app_id = parts[1].split('/')[0]
                    collected_covers.append(f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg")
            except: pass
        # GOG 封面 (改用 100% 精準網頁撈取法)
        elif "gog.com" in link:
            gog_cover = get_gog_cover_via_web(link)
            if gog_cover: collected_covers.append(gog_cover)

    # 如果是 Epic，或者上述平台沒撈滿，就把 FreeSteam 文章內的宣傳大圖也塞進去
    for img in article_images:
        if img not in collected_covers:
            collected_covers.append(img)
            
    # 去除重複圖源並過濾空值
    collected_covers = [x for x in collected_covers if x]

    # 🕵️‍♂️ 第二步：建立傳送門文字清單
    links_text = ""
    for link in store_links:
        platform = "Steam" if "steam" in link else "Epic Games" if "epic" in link else "GOG"
        links_text += f"🎮 [{platform} 直達傳送門]({link})\n"

    # 🕵️‍♂️ 第三步：利用 Discord Embed Group 密技，將多圖打包發送
    # 主卡片 (帶有文字與第一張圖)
    main_embed = DiscordEmbed(title=title, color=card_color)
    main_embed.add_embed_field(name="🎁 領取網址", value=links_text, inline=False)
    if collected_covers:
        main_embed.set_image(url=collected_covers[0])
    main_embed.set_timestamp()
    webhook.add_embed(main_embed)
    
    # 附屬卡片 (只帶圖片，Discord 會自動把它們縮小並排在主卡片下方，形成相簿)
    # Discord 限制一個訊息組最多放 4 張圖，我們扣除主圖，最多再塞 3 張
    for extra_img in collected_covers[1:4]:
        sub_embed = DiscordEmbed(color=card_color)
        sub_embed.set_image(url=extra_img)
        webhook.add_embed(sub_embed)

    try:
        webhook.execute()
    except Exception as e:
        print(f"❌ Discord 發送失敗: {e}")

def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動（全平台封面旗艦版）...")
    
    history = load_history()
    print(f"📋 載入歷史紀錄，目前已記憶了 {len(history)} 個網址。")
    
    try:
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')
        
        if IS_TEST_MODE:
            print("⚠️ 【測試強制推播模式】開啟！將在歷史文章中各挖出 2 篇 Epic/Steam/GOG 進行多圖相簿測試。")
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
                    print(f"   [測試模式] 正在強力解析: {tag.text.strip()[:20]}...")
                    links, all_imgs = extract_all_store_links_and_all_images(article_url, tag.text.strip())
                    
                    if links:
                        send_to_discord_multi_images(tag.text.strip(), links, all_imgs)
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
                    links, all_imgs = extract_all_store_links_and_all_images(article_url, title)
                    
                    if links:
                        send_to_discord_multi_images(title, links, all_imgs)
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
