import aiohttp
import asyncio

async def test():
    async with aiohttp.ClientSession() as session:
        # Test API project list
        url = "https://www.mexc.co/api/platform/spot/coin/v1/project/list"
        print(f"🔍 Testing: {url}\n")
        
        try:
            async with session.get(url, timeout=10) as r:
                print(f"✅ Status: {r.status}")
                data = await r.json()
                print(f"\n📊 Full Response:")
                print(data)
        except Exception as e:
            print(f"❌ Error: {e}")

asyncio.run(test())
