from langchain_core.tools import tool
from typing import Annotated, Optional
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_live_candles(
    symbol: Annotated[str, "TradingView-formatted symbol, e.g. 'NASDAQ:AAPL', 'BINANCE:BTCUSDT', 'NYSE:TSM'"],
    timeframe: Annotated[str, "Timeframe for candles: '1', '5', '15', '30', '60', '240', '1D', '1W', '1M'"],
    num_candles: Annotated[int, "Number of candles/bars to retrieve (max 5000)"] = 100,
) -> str:
    """
    Retrieve real-time OHLCV candle data from TradingView for a given symbol.
    Returns open, high, low, close, volume for each candle in the specified timeframe.

    Args:
        symbol (str): TradingView symbol, e.g. 'NASDAQ:AAPL', 'BINANCE:BTCUSDT'
        timeframe (str): Candle timeframe: '1', '5', '15', '30', '60', '240', '1D', '1W', '1M'
        num_candles (int): Number of candles to retrieve, default 100
    Returns:
        str: CSV-formatted OHLCV candle data with header metadata.
    """
    return route_to_vendor("get_live_candles", symbol=symbol, timeframe=timeframe, range_bars=num_candles)


@tool
def get_live_indicator(
    symbol: Annotated[str, "TradingView-formatted symbol, e.g. 'NASDAQ:AAPL', 'BINANCE:BTCUSDT'"],
    indicator: Annotated[str, "Indicator name, e.g. 'RSI', 'STD;MACD', 'STD;Supertrend'"],
    timeframe: Annotated[str, "Timeframe for indicator: '1D', '60', '240', etc."] = "1D",
) -> str:
    """
    Retrieve a real-time technical indicator value from TradingView.
    Works with built-in and custom indicators. Returns indicator values aligned with price candles.

    Args:
        symbol (str): TradingView symbol, e.g. 'NASDAQ:AAPL'
        indicator (str): Indicator name, e.g. 'RSI', 'STD;MACD', 'STD;Bollinger_Bands'
        timeframe (str): Timeframe, default '1D'
    Returns:
        str: CSV with indicator values and corresponding OHLCV price data.
    """
    return route_to_vendor("get_live_indicator", symbol=symbol, indicator=indicator, timeframe=timeframe)


@tool
def get_technical_analysis(
    symbol: Annotated[str, "TradingView-formatted symbol, e.g. 'NASDAQ:AAPL'"],
    timeframe: Annotated[str, "Timeframe for analysis: '1D', '1W', '1M', etc."] = "1D",
) -> str:
    """
    Retrieve TradingView's technical analysis summary for a symbol.
    Includes oscillators rating, moving averages rating, and individual indicator signals.

    Args:
        symbol (str): TradingView symbol, e.g. 'NASDAQ:AAPL'
        timeframe (str): Timeframe, default '1D'
    Returns:
        str: Formatted technical analysis summary with buy/sell signals.
    """
    return route_to_vendor("get_technical_analysis", symbol=symbol, timeframe=timeframe)


@tool
def search_symbol(
    query: Annotated[str, "Search query, e.g. 'Apple', 'BTC', 'Tesla'"],
    type: Annotated[Optional[str], "Filter by type: 'stock', 'crypto', 'forex'"] = "",
) -> str:
    """
    Search for TradingView symbols matching a query.
    Returns matching symbols with descriptions, types, and exchange info.
    Use this to find the correct TradingView symbol format (e.g., 'NASDAQ:AAPL') before calling other real-time tools.

    Args:
        query (str): Search term, e.g. 'Apple', 'BTC', 'TSLA'
        type (str, optional): Filter results by type
    Returns:
        str: CSV of matching symbols with descriptions.
    """
    return route_to_vendor("search_symbol", query=query, type=type)
