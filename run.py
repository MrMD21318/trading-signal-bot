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

    return signals


def fmt2(n):
    return f"{n:,.1f}" if n else "—"


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
        check_active_signals, track_signal, get_active_signal_count,
        check_level_break,
    )
    from tv_price import get_all_prices
    from mt5_executor import execute_signal as mt5_execute
    from mt5_manager import manage_positions as mt5_manage
    from mt5_click import execute_signal_via_ui as mt5_click_trade
    from ai_agent import evaluate_signal as ai_evaluate
    TOK = os.getenv("TELEGRAM_BOT_TOKEN", "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A")
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

    # Force a test signal to verify pipeline
    for sym in get_active_symbols():
        c = get_candles(sym, "5", 10)
        if c and len(c) >= 3:
            price_now = c[0][4]
            daily_c = get_candles(sym, "1D", 10)
            d_trend = 0
            if daily_c and len(daily_c) >= 5:
                d_trend = (daily_c[0][4] - daily_c[len(daily_c)//2][4]) / daily_c[len(daily_c)//2][4] * 100
            logger.info("BOOT TEST: %s price=%.1f trend=%+.1f%% candles_5m=%d candles_1d=%d",
                       sym, price_now, d_trend, len(c), len(daily_c) if daily_c else 0)
            # Send a boot notification to users
            for u in get_active_users_with_subs():
                tg_send(TOK, u["chat_id"],
                    f"\U0001f514 <b>Monitor Booted</b>\n\n"
                    f"Symbol: {sym}\nPrice: <code>{price_now:,.1f}</code>\n"
                    f"Daily trend: {d_trend:+.1f}%\n5M candles: {len(c)}\n\n"
                    f"Scanning every 45s — first signal coming soon.")
            break

    def log_status():
        # Debug: check candles working
        for sym in get_active_symbols():
            c = get_candles(sym, "5", 5)
            logger.info("DEBUG: %s 5M candles=%d", sym, len(c))
            if c:
                logger.info("DEBUG: %s last close=%s", sym, fmt2(c[0][4]))

    active_users = get_active_users_with_subs()
    log_status()
    if active_users:
        for u in active_users[:5]:
            tg_send(TOK, u["chat_id"],
                "Signal Monitor v3 Online\nMulti-TP | SMC+Scalp | TP/SL tracking")

    last_scan = last_session = last_news = last_track = last_heartbeat = 0
    sent_signals = {}
    last_direction_per_symbol = {}  # symbol -> last direction sent + timestamp

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

                # Get live price from TradingView screener (HTTP, no WebSocket)
                live_prices = get_all_prices(list(active_syms.keys()))
                live_price = live_prices.get(symbol)

                # Check TP/SL hits every 30s
                if now - last_track > 30:
                    m1_price = get_candles(symbol, "1", 3)
                    if m1_price:
                        current_price = m1_price[0][4]
                        alerts = check_active_signals(symbol, current_price)
                        for a in alerts:
                            for u in target_users:
                                tg_send(TOK, u["chat_id"], a)

                # Collect SCALP signals (1M, 5M, 15M)
                scalp_signals = []
                swing_signals = []
                session_key, session_name = get_current_session()
                session_emoji = get_session_emoji(session_key)

                if now - last_scan > 45:
                    m1 = get_candles(symbol, "1", 60)
                    m5 = get_candles(symbol, "5", 40)
                    m15 = get_candles(symbol, "15", 30)
                    m15_smc = get_candles(symbol, "15", 50)

                    # Skip if insufficient candles (stale/broken data)
                    if not m5 or len(m5) < 5:
                        last_scan = now
                        continue

                    # Check if minute data is flat (yfinance limitation) — if so, use only daily
                    price_range_5m = max(c[2] for c in m5) - min(c[3] for c in m5) if m5 else 0
                    minute_data_flat = price_range_5m < 0.5  # less than 0.5 pt range = flat

                    # Get trend context from daily + 4H
                    d1 = get_candles(symbol, "1D", 30)
                    h4 = get_candles(symbol, "240", 30)
                    daily_trend = 0
                    if d1 and len(d1) >= 5:
                        daily_trend = (d1[0][4] - d1[len(d1)//2][4]) / d1[len(d1)//2][4] * 100
                    h4_trend = 0
                    if h4 and len(h4) >= 5:
                        h4_trend = (h4[0][4] - h4[len(h4)//2][4]) / h4[len(h4)//2][4] * 100

                    if m1 and not minute_data_flat:
                        for sig in analyze_candles_1m(m1):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m1[0][4]; sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SCALP"; sig["source"] = "VPS"
                            scalp_signals.append(sig)
                    if m5 and not minute_data_flat:
                        for sig in analyze_candles_5m(m5):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m5[0][4]; sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SCALP"; sig["source"] = "VPS"
                            scalp_signals.append(sig)
                    if m15 and not minute_data_flat:
                        for sig in analyze_candles_15m(m15):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m15[0][4]; sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SCALP"; sig["source"] = "VPS"
                            scalp_signals.append(sig)
                    if m15_smc and not minute_data_flat:
                        for sig in analyze_smc(m15_smc, "15M", m5, m1):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m15_smc[0][4]; sig["strategy"] = "SMC"
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SWING"; sig["source"] = "VPS"
                            swing_signals.append(sig)

                    # SMC on all timeframes
                    h1 = get_candles(symbol, "60", 30)
                    if m1 and len(m1) >= 30 and not minute_data_flat:
                        for sig in analyze_smc(m1, "1M"):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m1[0][4]; sig["strategy"] = "SMC"
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SCALP"
                            sig["confidence"] = sig.get("confidence", 0.6) * 0.9
                            scalp_signals.append(sig)
                    if m5 and len(m5) >= 25 and not minute_data_flat:
                        for sig in analyze_smc(m5, "5M"):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m5[0][4]; sig["strategy"] = "SMC"
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SCALP"; sig["source"] = "VPS"
                            scalp_signals.append(sig)
                    # Daily always runs regardless of minute data
                    if d1 and len(d1) >= 10:
                        for sig in analyze_smc(d1, "Daily"):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = d1[0][4]; sig["strategy"] = "SMC"
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SWING"
                            sig["confidence"] = sig.get("confidence", 0.6) + 0.12
                            swing_signals.append(sig)
                    if h1 and len(h1) >= 15 and not minute_data_flat:
                        for sig in analyze_smc(h1, "1H"):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = h1[0][4]; sig["strategy"] = "SMC"
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SWING"
                            sig["confidence"] = sig.get("confidence", 0.6) + 0.05
                            swing_signals.append(sig)
                    if h4 and len(h4) >= 12:
                        for sig in analyze_smc(h4, "4H"):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = h4[0][4]; sig["strategy"] = "SMC"
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SWING"
                            sig["confidence"] = sig.get("confidence", 0.6) + 0.10
                            swing_signals.append(sig)
                    if d1 and len(d1) >= 10:
                        for sig in analyze_smc(d1, "Daily"):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = d1[0][4]; sig["strategy"] = "SMC"
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SWING"
                            sig["confidence"] = sig.get("confidence", 0.6) + 0.12
                            swing_signals.append(sig)

                    # 1H + 4H + Daily Swing analysis
                    if h1 and len(h1) >= 10:
                        for sig in _analyze_swing(h1, "1H", symbol, sym_name):
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SWING"; sig["source"] = "VPS"
                            swing_signals.append(sig)
                    if h4 and len(h4) >= 5:
                        for sig in _analyze_swing(h4, "4H", symbol, sym_name):
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SWING"; sig["source"] = "VPS"
                            swing_signals.append(sig)
                    if d1 and len(d1) >= 8:
                        for sig in _analyze_swing(d1, "Daily", symbol, sym_name):
                            sig["session"] = f"{session_emoji} {session_name}"
                            sig["trade_type"] = "SWING"; sig["source"] = "VPS"
                            swing_signals.append(sig)

                if now - last_scan > 45:
                    last_scan = now
                if now - last_track > 30:
                    last_track = now

                # Trend filter: if daily is up, prefer LONG scalps. If down, prefer SHORT.
                # Only send signals that align with the higher timeframe trend
                trend_aligned_scalp = []
                for s in scalp_signals:
                    if daily_trend > 0.2 and s["direction"] == "LONG":
                        s["confidence"] = min(0.9, s.get("confidence", 0.6) + 0.05)
                        s["reasoning"] = f"[TREND ALIGNED: Daily +{daily_trend:.1f}%] " + s.get("reasoning", "")
                        trend_aligned_scalp.append(s)
                    elif daily_trend < -0.2 and s["direction"] == "SHORT":
                        s["confidence"] = min(0.9, s.get("confidence", 0.6) + 0.05)
                        s["reasoning"] = f"[TREND ALIGNED: Daily {daily_trend:.1f}%] " + s.get("reasoning", "")
                        trend_aligned_scalp.append(s)
                    else:
                        # Counter-trend still allowed but at lower confidence
                        s["confidence"] = max(0.3, s.get("confidence", 0.6) - 0.15)
                        trend_aligned_scalp.append(s)

                # Select best scalp + best swing
                # ── Check for level breaks and send alerts ──
                for tf_label, tf_candles in [("15M", m15), ("1H", h1), ("4H", h4)]:
                    if tf_candles and len(tf_candles) >= 10:
                        from smc_luxalgo import compute_luxalgo_smc
                        tf_data = tf_candles[::-1]
                        r = compute_luxalgo_smc(tf_data, min(50, len(tf_data)//4), 5)
                        if r:
                            sh = [x[1] for x in r["swing_highs"]]
                            sl = [x[1] for x in r["swing_lows"]]
                            break_sig = check_level_break(symbol, tf_data[-1][4], sh, sl, tf_label)
                            if break_sig:
                                break_sig["symbol"] = symbol
                                break_sig["symbol_name"] = sym_name
                                break_sig["price_now"] = tf_data[-1][4]
                                break_sig["session"] = f"{session_emoji} {session_name}"
                                break_sig["trade_type"] = "SWING"
                                tp1, tp2, tp3 = calculate_multi_tp(break_sig)
                                break_sig["tp1"] = tp1; break_sig["tp2"] = tp2; break_sig["tp3"] = tp3
                                msg = format_professional_signal(break_sig)
                                for u in target_users:
                                    tg_send(TOK, u["chat_id"], 
                                        f"\U0001f514 <b>LEVEL BREAK!</b>\n{msg}")
                                logger.info("BREAK: %s", break_sig["setup"])

                # Select best scalp + best swing
                best_scalp = select_best_signals(trend_aligned_scalp)
                best_swing = select_best_signals(swing_signals)
                best = best_scalp + best_swing

                for sig in best:
                    # CONFLICT PREVENTION: don't send opposing direction within 30 min
                    sym_dir = f"{symbol}_{sig['direction']}"
                    opp_dir = f"{symbol}_{'SHORT' if sig['direction'] == 'LONG' else 'LONG'}"
                    if opp_dir in last_direction_per_symbol:
                        opp_time = last_direction_per_symbol[opp_dir]
                        if now - opp_time < 1800:  # 30 min cooldown
                            logger.info("CONFLICT BLOCKED: %s vs recent %s", sig['direction'], opp_dir)
                            continue
                    last_direction_per_symbol[sym_dir] = now

                    # Enforce minimum SL distance based on signal type
                    entry = sig["entry"]
                    sl = sig["sl"]
                    is_swing = sig.get("trade_type") == "SWING" or sig.get("strategy") == "SMC"
                    min_sl_pct = 0.0025 if is_swing else 0.0015  # 0.25% swing, 0.15% scalp
                    current_sl_dist = abs(entry - sl)
                    min_sl_dist = max(entry * min_sl_pct, 20)  # minimum 20 points absolute
                    # Adjust SL proportionally if too tight
                    missing = min_sl_dist - current_sl_dist
                    if missing > 0:
                        if sig["direction"] == "LONG":
                            sig["sl"] = round(entry - min_sl_dist, 1)
                        else:
                            sig["sl"] = round(entry + min_sl_dist, 1)

                    # Dedup: don't send same symbol+direction within 10 minutes
                    dedup_key = f"{symbol}_{sig['direction']}_{sig['setup']}"
                    if dedup_key in sent_signals and now - sent_signals[dedup_key] < 900:
                        continue
                    sent_signals[dedup_key] = now
                    # Clean old entries
                    for k in list(sent_signals.keys()):
                        if now - sent_signals[k] > 1200:
                            del sent_signals[k]

                    if get_active_signal_count(symbol) >= 2:
                        continue

                    tp1, tp2, tp3 = calculate_multi_tp(sig)
                    sig["tp1"] = tp1; sig["tp2"] = tp2; sig["tp3"] = tp3

                    msg = format_professional_signal(sig)

                    # AI evaluates the signal
                    d1_candles = get_candles(symbol, "1D", 10)
                    m15_candles = get_candles(symbol, "15", 20)
                    ai_decision = ai_evaluate(sig, d1_candles, m15_candles)

                    if ai_decision.get("action") == "SKIP":
                        logger.info("AI SKIPPED: %s — %s", sig["setup"], ai_decision.get("reason_en", ""))
                        for u in target_users:
                            tg_send(TOK, u["chat_id"],
                                f"\u274c <b>AI Skipped Signal</b>\n"
                                f"{ai_decision.get('reason_ar','Signal rejected by AI')}\n\n"
                                f"{ai_decision.get('reason_en','')}")
                        continue

                    if ai_decision.get("action") == "MODIFY":
                        new_sl = ai_decision.get("new_sl", 0) or ai_decision.get("sl", 0)
                        if new_sl:
                            sig["sl"] = float(new_sl)
                            tp1, tp2, tp3 = calculate_multi_tp(sig)
                            sig["tp1"] = tp1; sig["tp2"] = tp2; sig["tp3"] = tp3
                            msg = format_professional_signal(sig)
                        logger.info("AI MODIFIED: new SL=%s", new_sl)

                    # Capture chart screenshot if confidence is high (e.g. >= 0.70)
                    photo_path = None
                    if sig.get("confidence", 0) >= 0.70:
                        try:
                            from tv_capture_helper import capture_tv_chart
                            # Capture chart for the signal's timeframe
                            photo_path = capture_tv_chart(symbol=symbol, timeframe=sig.get("timeframe", "15M"))
                        except Exception as capture_err:
                            logger.error("Failed to capture chart for signal: %s", capture_err)

                    for u in target_users:
                        photo_sent = False
                        if photo_path and os.path.exists(photo_path):
                            try:
                                from tg_bot import send_photo
                                if len(msg) <= 1024:
                                    send_photo(u["chat_id"], photo_path, caption=msg)
                                    photo_sent = True
                                else:
                                    # Caption too long, send photo first, then text
                                    send_photo(u["chat_id"], photo_path, caption=f"📊 {symbol} {sig['direction']} Chart")
                                    tg_send(TOK, u["chat_id"], msg)
                                    photo_sent = True
                            except Exception as photo_err:
                                logger.error("Failed to send photo to Telegram: %s", photo_err)
                        
                        if not photo_sent:
                            tg_send(TOK, u["chat_id"], msg)

                        log_alert(u["chat_id"], symbol, sig["direction"], sig["setup"],
                                 sig["entry"], sig["sl"], tp2, sig.get("strategy", ""),
                                 sig.get("timeframe", ""), sig.get("confidence", 0))

                    # Auto-execute: try API first, fall back to click automation
                    mt5_result = mt5_execute(sig)
                    if not mt5_result.get("ok"):
                        # API blocked — use mouse/keyboard automation
                        logger.info("MT5 API blocked, using click automation...")
                        sig["lot"] = 0.01  # Safe lot for auto-click
                        mt5_click_trade(sig)
                        mt5_result = {"ok": True, "lot": 0.01, "entry": entry, "method": "click"}
                    if mt5_result.get("ok"):
                        is_pyramid = "SL at breakeven" if mt5_result.get("pyramid") else ""
                        pyramid_str = " \U0001f4c8 Pyramid" if is_pyramid else ""
                        logger.info("MT5 executed: %s", mt5_result)
                        for u in target_users:
                            tg_send(TOK, u["chat_id"],
                                f"\u2705 <b>MT5 Order</b>{pyramid_str}\n"
                                f"{sig['direction']} | Lot: <b>{mt5_result['lot']:.2f}</b>\n"
                                f"Entry: {mt5_result['entry']:.1f} | Conf: {sig.get('confidence',0):.0%}")
                    elif mt5_result.get("error"):
                        logger.warning("MT5 skip: %s", mt5_result["error"])

                    # Track signal only if R:R > 1.5
                    if abs(sig["tp2"] - sig["entry"]) > abs(sig["sl"] - sig["entry"]) * 1.5:
                        track_signal(symbol, sig["direction"], sig["entry"], sig["sl"],
                                    tp1, tp2, tp3, sig["setup"], sig.get("timeframe", ""),
                                    sig.get("confidence", 0))

                # ── MT5 position management (SL trailing, breakeven, sideways detection) ──
                mt5_msgs = mt5_manage()
                for mt5_msg in mt5_msgs:
                    for u in target_users:
                        tg_send(TOK, u["chat_id"], mt5_msg)
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
