"""Telegram Signal Bot: sends trading signals and receives analysis commands.

Uses direct HTTP calls to Telegram Bot API — no extra dependencies beyond `requests`
(already in TradingAgents).

Setup:
  1. Create a bot with @BotFather on Telegram → get BOT_TOKEN
  2. Get your chat ID (send /start to @userinfobot or your bot)
  3. Set in .env: TELEGRAM_BOT_TOKEN=..., TELEGRAM_CHAT_ID=...
  4. Run: python -m tradingagents.telegram.bot
"""

import json
import logging
import os
import time
from datetime import datetime

import requests

from tradingagents.dataflows.tv_realtime import (
    get_live_chart,
    get_live_indicator,
    get_technical_analysis,
    search_symbol,
)

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot"


# ── Telegram API helpers ──────────────────────────────────────
def _api(token, method, params=None):
    url = f"{TELEGRAM_API}{token}/{method}"
    try:
        r = requests.post(url, json=params, timeout=15)
        return r.json()
    except Exception as e:
        logger.error("Telegram API error: %s", e)
        return {"ok": False, "description": str(e)}


def send_message(token, chat_id, text, parse_mode="HTML", reply_markup=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return _api(token, "sendMessage", params)


def edit_message(token, chat_id, msg_id, text, parse_mode="HTML"):
    return _api(token, "editMessageText", {
        "chat_id": chat_id, "message_id": msg_id,
        "text": text, "parse_mode": parse_mode,
    })


# ── Formatting helpers ────────────────────────────────────────
def _fmt_num(n):
    """Format number: 27300.94 → '27,300.94'"""
    if n is None:
        return "—"
    s = f"{n:,.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return s


def _arrow(open_val, close_val):
    """Return direction arrow + emoji for a candle."""
    if close_val > open_val:
        return "\U0001f7e2"  # green dot (bullish)
    elif close_val < open_val:
        return "\U0001f534"  # red dot (bearish)
    return "\u26aa"  # white dot (neutral)


def _signal_emoji(signal):
    s = signal.lower()
    if s == "buy":
        return "\U0001f7e2 BUY"
    if s == "sell":
        return "\U0001f534 SELL"
    return "\u26aa WAIT"


def _conf_bar(confidence):
    """0.0 - 1.0 → visual confidence bar."""
    if confidence >= 0.8:
        stars = "\u2605\u2605\u2605\u2605\u2605"
    elif confidence >= 0.6:
        stars = "\u2605\u2605\u2605\u2605\u2606"
    elif confidence >= 0.4:
        stars = "\u2605\u2605\u2605\u2606\u2606"
    elif confidence >= 0.2:
        stars = "\u2605\u2605\u2606\u2606\u2606"
    else:
        stars = "\u2605\u2606\u2606\u2606\u2606"
    return stars


# ── Analysis functions ────────────────────────────────────────
def _resolve_symbol(query):
    """Search and return the best TradingView symbol for a query."""
    results = search_symbol(query)
    lines = results.strip().split("\n")
    if len(lines) < 2:
        return None, None, f"No symbol found for: {query}"
    first = lines[1].split(",")
    return first[0], first[1] if len(first) > 1 else query, None


def _analyze_signal(symbol, name=""):
    """Full technical signal analysis with daily/4H candles."""
    result = get_live_chart(symbol, timeframe="1D", range_bars=20)
    lines = result.strip().split("\n")

    meta = {}
    candles = []
    in_data = False
    for line in lines:
        if line.startswith("# "):
            kv = line[2:].split(": ", 1)
            if len(kv) == 2:
                meta[kv[0].strip()] = kv[1].strip()
        elif line.startswith("time,"):
            in_data = True
        elif in_data and line.strip():
            parts = line.split(",")
            if len(parts) >= 6:
                try:
                    candles.append([float(p) for p in parts])
                except ValueError:
                    pass

    if len(candles) < 3:
        return None

    recent = candles[0]
    prev = candles[-1] if len(candles) > 1 else recent
    price = recent[4]  # close
    high_20 = max(c[2] for c in candles if c[2] > 0)
    low_20 = min(c[3] for c in candles if c[3] > 0)

    # Trend: compare recent close to 10 bars ago
    mid_idx = min(9, len(candles) - 1)
    trend_close = candles[mid_idx][4]
    trend_pct = ((price - trend_close) / trend_close) * 100

    # Find swing low (last 5 bars) for SL placement
    recent5 = candles[:5]
    swing_low = min(c[3] for c in recent5 if c[3] > 0)
    swing_high = max(c[2] for c in recent5 if c[2] > 0)

    # Signal logic
    if trend_pct > 1 and recent[4] > recent[1] and price > (high_20 + low_20) / 2:
        signal = "Buy"
        entry = price
        sl = round(swing_low - (swing_high - swing_low) * 0.2, 2)
        tp = round(price + (price - sl) * 2.0, 2)
        confidence = min(0.8, 0.5 + abs(trend_pct) * 0.05)
    elif trend_pct < -1 and price < (high_20 + low_20) / 2:
        signal = "Sell"
        entry = price
        sl = round(swing_high + (swing_high - swing_low) * 0.2, 2)
        tp = round(price - (sl - price) * 2.0, 2)
        confidence = min(0.8, 0.5 + abs(trend_pct) * 0.05)
    else:
        signal = "Wait"
        entry = price
        sl = round(swing_low, 2)
        tp = round(swing_high, 2)
        confidence = 0.35

    description = name or meta.get("Description", symbol)

    return {
        "symbol": symbol,
        "name": description,
        "price": price,
        "signal": signal,
        "entry": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "confidence": confidence,
        "trend_pct": trend_pct,
        "high_20": high_20,
        "low_20": low_20,
        "swing_high": swing_high,
        "swing_low": swing_low,
    }


def _analyze_scalp(symbol, name=""):
    """Scalp analysis using 15M and 5M candles."""
    m15 = get_live_chart(symbol, timeframe="15", range_bars=30)
    m5 = get_live_chart(symbol, timeframe="5", range_bars=30)

    def _parse(data):
        candles = []
        in_data = False
        for line in data.strip().split("\n"):
            if line.startswith("time,"):
                in_data = True
            elif in_data and line.strip():
                parts = line.split(",")
                if len(parts) >= 6:
                    try:
                        candles.append([float(p) for p in parts])
                    except ValueError:
                        pass
        return candles

    c15 = _parse(m15)
    c5 = _parse(m5)

    if len(c15) < 5:
        return None

    price = c15[0][4]
    h15 = max(c[2] for c in c15)
    l15 = min(c[3] for c in c15)
    rng = h15 - l15

    # Check if price near top/bottom of range
    top_pct = (price - l15) / rng if rng > 0 else 0.5

    # Volume trend on last 5
    vol_avg_recent = sum(c[5] for c in c15[:5]) / 5
    vol_avg_full = sum(c[5] for c in c15) / len(c15)

    # Support/resistance from 15M
    if top_pct > 0.72 and vol_avg_recent < vol_avg_full * 0.9:
        signal = "Sell"
        entry = price
        sl = round(h15 * 1.001, 2)
        tp = round(l15 + rng * 0.25, 2)
        confidence = 0.65
    elif top_pct < 0.28 and vol_avg_recent > vol_avg_full * 1.1:
        signal = "Buy"
        entry = price
        sl = round(l15 * 0.999, 2)
        tp = round(h15 - rng * 0.25, 2)
        confidence = 0.60
    elif top_pct > 0.5:
        signal = "Wait"
        entry = price
        sl = round(l15, 2)
        tp = round(h15, 2)
        confidence = 0.30
    else:
        signal = "Wait"
        entry = price
        sl = round(l15, 2)
        tp = round(h15, 2)
        confidence = 0.30

    return {
        "symbol": symbol,
        "name": name or symbol,
        "price": price,
        "signal": signal,
        "entry": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "confidence": confidence,
        "range_h": h15,
        "range_l": l15,
        "top_pct": top_pct,
    }


# ── Message builders ──────────────────────────────────────────
def build_signal_message(data):
    s = _signal_emoji(data["signal"])
    stars = _conf_bar(data["confidence"])
    pct = data.get("trend_pct", 0)
    trend = f"+{pct:.1f}%" if pct > 0 else f"{pct:.1f}%"

    return (
        f"<b>\U0001f4c8 {data['name']}</b>\n"
        f"<code>{data['symbol']}</code>\n\n"
        f"<b>Signal:</b> {s}\n"
        f"<b>Price:</b> {_fmt_num(data['price'])}\n"
        f"<b>Trend:</b> {trend} (20 bars)\n"
        f"<b>Confidence:</b> {stars}\n\n"
        f"<b>\U0001f3af Entry:</b> {_fmt_num(data['entry'])}\n"
        f"<b>\U0001f6d1 Stop:</b>   {_fmt_num(data['stop_loss'])}\n"
        f"<b>\U0001f3c6 Target:</b> {_fmt_num(data['take_profit'])}\n\n"
        f"<i>Analyzed at {datetime.now().strftime('%H:%M UTC')}</i>"
    )


def build_scalp_message(data):
    s = _signal_emoji(data["signal"])
    stars = _conf_bar(data["confidence"])

    return (
        f"<b>\u26a1 SCALP: {data['name']}</b>\n"
        f"<code>{data['symbol']}</code> | 15M/5M\n\n"
        f"<b>Signal:</b> {s}\n"
        f"<b>Price:</b> {_fmt_num(data['price'])}\n"
        f"<b>Range:</b> {_fmt_num(data['range_l'])} – {_fmt_num(data['range_h'])}\n"
        f"<b>Confidence:</b> {stars}\n\n"
        f"<b>\U0001f3af Entry:</b> {_fmt_num(data['entry'])}\n"
        f"<b>\U0001f6d1 Stop:</b>   {_fmt_num(data['stop_loss'])}\n"
        f"<b>\U0001f3c6 Target:</b> {_fmt_num(data['take_profit'])}\n\n"
        f"<i>Analyzed at {datetime.now().strftime('%H:%M UTC')}</i>"
    )


def build_ta_message(symbol, result):
    return (
        f"<b>\U0001f4ca TA: {symbol}</b>\n"
        f"<pre>{result[:3500]}</pre>"
    )


# ── Bot runner ────────────────────────────────────────────────
class SignalBot:
    def __init__(self, token=None, chat_id=None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.running = False

        if not self.token:
            logger.warning("TELEGRAM_BOT_TOKEN not set")
        if not self.chat_id:
            logger.warning("TELEGRAM_CHAT_ID not set (bot can still respond to any chat)")

    def send(self, text, parse_mode="HTML", reply_markup=None):
        if not self.token or not self.chat_id:
            return {"ok": False, "description": "No token or chat_id configured"}
        return send_message(self.token, self.chat_id, text, parse_mode, reply_markup)

    def handle_command(self, chat_id, text):
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower().lstrip("/")
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "start":
            return self.send_msg(chat_id,
                "<b>\U0001f4c8 TradingAgents Signal Bot</b>\n\n"
                "Commands:\n"
                "/analyze SYMBOL — Full technical signal\n"
                "/scalp SYMBOL — Scalp signal (15M/5M)\n"
                "/ta SYMBOL — TradingView TA summary\n"
                "/price SYMBOL — Current price\n\n"
                "Examples:\n"
                "<code>/analyze CFI:US100</code>\n"
                "<code>/scalp NASDAQ:AAPL</code>\n"
                "<code>/ta BINANCE:BTCUSDT</code>"
            )

        if not arg:
            return self.send_msg(chat_id, f"Usage: <code>/{cmd} SYMBOL</code>\nExample: <code>/{cmd} NASDAQ:AAPL</code>")

        if cmd == "price":
            result = get_live_chart(arg, timeframe="1D", range_bars=2)
            lines = result.strip().split("\n")
            price = "N/A"
            for line in lines:
                if line.startswith("# Price:"):
                    price = line.split(":")[-1].strip()
                if not line.startswith("#") and not line.startswith("time"):
                    parts = line.split(",")
                    if len(parts) >= 5:
                        price = f"{parts[4]}"
            return self.send_msg(chat_id,
                f"<b>\U0001f4b0 {arg}</b>\nPrice: <code>{price}</code>")

        if cmd == "analyze":
            self.send_msg(chat_id, f"\U0001f50d Analyzing {arg}...")
            data = _analyze_signal(arg)
            if data is None:
                return self.send_msg(chat_id, f"Cannot analyze {arg}. Try a valid TradingView symbol like <code>NASDAQ:AAPL</code>")
            return self.send_msg(chat_id, build_signal_message(data))

        if cmd == "scalp":
            self.send_msg(chat_id, f"\U0001f50d Scalping {arg}...")
            data = _analyze_scalp(arg)
            if data is None:
                return self.send_msg(chat_id, f"Cannot scalp {arg}. Needs enough 15M data.")
            return self.send_msg(chat_id, build_scalp_message(data))

        if cmd == "ta":
            self.send_msg(chat_id, f"\U0001f50d Getting TA for {arg}...")
            result = get_technical_analysis(arg)
            if not result.strip():
                return self.send_msg(chat_id, f"No technical analysis available for {arg}")
            if len(result) > 3900:
                result = result[:3900] + "\n..."
            return self.send_msg(chat_id, f"<pre>{result}</pre>")

        return self.send_msg(chat_id, f"Unknown command: /{cmd}")

    def send_msg(self, chat_id, text, parse_mode="HTML"):
        return send_message(self.token, chat_id, text, parse_mode)

    def run(self, poll_interval=2.0):
        """Start long-polling for Telegram commands."""
        if not self.token:
            logger.error("Cannot start bot: TELEGRAM_BOT_TOKEN not set in .env")
            return

        self.running = True
        offset = 0
        logger.info("Bot started. Listening for /analyze, /scalp, /ta, /price...")

        while self.running:
            try:
                resp = _api(self.token, "getUpdates", {
                    "offset": offset, "timeout": 30
                })
                if resp.get("ok"):
                    for update in resp.get("result", []):
                        offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        chat_id = msg.get("chat", {}).get("id")
                        text = msg.get("text", "")
                        if text and chat_id:
                            self.handle_command(chat_id, text)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("Poll error: %s", e)
                time.sleep(5)

    def stop(self):
        self.running = False

    def send_signal(self, symbol):
        """Send a full signal analysis for a symbol to the configured chat."""
        data = _analyze_signal(symbol)
        if data is None:
            return {"ok": False, "description": f"Could not analyze {symbol}"}
        msg = build_signal_message(data)
        return self.send(msg)

    def send_scalp(self, symbol):
        """Send a scalp signal for a symbol to the configured chat."""
        data = _analyze_scalp(symbol)
        if data is None:
            return {"ok": False, "description": f"Could not scalp {symbol}"}
        msg = build_scalp_message(data)
        return self.send(msg)


def run_bot():
    """Entry point: run the Telegram signal bot."""
    logging.basicConfig(level=logging.INFO)
    bot = SignalBot()
    if not bot.token:
        print("ERROR: Set TELEGRAM_BOT_TOKEN in .env")
        print("  1. Create a bot with @BotFather on Telegram")
        print("  2. Copy the token to your .env file")
        return
    bot.run()


if __name__ == "__main__":
    run_bot()
