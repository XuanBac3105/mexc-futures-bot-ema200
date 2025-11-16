"""
Trang /newlisting dùng Next.js và load data qua API.
Các API endpoint có thể:

1. https://www.mexc.com/api/platform/spot/market/newlisting
2. https://www.mexc.com/api/platform/announcement/list
3. https://api.mexc.com/api/v3/...

Cần dùng browser DevTools (F12) -> Network tab -> reload trang
-> xem API nào được gọi để lấy listing data
"""

import asyncio
import aiohttp

async def test_api_endpoints():
    """Test các API endpoint có thể"""
    
    endpoints = [
        "https://www.mexc.co/api/platform/spot/market/newlisting",
        "https://www.mexc.co/api/platform/announcement/newlisting",
        "https://www.mexc.co/api/v3/newlisting",
        "https://www.mexc.co/open/api/v2/market/newlisting",
        "https://www.mexc.co/api/platform/spot/newlisting",
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        for url in endpoints:
            try:
                print(f"\n🔍 Testing: {url}")
                async with session.get(url, timeout=10) as r:
                    print(f"   Status: {r.status}")
                    if r.status == 200:
                        try:
                            data = await r.json()
                            print(f"   ✅ Got JSON! Keys: {list(data.keys()) if isinstance(data, dict) else 'array'}")
                            print(f"   Data preview: {str(data)[:300]}")
                        except:
                            text = await r.text()
                            print(f"   Text length: {len(text)}")
            except Exception as e:
                print(f"   ❌ Error: {e}")

asyncio.run(test_api_endpoints())

print("\n" + "="*80)
print("💡 HƯỚNG DẪN TÌM API:")
print("="*80)
print("1. Mở https://www.mexc.co/vi-VN/newlisting trong browser")
print("2. Mở DevTools (F12) -> tab Network")
print("3. Reload trang (Ctrl+R)")
print("4. Tìm request có chứa 'api', 'listing', 'newlisting'")
print("5. Copy URL của request đó")
print("="*80)
