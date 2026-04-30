"""One-shot Telegram responder — processes last message and replies."""
import os, sys, requests, json, time
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv; load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A")
API = "https://api.telegram.org/bot" + TOKEN

def send(chat_id, text):
    requests.post(API + "/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)

# Get last update
r = requests.get(API + "/getUpdates?offset=-3", timeout=10)
updates = r.json().get("result", [])

for u in updates:
    if "message" not in u: continue
    msg = u["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()
    first = msg["chat"].get("first_name", "")

    print(f"Processing: {text} from {first}")

    if text in ("/price", "price", "p"):
        try:
            import MetaTrader5 as mt5
            mt5.initialize(); mt5.login(22148595)
            t = mt5.symbol_info_tick("US100_Spot")
            send(chat_id, f"\U0001f4b0 US100: <b>{t.ask:.1f}</b> | Spread: {t.ask-t.bid:.1f}")
            print("Sent price")
        except Exception as e:
            send(chat_id, f"Error: {e}")

    elif text in ("/signal", "signal", "s"):
        try:
            from run_us100_monitor import get_candles, fmt
            from smc_manual import find_swings, find_order_blocks, find_liquidity, find_fvg
            m15 = get_candles("CFI:US100", "15", 25)[::-1]
            p = m15[-1][4]
            h,l = find_swings(m15, 10)
            fvgs = find_fvg(m15)
            liqs = find_liquidity(m15)
            m5 = get_candles("CFI:US100", "5", 5)[::-1]
            g5 = sum(1 for c in m5[-5:] if c[4] > c[1])

            msg = f"\U0001f9e0 <b>SMC Signal</b>\n\n"
            msg += f"\U0001f4b0 Price: <code>{fmt(p)}</code> | 5M: {g5}/5 green\n\n"
            if h: msg += f"Resist: {fmt(max(x[1] for x in h))}\n"
            if l: msg += f"Support: {fmt(min(x[1] for x in l))}\n"
            near_ob = [o for o in find_order_blocks(m15) if o[2] <= p <= o[3]]
            if near_ob: msg += f"OB: {near_ob[0][0]} {fmt(near_ob[0][2])}-{fmt(near_ob[0][3])}\n"
            near_fvg = [f for f in fvgs if abs(f[2]-p) < 100]
            if near_fvg: msg += f"FVG: {near_fvg[-1][0]} {fmt(near_fvg[-1][2])}-{fmt(near_fvg[-1][3])}\n"
            near_liq = [x for x in liqs if abs(x[2]-p)/p < 0.003]
            if near_liq: msg += f"Liq: {near_liq[0][0]} at {fmt(near_liq[0][2])}\n"

            direction = "BUY" if g5 >= 3 else "SELL" if g5 <= 1 else "WAIT"
            msg += f"\n<b>{direction}</b>"
            send(chat_id, msg)
            print("Sent signal")
        except Exception as e:
            send(chat_id, f"Error: {e}")

    elif text in ("/start","start","hi","hello"):
        send(chat_id, f"Hello {first}! Send:\n/price - current price\n/signal - SMC analysis")
