#!/usr/bin/env python
"""CFI:US100 Comprehensive Trading Monitor

Monitors 24/7 for:
- Session alerts (Asia/London/NY open/close with price)
- Scalp signals (1M/5M/15M) with entry order type (limit/stop)
- SMC/ICT signals (BOS, CHoCH, Order Blocks, FVG, Liquidity Sweeps)
- Swing signals (1H/4H/Daily) with higher R:R
- Market open/close alerts
- Brief news that may impact Nasdaq 100
- Every signal includes: reason, confidence, entry type, SL, TP

Timezone: Asia/Amman (GMT+3)
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

import pytz
import requests
from smc_analysis import analyze_smc
from symbol_manager import load_symbols, get_active_symbols


# ── Multi-user support ───────────────────────────────────────
def get_subscribed_users():
    try:
        with open(os.path.join(os.path.dirname(__file__), "users.json"), "r") as f:
            data = json.load(f)
        return {k: v for k, v in data.get("users", {}).items() if v.get("subscribed")}
    except:
        return {"624637526": {"first_name": "Mohd S"}}


def alert_all(text):
    users = get_subscribed_users()
    ok_count = 0
    for chat_id in users:
        r = tg("sendMessage", {"chat_id": int(chat_id), "text": text, "parse_mode": "HTML"})
        if r.get("ok"):
            ok_count += 1
        else:
            logger.error("Send to %s failed: %s", chat_id, r.get("description"))
    if ok_count:
        logger.info("Alert sent to %d/%d users", ok_count, len(users))
    return ok_count > 0


alert = alert_all


# ── Telegram subscription handling ────────────────────────────
_last_subscription_check = 0
_processed_updates = set()


def check_subscriptions():
    """Handle /start and /stop commands to subscribe/unsubscribe users."""
    global _last_subscription_check, _processed_updates

    updates = tg("getUpdates", {"timeout": 5})
    if not updates.get("ok") or not updates.get("result"):
        return

    try:
        data = json.load(open(os.path.join(os.path.dirname(__file__), "users.json"), "r"))
    except:
        data = {"users": {}}

    for update in updates["result"]:
        uid = update["update_id"]
        if uid in _processed_updates:
            continue
        _processed_updates.add(uid)

        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        first = chat.get("first_name", "")

        if not chat_id:
            continue

        if text in ("/start", "start"):
            data["users"][chat_id] = {
                "first_name": first,
                "username": chat.get("username", ""),
                "subscribed": True,
                "joined": datetime.now(TZ).isoformat(),
            }
            json.dump(data, open(os.path.join(os.path.dirname(__file__), "users.json"), "w"), indent=2)
            tg("sendMessage", {
                "chat_id": int(chat_id),
                "text": f"\u2705 <b>Subscribed!</b> You will receive CFI:US100 signals.\n\nCommands:\n/start — Subscribe\n/stop — Unsubscribe\n/symbols — List monitored symbols",
                "parse_mode": "HTML",
            })
            logger.info("User %s (%s) subscribed", chat_id, first)

        elif text in ("/stop", "stop", "unsubscribe"):
            if chat_id in data["users"]:
                data["users"][chat_id]["subscribed"] = False
                json.dump(data, open(os.path.join(os.path.dirname(__file__), "users.json"), "w"), indent=2)
                tg("sendMessage", {"chat_id": int(chat_id), "text": "\u23f9 You have been unsubscribed. Send /start to rejoin."})
                logger.info("User %s unsubscribed", chat_id)

        elif text == "/symbols":
            from symbol_manager import load_symbols
            syms = load_symbols()
            active = [f"<code>{k}</code> — {v.get('name','')}" for k, v in syms.items() if v.get("active")]
            if active:
                msg_text = "<b>Monitored Symbols:</b>\n\n" + "\n".join(active)
            else:
                msg_text = "No active symbols."
            tg("sendMessage", {"chat_id": int(chat_id), "text": msg_text, "parse_mode": "HTML"})

    if len(_processed_updates) > 1000:
        _processed_updates = set(list(_processed_updates)[-200:])
from tradingagents.dataflows.tv_realtime import get_live_chart

# ── Config ───────────────────────────────────────────────────
TOKEN = "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A"
DEFAULT_SYMBOL = "CFI:US100"
TZ = pytz.timezone("Asia/Amman")

TELEGRAM_API = "https://api.telegram.org/bot"
CHECK_SCALP_SEC = 45   # Scalp check every 45 secs
CHECK_SWING_SEC = 300  # Swing check every 5 mins
CHECK_SMC_SEC = 60     # SMC check every 60 secs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("us100_monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── Telegram ─────────────────────────────────────────────────
def tg(method, params=None):
    try:
        r = requests.post(f"{TELEGRAM_API}{TOKEN}/{method}", json=params or {}, timeout=15)
        return r.json()
    except:
        return {"ok": False}


# ── Data parsing ─────────────────────────────────────────────
def parse(raw):
    candles = []
    for line in raw.strip().split("\n"):
        if line.startswith("#") or line.startswith("time,"):
            continue
        p = line.split(",")
        if len(p) >= 6:
            try:
                candles.append([float(v) for v in p])
            except ValueError:
                pass
    return candles


def get_candles(symbol, tf, count):
    # Try TradingView bridge first
    try:
        from tradingagents.dataflows.tv_realtime import get_live_chart
        raw = get_live_chart(symbol, timeframe=tf, range_bars=count)
        candles = parse(raw)
        if candles and len(candles) >= 3:
            return candles
    except:
        pass

    # Fallback: yfinance (stocks/ETFs/indices)
    try:
        import yfinance as yf
        interval_map = {"1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h", "240": "4h", "1D": "1d", "1W": "1wk", "1M": "1mo"}
        period_map = {"1": "1d", "5": "5d", "15": "5d", "30": "5d", "60": "3mo", "240": "6mo", "1D": "1mo", "1W": "6mo", "1M": "2y"}
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period_map.get(tf, "1mo"), interval=interval_map.get(tf, "1d"))
        if hist is not None and not hist.empty:
            candles = []
            for idx, row in hist.tail(count).iterrows():
                candles.append([int(idx.timestamp()), float(row["Open"]), float(row["High"]),
                               float(row["Low"]), float(row["Close"]), float(row["Volume"])])
            return candles
    except:
        pass

    return []


def fmt(n):
    return f"{n:,.1f}"


# ── Sessions ────────────────────────────────────────────────
# All times in Asia/Amman (GMT+3)
SESSIONS = {
    "asia":     {"open": 3,  "close": 10, "name": "Asia"},
    "london":   {"open": 10, "close": 19, "name": "London"},
    "ny_forex": {"open": 15, "close": 19, "name": "NY Forex"},
    "wall_st":  {"open": 16, "close": 23, "name": "Wall Street (NYSE/NASDAQ)"},
}

# Track session START/END prices
_session_prices = {}


def get_current_session(hour=None):
    """Return the active trading session name."""
    if hour is None:
        from datetime import datetime
        import pytz
        hour = datetime.now(pytz.timezone("Asia/Amman")).hour
    for key, sess in SESSIONS.items():
        if sess["open"] <= hour < sess["close"]:
            return key, sess["name"]
    return "off", "Off-Hours"


def get_session_emoji(session_key):
    emojis = {"asia": "\U0001f1ef\U0001f1f5", "london": "\U0001f1ec\U0001f1e7", "ny_forex": "\U0001f4b1", "wall_st": "\U0001f3db"}
    return emojis.get(session_key, "\u23f0")

# Nas100 CFD trades 24hrs Mon 01:01 → Fri 23:59 (Amman time)
# Weekend: Fri 23:59 → Mon 01:01 — market closed
MARKET_OPEN_MINUTE = 61   # 01:01 Amman = Monday open (01:01)
MARKET_CLOSE_HOUR = 23
MARKET_CLOSE_MINUTE = 59
MARKET_CLOSE_WEEKDAY = 4  # Friday

_last_session_alerts = {}
_last_market_alert = None


def check_sessions():
    global _last_session_alerts, _last_market_alert
    now = datetime.now(TZ)
    h = now.hour
    m = now.minute
    wkday = now.weekday()  # 0=Mon, 6=Sun

    alerts = []

    # ── Market Open/Close (CFI:US100 CFD hours) ──
    # Open: Monday 01:01 | Close: Friday 23:59 (Amman)
    is_open_day = 0 <= wkday <= 4
    is_weekend = wkday >= 5

    # Market opening alert (Monday 01:01)
    if wkday == 0 and h == 1 and m <= 5:
        if _last_market_alert != "open":
            price = fmt(get_current_price())
            alerts.append(
                "\U0001f7e2 <b>WEEKLY MARKET OPEN</b>\n"
                f"Nas100 CFD trading resumes\n"
                f"Opening price: <code>{price}</code>\n"
                "<i>New week — watch for gap!</i>"
            )
            _last_market_alert = "open"

    # Market closing alert (Friday 23:59)
    if wkday == 4 and h == 23 and m >= 55:
        if _last_market_alert != "close":
            price = fmt(get_current_price())
            alerts.append(
                "\U0001f534 <b>WEEKLY MARKET CLOSE</b>\n"
                f"Nas100 CFD trading halts until Monday 01:01\n"
                f"Closing price: <code>{price}</code>\n"
                "<i>Close all positions or set wide stops</i>"
            )
            _last_market_alert = "close"

    # Weekend check
    if is_weekend:
        if _last_market_alert not in ("closed_weekend", "close"):
            alerts.append(
                "\U0001f6a7 <b>Market Closed — Weekend</b>\n"
                "Nas100 reopens Monday at 01:01 Amman\n"
                "<i>No trading available</i>"
            )
            _last_market_alert = "closed_weekend"
        return alerts

    # Reset open/close state for the new week
    if wkday == 0 and h >= 2:
        _last_market_alert = None

    # ── Session Alerts ──
    emoji_map = {"asia": "\U0001f1ef\U0001f1f5", "london": "\U0001f1ec\U0001f1e7", "ny_forex": "\U0001f4b1", "wall_st": "\U0001f3db"}
    for skey, sess in SESSIONS.items():
        sh, sc = sess["open"], sess["close"]
        label = f"{skey}_open"
        clabel = f"{skey}_close"
        emoji = emoji_map.get(skey, "")

        if h == sh and m <= 5:
            if _last_session_alerts.get(label) != now.date():
                price = fmt(get_current_price())
                _session_prices[skey] = {"start": price, "end": None}
                alerts.append(
                    f"{emoji} <b>{sess['name']} OPEN</b>\n"
                    f"Price: <code>{price}</code>\n"
                    f"<i>Session started | {sh:02d}:00-{sc:02d}:00 Amman</i>"
                )
                _last_session_alerts[label] = now.date()

        if h == sc and m >= 55:
            if _last_session_alerts.get(clabel) != now.date():
                price = fmt(get_current_price())
                start_price = _session_prices.get(skey, {}).get("start", "—")
                alerts.append(
                    f"{emoji} <b>{sess['name']} CLOSE</b>\n"
                    f"Close: <code>{price}</code> | Open: <code>{start_price}</code>\n"
                    f"<i>Session ended</i>"
                )
                _last_session_alerts[clabel] = now.date()
                _last_session_alerts[clabel] = now.date()

    return alerts


# ── News ────────────────────────────────────────────────────
_last_news_time = None


def check_news():
    global _last_news_time
    now = datetime.now(TZ)
    if _last_news_time and (now - _last_news_time).seconds < 3600:
        return []

    _last_news_time = now

    try:
        r = requests.get(
            "https://newsdata.io/api/1/news",
            params={"apikey": "pub_77234578ead2902d3cfd45b9cf58e1cea5051", "q": "nasdaq OR fed OR us100 OR tech stocks", "language": "en", "size": 3},
            timeout=10,
        )
        data = r.json()
        msgs = []
        for article in data.get("results", [])[:2]:
            title = article.get("title", "")[:80]
            desc = article.get("description", "")[:120]
            msgs.append(
                f"\U0001f4f0 <b>{title}</b>\n"
                f"<i>{desc}</i>"
            )
        return msgs
    except:
        return []


# ── Price ─────────────────────────────────────────────────────
_price_cache = {}


def get_current_price(symbol=None):
    global _price_cache
    sym = symbol or DEFAULT_SYMBOL
    cache_key = sym
    cache = _price_cache.get(cache_key, {"val": 0, "ts": 0})
    if time.time() - cache["ts"] < 30:
        return cache["val"]
    try:
        c = get_candles(sym, "1D", 2)
        if c:
            _price_cache[cache_key] = {"val": c[0][4], "ts": time.time()}
            return c[0][4]
    except:
        pass
    return cache["val"]


# ── Signal Detection ──────────────────────────────────────────


def analyze_candles_1m(m1):
    """Micro-scalp on 1M candles. Fast entries, tight stops."""
    if len(m1) < 20:
        return []

    price = m1[0][4]
    last = m1[0]
    prev = m1[1]
    body = last[4] - last[1]
    prev_body = prev[4] - prev[1]
    wick_hi = last[2] - max(last[1], last[4])
    wick_lo = min(last[1], last[4]) - last[3]

    h = max(c[2] for c in m1[:20])
    l = min(c[3] for c in m1[:20])
    rng = h - l
    pos = (price - l) / rng if rng > 0 else 0.5
    mid = (h + l) / 2

    # Volume spike detection
    v_last = last[5]
    v_avg = sum(c[5] for c in m1[:10]) / 10
    v_spike = v_last > v_avg * 1.5

    # Momentum (last 3 candles)
    c3 = [c[4] for c in m1[:3]]
    mom = (c3[0] - c3[-1]) / c3[-1] * 100

    signals = []

    # 1M BREAKOUT LONG — strong green candle above range
    if body > 0 and price >= h * 0.999 and v_spike:
        signals.append({
            "direction": "LONG", "setup": "1M Breakout",
            "order_type": "Buy Stop", "entry": round(h + rng * 0.01, 1),
            "sl": round(h - rng * 0.05, 1), "tp": round(h + rng * 0.4, 1),
            "confidence": 0.72, "timeframe": "1M",
            "reasoning": f"Price broke 1M range high at {fmt(h)} with {((v_last/v_avg)-1)*100:.0f}% volume spike. Momentum breakout. SL below break level."
        })

    # 1M BREAKDOWN SHORT — strong red candle below range
    if body < 0 and price <= l * 1.001 and v_spike:
        signals.append({
            "direction": "SHORT", "setup": "1M Breakdown",
            "order_type": "Sell Stop", "entry": round(l - rng * 0.01, 1),
            "sl": round(l + rng * 0.05, 1), "tp": round(l - rng * 0.4, 1),
            "confidence": 0.70, "timeframe": "1M",
            "reasoning": f"Price broke 1M range low at {fmt(l)} with volume spike. Breakdown momentum. SL above break level."
        })

    # 1M REVERSAL SHORT — shooting star at top
    if pos > 0.75 and wick_hi > abs(body) * 2 and prev_body > 0 and body < 0:
        signals.append({
            "direction": "SHORT", "setup": "1M Shooting Star",
            "order_type": "Sell Limit", "entry": round(price, 1),
            "sl": round(h + rng * 0.02, 1), "tp": round(mid, 1),
            "confidence": 0.65, "timeframe": "1M",
            "reasoning": f"Long wick ({fmt(wick_hi)}) rejected at {pos*100:.0f}% of range. Reversal candlestick. Quick scalp to mid-range."
        })

    # 1M REVERSAL LONG — hammer at bottom
    if pos < 0.25 and wick_lo > abs(body) * 2 and prev_body < 0 and body > 0:
        signals.append({
            "direction": "LONG", "setup": "1M Hammer Reversal",
            "order_type": "Buy Limit", "entry": round(price, 1),
            "sl": round(l - rng * 0.02, 1), "tp": round(mid, 1),
            "confidence": 0.65, "timeframe": "1M",
            "reasoning": f"Long lower wick ({fmt(wick_lo)}) at {pos*100:.0f}% of range — buyers stepped in. Bullish reversal. Target mid-range."
        })

    # 1M MOMENTUM LONG — 3 green candles in a row
    green3 = all(m1[i][4] > m1[i][1] for i in range(3))
    if green3 and mom > 0.03:
        signals.append({
            "direction": "LONG", "setup": "1M Green Streak",
            "order_type": "Buy Limit", "entry": round(price, 1),
            "sl": round(min(c[3] for c in m1[:3]) - rng * 0.02, 1),
            "tp": round(price + rng * 0.5, 1),
            "confidence": 0.60, "timeframe": "1M",
            "reasoning": f"3 consecutive green candles, mom +{mom*100:.1f}%. Strong intra-minute momentum. Ride the trend."
        })

    # 1M MOMENTUM SHORT — 3 red candles in a row
    red3 = all(m1[i][4] < m1[i][1] for i in range(3))
    if red3 and mom < -0.03:
        signals.append({
            "direction": "SHORT", "setup": "1M Red Streak",
            "order_type": "Sell Limit", "entry": round(price, 1),
            "sl": round(max(c[2] for c in m1[:3]) + rng * 0.02, 1),
            "tp": round(price - rng * 0.5, 1),
            "confidence": 0.60, "timeframe": "1M",
            "reasoning": f"3 consecutive red candles, mom {mom*100:.1f}%. Strong intra-minute selling. Ride the drop."
        })

    return signals


def analyze_candles_5m(m5, m1_ctx=None):
    """Short scalp on 5M candles."""
    if len(m5) < 15:
        return []

    price = m5[0][4]
    last = m5[0]
    prev = m5[1]
    body = last[4] - last[1]
    prev_body = prev[4] - prev[1]
    wick_hi = last[2] - max(last[1], last[4])
    wick_lo = min(last[1], last[4]) - last[3]

    h = max(c[2] for c in m5[:20])
    l = min(c[3] for c in m5[:20])
    rng = h - l
    pos = (price - l) / rng if rng > 0 else 0.5
    mid = (h + l) / 2

    # Volumes
    v_now = sum(c[5] for c in m5[:3]) / 3
    v_prev = sum(c[5] for c in m5[5:8]) / 3 if len(m5) > 8 else v_now

    signals = []

    # 5M BREAKOUT LONG
    if pos > 0.80 and body > 0 and v_now > v_prev:
        signals.append({
            "direction": "LONG", "setup": "5M Range Breakout",
            "order_type": "Buy Stop", "entry": round(h + rng * 0.01, 1),
            "sl": round(h - rng * 0.04, 1), "tp": round(h + rng * 0.5, 1),
            "confidence": 0.74, "timeframe": "5M",
            "reasoning": f"Price at {pos*100:.0f}% of 5M range with rising volume. Buy stop above {fmt(h)} for breakout continuation. SL below recent support."
        })

    # 5M BREAKDOWN SHORT
    if pos < 0.20 and body < 0 and v_now > v_prev:
        signals.append({
            "direction": "SHORT", "setup": "5M Range Breakdown",
            "order_type": "Sell Stop", "entry": round(l - rng * 0.01, 1),
            "sl": round(l + rng * 0.04, 1), "tp": round(l - rng * 0.5, 1),
            "confidence": 0.72, "timeframe": "5M",
            "reasoning": f"Price at {pos*100:.0f}% of 5M range, breaking down with volume. Sell stop below {fmt(l)}. SL above breakout level."
        })

    # 5M ENGULFING BULLISH
    if body > 0 and prev_body < 0 and abs(body) > abs(prev_body) * 1.2 and pos < 0.60:
        signals.append({
            "direction": "LONG", "setup": "5M Bullish Engulfing",
            "order_type": "Buy Limit", "entry": round(price - rng * 0.05, 1),
            "sl": round(l - rng * 0.02, 1), "tp": round(h + rng * 0.2, 1),
            "confidence": 0.68, "timeframe": "5M",
            "reasoning": "Green candle fully engulfs previous red — buyers overwhelmed sellers. Classic reversal at support area. Enter on slight pullback."
        })

    # 5M ENGULFING BEARISH
    if body < 0 and prev_body > 0 and abs(body) > abs(prev_body) * 1.2 and pos > 0.40:
        signals.append({
            "direction": "SHORT", "setup": "5M Bearish Engulfing",
            "order_type": "Sell Limit", "entry": round(price + rng * 0.05, 1),
            "sl": round(h + rng * 0.02, 1), "tp": round(l - rng * 0.2, 1),
            "confidence": 0.68, "timeframe": "5M",
            "reasoning": "Red candle completely engulfed previous green — sellers took control. Bearish reversal signal. Enter on slight bounce."
        })

    # 5M DOJI REVERSAL at range edge
    is_doji = abs(body) < rng * 0.02
    if is_doji and pos > 0.85 and prev_body > 0:
        signals.append({
            "direction": "SHORT", "setup": "5M Doji at Top",
            "order_type": "Sell Limit", "entry": round(price + rng * 0.02, 1),
            "sl": round(h + rng * 0.02, 1), "tp": round(mid, 1),
            "confidence": 0.62, "timeframe": "5M",
            "reasoning": f"Doji at {pos*100:.0f}% of 5M range — indecision at resistance. Previous candle was green. Likely reversal. Target mid-range."
        })

    if is_doji and pos < 0.15 and prev_body < 0:
        signals.append({
            "direction": "LONG", "setup": "5M Doji at Bottom",
            "order_type": "Buy Limit", "entry": round(price - rng * 0.02, 1),
            "sl": round(l - rng * 0.02, 1), "tp": round(mid, 1),
            "confidence": 0.62, "timeframe": "5M",
            "reasoning": f"Doji at {pos*100:.0f}% of 5M range — indecision at support. Sellers exhausted. Likely bounce. Target mid-range."
        })

    # 5M TREND CONTINUATION
    last5 = m5[:5]
    up5 = all(last5[i][4] > last5[i+1][4] for i in range(min(4, len(last5)-1)))
    if up5 and pos > 0.55:
        signals.append({
            "direction": "LONG", "setup": "5M Trend Continuation",
            "order_type": "Buy Limit", "entry": round(price - rng * 0.08, 1),
            "sl": round(l + rng * 0.15, 1), "tp": round(h + rng * 0.3, 1),
            "confidence": 0.64, "timeframe": "5M",
            "reasoning": "5 consecutive higher closes — solid uptrend. Buy on micro pullback. SL at mid-support. Target range extension."
        })

    down5 = all(last5[i][4] < last5[i+1][4] for i in range(min(4, len(last5)-1)))
    if down5 and pos < 0.45:
        signals.append({
            "direction": "SHORT", "setup": "5M Downtrend Continuation",
            "order_type": "Sell Limit", "entry": round(price + rng * 0.08, 1),
            "sl": round(h - rng * 0.15, 1), "tp": round(l - rng * 0.3, 1),
            "confidence": 0.64, "timeframe": "5M",
            "reasoning": "5 consecutive lower closes — strong downtrend. Sell on micro bounce. SL at mid-resistance. Target range extension downward."
        })

    # 5M PIN BAR REVERSAL
    if wick_hi > abs(body) * 2 and pos > 0.70:
        signals.append({
            "direction": "SHORT", "setup": "5M Pin Bar Top",
            "order_type": "Sell Limit", "entry": round(price, 1),
            "sl": round(h + rng * 0.01, 1), "tp": round(mid, 1),
            "confidence": 0.66, "timeframe": "5M",
            "reasoning": f"Pin bar with {fmt(wick_hi)} upper wick — sellers rejected new highs. Bearish reversal signal. SL above pin bar high."
        })

    if wick_lo > abs(body) * 2 and pos < 0.30:
        signals.append({
            "direction": "LONG", "setup": "5M Pin Bar Bottom",
            "order_type": "Buy Limit", "entry": round(price, 1),
            "sl": round(l - rng * 0.01, 1), "tp": round(mid, 1),
            "confidence": 0.66, "timeframe": "5M",
            "reasoning": f"Pin bar with {fmt(wick_lo)} lower wick — buyers rejected new lows. Bullish reversal signal. SL below pin bar low."
        })

    return signals


def analyze_candles_15m(m15):
    """Medium scalp on 15M candles."""
    if len(m15) < 10:
        return []

    price = m15[0][4]
    last = m15[0]
    prev = m15[1]
    body = last[4] - last[1]
    prev_body = prev[4] - prev[1]

    h = max(c[2] for c in m15)
    l = min(c[3] for c in m15)
    rng = h - l
    pos = (price - l) / rng if rng > 0 else 0.5
    mid = (h + l) / 2

    # Volumes
    v_recent = sum(c[5] for c in m15[:3]) / 3
    v_old = sum(c[5] for c in m15[5:8]) / 3 if len(m15) > 8 else v_recent

    signals = []

    # 15M BREAKOUT LONG — price / high tested, pushing
    top_test_count = sum(1 for c in m15[:10] if c[2] >= h * 0.998)
    if top_test_count >= 2 and body > 0 and v_recent > v_old:
        signals.append({
            "direction": "LONG", "setup": "15M Resistance Break",
            "order_type": "Buy Stop", "entry": round(h + rng * 0.015, 1),
            "sl": round(h - rng * 0.05, 1), "tp": round(h + rng * 0.6, 1),
            "confidence": 0.75, "timeframe": "15M",
            "reasoning": f"Resistance at {fmt(h)} tested {top_test_count}x in 10 candles. Volume rising — buyers absorbing. Breakout buy stop above resistance."
        })

    # 15M BREAKDOWN SHORT
    bot_test_count = sum(1 for c in m15[:10] if c[3] <= l * 1.002)
    if bot_test_count >= 2 and body < 0 and v_recent > v_old:
        signals.append({
            "direction": "SHORT", "setup": "15M Support Break",
            "order_type": "Sell Stop", "entry": round(l - rng * 0.015, 1),
            "sl": round(l + rng * 0.05, 1), "tp": round(l - rng * 0.6, 1),
            "confidence": 0.73, "timeframe": "15M",
            "reasoning": f"Support at {fmt(l)} tested {bot_test_count}x. Weak defense — sellers pushing through. Sell stop below support."
        })

    # 15M BOUNCE FROM SUPPORT
    if pos < 0.20 and body > 0 and prev_body < 0:
        signals.append({
            "direction": "LONG", "setup": "15M Support Bounce",
            "order_type": "Buy Limit", "entry": round(price, 1),
            "sl": round(l - rng * 0.02, 1), "tp": round(mid + rng * 0.2, 1),
            "confidence": 0.67, "timeframe": "15M",
            "reasoning": f"Price bounced from {pos*100:.0f}% of range after red candle. Support held. Bounce play targeting mid-range."
        })

    # 15M REJECTION FROM RESISTANCE
    if pos > 0.80 and body < 0 and prev_body > 0:
        signals.append({
            "direction": "SHORT", "setup": "15M Resistance Reject",
            "order_type": "Sell Limit", "entry": round(price, 1),
            "sl": round(h + rng * 0.02, 1), "tp": round(mid - rng * 0.2, 1),
            "confidence": 0.67, "timeframe": "15M",
            "reasoning": f"Price rejected at {pos*100:.0f}% of range. Resistance held. Reversal targeting lower half of range."
        })

    # 15M TREND — series of higher highs/lows
    last6 = m15[:6]
    hh_hl = all(last6[i][2] >= last6[i+1][2] and last6[i][3] >= last6[i+1][3] for i in range(min(5, len(last6)-1)))
    if hh_hl:
        signals.append({
            "direction": "LONG", "setup": "15M Higher Highs",
            "order_type": "Buy Limit", "entry": round(price - rng * 0.1, 1),
            "sl": round(min(c[3] for c in last6) - rng * 0.02, 1),
            "tp": round(price + rng * 0.5, 1),
            "confidence": 0.70, "timeframe": "15M",
            "reasoning": "6 candles of higher highs and higher lows — clear uptrend. Buy on pullback. SL below swing low. Target new highs."
        })

    # 15M TREND — series of lower highs/lows
    lh_ll = all(last6[i][2] <= last6[i+1][2] and last6[i][3] <= last6[i+1][3] for i in range(min(5, len(last6)-1)))
    if lh_ll:
        signals.append({
            "direction": "SHORT", "setup": "15M Lower Highs",
            "order_type": "Sell Limit", "entry": round(price + rng * 0.1, 1),
            "sl": round(max(c[2] for c in last6) + rng * 0.02, 1),
            "tp": round(price - rng * 0.5, 1),
            "confidence": 0.70, "timeframe": "15M",
            "reasoning": "6 candles of lower highs and lower lows — clear downtrend. Sell on rally. SL above swing high. Target new lows."
        })

    # 15M DOUBLE TOP
    if len(m15) >= 8:
        tops = [c[2] for c in m15[:8]]
        peak1 = max(tops[:4])
        peak2 = max(tops[4:])
        if abs(peak1 - peak2) < rng * 0.03 and pos > 0.65:
            signals.append({
                "direction": "SHORT", "setup": "15M Double Top",
                "order_type": "Sell Limit", "entry": round(price + rng * 0.03, 1),
                "sl": round(max(peak1, peak2) + rng * 0.01, 1),
                "tp": round(l + rng * 0.3, 1),
                "confidence": 0.71, "timeframe": "15M",
                "reasoning": f"Double top at {fmt(max(peak1, peak2))} — strong resistance. Failed to break higher twice. Bearish signal. Target lower support."
            })

    # 15M DOUBLE BOTTOM
    if len(m15) >= 8:
        bots = [c[3] for c in m15[:8]]
        dip1 = min(bots[:4])
        dip2 = min(bots[4:])
        if abs(dip1 - dip2) < rng * 0.03 and pos < 0.35:
            signals.append({
                "direction": "LONG", "setup": "15M Double Bottom",
                "order_type": "Buy Limit", "entry": round(price - rng * 0.03, 1),
                "sl": round(min(dip1, dip2) - rng * 0.01, 1),
                "tp": round(h - rng * 0.3, 1),
                "confidence": 0.71, "timeframe": "15M",
                "reasoning": f"Double bottom at {fmt(min(dip1, dip2))} — strong support held twice. Buyers defending. Bullish signal. Target upper range."
            })

    return signals


def analyze_swing():
    """Swing signals on 15M + 1H + Daily."""
    m15 = get_candles("15", 30)
    h1 = get_candles("60", 24)
    d1 = get_candles("1D", 20)

    if len(m15) < 10:
        return None

    price = d1[0][4] if d1 else m15[0][4]

    # Daily levels
    hd = max(c[2] for c in d1)
    ld = min(c[3] for c in d1)
    rd = hd - ld

    # 1H levels
    h1h = max(c[2] for c in h1) if h1 else hd
    h1l = min(c[3] for c in h1) if h1 else ld
    r1h = h1h - h1l

    # Trend: mid-point comparison
    d_mid = len(d1) // 2
    d_trend = (price - d1[d_mid][4]) / d1[d_mid][4] * 100 if d_mid < len(d1) else 0

    # 1H structure
    h1_mid = len(h1) // 2
    h1_trend = (price - h1[h1_mid][4]) / h1[h1_mid][4] * 100 if h1_mid < len(h1) else 0

    signals = []

    # ── SWING LONG: Uptrend pullback to support ──
    if d_trend > 2 and price < h1h - r1h * 0.15:
        fib38 = h1l + r1h * 0.382
        fib50 = h1l + r1h * 0.5
        if abs(price - fib38) / fib38 < 0.01 or abs(price - fib50) / fib50 < 0.01:
            signals.append({
                "direction": "LONG",
                "setup": "Swing Trend Continuation",
                "order_type": "Buy Limit",
                "entry": round(price, 1),
                "sl": round(h1l - r1h * 0.02, 1),
                "tp": round(h1h + r1h * 0.3, 1),
                "confidence": 0.70,
                "timeframe": "1H/Daily",
                "reasoning": (
                    f"Trend +{d_trend:.1f}% — price pulled back to Fib zone (38-50%). "
                    "Buying the dip in an uptrend. High probability continuation. "
                    f"1H support at {fmt(h1l)}. Targeting new highs."
                ),
            })

    # ── SWING SHORT: Downtrend rally to resistance ──
    if d_trend < -2 and price > h1l + r1h * 0.85:
        signals.append({
            "direction": "SHORT",
            "setup": "Swing Trend Reversal",
            "order_type": "Sell Limit",
            "entry": round(price, 1),
            "sl": round(h1h + r1h * 0.02, 1),
            "tp": round(h1l - r1h * 0.3, 1),
            "confidence": 0.68,
            "timeframe": "1H/Daily",
            "reasoning": (
                f"Downtrend {d_trend:.1f}% — price rallied to resistance. "
                "Selling into strength in a bear trend. "
                f"Resistance at {fmt(h1h)}. Target lower lows."
            ),
        })

    # ── SWING BREAKOUT LONG ──
    if d_trend > 1 and price >= hd * 0.998:
        signals.append({
            "direction": "LONG",
            "setup": "Swing Breakout — New Highs",
            "order_type": "Buy Stop",
            "entry": round(hd + rd * 0.01, 1),
            "sl": round(hd - rd * 0.03, 1),
            "tp": round(hd + rd * 0.15, 1),
            "confidence": 0.72,
            "timeframe": "Daily",
            "reasoning": (
                f"Price at {fmt(price)} — testing all-time highs from 20-day window. "
                f"Trend +{d_trend:.1f}% with strong momentum. "
                "Buy stop above resistance — captures breakout continuation."
            ),
        })

    # ── SUPPORT HOLD LONG ──
    if price <= ld * 1.003 and d_trend > 0:
        signals.append({
            "direction": "LONG",
            "setup": "Major Support Bounce",
            "order_type": "Buy Limit",
            "entry": round(price, 1),
            "sl": round(ld - rd * 0.02, 1),
            "tp": round(ld + rd * 0.3, 1),
            "confidence": 0.65,
            "timeframe": "Daily",
            "reasoning": (
                f"Price at {fmt(price)} near 20-day support at {fmt(ld)}. "
                "Buying at major support level with trend aligned. "
                "Stop below support. Target mid-range."
            ),
        })

    return {
        "price": price,
        "d_trend": d_trend,
        "h1_trend": h1_trend,
        "signals": signals,
    }


# ── Message formatter ────────────────────────────────────────
def format_signal(sig, is_scalp=True):
    d = "\U0001f7e2" if sig["direction"] == "LONG" else "\U0001f534"
    strategy = sig.get("strategy", "")
    if strategy == "SMC":
        label = "SMC \U0001f9e0"
    elif is_scalp:
        label = "SCALP"
    else:
        label = "SWING"
    r = sig["sl"] - sig["entry"] if sig["direction"] == "LONG" else sig["entry"] - sig["sl"]
    reward = sig["tp"] - sig["entry"] if sig["direction"] == "LONG" else sig["entry"] - sig["tp"]
    rr = abs(reward / r) if r != 0 else 0

    conf_stars = "\u2605" * int(sig["confidence"] * 5) + "\u2606" * (5 - int(sig["confidence"] * 5))

    return (
        f"{d} <b>{sig['direction']} — {label} [{sig['setup']}]</b>\n"
        f"<b>Symbol:</b> <code>{sig.get('symbol', DEFAULT_SYMBOL)}</code> {sig.get('symbol_name','')}\n"
        f"<b>Entry:</b> <code>{fmt(sig['entry'])}</code> | {sig['timeframe']}\n"
        f"<b>Order:</b> {sig['order_type']}\n"
        f"<b>Confidence:</b> {conf_stars} ({sig['confidence']:.0%})\n\n"
        f"<b>SL:</b> <code>{fmt(sig['sl'])}</code> "
        f"| <b>TP:</b> <code>{fmt(sig['tp'])}</code>\n"
        f"<b>R:R:</b> 1:{rr:.1f}\n\n"
        f"<b>Why:</b> <i>{sig['reasoning']}</i>\n\n"
        f"<i>{datetime.now(TZ).strftime('%H:%M')} Amman</i>"
    )


# ── Dedup ────────────────────────────────────────────────────
_scalp_seen = {}
_swing_seen = {}
_smc_seen = {}


def is_new(sig, cache, max_age=600):
    key = f"{sig['direction']}_{sig['setup']}"
    now = time.time()
    if key in cache and now - cache[key] < max_age:
        return False
    cache[key] = now
    # Clean old entries
    for k in list(cache.keys()):
        if now - cache[k] > max_age + 60:
            del cache[k]
    return True


# ── Main loop ────────────────────────────────────────────────
def main():
    logger.info("=" * 60)
    logger.info("CFI:US100 COMPREHENSIVE MONITOR STARTED")
    logger.info("Timezone: Asia/Amman (GMT+3)")
    logger.info("Scalp check: %ds | Swing check: %ds | SMC check: %ds", CHECK_SCALP_SEC, CHECK_SWING_SEC, CHECK_SMC_SEC)
    logger.info("Sessions: Asia/London/NY + Market Open/Close + News")
    logger.info("SMC: BOS/CHoCH/OB/FVG/Liquidity Sweeps")
    logger.info("=" * 60)

    time.sleep(1)
    alert(
        "\U0001f514 <b>US100 MONITOR IS LIVE</b>\n\n"
        "\U0001f539 Scalp signals every 45s (1M/5M/15M)\n"
        "\U0001f9e0 SMC/ICT signals every 60s (BOS, CHoCH, OB, FVG, Sweeps)\n"
        "\U0001f539 Swing signals every 5min (1H/Daily)\n"
        "\U0001f539 Session open/close alerts\n"
        "\U0001f539 Market open/close alerts\n"
        "\U0001f539 Brief news (hourly)\n"
        "\U0001f539 Every signal includes reason + SL + TP\n\n"
        "<i>You will be alerted automatically.</i>"
    )

    last_scalp = 0
    last_swing = 0
    last_smc = 0
    last_session_check = 0
    last_news_check = 0

    while True:
        try:
            now = time.time()
            active_symbols = get_active_symbols()
            if not active_symbols:
                active_symbols = {DEFAULT_SYMBOL: {"name": "Nasdaq 100 SPOT"}}

            # ── Subscription check (every 60s) ──
            if now - _last_subscription_check > 60:
                check_subscriptions()
                _last_subscription_check = now

            # ── Session alerts (every 2 min) ──
            if now - last_session_check > 120:
                session_alerts = check_sessions()
                for sa in session_alerts:
                    alert(sa)
                    time.sleep(1)
                last_session_check = now

            # ── News (every hour) ──
            if now - last_news_check > 3600:
                news_alerts = check_news()
                for na in news_alerts:
                    alert(na)
                    time.sleep(1)
                last_news_check = now

            # ── SCALP + SMC + SWING per symbol ──
            for symbol, sym_info in active_symbols.items():
                sym_name = sym_info.get("name", symbol)

                # SCALP
                if now - last_scalp > CHECK_SCALP_SEC:
                    m1 = get_candles(symbol, "1", 60)
                    m5 = get_candles(symbol, "5", 40)
                    m15 = get_candles(symbol, "15", 20)

                    all_scalp = []
                    sigs_1m = analyze_candles_1m(m1)
                    for sig in sigs_1m:
                        sig["symbol"] = symbol
                        sig["symbol_name"] = sym_name
                        if is_new(sig, _scalp_seen, 300):
                            all_scalp.append(sig)

                    sigs_5m = analyze_candles_5m(m5, m1)
                    for sig in sigs_5m:
                        sig["symbol"] = symbol
                        sig["symbol_name"] = sym_name
                        if is_new(sig, _scalp_seen, 600):
                            all_scalp.append(sig)

                    sigs_15m = analyze_candles_15m(m15)
                    for sig in sigs_15m:
                        sig["symbol"] = symbol
                        sig["symbol_name"] = sym_name
                        if is_new(sig, _scalp_seen, 900):
                            all_scalp.append(sig)

                    for sig in all_scalp:
                        logger.info("SCALP [%s|%s]: %s %s", symbol, sig["timeframe"], sig["direction"], sig["setup"])
                        alert(format_signal(sig, is_scalp=True))
                        time.sleep(1.2)

                # SMC
                if now - last_smc > CHECK_SMC_SEC:
                    m15_smc = get_candles(symbol, "15", 50)
                    m5_smc = get_candles(symbol, "5", 40)
                    m1_smc = get_candles(symbol, "1", 60)
                    smc_sigs = analyze_smc(m15_smc, m5_smc, m1_smc)
                    for sig in smc_sigs:
                        sig["symbol"] = symbol
                        sig["symbol_name"] = sym_name
                        if is_new(sig, _smc_seen, 600):
                            logger.info("SMC [%s]: %s %s", symbol, sig["direction"], sig["setup"])
                            alert(format_signal(sig, is_scalp=True))
                            time.sleep(1.2)

            # Update loop timers
            if now - last_scalp > CHECK_SCALP_SEC:
                last_scalp = now
            if now - last_smc > CHECK_SMC_SEC:
                last_smc = now

            # ── Swing signals ──
            if now - last_swing > CHECK_SWING_SEC:
                sw = analyze_swing()
                if sw and sw.get("signals"):
                    for sig in sw["signals"]:
                        if is_new(sig, _swing_seen, 1800):  # 30 min dedup
                            logger.info("SWING: %s %s @ %s", sig["direction"], sig["setup"], fmt(sig["entry"]))
                            alert(format_signal(sig, is_scalp=False))
                            time.sleep(1.5)
                last_swing = now

            time.sleep(10)

        except KeyboardInterrupt:
            alert("\u23f9 <b>US100 Monitor Stopped</b>")
            logger.info("Shutdown")
            break
        except Exception as e:
            logger.error("Error: %s", e, exc_info=True)
            time.sleep(15)


if __name__ == "__main__":
    main()
