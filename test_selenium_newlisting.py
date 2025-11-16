"""
Test scraping /newlisting với Selenium (headless browser)
Cần cài: pip install selenium
"""

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import time
    
    print("🚀 Starting Selenium test...")
    
    # Setup Chrome headless
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        url = "https://www.mexc.co/vi-VN/newlisting"
        print(f"📡 Loading {url}...")
        driver.get(url)
        
        # Đợi JavaScript load (5 giây)
        print("⏳ Waiting for JavaScript to load...")
        time.sleep(5)
        
        # Lấy page source sau khi JS load xong
        html = driver.page_source
        print(f"✅ Got HTML: {len(html)} chars\n")
        
        # Save HTML
        with open("newlisting_selenium.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("💾 Saved to newlisting_selenium.html\n")
        
        # Tìm elements có text về coin/date/time
        page_text = driver.find_element(By.TAG_NAME, "body").text
        
        print("="*80)
        print("📄 PAGE TEXT (first 2000 chars):")
        print("="*80)
        print(page_text[:2000])
        print("="*80)
        
        # Tìm dates/times trong text
        import re
        dates = re.findall(r'\d{1,2}[/-]\d{1,2}[/-]\d{4}', page_text)
        times = re.findall(r'\d{1,2}:\d{2}', page_text)
        symbols = re.findall(r'\b[A-Z]{3,10}\b', page_text)
        
        print(f"\n📅 Found dates: {dates[:10]}")
        print(f"⏰ Found times: {times[:10]}")
        print(f"💰 Found symbols: {set(symbols)}")
        
    finally:
        driver.quit()
        print("\n✅ Browser closed")
        
except ImportError:
    print("❌ Selenium not installed!")
    print("Install with: pip install selenium")
    print("\nAlternative: Giữ nguyên giải pháp scrape announcements (đang hoạt động)")
except Exception as e:
    print(f"❌ Error: {e}")
    print("\nSelenium cần ChromeDriver. Download tại:")
    print("https://chromedriver.chromium.org/downloads")
