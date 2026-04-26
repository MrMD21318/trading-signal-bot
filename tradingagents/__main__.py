"""Coolify entry point — python -m tradingagents redirects here."""
import os
import sys
import time
import threading
import logging

# Add project root to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SMC_CREDIT", "0")

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("runner")

from dashboard import run_dashboard
from database import get_users_for_symbol, log_alert, get_user_symbols, get_active_users_with_subs


def run_bot_poller():
    from tg_bot import poll_updates
    logger.info("Bot poller started")
    poll_updates()


def run_monitor():
    import pytz
    from run_us100_monitor import (
        get_candles, analyze_candles_1m, analyze_candles_5m,
        analyze_candles_15m, analyze_swing, check_sessions, check_news, tg,
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
                "\U0001f514 Signal Monitor Online\n"
                "Multi-TP entries only (1:2R+)\n"
                "Scalp + SMC + Swing\n"
                "/menu - manage | /stop - pause")

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

                # ── Signal tracking: check TP/SL hits ──
                if now - last_track > 30:
                    m1 = get_candles(symbol, "1", 3)
                    if m1:
                        current_price = m1[0][4]
                        alerts = check_active_signals(symbol, current_price)
                        for a in alerts:
                            for u in target_users:
                                tg_send(TOK, u["chat_id"], a)

                # ── Collect all signals across timeframes ──
                all_signals = []

                if now - last_scan > 45:
                    m1 = get_candles(symbol, "1", 60)
                    m5 = get_candles(symbol, "5", 40)
                    m15 = get_candles(symbol, "15", 30)
                    m15_smc = get_candles(symbol, "15", 50)
                    h1 = get_candles(symbol, "60", 24)
                    d1 = get_candles(symbol, "1D", 20)

                    # 1M signals
                    for sig in analyze_candles_1m(m1):
                        sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                        all_signals.append(sig)
                    # 5M signals
                    for sig in analyze_candles_5m(m5):
                        sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                        all_signals.append(sig)
                    # 15M signals
                    for sig in analyze_candles_15m(m15):
                        sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                        all_signals.append(sig)
                    # SMC signals
                    for sig in analyze_smc(m15_smc, m5, m1):
                        sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                        sig["strategy"] = "SMC"
                        all_signals.append(sig)

                if now - last_scan > 45:
                    last_scan = now
                if now - last_track > 30:
                    last_track = now

                # ── Select only the best signals ──
                best = select_best_signals(all_signals)

                # ── Send best signals with multi-TP ──
                for sig in best:
                    if get_active_signal_count(symbol) >= 2:
                        continue

                    # Current price for header
                    m1_price = get_candles(symbol, "1", 3)
                    sig["price_now"] = m1_price[0][4] if m1_price else sig["entry"]

                    tp1, tp2, tp3 = calculate_multi_tp(sig)
                    sig["tp1"] = tp1
                    sig["tp2"] = tp2
                    sig["tp3"] = tp3

                    msg = format_professional_signal(sig)
                    for u in target_users:
                        tg_send(TOK, u["chat_id"], msg)
                        log_alert(u["chat_id"], symbol, sig["direction"], sig["setup"],
                                 sig["entry"], sig["sl"], tp2, sig.get("strategy", ""),
                                 sig.get("timeframe", ""), sig.get("confidence", 0))

                    # Track this signal
                    track_signal(symbol, sig["direction"], sig["entry"], sig["sl"],
                                tp1, tp2, tp3, sig["setup"], sig.get("timeframe", ""),
                                sig.get("confidence", 0))
                    time.sleep(1.2)

                if not best and all_signals:
                    logger.info("%s: %d signals collected, none passed quality filter", symbol, len(all_signals))

            # ── Session & news ──
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


def main():
    logger.info("Starting Trading Signal Suite...")
    threading.Thread(target=run_bot_poller, daemon=True).start()
    time.sleep(1)
    threading.Thread(target=lambda: run_dashboard(port=5000), daemon=True).start()
    time.sleep(1)
    run_monitor()


if __name__ == "__main__":
    main()
