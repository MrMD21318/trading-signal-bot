from langchain_core.tools import tool
from typing import Annotated, Optional
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_screener_data(
    symbol: Annotated[str, "Ticker symbol of the company, e.g. AAPL, TSM"],
    screener_type: Annotated[str, "Screener type: 'stock', 'crypto', or 'forex'"],
    indicator: Annotated[Optional[str], "Specific technical indicator to retrieve, e.g. RSI, MACD"] = "",
    market: Annotated[Optional[str], "Market filter (for stocks): 'america', 'uk', 'india', etc."] = "america",
) -> str:
    """
    Retrieve screening data and technical indicators from TradingView's screener.
    Returns market data for the given symbol including price, volume, and optionally
    technical indicators (RSI, MACD, moving averages, Bollinger Bands, etc.).

    Args:
        symbol (str): Ticker symbol, e.g. AAPL, TSM
        screener_type (str): Choose 'stock', 'crypto', or 'forex'
        indicator (str, optional): Specific indicator to retrieve, e.g. 'RSI', 'MACD', 'RELATIVE_STRENGTH_INDEX_14'
        market (str, optional): Market filter, default 'america'
    Returns:
        str: CSV-formatted screener data with price, volume, and optional indicator values.
    """
    return route_to_vendor("get_screener_data", symbol= symbol, screener_type=screener_type, indicator=indicator, market=market)
