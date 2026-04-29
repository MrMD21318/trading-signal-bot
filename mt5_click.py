"""MT5 Click Automation — trades via mouse/keyboard when API is blocked.

IMPORTANT: Keep MT5 window visible on screen. Don't minimize.
The bot finds MT5, brings it to foreground, and clicks/keys to trade.
"""

import logging
import time

logger = logging.getLogger(__name__)

try:
    import pyautogui
    import pygetwindow as gw
    HAS_AUTO = True
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.1
except ImportError:
    HAS_AUTO = False
    logger.warning("Install pyautogui + pygetwindow: pip install pyautogui pygetwindow")


def get_mt5_window():
    """Find and focus MetaTrader 5 window."""
    if not HAS_AUTO:
        return None
    windows = gw.getWindowsWithTitle("MetaTrader")
    for w in windows:
        if w.visible and w.width > 400:
            return w
    return None


def focus_mt5():
    w = get_mt5_window()
    if w:
        w.activate()
        time.sleep(0.3)
        return True
    return False


def click(x, y):
    pyautogui.click(x, y)
    time.sleep(0.15)


def press_key(key):
    pyautogui.press(key)
    time.sleep(0.1)


def type_text(text):
    pyautogui.write(str(text), interval=0.02)
    time.sleep(0.1)


def open_order_window():
    """Press F9 to open New Order window."""
    if not focus_mt5():
        return False
    press_key("f9")
    time.sleep(0.5)
    return True


def place_buy_market(sl_points=40, tp_points=80, lot=0.01):
    """Place a market buy order via UI automation.

    1. F9 → New Order
    2. Tab to volume → type lot
    3. Tab to SL → type SL
    4. Tab to TP → type TP
    5. Click Buy button
    """
    if not HAS_AUTO:
        logger.error("pyautogui not available")
        return False

    from mt5_executor import get_mt5_config
    cfg = get_mt5_config()
    symbol = cfg["symbol"]  # US100_Spot

    if not focus_mt5():
        return False

    # F9 opens order
    press_key("f9")
    time.sleep(0.6)

    # Type symbol
    press_key("tab")
    type_text(symbol)
    press_key("enter")
    time.sleep(0.3)

    # Tab to volume
    press_key("tab")
    press_key("tab")
    type_text(str(lot))
    time.sleep(0.1)

    # Tab to SL
    press_key("tab")
    press_key("tab")
    type_text(str(sl_points))
    time.sleep(0.1)

    # Tab to TP  
    press_key("tab")
    type_text(str(tp_points))
    time.sleep(0.1)

    # Click Buy (red/green buttons at bottom of order window)
    # The Buy button is typically at bottom-left
    w = get_mt5_window()
    if w:
        buy_x = w.left + 300
        buy_y = w.top + w.height - 80
        click(buy_x, buy_y)

    time.sleep(0.5)
    return True


def modify_sl_tp(new_sl=None, new_tp=None):
    """Modify SL/TP on active position via right-click menu.
    
    Requires position to be selected in Terminal (Ctrl+T).
    """
    if not HAS_AUTO:
        return False

    if not focus_mt5():
        return False

    # Ctrl+T → Terminal
    pyautogui.hotkey("ctrl", "t")
    time.sleep(0.3)

    # Right-click on position area (usually at bottom of screen)
    w = get_mt5_window()
    if w:
        click_x = w.left + 200
        click_y = w.top + w.height - 200
        pyautogui.rightClick(click_x, click_y)
        time.sleep(0.3)

    # Navigate to "Modify" — press down arrow 2 times then Enter
    for _ in range(2):
        press_key("down")
        time.sleep(0.1)

    if new_sl is not None:
        # Tab through fields to SL
        for _ in range(5):
            press_key("tab")
            time.sleep(0.05)
        pyautogui.hotkey("ctrl", "a")
        type_text(str(int(new_sl)))

    if new_tp is not None:
        press_key("tab")
        pyautogui.hotkey("ctrl", "a")
        type_text(str(int(new_tp)))

    # Click Modify button
    press_key("enter")
    time.sleep(0.5)
    return True


def close_position():
    """Close current position via Alt+B or right-click → Close."""
    if not focus_mt5():
        return False

    # Ctrl+T for Terminal
    pyautogui.hotkey("ctrl", "t")
    time.sleep(0.3)

    w = get_mt5_window()
    if w:
        click_x = w.left + 200
        click_y = w.top + w.height - 200
        pyautogui.rightClick(click_x, click_y)
        time.sleep(0.3)
        # "Close Position" is first option
        press_key("enter")
        time.sleep(0.5)

        # Confirm red close button on the confirmation dialog
        press_key("tab")
        press_key("enter")
        time.sleep(0.3)

    return True


def execute_signal_via_ui(signal):
    """Execute a trading signal via MT5 UI automation."""
    direction = signal.get("direction", "LONG")
    entry = signal.get("entry", 0)
    sl = signal.get("sl", 0)
    tp = signal.get("tp2", signal.get("tp", 0))
    lot = signal.get("lot", 0.01)
    setup = signal.get("setup", "Auto")

    if not HAS_AUTO:
        return False

    if not focus_mt5():
        return False

    # Open New Order (F9)
    press_key("f9")
    time.sleep(0.5)

    # Tab to volume (usually 3rd field after symbol/type)
    for _ in range(2):
        press_key("tab")
        time.sleep(0.05)

    type_text(str(lot))
    time.sleep(0.1)

    # SL/TP fields
    press_key("tab")
    if direction == "LONG":
        type_text(str(int(sl)))
    else:
        type_text(str(int(sl)))

    press_key("tab")
    type_text(str(int(tp)))

    # Click Buy or Sell button
    w = get_mt5_window()
    if w:
        if direction == "LONG":
            click(w.left + 280, w.top + w.height - 100)
        else:
            click(w.left + 400, w.top + w.height - 100)

    time.sleep(0.5)
    logger.info("UI: %s order placed via automation — Lot: %s", direction, lot)
    return True
