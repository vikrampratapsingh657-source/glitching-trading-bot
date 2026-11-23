import os
import time
import threading
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from flask import Flask, request

# ==============================================================================
# 1. TELEGRAM & RENDER CONFIGURATION
# ==============================================================================
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8817947998:AAHVC18Hh2y4qshr5")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7448627639")
IST = pytz.timezone("Asia/Kolkata")

SYMBOLS = {
    "GOLD (XAUUSD)": "GC=F",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "AUDUSD": "AUDUSD=X",
    "USDJPY": "USDJPY=X",
    "BTCUSD": "BTC-USD",
    "RELIANCE (NSE)": "RELIANCE.NS"
}

INITIAL_CAPITAL = 1000.0
RISK_PER_TRADE  = 0.005  # 0.5% ($5 per trade)
MAX_DAILY_LOSS  = 2      # Max 2 SL per day

active_trades = {}
last_signal_candle = {}
daily_sl_count = {}

# ==============================================================================
# 2. RENDER WEB SERVER + 0-SECOND TRADINGVIEW WEBHOOK RECEIVER
# ==============================================================================
app = Flask(__name__)

@app.route("/", methods=["GET"])
def health_check():
    return f"🎯 0-Sec Live Ultra-Sniper Bot Running | Active Trades: {len(active_trades)}", 200

@app.route("/webhook", methods=["POST"])
def tradingview_webhook():
    data = request.get_data(as_text=True)
    now_str = datetime.now(IST).strftime("%I:%M:%S %p")
    send_telegram(
        f"⚡ <b>0-SEC LIVE TRADINGVIEW ALERT!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{data}\n"
        f"⏰ <b>IST Time:</b> {now_str}"
    )
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ==============================================================================
# 3. TELEGRAM MESSENGER
# ==============================================================================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

# ==============================================================================
# 4. INDICATORS & 4-IN-1 ULTRA-SNIPER SIGNAL ENGINE
# ==============================================================================
def prepare_data(ticker):
    df = yf.download(ticker, period="10d", interval="15m", progress=False)
    if df.empty or len(df) < 50:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_convert(IST) if df.index.tz is not None else df.index.tz_localize("UTC").tz_convert(IST)

    for p in [9, 15, 50, 200]:
        df[f"EMA_{p}"] = df["Close"].ewm(span=p, adjust=False).mean()

    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/7, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/7, adjust=False).mean()
    df["RSI_7"] = 100 - (100 / (1 + (gain / loss.replace(0, np.nan))))

    tr = np.maximum(df["High"] - df["Low"], np.maximum(abs(df["High"] - df["Close"].shift(1)), abs(df["Low"] - df["Close"].shift(1))))
    df["ATR"] = tr.rolling(14).mean()
    up_m = df["High"] - df["High"].shift(1)
    dn_m = df["Low"].shift(1) - df["Low"]
    p_dm = np.where((up_m > dn_m) & (up_m > 0), up_m, 0.0)
    m_dm = np.where((dn_m > up_m) & (dn_m > 0), dn_m, 0.0)
    p_di = 100 * pd.Series(p_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / df["ATR"]
    m_di = 100 * pd.Series(m_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / df["ATR"]
    dx   = 100 * abs(p_di - m_di) / (p_di + m_di).replace(0, np.nan)
    df["ADX"] = dx.ewm(alpha=1/14, adjust=False).mean()

    df["BB30_Mid"] = df["Close"].rolling(30).mean()
    df["BB30_Std"] = df["Close"].rolling(30).std()
    df["BB30_Up"]  = df["BB30_Mid"] + 2 * df["BB30_Std"]
    df["BB30_Lo"]  = df["BB30_Mid"] - 2 * df["BB30_Std"]
    df["BB30_W"]   = (df["BB30_Up"] - df["BB30_Lo"]) / df["BB30_Mid"]

    df["Swing_High"] = df["High"].rolling(30).max().shift(1)
    df["Swing_Low"]  = df["Low"].rolling(30).min().shift(1)
    return df.dropna()

def evaluate_sniper_setup(df):
    r, p1, p2, p3 = df.iloc[-2], df.iloc[-3], df.iloc[-4], df.iloc[-5]
    c_time = str(df.index[-2])
    atr = r["ATR"]
    if atr <= 0 or np.isnan(atr):
        return None

    c, h, l, o = r["Close"], r["High"], r["Low"], r["Open"]
    c_rng = h - l
    if c_rng <= 0 or (abs(c - o) / c_rng) < 0.50:
        return None

    rng = r["Swing_High"] - r["Swing_Low"]
    if rng <= 0:
        return None

    hr, mn = df.index[-2].hour, df.index[-2].minute

    # PRIORITY 1 (80.0% WR): 0.786 Deep Fib + 9/15 EMA + 200 EMA
    f786_b = r["Swing_High"] - 0.786 * rng
    f786_s = r["Swing_Low"]  + 0.786 * rng
    if c > r["EMA_200"] and r["EMA_9"] > r["EMA_15"] and l <= f786_b and c > f786_b and c > o and r["RSI_7"] < 45:
        sl = r["Swing_Low"] - 0.3 * atr
        return {"strategy": "P1: 0.786 Fib + 9/15 EMA", "wr": "80.0%", "dir": "BUY", "entry": c, "sl": sl, "tp": c + 1.8*(c - sl), "rr": 1.8, "candle_time": c_time}
    if c < r["EMA_200"] and r["EMA_9"] < r["EMA_15"] and h >= f786_s and c < f786_s and c < o and r["RSI_7"] > 55:
        sl = r["Swing_High"] + 0.3 * atr
        return {"strategy": "P1: 0.786 Fib + 9/15 EMA", "wr": "80.0%", "dir": "SELL", "entry": c, "sl": sl, "tp": c - 1.8*(sl - c), "rr": 1.8, "candle_time": c_time}

    # PRIORITY 2 (61.1% WR): Golden 3-Candle Exhaustion Sweep + RSI(7)
    if p1["Close"] < p1["Open"] and p2["Close"] < p2["Open"] and p3["Close"] < p3["Open"] and l < r["Swing_Low"] and c > o and r["RSI_7"] < 25:
        sl = l - 0.3 * atr
        return {"strategy": "P2: Golden 3-Candle Sweep", "wr": "61.1%", "dir": "BUY", "entry": c, "sl": sl, "tp": c + 1.8*(c - sl), "rr": 1.8, "candle_time": c_time}
    if p1["Close"] > p1["Open"] and p2["Close"] > p2["Open"] and p3["Close"] > p3["Open"] and h > r["Swing_High"] and c < o and r["RSI_7"] > 75:
        sl = h + 0.3 * atr
        return {"strategy": "P2: Golden 3-Candle Sweep", "wr": "61.1%", "dir": "SELL", "entry": c, "sl": sl, "tp": c - 1.8*(sl - c), "rr": 1.8, "candle_time": c_time}

    # PRIORITY 3 (42.3% WR): BB(30) Squeeze Expansion + ADX > 22
    if p1["BB30_W"] < df["BB30_W"].iloc[-22:-2].quantile(0.15) and r["ADX"] > 22:
        if c > r["BB30_Up"] and c > r["EMA_200"]:
            return {"strategy": "P3: BB(30) Squeeze Breakout", "wr": "42.3%", "dir": "BUY", "entry": c, "sl": r["BB30_Mid"], "tp": c + 1.8*(c - r["BB30_Mid"]), "rr": 1.8, "candle_time": c_time}
        if c < r["BB30_Lo"] and c < r["EMA_200"]:
            return {"strategy": "P3: BB(30) Squeeze Breakout", "wr": "42.3%", "dir": "SELL", "entry": c, "sl": r["BB30_Mid"], "tp": c - 1.8*(r["BB30_Mid"] - c), "rr": 1.8, "candle_time": c_time}

    # PRIORITY 4 (41.4% WR): 05:30 IST Morning Fib Breakout (05:45 candle)
    if hr == 5 and mn == 45 and r["ADX"] > 20:
        cr = p1["High"] - p1["Low"]
        if cr > 0 and c > p1["High"] and c > r["EMA_50"]:
            sl = p1["Low"] + 0.25 * cr
            return {"strategy": "P4: 05:30 IST Fib Breakout", "wr": "41.4%", "dir": "BUY", "entry": c, "sl": sl, "tp": c + 2.2*(c - sl), "rr": 2.2, "candle_time": c_time}
        if cr > 0 and c < p1["Low"] and c < r["EMA_50"]:
            sl = p1["High"] - 0.25 * cr
            return {"strategy": "P4: 05:30 IST Fib Breakout", "wr": "41.4%", "dir": "SELL", "entry": c, "sl": sl, "tp": c - 2.2*(sl - c), "rr": 2.2, "candle_time": c_time}

    return None

# ==============================================================================
# 5. FAST 15-SEC LIVE SCANNER & TARGET/SL HIT MONITOR
# ==============================================================================
def scanner_loop():
    send_telegram(
        "🚀 <b>0-Sec Webhook + Fast Sniper Bot Live!</b>\n"
        "• Mode: TradingView Webhook Ready + 15-Sec Scanner\n"
        "• Prop Shield: 0.5% Risk/Trade | Max 2 SL/Day"
    )

    while True:
        now_ist = datetime.now(IST)
        today_str = now_ist.strftime("%Y-%m-%d")

        for m_name, ticker in SYMBOLS.items():
            try:
                df = prepare_data(ticker)
                if df is None:
                    continue

                curr_high = float(df.iloc[-1]["High"])
                curr_low  = float(df.iloc[-1]["Low"])

                if m_name in active_trades:
                    tr = active_trades[m_name]
                    dec = 2 if "GOLD" in m_name or "BTC" in m_name or "RELIANCE" in m_name else (3 if "JPY" in m_name else 5)

                    if tr["dir"] == "BUY":
                        if curr_high >= tr["tp"]:
                            profit_usd = round(INITIAL_CAPITAL * RISK_PER_TRADE * tr["rr"], 2)
                            send_telegram(
                                f"✅ <b>TARGET HIT SAFELY! (+{tr['rr']}R | +${profit_usd})</b>\n"
                                f"📌 <b>Pair:</b> {m_name}\n"
                                f"🧠 <b>Strategy:</b> {tr['strategy']}\n"
                                f"🎯 <b>Target Price:</b> {round(tr['tp'], dec)}"
                            )
                            del active_trades[m_name]
                        elif curr_low <= tr["sl"]:
                            loss_usd = round(INITIAL_CAPITAL * RISK_PER_TRADE, 2)
                            daily_sl_count[today_str] = daily_sl_count.get(today_str, 0) + 1
                            send_telegram(
                                f"🛑 <b>STOP LOSS HIT (-1.0R | -${loss_usd})</b>\n"
                                f"📌 <b>Pair:</b> {m_name}\n"
                                f"🛡️ <b>Daily SL:</b> {daily_sl_count[today_str]}/{MAX_DAILY_LOSS}"
                            )
                            del active_trades[m_name]

                    elif tr["dir"] == "SELL":
                        if curr_low <= tr["tp"]:
                            profit_usd = round(INITIAL_CAPITAL * RISK_PER_TRADE * tr["rr"], 2)
                            send_telegram(
                                f"✅ <b>TARGET HIT SAFELY! (+{tr['rr']}R | +${profit_usd})</b>\n"
                                f"📌 <b>Pair:</b> {m_name}\n"
                                f"🧠 <b>Strategy:</b> {tr['strategy']}\n"
                                f"🎯 <b>Target Price:</b> {round(tr['tp'], dec)}"
                            )
                            del active_trades[m_name]
                        elif curr_high >= tr["sl"]:
                            loss_usd = round(INITIAL_CAPITAL * RISK_PER_TRADE, 2)
                            daily_sl_count[today_str] = daily_sl_count.get(today_str, 0) + 1
                            send_telegram(
                                f"🛑 <b>STOP LOSS HIT (-1.0R | -${loss_usd})</b>\n"
                                f"📌 <b>Pair:</b> {m_name}\n"
                                f"🛡️ <b>Daily SL:</b> {daily_sl_count[today_str]}/{MAX_DAILY_LOSS}"
                            )
                            del active_trades[m_name]

                if m_name not in active_trades:
                    if daily_sl_count.get(today_str, 0) >= MAX_DAILY_LOSS:
                        continue

                    sig = evaluate_sniper_setup(df)
                    if sig and last_signal_candle.get(m_name) != sig["candle_time"]:
                        last_signal_candle[m_name] = sig["candle_time"]
                        active_trades[m_name] = sig

                        dec = 2 if "GOLD" in m_name or "BTC" in m_name or "RELIANCE" in m_name else (3 if "JPY" in m_name else 5)
                        emoji = "🟢" if sig["dir"] == "BUY" else "🔴"

                        send_telegram(
                            f"{emoji} <b>NEW SNIPER TRADE ACTIVE!</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"📊 <b>Market:</b> {m_name} (15m)\n"
                            f"🧠 <b>Strategy:</b> {sig['strategy']} (WR: {sig['wr']})\n"
                            f"⚡ <b>Action:</b> {sig['dir']} NOW\n"
                            f"🚪 <b>Entry:</b> <code>{round(sig['entry'], dec)}</code>\n"
                            f"🛑 <b>Stop Loss:</b> <code>{round(sig['sl'], dec)}</code>\n"
                            f"🎯 <b>Target TP:</b> <code>{round(sig['tp'], dec)}</code>\n"
                            f"⏰ <b>IST Time:</b> {now_ist.strftime('%I:%M %p')}"
                        )

            except Exception as e:
                print(f"Error scanning {m_name}: {e}")

        time.sleep(15) # Fast 15-second scan loop

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    scanner_loop()
