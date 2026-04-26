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
        analyze_candles_15m, analyze_swing, fmt, format_signal,
        check_sessions, check_news, tg,
    )
    from symbol_manager import get_active_symbols
    from smc_analysis import analyze_smc

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

    logger.info("Monitor started")
    time.sleep(3)

    active_users = get_active_users_with_subs()
    if active_users:
        for u in active_users[:5]:
            tg_send(TOK, u["chat_id"],
                "Signal Monitor Online - you will receive alerts for your markets.\n/menu - manage | /stop - pause")

    last_scalp = last_swing = last_smc = last_session = last_news = 0
    seen = {}
    smc_seen = {}

    while True:
        try:
            now = time.time()
            active_syms = get_active_symbols()
            if not active_syms:
                active_syms = {DEFAULT: {"name": "Nasdaq 100 SPOT"}}

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

            for symbol, sym_info in active_syms.items():
                sym_name = sym_info.get("name", symbol)
                target_users = get_users_for_symbol(symbol) or get_active_users_with_subs()

                if now - last_scalp > 45:
                    m1 = get_candles(symbol, "1", 60)
                    m5 = get_candles(symbol, "5", 40)
                    m15 = get_candles(symbol, "15", 20)
                    for sig_func in [lambda m=m1: analyze_candles_1m(m), lambda m=m5: analyze_candles_5m(m), lambda m=m15: analyze_candles_15m(m)]:
                        for sig in sig_func():
                            key = f"{symbol}_{sig['direction']}_{sig['setup']}"
                            if key in seen and now - seen[key] < 600:
                                continue
                            seen[key] = now
                            sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                            msg = format_signal(sig, is_scalp=True)
                            for u in target_users:
                                tg_send(TOK, u["chat_id"], msg)
                                log_alert(u["chat_id"], symbol, sig["direction"], sig["setup"], sig.get("entry", 0), sig.get("sl", 0), sig.get("tp", 0), "scalp", sig.get("timeframe", ""), sig.get("confidence", 0))

                if now - last_smc > 60:
                    m15s = get_candles(symbol, "15", 50)
                    for sig in analyze_smc(m15s, None, None):
                        key = f"{symbol}_SMC_{sig['direction']}_{sig['setup']}"
                        if key in smc_seen and now - smc_seen[key] < 600:
                            continue
                        smc_seen[key] = now
                        sig["symbol"] = symbol; sig["symbol_name"] = sym_name
                        msg = format_signal(sig, is_scalp=True)
                        for u in target_users:
                            tg_send(TOK, u["chat_id"], msg)
                            log_alert(u["chat_id"], symbol, sig["direction"], sig["setup"], sig.get("entry", 0), sig.get("sl", 0), sig.get("tp", 0), "SMC", "15M", sig.get("confidence", 0))

                for d in (seen, smc_seen):
                    for k in list(d.keys()):
                        if now - d[k] > 2000: del d[k]

            if now - last_scalp > 45: last_scalp = now
            if now - last_smc > 60: last_smc = now
            time.sleep(10)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Monitor error: %s", e)
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
