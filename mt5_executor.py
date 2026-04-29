"""MetaTrader 5 auto-trade executor for US100 signals.

Connects to MT5 and automatically places trades based on signals.
Supports: Buy/Sell Limit, Buy/Sell Stop orders with SL and TP.
"""

import logging
import os

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.warning("MetaTrader5 not installed. pip install MetaTrader5")


# ── Config from .env ──
def get_mt5_config():
    return {
        "login": int(os.getenv("MT5_LOGIN", "0")),
        "password": os.getenv("MT5_PASSWORD", ""),
        "server": os.getenv("MT5_SERVER", ""),
        "enabled": os.getenv("MT5_ENABLED", "false").lower() == "true",
        "risk_percent": float(os.getenv("MT5_RISK_PCT", "1.0")),  # risk per trade %
        "symbol": os.getenv("MT5_SYMBOL", "US100"),  # MT5 symbol name
        "max_spread": int(os.getenv("MT5_MAX_SPREAD", "50")),  # max spread points
    }


def connect():
    """Connect to MT5 terminal. Returns True if connected."""
    if not MT5_AVAILABLE:
        return False

    cfg = get_mt5_config()
    if not cfg["enabled"] or not cfg["login"]:
        logger.info("MT5 disabled or not configured")
        return False

    if mt5.initialize():
        authorized = mt5.login(cfg["login"], password=cfg["password"], server=cfg["server"])
        if authorized:
            logger.info("MT5 connected: %s on %s", cfg["login"], cfg["server"])
            return True
        else:
            logger.error("MT5 login failed: %s", mt5.last_error())
    else:
        logger.error("MT5 init failed: %s", mt5.last_error())
    return False


def disconnect():
    if MT5_AVAILABLE:
        mt5.shutdown()


def calculate_lot_size(sl_points):
    """Calculate lot size based on risk percentage."""
    cfg = get_mt5_config()
    account = mt5.account_info()
    if not account:
        return 0.01

    balance = account.balance
    risk_amount = balance * (cfg["risk_percent"] / 100)

    symbol_info = mt5.symbol_info(cfg["symbol"])
    if not symbol_info:
        return 0.01

    tick_value = symbol_info.trade_tick_value
    tick_size = symbol_info.trade_tick_size

    if tick_size == 0 or tick_value == 0:
        return 0.01

    lot_size = risk_amount / (sl_points / tick_size * tick_value)
    lot_size = round(lot_size, 2)
    return max(0.01, min(lot_size, 10.0))


def execute_signal(sig):
    """Execute a trading signal on MT5. Skips if conflicting position exists."""

    if not MT5_AVAILABLE:
        return {"ok": False, "error": "MT5 not available"}

    cfg = get_mt5_config()
    if not cfg["enabled"]:
        return {"ok": False, "error": "MT5 autotrade disabled"}

    if not mt5.terminal_info():
        if not connect():
            return {"ok": False, "error": "MT5 not connected"}

    symbol = cfg["symbol"]
    direction = sig["direction"]

    # Check existing positions — don't open conflicting trade
    positions = mt5.positions_get(symbol=symbol)
    if positions:
        for pos in positions:
            pos_dir = "LONG" if pos.type == mt5.POSITION_TYPE_BUY else "SHORT"
            if pos_dir != direction:
                logger.info("MT5: Skipping %s — conflicting %s position open (%d lots)",
                           direction, pos_dir, pos.volume)
                return {"ok": False, "error": f"Conflicting {pos_dir} position open on {symbol}"}
            else:
                logger.info("MT5: Already LONG on %s, skipping duplicate", symbol)
                return {"ok": False, "error": "Already in same direction"}

    # Also check pending orders — don't duplicate
    orders = mt5.orders_get(symbol=symbol)
    if orders and len(orders) >= 2:
        logger.info("MT5: %d pending orders on %s, skipping", len(orders), symbol)
        return {"ok": False, "error": f"{len(orders)} pending orders already"}
    entry = sig["entry"]
    sl = sig["sl"]
    tp = sig.get("tp2", sig.get("tp", entry))
    order_type = sig.get("order_type", "")
    setup = sig.get("setup", "Signal")

    # Ensure symbol is available
    mt5.symbol_select(symbol, True)

    # Get current price for market orders vs pending
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"ok": False, "error": f"No tick data for {symbol}"}
    current_price = tick.ask if direction == "LONG" else tick.bid

    # Determine order type
    is_limit = "Limit" in order_type
    is_stop = "Stop" in order_type

    if direction == "LONG":
        if is_stop:
            order_price = entry  # Buy Stop above market
            mt5_type = mt5.ORDER_TYPE_BUY_STOP
        elif is_limit:
            order_price = entry  # Buy Limit below market
            mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
        else:
            order_price = tick.ask  # Market buy
            mt5_type = mt5.ORDER_TYPE_BUY

        sl_price = sl
        tp_price = tp
        sl_points = entry - sl
    else:
        if is_stop:
            order_price = entry
            mt5_type = mt5.ORDER_TYPE_SELL_STOP
        elif is_limit:
            order_price = entry
            mt5_type = mt5.ORDER_TYPE_SELL_LIMIT
        else:
            order_price = tick.bid
            mt5_type = mt5.ORDER_TYPE_SELL

        sl_price = sl
        tp_price = tp
        sl_points = sl - entry

    if sl_points <= 0:
        return {"ok": False, "error": f"Invalid SL: entry={entry} sl={sl}"}

    lot = calculate_lot_size(sl_points)

    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": lot,
        "type": mt5_type,
        "price": order_price,
        "sl": sl_price,
        "tp": tp_price,
        "deviation": 20,
        "magic": 100700,  # unique ID for our bot
        "comment": f"{setup[:25]} | {sig.get('timeframe','')}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(
            "MT5 ORDER: %s %s %.1f lots @ %.1f SL=%.1f TP=%.1f | %s",
            direction, order_type, lot, order_price, sl_price, tp_price, setup,
        )
        return {
            "ok": True,
            "order_id": result.order,
            "lot": lot,
            "entry": order_price,
            "sl": sl_price,
            "tp": tp_price,
        }
    else:
        logger.error("MT5 order failed: %s (code %s)", result.comment, result.retcode)
        return {"ok": False, "error": f"MT5: {result.comment}"}
