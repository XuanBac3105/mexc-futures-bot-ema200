import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re
import json

async def test_detailed():
    url = "https://www.mexc.co/vi-VN/newlisting"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=15) as r:
            html = await r.text()
            
            # Parse với BeautifulSoup
            soup = BeautifulSoup(html, 'lxml')
            
            print("=" * 80)
            print("🔍 TÌM KIẾM DỮ LIỆU LISTING")
            print("=" * 80)
            
            # Tìm tất cả script tags có JSON
            scripts = soup.find_all('script', type='application/json')
            print(f"\n📦 Found {len(scripts)} JSON script tags")
            
            for i, script in enumerate(scripts[:3]):  # Check 3 cái đầu
                try:
                    data = json.loads(script.string)
                    print(f"\n--- Script {i+1} ---")
                    # Print structure
                    if isinstance(data, dict):
                        print(f"Keys: {list(data.keys())[:10]}")
                        # Tìm keys có liên quan đến listing
                        for key in data:
                            if any(word in str(key).lower() for word in ['list', 'coin', 'token', 'announcement']):
                                print(f"  🎯 {key}: {str(data[key])[:200]}")
                except:
                    pass
            
            # Tìm __NEXT_DATA__ (Next.js data)
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data:
                print("\n\n🎯 FOUND __NEXT_DATA__!")
                try:
                    data = json.loads(next_data.string)
                    print(f"Keys: {list(data.keys())}")
                    
                    # Deep search cho listing data
                    def search_dict(d, path=""):
                        results = []
                        if isinstance(d, dict):
                            for k, v in d.items():
                                new_path = f"{path}.{k}" if path else k
                                if any(word in k.lower() for word in ['list', 'coin', 'symbol', 'announcement', 'time', 'date']):
                                    results.append((new_path, v))
                                results.extend(search_dict(v, new_path))
                        elif isinstance(d, list) and d:
                            results.extend(search_dict(d[0], f"{path}[0]"))
                        return results
                    
                    matches = search_dict(data)
                    print(f"\n🔍 Found {len(matches)} relevant fields:")
                    for path, value in matches[:20]:
                        value_str = str(value)[:150]
                        print(f"  • {path}: {value_str}")
                        
                except Exception as e:
                    print(f"Error parsing: {e}")
            
            # Tìm text có pattern ngày tháng
            text = soup.get_text()
            
            # Pattern: DD/MM/YYYY hoặc YYYY-MM-DD
            date_pattern1 = r'\d{1,2}[/-]\d{1,2}[/-]\d{4}'
            date_pattern2 = r'\d{4}[/-]\d{1,2}[/-]\d{1,2}'
            time_pattern = r'\d{1,2}:\d{2}(?::\d{2})?'
            
            dates1 = re.findall(date_pattern1, text)
            dates2 = re.findall(date_pattern2, text)
            times = re.findall(time_pattern, text)
            
            print(f"\n📅 Dates found:")
            print(f"  DD/MM/YYYY format: {dates1[:10]}")
            print(f"  YYYY-MM-DD format: {dates2[:10]}")
            print(f"  Times: {times[:10]}")
            
            # Tìm coin symbols (2-10 uppercase letters)
            symbols = re.findall(r'\b([A-Z]{2,10})\b', text)
            symbol_counts = {}
            for s in symbols:
                if s not in ['MEXC', 'USDT', 'BTC', 'ETH', 'USD', 'VN']:  # Skip common words
                    symbol_counts[s] = symbol_counts.get(s, 0) + 1
            
            print(f"\n💰 Potential coin symbols (appearing > 1 time):")
            sorted_symbols = sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:20]
            for sym, count in sorted_symbols:
                print(f"  {sym}: {count} times")

asyncio.run(test_detailed())
