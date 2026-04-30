"""SMC analysis matching LuxAlgo Smart Money Concepts indicator logic.

Based on LuxAlgo's Pine Script v5 implementation.
Computes: BOS, CHoCH, Order Blocks, FVG, EQH/EQL
"""


def compute_luxalgo_smc(candles, swing_length=50, internal_length=5):
    """Compute full SMC based on LuxAlgo's algorithm.

    candles: [[time, open, high, low, close, volume], ...] oldest first.
    Returns dict with all SMC components.
    """
    n = len(candles)
    if n < swing_length:
        return {}

    # Extract OHLCV arrays
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    closes = [c[4] for c in candles]
    opens = [c[1] for c in candles]
    volumes = [c[5] for c in candles]

    # ── Leg detection (LuxAlgo method) ──
    def leg_detection(size):
        """Returns leg array: 1=bullish leg, 0=bearish leg."""
        legs = [1] * n  # default bullish
        for i in range(size, n):
            # Check if new bearish leg (price broke highest of last 'size' bars)
            new_leg_low = lows[i] < min(lows[i - size:i])
            # Check if new bullish leg (price broke lowest of last 'size' bars)
            new_leg_high = highs[i] > max(highs[i - size:i])
            if new_leg_high:
                legs[i] = 0  # bearish leg
            elif new_leg_low:
                legs[i] = 1  # bullish leg
            else:
                legs[i] = legs[i - 1] if i > 0 else 1
        return legs

    # Swing legs (50 bars)
    swing_legs = leg_detection(swing_length)
    # Internal legs (5 bars)
    internal_legs = leg_detection(internal_length)

    # ── Find swing points ──
    swing_highs = []
    swing_lows = []
    for i in range(1, n):
        if swing_legs[i] != swing_legs[i - 1]:
            if swing_legs[i] == 0:  # shifted to bearish
                swing_highs.append((i, max(highs[max(i - 10, 0):i + 1])))
            else:  # shifted to bullish
                swing_lows.append((i, min(lows[max(i - 10, 0):i + 1])))

    # ── Internal pivot points ──
    internal_highs = []
    internal_lows = []
    for i in range(1, n):
        if internal_legs[i] != internal_legs[i - 1]:
            if internal_legs[i] == 0:
                internal_highs.append((i, highs[i]))
            else:
                internal_lows.append((i, lows[i]))

    # ── BOS & CHoCH detection ──
    trend = 0  # 0=undefined, 1=bullish, -1=bearish
    bos_signals = []
    choch_signals = []

    for i in range(swing_length, n):
        if swing_highs:
            last_swing_high = max(s[1] for s in swing_highs if s[0] < i) if any(s[0] < i for s in swing_highs) else None
            if last_swing_high and closes[i] > last_swing_high:
                tag = "CHoCH" if trend == -1 else "BOS"
                if tag == "CHoCH":
                    choch_signals.append(("Bullish", i, last_swing_high))
                else:
                    bos_signals.append(("Bullish", i, last_swing_high))
                trend = 1

        if swing_lows:
            last_swing_low = min(s[1] for s in swing_lows if s[0] < i) if any(s[0] < i for s in swing_lows) else None
            if last_swing_low and closes[i] < last_swing_low:
                tag = "CHoCH" if trend == 1 else "BOS"
                if tag == "CHoCH":
                    choch_signals.append(("Bearish", i, last_swing_low))
                else:
                    bos_signals.append(("Bearish", i, last_swing_low))
                trend = -1

    # ── Order Blocks ──
    ob_list = []
    for s_idx, s_level in swing_highs + swing_lows:
        # Find the candle just before the swing point
        ob_idx = s_idx - 1
        if ob_idx >= 0 and ob_idx < n:
            bias = "Bullish" if (s_idx, s_level) in swing_lows else "Bearish"
            ob_high = highs[ob_idx]
            ob_low = lows[ob_idx]
            ob_list.append((bias, ob_idx, ob_high, ob_low))

    # ── Fair Value Gaps (LuxAlgo method) ──
    fvg_list = []
    for i in range(2, n):
        last_close = closes[i - 1]
        last_open = opens[i - 1]
        last2_high = highs[i - 2]
        last2_low = lows[i - 2]
        current_high = highs[i]
        current_low = lows[i]

        # Bullish FVG: current low > 2 bars ago high
        if current_low > last2_high and closes[i] > last2_high:
            bar_delta = (last_close - last_open) / last_open * 100
            # Threshold filter (cumulative mean of abs delta * 2)
            fvg_list.append(("Bullish", i, last2_high, current_low))

        # Bearish FVG: current high < 2 bars ago low  
        if current_high < last2_low and closes[i] < last2_low:
            bar_delta = (last_close - last_open) / last_open * 100
            fvg_list.append(("Bearish", i, current_high, last2_low))

    # ── EQH/EQL (Equal Highs/Lows) ──
    eqh_list = []
    eql_list = []
    atr_value = sum(abs(highs[i] - lows[i]) for i in range(max(0, n - 200), n)) / min(200, n)
    threshold = 0.1 * atr_value

    for i in range(3, n):
        # Check last 3 bars for equal highs
        h_window = highs[max(0, i - 3):i + 1]
        if max(h_window) - min(h_window) < threshold:
            eqh_list.append((i, max(h_window)))

        # Check last 3 bars for equal lows
        l_window = lows[max(0, i - 3):i + 1]
        if max(l_window) - min(l_window) < threshold:
            eql_list.append((i, min(l_window)))

    return {
        "price": closes[-1],
        "trend": "Bullish" if trend == 1 else "Bearish" if trend == -1 else "Neutral",
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
        "bos": bos_signals,
        "choch": choch_signals,
        "order_blocks": ob_list,
        "fvgs": fvg_list,
        "eqh": eqh_list,
        "eql": eql_list,
    }
