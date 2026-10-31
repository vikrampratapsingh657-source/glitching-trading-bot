import os
import time
import threading
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from http.server import HTTPServer, BaseHTTPRequestHandler

# Telegram Credentials
TELEGRAM_BOT_TOKEN = "8817947998:AAHVCl8Hh2y4qshr5mLFk1at5q2zJikLOJs"
TELEGRAM_CHAT_ID = "7448627639"

ASSETS = [
    {"name": "Bitcoin", "ticker": "BTC-USD"},
    {"name": "Ethereum", "ticker": "ETH-USD"},
    {"name": "Solana", "ticker": "SOL-USD"},
    {"name": "Gold (Comex)", "ticker": "GC=F"},
    {"name": "EUR/USD", "ticker": "EURUSD=X"}
]

# 1-Min, 5-Min, 15-Min Scanners
TIMEFRAMES = ["1m", "5m", "15m"]

FIB_RATIO = 0.146
T1_RR = 1.5
T2_RR = 3.0

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Glitching Trading Engine 24/7 Running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

def send_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

def get_market_data(ticker, tf):
    try:
        period = "1d" if tf in ["1m", "5m"] else "5d"
        df = yf.download(ticker, period=period, interval=tf, progress=False)
        if df.empty or len(df) < 20:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def analyze_strategy(df):
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    volumes = df['Volume'].values

    sw_high = float(np.max(highs[-20:]))
    sw_low = float(np.min(lows[-20:]))
    diff = sw_high - sw_low

    if diff <= 0:
        return None

    live_price = float(closes[-1])
    ema_20 = float(pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1])
    is_uptrend = live_price > ema_20

    rsi_series = calculate_rsi(pd.Series(closes))
    rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0

    fib_level = (sw_low + (diff * FIB_RATIO)) if is_uptrend else (sw_high - (diff * FIB_RATIO))

    bull_vol, bear_vol = 0.0, 0.0
    for i in range(-5, 0):
        c_open = float(df['Open'].iloc[i])
        c_close = float(closes[i])
        vol = float(volumes[i]) if volumes[i] > 0 else 1.0
        if c_close >= c_open:
            bull_vol += vol
        else:
            bear_vol += vol

    tot_vol = bull_vol + bear_vol
    buyer_score = (bull_vol / tot_vol) * 100 if tot_vol > 0 else 50.0
    seller_score = (bear_vol / tot_vol) * 100 if tot_vol > 0 else 50.0

    return {
        "live_price": live_price,
        "fib_level": fib_level,
        "sw_high": sw_high,
        "sw_low": sw_low,
        "is_uptrend": is_uptrend,
        "buyer_score": buyer_score,
        "seller_score": seller_score,
        "rsi": rsi
    }

def trading_bot_loop():
    print("Multi-TF Trading Engine Active...")
    send_alert("⚡ *Trading Bot Active*\nScanning 1m, 5m, 15m (Alerts with Reversal Chance %)")
    last_signals = {}

    while True:
        try:
            for item in ASSETS:
                ticker = item["ticker"]
                name = item["name"]

                for tf in TIMEFRAMES:
                    df = get_market_data(ticker, tf)
                    if df is None:
                        continue

                    data = analyze_strategy(df)
                    if data is None:
                        continue

                    live_price = data["live_price"]
                    fib_level = data["fib_level"]
                    sw_high = data["sw_high"]
                    sw_low = data["sw_low"]
                    is_uptrend = data["is_uptrend"]
                    buyer_score = data["buyer_score"]
                    seller_score = data["seller_score"]
                    rsi = data["rsi"]

                    sig_key = f"{ticker}_{tf}"
                    now_ts = time.time()
                    last_ts = last_signals.get(sig_key, 0)

                    # Cooldowns: 1m = 3 min, 5m = 8 min, 15m = 20 min
                    cooldown = 180 if tf == "1m" else (480 if tf == "5m" else 1200)

                    if now_ts - last_ts > cooldown:
                        if tf == "1m":
                            tf_name = "⚡ 1-Min"
                        elif tf == "5m":
                            tf_name = "🎯 5-Min"
                        else:
                            tf_name = "📊 15-Min"

                        # BUY Setup
                        if is_uptrend and live_price >= fib_level and buyer_score >= 55:
                            sl = sw_low
                            r_dist = live_price - sl
                            if r_dist > 0:
                                t1 = live_price + (T1_RR * r_dist)
                                t2 = live_price + (T2_RR * r_dist)

                                # सिर्फ़ रिवर्सल होने के चांसेस कैलकुलेट करना
                                reversal_chance = int(np.clip((rsi - 45) * 1.3 + (seller_score * 0.3), 15, 75))

                                msg = (
                                    f"🟢 *BUY SIGNAL*\n"
                                    f"⏱ *Timeframe:* `{tf_name}`\n"
                                    f"📌 *Asset:* {name} ({ticker})\n"
                                    f"💵 *Entry:* ${live_price:.2f}\n"
                                    f"🛑 *Stop-Loss:* ${sl:.2f}\n"
                                    f"🎯 *Target 1 (1:1.5):* ${t1:.2f}\n"
                                    f"🎯 *Target 2 (1:3.0):* ${t2:.2f}\n"
                                    f"━━━━━━━━━━━━━━━━━━\n"
                                    f"⚠️ *रिवर्सल होने के चांस:* `{reversal_chance}%` (नियर ${sw_high:.2f})"
                                )
                                send_alert(msg)
                                last_signals[sig_key] = now_ts

                        # SELL Setup
                        elif not is_uptrend and live_price <= fib_level and seller_score >= 55:
                            sl = sw_high
                            r_dist = sl - live_price
                            if r_dist > 0:
                                t1 = live_price - (T1_RR * r_dist)
                                t2 = live_price - (T2_RR * r_dist)

                                # सिर्फ़ रिवर्सल होने के चांसेस कैलकुलेट करना
                                reversal_chance = int(np.clip((55 - rsi) * 1.3 + (buyer_score * 0.3), 15, 75))

                                msg = (
                                    f"🔴 *SELL SIGNAL*\n"
                                    f"⏱ *Timeframe:* `{tf_name}`\n"
                                    f"📌 *Asset:* {name} ({ticker})\n"
                                    f"💵 *Entry:* ${live_price:.2f}\n"
                                    f"🛑 *Stop-Loss:* ${sl:.2f}\n"
                                    f"🎯 *Target 1 (1:1.5):* ${t1:.2f}\n"
                                    f"🎯 *Target 2 (1:3.0):* ${t2:.2f}\n"
                                    f"━━━━━━━━━━━━━━━━━━\n"
                                    f"⚠️ *रिवर्सल होने के चांस:* `{reversal_chance}%` (नियर ${sw_low:.2f})"
                                )
                                send_alert(msg)
                                last_signals[sig_key] = now_ts

                    time.sleep(1)

            time.sleep(15)

        except Exception as e:
            print(f"Engine Loop Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    t = threading.Thread(target=run_web_server, daemon=True)
    t.start()
    trading_bot_loop()
