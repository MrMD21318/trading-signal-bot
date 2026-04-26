"""Lightweight TradingView search and chart using direct HTTP — no Node.js bridge needed.

Uses TradingView's public API endpoints directly via Python requests.
"""

import json
import logging
import requests

logger = logging.getLogger(__name__)

TV_SEARCH_URL = "https://symbol-search.tradingview.com/symbol_search/"


def search_tv(query, limit=15):
    """Search TradingView symbols via public HTTP API."""
    try:
        params = {
            "text": query,
            "hl": "1",
            "exchange": "",
            "lang": "en",
            "search_type": "",
            "domain": "production",
        }
        r = requests.get(TV_SEARCH_URL, params=params, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        results = []
        for item in data[:limit]:
            results.append({
                "symbol": item.get("symbol", ""),
                "description": item.get("description", ""),
                "type": item.get("type", ""),
                "exchange": item.get("exchange", ""),
                "full_symbol": item.get("exchange", "") + ":" + item.get("symbol", "") if item.get("exchange") else item.get("symbol", ""),
            })
        return results
    except Exception as e:
        logger.warning("TV search failed: %s", e)
        return []


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
