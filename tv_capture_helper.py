import os
import time
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

logger = logging.getLogger(__name__)

def capture_tv_chart(symbol="CFI:US100", timeframe="15M", output_filename=None):
    """
    Capture TradingView chart screenshot for a specific symbol and timeframe.
    Returns the absolute path to the screenshot, or None if failed.
    """
    # Timeframe mapping
    tf_mapping = {
        "1M": "1", "1m": "1",
        "5M": "5", "5m": "5",
        "15M": "15", "15m": "15",
        "30M": "30", "30m": "30",
        "1H": "60", "1h": "60",
        "4H": "240", "4h": "240",
        "Daily": "1D", "1D": "1D", "1d": "1D"
    }
    tf_code = tf_mapping.get(timeframe, "15")
    
    opts = Options()
    opts.add_argument("--window-size=1280,720")
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--mute-audio")
    opts.add_argument("--disable-dev-shm-usage")
    # Custom user-agent to ensure page loads in headless mode
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    logger.info("Starting Selenium to capture %s (%s)...", symbol, timeframe)
    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as e:
        logger.error("Failed to initialize Chrome driver: %s", e)
        return None
        
    try:
        url = f"https://www.tradingview.com/chart/?symbol={symbol}&interval={tf_code}"
        driver.get(url)
        
        # Allow enough time for TradingView websocket and canvas to load
        time.sleep(6)
        
        # Scroll down slightly to center the chart canvas
        driver.execute_script("window.scrollTo(0, 200);")
        time.sleep(1)
        
        if not output_filename:
            output_filename = f"chart_{timeframe}.png"
            
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), output_filename))
        driver.save_screenshot(path)
        logger.info("Chart captured successfully: %s", path)
        return path
    except Exception as e:
        logger.error("Error capturing TradingView chart: %s", e)
        return None
    finally:
        driver.quit()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = capture_tv_chart(symbol="CFI:US100", timeframe="15M")
    if path:
        print(f"Captured: {path}")
    else:
        print("Failed to capture.")
