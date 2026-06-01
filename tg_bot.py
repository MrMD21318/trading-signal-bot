"""Telegram bot with conversation flow — onboards users to choose their markets."""

import os
import json
import logging
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from database import (
    upsert_user, get_user, set_user_active, add_user_symbol,
    remove_user_symbol, get_user_symbols, set_user_phone,
)

logger = logging.getLogger(__name__)

TOKEN = "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A"
API = "https://api.telegram.org/bot"


def tg(method, params=None):
    try:
        r = requests.post(f"{API}{TOKEN}/{method}", json=params or {}, timeout=15)
        return r.json()
    except:
        return {"ok": False}


def send_msg(chat_id, text, reply_markup=None, parse_mode="HTML"):
    params = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return tg("sendMessage", params)


def send_photo(chat_id, photo_path, caption=None, reply_markup=None, parse_mode="HTML"):
    try:
        url = f"{API}{TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": chat_id, "parse_mode": parse_mode}
            if caption:
                data["caption"] = caption
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)
            r = requests.post(url, data=data, files=files, timeout=30)
            return r.json()
    except Exception as e:
        logger.error("Send photo failed: %s", e)
        return {"ok": False}



def edit_msg(chat_id, msg_id, text, reply_markup=None, parse_mode="HTML"):
    params = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return tg("editMessageText", params)


# ── Keyboard builders ─────────────────────────────────────────

MARKETS = [
    ("ForEx", ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD"]),
    ("Indices", ["CFI:US100", "CFI:US500", "CFI:US30", "CFI:GER40", "CFI:UK100"]),
    ("Crypto", ["BINANCE:BTCUSDT", "BINANCE:ETHUSDT", "BINANCE:SOLUSDT"]),
    ("Stocks", ["NASDAQ:AAPL", "NASDAQ:NVDA", "NASDAQ:TSLA", "NASDAQ:MSFT", "NASDAQ:META"]),
]


def markets_keyboard(selected=None):
    """Build inline keyboard of markets with checkmarks."""
    selected = selected or []
    kb = {"inline_keyboard": []}
    for category, symbols in MARKETS:
        # Category header
        kb["inline_keyboard"].append([{
            "text": f"--- {category} ---",
            "callback_data": f"cat:{category}",
        }])
        # Row of 2-3 symbols
        row = []
        for sym in symbols:
            mark = "✅ " if sym in selected else ""
            row.append({"text": f"{mark}{sym}", "callback_data": f"sym:{sym}"})
            if len(row) == 3:
                kb["inline_keyboard"].append(row)
                row = []
        if row:
            kb["inline_keyboard"].append(row)
    # Done button
    kb["inline_keyboard"].append([{"text": "✅ SAVE & START ALERTS", "callback_data": "done"}])
    kb["inline_keyboard"].append([{"text": "❌ Cancel", "callback_data": "cancel"}])
    return kb


def main_menu_keyboard():
    return {"inline_keyboard": [
        [{"text": "📋 My Markets", "callback_data": "my_markets"}],
        [{"text": "🔔 Start Alerts", "callback_data": "start_alerts"},
         {"text": "🔕 Stop Alerts", "callback_data": "stop_alerts"}],
        [{"text": "📊 Status", "callback_data": "status"}],
    ]}


# ── Conversation state ───────────────────────────────────────
user_states = {}  # chat_id -> {"state": "choosing", "selected": []}


def handle_update(update):
    try:
        if "message" in update:
            return handle_message(update["message"])
        if "callback_query" in update:
            return handle_callback(update["callback_query"])
    except Exception as e:
        logger.error("Update error: %s", e)
    return "ok"


def handle_message(msg):
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text", "") or "").strip()
    text_lower = text.lower()
    first = msg.get("chat", {}).get("first_name", "")
    username = msg.get("chat", {}).get("username", "")

    if not chat_id:
        return "ok"

    upsert_user(chat_id, first, username)

    # Check if user shared contact
    contact = msg.get("contact")
    if contact:
        phone = contact.get("phone_number", "")
        set_user_phone(chat_id, phone)
        send_msg(chat_id, "✅ Phone saved! Now use the menu below:", main_menu_keyboard())
        return "ok"

    if text_lower in ("/start", "start"):
        user = get_user(chat_id)
        if user and user.get("active"):
            # Already active
            syms = get_user_symbols(chat_id)
            syms_list = [s["symbol"] for s in syms]
            expiry = user.get("subscription_expiry", "")
            exp_str = f"\nSubscription expires: {expiry[:10]}" if expiry else ""
            send_msg(chat_id,
                f"\U0001f44b Welcome back <b>{first}</b>!\n\n"
                f"Status: <b>ACTIVE</b>{exp_str}\n"
                f"Markets: <code>{', '.join(syms_list) or 'None'}</code>\n\n"
                "You are receiving trading signals.\n"
                "/menu — Manage | /status — Stats | /stop — Pause\n"
                "/chart — Capture live TradingView chart and analyze it!",
                main_menu_keyboard(),
            )
        else:
            # New or pending user — show pending message
            send_msg(chat_id,
                f"\U0001f44b Welcome <b>{first}</b>!\n\n"
                "\u23f3 <b>Your account is pending activation.</b>\n\n"
                "The admin needs to activate your account and assign markets before you can receive signals.\n\n"
                "You'll receive a confirmation message once activated.\n\n"
                "<i>Your Chat ID: <code>{}</code></i>".format(chat_id),
            )
        return "ok"

    # ── Trading commands ──
    if text_lower in ("/price", "price", "/price@tradingsignalbot"):
        try:
            import MetaTrader5 as mt5
            mt5.initialize()
            mt5.login(22148595)
            t = mt5.symbol_info_tick("US100_Spot")
            if t:
                send_msg(chat_id, f"\U0001f4b0 <b>US100: {t.ask:.1f}</b>\nSpread: {t.ask-t.bid:.1f}")
            else:
                send_msg(chat_id, "MT5 not connected")
        except:
            send_msg(chat_id, "Error getting price")
        return "ok"

    if text_lower in ("/signal", "signal", "/signal@tradingsignalbot"):
        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(__file__))
            from run_us100_monitor import get_candles, fmt
            m1 = get_candles("CFI:US100", "1", 5)
            m5 = get_candles("CFI:US100", "5", 4)
            if m1 and m5:
                p = m1[0][4]
                g1 = sum(1 for c in m1[:5] if c[4] > c[1])
                g5 = sum(1 for c in m5[:4] if c[4] > c[1])
                trend = "BULLISH" if g5 >= 3 else "BEARISH" if g5 <= 1 else "NEUTRAL"
                send_msg(chat_id,
                    f"\U0001f4ca <b>Quick Signal</b>\n"
                    f"Price: <code>{fmt(p)}</code>\n"
                    f"1M: {g1}/5 green\n5M: {g5}/4 green\n"
                    f"Trend: <b>{trend}</b>\n\n"
                    f"{'BUY' if trend=='BULLISH' else 'SELL' if trend=='BEARISH' else 'WAIT'}"
                )
        except:
            send_msg(chat_id, "Error")
        return "ok"

    if text_lower in ("/analysis", "analysis", "/analysis@tradingsignalbot"):
        try:
            import sys, os; sys.path.insert(0, os.path.dirname(__file__))
            from run_us100_monitor import get_candles, fmt
            from smc_manual import find_swings, find_order_blocks, find_liquidity
            m15 = get_candles("CFI:US100", "15", 30)[::-1]
            p = m15[-1][4]
            h, l = find_swings(m15, 10)
            obs = find_order_blocks(m15)
            liqs = find_liquidity(m15)
            msg = f"\U0001f9e0 <b>SMC Analysis</b>\nPrice: <code>{fmt(p)}</code>\n"
            if h: msg += f"Resist: {fmt(h[-1][1])}\n"
            if l: msg += f"Support: {fmt(l[-1][1])}\n"
            near_ob = [o for o in obs if o[2] <= p <= o[3]]
            if near_ob: msg += f"OB: {near_ob[0][0]} {fmt(near_ob[0][2])}-{fmt(near_ob[0][3])}\n"
            near_liq = [x for x in liqs if abs(x[2]-p)/p < 0.002]
            if near_liq: msg += f"Liq: {near_liq[0][0]} at {fmt(near_liq[0][2])}\n"
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, f"Error: {e}")
        return "ok"

    if text_lower in ("/chart", "/analyse", "chart", "analyse", "/chart@tradingsignalbot"):
        send_msg(chat_id, "⏳ <b>Opening TradingView and capturing live CFI:US100 chart...</b>\n<i>Please wait ~8 seconds.</i>")
        try:
            from tv_capture_helper import capture_tv_chart
            # Capture 15M chart
            photo_path = capture_tv_chart(symbol="CFI:US100", timeframe="15M")
            if photo_path and os.path.exists(photo_path):
                send_msg(chat_id, "🤖 <b>Chart captured! Running expert GPT-4 Vision analysis...</b>")
                
                # Analyze using GPT-4 Vision helper
                from tv_capture import analyze_with_gpt
                analysis_text = analyze_with_gpt(photo_path, "15M")
                
                caption = f"📊 <b>CFI:US100 15M Live Chart Analysis</b>\n\n{analysis_text}"
                if len(caption) > 1024:
                    send_photo(chat_id, photo_path, caption="📊 CFI:US100 15M Live Chart")
                    send_msg(chat_id, analysis_text)
                else:
                    send_photo(chat_id, photo_path, caption=caption)
            else:
                send_msg(chat_id, "❌ Failed to capture chart screenshot. Make sure chrome is running correctly.")
        except Exception as e:
            logger.error("Chart command error: %s", e)
            send_msg(chat_id, f"❌ Error: {e}")
        return "ok"

    # AI Chat Fallback - natural chat
    if text:
        tg("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        reply = chat_with_ai(chat_id, text, first)
        send_msg(chat_id, reply)
        return "ok"


def handle_callback(cb):
    chat_id = cb["from"]["id"]
    data = cb.get("data", "")
    msg_id = cb["message"]["message_id"]
    cb_id = cb.get("id", "")

    upsert_user(chat_id, cb["from"].get("first_name", ""), cb["from"].get("username", ""))

    if cb_id:
        tg("answerCallbackQuery", {"callback_query_id": cb_id})

    if data == "cancel":
        user_states.pop(chat_id, None)
        edit_msg(chat_id, msg_id, "❌ Setup cancelled. Send /start to try again.")
        return "ok"

    if data == "done":
        state = user_states.pop(chat_id, {"selected": []})
        selected = state["selected"]
        if not selected:
            edit_msg(chat_id, msg_id, "⚠️ You must select at least one market. Try again:", markets_keyboard([]))
            user_states[chat_id] = {"state": "choosing", "selected": [], "message_id": None}
            return "ok"
            
        # Save to DB
        conn_remove = __import__("database").get_conn()
        conn_remove.execute("DELETE FROM user_symbols WHERE chat_id=?", (chat_id,))
        conn_remove.commit()
        conn_remove.close()
        for sym in selected:
            add_user_symbol(chat_id, sym, sym)
        set_user_active(chat_id, True)
        syms_str = ", ".join(selected)
        edit_msg(chat_id, msg_id,
            f"✅ <b>Setup complete!</b>\n\n"
            f"Tracking: <code>{syms_str}</code>\n\n"
            "You will receive scalp + SMC signals for these markets.\n\n"
            "Commands:\n"
            "/menu — Manage settings\n"
            "/status — Check status\n"
            "/stop — Stop alerts\n"
            "/markets — Change markets",
            main_menu_keyboard(),
        )
        return "ok"

    if data.startswith("sym:"):
        sym = data[4:]
        state = user_states.get(chat_id, {"state": "choosing", "selected": []})
        if sym in state["selected"]:
            state["selected"].remove(sym)
        else:
            state["selected"].append(sym)
        user_states[chat_id] = state
        edit_msg(chat_id, msg_id,
            f"<b>Select markets:</b>\n\nSelected: <code>{', '.join(state['selected']) or 'None'}</code>",
            markets_keyboard(state["selected"]),
        )
        return "ok"

    if data == "my_markets":
        syms = get_user_symbols(chat_id)
        syms_list = [s["symbol"] for s in syms]
        if syms_list:
            send_msg(chat_id, f"📋 <b>Your Markets:</b>\n<code>{', '.join(syms_list)}</code>")
        else:
            send_msg(chat_id, "No markets selected. Send /start to set up.")

    if data == "start_alerts":
        set_user_active(chat_id, True)
        user = get_user(chat_id)
        syms = get_user_symbols(chat_id)
        if not syms:
            send_msg(chat_id, "⚠️ No markets selected! Send /start to choose.")
        else:
            send_msg(chat_id, "🔔 <b>Alerts ACTIVATED!</b> You will receive signals for your markets.")

    if data == "stop_alerts":
        set_user_active(chat_id, False)
        send_msg(chat_id, "🔕 <b>Alerts STOPPED.</b> Send /start to reactivate.", main_menu_keyboard())

    if data == "status":
        user = get_user(chat_id)
        syms = get_user_symbols(chat_id)
        count = user["alerts_received"] if user else 0
        active = "ACTIVE" if (user and user.get("active")) else "PAUSED"
        syms_str = ", ".join(s["symbol"] for s in syms) if syms else "None"
        send_msg(chat_id,
            f"📊 <b>Your Status</b>\n\n"
            f"Status: <b>{active}</b>\n"
            f"Markets: <code>{syms_str}</code>\n"
            f"Alerts received: <b>{count}</b>\n"
            f"Last alert: {user.get('last_alert_at','Never')[:19] if user else 'Never'}",
        )

    return "ok"


def poll_updates():
    """Poll Telegram for updates and handle them."""
    offset = 0
    while True:
        try:
            resp = tg("getUpdates", {"offset": offset, "timeout": 30})
            if resp.get("ok"):
                for update in resp.get("result", []):
                    offset = update["update_id"] + 1
                    handle_update(update)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Poll error: %s", e)
            time.sleep(5)
# ── AI Chat handler ────────────────────────────────────────────
def chat_with_ai(chat_id, user_text, user_name=""):
    """Send user message to Moonshot Kimi (Nvidia) or OpenAI and return response."""
    import requests as req, os, sys
    sys.path.insert(0, os.path.dirname(__file__))

    # Get market context
    ctx = ""
    try:
        from run_us100_monitor import get_candles, fmt
        from smc_manual import find_swings, find_order_blocks, find_liquidity
        c = get_candles("CFI:US100", "15", 20)[::-1]
        p = c[-1][4]
        h,l = find_swings(c, 10)
        ctx = f"US100 price: {fmt(p)}. "
        if h: ctx += f"Resistance: {fmt(max(x[1] for x in h))}. "
        if l: ctx += f"Support: {fmt(min(x[1] for x in l))}. "
    except:
        pass

    kimi_key = os.getenv("KIMI_API_KEY", "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")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    system_prompt = f"You are an expert SMC/ICT trader analyzing CFI:US100 (Nasdaq100). Reply in Arabic+English. Be helpful, decisive, and technical. Current market: {ctx}. Give entry/SL/TP when asked. Use emojis."

    # Try Kimi first
    if kimi_key:
        try:
            resp = req.post("https://integrate.api.nvidia.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {kimi_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "moonshotai/kimi-k2.6",
                    "max_tokens": 500,
                    "temperature": 1.00,
                    "top_p": 1.00,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text}
                    ]
                },
                timeout=15
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning("Chat Kimi failed: %s", e)

    # Try OpenAI as fallback
    if openai_key:
        try:
            resp = req.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}"},
                json={
                    "model": "gpt-4o",
                    "max_tokens": 500,
                    "temperature": 0.4,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text}
                    ]
                },
                timeout=15
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning("Chat OpenAI failed: %s", e)

    return "Error connecting to AI. Try again."
