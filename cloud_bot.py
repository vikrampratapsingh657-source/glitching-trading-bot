import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import os
import sys
import csv
import json
from datetime import datetime

# ================= 1. CONFIGURATION =================
TG_TOKEN = "8817947998:AAHVC18Hh2y4qshr5mLFk1at5q2zJikLOJs"
TG_CHAT_ID = "7448627639"

INITIAL_CAPITAL = 1000.0   # वर्चुअल बैलेंस ($)
LEVERAGE = 10              # लेवरेज
RISK_PCT = 0.01            # 1% फिक्स रिस्क
FIB_RATIO = 0.146
T1_RR = 1.5
T2_RR = 3.0
WINDOW = 20
INTERVAL = "15m"

# तीनों सेगमेंट्स (Crypto, Forex/Commodity, Indian Market) के टॉप एसेट्स
WATCHLIST = [
    {"type": "CRYPTO", "ticker": "BTCUSDT", "yf": "BTC-USD", "name": "Bitcoin (Crypto)"},
    {"type": "CRYPTO", "ticker": "SOLUSDT", "yf": "SOL-USD", "name": "Solana (Crypto)"},
    {"type": "FOREX", "ticker": "GC=F", "yf": "GC=F", "name": "Gold / XAUUSD (Commodity)"},
    {"type": "FOREX", "ticker": "CL=F", "yf": "CL=F", "name": "Crude Oil WTI (Commodity)"},
    {"type": "INDIAN", "ticker": "^NSEI", "yf": "^NSEI", "name": "NIFTY 50 (Indian Market)"},
    {"type": "INDIAN", "ticker": "RELIANCE.NS", "yf": "RELIANCE.NS", "name": "Reliance Ind. (Indian Stock)"}
]

CSV_FILE = "trades_history.csv"
STATE_FILE = "account_state.json"

# ================= 2. HELPER FUNCTIONS =================
def save_state(capital, initial_capital, total_trades, wins, losses):
    data = {
        "current_capital": capital,
        "initial_capital": initial_capital,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_trade_to_csv(trade_data):
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, mode='a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=trade_data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade_data)

def send_telegram_alert(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=3.0)
    except Exception as e:
        print(f"Telegram Error: {e}")

def calculate_atr(df, length=14):
    if len(df) < length + 1:
        return (df['High'] - df['Low']).mean()
    high = df['High']
    low = df['Low']
    close = df['Close'].shift(1)
    tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
    return float(tr.rolling(window=length).mean().iloc[-1])

# ================= 3. STATE INITIALIZATION =================
saved_state = load_state()
if saved_state:
    capital = float(saved_state['current_capital'])
    initial_cap = float(saved_state['initial_capital'])
    restored_trades = saved_state.get('total_trades', 0)
    restored_wins = saved_state.get('wins', 0)
    restored_losses = saved_state.get('losses', 0)
else:
    capital = INITIAL_CAPITAL
    initial_cap = INITIAL_CAPITAL
    restored_trades = 0
    restored_wins = 0
    restored_losses = 0
    save_state(capital, initial_cap, 0, 0, 0)

send_telegram_alert(
    f"🌐 *TRI-MARKET HIGH ACCURACY SCANNER RUNNING*\n"
    f"📊 Scanning: Crypto, Gold/Forex & Indian Markets\n"
    f"⏱ Timeframe: `{INTERVAL}` | Risk Filter: `Delta >= 70%`\n"
    f"💼 Balance: `${capital:,.2f}` | Lev: `{LEVERAGE}x`\n"
    f"🎯 Rule: Din me sirf highest accuracy setup aayega (No Spam)."
)

active_trade = None
history = []
asset_caches = {}
last_cache_time = 0

# ================= 4. MAIN CONTINUOUS SCANNING LOOP =================
while True:
    loop_start = time.time()

    # 1. Active Trade Tracking
    if active_trade is not None:
        t = active_trade
        live_price = t['entry']

        if t['type'] == "CRYPTO":
            try:
                res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={t['ticker']}", timeout=1.2).json()
                if 'price' in res:
                    live_price = float(res['price'])
            except Exception:
                pass
        else:
            try:
                temp_df = yf.download(t['yf'], period="1d", interval="1m", progress=False)
                if not temp_df.empty:
                    if isinstance(temp_df.columns, pd.MultiIndex):
                        temp_df.columns = temp_df.columns.get_level_values(0)
                    live_price = float(temp_df['Close'].iloc[-1])
            except Exception:
                pass

        ent = t['entry']
        trade_closed = False
        outcome = ""

        if t['side'] == "LONG":
            if live_price > t['peak_price']:
                t['peak_price'] = live_price

            if not t['t1_hit']:
                if live_price <= t['sl']:
                    capital -= t['risk_amt']
                    outcome = "FULL SL HIT"
                    trade_closed = True
                elif live_price >= t['t1']:
                    t['t1_hit'] = True
                    capital += (t['risk_amt'] / 2.0) * T1_RR
                    t['sl'] = ent
                    send_telegram_alert(f"🎯 *TARGET 1 REACHED (50% Profit Booked)*: `{t['name']}`\n🔒 Stop-Loss Breakeven (${ent:.2f}) par lock kar diya gaya hai.")
            else:
                trailed_sl = max(ent, t['peak_price'] - t['atr'])
                if trailed_sl > t['sl']:
                    t['sl'] = trailed_sl

                if live_price >= t['t2']:
                    capital += (t['risk_amt'] / 2.0) * T2_RR
                    outcome = "T2 JACKPOT"
                    trade_closed = True
                elif live_price <= t['sl']:
                    outcome = "TRAILED PROFIT SL"
                    trade_closed = True

        elif t['side'] == "SHORT":
            if live_price < t['peak_price']:
                t['peak_price'] = live_price

            if not t['t1_hit']:
                if live_price <= t['sl']:
                    capital -= t['risk_amt']
                    outcome = "FULL SL HIT"
                    trade_closed = True
                elif live_price >= t['t1']:
                    t['t1_hit'] = True
                    capital += (t['risk_amt'] / 2.0) * T1_RR
                    t['sl'] = ent
                    send_telegram_alert(f"🎯 *TARGET 1 REACHED (50% Profit Booked)*: `{t['name']}`\n🔒 Stop-Loss Breakeven (${ent:.2f}) par lock kar diya gaya hai.")
            else:
                trailed_sl = min(ent, t['peak_price'] + t['atr'])
                if trailed_sl < t['sl']:
                    t['sl'] = trailed_sl

                if live_price <= t['t2']:
                    capital += (t['risk_amt'] / 2.0) * T2_RR
                    outcome = "T2 JACKPOT"
                    trade_closed = True
                elif live_price <= t['sl']:
                    outcome = "TRAILED PROFIT SL"
                    trade_closed = True

        if trade_closed:
            duration_sec = int(time.time() - t['start_timestamp'])
            duration_str = f"{duration_sec // 60}m {duration_sec % 60}s" if duration_sec >= 60 else f"{duration_sec}s"

            if "JACKPOT" in outcome:
                pnl_realized = (t['risk_amt'] / 2.0 * T1_RR + t['risk_amt'] / 2.0 * T2_RR)
            elif "TRAILED" in outcome:
                second_half_pnl = ((t['sl'] - ent) * (t['qty'] / 2.0)) if t['side'] == "LONG" else ((ent - t['sl']) * (t['qty'] / 2.0))
                pnl_realized = (t['risk_amt'] / 2.0 * T1_RR) + second_half_pnl
            else:
                pnl_realized = -t['risk_amt']

            trade_entry = {
                "id": t['id'],
                "asset": t['name'],
                "side": t['side'],
                "entry_time": t['entry_time'],
                "exit_time": datetime.now().strftime("%H:%M:%S"),
                "duration": duration_str,
                "entry": f"{ent:.2f}",
                "exit": f"{live_price:.2f}",
                "outcome": outcome,
                "pnl": f"{pnl_realized:+.2f}",
                "balance": f"{capital:.2f}"
            }
            history.append(trade_entry)
            save_trade_to_csv(trade_entry)

            w_cnt = restored_wins + sum(1 for h in history if float(h['pnl']) > 0)
            l_cnt = restored_losses + sum(1 for h in history if float(h['pnl']) < 0)
            save_state(capital, initial_cap, restored_trades + len(history), w_cnt, l_cnt)

            send_telegram_alert(
                f"🏁 *TRADE CLOSED ({outcome})*\n"
                f"📌 Asset: `{t['name']}`\n"
                f"💵 Exit: `${live_price:.2f}`\n"
                f"📊 PnL: `${pnl_realized:+.2f}`\n"
                f"💼 Updated Balance: `${capital:,.2f}`\n"
                f"🔍 Ab bot agle high-accuracy setup ko scan kar raha hai..."
            )
            active_trade = None

        time.sleep(2)
        continue

    # 2. Scanning Mode (सभी 6 एसेट्स स्कैन होंगे)
    refresh_needed = (time.time() - last_cache_time > 60)
    for asset in WATCHLIST:
        a_key = asset['ticker']

        if refresh_needed or a_key not in asset_caches:
            try:
                df = yf.download(asset['yf'], period="5d", interval=INTERVAL, progress=False)
                if not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    asset_caches[a_key] = df
            except Exception:
                continue

        df = asset_caches.get(a_key)
        if df is None or len(df) < WINDOW + 2:
            continue

        curr_price = float(df['Close'].iloc[-1])
        if asset['type'] == "CRYPTO":
            try:
                res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={asset['ticker']}", timeout=1.0).json()
                if 'price' in res:
                    curr_price = float(res['price'])
            except Exception:
                pass

        atr_val = calculate_atr(df, 14)
        sw_high = float(df['High'].iloc[-WINDOW-1:-1].max())
        sw_low = float(df['Low'].iloc[-WINDOW-1:-1].min())
        rng = sw_high - sw_low if (sw_high - sw_low) > 0 else 0.01

        is_uptrend = float(df['Close'].iloc[-2]) > float(df['Open'].iloc[-WINDOW-1])
        fib_level = (sw_low + (FIB_RATIO * rng)) if is_uptrend else (sw_high - (FIB_RATIO * rng))

        last_c = df.iloc[-1]
        c_open = float(last_c['Open'])
        c_high = max(float(last_c['High']), curr_price)
        c_low = min(float(last_c['Low']), curr_price)
        tot_rng = c_high - c_low if (c_high - c_low) > 0 else 0.001

        if curr_price >= c_open:
            buyer_score = ((curr_price - c_low) / tot_rng) * 100
        else:
            buyer_score = ((c_high - curr_price) / tot_rng) * 100
            buyer_score = 100.0 - buyer_score

        buyer_score = max(5.0, min(95.0, buyer_score))
        seller_score = 100.0 - buyer_score

        # 3. High-Accuracy Trigger (Strict 70% Delta Filter)
        # SHORT TRIGGER
        if not is_uptrend and curr_price <= fib_level and seller_score >= 70.0:
            sl = sw_high + (0.5 * atr_val)
            risk_d = sl - curr_price
            if risk_d > 0:
                r_amt = capital * RISK_PCT
                qty = (r_amt / risk_d)
                active_trade = {
                    "id": f"ORD-{len(history)+restored_trades+1:03d}",
                    "side": "SHORT",
                    "type": asset['type'],
                    "ticker": asset['ticker'],
                    "yf": asset['yf'],
                    "name": asset['name'],
                    "entry": curr_price,
                    "sl": sl,
                    "initial_sl": sl,
                    "t1": curr_price - (T1_RR * risk_d),
                    "t2": curr_price - (T2_RR * risk_d),
                    "risk_amt": r_amt,
                    "qty": qty,
                    "atr": atr_val,
                    "t1_hit": False,
                    "peak_price": curr_price,
                    "entry_time": datetime.now().strftime("%H:%M:%S"),
                    "start_timestamp": time.time()
                }
                send_telegram_alert(
                    f"🔴 *HIGH-ACCURACY SELL SIGNAL*\n"
                    f"📌 Segment: `{asset['name']}`\n"
                    f"⏱ Timeframe: `{INTERVAL}`\n"
                    f"💵 Entry: `${curr_price:.2f}`\n"
                    f"🛑 Stop-Loss: `${sl:.2f}`\n"
                    f"🎯 Target 1 (1:1.5): `${active_trade['t1']:.2f}`\n"
                    f"🎯 Target 2 (1:3.0): `${active_trade['t2']:.2f}`\n"
                    f"🔥 Seller Strength: `{seller_score:.0f}%` (High Accuracy)"
                )
                break

        # LONG TRIGGER
        elif is_uptrend and curr_price >= fib_level and buyer_score >= 70.0:
            sl = sw_low - (0.5 * atr_val)
            risk_d = curr_price - sl
            if risk_d > 0:
                r_amt = capital * RISK_PCT
                qty = (r_amt / risk_d)
                active_trade = {
                    "id": f"ORD-{len(history)+restored_trades+1:03d}",
                    "side": "LONG",
                    "type": asset['type'],
                    "ticker": asset['ticker'],
                    "yf": asset['yf'],
                    "name": asset['name'],
                    "entry": curr_price,
                    "sl": sl,
                    "initial_sl": sl,
                    "t1": curr_price + (T1_RR * risk_d),
                    "t2": curr_price + (T2_RR * risk_d),
                    "risk_amt": r_amt,
                    "qty": qty,
                    "atr": atr_val,
                    "t1_hit": False,
                    "peak_price": curr_price,
                    "entry_time": datetime.now().strftime("%H:%M:%S"),
                    "start_timestamp": time.time()
                }
                send_telegram_alert(
                    f"🟢 *HIGH-ACCURACY BUY SIGNAL*\n"
                    f"📌 Segment: `{asset['name']}`\n"
                    f"⏱ Timeframe: `{INTERVAL}`\n"
                    f"💵 Entry: `${curr_price:.2f}`\n"
                    f"🛑 Stop-Loss: `${sl:.2f}`\n"
                    f"🎯 Target 1 (1:1.5): `${active_trade['t1']:.2f}`\n"
                    f"🎯 Target 2 (1:3.0): `${active_trade['t2']:.2f}`\n"
                    f"🔥 Buyer Strength: `{buyer_score:.0f}%` (High Accuracy)"
                )
                break

    if refresh_needed:
        last_cache_time = time.time()

    elapsed = time.time() - loop_start
    time.sleep(max(1.0, 5.0 - elapsed))
