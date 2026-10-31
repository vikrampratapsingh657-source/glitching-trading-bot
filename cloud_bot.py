import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# Telegram Settings
TELEGRAM_BOT_TOKEN = "8817947998:AAHVCl8Hh2y4qshr5mLFk1at5q2zJikLOJs"
TELEGRAM_CHAT_ID = "7448627639"

ASSETS = [
    {"name": "Bitcoin", "ticker": "BTC-USD"},
    {"name": "Ethereum", "ticker": "ETH-USD"},
    {"name": "Solana", "ticker": "SOL-USD"},
    {"name": "Gold", "ticker": "GC=F"},
    {"name": "EUR/USD", "ticker": "EURUSD=X"}
]

FIB_RATIO = 0.146
T1_RR = 1.5
T2_RR = 3.0
TIMEFRAME = "5m"

def send_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

def get_market_data(ticker):
    try:
        df = yf.download(ticker, period="1d", interval=TIMEFRAME, progress=False)
        if df.empty or len(df) < 15:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None

def analyze_strategy(df):
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    volumes = df['Volume'].values

    sw_high = float(np.max(highs[-15:]))
    sw_low = float(np.min(lows[-15:]))
    diff = sw_high - sw_low

    if diff <= 0:
        return None, None, None, None, None, None

    live_price = float(closes[-1])
    is_uptrend = live_price > float(np.mean(closes[-10:]))
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

    return live_price, fib_level, sw_high, sw_low, is_uptrend, buyer_score, seller_score

print("24/7 Glitching Trading Bot Started...")
send_alert("🚀 *24/7 Trading Bot Started on Cloud*\nMonitoring BTC, ETH, SOL, Gold, EUR/USD...")

last_signals = {}

while True:
    try:
        for item in ASSETS:
            ticker = item["ticker"]
            name = item["name"]

            df = get_market_data(ticker)
            if df is None:
                continue

            res = analyze_strategy(df)
            if res[0] is None:
                continue

            live_price, fib_level, sw_high, sw_low, is_uptrend, buyer_score, seller_score = res
            now_ts = time.time()
            last_ts = last_signals.get(ticker, 0)

            if now_ts - last_ts > 900:
                # Long Setup
                if is_uptrend and live_price >= fib_level and buyer_score >= 55:
                    sl = sw_low
                    r_dist = live_price - sl
                    if r_dist > 0:
                        t1 = live_price + (T1_RR * r_dist)
                        t2 = live_price + (T2_RR * r_dist)
                        msg = (
                            f"🟢 *LONG SIGNAL DETECTED*\n"
                            f"📌 *Asset:* {name} ({ticker})\n"
                            f"💵 *Entry:* ${live_price:.2f}\n"
                            f"🛑 *Stop-Loss:* ${sl:.2f}\n"
                            f"🎯 *Target 1 (1:1.5):* ${t1:.2f}\n"
                            f"🎯 *Target 2 (1:3.0):* ${t2:.2f}\n"
                            f"📊 *Buyers Pressure:* {buyer_score:.1f}%"
                        )
                        send_alert(msg)
                        last_signals[ticker] = now_ts

                # Short Setup
                elif not is_uptrend and live_price <= fib_level and seller_score >= 55:
                    sl = sw_high
                    r_dist = sl - live_price
                    if r_dist > 0:
                        t1 = live_price - (T1_RR * r_dist)
                        t2 = live_price - (T2_RR * r_dist)
                        msg = (
                            f"🔴 *SHORT SIGNAL DETECTED*\n"
                            f"📌 *Asset:* {name} ({ticker})\n"
                            f"💵 *Entry:* ${live_price:.2f}\n"
                            f"🛑 *Stop-Loss:* ${sl:.2f}\n"
                            f"🎯 *Target 1 (1:1.5):* ${t1:.2f}\n"
                            f"🎯 *Target 2 (1:3.0):* ${t2:.2f}\n"
                            f"📊 *Sellers Pressure:* {seller_score:.1f}%"
                        )
                        send_alert(msg)
                        last_signals[ticker] = now_ts

            time.sleep(1)

        time.sleep(15)

    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(10)
