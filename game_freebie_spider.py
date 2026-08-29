import time
import re
import os
import sys

import cloudscraper
from bs4 import BeautifulSoup
from discord_webhook import DiscordWebhook, DiscordEmbed

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
IS_TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true" or "--test" in sys.argv
TEST_URL = os.environ.get("TEST_URL", "").strip()

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"
HISTORY_FILE = "posted_links.txt"

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://freesteam.games/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24", "Google Chrome";v="125"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

# 🛡️ 用 cloudscraper 取代 requests：能自動處理 Cloudflare 類型的防機器人挑戰頁面
SCRAPER = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)

BAD_HREF_KEYWORDS = ["galaxy", "login", "support", "privacy", "download", "/u/", "account", "cart", "order", "checkout"]
GENERIC_TEXT_KEYWORDS = ["點擊", "這裡", "商店頁面"]


# ------------------------------------------------------------------
# 歷史紀錄
# ------------------------------------------------------------------

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_history(history_set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for link in sorted(history_set):
            f.write(f"{link}\n")


# ------------------------------------------------------------------
# 共用的請求函式：帶重試機制 + 偵錯輸出
# ------------------------------------------------------------------

def fetch_url(url, timeout=15, label=""):
    """
    統一的網頁請求函式。
    - 使用 cloudscraper 繞過基本的防機器人偵測
    - 失敗時自動重試（最多 MAX_RETRIES 次）
    - 印出狀態碼，方便未來排查「被擋下但沒有報錯」的狀況
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            res = SCRAPER.get(url, headers=HEADERS, timeout=timeout)
            print(f"   🌐 [{label}] 請求 {url} → 狀態碼 {res.status_code}（第 {attempt} 次嘗試）")
            if res.status_code == 200:
                return res
            last_error = f"狀態碼異常: {res.status_code}"
        except Exception as e:
            last_error = str(e)
            print(f"   ⚠️ [{label}] 第 {attempt} 次請求失敗: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SECONDS)

    print(f"   ❌ [{label}] 重試 {MAX_RETRIES} 次後仍失敗，最後錯誤: {last_error}")
    return None


# ------------------------------------------------------------------
# Steam 官方 API：一次呼叫同時拿「遊戲名稱」+「封面圖」，並用 cache 避免重複請求
# ------------------------------------------------------------------

def fetch_steam_app_details(app_id, cache):
    """
    透過 Steam 官方 appdetails API 取得遊戲名稱與封面圖。
    同一個 app_id 在同一篇文章處理過程中只會呼叫一次 API（用 cache 記住結果）。
    """
    if app_id in cache:
        return cache[app_id]

    result = None
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=tchinese"
        res = SCRAPER.get(url, headers=HEADERS, timeout=8)
        if res.status_code == 200:
            data = res.json()
            app_data = data.get(str(app_id), {})
            if app_data.get("success"):
                d = app_data.get("data", {})
                name = (d.get("name") or "").strip()
                result = {
                    "name": name or None,
                    "header_image": d.get("header_image"),
                }
    except Exception as e:
        print(f"   ⚠️ 從 Steam API 抓取 App ID {app_id} 資料失敗: {e}")

    cache[app_id] = result
    return result


def check_image_exists(img_url):
    try:
        response = SCRAPER.head(img_url, headers=HEADERS, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"   ⚠️ 檢查圖片是否存在失敗 ({img_url}): {e}")
        return False


def get_valid_steam_image(app_id, cache):
    """
    優先使用 Steam 官方 API 回傳的 header_image（最準確、不會被擋）。
    抓不到才退回 Akamai 的固定網址規則當備援。
    """
    details = fetch_steam_app_details(app_id, cache)
    if details and details.get("header_image"):
        return details["header_image"]

    fallback_urls = [
        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg",
        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/library_600x900.jpg",
    ]
    for img_url in fallback_urls:
        if check_image_exists(img_url):
            return img_url

    return None


def resolve_app_id_name(app_id, cache):
    """純數字 App ID 的名稱解析：呼叫 Steam API，抓不到則用預設文字。"""
    print(f"   🔍 正在向 Steam API 查詢 App ID [{app_id}] 的真實遊戲名稱...")
    details = fetch_steam_app_details(app_id, cache)
    if details and details.get("name"):
        return details["name"]
    return f"Steam 限免遊戲 ({app_id})"


# ------------------------------------------------------------------
# 從文章頁面解析商店連結
# ------------------------------------------------------------------

def determine_game_name(raw_text, href, platform, cache):
    """依序嘗試：連結文字本身 → 連結文字是純數字 ID → 網址 slug → 網址 slug 是純數字 ID → 預設文字"""
    clean_name = " ".join(raw_text.split())

    is_placeholder = (
        not clean_name
        or len(clean_name) <= 1
        or clean_name.isdigit()
        or "http" in clean_name
        or any(kw in clean_name for kw in GENERIC_TEXT_KEYWORDS)
    )
    if not is_placeholder:
        return clean_name

    # 連結文字本身就是純數字 App ID
    if clean_name.isdigit() and platform == "Steam":
        return resolve_app_id_name(clean_name, cache)

    # 退而求其次：用網址最後一段當名稱
    try:
        slug = href.rstrip('/').split('/')[-1]
    except Exception as e:
        print(f"   ⚠️ 無法從網址取得 slug ({href}): {e}")
        return f"{platform} 遊戲"

    # 網址 slug 也是純數字（網址只到 /app/1234567，沒有名稱後綴）
    if slug.isdigit() and platform == "Steam":
        return resolve_app_id_name(slug, cache)

    return slug.replace('-', ' ').replace('_', ' ').title()


def extract_all_store_links_and_pure_images(page_url):
    found_stores = []
    widget_steam_urls = []
    all_game_urls_in_article = set()
    freesteam_main_image = None
    steam_app_cache = {}

    time.sleep(0.5)
    res = fetch_url(page_url, timeout=10, label="文章頁面")
    if res is None:
        return [], [], None, steam_app_cache

    try:
        inner_soup = BeautifulSoup(res.text, 'html.parser')

        og_img = inner_soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get('content'):
            freesteam_main_image = og_img['content'].split('?')[0].strip()

        content_area = inner_soup.select_one('.entry-content') or inner_soup

        # 從 iframe（Steam 官方小工具）抓 App ID
        for iframe in content_area.find_all('iframe', src=True):
            src = iframe['src']
            if "store.steampowered.com/widget/" in src:
                try:
                    app_id = src.split('/widget/')[1].split('/')[0]
                    widget_url = f"https://store.steampowered.com/app/{app_id}"
                    if widget_url not in widget_steam_urls:
                        widget_steam_urls.append(widget_url)
                except Exception as e:
                    print(f"   ⚠️ 解析 iframe App ID 失敗: {e}")

        # 從文字中抓「#123456」這種格式的 App ID，但要求附近文字提及 Steam，避免誤判成其他編號
        page_text = content_area.get_text()
        for match in re.finditer(r'#\s*(\d{5,7})', page_text):
            context = page_text[max(0, match.start() - 30): match.end() + 30]
            if "steam" in context.lower():
                app_id = match.group(1)
                widget_url = f"https://store.steampowered.com/app/{app_id}"
                if widget_url not in widget_steam_urls:
                    widget_steam_urls.append(widget_url)

        for tag in content_area.find_all('a', href=True):
            href = tag['href'].split('?')[0].rstrip('/')
            raw_text = tag.get_text().strip()
            lower_href = href.lower()

            if any(bad in lower_href for bad in BAD_HREF_KEYWORDS):
                continue

            platform = None
            if "store.steampowered.com/app/" in href:
                if "agecheck" not in href:
                    platform = "Steam"
            elif "epicgames.com" in href:
                if href in ["https://store.epicgames.com", "https://www.epicgames.com", "https://store.epicgames.com/en-US"]:
                    continue
                platform = "Epic Games"
            elif "gog.com" in href:
                if href != "https://www.gog.com":
                    platform = "GOG"

            if not platform:
                continue

            all_game_urls_in_article.add(href)
            clean_name = determine_game_name(raw_text, href, platform, steam_app_cache)

            if not any(item['link'] == href for item in found_stores):
                found_stores.append({
                    "link": href,
                    "name": clean_name,
                    "platform": platform,
                })

    except Exception as e:
        print(f"   ⚠️ 解析文章頁面失敗 ({page_url}): {e}")

    if not widget_steam_urls:
        widget_steam_urls = [x for x in all_game_urls_in_article if "store.steampowered.com" in x]

    print(f"   📦 本篇文章抓到 {len(found_stores)} 個商店連結。")
    return found_stores, widget_steam_urls, freesteam_main_image, steam_app_cache


# ------------------------------------------------------------------
# 發送到 Discord
# ------------------------------------------------------------------

def send_to_discord_clean_images(title, store_items, widget_steam_urls, freesteam_main_image, steam_app_cache):
    if not store_items or not DISCORD_WEBHOOK_URL:
        return

    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)

    links_str = "".join(item["link"] for item in store_items).lower()
    card_color = "00c0ff" if "steam" in links_str else "1a1a1a" if "epic" in links_str else "f1c40f"

    collected_covers = []
    for widget_url in widget_steam_urls:
        try:
            app_id = widget_url.split('/app/')[1].split('/')[0]
            valid_img = get_valid_steam_image(app_id, steam_app_cache)
            if valid_img and valid_img not in collected_covers:
                collected_covers.append(valid_img)
        except Exception as e:
            print(f"   ⚠️ 取得封面圖失敗 ({widget_url}): {e}")

    if not collected_covers and freesteam_main_image and check_image_exists(freesteam_main_image):
        collected_covers.append(freesteam_main_image)

    processed_lines = []
    skip_next = False
    for i in range(len(store_items)):
        if skip_next:
            skip_next = False
            continue

        current = store_items[i]
        platform_label = f"[{current['platform']}] "

        if i + 1 < len(store_items) and store_items[i + 1]["name"] == "遊戲本體":
            next_item = store_items[i + 1]
            processed_lines.append(
                f"{platform_label}[{current['name']}]({current['link']}) ([遊戲本體]({next_item['link']}))"
            )
            skip_next = True
        else:
            processed_lines.append(f"{platform_label}[{current['name']}]({current['link']})")

    links_text = "\n".join(processed_lines) + "\n"

    main_embed = DiscordEmbed(title=title, color=card_color)
    main_embed.add_embed_field(name="🎁 領取網址", value=links_text, inline=False)
    if collected_covers:
        main_embed.set_image(url=collected_covers[0])
    main_embed.set_timestamp()
    webhook.add_embed(main_embed)

    for extra_img in collected_covers[1:4]:
        sub_embed = DiscordEmbed(color=card_color)
        sub_embed.set_image(url=extra_img)
        webhook.add_embed(sub_embed)

    try:
        webhook.execute()
        print("   🎉 Discord 發送成功！")
    except Exception as e:
        print(f"❌ Discord 發送失敗: {e}")


# ------------------------------------------------------------------
# 共用流程：處理單篇文章（測試模式 / 排程模式都會用到）
# ------------------------------------------------------------------

def process_article(article_url, title):
    """解析一篇文章並發送到 Discord。回傳 True 代表有抓到有效商店連結。"""
    print(f"   解析文章: {title[:30]}...")
    store_items, widget_urls, main_img, steam_app_cache = extract_all_store_links_and_pure_images(article_url)

    if not store_items:
        print("   ⚠️ 無有效商店連結。")
        return False

    send_to_discord_clean_images(title, store_items, widget_urls, main_img, steam_app_cache)
    return True


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

def run_test_mode():
    print(f"⚠️ 【強制指定測試網址】正在解析: {TEST_URL}")
    res = fetch_url(TEST_URL, timeout=10, label="測試網址")
    if res is None:
        print("   ❌ 無法連線到測試網址。")
        return

    try:
        soup = BeautifulSoup(res.text, 'html.parser')
        title_tag = soup.select_one('h1.entry-title, h1')
        title = title_tag.text.strip() if title_tag else "測試限免遊戲"
        process_article(TEST_URL, title)
    except Exception as e:
        print(f"   ❌ 測試執行發生異常: {e}")


def run_scheduled_mode():
    history = load_history()
    print(f"📋 載入歷史紀錄，目前已記憶了 {len(history)} 個網址。")

    count = 0
    response = fetch_url(URL_FREESTEAM, timeout=15, label="限免列表頁")
    if response is None:
        print("❌ 無法取得限免列表頁，本次排程結束（history 不會被覆寫）。")
        return

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')
        print(f"   📰 列表頁共抓到 {len(articles)} 篇文章區塊。")

        if not articles:
            # 抓到 0 篇文章通常代表被防機器人機制擋下，印出前 300 字方便排查
            print("   ⚠️ 抓不到任何 <article> 標籤，可能被網站擋下。頁面內容片段：")
            print("   " + response.text[:300].replace("\n", " "))

        for article in reversed(articles[:5]):
            tag = article.select_one('.entry-title a, h2 a, h3 a')
            if not tag:
                continue

            article_url = tag['href'].strip()
            title = tag.text.strip()

            if article_url in history:
                print(f"   Skip: {title[:20]}...")
                continue

            print(f"   New Article: {title[:20]}...")
            if process_article(article_url, title):
                count += 1
            history.add(article_url)

        save_history(history)
        print(f"   [FreeSteam] 自動排程處理完畢，共推播了 {count} 則全新限免！")

    except Exception as e:
        print(f"❌ 發生異常: {e}")


def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動（cloudscraper + 偵錯強化版）...")

    if IS_TEST_MODE and TEST_URL:
        run_test_mode()
    else:
        run_scheduled_mode()

    print("\n🎉 全數流程執行完畢！")


if __name__ == "__main__":
    main()
