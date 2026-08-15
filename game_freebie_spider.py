import os
import requests
from bs4 import BeautifulSoup
from discord_webhook import DiscordWebhook, DiscordEmbed
import sys

# --- 設定區 ---
URL_FREESTEAM = "https://freesteam.games/"
HISTORY_FILE = "posted_links.txt"

# 抓取 GitHub Actions 傳進來的環境變數
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
# 判斷是否為測試模式 (透過環境變數或啟動參數)
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true" or "--test" in sys.argv

# 偽裝成一般瀏覽器，避免被網站阻擋
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

def load_history():
    """讀取已經發送過的歷史網址"""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_history(history):
    """儲存已發送的網址到歷史紀錄"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for url in history:
            f.write(f"{url}\n")

def extract_all_store_links_and_pure_images(article_url):
    """解析單篇文章，抓取遊戲連結與圖片"""
    try:
        res = requests.get(article_url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return [], [], ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 抓取主要圖片
        main_img = ""
        img_tag = soup.select_one('.entry-content img')
        if img_tag and img_tag.get('src'):
            main_img = img_tag['src']
            
        # 抓取商店連結 (排除網站本身的廣告連結)
        links = []
        for a in soup.select('.entry-content a'):
            href = a.get('href', '')
            if href and 'freesteam.games' not in href and href.startswith('http'):
                links.append(href)
                
        # 去除重複
        links = list(dict.fromkeys(links))
        return links, [], main_img
        
    except Exception as e:
        print(f"   ⚠️ 解析文章失敗: {e}")
        return [], [], ""

def send_to_discord(title, links, main_img):
    """發送訊息到 Discord，並回傳是否發送成功"""
    if not DISCORD_WEBHOOK_URL:
        print("   ❌ 發送失敗：沒有設定 Webhook URL！")
        return False
        
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    # 組合連結文字
    desc = ""
    for i, link in enumerate(links):
        desc += f"🔗 [點此領取遊戲 {i+1}]({link})\n"
        
    embed = DiscordEmbed(title=title, description=desc, color="03b2f8")
    if main_img:
        embed.set_image(url=main_img)
        
    webhook.add_embed(embed)
    
    # 執行發送並檢查狀態
    response = webhook.execute()
    if response.status_code in [200, 204]:
        print("   🎉 Discord 發送成功！")
        return True
    else:
        print(f"   ❌ Discord 拒絕發送，狀態碼: {response.status_code}")
        print(f"   ❌ 錯誤詳情: {response.text}")
        return False

def test_webhook_mode():
    """專門用來測試 Webhook 是否正常的模式"""
    print("⚠️ 【標準測試模式】開啟！")
    
    if not DISCORD_WEBHOOK_URL:
        print("❌ 慘了！Python 完全沒有讀到 DISCORD_WEBHOOK_URL 環境變數！")
        print("💡 請去檢查 GitHub 的 YAML 檔案有沒有加 env:，以及 Secrets 名稱是否正確。")
        return

    print(f"✅ 成功讀取到 Webhook 網址 (前綴): {DISCORD_WEBHOOK_URL[:35]}...")
    
    webhook = DiscordWebhook(
        url=DISCORD_WEBHOOK_URL, 
        content="🚀 這是一條來自 GitHub Actions 的測試訊息！如果你看到這個，代表你的 Webhook 與 Python 程式完全正常連線！"
    )
    
    response = webhook.execute()
    if response.status_code in [200, 204]:
        print("🎉 Discord 回傳成功 (HTTP 200/204)！測試發送完畢，請去 Discord 確認有無收到訊息！")
    else:
        print(f"❌ Discord 拒絕發送！錯誤碼: {response.status_code}")
        print(f"❌ 錯誤詳情: {response.text}")
        print("💡 可能是 Webhook 網址已經失效、被刪除，或複製不完整。")

def main():
    print("🚀 GitHub Actions 智慧即時限免爬蟲啟動...")
    
    # 如果觸發了測試模式，就只跑測試並結束
    if TEST_MODE:
        test_webhook_mode()
        return

    if not DISCORD_WEBHOOK_URL:
        print("⚠️ [警告] 未偵測到 DISCORD_WEBHOOK_URL，發送功能將無法運作！")

    history = load_history()
    print(f"📜 目前已記錄的歷史文章數量: {len(history)}")
    
    try:
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        print(f"📡 請求首頁 HTTP 狀態碼: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ 無法存取首頁，可能被防火牆封鎖 (HTTP {response.status_code})")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')
        print(f"📦 成功抓取到的首頁文章數量: {len(articles)}")
        
        if not articles:
            print("⚠️ 未找到任何文章標籤，網站可能改版了。")
            print("🔍 讓我們來看看網站到底回傳了什麼畫面 (前1000字元)：")
            print(response.text[:1000])
            return

        count = 0
        # 只取最新 5 篇反向檢查
        for article in reversed(articles[:5]): 
            tag = article.select_one('.entry-title a, h2 a, h3 a')
            if tag:
                article_url = tag['href'].strip()
                title = tag.text.strip()
                
                if article_url in history:
                    print(f"   [Skip 已推播過] {title[:25]}...")
                    continue
                
                print(f"\n   [發現新文章] {title[:25]}...")
                links, _, main_img = extract_all_store_links_and_pure_images(article_url)
                
                if links:
                    is_success = send_to_discord(title, links, main_img)
                    if is_success:
                        history.add(article_url)
                        count += 1
                else:
                    print("   ⚠️ 內文無有效遊戲連結，為避免誤判，暫不寫入歷史紀錄。")
                    
        save_history(history)
        print(f"\n🎉 [FreeSteam] 自動排程處理完畢，共推播了 {count} 則全新限免！")
        
    except Exception as e:
        print(f"❌ 發生異常: {e}")

if __name__ == "__main__":
    main()
