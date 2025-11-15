import requests
import re
from datetime import datetime
import pytz

# Scrape 2 trang đầu
urls = [
    "https://www.mexc.co/vi-VN/announcements/new-listings",
    "https://www.mexc.co/vi-VN/announcements/new-listings/19"
]

# Pattern: "niêm yết X (SYMBOL) ... Futures ... HH:MM DD/MM/YYYY"
pattern = r'niêm yết\s+([\w\s]+?)\s*\(([A-Z0-9]+)\)\s+(?:USDT-M\s+)?[Ff]utures.*?(\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4})'

all_clean_matches = []

for page_num, url in enumerate(urls, 1):
    print(f"\n📄 Scraping page {page_num}: {url}")
    
    try:
        response = requests.get(url, timeout=15)
        print(f"Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Failed to fetch page {page_num}")
            continue
        
        html = response.text
        print(f"HTML length: {len(html)} characters")
        
        # Tìm matches
        matches = re.findall(pattern, html, re.DOTALL)
        print(f"Found {len(matches)} raw matches on page {page_num}")
        
        # Làm sạch
        for full_name, symbol, time_str in matches:
            full_name = full_name.strip()
            if len(full_name) < 50 and '\n' not in full_name:
                # Tránh duplicate
                if (full_name, symbol, time_str) not in all_clean_matches:
                    all_clean_matches.append((full_name, symbol, time_str))
                    print(f"  ✅ Added: {symbol} ({full_name}) at {time_str}")
    
    except Exception as e:
        print(f"❌ Error scraping page {page_num}: {e}")

print(f"\n🎯 Total unique FUTURES announcements: {len(all_clean_matches)}")

vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')

for i, (full_name, symbol, time_str) in enumerate(all_clean_matches, 1):
    try:
        dt = datetime.strptime(time_str, "%H:%M %d/%m/%Y")
        dt = vn_tz.localize(dt)
        
        print(f"\n{i}. 🚀 Futures Coin: {symbol}")
        print(f"   Full name: {full_name}")
        print(f"   Time: {time_str}")
        print(f"   Parsed: {dt}")
    except:
        print(f"\n{i}. ❌ Failed to parse: {symbol} - {time_str}")
