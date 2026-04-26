"""Smart Money Concepts (ICT) analysis for US100 monitor.

Core SMC entry logic:
1. Identify market structure (BOS = trend, CHoCH = reversal)
2. Detect liquidity sweeps (stop hunts)
3. Wait for return to Order Block or Fair Value Gap
4. Enter with tight SL at swing point
5. Target next liquidity level
"""

import os
import pandas as pd

os.environ.setdefault("SMC_CREDIT", "0")
from smartmoneyconcepts import smc


def candles_to_ohlc(candles):
    """Convert our candle format [[time, open, high, low, close, volume], ...]
    to SMC-expected DataFrame with lowercase columns."""
    if not candles:
        return None
    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


def analyze_smc(candles_15m, candles_5m=None, candles_1m=None):
    """Run full SMC analysis on 15M candles (primary) and 5M/1M for entry precision.

    Returns list of SMC signals.
    """
    df = candles_to_ohlc(candles_15m)
    if df is None or len(df) < 20:
        return []

    signals = []
    last_idx = len(df) - 1
    price = float(df["close"].iloc[-1])

    # ── Swing Highs/Lows ──
    try:
        swings = smc.swing_highs_lows(df, swing_length=10)
    except:
        return []

    # ── BOS / CHoCH ──
    try:
        bc = smc.bos_choch(df, swings, close_break=True)
    except:
        return []

    # ── Order Blocks ──
    try:
        ob = smc.ob(df, swings, close_mitigation=False)
    except:
        ob = None

    # ── Fair Value Gaps ──
    try:
        fvg = smc.fvg(df, join_consecutive=True)
    except:
        fvg = None

    # ── Liquidity ──
    try:
        liq = smc.liquidity(df, swings, range_percent=0.005)
    except:
        liq = None

    # ── Latest indicators ──
    latest_swing = None
    latest_swing_idx = 0
    for i in range(last_idx, max(last_idx - 30, 0), -1):
        if swings["HighLow"].iloc[i] != 0:
            latest_swing = {
                "type": "High" if swings["HighLow"].iloc[i] == 1 else "Low",
                "level": swings["Level"].iloc[i],
                "index": i,
            }
            latest_swing_idx = i
            break

    latest_bos = None
    latest_choch = None
    for i in range(last_idx, max(last_idx - 20, 0), -1):
        bos_val = bc["BOS"].iloc[i]
        choch_val = bc["CHOCH"].iloc[i]
        level_val = bc["Level"].iloc[i]
        if not pd.isna(bos_val) and bos_val != 0 and latest_bos is None:
            latest_bos = {
                "type": "Bullish" if float(bos_val) == 1 else "Bearish",
                "level": float(level_val) if not pd.isna(level_val) else 0,
                "index": i,
            }
        if not pd.isna(choch_val) and choch_val != 0 and latest_choch is None:
            latest_choch = {
                "type": "Bullish" if float(choch_val) == 1 else "Bearish",
                "level": float(level_val) if not pd.isna(level_val) else 0,
                "index": i,
            }

    # ── Recent Order Block (within 15 bars) ──
    near_ob = None
    if ob is not None:
        for i in range(last_idx - 15, last_idx + 1):
            if i >= 0 and ob["OB"].iloc[i] != 0:
                near_ob = {
                    "type": "Bullish" if ob["OB"].iloc[i] == 1 else "Bearish",
                    "top": float(ob["Top"].iloc[i]),
                    "bottom": float(ob["Bottom"].iloc[i]),
                    "index": i,
                    "strength": float(ob.get("Percentage", pd.Series([0])).iloc[i]) if "Percentage" in ob.columns else 0.5,
                }

    # ── Recent FVG (within 10 bars, not mitigated) ──
    near_fvg = None
    if fvg is not None:
        for i in range(last_idx - 10, last_idx + 1):
            if i >= 0 and fvg["FVG"].iloc[i] != 0:
                mitigated = fvg["MitigatedIndex"].iloc[i]
                if pd.isna(mitigated) or mitigated == 0:
                    near_fvg = {
                        "type": "Bullish" if fvg["FVG"].iloc[i] == 1 else "Bearish",
                        "top": float(fvg["Top"].iloc[i]),
                        "bottom": float(fvg["Bottom"].iloc[i]),
                        "index": i,
                    }

    # ── Recent Liquidity Sweep ──
    swept_liq = None
    if liq is not None:
        for i in range(last_idx - 10, last_idx + 1):
            if i >= 0 and liq["Liquidity"].iloc[i] != 0:
                swept_idx = liq["Swept"].iloc[i]
                if not pd.isna(swept_idx) and swept_idx > 0:
                    swept_liq = {
                        "type": "Bullish" if liq["Liquidity"].iloc[i] == 1 else "Bearish",
                        "level": float(liq["Level"].iloc[i]),
                        "index": i,
                    }

    # ── SIGNAL GENERATION ──

    # SIGNAL 1: CHoCH Bullish — reversal signal
    if latest_choch and latest_choch["type"] == "Bullish" and latest_choch["index"] >= last_idx - 5:
        choch_lvl = latest_choch.get("level", 0) or 0
        entry = price
        sl = float(df["low"].iloc[latest_choch["index"]:last_idx+1].min())
        tp = entry + (entry - sl) * 2.5
        signals.append({
            "strategy": "SMC",
            "setup": "CHoCH Bullish — Reversal",
            "direction": "LONG",
            "order_type": "Buy Limit",
            "entry": round(entry, 1),
            "sl": round(sl - abs(entry-sl)*0.05, 1),
            "tp": round(tp, 1),
            "timeframe": "15M",
            "confidence": 0.75,
            "reasoning": (
                f"Change of Character detected: price broke above previous swing high"
                + (f" at {fmt(choch_lvl)}" if choch_lvl else "")
                + " — sellers lost control. "
                "Market structure shifting from bearish to bullish. "
                f"SL below recent swing low. Target 2.5R."
            ),
        })

    # SIGNAL 2: CHoCH Bearish — reversal signal
    if latest_choch and latest_choch["type"] == "Bearish" and latest_choch["index"] >= last_idx - 5:
        choch_lvl = latest_choch.get("level", 0) or 0
        entry = price
        sl = float(df["high"].iloc[latest_choch["index"]:last_idx+1].max())
        tp = entry - (sl - entry) * 2.5
        signals.append({
            "strategy": "SMC",
            "setup": "CHoCH Bearish — Reversal",
            "direction": "SHORT",
            "order_type": "Sell Limit",
            "entry": round(entry, 1),
            "sl": round(sl + abs(sl-entry)*0.05, 1),
            "tp": round(tp, 1),
            "timeframe": "15M",
            "confidence": 0.75,
            "reasoning": (
                f"Change of Character detected: price broke below previous swing low"
                + (f" at {fmt(choch_lvl)}" if choch_lvl else "")
                + " — buyers lost control. "
                "Market structure shifting from bullish to bearish. "
                f"SL above recent swing high. Target 2.5R."
            ),
        })

    # SIGNAL 3: Liquidity Sweep + Bullish reversal
    if swept_liq and swept_liq["type"] == "Bullish":
        # Price swept below equal lows (stop hunt), now reversing up
        entry = price
        recent_low = float(df["low"].iloc[max(0, swept_liq["index"]-3):last_idx+1].min())
        sl = recent_low - abs(price - recent_low) * 0.1
        tp = swept_liq["level"] + abs(swept_liq["level"] - sl) * 2
        signals.append({
            "strategy": "SMC",
            "setup": "Liquidity Sweep Long",
            "direction": "LONG",
            "order_type": "Buy Limit",
            "entry": round(entry, 1),
            "sl": round(sl, 1),
            "tp": round(tp, 1),
            "timeframe": "15M",
            "confidence": 0.78,
            "reasoning": (
                f"Liquidity sweep detected below equal lows at {fmt(swept_liq['level'])}. "
                "Smart money grabbed stop losses, now reversing. "
                "Classic ICT setup — buy after the stop hunt. "
                f"SL below sweep low. TP at original level."
            ),
        })

    # SIGNAL 4: Liquidity Sweep + Bearish reversal
    if swept_liq and swept_liq["type"] == "Bearish":
        entry = price
        recent_high = float(df["high"].iloc[max(0, swept_liq["index"]-3):last_idx+1].max())
        sl = recent_high + abs(recent_high - price) * 0.1
        tp = swept_liq["level"] - abs(sl - swept_liq["level"]) * 2
        signals.append({
            "strategy": "SMC",
            "setup": "Liquidity Sweep Short",
            "direction": "SHORT",
            "order_type": "Sell Limit",
            "entry": round(entry, 1),
            "sl": round(sl, 1),
            "tp": round(tp, 1),
            "timeframe": "15M",
            "confidence": 0.78,
            "reasoning": (
                f"Liquidity sweep detected above equal highs at {fmt(swept_liq['level'])}. "
                "Smart money grabbed breakout trader stops, now reversing down. "
                f"SL above sweep high. TP at original level."
            ),
        })

    # SIGNAL 5: Price at bullish Order Block → bounce entry
    if near_ob and near_ob["type"] == "Bullish":
        ob_bottom = near_ob["bottom"]
        ob_top = near_ob["top"]
        if ob_bottom <= price <= ob_top * 1.01:
            sl = ob_bottom - abs(ob_top - ob_bottom) * 0.5
            tp = price + abs(price - sl) * 2
            signals.append({
                "strategy": "SMC",
                "setup": "Bullish Order Block Bounce",
                "direction": "LONG",
                "order_type": "Buy Limit",
                "entry": round(ob_bottom, 1),
                "sl": round(sl, 1),
                "tp": round(tp, 1),
                "timeframe": "15M",
                "confidence": 0.70,
                "reasoning": (
                    f"Price at bullish Order Block ({fmt(ob_bottom)}—{fmt(ob_top)}). "
                    f"Strength: {near_ob['strength']*100:.0f}%. "
                    "Institutional buying zone — expected bounce. "
                    "Smart money accumulating here. SL below OB."
                ),
            })

    # SIGNAL 6: Price at bearish Order Block → rejection entry
    if near_ob and near_ob["type"] == "Bearish":
        ob_bottom = near_ob["bottom"]
        ob_top = near_ob["top"]
        if ob_bottom * 0.99 <= price <= ob_top:
            sl = ob_top + abs(ob_top - ob_bottom) * 0.5
            tp = price - abs(sl - price) * 2
            signals.append({
                "strategy": "SMC",
                "setup": "Bearish Order Block Rejection",
                "direction": "SHORT",
                "order_type": "Sell Limit",
                "entry": round(ob_top, 1),
                "sl": round(sl, 1),
                "tp": round(tp, 1),
                "timeframe": "15M",
                "confidence": 0.70,
                "reasoning": (
                    f"Price at bearish Order Block ({fmt(ob_bottom)}—{fmt(ob_top)}). "
                    f"Strength: {near_ob['strength']*100:.0f}%. "
                    "Institutional selling zone — expected rejection. "
                    "Smart money distributing here. SL above OB."
                ),
            })

    # SIGNAL 7: Price returning to bullish FVG → fill the gap
    if near_fvg and near_fvg["type"] == "Bullish":
        fvg_bottom = near_fvg["bottom"]
        fvg_top = near_fvg["top"]
        if fvg_bottom <= price <= fvg_top * 1.005:
            sl = fvg_bottom - abs(fvg_top - fvg_bottom)
            tp = fvg_top + abs(fvg_top - fvg_bottom) * 3
            signals.append({
                "strategy": "SMC",
                "setup": "Bullish FVG Fill",
                "direction": "LONG",
                "order_type": "Buy Limit",
                "entry": round(fvg_bottom, 1),
                "sl": round(sl, 1),
                "tp": round(tp, 1),
                "timeframe": "15M",
                "confidence": 0.68,
                "reasoning": (
                    f"Price returning to fill Bullish Fair Value Gap ({fmt(fvg_bottom)}—{fmt(fvg_top)}). "
                    "Imbalance being corrected — price likely to reverse from gap. "
                    "Entry at gap bottom. SL below gap. TP extension of move."
                ),
            })

    # SIGNAL 8: Price returning to bearish FVG → rejection
    if near_fvg and near_fvg["type"] == "Bearish":
        fvg_bottom = near_fvg["bottom"]
        fvg_top = near_fvg["top"]
        if fvg_bottom * 0.995 <= price <= fvg_top:
            sl = fvg_top + abs(fvg_top - fvg_bottom)
            tp = fvg_bottom - abs(fvg_top - fvg_bottom) * 3
            signals.append({
                "strategy": "SMC",
                "setup": "Bearish FVG Fill",
                "direction": "SHORT",
                "order_type": "Sell Limit",
                "entry": round(fvg_top, 1),
                "sl": round(sl, 1),
                "tp": round(tp, 1),
                "timeframe": "15M",
                "confidence": 0.68,
                "reasoning": (
                    f"Price returning to fill Bearish Fair Value Gap ({fmt(fvg_bottom)}—{fmt(fvg_top)}). "
                    "Imbalance being corrected — price likely to continue down from gap. "
                    "Entry at gap top. SL above gap. TP extension of move."
                ),
            })

    # SIGNAL 9: BOS Bullish continuation
    if latest_bos and latest_bos["type"] == "Bullish" and latest_bos["index"] >= last_idx - 3:
        bos_lvl = latest_bos.get("level", 0) or 0
        entry = price
        recent_swing_low = None
        for i in range(last_idx, max(last_idx-20, 0), -1):
            if swings["HighLow"].iloc[i] == -1:
                recent_swing_low = swings["Level"].iloc[i]
                if not pd.isna(recent_swing_low):
                    recent_swing_low = float(recent_swing_low)
                    break
        if recent_swing_low:
            signals.append({
                "strategy": "SMC",
                "setup": "BOS Bullish — Trend Continuation",
                "direction": "LONG",
                "order_type": "Buy Limit",
                "entry": round(entry, 1),
                "sl": round(recent_swing_low - abs(entry-recent_swing_low)*0.1, 1),
                "tp": round(entry + abs(entry-recent_swing_low)*2, 1),
                "timeframe": "15M",
                "confidence": 0.72,
                "reasoning": (
                    f"Break of Structure (Bullish) — price broke above "
                    + (f"{fmt(bos_lvl)}. " if bos_lvl else "resistance. ")
                    + "Market in uptrend. Buy pullbacks. "
                    f"SL below recent swing low at {fmt(recent_swing_low)}. "
                    "Ride the trend higher."
                ),
            })

    # SIGNAL 10: BOS Bearish continuation
    if latest_bos and latest_bos["type"] == "Bearish" and latest_bos["index"] >= last_idx - 3:
        bos_lvl = latest_bos.get("level", 0) or 0
        entry = price
        recent_swing_high = None
        for i in range(last_idx, max(last_idx-20, 0), -1):
            if swings["HighLow"].iloc[i] == 1:
                recent_swing_high = swings["Level"].iloc[i]
                if not pd.isna(recent_swing_high):
                    recent_swing_high = float(recent_swing_high)
                    break
        if recent_swing_high:
            signals.append({
                "strategy": "SMC",
                "setup": "BOS Bearish — Trend Continuation",
                "direction": "SHORT",
                "order_type": "Sell Limit",
                "entry": round(entry, 1),
                "sl": round(recent_swing_high + abs(recent_swing_high-entry)*0.1, 1),
                "tp": round(entry - abs(recent_swing_high-entry)*2, 1),
                "timeframe": "15M",
                "confidence": 0.72,
                "reasoning": (
                    f"Break of Structure (Bearish) — price broke below "
                    + (f"{fmt(bos_lvl)}. " if bos_lvl else "support. ")
                    + "Market in downtrend. Sell rallies. "
                    f"SL above recent swing high at {fmt(recent_swing_high)}. "
                    "Ride the trend lower."
                ),
            })

    return signals


def fmt(n):
    return f"{n:,.1f}"
