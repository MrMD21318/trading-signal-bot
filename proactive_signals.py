"""Proactive Signal System — alerts before, during, and after entries.

Levels:
  WATCH — Price approaching a key level
  READY — Confirmation building (2 of 3 required)
  ENTRY — Confirmed, place trade now
  HIT — TP/SL reached
"""

import time, logging

logger = logging.getLogger(__name__)

# Track state to avoid spamming
_last_watch = {}
_last_ready = {}
_last_entry = {}
_last_gap = None


def detect_gap(symbol, current_price, prev_close, timeframe="1D"):
    """Detect gap at market open."""
    global _last_gap
    gap = current_price - prev_close
    gap_pct = gap / prev_close * 100

    if abs(gap_pct) < 0.05:  # Less than 0.05% = no real gap
        return None

    key = f"{symbol}_gap"
    if _last_gap == key:
        return None
    _last_gap = key

    direction = "UP" if gap > 0 else "DOWN"
    return {
        "type": "GAP",
        "direction": direction,
        "price": current_price,
        "prev_close": prev_close,
        "gap_pts": abs(gap),
        "msg": f"GAP {direction} — {abs(gap):.0f} pts\nPrev close: {prev_close:.0f}\nOpen: {current_price:.0f}",
        "entry": f"Buy after gap fill" if gap > 0 else "Sell after gap fill",
    }


def check_watch(symbol, current_price, support_levels, resistance_levels):
    """Alert when price approaches a key level (within 15 pts)."""
    global _last_watch

    key = f"{symbol}_watch"
    if key in _last_watch and time.time() - _last_watch[key] < 300:
        return None

    for level in support_levels:
        dist = abs(current_price - level)
        if dist < 15 and current_price > level:
            _last_watch[key] = time.time()
            return {
                "type": "WATCH",
                "level": level,
                "direction": "BUY",
                "msg": f"Price approaching SUPPORT {level:.0f}\nOnly {dist:.0f} pts away\nGet ready to BUY",
            }

    for level in resistance_levels:
        dist = abs(current_price - level)
        if dist < 15 and current_price < level:
            _last_watch[key] = time.time()
            return {
                "type": "WATCH",
                "level": level,
                "direction": "SELL",
                "msg": f"Price approaching RESISTANCE {level:.0f}\nOnly {dist:.0f} pts away\nGet ready to SELL",
            }

    # Reset if price moved away
    if current_price < min(support_levels) - 30 or current_price > max(resistance_levels) + 30:
        key_to_clear = [k for k in _last_watch if k.startswith(symbol)]
        for k in key_to_clear:
            if time.time() - _last_watch[k] > 300:
                del _last_watch[k]

    return None


def check_ready(symbol, current_price, candles_1m, key_level, direction):
    """Alert when confirmation is building (2 of 3 conditions met)."""
    global _last_ready

    if len(candles_1m) < 5:
        return None

    key = f"{symbol}_ready_{direction}"
    if key in _last_ready and time.time() - _last_ready[key] < 600:
        return None

    # Condition 1: Price near key level (within 10 pts)
    near_level = abs(current_price - key_level) < 10

    # Condition 2: Candles turning in right direction
    if direction == "BUY":
        turning = sum(1 for c in candles_1m[-3:] if c[4] > c[1]) >= 2  # 2 of 3 green
    else:
        turning = sum(1 for c in candles_1m[-3:] if c[4] < c[1]) >= 2  # 2 of 3 red

    # Condition 3: Volume increasing
    if len(candles_1m) >= 6:
        vol_recent = sum(c[5] for c in candles_1m[-3:]) / 3
        vol_prev = sum(c[5] for c in candles_1m[-6:-3]) / 3
        vol_up = vol_recent > vol_prev * 1.2
    else:
        vol_up = False

    conditions_met = sum([near_level, turning, vol_up])

    if conditions_met >= 2:
        _last_ready[key] = time.time()
        return {
            "type": "READY",
            "direction": direction,
            "level": key_level,
            "conditions": conditions_met,
            "msg": f"Setup forming: {direction} at {key_level:.0f}\nConditions: {conditions_met}/3 met\nNear level: {'Yes' if near_level else 'No'}\nCandles turning: {'Yes' if turning else 'No'}\nVolume: {'Up' if vol_up else 'Normal'}\nWAITING for 3/3 to ENTER",
        }

    return None


def check_entry(symbol, current_price, candles_1m, candles_5m, key_level, direction):
    """Alert when all 3 conditions are met — EXECUTE NOW."""
    global _last_entry

    if len(candles_1m) < 6 or len(candles_5m) < 4:
        return None

    key = f"{symbol}_entry_{direction}_{int(key_level)}"
    if key in _last_entry and time.time() - _last_entry[key] < 1800:
        return None

    # 3-CANDLE CONFIRMATION (must have 3 consecutive in right direction)
    if direction == "BUY":
        confirmed = sum(1 for c in candles_1m[-3:] if c[4] > c[1]) == 3
        # Also check 5M is green
        tf_ok = sum(1 for c in candles_5m[-3:] if c[4] > c[1]) >= 2
        sl = current_price - 25
        tp = current_price + 60
    else:
        confirmed = sum(1 for c in candles_1m[-3:] if c[4] < c[1]) == 3
        tf_ok = sum(1 for c in candles_5m[-3:] if c[4] < c[1]) >= 2
        sl = current_price + 25
        tp = current_price - 60

    if confirmed and tf_ok:
        _last_entry[key] = time.time()
        return {
            "type": "ENTRY",
            "direction": direction,
            "entry": current_price,
            "sl": sl,
            "tp": tp,
            "msg": f"ENTRY CONFIRMED — {direction}\nEntry: {current_price:.1f}\nSL: {sl:.1f} | TP: {tp:.1f}\n3-candle confirmation + 5M aligned\nEXECUTE NOW",
        }

    return None


def session_alert(session_name, price, trend, levels):
    """Generate session open alert with prediction."""
    sup = levels.get("support", [])[:2]
    res = levels.get("resistance", [])[:2]

    direction = "BULLISH" if trend > 0.3 else "BEARISH" if trend < -0.3 else "NEUTRAL"

    msg = f"{session_name} OPEN\nPrice: {price:.1f}\nTrend: {direction} ({trend:+.1f}%)\n"
    if sup:
        msg += f"Support: {sup[0]:.0f}, {sup[1]:.0f}\n" if len(sup) > 1 else f"Support: {sup[0]:.0f}\n"
    if res:
        msg += f"Resistance: {res[0]:.0f}, {res[1]:.0f}\n" if len(res) > 1 else f"Resistance: {res[0]:.0f}\n"

    if direction == "BULLISH":
        msg += f"\nPrediction: Buy pullbacks to {sup[0]:.0f}"
    elif direction == "BEARISH":
        msg += f"\nPrediction: Sell rallies to {res[0]:.0f}"

    return msg
