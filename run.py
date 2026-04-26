"""US100 Signal Suite — Multi-service runner for Docker/Coolify.

Runs 3 services in one process:
  1. Dashboard (Flask) — admin panel on port 5000
  2. TG Bot poller — handles /start, menu, inline keyboards
  3. Signal Monitor — analyzes charts, sends per-user alerts
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

# Import after env setup
from dashboard import run_dashboard
from database import get_users_for_symbol, log_alert, get_user_symbols


def run_bot_poller():
    """Poll Telegram for commands."""
    from tg_bot import poll_updates
    logger.info("Bot poller started")
    poll_updates()


def run_monitor():
    """Run the signal monitor with per-user alerting."""
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

    # Welcome via TG
    from database import get_active_users_with_subs
    active_users = get_active_users_with_subs()
    if active_users:
        for u in active_users[:5]:
            tg_send(TOK, u["chat_id"],
                "🟢 <b>Signal Monitor Online</b>\n"
                "You will receive alerts for your subscribed markets.\n"
                "/menu — Manage settings | /stop — Pause alerts")

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

            # Per-symbol analysis
            for symbol, sym_info in active_syms.items():
                sym_name = sym_info.get("name", symbol)

                # Which users want this symbol?
                target_users = get_users_for_symbol(symbol)
                if not target_users:
                    target_users = get_active_users_with_subs()  # fallback: all active

                # SCALP
                if now - last_scalp > 45:
                    m1 = get_candles(symbol, "1", 60)
                    m5 = get_candles(symbol, "5", 40)
                    m15 = get_candles(symbol, "15", 20)

                    for sig_func, tf_label, dedup_sec in [
                        (lambda: analyze_candles_1m(m1), "1M", 300),
                        (lambda: analyze_candles_5m(m5), "5M", 600),
                        (lambda: analyze_candles_15m(m15), "15M", 900),
                    ]:
                        for sig in sig_func():
                            key = f"{symbol}_{sig['direction']}_{sig['setup']}_{tf_label}"
                            if key in seen and now - seen[key] < dedup_sec:
                                continue
                            seen[key] = now
                            sig["symbol"] = symbol
                            sig["symbol_name"] = sym_name
                            sig["timeframe"] = tf_label
                            msg = format_signal(sig, is_scalp=True)
                            for u in target_users:
                                tg_send(TOK, u["chat_id"], msg)
                                log_alert(u["chat_id"], symbol, sig["direction"], sig["setup"],
                                         sig["entry"], sig["sl"], sig["tp"], "scalp", tf_label, sig.get("confidence", 0))

                # SMC
                if now - last_smc > 60:
                    m15s = get_candles(symbol, "15", 50)
                    for sig in analyze_smc(m15s, None, None):
                        key = f"{symbol}_SMC_{sig['direction']}_{sig['setup']}"
                        if key in smc_seen and now - smc_seen[key] < 600:
                            continue
                        smc_seen[key] = now
                        sig["symbol"] = symbol
                        sig["symbol_name"] = sym_name
                        msg = format_signal(sig, is_scalp=True)
                        for u in target_users:
                            tg_send(TOK, u["chat_id"], msg)
                            log_alert(u["chat_id"], symbol, sig["direction"], sig["setup"],
                                     sig["entry"], sig["sl"], sig["tp"], "SMC", "15M", sig.get("confidence", 0))

                # Clean SEEN
                for d in (seen, smc_seen):
                    for k in list(d.keys()):
                        if now - d[k] > 2000:
                            del d[k]

            if now - last_scalp > 45:
                last_scalp = now
            if now - last_smc > 60:
                last_smc = now

            # Session check every 2 min
            if now - last_session > 120:
                for sa in check_sessions():
                    for u in get_active_users_with_subs():
                        tg_send(TOK, u["chat_id"], sa)
                last_session = now

            time.sleep(10)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Monitor error: %s", e)
            time.sleep(15)


if __name__ == "__main__":
    logger.info("Starting US100 Signal Suite...")

    # Start bot poller in background
    t_bot = threading.Thread(target=run_bot_poller, daemon=True)
    t_bot.start()
    time.sleep(1)

    # Start dashboard in background
    t_dash = threading.Thread(target=lambda: run_dashboard(port=5000), daemon=True)
    t_dash.start()
    time.sleep(1)

    # Run monitor in foreground
    run_monitor()
