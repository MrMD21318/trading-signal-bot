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

    active_users = get_active_users_with_subs()
    if active_users:
        for u in active_users[:5]:
            tg_send(TOK, u["chat_id"],
                "Signal Monitor v3 Online\nMulti-TP | SMC+Scalp | TP/SL tracking")

    last_scan = last_session = last_news = last_track = 0

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
                if now - last_scan > 45:
                    m1 = get_candles(symbol, "1", 60)
                    m5 = get_candles(symbol, "5", 40)
                    m15 = get_candles(symbol, "15", 30)
                    m15_smc = get_candles(symbol, "15", 50)

                    if m1:
                        for sig in analyze_candles_1m(m1):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m1[0][4]
                            all_signals.append(sig)
                    if m5:
                        for sig in analyze_candles_5m(m5):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m5[0][4]
                            all_signals.append(sig)
                    if m15:
                        for sig in analyze_candles_15m(m15):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m15[0][4]
                            all_signals.append(sig)
                    if m15_smc:
                        for sig in analyze_smc(m15_smc, m5, m1):
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            sig["price_now"] = m15_smc[0][4]
                            sig["strategy"] = "SMC"
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
