"""Auto Signal Generator — captures chart, analyzes via GPT-4 Vision, sends to Telegram."""

import os, sys, time, base64, json, requests, logging

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv; load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GPT_KEY = os.getenv("OPENAI_API_KEY", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A")
# Get chat IDs from users.json - send to ALL active users
TG_CHATS = [624637526]  # default

SYMBOL = "CFI:US100"
TIMEFRAMES = {"1M": "1", "5M": "5", "15M": "15", "1H": "60", "4H": "240"}


def capture_single_tf(tf_code, label):
    """Capture a single timeframe chart."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=opts)

    try:
        url = f"https://www.tradingview.com/chart/?symbol={SYMBOL}&interval={tf_code}"
        driver.get(url)
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(1)

        path = os.path.join(os.path.dirname(__file__), f"chart_{label}.png")
        driver.save_screenshot(path)
        return path
    except Exception as e:
        logger.error("Capture %s: %s", label, e)
        return None
    finally:
        driver.quit()


def analyze_chart(image_path, tf_label):
    """Send chart to GPT-4 Vision for SMC analysis."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    # Also get MT5 price for accuracy
    current_price = ""
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        mt5.login(22148595)
        t = mt5.symbol_info_tick("US100_Spot")
        if t:
            current_price = f"MT5 real-time price: {t.ask:.1f}"
    except:
        pass

    resp = requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {GPT_KEY}"},
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": f"""You are an expert SMC/ICT trader. This is CFI:US100 {tf_label} chart. {current_price}
                
Analyze and return ONLY this format:

DIRECTION: BUY / SELL / WAIT
ENTRY: [exact price]
SL: [exact price] 
TP1: [exact price]
TP2: [exact price]
CONFIDENCE: [0-100%]
REASON: [2 lines max, key SMC reason]

Pick ONE best signal based on what you see. Be specific with prices."""},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}}
            ]}],
            "max_tokens": 250, "temperature": 0.3
        }, timeout=30)

    if resp.status_code == 200:
        return resp.json()["choices"][0]["message"]["content"]
    return f"Error: {resp.status_code}"


def send_to_telegram(text):
    """Send message to all active Telegram users."""
    try:
        from database import get_active_users_with_subs
        users = get_active_users_with_subs()
        for u in users:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                         json={"chat_id": u["chat_id"], "text": text, "parse_mode": "HTML"}, timeout=10)
        return True
    except:
        # Fallback to default
        for chat in TG_CHATS:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                         json={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=10)
        return True


def generate_and_send_signal():
    """Full pipeline: capture, analyze, send signal to Telegram."""
    logger.info("Generating signal...")

    # Get best timeframe (15M for scalp, 1H for swing)
    for tf_label, tf_code in [("15M", "15"), ("1H", "60")]:
        path = capture_single_tf(tf_code, tf_label)
        if not path:
            continue

        logger.info("Analyzing %s chart...", tf_label)
        analysis = analyze_chart(path, tf_label)

        if analysis and "BUY" in analysis.upper() or "SELL" in analysis.upper():
            # Format nicely
            msg = f"\U0001f9e0 <b>SMC Signal [{tf_label}]</b>\n\n{analysis}\n\n<i>Generated at {time.strftime('%H:%M')}</i>"
            send_to_telegram(msg)
            logger.info("Signal sent for %s", tf_label)
            return analysis

    # If no clear signal, send summary
    send_to_telegram(f"\U0001f4ca <b>Market Update</b>\nNo clear signal. Choppy market.")
    return None


if __name__ == "__main__":
    generate_and_send_signal()
