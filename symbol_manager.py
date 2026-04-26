"""Multi-symbol support. Load/save monitored symbols, search via TradingView."""

import json
import os
from datetime import datetime

SYMBOLS_FILE = os.path.join(os.path.dirname(__file__), "symbols.json")


def load_symbols():
    if os.path.exists(SYMBOLS_FILE):
        with open(SYMBOLS_FILE, "r") as f:
            data = json.load(f)
        return data.get("symbols", {})
    return {"CFI:US100": {"name": "Nasdaq 100 SPOT", "active": True, "added": datetime.now().isoformat()}}


def save_symbols(symbols):
    with open(SYMBOLS_FILE, "w") as f:
        json.dump({"symbols": symbols}, f, indent=2)


def get_active_symbols():
    return {k: v for k, v in load_symbols().items() if v.get("active")}


def add_symbol(symbol, name="", active=True):
    symbols = load_symbols()
    symbols[symbol] = {
        "name": name or symbol,
        "active": active,
        "added": datetime.now().isoformat(),
    }
    save_symbols(symbols)
    return symbols[symbol]


def remove_symbol(symbol):
    symbols = load_symbols()
    if symbol in symbols:
        del symbols[symbol]
        save_symbols(symbols)
        return True
    return False


def toggle_symbol(symbol, active=None):
    symbols = load_symbols()
    if symbol in symbols:
        symbols[symbol]["active"] = active if active is not None else not symbols[symbol].get("active", True)
        save_symbols(symbols)
        return symbols[symbol]


def search_tv_symbol(query):
    """Search TradingView for a symbol."""
    try:
        from tradingagents.dataflows.tv_realtime import search_symbol
        result = search_symbol(query)
        lines = result.strip().split("\n")
        matches = []
        for line in lines[1:]:  # skip header
            if line.strip():
                parts = line.split(",")
                if len(parts) >= 4:
                    matches.append({
                        "symbol": parts[0],
                        "description": parts[1],
                        "type": parts[2],
                        "exchange": parts[3],
                    })
        return matches[:15]
    except Exception as e:
        return []
