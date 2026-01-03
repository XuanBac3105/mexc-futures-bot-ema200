# MEXC Futures Bot - EMA 200 Edition

Bot Telegram tự động theo dõi và cảnh báo biến động giá trên MEXC Futures với tính năng phát hiện EMA 200.

## ✨ Tính năng chính

### 🚀 Pump/Dump Detection
- Theo dõi **realtime** giá tất cả coins USDT Futures
- Cảnh báo **ngay lập tức** khi biến động ≥3%
- 3 modes: Tất cả (3-10%+), Trung bình (3-5%), Cực mạnh (≥10%)
- Dynamic base price - không bỏ lỡ pump/dump

### 📊 EMA 200 Detection (NEW!)
- Phát hiện coins gần chạm EMA 200 trên **6 khung thời gian**: M1, M5, M15, M30, H1, H4
- Lệnh `/ema200` để xem manual
- **Auto scan mỗi 5 phút** và gửi alert tự động
- Proximity threshold: ±1.5% từ EMA 200

### 🔔 Alert Toggle Controls (NEW!)
- Bật/tắt riêng từng loại thông báo
- `/pumpdump_on` / `/pumpdump_off` - Điều khiển thông báo pump/dump
- `/ema_on` / `/ema_off` - Điều khiển thông báo EMA 200
- Tránh spam khi chỉ muốn nhận 1 loại alert

### 🎯 Các tính năng khác
- Mute/unmute coin cụ thể
- Lịch coin sắp list trong tuần
- Coin vừa list gần đây
- Auto-restart khi có coin mới

## 📋 Yêu cầu

- Python 3.8+
- Telegram Bot Token
- Channel/Group ID để gửi alert

## 🚀 Cài đặt

1. Clone repository:
```bash
git clone https://github.com/XuanBac3105/mexc-futures-bot-ema200.git
cd mexc-futures-bot-ema200
```

2. Cài đặt dependencies:
```bash
pip install -r requirements.txt
```

3. Tạo file `.env` từ template:
```bash
cp .env.example .env
```

4. Cấu hình file `.env`:
```env
BOT_TOKEN=your_telegram_bot_token
CHANNEL_ID=your_channel_id
ADMIN_IDS=your_user_id
```

5. Chạy bot:
```bash
python mexc_futures_bot.py
```

## 📱 Các lệnh Telegram

### Quản lý thông báo
- `/start` - Khởi động bot và xem hướng dẫn
- `/subscribe` - Bật thông báo tự động
- `/unsubscribe` - Tắt thông báo tự động

### Chế độ pump/dump
- `/mode1` - Báo tất cả (3-5% + ≥10%)
- `/mode2` - Chỉ báo trung bình (3-5%)
- `/mode3` - Chỉ báo cực mạnh (≥10%)

### Toggle alerts
- `/pumpdump_on` - Bật thông báo pump/dump
- `/pumpdump_off` - Tắt thông báo pump/dump
- `/ema_on` - Bật thông báo EMA 200
- `/ema_off` - Tắt thông báo EMA 200

### Mute coins
- `/mute COIN` - Tắt thông báo coin (ví dụ: `/mute BTC`)
- `/unmute COIN` - Bật lại thông báo coin
- `/mutelist` - Xem danh sách coin đã mute

### EMA 200
- `/ema200` - Xem coins gần chạm EMA 200 trên tất cả timeframes

### Listing
- `/timelist` - Lịch coin sắp list trong 1 tuần
- `/coinlist` - Coin đã list trong 1 tuần qua

## 🎨 Format Alert

### Pump/Dump Alert
```
⚠️BIẾN ĐỘNG CỰC MẠNH⚠️
┌🚀🚀🚀 BTC ⚡ +12.50% 🟢
└ 45000 → 50625
```

### EMA 200 Alert
```
🎯 EMA 200 ALERT

🕐 M1
🟢 BTC trên EMA200 +0.8%
🔴 ETH dưới EMA200 -1.2%

🕐 M5
🎯 SOL CHẠM EMA200 +0.1%
```

## ⚙️ Cấu hình

File `mexc_futures_bot.py` có các constants có thể điều chỉnh:

```python
# Pump/Dump thresholds
PUMP_THRESHOLD = 3.0      # Tăng >= 3%
DUMP_THRESHOLD = -3.0     # Giảm >= 3%
EXTREME_THRESHOLD = 10.0  # Ngưỡng cực mạnh >= 10%

# EMA 200 settings
EMA_PERIOD = 200
EMA_PROXIMITY_THRESHOLD = 1.5  # ±1.5% từ EMA 200

# Volume filter
MIN_VOL_THRESHOLD = 100000  # Volume tối thiểu
```

## 🐳 Deploy với Docker

```bash
docker-compose up -d
```

## 📊 Deploy trên Railway

1. Fork repository này
2. Tạo project mới trên Railway
3. Connect với GitHub repository
4. Thêm environment variables:
   - `BOT_TOKEN`
   - `CHANNEL_ID`
   - `ADMIN_IDS`
5. Deploy!

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first.

## 📝 License

MIT

## ⚠️ Disclaimer

Bot này chỉ để theo dõi và cảnh báo biến động giá. Không phải lời khuyên đầu tư. Trade có rủi ro!
