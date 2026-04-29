"""AI Trading Agent — uses DeepSeek to validate signals and manage trades autonomously.

The AI reviews each signal with full market context and decides:
  1. EXECUTE — open the trade
  2. SKIP — don't open (low confidence, bad setup)
  3. MODIFY — adjust entry/SL/TP based on deeper analysis

For active trades, AI decides:
  1. HOLD — keep current SL/TP
  2. MOVE_SL — move stop loss to protect profit
  3. CLOSE — exit trade early (trend changing)
  4. PARTIAL — close half, keep rest
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

_last_ai_time = {}
_ai_cache = {}

DEEPSEEK_API = os.getenv("DEEPSEEK_API_KEY", "sk-a0f838920b5348d58b1bf10e34748729")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Cache the last AI decision to avoid spamming API
_last_ai_decision_time = {}
_ai_cache = {}


def ask_ai(prompt, max_tokens=300):
    """Send a prompt to DeepSeek and get response."""
    import requests
    try:
        r = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You are a professional ICT/SMC trader analyzing CFI:US100 (Nasdaq 100). You speak Arabic and English. Be decisive — never say 'it depends'. Answer in JSON format only."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=20,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        logger.warning("DeepSeek error: %s", r.status_code)
        return None
    except Exception as e:
        logger.warning("DeepSeek API error: %s", e)
        return None


def evaluate_signal(signal, candles_daily, candles_15m):
    """AI evaluates a trading signal and decides whether to execute.

    Returns JSON: {"action":"EXECUTE"|"SKIP"|"MODIFY", "confidence":0.75, "reason":"...", "entry":..., "sl":..., "tp":...}
    """
    import time
    now = time.time()
    key = f"{signal.get('symbol','?')}_{signal.get('direction','?')}"
    if key in _last_ai_time and now - _last_ai_time[key] < 300:
        logger.info("AI: Using cached decision for %s", key)
        return _ai_cache.get(key, {"action": "EXECUTE", "confidence": signal.get("confidence", 0.7)})

    # Build market context
    from run_us100_monitor import fmt
    price = signal.get("price_now", signal.get("entry"))

    # Last 5 daily candles
    daily_summary = ""
    if candles_daily and len(candles_daily) >= 5:
        for c in candles_daily[:5]:
            body = c[4] - c[1]
            color = "GREEN" if body > 0 else "RED"
            daily_summary += f"  {color}: O={fmt(c[1])} H={fmt(c[2])} L={fmt(c[3])} C={fmt(c[4])}\n"

    # 15M summary
    m15_high = max(c[2] for c in candles_15m) if candles_15m else price
    m15_low = min(c[3] for c in candles_15m) if candles_15m else price
    m15_range = m15_high - m15_low

    prompt = f"""You are an expert ICT/SMC trader. Evaluate this signal for CFI:US100 (Nasdaq 100).

CURRENT PRICE: {fmt(price)}

DAILY STRUCTURE (last 5 days):
{daily_summary}
15M RANGE: {fmt(m15_low)} - {fmt(m15_high)} ({m15_range:.1f} pts)

SIGNAL TO EVALUATE:
  Direction: {signal['direction']}
  Setup: {signal.get('setup','')}
  Entry: {fmt(signal['entry'])}
  SL: {fmt(signal['sl'])}
  TP: {fmt(signal.get('tp',signal.get('tp2',0)))}
  Confidence: {signal.get('confidence',0):.0%}
  Reasoning: {signal.get('reasoning','')[:200]}

DECIDE and return ONLY a JSON object:
{{
  "action": "EXECUTE" or "SKIP" or "MODIFY",
  "confidence": 0.0 to 1.0,
  "reason_ar": "Arabic reason with emojis",
  "reason_en": "English reason"
}}

Rules:
- SKIP if signal goes against daily trend or SL too tight
- MODIFY if SL needs adjustment, provide new SL
- EXECUTE if setup makes sense with trend and risk"""

    response = ask_ai(prompt, max_tokens=300)
    _last_ai_time[key] = now

    if response:
        try:
            # Try to find JSON in response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                decision = json.loads(response[start:end])
                decision["raw"] = response
                _ai_cache[key] = decision
                logger.info("AI Decision: %s (conf=%.0f%%)", decision.get("action"), decision.get("confidence", 0) * 100)
                return decision
        except json.JSONDecodeError:
            logger.warning("AI response not valid JSON: %s", response[:200])

    # Default: trust the signal
    return {"action": "EXECUTE", "confidence": signal.get("confidence", 0.7)}


def manage_trade_ai(position_info, candles_5m):
    """AI decides how to manage an active trade.

    Returns JSON: {"action":"HOLD"|"MOVE_SL"|"CLOSE"|"PARTIAL", "new_sl":..., "reason":"..."}
    """
    from run_us100_monitor import fmt

    entry = position_info.get("entry", 0)
    current_price = position_info.get("current_price", 0)
    sl = position_info.get("sl", 0)
    tp = position_info.get("tp", 0)
    profit_pct = position_info.get("profit_pct", 0)
    direction = position_info.get("direction", "LONG")

    # 5M recent structure
    m5_summary = ""
    if candles_5m and len(candles_5m) >= 5:
        last5 = candles_5m[:5]
        bodies = [c[4] - c[1] for c in last5]
        body_dir = "bullish" if sum(bodies) > 0 else "bearish"
        highs = max(c[2] for c in last5)
        lows = min(c[3] for c in last5)
        m5_summary = f"5M: {body_dir}, range {fmt(lows)}-{fmt(highs)}"

    prompt = f"""You manage an active trade on CFI:US100. Decide what to do.

TRADE:
  Direction: {direction}
  Entry: {fmt(entry)}
  Current SL: {fmt(sl)}
  Target TP: {fmt(tp)}
  Current Price: {fmt(current_price)}
  P/L: {profit_pct:+.2f}%
  {m5_summary}

Decide and return JSON:
{{
  "action": "HOLD" or "MOVE_SL" or "CLOSE" or "PARTIAL",
  "new_sl": number or 0 (if MOVE_SL),
  "reason_ar": "Arabic reason",
  "reason_en": "English reason"
}}

Rules:
- If profit >0.1% and trending → MOVE_SL to entry
- If profit >0.3% and strong trend → MOVE_SL trail
- If reversing → CLOSE
- If profit >0.2% sideways → PARTIAL (close half)"""

    response = ask_ai(prompt, max_tokens=200)
    if response:
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except:
            pass
    return {"action": "HOLD"}
