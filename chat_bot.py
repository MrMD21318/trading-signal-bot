"""Simple conversational Telegram bot — replies with AI analysis."""

import os, sys, time, requests, json, logging
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv; load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A")
AI_KEY = os.getenv("KIMI_API_KEY", "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")
API = f"https://api.telegram.org/bot{TOKEN}"
AI_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def tg(method, params=None):
    try:
        r = requests.post(f"{API}/{method}", json=params or {}, timeout=15)
        return r.json()
    except:
        return {"ok": False}


def get_market_context():
    try:
        from run_us100_monitor import get_candles, fmt
        from smc_manual import find_swings
        c = get_candles("CFI:US100", "15", 20)[::-1]
        p = c[-1][4]
        h,l = find_swings(c, 10)
        ctx = f"US100: {fmt(p)}"
        if h: ctx += f" | Resist: {fmt(max(x[1] for x in h))}"
        if l: ctx += f" | Support: {fmt(min(x[1] for x in l))}"
        return ctx
    except:
        return "US100 market data unavailable"


def ask_ai(user_text, user_name=""):
    ctx = get_market_context()
    try:
        r = requests.post(AI_URL,
            headers={"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"},
            json={
                "model": "moonshotai/kimi-k2.6",
                "max_tokens": 600,
                "temperature": 1.00,
                "top_p": 1.00,
                "messages": [
                    {"role": "system", "content": f"You are a professional SMC/ICT trader for CFI:US100. Market: {ctx}. Reply in Arabic+English. Be helpful, decisive. Give entry/SL/TP when asked. Use emojis. Keep under 500 chars."},
                    {"role": "user", "content": user_text}
                ]
            }, timeout=20)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return f"AI error: {r.status_code}"
    except Exception as e:
        return f"Error: {e}"


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()
    first = msg["chat"].get("first_name", "")

    if not text:
        return

    # Commands
    if text in ("/price", "price"):
        ctx = get_market_context()
        tg("sendMessage", {"chat_id": chat_id, "text": f"\U0001f4b0 {ctx}", "parse_mode": "HTML"})
        return

    if text in ("/start", "start"):
        tg("sendMessage", {"chat_id": chat_id, "text": f"Hello {first}! Ask me anything about US100 trading.\n/price - current price\nOr just chat naturally!", "parse_mode": "HTML"})
        return

    # AI Chat — everything else
    tg("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    reply = ask_ai(text, first)
    tg("sendMessage", {"chat_id": chat_id, "text": reply, "parse_mode": "HTML"})


def run():
    offset = 0
    tg("sendMessage", {"chat_id": 624637526, "text": "\U0001f514 Bot online. Ask me anything about US100!"})
    logger.info("Bot started. Waiting for messages...")

    while True:
        try:
            r = requests.get(f"{API}/getUpdates?offset={offset}&timeout=30", timeout=35)
            data = r.json()
            if data.get("result"):
                for u in data["result"]:
                    offset = u["update_id"] + 1
                    msg = u.get("message")
                    if msg:
                        handle_message(msg)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Error: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    run()
