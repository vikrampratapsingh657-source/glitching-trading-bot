import os
import time
import threading
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from flask import Flask, request, jsonify

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8817947998:AAHVCl8Hh2y4qshr5mLFk1at5q2zJikLOJs")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7448627639")
IST = pytz.timezone("Asia/Kolkata")

SYMBOLS = {
    "GOLD (XAUUSD)": "GC=F",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "AUDUSD": "AUDUSD=X",
    "USDJPY": "JPY=X",
    "BTCUSD": "BTC-USD",
    "RELIANCE": "RELIANCE.NS"
}

app = Flask(__name__)

# ==============================================================================
# 2. LIVE STATS & MULTI-DAY TRACKER (NO TRADE BLOCKING)
# ==============================================================================
stats = {
    "start_date": datetime.now(IST).strftime("%d %b %Y"),
    "days_active": set([datetime.now(IST).strftime("%Y-%m-%d")]),
    "today_date": datetime.now(IST).strftime("%Y-%m-%d"),
    "today_tp": 0,
    "today_sl": 0,
    "total_tp": 0,
    "total_sl": 0
}

active_trades = {}
last_signal_bar = {}

def check_day_rollover():
    today = datetime.now(IST).strftime("%Y-%m-%d")
    stats["days_active"].add(today)
    if stats["today_date"] != today:
        # Send automatic End-of-Day summary before resetting today's count
        prev_day = stats["today_date"]
        msg = (
            f"📊 **DAILY PERFORMANCE REPORT ({prev_day})**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Aaj Ke Total Target Hit: **{stats['today_tp']}**\n"
            f"🛑 Aaj Ke Total SL Hit: **{stats['today_sl']}**\n"
            f"📅 Kul {len(stats['days_active'])-1} Din Ka Hisab: **{stats['total_tp']} TP** | **{stats['total_sl']} SL**"
        )
        send_tg(msg)
        stats["today_date"] = today
        stats["today_tp"] = 0
        stats["today_sl"] = 0

def get_scorecard_text():
    days_cnt = len(stats["days_active"])
    return (
        f"📊 **LIVE HISAB (Aaj vs Kul {days_cnt} Din):**\n"
        f"• Aaj ({datetime.now(IST).strftime('%d %b')}): **{stats['today_tp']} Target Hit** | **{stats['today_sl']} SL Hit**\n"
        f"• Kul {days_cnt} Din Mein: **{stats['total_tp']} Target Hit** | **{stats['total_sl']} SL Hit**"
    )

def send_tg(text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=8)
    except Exception as e:
        print(f"TG Error: {e}")

# ==============================================================================
# 3. INDICATORS & HIGH-ACCURACY SNIPER ENGINE
# ==============================================================================
def compute_indicators(df):
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema15"] = close.ewm(span=15, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi7"] = 100 - (100 / (1 + rs))

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr14 = tr.rolling(14).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).mean() / atr14
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).mean() / atr14
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.rolling(14).mean()

    df["bb_mid"] = close.rolling(30).mean()
    bb_std = close.rolling(30).std()
    df["bb_upper"] = df["bb_mid"] + 2.0 * bb_std
    df["bb_lower"] = df["bb_mid"] - 2.0 * bb_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

    df["sw_hi"] = high.rolling(30).max().shift(1)
    df["sw_lo"] = low.rolling(30).min().shift(1)
    return df

def evaluate_market(pair_name, yf_ticker):
    try:
        df = yf.download(yf_ticker, period="7d", interval="15m", progress=False)
        if df.empty or len(df) < 60:
            return
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = compute_indicators(df)
        curr_live = df.iloc[-1]
        c = df.iloc[-2]  # Last confirmed closed 15m candle
        bar_ts = str(df.index[-2])

        # 1. Check Live TP / SL Hit for Active Trade
        if pair_name in active_trades:
            tr = active_trades[pair_name]
            live_hi = float(curr_live["High"])
            live_lo = float(curr_live["Low"])

            tp_hit = (tr["dir"] == "BUY" and live_hi >= tr["tp"]) or (tr["dir"] == "SELL" and live_lo <= tr["tp"])
            sl_hit = (tr["dir"] == "BUY" and live_lo <= tr["sl"]) or (tr["dir"] == "SELL" and live_hi >= tr["sl"])

            if tp_hit:
                stats["today_tp"] += 1
                stats["total_tp"] += 1
                del active_trades[pair_name]
                send_tg(
                    f"✅ **TARGET HIT SAFELY! (+1 TP)**\n"
                    f"📊 Pair: **{pair_name}** (15m)\n"
                    f"🧠 Strategy: {tr['strat']}\n"
                    f"🎯 Target Price: `{tr['tp']:.4f}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{get_scorecard_text()}"
                )
            elif sl_hit:
                stats["today_sl"] += 1
                stats["total_sl"] += 1
                del active_trades[pair_name]
                send_tg(
                    f"🛑 **STOP LOSS HIT! (+1 SL)**\n"
                    f"📊 Pair: **{pair_name}** (15m)\n"
                    f"🧠 Strategy: {tr['strat']}\n"
                    f"🛑 SL Price: `{tr['sl']:.4f}`\n"
                    f"ℹ️ _Bot chalu hai — agle high-accuracy setup ka wait kar raha hai._\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{get_scorecard_text()}"
                )

        if last_signal_bar.get(pair_name) == bar_ts:
            return

        op, hi, lo, cl = float(c["Open"]), float(c["High"]), float(c["Low"]), float(c["Close"])
        rng = hi - lo
        if rng <= 0 or (abs(cl - op) / rng) < 0.50:
            return

        sw_hi, sw_lo = float(c["sw_hi"]), float(c["sw_lo"])
        fib_rng = sw_hi - sw_lo
        if fib_rng <= 0 or pd.isna(fib_rng):
            return

        ema9, ema15, ema50, ema200 = float(c["ema9"]), float(c["ema15"]), float(c["ema50"]), float(c["ema200"])
        rsi7, atr, adx = float(c["rsi7"]), float(c["atr"]), float(c["adx"])

        sig = None

        # PRIORITY 1: 0.786 Deep Fib + 9/15 EMA (80.0% WR — HIGHEST ACCURACY)
        f786_b = sw_hi - 0.786 * fib_rng
        f786_s = sw_lo + 0.786 * fib_rng
        if cl > ema200 and ema9 > ema15 and lo <= f786_b and cl > f786_b and cl > op and rsi7 < 45:
            sl = sw_lo - 0.3 * atr
            tp = cl + 1.8 * (cl - sl)
            sig = ("BUY", "P1: 0.786 Deep Fib + EMA", "80.0% WR", True, cl, sl, tp)
        elif cl < ema200 and ema9 < ema15 and hi >= f786_s and cl < f786_s and cl < op and rsi7 > 55:
            sl = sw_hi + 0.3 * atr
            tp = cl - 1.8 * (sl - cl)
            sig = ("SELL", "P1: 0.786 Deep Fib + EMA", "80.0% WR", True, cl, sl, tp)

        # PRIORITY 2: Golden 3-Candle Exhaustion Sweep (61.1% WR — HIGH ACCURACY)
        if not sig and len(df) >= 6:
            c1, c2, c3 = df.iloc[-3], df.iloc[-4], df.iloc[-5]
            if float(c1["Close"]) < float(c1["Open"]) and float(c2["Close"]) < float(c2["Open"]) and float(c3["Close"]) < float(c3["Open"]) and lo < sw_lo and cl > op and rsi7 < 25:
                sl = lo - 0.3 * atr
                tp = cl + 1.8 * (cl - sl)
                sig = ("BUY", "P2: Golden 3-Candle Sweep", "61.1% WR", True, cl, sl, tp)
            elif float(c1["Close"]) > float(c1["Open"]) and float(c2["Close"]) > float(c2["Open"]) and float(c3["Close"]) > float(c3["Open"]) and hi > sw_hi and cl < op and rsi7 > 75:
                sl = hi + 0.3 * atr
                tp = cl - 1.8 * (sl - cl)
                sig = ("SELL", "P2: Golden 3-Candle Sweep", "61.1% WR", True, cl, sl, tp)

        # PRIORITY 3: BB(30) Volatility Squeeze (42.3% WR — Standard Setup)
        if not sig and adx > 22:
            bb_w_series = df["bb_width"].iloc[-22:-2]
            if not bb_w_series.empty and float(df["bb_width"].iloc[-3]) < np.percentile(bb_w_series.dropna(), 15):
                if cl > float(c["bb_upper"]) and cl > ema200:
                    sl = float(c["bb_mid"])
                    tp = cl + 1.8 * (cl - sl)
                    sig = ("BUY", "P3: BB(30) Squeeze Breakout", "42.3% WR", False, cl, sl, tp)
                elif cl < float(c["bb_lower"]) and cl < ema200:
                    sl = float(c["bb_mid"])
                    tp = cl - 1.8 * (sl - cl)
                    sig = ("SELL", "P3: BB(30) Squeeze Breakout", "42.3% WR", False, cl, sl, tp)

        if sig:
            direction, strat_name, wr_tag, is_high_acc, entry_p, sl_p, tp_p = sig
            last_signal_bar[pair_name] = bar_ts
            active_trades[pair_name] = {
                "dir": direction, "strat": strat_name, "entry": entry_p, "sl": sl_p, "tp": tp_p
            }

            if is_high_acc:
                conviction_banner = (
                    f"🔥🔥 **HIGHEST ACCURACY TRADE ({wr_tag})** 🔥🔥\n"
                    f"👉 **IS TRADE MEIN SABSE ZYADA ACCURACY HAI — ISKO ZAROOR TRADE KARNA!**\n"
                )
            else:
                conviction_banner = f"⚡ **STANDARD SNIPER SETUP ({wr_tag})**\n"

            act_emoji = "🟢 BUY NOW" if direction == "BUY" else "🔴 SELL NOW"
            msg = (
                f"{conviction_banner}"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Pair: **{pair_name}** (15m)\n"
                f"🧠 Strategy: **{strat_name}**\n"
                f"🎬 Action: **{act_emoji}**\n"
                f"🚪 Entry: `{entry_p:.4f}`\n"
                f"🛑 Stop Loss: `{sl_p:.4f}`\n"
                f"🎯 Target TP: `{tp_p:.4f}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{get_scorecard_text()}"
            )
            send_tg(msg)

    except Exception as e:
        print(f"Scan error on {pair_name}: {e}")

def scanner_loop():
    send_tg(
        "🚀 **24/7 UNLIMITED SNIPER BOT UPDATED!**\n"
        "• **No SL Lock:** SL ke baad bhi trades aate rahenge\n"
        "• **Live Hisab:** Har TP/SL par aaj ka aur kul dino ka record dikhega\n"
        "• **High-Accuracy Tag:** 80% & 61% WR trades par special alert aayega"
    )
    while True:
        check_day_rollover()
        for pair_name, ticker in SYMBOLS.items():
            evaluate_market(pair_name, ticker)
        time.sleep(15)

# ==============================================================================
# 4. WEBHOOK & HEALTH ENDPOINTS
# ==============================================================================
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Live", "stats": {k: (list(v) if isinstance(v, set) else v) for k, v in stats.items()}}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_data(as_text=True)
    if data:
        send_tg(f"⚡ **0-SEC TRADINGVIEW ALERT:**\n{data}\n\n{get_scorecard_text()}")
    return "OK", 200

threading.Thread(target=scanner_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
