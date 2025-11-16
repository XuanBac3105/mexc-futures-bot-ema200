import asyncio
import aiohttp
from datetime import datetime
import pytz

async def test_parse_calendar():
    timestamp = int(datetime.now().timestamp() * 1000)
    url = f"https://www.mexc.co/api/operation/new_coin_calendar?timestamp={timestamp}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=15) as r:
            data = await r.json()
            
            coins = data.get('data', {}).get('newCoins', [])
            print(f"✅ Found {len(coins)} coins\n")
            
            vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
            now = datetime.now(vn_tz)
            
            print("="*80)
            print("UPCOMING LISTINGS:")
            print("="*80)
            
            for coin in coins[:10]:
                symbol = coin.get('vcoinName')
                full_name = coin.get('vcoinNameFull')
                timestamp_ms = coin.get('firstOpenTime')
                
                # Convert timestamp to datetime
                if timestamp_ms:
                    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=vn_tz)
                    weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
                    weekday = weekdays[dt.weekday()]
                    date_str = dt.strftime("%d/%m/%Y %H:%M")
                    
                    # Check if upcoming
                    if dt > now:
                        print(f"🚀 {symbol} ({full_name})")
                        print(f"   ⏰ {weekday}, {date_str}")
                        print(f"   📅 {dt}")
                        print()

asyncio.run(test_parse_calendar())
