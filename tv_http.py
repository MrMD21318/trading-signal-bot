"""Symbol search — uses yfinance (reliable, stocks+ETFs+indices) + manual TV symbol entry."""

import logging

logger = logging.getLogger(__name__)


def search_tv(query, limit=15):
    """Search for trading symbols. Uses yfinance for stocks/ETFs.
    
    For CFD/Forex/Crypto TV symbols (e.g., CFI:US100, BINANCE:BTCUSDT),
    type them directly in the "Add Market" input field.
    """
    results = []

    # Primary: Yahoo Finance (reliable, no auth needed)
    try:
        import yfinance as yf
        sr = yf.Search(query)
        if hasattr(sr, 'quotes') and sr.quotes:
            for q in sr.quotes[:limit]:
                sym = q.get('symbol', '')
                name = q.get('shortname') or q.get('longname', '')
                etype = q.get('quoteType', '')
                exch = q.get('exchange', '')
                results.append({
                    "symbol": sym,
                    "description": name,
                    "type": etype,
                    "exchange": exch,
                    "full_symbol": f"{exch}:{sym}" if exch else sym,
                })
    except Exception as e:
        logger.debug("YFinance search error: %s", e)

    # Fallback: try tvscreener stock search
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
            logger.debug("TV Screener search error: %s", e)

    return results


def get_chart_data(symbol, timeframe="1D", bars=30):
    """Get OHLCV data from TradingView via public chart API."""
    try:
        # TradingView chart data API
        resolution_map = {
            "1": "1", "5": "5", "15": "15", "30": "30",
            "60": "60", "240": "240", "1D": "D", "1W": "W", "1M": "M",
        }
        res = resolution_map.get(timeframe, "D")

        url = "https://scanner.tradingview.com/america/scan"
        # This is the screener approach - for chart data we use a different endpoint
        # Fall back to tvscreener lib or bridge

        # Try bridge first, then fall back
        try:
            from tradingagents.dataflows.tv_realtime import get_live_chart
            raw = get_live_chart(symbol, timeframe=timeframe, range_bars=bars)
            result = []
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
        except:
            pass

        # Fallback: empty result
        logger.warning("Chart data unavailable for %s", symbol)
        return []

    except Exception as e:
        logger.warning("Chart fetch failed: %s", e)
        return []
