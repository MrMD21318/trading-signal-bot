"""Symbol search + chart data using yfinance (primary) and TV bridge (fallback)."""

import logging

logger = logging.getLogger(__name__)


def search_tv(query, limit=15):
    """Search symbols. Uses yfinance + tvscreener fallback."""
    results = []

    try:
        import yfinance as yf
        sr = yf.Search(query)
        if hasattr(sr, "quotes") and sr.quotes:
            for q in sr.quotes[:limit]:
                results.append({
                    "symbol": q.get("symbol", ""),
                    "description": q.get("shortname") or q.get("longname", ""),
                    "type": q.get("quoteType", ""),
                    "exchange": q.get("exchange", ""),
                    "full_symbol": f"{q.get('exchange', '')}:{q.get('symbol', '')}" if q.get("exchange") else q.get("symbol", ""),
                })
    except Exception as e:
        logger.debug("YFinance search error: %s", e)

    if not results:
        try:
            import tvscreener as tvs
            ss = tvs.StockScreener()
            ss.where(tvs.StockField.NAME.like(f"*{query}*"))
            df = ss.get()
            if df is not None and not df.empty:
                for _, row in df.head(limit).iterrows():
                    results.append({
                        "symbol": str(row.get("Symbol", "")),
                        "description": str(row.get("Name", "")),
                        "type": "stock",
                        "exchange": "",
                        "full_symbol": str(row.get("Symbol", "")),
                    })
        except Exception as e:
            logger.debug("TV screener search error: %s", e)

    return results


def get_chart_data(symbol, timeframe="1D", bars=30):
    """Get OHLCV candles. Tries TV bridge first, falls back to yfinance."""
    result = []

    try:
        from tradingagents.dataflows.tv_realtime import get_live_chart
        raw = get_live_chart(symbol, timeframe=timeframe, range_bars=bars)
        for line in raw.strip().split("\n"):
            if line.startswith("#") or line.startswith("time,"):
                continue
            parts = line.split(",")
            if len(parts) >= 5:
                try:
                    result.append({
                        "time": int(float(parts[0])),
                        "open": float(parts[1]),
                        "high": float(parts[2]),
                        "low": float(parts[3]),
                        "close": float(parts[4]),
                        "volume": float(parts[5]) if len(parts) > 5 else 0,
                    })
                except ValueError:
                    pass
        if result:
            return result
    except Exception as e:
        logger.debug("TV bridge chart failed: %s", e)

    try:
        import yfinance as yf
        period_map = {"1D": "1mo", "1W": "6mo", "1M": "2y"}
        interval_map = {
            "1": "1m", "5": "5m", "15": "15m", "30": "30m",
            "60": "1h", "240": "4h", "1D": "1d", "1W": "1wk", "1M": "1mo",
        }
        ticker = yf.Ticker(symbol)
        hist = ticker.history(
            period=period_map.get(timeframe, "1mo"),
            interval=interval_map.get(timeframe, "1d"),
        )
        if hist is not None and not hist.empty:
            for idx, row in hist.tail(bars).iterrows():
                result.append({
                    "time": int(idx.timestamp()),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                })
            return result
    except Exception as e:
        logger.debug("YFinance chart failed: %s", e)

    return result
