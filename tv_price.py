"""Live price data from TradingView screener — no Node.js/WebSocket needed.

Uses tvscreener for real-time CFD/stock/crypto prices.
"""

import logging

logger = logging.getLogger(__name__)

try:
    import tvscreener as tvs
    SCREENER_AVAILABLE = True
except ImportError:
    SCREENER_AVAILABLE = False


def get_live_price(symbol):
    """Get live price from TradingView screener for any symbol type."""
    if not SCREENER_AVAILABLE:
        return None

    try:
        # Try stock first
        ss = tvs.StockScreener()
        ss.select(tvs.StockField.NAME, tvs.StockField.CLOSE, tvs.StockField.CHANGE)
        df = ss.get()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                tv_sym = str(row.get("Symbol", ""))
                if symbol in tv_sym or tv_sym in symbol:
                    return float(row["Close"])
    except:
        pass

    return None


def get_all_prices(symbols):
    """Get live prices for multiple symbols via screener."""
    prices = {}
    if not SCREENER_AVAILABLE:
        return prices

    try:
        ss = tvs.StockScreener()
        ss.select(tvs.StockField.NAME, tvs.StockField.CLOSE, tvs.StockField.CHANGE_PERCENT)
        df = ss.get()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                tv_sym = str(row.get("Symbol", ""))
                for our_sym in symbols:
                    if our_sym.replace("CFI:", "") in tv_sym or our_sym in tv_sym or tv_sym in our_sym:
                        prices[our_sym] = float(row["Close"])
    except Exception as e:
        logger.debug("Screener price fetch: %s", e)

    return prices
