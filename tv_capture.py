"""TradingView Chart Capture — opens browser, navigates CFI:US100, captures all timeframes."""

import time, os, base64, json, requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

GPT_KEY = os.getenv("OPENAI_API_KEY", "")
TIMEFRAMES = {
    "1M": "1", "5M": "5", "15M": "15", "1H": "60", "4H": "240", "Day": "1D"
}


def get_driver():
    opts = Options()
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--headless=new")  # Run without visible window
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=opts)
    return driver


def capture_timeframes():
    driver = get_driver()
    screenshots = {}

    try:
        for label, tf_code in TIMEFRAMES.items():
            try:
                # Navigate directly with interval in URL
                url = f"https://www.tradingview.com/chart/?symbol=CFI:US100&interval={tf_code}"
                driver.get(url)
                time.sleep(3)

                # Scroll chart area into view and wait for render
                driver.execute_script("window.scrollTo(0, 300);")
                time.sleep(1)

                path = os.path.join(os.path.dirname(__file__), f"chart_{label}.png")
                driver.save_screenshot(path)
                screenshots[label] = path
                print(f"Captured {label} ({tf_code}) -> {path}")
            except Exception as e:
                print(f"Failed {label}: {e}")

    finally:
        driver.quit()

    return screenshots


def analyze_with_gpt(image_path, timeframe):
    """Send chart to GPT-4 Vision for SMC analysis."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    resp = requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {GPT_KEY}"},
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": f"You are an SMC/ICT expert. This is CFI:US100 {timeframe} chart. Analyze: trend direction, any order blocks (OB), fair value gaps (FVG), swing highs/lows, BOS/CHoCH, liquidity sweeps. Give specific price levels you see on the chart. Then give ONE trading signal: direction, entry price, stop loss, take profit. Be specific with numbers."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]}],
            "max_tokens": 500
        }, timeout=40)

    if resp.status_code == 200:
        return resp.json()["choices"][0]["message"]["content"]
    return f"Error: {resp.status_code}"


def full_analysis():
    """Capture all timeframes and analyze each."""
    screenshots = capture_timeframes()
    if not screenshots:
        print("No screenshots captured")
        return

    results = {}
    for tf_label, path in screenshots.items():
        print(f"\nAnalyzing {tf_label}...")
        analysis = analyze_with_gpt(path, tf_label)
        results[tf_label] = analysis
        print(analysis[:200])

    # Save full report
    report = "\n\n=== " + "=" * 40 + "\n\n".join(
        f"=== {tf} ===\n{analysis}" for tf, analysis in results.items()
    )
    with open("smc_report.txt", "w", encoding="utf-8") as f:
        f.write(report)
    print("\nFull report saved to smc_report.txt")
    return results


if __name__ == "__main__":
    full_analysis()
