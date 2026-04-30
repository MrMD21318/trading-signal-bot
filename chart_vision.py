"""Chart Vision Reader — takes TradingView screenshot, sends to GPT-4 Vision for SMC analysis."""

import os, base64, json, requests

GPT_KEY = os.getenv("OPENAI_API_KEY", "")


def read_chart(image_path, prompt="Read the chart"):
    """Send chart image to GPT-4 Vision and get SMC analysis."""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    resp = requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {GPT_KEY}"},
        json={
            "model": "gpt-4o",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": """Analyze this TradingView chart of CFI:US100 (Nasdaq100).
Return ONLY a JSON with these SMC levels:
{
  "price": current price,
  "trend": "bullish" or "bearish",
  "swing_highs": [levels],
  "swing_lows": [levels],
  "order_blocks": [{"type":"bullish/bearish","top":price,"bottom":price}],
  "fvgs": [{"type":"bullish/bearish","top":price,"bottom":price}],
  "eqh": [levels],
  "eql": [levels],
  "bos": [{"type":"bullish/bearish","level":price}],
  "choch": [{"type":"bullish/bearish","level":price}],
  "weak_high": price or null,
  "strong_low": price or null,
  "signal": "buy" or "sell" or "wait",
  "entry": price, "stop_loss": price, "take_profit": price
}"""},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
                ]
            }],
            "max_tokens": 1000
        }, timeout=30)

    if resp.status_code == 200:
        content = resp.json()["choices"][0]["message"]["content"]
        # Extract JSON
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0:
            return json.loads(content[start:end])
        return {"raw": content}
    return {"error": f"GPT error {resp.status_code}: {resp.text[:200]}"}


def capture_chart():
    """Capture TradingView chart screenshot via pyautogui."""
    try:
        import pyautogui, pygetwindow as gw
        # Find browser window with TradingView
        for w in gw.getAllWindows():
            title = w.title or ""
            if "US100" in title or "CFI" in title or "TradingView" in title:
                if w.visible and w.width > 400:
                    w.activate()
                    import time; time.sleep(0.5)
                    img = pyautogui.screenshot(region=(w.left, w.top, w.width, w.height))
                    path = os.path.join(os.path.dirname(__file__), "chart.png")
                    img.save(path)
                    return path
    except Exception as e:
        print(f"Capture error: {e}")
    return None


def get_smc_signal():
    """Capture chart + AI analysis + return signal."""
    path = capture_chart()
    if not path:
        # Fallback: read existing screenshot
        path = os.path.join(os.path.dirname(__file__), "chart.png")
        if not os.path.exists(path):
            return {"error": "No chart screenshot available. Open TradingView first."}

    print(f"Reading chart from {path}...")
    result = read_chart(path)
    return result


if __name__ == "__main__":
    result = get_smc_signal()
    print(json.dumps(result, indent=2))
