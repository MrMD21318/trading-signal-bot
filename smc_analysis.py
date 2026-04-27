"""Smart Money Concepts (ICT) analysis — proper OB, FVG, Liquidity sweep trading.

TP based on next liquidity pool, not arbitrary R:R.
"""

import os
import pandas as pd

os.environ.setdefault("SMC_CREDIT", "0")
from smartmoneyconcepts import smc


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

    # Swing highs/lows
    try:
        swings = smc.swing_highs_lows(df, swing_length=cfg["swing_length"])
    except:
        return []

    # BOS/CHoCH
    try:
        bc = smc.bos_choch(df, swings, close_break=True)
    except:
        return []

    # Order Blocks
    try:
        ob = smc.ob(df, swings, close_mitigation=False)
    except:
        ob = None

    # FVG
    try:
        fvg = smc.fvg(df, join_consecutive=True)
    except:
        fvg = None

    # Liquidity
    try:
        liq = smc.liquidity(df, swings, range_percent=cfg["liq_range"])
    except:
        liq = None

    # ── Find key levels ──
    swing_highs = []
    swing_lows = []
    for i in range(min(last_idx, cfg["bos_lookback"] * 4)):
        idx = last_idx - i
        if idx < 0:
            break
        val = swings["HighLow"].iloc[idx]
        level = swings["Level"].iloc[idx]
        if not pd.isna(val) and not pd.isna(level) and val != 0:
            if int(val) == 1:
                swing_highs.append(float(level))
            elif int(val) == -1:
                swing_lows.append(float(level))

    # Liquidity pools
    bullish_liq_levels = []
    bearish_liq_levels = []
    if liq is not None:
        for i in range(min(last_idx, cfg["liq_lookback"])):
            idx = last_idx - i
            if idx < 0:
                break
            l_val = liq["Liquidity"].iloc[idx]
            l_level = liq["Level"].iloc[idx]
            swept = liq["Swept"].iloc[idx]
            if not pd.isna(l_val) and not pd.isna(l_level) and l_val != 0:
                is_swept = not pd.isna(swept) and swept > 0
                if int(l_val) == 1:
                    bullish_liq_levels.append({"level": float(l_level), "swept": is_swept, "idx": idx})
                elif int(l_val) == -1:
                    bearish_liq_levels.append({"level": float(l_level), "swept": is_swept, "idx": idx})

    # Recent BOS/CHoCH
    latest_bos = None
    latest_choch = None
    for i in range(min(last_idx, cfg["bos_lookback"])):
        idx = last_idx - i
        if idx < 0:
            break
        bos_val = bc["BOS"].iloc[idx]
        choch_val = bc["CHOCH"].iloc[idx]
        level_val = bc["Level"].iloc[idx]
        if not pd.isna(bos_val) and bos_val != 0 and latest_bos is None:
            latest_bos = {"type": "Bullish" if int(bos_val) == 1 else "Bearish", "level": float(level_val) if not pd.isna(level_val) else 0, "idx": idx}
        if not pd.isna(choch_val) and choch_val != 0 and latest_choch is None:
            latest_choch = {"type": "Bullish" if int(choch_val) == 1 else "Bearish", "level": float(level_val) if not pd.isna(level_val) else 0, "idx": idx}

    # Recent Order Block
    near_ob = None
    if ob is not None:
        for i in range(min(last_idx, cfg["ob_lookback"])):
            idx = last_idx - i
            if idx < 0:
                break
            ob_val = ob["OB"].iloc[idx]
            ob_top = ob["Top"].iloc[idx]
            ob_bot = ob["Bottom"].iloc[idx]
            if not pd.isna(ob_val) and ob_val != 0 and not pd.isna(ob_top) and not pd.isna(ob_bot):
                near_ob = {"type": "Bullish" if int(ob_val) == 1 else "Bearish", "top": float(ob_top), "bottom": float(ob_bot), "idx": idx}
                break

    # Recent FVG
    near_fvg = None
    if fvg is not None:
        for i in range(min(last_idx, cfg["fvg_lookback"])):
            idx = last_idx - i
            if idx < 0:
                break
            f_val = fvg["FVG"].iloc[idx]
            f_top = fvg["Top"].iloc[idx]
            f_bot = fvg["Bottom"].iloc[idx]
            mitigated = fvg["MitigatedIndex"].iloc[idx]
            if not pd.isna(f_val) and f_val != 0 and not pd.isna(f_top) and not pd.isna(f_bot):
                if pd.isna(mitigated) or mitigated == 0:
                    near_fvg = {"type": "Bullish" if int(f_val) == 1 else "Bearish", "top": float(f_top), "bottom": float(f_bot), "idx": idx}
                    break

    # Sweep detection windows
    swept_bearish = [l for l in bearish_liq_levels if l["swept"] and l["idx"] >= last_idx - cfg["bos_lookback"]]
    swept_bullish = [l for l in bullish_liq_levels if l["swept"] and l["idx"] >= last_idx - cfg["bos_lookback"]]
    if swept_bullish:
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
