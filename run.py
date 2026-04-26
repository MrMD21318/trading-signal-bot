"""US100 Signal Suite — Docker entry point.

Uses the professional signal engine:
- Multi-TP (TP1/TP2/TP3)
- Signal scoring & conflict resolution
- TP/SL hit tracking
- Current price in every signal header
"""

import os
import sys
import time
import threading
import logging

os.environ.setdefault("SMC_CREDIT", "0")
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("runner")

from dashboard import run_dashboard
from database import get_users_for_symbol, log_alert, get_active_users_with_subs


def run_bot_poller():
    from tg_bot import poll_updates
    logger.info("Bot poller started")
    poll_updates()


def run_monitor():
    import pytz
    from run_us100_monitor import (
        get_candles, analyze_candles_1m, analyze_candles_5m,
        analyze_candles_15m, check_sessions, check_news,
        get_current_session, get_session_emoji,
    )
    from symbol_manager import get_active_symbols
    from smc_analysis import analyze_smc
    from signal_engine import (
        select_best_signals, calculate_multi_tp, format_professional_signal,
        check_active_signals, track_signal,
    )

    TOK = os.getenv("TELEGRAM_BOT_TOKEN", "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A")
    TZ = pytz.timezone("Asia/Amman")
    DEFAULT = "CFI:US100"

    def tg_send(token, chat_id, text):
        import requests
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                         json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        except:
            pass

    logger.info("Professional Signal Engine started")
    time.sleep(3)


def _analyze_swing(candles, tf_label, symbol, sym_name):
    """Analyze higher timeframe for trend-following swing signals."""
    if len(candles) < 8:
        return []

    price = candles[0][4]
    recent = candles[:max(3, len(candles)//4)]

    h = max(c[2] for c in recent)
    l = min(c[3] for c in recent)
    rng = h - l
    pos = (price - l) / rng if rng > 0 else 0.5

    # Trend: compare recent to older
    mid = len(candles) // 2
    old_close = candles[mid][4]
    trend_pct = (price - old_close) / old_close * 100 if old_close else 0

    signals = []

    # Uptrend pullback to support
    if trend_pct > 1 and pos < 0.35:
        signals.append({
            "symbol": symbol, "symbol_name": sym_name, "direction": "LONG",
            "setup": f"{tf_label} Trend Pullback",
            "order_type": "Buy Limit", "entry": round(price, 1),
            "sl": round(l - rng * 0.02, 1),
            "tp": round(h + rng * 0.5, 1),
            "confidence": 0.68, "timeframe": tf_label,
            "price_now": price,
            "reasoning": f"Uptrend +{trend_pct:.1f}% — price pulled to {pos*100:.0f}% of {tf_label} range. Buying dip in trend with SL below support. Target new highs.",
        })

    # Breakout above range
    if trend_pct > 0.5 and price >= h * 0.998:
        signals.append({
            "symbol": symbol, "symbol_name": sym_name, "direction": "LONG",
            "setup": f"{tf_label} Breakout",
            "order_type": "Buy Stop", "entry": round(h + rng * 0.01, 1),
            "sl": round(l + rng * 0.3, 1),
            "tp": round(h + rng, 1),
            "confidence": 0.72, "timeframe": tf_label,
            "price_now": price,
            "reasoning": f"Price breaking {tf_label} highs at {fmt2(h)}. Trend +{trend_pct:.1f}%. Buy stop above resistance captures breakout momentum.",
        })

    # Downtrend rally to resistance
    if trend_pct < -1 and pos > 0.65:
        signals.append({
            "symbol": symbol, "symbol_name": sym_name, "direction": "SHORT",
            "setup": f"{tf_label} Trend Rally Short",
            "order_type": "Sell Limit", "entry": round(price, 1),
            "sl": round(h + rng * 0.02, 1),
            "tp": round(l - rng * 0.5, 1),
            "confidence": 0.68, "timeframe": tf_label,
            "price_now": price,
            "reasoning": f"Downtrend {trend_pct:.1f}% — price rallied to {pos*100:.0f}% of {tf_label} range. Selling into strength with SL above resistance.",
        })

    # Support bounce
    if price <= l * 1.005 and trend_pct > -0.5:
        signals.append({
            "symbol": symbol, "symbol_name": sym_name, "direction": "LONG",
            "setup": f"{tf_label} Support Bounce",
            "order_type": "Buy Limit", "entry": round(price, 1),
            "sl": round(l - rng * 0.03, 1),
            "tp": round(l + rng * 0.6, 1),
            "confidence": 0.65, "timeframe": tf_label,
            "price_now": price,
            "reasoning": f"Price at {tf_label} support {fmt2(l)}. Buy at demand zone. SL below support. Target mid-range.",
        })

    for sig in _analyze_swing(h1, "1H", symbol, sym_name):
        signals.append(sig)
    signals[-1]["session"] = f"{session_emoji} {session_name}"
    return signals


def fmt2(n):
    return f"{n:,.1f}" if n else "—"


def run_monitor():

    active_users = get_active_users_with_subs()
    if active_users:
        for u in active_users[:5]:
            tg_send(TOK, u["chat_id"],
                "Signal Monitor v3 Online\nMulti-TP | SMC+Scalp | TP/SL tracking")

    last_scan = last_session = last_news = last_track = last_heartbeat = 0

    while True:
        try:
            now = time.time()
            active_syms = get_active_symbols()
            if not active_syms:
                active_syms = {DEFAULT: {"name": "Nasdaq 100 SPOT"}}

            for symbol, sym_info in active_syms.items():
                sym_name = sym_info.get("name", symbol)
                target_users = get_users_for_symbol(symbol) or get_active_users_with_subs()
                if not target_users:
                    continue

                # Check TP/SL hits every 30s
                if now - last_track > 30:
                    m1_price = get_candles(symbol, "1", 3)
                    if m1_price:
                        current_price = m1_price[0][4]
                        alerts = check_active_signals(symbol, current_price)
                        for a in alerts:
                            for u in target_users:
                                tg_send(TOK, u["chat_id"], a)

                # Collect all signals
                all_signals = []
                session_key, session_name = get_current_session()
                session_emoji = get_session_emoji(session_key)

                if now - last_scan > 45:
                    m1 = get_candles(symbol, "1", 60)
                    m5 = get_candles(symbol, "5", 40)
                    m15 = get_candles(symbol, "15", 30)
                    m15_smc = get_candles(symbol, "15", 50)

                    if m1:
                        for sig in analyze_candles_1m(m1):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m1[0][4]; sig["session"] = f"{session_emoji} {session_name}"
                            all_signals.append(sig)
                    if m5:
                        for sig in analyze_candles_5m(m5):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m5[0][4]; sig["session"] = f"{session_emoji} {session_name}"
                            all_signals.append(sig)
                    if m15:
                        for sig in analyze_candles_15m(m15):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m15[0][4]; sig["session"] = f"{session_emoji} {session_name}"
                            all_signals.append(sig)
                    if m15_smc:
                        for sig in analyze_smc(m15_smc, m5, m1):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m15_smc[0][4]; sig["strategy"] = "SMC"
                            sig["session"] = f"{session_emoji} {session_name}"
                            all_signals.append(sig)

                    # 1H Swing
                    h1 = get_candles(symbol, "60", 30)
                    if h1 and len(h1) >= 10:
                        for sig in _analyze_swing(h1, "1H", symbol, sym_name):
                            sig["session"] = f"{session_emoji} {session_name}"
                            all_signals.append(sig)

                    # Daily Swing
                    d1 = get_candles(symbol, "1D", 30)
                    if d1 and len(d1) >= 8:
                        for sig in _analyze_swing(d1, "Daily", symbol, sym_name):
                            sig["session"] = f"{session_emoji} {session_name}"
                            all_signals.append(sig)

                if now - last_scan > 45:
                    last_scan = now
                if now - last_track > 30:
                    last_track = now

                # Filter: only best signals, no conflicts
                best = select_best_signals(all_signals)

                for sig in best:
                    if get_active_signal_count(symbol) >= 2:
                        continue

                    tp1, tp2, tp3 = calculate_multi_tp(sig)
                    sig["tp1"] = tp1; sig["tp2"] = tp2; sig["tp3"] = tp3

                    msg = format_professional_signal(sig)
                    for u in target_users:
                        tg_send(TOK, u["chat_id"], msg)
                        log_alert(u["chat_id"], symbol, sig["direction"], sig["setup"],
                                 sig["entry"], sig["sl"], tp2, sig.get("strategy", ""),
                                 sig.get("timeframe", ""), sig.get("confidence", 0))

                    track_signal(symbol, sig["direction"], sig["entry"], sig["sl"],
                                tp1, tp2, tp3, sig["setup"], sig.get("timeframe", ""),
                                sig.get("confidence", 0))
                    time.sleep(1.2)

            # Sessions & news
            if now - last_session > 120:
                for sa in check_sessions():
                    for u in get_active_users_with_subs():
                        tg_send(TOK, u["chat_id"], sa)
                last_session = now
            if now - last_news > 3600:
                for na in check_news():
                    for u in get_active_users_with_subs():
                        tg_send(TOK, u["chat_id"], na)
                last_news = now

            # Heartbeat every 30 min so you know system is alive
            if now - last_heartbeat > 1800:
                for u in get_active_users_with_subs():
                    from signal_engine import get_active_signal_count
                    active_count = sum(get_active_signal_count(s) for s in active_syms)
                    tg_send(TOK, u["chat_id"],
                        f"\u2705 Monitor Active\nTracking {len(active_syms)} symbols\n{active_count} open positions\n"
                        "Next scan in 45s")
                last_heartbeat = now

            time.sleep(10)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Monitor error: %s", e, exc_info=True)
            time.sleep(15)


if __name__ == "__main__":
    logger.info("Starting US100 Signal Suite v3...")
    threading.Thread(target=run_bot_poller, daemon=True).start()
    time.sleep(1)
    threading.Thread(target=lambda: run_dashboard(port=5000), daemon=True).start()
    time.sleep(1)
    run_monitor()
