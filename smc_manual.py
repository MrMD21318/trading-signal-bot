"""Manual SMC computation — pure Python, no library dependency.

Computes ICT concepts directly from candle data.
"""


def find_swings(candles, lookback=10):
    """Find swing highs and lows.
    candles: [[time, open, high, low, close, volume], ...] oldest first.
    Returns highs, lows as list of (index, price).
    """
    highs = []
    lows = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        h = candles[i][2]
        l = candles[i][3]
        is_high = all(candles[j][2] <= h for j in range(i - lookback, i + lookback + 1))
        is_low = all(candles[j][3] >= l for j in range(i - lookback, i + lookback + 1))
        if is_high:
            highs.append((i, h))
        if is_low:
            lows.append((i, l))
    return highs, lows


def find_bos_choch(candles, highs, lows):
    """Find Break of Structure and Change of Character."""
    bos = []
    choch = []

    for i in range(len(candles)):
        close = candles[i][4]
        # Check break of recent swing high
        if highs:
            for hi, hv in reversed(highs):
                if hi < i:
                    if close > hv:
                        bos.append(("Bullish", i, hv))
                    break
        # Check break of recent swing low
        if lows:
            for li, lv in reversed(lows):
                if li < i:
                    if close < lv:
                        bos.append(("Bearish", i, lv))
                    break

    # CHOCH = price breaks previous swing HIGH after series of lower highs (or vice versa)
    if len(highs) >= 2:
        prev_swing_high = highs[-2][1]
        if candles[-1][4] > prev_swing_high:
            choch.append(("Bullish", len(candles)-1, prev_swing_high))
    if len(lows) >= 2:
        prev_swing_low = lows[-2][1]
        if candles[-1][4] < prev_swing_low:
            choch.append(("Bearish", len(candles)-1, prev_swing_low))

    return bos, choch


def find_order_blocks(candles, lookback=15):
    """Find bullish and bearish order blocks.
    Bullish OB = last red candle before a strong green move.
    Bearish OB = last green candle before a strong red move.
    """
    obs = []
    n = len(candles)
    for i in range(1, n - 1):
        prev = candles[i - 1]
        curr = candles[i]
        # Bullish OB: red candle followed by strong green
        if prev[4] < prev[1] and curr[4] > curr[1]:
            move = abs(curr[4] - curr[1])
            if move > 0:
                obs.append(("Bullish", i - 1, prev[1], prev[4]))
        # Bearish OB: green candle followed by strong red
        if prev[4] > prev[1] and curr[4] < curr[1]:
            move = abs(curr[4] - curr[1])
            if move > 0:
                obs.append(("Bearish", i - 1, prev[4], prev[1]))
    return obs


def find_fvg(candles):
    """Find Fair Value Gaps.
    Bullish FVG: candle[0].high < candle[2].low  (gap up)
    Bearish FVG: candle[0].low > candle[2].high  (gap down)
    """
    fvgs = []
    n = len(candles)
    for i in range(2, n):
        c0, c1, c2 = candles[i - 2], candles[i - 1], candles[i]
        # Bullish FVG
        if c0[2] < c2[3]:
            fvgs.append(("Bullish", i, c0[2], c2[3]))
        # Bearish FVG
        if c0[3] > c2[2]:
            fvgs.append(("Bearish", i, c2[2], c0[3]))
    return fvgs


def find_liquidity(candles, range_pct=0.002):
    """Find liquidity pools (equal highs/lows).
    Groups highs/lows within range_pct% of each other.
    """
    n = len(candles)
    highs = [(i, candles[i][2]) for i in range(n)]
    lows = [(i, candles[i][3]) for i in range(n)]

    pools = []
    # Group highs
    for i in range(n):
        h = candles[i][2]
        group = [j for j in range(max(0, i - 5), min(n, i + 5))
                if abs(candles[j][2] - h) / h < range_pct and j != i]
        if len(group) >= 1:
            pools.append(("Bearish", i, h, len(group) + 1))
            break

    # Group lows
    for i in range(n):
        l = candles[i][3]
        group = [j for j in range(max(0, i - 5), min(n, i + 5))
                if abs(candles[j][3] - l) / l < range_pct and j != i]
        if len(group) >= 1:
            pools.append(("Bullish", i, l, len(group) + 1))
            break

    return pools
