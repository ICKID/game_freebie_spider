import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL_FREESTEAM = "https://freesteam.games/category/limited-time-free"
URL_4GAMERS_API = "https://www.4gamers.com.tw/site/api/news/by-tag?tag=%E9%99%90%E6%99%82%E5%85%8D%E8%B2%BB&nextStart=0&pageSize=25"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/json",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/"
}

def extract_all_store_links(page_url):
    """【升級：複數偵測】深入內頁，撈出所有不重複的遊戲領取網址"""
    found_stores = set() # 使用集合自動過濾重複的網址
    try:
        time.sleep(0.3)
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return []
        
        inner_soup = BeautifulSoup(res.text, 'html.parser')
        
        # 🕵️‍♂️ 策略一：拆解 4Gamers 的多個 Steam 內嵌框框 (iframe)
        if "4gamers.com.tw" in page_url:
            iframes = inner_soup.find_all('iframe', src=True)
            for iframe in iframes:
                src = iframe['src']
                if "store.steampowered.com/widget/" in src:
                    real_app_url = src.replace('/widget/', '/app/').split('?')[0]
                    found_stores.add(real_app_url)

        # 🕵️‍♂️ 策略二：掃描內文所有的 <a> 標籤超連結
        links = inner_soup.find_all('a', href=True)
        for tag in links:
            href = tag['href'].split('?')[0].rstrip('/') # 移除網址後方的參數與雜訊
            
            # 偵測主流商店
            if "store.steampowered.com/app/" in href or "epicgames.com" in href or "gog.com" in href:
                # 過濾非直接領取頁面的雜訊（如：年齡限制、隱私條款或首頁）
                if "agecheck" not in href and "privacy" not in href and href != "https://store.epicgames.com":
                    found_stores.add(href)
    except:
        pass
    return list(found_stores)

def check_freesteam():
    print("\n🔎 [1/2] 正在檢查 FreeSteam.games 限時免費...")
    try:
        response = requests.get(URL_FREESTEAM, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')
        
        count = 1
        for article in articles:
            title_tag = article.select_one('.entry-title a, h2 a, h3 a, .wporg-tile-title a')
            if title_tag:
                title = title_tag.text.strip()
                news_link = title_tag['href']
                
                # 🛠 挖出內頁中「所有的」商店連結
                store_links = extract_all_store_links(news_link)
                
                print(f" 🎮 {count}. {title}")
                if store_links:
                    for s_link in store_links:
                        print(f"    🔗 領取網址: {s_link}")
                else:
                    print(f"    🔗 領取網址: {news_link} (未偵測到直達連結，請至新聞內查看)")
                
                count += 1
                if count > 5: break
    except Exception as e:
        print(f"❌ 抓取 FreeSteam 失敗: {e}")

def find_list_in_dict(d):
    if isinstance(d, list): return d
    if isinstance(d, dict):
        for key in ['list', 'data', 'results', 'news']:
            if key in d and isinstance(d[key], list) and len(d[key]) > 0: return d[key]
        for key, value in d.items():
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict): return value
            elif isinstance(value, dict):
                deep_result = find_list_in_dict(value)
                if deep_result: return deep_result
    return None

def check_4gamers_api():
    print("\n🔎 [2/2] 正在檢查 4Gamers 限時免費標籤...")
    try:
        response = requests.get(URL_4GAMERS_API, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        
        json_data = response.json()
        news_list = find_list_in_dict(json_data)
        
        if not news_list: return

        count = 1
        for news in news_list:
            if not isinstance(news, dict): continue
            
            title = news.get('title') or news.get('name') or ''
            title = title.strip()
            news_id = news.get('id') or news.get('newsId')
            link_path = news.get('canonicalUrl') or news.get('url')
            
            if not link_path and news_id:
                news_link = f"https://www.4gamers.com.tw/news/detail/{news_id}"
            elif link_path:
                news_link = link_path if link_path.startswith('http') else f"https://www.4gamers.com.tw/{link_path.lstrip('/')}"
            else:
                news_link = "https://www.4gamers.com.tw/news/tag/%E9%99%90%E6%99%82%E5%85%8D%E8%B2%BB"
                
            if title:
                # 🛠 挖出內頁中「所有的」商店連結
                store_links = extract_all_store_links(news_link)
                
                print(f" 📰 {count}. {title}")
                if store_links:
                    for s_link in store_links:
                        print(f"    🔗 領取網址: {s_link}")
                else:
                    print(f"    🔗 領取網址: {news_link} (未偵測到直達連結，請至新聞內查看)")
                
                count += 1
                if count > 5: break
    except Exception as e:
        print(f"❌ 抓取 4Gamers 失敗: {e}")

def main():
    print(f"==========================================")
    print(f" ⏰ 執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"==========================================")
    
    check_freesteam()
    check_4gamers_api()
    
    print(f"\n==========================================")
    print("今日限免精簡列表檢查完畢！")

if __name__ == "__main__":
    main()
