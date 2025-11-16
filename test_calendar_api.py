import asyncio
import aiohttp
import json
from datetime import datetime

async def test_calendar_api():
    # Timestamp hiện tại (milliseconds)
    timestamp = int(datetime.now().timestamp() * 1000)
    url = f"https://www.mexc.co/api/operation/new_coin_calendar?timestamp={timestamp}"
    
    print(f"🔍 Testing: {url}\n")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=15) as r:
                print(f"Status: {r.status}")
                
                if r.status == 200:
                    data = await r.json()
                    print(f"✅ Got JSON data!\n")
                    
                    # Pretty print
                    print("="*80)
                    print("RESPONSE DATA:")
                    print("="*80)
                    print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
                    print("="*80)
                    
                    # Analyze structure
                    if isinstance(data, dict):
                        print(f"\n📊 Top-level keys: {list(data.keys())}")
                        
                        # Tìm list coins
                        for key, value in data.items():
                            if isinstance(value, list) and value:
                                print(f"\n🎯 Found array '{key}' with {len(value)} items")
                                print(f"First item: {json.dumps(value[0], indent=2, ensure_ascii=False)[:500]}")
                else:
                    text = await r.text()
                    print(f"Response: {text[:500]}")
                    
        except Exception as e:
            print(f"❌ Error: {e}")

asyncio.run(test_calendar_api())
