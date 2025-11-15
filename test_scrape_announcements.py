import aiohttp
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import re

async def test_scrape_announcements():
    async with aiohttp.ClientSession() as session:
        url = "https://www.mexc.co/vi-VN/announcements/new-listings"
        print(f"🔍 Scraping: {url}\n")
        
        try:
            async with session.get(url, timeout=15) as r:
                print(f"✅ Status: {r.status}\n")
                
                if r.status != 200:
                    print(f"❌ HTTP Error: {r.status}")
                    return
                
                html = await r.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                print(f"📄 HTML Length: {len(html)} characters\n")
                
                # Tìm tất cả announcement items
                # Thử nhiều selector
                selectors = [
                    'a[href*="/announcements/"]',  # Links to announcements
                    'div.announcement-item',
                    'article',
                    'li',
                ]
                
                results = []
                
                # Tìm pattern CHỈ FUTURES - cải thiện
                # Pattern 1: "Đầu tiên trên thị trường: MEXC niêm yết X (SYMBOL) USDT-M Futures vào HH:MM DD/MM/YYYY"
                # Pattern 2: "niêm yết X (SYMBOL) ... Futures ... HH:MM DD/MM/YYYY"
                
                pattern1 = r'niêm yết\s+([\w\s]+?)\s*\(([A-Z0-9]+)\)\s+(?:USDT-M\s+)?[Ff]utures.*?(\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4})'
                
                # Tìm trong toàn bộ text
                text_content = soup.get_text()
                matches = re.findall(pattern1, text_content, re.DOTALL)
                
                # Làm sạch matches - loại bỏ text dài bất thường
                clean_matches = []
                for full_name, symbol, time_str in matches:
                    # Chỉ giữ tên coin ngắn gọn (< 50 ký tự)
                    full_name = full_name.strip()
                    if len(full_name) < 50 and not '\n' in full_name:
                        clean_matches.append((full_name, symbol, time_str))
                
                matches = clean_matches
                
                print(f"🎯 Found {len(matches)} FUTURES announcements:\n")
                
                for idx, (full_name, symbol, time_str) in enumerate(matches[:10], 1):
                    print(f"{idx}. 🚀 Futures Coin: {symbol.strip()}")
                    print(f"   Full name: {full_name.strip()}")
                    print(f"   Time: {time_str}")
                    
                    # Parse thời gian: "21:10 14/11/2025"
                    try:
                        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
                        dt = datetime.strptime(time_str, "%H:%M %d/%m/%Y")
                        dt = vn_tz.localize(dt)
                        print(f"   Parsed: {dt}")
                    except Exception as e:
                        print(f"   Parse error: {e}")
                    
                    print()
                
                # Không cần pattern 2 nữa vì chỉ lấy Futures
                
                # Lưu HTML để debug
                with open("mexc_announcements.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("\n💾 Saved HTML to mexc_announcements.html")
                
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

asyncio.run(test_scrape_announcements())
