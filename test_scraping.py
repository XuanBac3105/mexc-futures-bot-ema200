import aiohttp
import asyncio
from datetime import datetime, timedelta
import pytz
import re

async def test_scraping():
    async with aiohttp.ClientSession() as session:
        url = "https://www.mexc.co/vi-VN/newlisting"
        print(f"🔍 Scraping: {url}\n")
        
        try:
            async with session.get(url, timeout=15) as r:
                print(f"✅ Status: {r.status}\n")
                
                if r.status != 200:
                    print(f"❌ HTTP Error: {r.status}")
                    return
                
                html = await r.text()
                print(f"📄 HTML Length: {len(html)} characters\n")
                
                # Lưu HTML ra file để xem
                with open("mexc_newlisting.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("� Saved HTML to mexc_newlisting.html\n")
                
                # Tìm các từ khóa liên quan
                keywords = ["niêm yết", "listing", "KAIROS", "MINDHIVE", "vcoinName", "onlineTime"]
                for kw in keywords:
                    count = html.count(kw)
                    print(f"  '{kw}': {count} occurrences")
                
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

asyncio.run(test_scraping())
