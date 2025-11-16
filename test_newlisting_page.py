import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re

async def test_newlisting():
    url = "https://www.mexc.co/vi-VN/newlisting"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=15) as r:
            print(f"Status: {r.status}")
            html = await r.text()
            print(f"HTML length: {len(html)} chars\n")
            
            # Save HTML
            with open("mexc_newlisting_test.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("💾 Saved to mexc_newlisting_test.html\n")
            
            # Try BeautifulSoup
            soup = BeautifulSoup(html, 'lxml')
            
            # Tìm các pattern phổ biến
            print("=" * 60)
            print("🔍 SEARCHING FOR LISTING DATA...")
            print("=" * 60)
            
            # Pattern 1: Tìm text có "list", "listing", hoặc symbol pattern
            text = soup.get_text()
            
            # Tìm các coin symbols (chữ hoa 2-10 ký tự)
            symbols = re.findall(r'\b[A-Z]{2,10}\b', text[:5000])  # Check 5000 chars đầu
            print(f"\n📊 Found {len(set(symbols))} unique uppercase words (potential symbols):")
            print(set(symbols))
            
            # Tìm dates/times
            dates = re.findall(r'\d{1,2}[/-]\d{1,2}[/-]\d{4}', text[:5000])
            times = re.findall(r'\d{1,2}:\d{2}', text[:5000])
            print(f"\n📅 Found {len(dates)} dates: {dates[:5]}")
            print(f"⏰ Found {len(times)} times: {times[:5]}")
            
            # Check if JavaScript loaded content
            if "react" in html.lower() or "vue" in html.lower() or "__NEXT" in html:
                print("\n⚠️ WARNING: Page uses JavaScript framework!")
                print("This page likely loads data dynamically via JS")
            
            # Tìm JSON data trong HTML
            json_pattern = r'<script[^>]*>.*?({.*?})</script>'
            json_matches = re.findall(json_pattern, html[:10000], re.DOTALL)
            print(f"\n🔍 Found {len(json_matches)} potential JSON blocks in HTML")

asyncio.run(test_newlisting())
