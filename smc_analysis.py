"""Smart Money Concepts (ICT) analysis — manual computation, no library dependency.

TP based on next liquidity pool, not arbitrary R:R.
"""

import os
import logging
import pandas as pd

from smc_manual import find_swings, find_bos_choch, find_order_blocks, find_fvg, find_liquidity

logger = logging.getLogger(__name__)



def candles_to_ohlc(candles):
    if not candles:
        return None
    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


def analyze_smc(candles, timeframe="15M", candles_lower=None, candles_higher=None):
    """SMC analysis on any timeframe with adaptive parameters.

    Timeframe affects swing_length, liquidity range, and min candles.
    """
    df = candles_to_ohlc(candles)
    if df is None:
        return []

    # Adaptive parameters per timeframe
    tf_config = {
        "1M":  {"swing_length": 8, "liq_range": 0.0003, "min_candles": 30, "bos_lookback": 15, "fvg_lookback": 10, "ob_lookback": 12, "liq_lookback": 20},
        "5M":  {"swing_length": 8, "liq_range": 0.0005, "min_candles": 25, "bos_lookback": 12, "fvg_lookback": 8,  "ob_lookback": 10, "liq_lookback": 18},
        "15M": {"swing_length": 10,"liq_range": 0.001,  "min_candles": 20, "bos_lookback": 10, "fvg_lookback": 8,  "ob_lookback": 10, "liq_lookback": 15},
        "1H":  {"swing_length": 12,"liq_range": 0.002,  "min_candles": 15, "bos_lookback": 8,  "fvg_lookback": 5,  "ob_lookback": 8,  "liq_lookback": 12},
        "4H":  {"swing_length": 15,"liq_range": 0.005,  "min_candles": 12, "bos_lookback": 6,  "fvg_lookback": 4,  "ob_lookback": 6,  "liq_lookback": 10},
        "Daily":{"swing_length": 15,"liq_range": 0.008,  "min_candles": 10, "bos_lookback": 4,  "fvg_lookback": 3,  "ob_lookback": 5,  "liq_lookback": 8},
    }
    cfg = tf_config.get(timeframe, tf_config["15M"])

    if len(df) < cfg["min_candles"]:
        return []

    signals = []
    last_idx = len(df) - 1
    price = float(df["close"].iloc[-1])

    # ── Run manual SMC ──
    candles_list = [[float(df["open"].iloc[i]), float(df["high"].iloc[i]),
                     float(df["low"].iloc[i]), float(df["close"].iloc[i]),
                     float(df["volume"].iloc[i])] for i in range(len(df))]
    candles_list = [[0, c[0], c[1], c[2], c[3], c[4]] for c in candles_list]

    swings_high, swings_low = find_swings(candles_list, cfg["swing_length"])
    bos_list, choch_list = find_bos_choch(candles_list, swings_high, swings_low)
    ob_list = find_order_blocks(candles_list)
    fvg_list = find_fvg(candles_list)
    liq_list = find_liquidity(candles_list, cfg["liq_range"])

    # Convert to our internal format
    swing_highs = [p for _, p in swings_high]
    swing_lows = [p for _, p in swings_low]

    # ── LuxAlgo Cross-Check Overlay ──
    try:
        from smc_luxalgo import compute_luxalgo_smc
        lux = compute_luxalgo_smc(candles_list, swing_length=min(40, len(candles_list)//3), internal_length=5)
        if lux:
            swing_highs = [p for _, p in lux.get("swing_highs", [])]
            swing_lows = [p for _, p in lux.get("swing_lows", [])]
            if lux.get("order_blocks"):
                # Map Bullish/Bearish from LuxAlgo swing point OBs
                ob_list = []
                for bias, idx, o_h, o_l in lux["order_blocks"]:
                    ob_list.append((bias, idx, o_h, o_l))
            if lux.get("bos"):
                bos_list = lux["bos"]
            if lux.get("choch"):
                choch_list = lux["choch"]
    except Exception as e:
        logger.error("LuxAlgo cross-check overlay failed, using manual SMC: %s", e)

    latest_bos = {"type": bos_list[-1][0], "level": bos_list[-1][2], "idx": bos_list[-1][1]} if bos_list else None
    latest_choch = {"type": choch_list[-1][0], "level": choch_list[-1][2], "idx": choch_list[-1][1]} if choch_list else None

    # Recent OB near price
    near_ob = None
    for o_type, o_idx, o_h, o_l in reversed(ob_list[-8:]):
        if (o_type == "Bullish" and o_l <= price <= o_h) or (o_type == "Bearish" and o_l <= price <= o_h):
            near_ob = {"type": o_type, "top": o_h, "bottom": o_l, "idx": o_idx}
            break

    # Recent FVG
    near_fvg = None
    for f_type, f_idx, f_low, f_high in reversed(fvg_list[-6:]):
        if (f_type == "Bullish" and f_low <= price <= f_high) or (f_type == "Bearish" and f_low <= price <= f_high):
            near_fvg = {"type": f_type, "top": f_high, "bottom": f_low, "idx": f_idx}
            break

    # Liquidity pools
    bullish_liq = []
    bearish_liq = []
    swept_bearish = []
    swept_bullish = []
    for l_type, l_idx, l_level, l_count in liq_list:
        entry = {"level": l_level, "swept": l_idx >= last_idx - cfg["bos_lookback"], "idx": l_idx}
        if l_type == "Bullish":
            bullish_liq.append(entry)
            if entry["swept"]:
                swept_bullish.append(entry)
        else:
            bearish_liq.append(entry)
            if entry["swept"]:
                swept_bearish.append(entry)

    def find_tp_long(sl_price):
        targets = []
        for sh in swing_highs:
            if sh > price:
                targets.append(sh)
        for bl in bearish_liq:
            if bl["level"] > price:
                targets.append(bl["level"])
        if targets:
            return min(targets)
        return price + (price - sl_price) * 2

    def find_tp_short(sl_price):
        targets = []
        for sw in swing_lows:
            if sw < price:
                targets.append(sw)
        for bl in bullish_liq:
            if bl["level"] < price:
                targets.append(bl["level"])
        if targets:
            return max(targets)
        return price - (sl_price - price) * 2

    # 2. Liquidity Sweep SHORT (bull trap)

    # 1. Liquidity Sweep LONG (bear trap)
    if swept_bearish:
        sweep = swept_bearish[0]
        sweep_level = sweep["level"]
        recent_low = float(df["low"].iloc[max(0, sweep["idx"]):last_idx+1].min())
        if price > recent_low * 1.001:
            sl_price = recent_low - abs(price - recent_low) * 0.1
            tp_price = find_tp_long(sl_price)
            entry_price = price
            if near_ob and near_ob["type"] == "Bullish" and near_ob["bottom"] <= price <= near_ob["top"]:
                entry_price = near_ob["bottom"]
            signals.append({
                "strategy": "SMC", "direction": "LONG",
                "setup": f"Liquidity Sweep + {'OB Entry' if near_ob and near_ob['type']=='Bullish' else 'Reversal'}",
                "order_type": "Buy Limit", "entry": round(entry_price, 1),
                "sl": round(sl_price, 1), "tp": round(tp_price, 1),
                "confidence": 0.78, "timeframe": timeframe, "price_now": price,
                "reasoning": (
                    f"Bearish liquidity swept at {fmt(sweep_level)} — stop hunt complete. "
                    f"Smart money grabbed sell-side stops, now reversing up. "
                    + (f"Entry at bullish OB ({fmt(near_ob['bottom'])}-{fmt(near_ob['top'])}). " if near_ob and near_ob["type"] == "Bullish" else "")
                    + f"SL below sweep low {fmt(sl_price)}. TP at next liquidity {fmt(tp_price)}."
                ),
            })

    # 2. Liquidity Sweep SHORT (bull trap)
        sweep = swept_bullish[0]
        sweep_level = sweep["level"]
        recent_high = float(df["high"].iloc[max(0, sweep["idx"]):last_idx+1].max())
        if price < recent_high * 0.999:
            sl_price = recent_high + abs(recent_high - price) * 0.1
            tp_price = find_tp_short(sl_price)
            entry_price = price
            if near_ob and near_ob["type"] == "Bearish" and near_ob["bottom"] <= price <= near_ob["top"]:
                entry_price = near_ob["top"]

            signals.append({
                "strategy": "SMC", "direction": "SHORT",
                "setup": f"Liquidity Sweep + Reversal",
                "order_type": "Sell Limit",
                "entry": round(price, 1), "sl": round(sl_price, 1),
                "tp": round(tp_price, 1),
                "confidence": 0.78, "timeframe": timeframe,
                "price_now": price,
                "reasoning": (
                    f"Bullish liquidity swept at {fmt(sweep_level)} — buy-side stops grabbed. "
                    f"Reversing down. SL above sweep high {fmt(sl_price)}. "
                    f"TP at next bullish liquidity pool {fmt(tp_price)}."
                ),
            })

    # 3. CHoCH Bullish — structure reversal
    if latest_choch and latest_choch["type"] == "Bullish" and latest_choch["idx"] >= last_idx - 5:
        recent_low = float(df["low"].iloc[max(0, latest_choch["idx"]):last_idx+1].min())
        sl_price = recent_low - abs(price - recent_low) * 0.05
        tp_price = find_tp_long(sl_price)
        # Entry at FVG if available
        entry_price = price
        if near_fvg and near_fvg["type"] == "Bullish" and near_fvg["bottom"] <= price <= near_fvg["top"]:
            entry_price = near_fvg["bottom"]
        signals.append({
            "strategy": "SMC", "direction": "LONG",
            "setup": "CHoCH Bullish — Structure Reversal",
            "order_type": "Buy Limit", "entry": round(entry_price, 1),
            "sl": round(sl_price, 1), "tp": round(tp_price, 1),
            "confidence": 0.75, "timeframe": timeframe,
            "price_now": price,
            "reasoning": (
                f"Change of Character: price broke above swing high — sellers lost control. "
                + (f"Entering at bullish FVG ({fmt(near_fvg['bottom'])}-{fmt(near_fvg['top'])}). " if near_fvg and near_fvg["type"] == "Bullish" else "")
                + f"SL below recent low {fmt(sl_price)}. TP at liquidity {fmt(tp_price)}."
            ),
        })

    # 4. CHoCH Bearish
    if latest_choch and latest_choch["type"] == "Bearish" and latest_choch["idx"] >= last_idx - 5:
        recent_high = float(df["high"].iloc[max(0, latest_choch["idx"]):last_idx+1].max())
        sl_price = recent_high + abs(recent_high - price) * 0.05
        tp_price = find_tp_short(sl_price)
        entry_price = price
        if near_fvg and near_fvg["type"] == "Bearish" and near_fvg["bottom"] <= price <= near_fvg["top"]:
            entry_price = near_fvg["top"]
        signals.append({
            "strategy": "SMC", "direction": "SHORT",
            "setup": "CHoCH Bearish — Structure Reversal",
            "order_type": "Sell Limit", "entry": round(entry_price, 1),
            "sl": round(sl_price, 1), "tp": round(tp_price, 1),
            "confidence": 0.75, "timeframe": timeframe,
            "price_now": price,
            "reasoning": (
                f"Change of Character: price broke below swing low — buyers lost control. "
                + (f"Entering at bearish FVG. " if near_fvg and near_fvg["type"] == "Bearish" else "")
                + f"SL above recent high {fmt(sl_price)}. TP at liquidity {fmt(tp_price)}."
            ),
        })

    # 5. Order Block Bounce — price at institutional level
    if near_ob:
        if near_ob["type"] == "Bullish" and near_ob["bottom"] * 0.998 <= price <= near_ob["top"] * 1.01:
            sl_price = near_ob["bottom"] - abs(near_ob["top"] - near_ob["bottom"]) * 0.5
            tp_price = find_tp_long(sl_price)
            signals.append({
                "strategy": "SMC", "direction": "LONG",
                "setup": "Bullish Order Block Bounce",
                "order_type": "Buy Limit", "entry": round(near_ob["bottom"], 1),
                "sl": round(sl_price, 1), "tp": round(tp_price, 1),
                "confidence": 0.70, "timeframe": timeframe,
                "price_now": price,
                "reasoning": (
                    f"Price at bullish Order Block ({fmt(near_ob['bottom'])}-{fmt(near_ob['top'])}). "
                    f"Institutional buying zone. SL below OB. TP at liquidity {fmt(tp_price)}."
                ),
            })
        if near_ob["type"] == "Bearish" and near_ob["bottom"] * 0.99 <= price <= near_ob["top"] * 1.002:
            sl_price = near_ob["top"] + abs(near_ob["top"] - near_ob["bottom"]) * 0.5
            tp_price = find_tp_short(sl_price)
            signals.append({
                "strategy": "SMC", "direction": "SHORT",
                "setup": "Bearish Order Block Rejection",
                "order_type": "Sell Limit", "entry": round(near_ob["top"], 1),
                "sl": round(sl_price, 1), "tp": round(tp_price, 1),
                "confidence": 0.70, "timeframe": timeframe,
                "price_now": price,
                "reasoning": (
                    f"Price at bearish Order Block ({fmt(near_ob['bottom'])}-{fmt(near_ob['top'])}). "
                    f"Institutional selling zone. SL above OB. TP at liquidity {fmt(tp_price)}."
                ),
            })

    # 6. FVG Fill — price returning to imbalance
    if near_fvg:
        if near_fvg["type"] == "Bullish" and near_fvg["bottom"] * 0.997 <= price <= near_fvg["top"] * 1.01:
            sl_price = near_fvg["bottom"] - abs(near_fvg["top"] - near_fvg["bottom"])
            tp_price = find_tp_long(sl_price)
            signals.append({
                "strategy": "SMC", "direction": "LONG",
                "setup": "Bullish FVG Fill",
                "order_type": "Buy Limit", "entry": round(near_fvg["bottom"], 1),
                "sl": round(sl_price, 1), "tp": round(tp_price, 1),
                "confidence": 0.68, "timeframe": timeframe,
                "price_now": price,
                "reasoning": (
                    f"Price filling bullish Fair Value Gap ({fmt(near_fvg['bottom'])}-{fmt(near_fvg['top'])}). "
                    f"Imbalance correction — expected reversal from gap. SL below gap. TP at liquidity {fmt(tp_price)}."
                ),
            })
        if near_fvg["type"] == "Bearish" and near_fvg["bottom"] * 0.99 <= price <= near_fvg["top"] * 1.003:
            sl_price = near_fvg["top"] + abs(near_fvg["top"] - near_fvg["bottom"])
            tp_price = find_tp_short(sl_price)
            signals.append({
                "strategy": "SMC", "direction": "SHORT",
                "setup": "Bearish FVG Fill",
                "order_type": "Sell Limit", "entry": round(near_fvg["top"], 1),
                "sl": round(sl_price, 1), "tp": round(tp_price, 1),
                "confidence": 0.68, "timeframe": timeframe,
                "price_now": price,
                "reasoning": (
                    f"Price filling bearish Fair Value Gap ({fmt(near_fvg['bottom'])}-{fmt(near_fvg['top'])}). "
                    f"Imbalance correction — expected continuation from gap. SL above gap. TP at liquidity {fmt(tp_price)}."
                ),
            })

    # 7. BOS Bullish — ride the trend
    if latest_bos and latest_bos["type"] == "Bullish" and latest_bos["idx"] >= last_idx - 3:
        recent_swing_low = swing_lows[0] if swing_lows else price * 0.995
        sl_price = recent_swing_low - abs(price - recent_swing_low) * 0.1
        tp_price = find_tp_long(sl_price)
        signals.append({
            "strategy": "SMC", "direction": "LONG",
            "setup": "BOS Bullish — Trend Continuation",
            "order_type": "Buy Limit", "entry": round(price, 1),
            "sl": round(sl_price, 1), "tp": round(tp_price, 1),
            "confidence": 0.72, "timeframe": timeframe,
            "price_now": price,
            "reasoning": (
                f"Break of Structure Bullish — market in uptrend. "
                f"SL below swing low {fmt(sl_price)}. TP at next liquidity {fmt(tp_price)}. "
                f"Ride the trend with the institutions."
            ),
        })

    # 8. BOS Bearish
    if latest_bos and latest_bos["type"] == "Bearish" and latest_bos["idx"] >= last_idx - 3:
        recent_swing_high = swing_highs[0] if swing_highs else price * 1.005
        sl_price = recent_swing_high + abs(recent_swing_high - price) * 0.1
        tp_price = find_tp_short(sl_price)
        signals.append({
            "strategy": "SMC", "direction": "SHORT",
            "setup": "BOS Bearish — Trend Continuation",
            "order_type": "Sell Limit", "entry": round(price, 1),
            "sl": round(sl_price, 1), "tp": round(tp_price, 1),
            "confidence": 0.72, "timeframe": timeframe,
            "price_now": price,
            "reasoning": (
                f"Break of Structure Bearish — market in downtrend. "
                f"SL above swing high {fmt(sl_price)}. TP at next liquidity {fmt(tp_price)}. "
                f"Ride with smart money."
            ),
        })

    return signals


def fmt(n):
    return f"{n:,.1f}" if n and not (isinstance(n, float) and (n != n)) else "—"
