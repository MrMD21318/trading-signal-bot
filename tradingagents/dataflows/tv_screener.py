import pandas as pd
import logging

logger = logging.getLogger(__name__)

try:
    import tvscreener as tvs
    SCREENER_AVAILABLE = True
except ImportError:
    SCREENER_AVAILABLE = False
    logger.warning("tvscreener not installed. Install with: pip install tvscreener")


def _screener_to_csv(df: pd.DataFrame, max_rows: int = 150) -> str:
    if df is None or df.empty:
        return "No results found for the given screener query."
    df = df.head(max_rows)
    for col in df.columns:
        if df[col].dtype == "float64":
            df[col] = df[col].round(4)
    return df.to_csv(index=False)


def _get_field_class(screener_type: str):
    if screener_type == "stock":
        return tvs.StockField
    elif screener_type == "crypto":
        return tvs.CryptoField
    elif screener_type == "forex":
        return tvs.ForexField
    return None


def _get_screener_class(screener_type: str):
    if screener_type == "stock":
        return tvs.StockScreener
    elif screener_type == "crypto":
        return tvs.CryptoScreener
    elif screener_type == "forex":
        return tvs.ForexScreener
    return None


def get_screener_stocks(
    symbol: str = "",
    screener_type: str = "stock",
    indicator: str = "",
    market: str = "america",
    limit: int = 50,
) -> str:
    """Screener vendor entry point. Matches the get_screener_data tool signature.

    The route_to_vendor call forwards all kwargs so the function must accept:
        symbol, screener_type, indicator, market
    """
    if not SCREENER_AVAILABLE:
        return "Error: tvscreener library is not installed. Install with: pip install tvscreener"

    try:
        ScreenerClass = _get_screener_class(screener_type)
        Field = _get_field_class(screener_type)

        if ScreenerClass is None or Field is None:
            return f"Unknown screener type: {screener_type}. Use 'stock', 'crypto', or 'forex'."

        scr = ScreenerClass()

        # Always select core fields
        selected = [Field.NAME, Field.PRICE, Field.CHANGE_PERCENT, Field.VOLUME]

        # Add specific indicator if provided
        if indicator:
            indicator_upper = indicator.upper().strip()
            if hasattr(Field, indicator_upper):
                selected.append(getattr(Field, indicator_upper))
            else:
                # Try fuzzy search for RSI, MACD, etc.
                search_results = Field.search(indicator_upper)
                if search_results:
                    best = search_results[0]
                    selected.append(best)

        scr.select(*selected)
        df = scr.get()
        return _screener_to_csv(df, limit)

    except Exception as e:
        return f"Error fetching screener data: {str(e)}"
