"""MT5 Trade Manager — monitors active positions and manages SL/TP dynamically.

Features:
- Move SL to breakeven when TP1 is reached
- Trail stop in strong trends
- Detect sideways → hold for TP2
- Send Telegram notifications on every adjustment
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_OK = True
except ImportError:
    MT5_OK = False


def get_cfg():
    return {
        "symbol": os.getenv("MT5_SYMBOL", "US100"),
        "enabled": os.getenv("MT5_ENABLED", "false").lower() == "true",
    }


def get_candles_data(symbol, tf, count):
    """Get candles for trend detection."""
    try:
        from run_us100_monitor import get_candles
        return get_candles(symbol, tf, count)
    except:
        return []


def is_sideways(candles):
    """Detect if market is ranging/choppy."""
    if len(candles) < 10:
        return False
    recent = candles[:10]
    high = max(c[2] for c in recent)
    low = min(c[3] for c in recent)
    rng = high - low
    avg_price = sum(c[4] for c in recent) / len(recent)
    return (rng / avg_price * 100) < 0.15  # less than 0.15% range = sideways


def is_strong_trend(candles):
    """Detect strong directional movement."""
    if len(candles) < 10:
        return False
    closes = [c[4] for c in candles[:10]]
    # Consistent higher closes
    higher = sum(1 for i in range(len(closes) - 1) if closes[i] > closes[i + 1])
    lower = sum(1 for i in range(len(closes) - 1) if closes[i] < closes[i + 1])
    return higher >= 7 or lower >= 7


def manage_positions(tg_send_callback=None):
    """Check all MT5 positions and manage SL/TP dynamically.

    Returns list of Telegram messages to send.
    """
    if not MT5_OK:
        return []

    cfg = get_cfg()
    if not cfg["enabled"]:
        return []

    if not mt5.terminal_info():
        return []

    symbol = cfg["symbol"]
    messages = []
    candles_5m = get_candles_data(symbol, "5", 15)

    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return []

    for pos in positions:
        try:
            pos_id = pos.ticket
            entry_price = pos.price_open
            current_price = pos.price_current
            sl = pos.sl
            tp = pos.tp
            direction = "LONG" if pos.type == mt5.POSITION_TYPE_BUY else "SHORT"
            profit_pct = (current_price - entry_price) / entry_price * 100 if direction == "LONG" else (entry_price - current_price) / entry_price * 100

            # ── TP1 reached? Move SL to breakeven ──
            if profit_pct > 0.08:  # 0.08% profit (TP1 zone)
                if direction == "LONG" and sl < entry_price:
                    # Move SL to entry + 1pt
                    new_sl = entry_price + 1
                    req = {"action": mt5.TRADE_ACTION_SLTP, "position": pos_id, "sl": new_sl, "tp": tp}
                    result = mt5.order_send(req)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        msg = f"\U0001f6d1 <b>SL → Breakeven</b>\n{profit_pct:.2f}% profit | SL moved to entry"
                        messages.append(msg)
                        logger.info("MT5: SL→BE for #%d @ %.1f", pos_id, entry_price)
                    else:
                        logger.warning("MT5 SL adjust failed: %s", result.comment)
                elif direction == "SHORT" and sl > entry_price:
                    new_sl = entry_price - 1
                    req = {"action": mt5.TRADE_ACTION_SLTP, "position": pos_id, "sl": new_sl, "tp": tp}
                    result = mt5.order_send(req)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        messages.append(f"\U0001f6d1 <b>SL → Breakeven</b>\n{profit_pct:.2f}% profit | SL moved to entry")
                        logger.info("MT5: SL→BE for #%d", pos_id)

            # ── Strong trend? Trail stop ──
            if profit_pct > 0.20 and is_strong_trend(candles_5m):
                trail_distance = abs(current_price - sl) * 0.5  # 50% of current distance
                if direction == "LONG":
                    new_sl = current_price - trail_distance
                    if new_sl > sl and new_sl > entry_price:
                        req = {"action": mt5.TRADE_ACTION_SLTP, "position": pos_id, "sl": new_sl, "tp": tp}
                        result = mt5.order_send(req)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            messages.append(f"\U0001f4c8 <b>SL Trailed</b>\n+{profit_pct:.2f}% | New SL: {new_sl:.1f}")
                else:
                    new_sl = current_price + trail_distance
                    if new_sl < sl and new_sl < entry_price:
                        req = {"action": mt5.TRADE_ACTION_SLTP, "position": pos_id, "sl": new_sl, "tp": tp}
                        result = mt5.order_send(req)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            messages.append(f"\U0001f4c8 <b>SL Trailed</b>\n+{profit_pct:.2f}% | New SL: {new_sl:.1f}")

            # ── Sideways? Don't adjust TP, hold ──
            if is_sideways(candles_5m) and profit_pct > 0.05:
                pass  # Hold position, let it reach original TP

        except Exception as e:
            logger.error("MT5 manage error: %s", e)

    return messages
