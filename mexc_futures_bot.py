import os
import aiohttp
import asyncio
import json
import websockets
from statistics import mean
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz
from collections import defaultdict, deque
import pickle
import os.path

# Load biến môi trường từ file .env
load_dotenv()

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # ID của channel (ví dụ: -1001234567890 hoặc @channel_name)
ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else set()  # Admin user IDs

FUTURES_BASE = "https://contract.mexc.co"
WEBSOCKET_URL = "wss://contract.mexc.co/edge"  # MEXC Futures WebSocket endpoint

# Ngưỡng để báo động (%)
PUMP_THRESHOLD = 3.0      # Tăng >= 3%
DUMP_THRESHOLD = -3.0     # Giảm >= 3%
MODERATE_MAX = 5.0        # Ngưỡng giữa (3-5%)
EXTREME_THRESHOLD = 10.0  # Ngưỡng cực mạnh >= 10%

# Volume tối thiểu để tránh coin ít thanh khoản
MIN_VOL_THRESHOLD = 100000

# EMA 200 Detection
EMA_PERIOD = 200
EMA_PROXIMITY_THRESHOLD = 1.5  # ±1.5% từ EMA 200
EMA_TIMEFRAMES = ["Min1", "Min5", "Min15", "Min30", "Min60", "Hour4"]
EMA_TIMEFRAME_LABELS = {
    "Min1": "M1",
    "Min5": "M5", 
    "Min15": "M15",
    "Min30": "M30",
    "Min60": "H1",
    "Hour4": "H4"
}


SUBSCRIBERS = set()  # User IDs (cho private chat)
ALERT_MODE = {}  # {chat_id: mode} - 1: tất cả, 2: chỉ biến động mạnh ≥3%
MUTED_COINS = {}  # {chat_id: set(symbols)} - danh sách coin bị mute
KNOWN_SYMBOLS = set()  # Danh sách coin đã biết
ALL_SYMBOLS = []  # Cache danh sách coin

# WebSocket price tracking
LAST_PRICES = {}  # {symbol: {"price": float, "time": datetime}}
BASE_PRICES = {}  # {symbol: base_price} - Dynamic reset: chỉ reset sau khi alert
ALERTED_SYMBOLS = {}  # {symbol: timestamp} - tránh spam alert
MAX_CHANGES = {}  # {symbol: {"max_pct": float, "time": datetime}} - Track max % change trong đợt pump/dump
LAST_SIGNIFICANT_CHANGE = {}  # {symbol: timestamp} - Lần cuối có biến động mạnh

# Scheduled restart tracking
SCHEDULED_RESTARTS = set()  # Set of timestamps đã schedule restart

# EMA 200 alert tracking
EMA200_ALERTED = {}  # {symbol: {timeframe: timestamp}} - tránh spam alert EMA 200

# WebSocket-based EMA - candle buffers (NEW)
CANDLE_BUFFERS = {}  # {symbol: {timeframe: deque([close_prices])}}
EMA_VALUES = {}  # {symbol: {timeframe: float}} - cached EMA 200
LAST_CANDLE_TIME = {}  # {symbol: {timeframe: int}} - track candle timestamp

# Alert preferences - bật/tắt từng loại alert
PUMPDUMP_ALERTS_ENABLED = {}  # {chat_id: bool} - True = bật pump/dump alerts
EMA_ALERTS_ENABLED = {}  # {chat_id: bool} - True = bật EMA 200 alerts




# File để lưu dữ liệu persist
DATA_FILE = "bot_data.pkl"


# ================== PERSISTENT DATA ==================
def save_data():
    """Lưu dữ liệu quan trọng vào file"""
    data = {
        "subscribers": SUBSCRIBERS,
        "alert_mode": ALERT_MODE,
        "muted_coins": MUTED_COINS,
        "known_symbols": KNOWN_SYMBOLS,
        "pumpdump_alerts_enabled": PUMPDUMP_ALERTS_ENABLED,
        "ema_alerts_enabled": EMA_ALERTS_ENABLED
    }
    try:
        with open(DATA_FILE, "wb") as f:
            pickle.dump(data, f)
        print(f"✅ Đã lưu dữ liệu: {len(SUBSCRIBERS)} subscribers")
    except Exception as e:
        print(f"⚠️ Lỗi lưu dữ liệu: {e}")


def load_data():
    """Tải dữ liệu từ file"""
    global SUBSCRIBERS, ALERT_MODE, MUTED_COINS, KNOWN_SYMBOLS, PUMPDUMP_ALERTS_ENABLED, EMA_ALERTS_ENABLED
    
    if not os.path.exists(DATA_FILE):
        print("ℹ️ Chưa có dữ liệu lưu trữ")
        return
    
    try:
        with open(DATA_FILE, "rb") as f:
            data = pickle.load(f)
        
        SUBSCRIBERS = data.get("subscribers", set())
        ALERT_MODE = data.get("alert_mode", {})
        MUTED_COINS = data.get("muted_coins", {})
        KNOWN_SYMBOLS = data.get("known_symbols", set())
        PUMPDUMP_ALERTS_ENABLED = data.get("pumpdump_alerts_enabled", {})
        EMA_ALERTS_ENABLED = data.get("ema_alerts_enabled", {})
        
        print(f"✅ Đã tải dữ liệu: {len(SUBSCRIBERS)} subscribers, {len(KNOWN_SYMBOLS)} coins")
    except Exception as e:
        print(f"⚠️ Lỗi tải dữ liệu: {e}")


# ================== UTIL ==================
async def fetch_json(session, url, params=None, retry=3):
    """Fetch JSON với retry logic cho 429 errors"""
    import random
    
    for attempt in range(retry):
        try:
            async with session.get(url, params=params, timeout=10) as r:
                if r.status == 429:
                    # Rate limit - đợi exponential backoff
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    print(f"⚠️ Rate limit {url}, retry sau {wait:.1f}s...")
                    await asyncio.sleep(wait)
                    continue
                
                r.raise_for_status()
                data = await r.json()
                return data.get("data", data)
        except Exception as e:
            if attempt == retry - 1:  # Lần thử cuối
                print(f"❌ Error calling {url}: {e}")
                raise
            # Thử lại với delay
            await asyncio.sleep(random.uniform(0.5, 1.5))
    
    raise Exception(f"Failed after {retry} retries")


async def get_kline(session, symbol, interval="Min5", limit=10):
    url = f"{FUTURES_BASE}/api/v1/contract/kline/{symbol}"
    try:
        data = await fetch_json(session, url, {"interval": interval})
        
        # Kiểm tra data có đầy đủ fields không
        if not data or "close" not in data or "high" not in data or "low" not in data or "vol" not in data:
            return None, None, None, None
        
        closes = [float(x) for x in data["close"][-limit:]]
        highs = [float(x) for x in data["high"][-limit:]]
        lows = [float(x) for x in data["low"][-limit:]]
        vols = [float(v) for v in data["vol"][-limit:]]
        return closes, highs, lows, vols
    except Exception as e:
        # Bỏ qua lỗi 404 (coin đã delist) và lỗi data format
        if "404" not in str(e) and "close" not in str(e):
            print(f"⚠️ Error getting kline for {symbol}: {e}")
        return None, None, None, None




async def get_ticker(session, symbol):
    """Lấy giá ticker hiện tại (realtime)"""
    url = f"{FUTURES_BASE}/api/v1/contract/ticker/{symbol}"
    try:
        data = await fetch_json(session, url)
        return float(data["lastPrice"]) if data and "lastPrice" in data else None
    except Exception as e:
        # Bỏ qua lỗi 404 (coin đã delist) - không in ra để tránh spam log
        if "404" not in str(e):
            print(f"⚠️ Error getting ticker for {symbol}: {e}")
        return None



async def get_all_contracts(session):
    url = f"{FUTURES_BASE}/api/v1/contract/detail"
    data = await fetch_json(session, url)
    if isinstance(data, dict): data = [data]

    return [
        c for c in data
        if c.get("settleCoin") == "USDT" and c.get("state") == 0
    ]


async def get_all_symbols(session):
    """Lấy danh sách TẤT CẢ symbol USDT Futures đang active"""
    contracts = await get_all_contracts(session)
    return [c["symbol"] for c in contracts if c.get("symbol")]


def fmt_top(title, data):
    txt = [f"🔥 *{title}*"]
    for i, (sym, chg) in enumerate(data, start=1):
        icon = "🚀" if chg > 0 else "💥"
        txt.append(f"{i}. {icon} `{sym}` → {chg:+.2f}%")
    return "\n".join(txt)


def calculate_ema(prices, period=200):
    """
    Tính EMA (Exponential Moving Average)
    Formula: EMA = Price(t) × k + EMA(y) × (1 − k)
    k = 2 / (N + 1)
    """
    if len(prices) < period:
        return None
    
    k = 2 / (period + 1)
    
    # Bắt đầu với SMA cho period đầu tiên
    ema = sum(prices[:period]) / period
    
    # Tính EMA cho các giá trị còn lại
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    
    return ema


async def get_ema200_data(session, symbol, timeframe="Min5"):
    """
    Lấy dữ liệu EMA 200 cho 1 symbol và 1 timeframe
    Returns: dict với ema200, current_price, distance_pct hoặc None nếu lỗi
    """
    try:
        # Lấy 250 candles để đảm bảo đủ data tính EMA 200
        closes, _, _, _ = await get_kline(session, symbol, timeframe, limit=250)
        
        # Kiểm tra nếu get_kline trả về None (coin đã delist)
        if closes is None or len(closes) < EMA_PERIOD:
            return None

        
        # Tính EMA 200
        ema200 = calculate_ema(closes, EMA_PERIOD)
        if ema200 is None:
            return None
        
        # Lấy giá hiện tại (realtime)
        current_price = await get_ticker(session, symbol)
        if not current_price:
            return None
        
        # Tính khoảng cách % từ giá hiện tại đến EMA 200
        distance_pct = ((current_price - ema200) / ema200) * 100
        
        return {
            "ema200": ema200,
            "current_price": current_price,
            "distance_pct": distance_pct
        }
    except Exception as e:
        # print(f"Error getting EMA200 for {symbol} {timeframe}: {e}")
        return None



async def detect_ema200_proximity(session, symbols, threshold=EMA_PROXIMITY_THRESHOLD):
    """
    Phát hiện coins gần chạm EMA 200 trên đa khung thời gian
    Returns: dict {timeframe: [(symbol, ema200, current_price, distance_pct), ...]}
    """
    import random
    
    results = {tf: [] for tf in EMA_TIMEFRAMES}
    
    # Scan từng timeframe
    for timeframe in EMA_TIMEFRAMES:
        print(f"🔍 Scanning EMA 200 for {timeframe}...")
        
        # Chia nhỏ thành batch để tránh rate limit
        BATCH_SIZE = 30
        
        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i:i+BATCH_SIZE]
            tasks = [get_ema200_data(session, sym, timeframe) for sym in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Lọc kết quả và kiểm tra proximity
            for j, result in enumerate(batch_results):
                if result and not isinstance(result, Exception):
                    distance = result["distance_pct"]
                    
                    # Kiểm tra nếu trong vùng proximity threshold
                    if abs(distance) <= threshold:
                        symbol = batch[j]
                        results[timeframe].append((
                            symbol,
                            result["ema200"],
                            result["current_price"],
                            distance
                        ))
            
            # Delay giữa các batch
            if i + BATCH_SIZE < len(symbols):
                await asyncio.sleep(random.uniform(0.3, 0.6))
        
        # Delay giữa các timeframe
        await asyncio.sleep(random.uniform(0.5, 1.0))
    
    # Sort mỗi timeframe theo khoảng cách gần nhất
    for tf in results:
        results[tf].sort(key=lambda x: abs(x[3]))
    
    return results


# ==================== WEBSOCKET EMA FUNCTIONS ====================

def update_candle_buffer(symbol, timeframe, candle_close, candle_time):
    """Update candle buffer và recalculate EMA khi có candle mới"""
    global CANDLE_BUFFERS, EMA_VALUES, LAST_CANDLE_TIME
    
    if symbol not in CANDLE_BUFFERS:
        CANDLE_BUFFERS[symbol] = {}
        EMA_VALUES[symbol] = {}
        LAST_CANDLE_TIME[symbol] = {}
    
    if timeframe not in CANDLE_BUFFERS[symbol]:
        CANDLE_BUFFERS[symbol][timeframe] = deque(maxlen=EMA_PERIOD)
        LAST_CANDLE_TIME[symbol][timeframe] = 0
    
    if candle_time > LAST_CANDLE_TIME[symbol][timeframe]:
        buffer = CANDLE_BUFFERS[symbol][timeframe]
        buffer.append(float(candle_close))
        LAST_CANDLE_TIME[symbol][timeframe] = candle_time
        
        if len(buffer) >= EMA_PERIOD:
            ema200 = calculate_ema(list(buffer), EMA_PERIOD)
            if ema200:
                EMA_VALUES[symbol][timeframe] = ema200


async def check_ema_proximity_realtime(symbol, current_price, context):
    """Check realtime nếu giá gần chạm EMA 200"""
    if symbol not in EMA_VALUES:
        return
    
    alerts, now = [], datetime.now()
    
    for timeframe, ema200 in EMA_VALUES[symbol].items():
        distance_pct = ((current_price - ema200) / ema200) * 100
        
        if abs(distance_pct) <= EMA_PROXIMITY_THRESHOLD:
            if symbol not in EMA200_ALERTED:
                EMA200_ALERTED[symbol] = {}
            
            last_alert = EMA200_ALERTED[symbol].get(timeframe)
            if last_alert is None or (now - last_alert).total_seconds() > 1800:
                alerts.append((timeframe, ema200, distance_pct))
                EMA200_ALERTED[symbol][timeframe] = now
    
    if alerts and (CHANNEL_ID or SUBSCRIBERS):
        msg_parts = ["🎯 *EMA 200 ALERT*\\n"]
        for tf, ema, dist in alerts:
            tf_label = EMA_TIMEFRAME_LABELS.get(tf, tf)
            coin = symbol.replace("_USDT", "")
            icon = "🎯" if abs(dist) <= 0.3 else ("🟢" if dist > 0 else "🔴")
            status = "CHẠM" if abs(dist) <= 0.3 else ("trên" if dist > 0 else "dưới")
            link = f"https://www.mexc.co/futures/{symbol}"
            msg_parts.append(f"\\n🕐 *{tf_label}*")
            msg_parts.append(f"{icon} [{coin}]({link}) {status} EMA200 `{dist:+.2f}%`")
        
        msg, tasks = "\\n".join(msg_parts), []
        if CHANNEL_ID:
            tasks.append(context.bot.send_message(CHANNEL_ID, msg, parse_mode="Markdown", disable_web_page_preview=True))
        for chat in SUBSCRIBERS:
            if EMA_ALERTS_ENABLED.get(chat, True):
                tasks.append(context.bot.send_message(chat, msg, parse_mode="Markdown", disable_web_page_preview=True))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def init_candle_buffers(session):
    """Load initial 200 candles"""
    print("📊 Loading EMA buffers...")
    loaded = 0
    for tf in EMA_TIMEFRAMES:
        print(f"  📈 {EMA_TIMEFRAME_LABELS.get(tf, tf)}...")
        for i in range(0, len(ALL_SYMBOLS), 50):
            for sym in ALL_SYMBOLS[i:i+50]:
                try:
                    closes, _, _, _ = await get_kline(session, sym, tf, limit=EMA_PERIOD)
                    if closes and len(closes) >= EMA_PERIOD:
                        if sym not in CANDLE_BUFFERS:
                            CANDLE_BUFFERS[sym] = {}
                            EMA_VALUES[sym] = {}
                            LAST_CANDLE_TIME[sym] = {}
                        CANDLE_BUFFERS[sym][tf] = deque(closes, maxlen=EMA_PERIOD)
                        LAST_CANDLE_TIME[sym][tf] = 0
                        ema = calculate_ema(list(CANDLE_BUFFERS[sym][tf]), EMA_PERIOD)
                        if ema:
                            EMA_VALUES[sym][tf] = ema
                            loaded += 1
                except:
                    pass
            await asyncio.sleep(0.05)
    print(f"✅ Loaded {loaded} EMA buffers")




def fmt_alert(symbol, old_price, new_price, change_pct):
    """Format báo động pump/dump với 2 mức độ: trung bình (3-5%) và cực mạnh (≥10%)"""
    color = "🟢" if change_pct >= 0 else "🔴"
    
    # Phân loại 2 mức độ biến động
    abs_change = abs(change_pct)
    
    if abs_change >= 10.0:
        # Mức 2: BIẾN ĐỘNG CỰC MẠNH >= 10%
        icon = "🚀🚀🚀" if change_pct >= 0 else "💥💥💥"
        highlight = "⚠️BIẾN ĐỘNG CỰC MẠNH⚠️"
        size_tag = f"*{change_pct:+.2f}%*"  # Bold cho số %
    else:
        # Mức 1: Trung bình 3-9.9%
        icon = "🚀🚀" if change_pct >= 0 else "💥💥"
        highlight = ""
        size_tag = f"{change_pct:+.2f}%"
    
    # Lấy tên coin (bỏ _USDT)
    coin_name = symbol.replace("_USDT", "")
    
    # Link ẩn để không hiển thị URL
    link = f"https://www.mexc.co/futures/{symbol}"
    
    return (
        f"{highlight}"
        f"┌{icon} [{coin_name}]({link}) ⚡ {size_tag} {color}\n"
        f"└ {old_price:.6g} → {new_price:.6g}"
    )


# ================== ADMIN CHECK ==================
def admin_only(func):
    """Decorator để giới hạn command chỉ cho admin"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Nếu không set ADMIN_IDS → cho phép tất cả (backward compatibility)
        if not ADMIN_IDS:
            return await func(update, context)
        
        # Nếu không phải admin → từ chối
        if user_id not in ADMIN_IDS:
            msg = (
                "⛔ Lệnh này chỉ dành cho admin.\n\n"
                "Bạn có thể xem alert trong channel!"
            )
            if getattr(update, "effective_message", None):
                await update.effective_message.reply_text(msg)
            else:
                print("⛔ Lệnh admin bị từ chối (no message object)")
            return
        
        return await func(update, context)
    
    return wrapper


# ================== COMMANDS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)
    if chat_id not in ALERT_MODE:
        ALERT_MODE[chat_id] = 1  # Mặc định: tất cả

    current_mode = ALERT_MODE.get(chat_id, 1)
    if current_mode == 1:
        mode_text = "Tất cả (3-5% + ≥10%)"
    elif current_mode == 2:
        mode_text = "Chỉ trung bình (3-5%)"
    else:
        mode_text = "Chỉ cực mạnh (≥10%)"

    text = (
        "🤖 Bot Quét MEXC Futures !\n\n"
        "✅ Nhận giá REALTIME từ server\n"
        "✅ Báo NGAY LẬP TỨC khi ≥3%\n"
        "✅ Dynamic base price - không miss pump/dump\n\n"
        f"📊 Chế độ hiện tại: {mode_text}\n\n"
        "Các lệnh:\n"
        "/subscribe – bật báo động\n"
        "/unsubscribe – tắt báo động\n"
        "/mode1 – báo tất cả (3-5% + ≥10%)\n"
        "/mode2 – chỉ báo 3-5%\n"
        "/mode3 – chỉ báo ≥10%\n"
        "/pumpdump_on – bật thông báo pump/dump\n"
        "/pumpdump_off – tắt thông báo pump/dump\n"
        "/ema_on – bật thông báo EMA 200\n"
        "/ema_off – tắt thông báo EMA 200\n"
        "/mute COIN – tắt thông báo coin\n"
        "/unmute COIN – bật lại thông báo coin\n"
        "/mutelist – xem danh sách coin đã mute\n"
        "/ema200 – xem coins gần chạm EMA 200\n"
        "/timelist – lịch coin sắp list\n"
        "/coinlist – coin vừa list gần đây"
    )



    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(text)
    else:
        print("Start command invoked but no message to reply to")


async def subscribe(update, context):
    SUBSCRIBERS.add(update.effective_chat.id)
    save_data()  # Lưu ngay sau khi subscribe
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text("Đã bật báo!")
    else:
        print("Subscribe executed (no message to reply)")


async def unsubscribe(update, context):
    SUBSCRIBERS.discard(update.effective_chat.id)
    save_data()  # Lưu sau khi unsubscribe
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text("Đã tắt báo!")
    else:
        print("Unsubscribe executed (no message to reply)")


async def mode1(update, context):
    chat_id = update.effective_chat.id
    ALERT_MODE[chat_id] = 1
    save_data()  # Lưu sau khi đổi mode
    text = (
        "✅ Đã chuyển sang Mode 1\n\n"
        "📊 Báo TẤT CẢ biến động:\n"
        "  🔸 Trung bình (3-5%)\n"
        "  🔥 Cực mạnh (≥10%)"
    )
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(text)
    else:
        print("Mode1 set (no message to reply)")


async def mode2(update, context):
    chat_id = update.effective_chat.id
    ALERT_MODE[chat_id] = 2
    save_data()  # Lưu sau khi đổi mode
    text = (
        "✅ Đã chuyển sang Mode 2\n\n"
        "📊 CHỊ báo biến động trung bình:\n"
        "  🔸 3-5% (bỏ qua cực mạnh ≥10%)"
    )
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(text)
    else:
        print("Mode2 set (no message to reply)")


async def mode3(update, context):
    chat_id = update.effective_chat.id
    ALERT_MODE[chat_id] = 3
    save_data()  # Lưu sau khi đổi mode
    text = (
        "✅ Đã chuyển sang Mode 3\n\n"
        "📊 CHỊ báo biến động CỰC MẠNH:\n"
        "  🔥 ≥10% (bỏ qua 3-5%)"
    )
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(text)
    else:
        print("Mode3 set (no message to reply)")


async def mute_coin(update, context):
    chat_id = update.effective_chat.id
    
    if not context.args:
        if getattr(update, "effective_message", None):
            await update.effective_message.reply_text(
                "❌ Vui lòng nhập tên coin\n\n"
                "Ví dụ: /mute XION hoặc /mute xion"
            )
        else:
            print("❌ Mute command thiếu args (không có message object)")
        return
    
    coin = context.args[0].upper().strip()  # Tự động chuyển thành chữ hoa
    symbol = f"{coin}_USDT" if not coin.endswith("_USDT") else coin
    
    if chat_id not in MUTED_COINS:
        MUTED_COINS[chat_id] = set()
    
    MUTED_COINS[chat_id].add(symbol)
    save_data()  # Lưu sau khi mute
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(f"🔇 Đã tắt thông báo cho `{coin}`", parse_mode="Markdown")
    else:
        try:
            await context.bot.send_message(chat_id, f"🔇 Đã tắt thông báo cho `{coin}`", parse_mode="Markdown")
        except Exception:
            print("🔇 Đã mute coin nhưng không thể gửi tin xác nhận")


@admin_only
async def unmute_coin(update, context):
    chat_id = update.effective_chat.id
    
    if not context.args:
        if getattr(update, "effective_message", None):
            await update.effective_message.reply_text(
                "❌ Vui lòng nhập tên coin\n\n"
                "Ví dụ: /unmute XION hoặc /unmute xion"
            )
        else:
            print("❌ Unmute command thiếu args (không có message object)")
        return
    
    coin = context.args[0].upper().strip()  # Tự động chuyển thành chữ hoa
    symbol = f"{coin}_USDT" if not coin.endswith("_USDT") else coin
    
    if chat_id in MUTED_COINS and symbol in MUTED_COINS[chat_id]:
        MUTED_COINS[chat_id].remove(symbol)
        save_data()  # Lưu sau khi unmute
        if getattr(update, "effective_message", None):
            await update.effective_message.reply_text(f"🔔 Đã bật lại thông báo cho `{coin}`", parse_mode="Markdown")
        else:
            try:
                await context.bot.send_message(chat_id, f"🔔 Đã bật lại thông báo cho `{coin}`", parse_mode="Markdown")
            except Exception:
                print("🔔 Đã unmute coin nhưng không thể gửi tin xác nhận")
    else:
        if getattr(update, "effective_message", None):
            await update.effective_message.reply_text(f"ℹ️ `{coin}` chưa bị mute", parse_mode="Markdown")
        else:
            try:
                await context.bot.send_message(chat_id, f"ℹ️ `{coin}` chưa bị mute", parse_mode="Markdown")
            except Exception:
                print("ℹ️ Trạng thái unmute không thể gửi (không có message)")


async def ema200(update, context):
    """Lệnh xem coins gần chạm EMA 200 trên đa khung thời gian"""
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text("⏳ Đang quét EMA 200 trên tất cả khung thời gian...")
    else:
        try:
            await context.bot.send_message(update.effective_chat.id, "⏳ Đang quét EMA 200...")
        except Exception:
            print("⏳ EMA200 requested (no message object)")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Detect coins near EMA 200
            results = await detect_ema200_proximity(session, ALL_SYMBOLS)
            
            # Format message
            msg_parts = ["📊 *COINS GẦN CHẠM EMA 200*\n"]
            total_count = 0
            
            for timeframe in EMA_TIMEFRAMES:
                coins = results[timeframe]
                if not coins:
                    continue
                
                tf_label = EMA_TIMEFRAME_LABELS[timeframe]
                msg_parts.append(f"\n🕐 *{tf_label}*")
                
                # Hiển thị tối đa 10 coins gần nhất mỗi timeframe
                for symbol, ema200, current_price, distance in coins[:10]:
                    coin_name = symbol.replace("_USDT", "")
                    
                    # Icon dựa trên vị trí
                    if abs(distance) <= 0.3:
                        icon = "🎯"  # Đang chạm
                        status = "CHẠM"
                    elif distance > 0:
                        icon = "🟢"  # Trên EMA
                        status = "trên"
                    else:
                        icon = "🔴"  # Dưới EMA
                        status = "dưới"
                    
                    link = f"https://www.mexc.co/futures/{symbol}"
                    msg_parts.append(
                        f"{icon} [{coin_name}]({link}) "
                        f"`{distance:+.2f}%` {status} EMA200"
                    )
                    total_count += 1
                
                if len(coins) > 10:
                    msg_parts.append(f"_...và {len(coins) - 10} coin khác_")
            
            if total_count == 0:
                msg = "ℹ️ Không có coin nào gần EMA 200 trong vùng ±1.5%"
            else:
                msg_parts.append(f"\n_Tổng: {total_count} coins (hiển thị top 10/timeframe)_")
                msg = "\n".join(msg_parts)
            
            if getattr(update, "effective_message", None):
                await update.effective_message.reply_text(
                    msg, 
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            else:
                try:
                    await context.bot.send_message(
                        update.effective_chat.id, 
                        msg,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                except Exception:
                    print("📊 Không thể gửi kết quả EMA200")
    
    except Exception as e:
        print(f"❌ Lỗi EMA200 scan: {e}")
        error_msg = "❌ Có lỗi khi quét EMA 200. Vui lòng thử lại sau."
        if getattr(update, "effective_message", None):
            await update.effective_message.reply_text(error_msg)
        else:
            try:
                await context.bot.send_message(update.effective_chat.id, error_msg)
            except Exception:
                print("❌ EMA200: không thể gửi lỗi đến user")


async def pumpdump_on(update, context):
    """Bật thông báo pump/dump"""
    chat_id = update.effective_chat.id
    PUMPDUMP_ALERTS_ENABLED[chat_id] = True
    save_data()
    
    msg = "✅ Đã BẬT thông báo Pump/Dump"
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(msg)
    else:
        try:
            await context.bot.send_message(chat_id, msg)
        except Exception:
            print("✅ Pump/Dump alerts enabled")


async def pumpdump_off(update, context):
    """Tắt thông báo pump/dump"""
    chat_id = update.effective_chat.id
    PUMPDUMP_ALERTS_ENABLED[chat_id] = False
    save_data()
    
    msg = "🔕 Đã TẮT thông báo Pump/Dump"
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(msg)
    else:
        try:
            await context.bot.send_message(chat_id, msg)
        except Exception:
            print("🔕 Pump/Dump alerts disabled")


async def ema_on(update, context):
    """Bật thông báo EMA 200"""
    chat_id = update.effective_chat.id
    EMA_ALERTS_ENABLED[chat_id] = True
    save_data()
    
    msg = "✅ Đã BẬT thông báo EMA 200"
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(msg)
    else:
        try:
            await context.bot.send_message(chat_id, msg)
        except Exception:
            print("✅ EMA 200 alerts enabled")


async def ema_off(update, context):
    """Tắt thông báo EMA 200"""
    chat_id = update.effective_chat.id
    EMA_ALERTS_ENABLED[chat_id] = False
    save_data()
    
    msg = "🔕 Đã TẮT thông báo EMA 200"
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(msg)
    else:
        try:
            await context.bot.send_message(chat_id, msg)
        except Exception:
            print("🔕 EMA 200 alerts disabled")





async def mutelist(update, context):
    chat_id = update.effective_chat.id
    
    if chat_id not in MUTED_COINS or not MUTED_COINS[chat_id]:
        if getattr(update, "effective_message", None):
            await update.effective_message.reply_text("ℹ️ Chưa có coin nào bị mute")
        else:
            try:
                await context.bot.send_message(chat_id, "ℹ️ Chưa có coin nào bị mute")
            except Exception:
                print("ℹ️ Không có coin mute (không thể gửi message)")
        return
    
    coins = [sym.replace("_USDT", "") for sym in MUTED_COINS[chat_id]]
    msg = "🔇 *DANH SÁCH COIN ĐÃ MUTE*\n\n"
    msg += "\n".join([f"• `{coin}`" for coin in sorted(coins)])
    msg += f"\n\n_Tổng: {len(coins)} coin_"
    
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text(msg, parse_mode="Markdown")
    else:
        try:
            await context.bot.send_message(chat_id, msg, parse_mode="Markdown")
        except Exception:
            print("ℹ️ Không thể gửi danh sách mute (no message object)")


async def websocket_stream(context):
    """WebSocket stream để nhận giá realtime từ MEXC Futures"""
    reconnect_delay = 5
    
    while True:
        try:
            # Tăng timeout và thêm ping interval
            async with websockets.connect(
                WEBSOCKET_URL,
                ping_interval=20,  # Ping server mỗi 20s để giữ kết nối
                ping_timeout=10,   # Timeout cho pong response
                close_timeout=10
            ) as ws:
                print(f"✅ Kết nối WebSocket thành công")
                
                # Subscribe tất cả ticker streams - MEXC Futures format
                for symbol in ALL_SYMBOLS:
                    # MEXC Futures WebSocket format: sub.ticker
                    sub_msg = {
                        "method": "sub.ticker",
                        "param": {
                            "symbol": symbol
                        }
                    }
                    await ws.send(json.dumps(sub_msg))
                    await asyncio.sleep(0.005)  # 5ms delay giữa subscriptions
                
                print(f"✅ Đã subscribe {len(ALL_SYMBOLS)} coin qua WebSocket")
                
                # Subscribe kline cho EMA (chỉ coins có buffer)
                if CANDLE_BUFFERS:
                    print(f"📊 Subscribing kline streams...")
                    kline_count = 0
                    for symbol in CANDLE_BUFFERS.keys():
                        for timeframe in EMA_TIMEFRAMES:
                            await ws.send(json.dumps({
                                "method": "sub.kline",
                                "param": {"symbol": symbol, "interval": timeframe}
                            }))
                            kline_count += 1
                            await asyncio.sleep(0.005)
                    print(f"✅ Subscribed {kline_count} kline streams")

                
                # Reset reconnect delay sau khi connect thành công
                reconnect_delay = 5
                
                # Lắng nghe messages
                async for message in ws:
                    try:
                        data = json.loads(message)
                        
                        # Xử lý ping/pong
                        if "ping" in data:
                            await ws.send(json.dumps({"pong": data["ping"]}))
                            continue
                        
                        # Xử lý ticker data
                        if "channel" in data and data.get("channel") == "push.ticker":
                            if "data" in data:
                                await process_ticker(data["data"], context)
                        
                        # Xử lý kline data - UPDATE BUFFER
                        elif "channel" in data and data.get("channel") == "push.kline":
                            if "data" in data:
                                kline = data["data"]
                                sym = kline.get("symbol")
                                interval = kline.get("interval")
                                close = kline.get("c")
                                timestamp = kline.get("t")
                                if sym and interval and close and timestamp:
                                    update_candle_buffer(sym, interval, close, timestamp)

                            
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        print(f"❌ Error processing message: {e}")
                        continue
                        
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            print(f"🔄 Reconnecting in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            
            # Exponential backoff: 5s -> 10s -> 20s -> max 60s
            reconnect_delay = min(reconnect_delay * 2, 60)


async def process_ticker(ticker_data, context):
    """Xử lý ticker data từ WebSocket và phát hiện pump/dump - DUAL BASE PRICE"""
    symbol = ticker_data.get("symbol")
    if not symbol:
        return
    
    try:
        current_price = float(ticker_data.get("lastPrice", 0))
        volume = float(ticker_data.get("volume24", 0))
        
        if current_price == 0 or volume < MIN_VOL_THRESHOLD:
            return
        
        now = datetime.now()
        
        # Lưu giá hiện tại
        LAST_PRICES[symbol] = {
            "price": current_price,
            "time": now
        }
        
        # REALTIME EMA CHECK
        await check_ema_proximity_realtime(symbol, current_price, context)
        
        # Thiết lập base price nếu chưa có
        if symbol not in BASE_PRICES:
            BASE_PRICES[symbol] = current_price
            return

        
        # Tính % thay đổi từ BASE_PRICE (dynamic - chỉ reset sau alert)
        base_price = BASE_PRICES[symbol]
        price_change = (current_price - base_price) / base_price * 100
        abs_change = abs(price_change)
        
        # Track max change trong đợt pump/dump
        if symbol not in MAX_CHANGES:
            MAX_CHANGES[symbol] = {"max_pct": 0, "time": now}
        
        # Cập nhật max change nếu vượt qua
        if abs_change > abs(MAX_CHANGES[symbol]["max_pct"]):
            MAX_CHANGES[symbol] = {"max_pct": price_change, "time": now}
            LAST_SIGNIFICANT_CHANGE[symbol] = now
        
        # Kiểm tra xem có nên reset base price không
        # Reset nếu: giá quay về gần base (< 1.5%) HOẶC đã qua 3 phút không có biến động mạnh
        should_reset_base = False
        if abs_change < 1.5:  # Giá đã quay về gần base price
            should_reset_base = True
        elif symbol in LAST_SIGNIFICANT_CHANGE:
            time_since_last = (now - LAST_SIGNIFICANT_CHANGE[symbol]).total_seconds()
            if time_since_last > 50:  # 50 giây không có biến động mạnh
                should_reset_base = True
        
        if should_reset_base and symbol in MAX_CHANGES:
            BASE_PRICES[symbol] = current_price
            MAX_CHANGES[symbol] = {"max_pct": 0, "time": now}
        
        # Kiểm tra ngưỡng và alert ngay khi vượt
        should_alert = False
        if (price_change >= PUMP_THRESHOLD or price_change <= DUMP_THRESHOLD):
            last_alert = ALERTED_SYMBOLS.get(symbol)
            last_max = MAX_CHANGES[symbol].get("last_alerted_pct")
            # Báo ngay lần đầu vượt ngưỡng
            if last_alert is None:
                should_alert = True
            else:
                # Nếu đã báo rồi, chỉ báo lại khi tăng thêm >=1.5%
                if last_max is None:
                    last_max = 0.0
                if abs_change >= abs(last_max) + 1.5:
                    should_alert = True
            if should_alert:
                ALERTED_SYMBOLS[symbol] = now
                MAX_CHANGES[symbol]["last_alerted_pct"] = price_change

        if should_alert and SUBSCRIBERS:
            # Dùng BASE_PRICE và hiển thị % thay đổi TỔNG
            msg = fmt_alert(symbol, base_price, current_price, price_change)
            if price_change >= PUMP_THRESHOLD:
                print(f"🚀 PUMP: {symbol} +{price_change:.2f}% (max: +{MAX_CHANGES[symbol]['max_pct']:.2f}%)")
            else:
                print(f"💥 DUMP: {symbol} {price_change:.2f}% (max: {MAX_CHANGES[symbol]['max_pct']:.2f}%)")

            # Gửi alert
            tasks = []
            
            # Nếu có CHANNEL_ID → gửi vào channel
            if CHANNEL_ID:
                tasks.append(
                    context.bot.send_message(
                        CHANNEL_ID,
                        msg,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                )
            
            # Gửi cho subscribers cá nhân (nếu có)
            for chat in SUBSCRIBERS:
                # Kiểm tra xem user có bật pump/dump alerts không
                pumpdump_enabled = PUMPDUMP_ALERTS_ENABLED.get(chat, True)  # Mặc định: bật
                if not pumpdump_enabled:
                    continue
                
                # Kiểm tra coin có bị mute không
                if chat in MUTED_COINS and symbol in MUTED_COINS[chat]:
                    continue
                
                mode = ALERT_MODE.get(chat, 1)  # Mặc định mode 1
                abs_change = abs(price_change)


                # Mode 1: Báo tất cả (3-5% + ≥10%)
                # Mode 2: Chỉ báo 3-5%
                # Mode 3: Chỉ báo ≥10%
                
                if mode == 2:
                    # Mode 2: Chỉ 3-5%, bỏ qua ≥10%
                    if abs_change > MODERATE_MAX:
                        continue
                elif mode == 3:
                    # Mode 3: Chỉ ≥10%
                    if abs_change < EXTREME_THRESHOLD:
                        continue
                # Mode 1: Không filter, báo tất cả

                tasks.append(
                    context.bot.send_message(
                        chat,
                        msg,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                )

            if tasks:
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    # Nếu đây là alert cực mạnh (>= EXTREME_THRESHOLD) -> reset base ngay lập tức
                    try:
                        if abs_change >= EXTREME_THRESHOLD:
                            BASE_PRICES[symbol] = current_price
                            MAX_CHANGES[symbol] = {"max_pct": 0, "time": now}
                            print(f"🔁 Reset base price for {symbol} after extreme alert ({abs_change:.2f}%)")
                    except Exception:
                        pass
                except Exception as e:
                    print(f"❌ Lỗi gửi tin nhắn: {e}")
            
    except Exception as e:
        print(f"❌ Error processing ticker for {symbol}: {e}")


async def reset_base_prices(context):
    """Job backup reset base prices mỗi 5 phút"""
    global BASE_PRICES
    
    # Cập nhật base prices từ last prices (chỉ cho coin không có alert gần đây)
    for symbol, data in LAST_PRICES.items():
        # Chỉ reset nếu không có alert trong 5 phút qua
        if symbol not in ALERTED_SYMBOLS or \
           (datetime.now() - ALERTED_SYMBOLS[symbol]).seconds > 300:
            BASE_PRICES[symbol] = data["price"]
    
    print(f"🔄 Backup reset {len(BASE_PRICES)} base prices")


async def calc_movers(session, interval, symbols):
    """Tính % thay đổi giá cho danh sách symbols - BATCH để tránh rate limit"""
    import asyncio
    
    async def get_single_mover(sym):
        """Lấy dữ liệu cho 1 coin - so sánh giá HIỆN TẠI vs candle cuối (bao gồm HIGH/LOW để bắt râu)"""
        try:
            # Lấy candle đã đóng (close, high, low, volume)
            closes, highs, lows, vols = await get_kline(session, sym, interval, 2)
            if len(closes) < 1 or closes[-1] == 0:
                return None
            
            # Lấy giá REALTIME hiện tại
            current_price = await get_ticker(session, sym)
            if not current_price:
                return None
            
            # Giá base để tính % thay đổi
            base_price = closes[-1]  # Candle đóng cửa
            high_price = highs[-1]   # Giá cao nhất của candle
            low_price = lows[-1]     # Giá thấp nhất của candle
            vol = vols[-1]
            
            # Tính % thay đổi so với close
            chg_from_close = (current_price - base_price) / base_price * 100
            
            # Kiểm tra xem giá hiện tại có vượt HIGH hoặc LOW không (phát hiện breakout)
            chg_from_high = (current_price - high_price) / high_price * 100
            chg_from_low = (current_price - low_price) / low_price * 100
            
            # Chọn % thay đổi lớn nhất để phát hiện các spike/wick
            if abs(chg_from_close) >= abs(chg_from_high) and abs(chg_from_close) >= abs(chg_from_low):
                chg = chg_from_close
                old_price = base_price
            elif abs(chg_from_high) > abs(chg_from_low):
                chg = chg_from_high
                old_price = high_price
            else:
                chg = chg_from_low
                old_price = low_price
            
            return (sym, chg, old_price, current_price, vol)
        except Exception as e:
            return None
    
    # CHIA NHỎ THÀNH BATCH để tránh 429 Too Many Requests
    BATCH_SIZE = 50  # Quét 50 coins/lần
    BATCH_DELAY_MIN = 0.6  # Random delay 0.6-1.0s giữa các batch
    BATCH_DELAY_MAX = 1.0
    
    all_movers = []
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i+BATCH_SIZE]
        tasks = [get_single_mover(sym) for sym in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Lọc bỏ None và exceptions
        movers = [r for r in results if r is not None and not isinstance(r, Exception)]
        all_movers.extend(movers)
        
        # Random delay giữa các batch (trừ batch cuối)
        if i + BATCH_SIZE < len(symbols):
            import random
            delay = random.uniform(BATCH_DELAY_MIN, BATCH_DELAY_MAX)
            await asyncio.sleep(delay)
    
    return all_movers


async def timelist(update, context):
    """Lệnh xem lịch coin sẽ list trong 1 tuần - API Calendar"""
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text("⏳ Đang lấy lịch listing...")
    else:
        try:
            await context.bot.send_message(update.effective_chat.id, "⏳ Đang lấy lịch listing...")
        except Exception:
            print("⏳ Timelist requested (no message object)")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Gọi API calendar
            timestamp = int(datetime.now().timestamp() * 1000)
            url = f"https://www.mexc.co/api/operation/new_coin_calendar?timestamp={timestamp}"
            
            async with session.get(url, timeout=15) as r:
                if r.status != 200:
                    raise Exception(f"HTTP {r.status}")
                
                data = await r.json()
                coins = data.get('data', {}).get('newCoins', [])
                
                if not coins:
                    raise Exception("Không tìm thấy dữ liệu listing")
                
                vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
                now = datetime.now(vn_tz)
                one_week_later = now + timedelta(days=7)
                
                msg = "📅 *LỊCH COIN SẮP LIST (1 TUẦN)*\n\n"
                count = 0
                
                for coin in coins:
                    symbol = coin.get('vcoinName')
                    full_name = coin.get('vcoinNameFull', symbol)
                    timestamp_ms = coin.get('firstOpenTime')
                    
                    if not timestamp_ms:
                        continue
                    
                    # Convert timestamp to datetime - API trả UTC, convert sang VN
                    dt_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
                    dt = dt_utc.astimezone(vn_tz)
                    
                    # Chỉ hiển thị coin list trong 1 tuần tới
                    if now <= dt <= one_week_later:
                        weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
                        weekday = weekdays[dt.weekday()]
                        date_str = dt.strftime("%d/%m/%Y %H:%M")
                        
                        msg += f"🆕 `{symbol}` ({full_name})\n"
                        msg += f"   ⏰ {weekday}, {date_str}\n\n"
                        count += 1
                
                if count == 0:
                    if getattr(update, "effective_message", None):
                        await update.effective_message.reply_text("📅 Chưa có coin nào sắp list trong tuần tới")
                    else:
                        try:
                            await context.bot.send_message(update.effective_chat.id, "📅 Chưa có coin nào sắp list trong tuần tới")
                        except Exception:
                            print("📅 Không thể gửi thông báo timelist")
                else:
                    if getattr(update, "effective_message", None):
                        await update.effective_message.reply_text(msg, parse_mode="Markdown")
                    else:
                        try:
                            await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")
                        except Exception:
                            print("📅 Không thể gửi danh sách timelist")
    
    except Exception as e:
        print(f"❌ Lỗi scrape Futures listing: {e}")
        msg = (
            "❌ Không thể lấy dữ liệu từ MEXC\n\n"
            "Vui lòng xem trực tiếp tại:\n"
            "🔗 https://www.mexc.co/vi-VN/announcements/new-listings"
        )
        if getattr(update, "effective_message", None):
            await update.effective_message.reply_text(msg, parse_mode="Markdown")
        else:
            try:
                await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")
            except Exception:
                print("❌ Timelist: không thể gửi lỗi đến user")


async def coinlist(update, context):
    """Lệnh xem các coin đã list trong 1 tuần - API Calendar"""
    if getattr(update, "effective_message", None):
        await update.effective_message.reply_text("⏳ Đang lấy danh sách coin mới...")
    else:
        try:
            await context.bot.send_message(update.effective_chat.id, "⏳ Đang lấy danh sách coin mới...")
        except Exception:
            print("⏳ Coinlist requested (no message object)")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Gọi API calendar
            timestamp = int(datetime.now().timestamp() * 1000)
            url = f"https://www.mexc.co/api/operation/new_coin_calendar?timestamp={timestamp}"
            
            async with session.get(url, timeout=15) as r:
                if r.status != 200:
                    raise Exception(f"HTTP {r.status}")
                
                data = await r.json()
                coins = data.get('data', {}).get('newCoins', [])
                
                if not coins:
                    raise Exception("Không tìm thấy dữ liệu listing")
                
                vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
                now = datetime.now(vn_tz)
                one_week_ago = now - timedelta(days=7)
                
                msg = "📋 *COIN ĐÃ LIST (1 TUẦN QUA)*\n\n"
                count = 0
                
                for coin in coins:
                    symbol = coin.get('vcoinName')
                    full_name = coin.get('vcoinNameFull', symbol)
                    timestamp_ms = coin.get('firstOpenTime')
                    
                    if not timestamp_ms:
                        continue
                    
                    # Convert timestamp to datetime - API trả UTC, convert sang VN
                    dt_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
                    dt = dt_utc.astimezone(vn_tz)
                    
                    # Chỉ hiển thị coin list trong 1 tuần qua
                    if one_week_ago <= dt <= now:
                        weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
                        weekday = weekdays[dt.weekday()]
                        date_str = dt.strftime("%d/%m/%Y %H:%M")
                        
                        msg += f"✅ `{symbol}` ({full_name})\n"
                        msg += f"   ⏰ {weekday}, {date_str}\n\n"
                        count += 1
                
                if count == 0:
                    if getattr(update, "effective_message", None):
                        await update.effective_message.reply_text("📋 Không có coin nào list trong tuần qua")
                    else:
                        try:
                            await context.bot.send_message(update.effective_chat.id, "📋 Không có coin nào list trong tuần qua")
                        except Exception:
                            print("📋 Không thể gửi coinlist (no message)")
                else:
                    if getattr(update, "effective_message", None):
                        await update.effective_message.reply_text(msg, parse_mode="Markdown")
                    else:
                        try:
                            await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")
                        except Exception:
                            print("📋 Không thể gửi danh sách coinlist")
    
    except Exception as e:
        print(f"❌ Lỗi scrape Futures listing: {e}")
        msg = (
            "❌ Không thể lấy dữ liệu từ MEXC\n\n"
            "Vui lòng xem trực tiếp tại:\n"
            "🔗 https://www.mexc.co/vi-VN/announcements/new-listings"
        )
        if getattr(update, "effective_message", None):
            await update.effective_message.reply_text(msg, parse_mode="Markdown")
        else:
            try:
                await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")
            except Exception:
                print("❌ Coinlist: không thể gửi lỗi đến user")


# ================== JOBS ==================
async def job_scan_pumps_dumps(context):
    """Job chính: Quét TẤT CẢ coin và báo khi có pump/dump"""
    if not SUBSCRIBERS:
        return
    
    print("🔍 Đang quét tất cả coin...")
    
    async with aiohttp.ClientSession() as session:
        # Lấy danh sách tất cả symbols
        global ALL_SYMBOLS
        if not ALL_SYMBOLS:
            ALL_SYMBOLS = await get_all_symbols(session)
            print(f"✅ Tìm thấy {len(ALL_SYMBOLS)} coin")
        
        # Tính movers cho tất cả coin
        movers = await calc_movers(session, "Min1", ALL_SYMBOLS)
    
    if not movers:
        return
    
    # Lọc coin có volume đủ và biến động mạnh
    alerts = []
    for sym, chg, old_price, new_price, vol in movers:
        if vol < MIN_VOL_THRESHOLD:
            continue
        
        # PUMP: tăng >= ngưỡng
        if chg >= PUMP_THRESHOLD:
            msg = fmt_alert(sym, old_price, new_price, chg)
            alerts.append(msg)
            print(f"🚀 PUMP: {sym} {chg:+.2f}%")
        
        # DUMP: giảm >= ngưỡng
        elif chg <= DUMP_THRESHOLD:
            msg = fmt_alert(sym, old_price, new_price, chg)
            alerts.append(msg)
            print(f"� DUMP: {sym} {chg:+.2f}%")
    
    # Gửi alert đến tất cả subscribers
    if alerts:
        # Gom nhóm để tránh spam
        text = "\n\n".join(alerts[:10])  # Chỉ gửi tối đa 10 alert mỗi lần
        if len(alerts) > 10:
            text += f"\n\n... và {len(alerts) - 10} coin khác"
        
        for chat in SUBSCRIBERS:
            try:
                await context.bot.send_message(
                    chat, 
                    text, 
                    parse_mode="Markdown",
                    disable_web_page_preview=True  # Tắt preview link
                )
            except Exception as e:
                print(f"❌ Lỗi gửi tin nhắn: {e}")


async def job_new_listing(context):
    """Job phát hiện coin mới list bằng cách so sánh danh sách"""
    if not SUBSCRIBERS:
        return

    async with aiohttp.ClientSession() as session:
        try:
            symbols = await get_all_symbols(session)
        except:
            return
    
    global KNOWN_SYMBOLS
    
    # Lần đầu chạy: lưu danh sách hiện tại
    if not KNOWN_SYMBOLS:
        KNOWN_SYMBOLS = set(symbols)
        print(f"✅ Đã lưu {len(KNOWN_SYMBOLS)} coin ban đầu")
        return
    
    # So sánh với danh sách cũ
    new_coins = set(symbols) - KNOWN_SYMBOLS
    
    if new_coins:
        alerts = []
        for sym in new_coins:
            KNOWN_SYMBOLS.add(sym)
            coin = sym.replace("_USDT", "")
            alerts.append(f"🆕 *COIN MỚI LIST:* `{coin}`")
            print(f"🆕 NEW LISTING: {sym}")


async def job_ema200_scan(context):
    """Job quét EMA 200 mỗi 5 phút và gửi alert khi có coin mới vào vùng proximity"""
    try:
        async with aiohttp.ClientSession() as session:
            # Detect coins near EMA 200
            results = await detect_ema200_proximity(session, ALL_SYMBOLS)
            
            # Track coins đã alert để tránh spam
            global EMA200_ALERTED
            now = datetime.now()
            
            new_alerts = []  # [(timeframe, symbol, ema200, current_price, distance), ...]
            
            for timeframe in EMA_TIMEFRAMES:
                coins = results[timeframe]
                
                for symbol, ema200, current_price, distance in coins:
                    # Kiểm tra xem đã alert coin này ở timeframe này chưa
                    if symbol not in EMA200_ALERTED:
                        EMA200_ALERTED[symbol] = {}
                    
                    last_alert = EMA200_ALERTED[symbol].get(timeframe)
                    
                    # Chỉ alert nếu:
                    # 1. Chưa từng alert coin này ở timeframe này, HOẶC
                    # 2. Đã qua 30 phút kể từ lần alert cuối
                    should_alert = False
                    if last_alert is None:
                        should_alert = True
                    else:
                        time_since_alert = (now - last_alert).total_seconds()
                        if time_since_alert > 1800:  # 30 phút
                            should_alert = True
                    
                    if should_alert:
                        new_alerts.append((timeframe, symbol, ema200, current_price, distance))
                        EMA200_ALERTED[symbol][timeframe] = now
            
            # Nếu có alert mới, gửi thông báo
            if new_alerts and (CHANNEL_ID or SUBSCRIBERS):
                # Group alerts theo timeframe
                alerts_by_tf = {}
                for tf, symbol, ema200, current_price, distance in new_alerts:
                    if tf not in alerts_by_tf:
                        alerts_by_tf[tf] = []
                    alerts_by_tf[tf].append((symbol, ema200, current_price, distance))
                
                # Format message
                msg_parts = ["🎯 *EMA 200 ALERT*\n"]
                
                for timeframe in EMA_TIMEFRAMES:
                    if timeframe not in alerts_by_tf:
                        continue
                    
                    tf_label = EMA_TIMEFRAME_LABELS[timeframe]
                    msg_parts.append(f"\n🕐 *{tf_label}*")
                    
                    for symbol, ema200, current_price, distance in alerts_by_tf[timeframe]:
                        coin_name = symbol.replace("_USDT", "")
                        
                        # Icon và status
                        if abs(distance) <= 0.3:
                            icon = "🎯"
                            status = "CHẠM"
                        elif distance > 0:
                            icon = "🟢"
                            status = "trên"
                        else:
                            icon = "🔴"
                            status = "dưới"
                        
                        link = f"https://www.mexc.co/futures/{symbol}"
                        msg_parts.append(
                            f"{icon} [{coin_name}]({link}) {status} EMA200 `{distance:+.2f}%`"
                        )
                
                msg = "\n".join(msg_parts)
                
                # Gửi alert
                tasks = []
                
                if CHANNEL_ID:
                    tasks.append(
                        context.bot.send_message(
                            CHANNEL_ID,
                            msg,
                            parse_mode="Markdown",
                            disable_web_page_preview=True
                        )
                    )
                
                for chat in SUBSCRIBERS:
                    # Kiểm tra xem user có bật EMA alerts không
                    ema_enabled = EMA_ALERTS_ENABLED.get(chat, True)  # Mặc định: bật
                    if not ema_enabled:
                        continue
                    
                    tasks.append(
                        context.bot.send_message(
                            chat,
                            msg,
                            parse_mode="Markdown",
                            disable_web_page_preview=True
                        )
                    )

                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    print(f"✅ Sent EMA 200 alerts for {len(new_alerts)} coins")
    
    except Exception as e:
        print(f"❌ Error in job_ema200_scan: {e}")

        
        save_data()  # Lưu danh sách coin mới
        
        # Gửi thông báo
        text = "\n".join(alerts)
        
        # Gửi vào channel nếu có
        if CHANNEL_ID:
            try:
                await context.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown")
            except Exception as e:
                print(f"❌ Lỗi gửi thông báo coin mới vào channel: {e}")
        
        # Gửi cho subscribers cá nhân
        for chat in SUBSCRIBERS:
            try:
                await context.bot.send_message(chat, text, parse_mode="Markdown")
            except Exception as e:
                print(f"❌ Lỗi gửi thông báo coin mới: {e}")


async def job_schedule_restarts(context):
    """Job lên lịch restart bot khi có coin mới list"""
    async with aiohttp.ClientSession() as session:
        try:
            # Gọi API calendar để lấy lịch listing
            timestamp = int(datetime.now().timestamp() * 1000)
            url = f"https://www.mexc.co/api/operation/new_coin_calendar?timestamp={timestamp}"
            
            async with session.get(url, timeout=15) as r:
                if r.status != 200:
                    return
                
                data = await r.json()
                coins = data.get('data', {}).get('newCoins', [])
                
                if not coins:
                    return
                
                vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
                now = datetime.now(vn_tz)
                next_24h = now + timedelta(hours=24)
                
                for coin in coins:
                    timestamp_ms = coin.get('firstOpenTime')
                    if not timestamp_ms:
                        continue
                    
                    # Convert timestamp sang giờ VN
                    dt_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
                    list_time = dt_utc.astimezone(vn_tz)
                    
                    # Chỉ schedule cho coin list trong 24h tới
                    if now <= list_time <= next_24h:
                        # Tránh schedule trùng
                        if timestamp_ms in SCHEDULED_RESTARTS:
                            continue
                        
                        SCHEDULED_RESTARTS.add(timestamp_ms)
                        
                        # Tính thời gian chờ
                        wait_seconds = (list_time - now).total_seconds()
                        wait_seconds_plus_1h = wait_seconds + 3600  # +1 tiếng
                        
                        if wait_seconds > 0:
                            coin_name = coin.get('vcoinName', 'Unknown')
                            print(f"📅 Đã lên lịch restart cho {coin_name}:")
                            print(f"   - Restart 1: {list_time.strftime('%d/%m %H:%M')} ({wait_seconds/60:.0f} phút)")
                            print(f"   - Restart 2: {(list_time + timedelta(hours=1)).strftime('%d/%m %H:%M')} (sau 1h)")
                            
                            # Schedule restart lần 1 (đúng giờ list)
                            context.job_queue.run_once(
                                restart_bot,
                                wait_seconds,
                                data={"reason": f"Coin mới list: {coin_name}"}
                            )
                            
                            # Schedule restart lần 2 (sau 1 tiếng)
                            context.job_queue.run_once(
                                restart_bot,
                                wait_seconds_plus_1h,
                                data={"reason": f"Restart lần 2 sau khi {coin_name} list"}
                            )
        
        except Exception as e:
            print(f"❌ Lỗi schedule restart: {e}")


async def restart_bot(context):
    """Restart bot để load coin mới"""
    reason = context.job.data.get("reason", "Scheduled restart")
    
    print(f"🔄 BOT ĐANG RESTART: {reason}")
    
    # Gửi thông báo cho channel và users
    msg = f"🔄 *Bot đang khởi động lại*\n\n_{reason}_"
    
    # Gửi vào channel
    if CHANNEL_ID:
        try:
            await context.bot.send_message(CHANNEL_ID, msg, parse_mode="Markdown")
        except:
            pass
    
    # Gửi cho subscribers
    for chat in SUBSCRIBERS:
        try:
            await context.bot.send_message(chat, msg, parse_mode="Markdown")
        except:
            pass
    
    # Đợi 2 giây để gửi hết tin nhắn
    await asyncio.sleep(2)
    
    # Restart bot bằng cách stop application
    print("🔄 Stopping application for restart...")
    await context.application.stop()
    await context.application.shutdown()


# ================== MAIN ==================
async def post_init(app):
    """Set bot commands menu"""
    from telegram import BotCommand
    
    # Kiểm tra bot token hoạt động (retry với delay dài hơn)
    for conn_attempt in range(5):
        try:
            bot_info = await app.bot.get_me()
            print(f"✅ Bot đã kết nối: @{bot_info.username} (ID: {bot_info.id})")
            break
        except Exception as e:
            print(f"⚠️ Lỗi kết nối bot (attempt {conn_attempt+1}/5): {e}")
            if conn_attempt < 4:
                print(f"🔄 Thử lại sau 10 giây....")
                await asyncio.sleep(10)
            else:
                print("❌ KHÔNG THỂ KẾT NỐI BOT sau 5 lần thử!")
                print("❌ Kiểm tra lại BOT_TOKEN trên Railway!")
                return
    
    commands = [
        BotCommand("start", "Khởi động bot và xem hướng dẫn"),
        BotCommand("subscribe", "Bật thông báo pump/dump tự động"),
        BotCommand("unsubscribe", "Tắt thông báo tự động"),
        BotCommand("mode1", "Báo tất cả (3-5% + ≥10%)"),
        BotCommand("mode2", "Chỉ báo trung bình (3-5%)"),
        BotCommand("mode3", "Chỉ báo cực mạnh (≥10%)"),
        BotCommand("mute", "Tắt thông báo coin (ví dụ: /mute XION)"),
        BotCommand("unmute", "Bật lại thông báo coin"),
        BotCommand("mutelist", "Xem danh sách coin đã mute"),
        BotCommand("ema200", "Xem coins gần chạm EMA 200"),
        BotCommand("timelist", "Lịch coin sắp list trong 1 tuần"),
        BotCommand("coinlist", "Coin đã list trong 1 tuần qua"),
    ]

    
    # Retry logic cho set_my_commands (tránh timeout khi khởi động)
    for attempt in range(3):
        try:
            await app.bot.set_my_commands(commands)
            print("✅ Đã thiết lập menu lệnh bot")
            break
        except Exception as e:
            print(f"⚠️ Lỗi set commands (attempt {attempt+1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(5)  # Tăng từ 2s lên 5s
            else:
                print("⚠️ Skip set commands, bot vẫn hoạt động bình thường")


def main():
    # Tăng timeout cho Telegram API (Railway có thể chậm)
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=60.0,  # Tăng lên 60s
        read_timeout=60.0,     # Tăng lên 60s
        write_timeout=60.0,
        pool_timeout=60.0
    )
    
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("mode1", mode1))
    app.add_handler(CommandHandler("mode2", mode2))
    app.add_handler(CommandHandler("mode3", mode3))
    app.add_handler(CommandHandler("pumpdump_on", pumpdump_on))
    app.add_handler(CommandHandler("pumpdump_off", pumpdump_off))
    app.add_handler(CommandHandler("ema_on", ema_on))
    app.add_handler(CommandHandler("ema_off", ema_off))
    app.add_handler(CommandHandler("mute", mute_coin))
    app.add_handler(CommandHandler("unmute", unmute_coin))

    app.add_handler(CommandHandler("mutelist", mutelist))
    app.add_handler(CommandHandler("ema200", ema200))
    app.add_handler(CommandHandler("timelist", timelist))
    app.add_handler(CommandHandler("coinlist", coinlist))


    jq = app.job_queue
    
    # Lấy danh sách symbols và khởi động WebSocket
    async def init_websocket(context):
        global ALL_SYMBOLS
        
        # Tải dữ liệu đã lưu (subscribers, modes, muted coins)
        load_data()
        
        async with aiohttp.ClientSession() as session:
            ALL_SYMBOLS = await get_all_symbols(session)
            print(f"✅ Tìm thấy {len(ALL_SYMBOLS)} coin")
        
        # Khởi động WebSocket stream
        asyncio.create_task(websocket_stream(context))
    
    # Chạy init ngay khi khởi động
    jq.run_once(init_websocket, 5)
    
    # Backup reset base prices mỗi 5 phút (dynamic reset là chính)
    jq.run_repeating(reset_base_prices, 300, first=305)
    
    # Kiểm tra coin mới mỗi 5 phút
    jq.run_repeating(job_new_listing, 300, first=30)
    
    # Quét EMA 200 mỗi 5 phút
    jq.run_repeating(job_ema200_scan, 300, first=90)
    
    # Schedule restart cho coin mới list (chạy mỗi 30 phút để cập nhật lịch)
    jq.run_repeating(job_schedule_restarts, 1800, first=60)


    print("🔥 Bot quét MEXC Futures...")
    print(f"📊 Ngưỡng pump: >= {PUMP_THRESHOLD}%")
    print(f"📊 Ngưỡng dump: <= {DUMP_THRESHOLD}%")
    print(f"💰 Volume tối thiểu: {MIN_VOL_THRESHOLD:,}")
    print("🌐 WebSocket: Realtime price streaming")
    print("📅 Auto-restart khi có coin mới list")
    
    # Chạy với graceful shutdown và auto-restart
    while True:
        try:
            print("🚀 Starting bot...")
            app.run_polling(drop_pending_updates=True)
            # Nếu run_polling kết thúc bình thường (restart) → restart lại
            print("🔄 Bot stopped, restarting in 3 seconds...")
            import time
            time.sleep(3)
        except KeyboardInterrupt:
            print("🛑 Bot đang tắt...")
            break
        except Exception as e:
            print(f"❌ Bot error: {e}")
            print("🔄 Restarting in 5 seconds...")
            import time
            time.sleep(5)


if __name__ == "__main__":
    main()
