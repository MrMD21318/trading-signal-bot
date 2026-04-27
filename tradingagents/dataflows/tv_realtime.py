import json
import os
import subprocess
import sys
import time
import uuid
import logging

logger = logging.getLogger(__name__)

_BRIDGE_PROCESS = None
_BRIDGE_READY = False
_RESPONSES = {}
_BRIDGE_DIR = os.environ.get("TV_BRIDGE_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tv_bridge"))


def _get_bridge_process():
    global _BRIDGE_PROCESS, _BRIDGE_READY

    if _BRIDGE_PROCESS is not None and _BRIDGE_PROCESS.poll() is not None:
        logger.warning("Bridge process exited with code %d, restarting", _BRIDGE_PROCESS.returncode)
        _BRIDGE_PROCESS = None
        _BRIDGE_READY = False

    if _BRIDGE_PROCESS is None:
        node_exe = os.environ.get("NODE_BIN", "node")
        bridge_script = os.path.join(_BRIDGE_DIR, "tv_bridge.mjs")

        logger.info("Starting bridge: %s %s (cwd: %s)", node_exe, bridge_script, _BRIDGE_DIR)

        if not os.path.exists(bridge_script):
            raise RuntimeError(
                f"TV bridge script not found at {bridge_script}. "
                f"Files in tv_bridge: {os.listdir(_BRIDGE_DIR) if os.path.exists(_BRIDGE_DIR) else 'DIR NOT FOUND'}"
            )

        if not os.path.exists(os.path.join(_BRIDGE_DIR, "node_modules")):
            raise RuntimeError(
                f"Node modules not found in {_BRIDGE_DIR}. Run: cd tv_bridge && npm install"
            )

        try:
            _BRIDGE_PROCESS = subprocess.Popen(
                [node_exe, bridge_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=_BRIDGE_DIR,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Node.js is not installed. Install from: https://nodejs.org"
            )

        stderr_line = _BRIDGE_PROCESS.stderr.readline().strip()
        if stderr_line:
            try:
                msg = json.loads(stderr_line)
                if msg.get("ready"):
                    _BRIDGE_READY = True
            except json.JSONDecodeError:
                logger.warning(f"Bridge stderr: {stderr_line}")

        time.sleep(0.5)

    return _BRIDGE_PROCESS


def _send_command(command: str, timeout: float = 30.0, **params) -> dict:
    proc = _get_bridge_process()
    if not _BRIDGE_READY:
        raise RuntimeError("TV bridge is not ready. Ensure Node.js and @mathieuc/tradingview are installed.")

    request_id = str(uuid.uuid4())[:8]
    payload = {"id": request_id, "command": command, **params}

    try:
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
    except (BrokenPipeError, OSError) as e:
        _shutdown_bridge()
        raise RuntimeError(f"Bridge process disconnected: {e}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                stderr_text = proc.stderr.read() if proc.stderr else ""
                _shutdown_bridge()
                raise RuntimeError(f"Bridge process exited unexpectedly. Stderr: {stderr_text}")
            time.sleep(0.1)
            continue

        try:
            result = json.loads(line.strip())
            if result.get("id") == request_id:
                if result.get("error"):
                    raise RuntimeError(f"Bridge error [{result.get('code', 'UNKNOWN')}]: {result.get('message', 'Unknown error')}")
                return result
        except json.JSONDecodeError:
            continue

    raise TimeoutError(f"Bridge command '{command}' timed out after {timeout}s")


def _shutdown_bridge():
    global _BRIDGE_PROCESS, _BRIDGE_READY
    if _BRIDGE_PROCESS:
        try:
            _BRIDGE_PROCESS.stdin.close()
            _BRIDGE_PROCESS.stdout.close()
            _BRIDGE_PROCESS.stderr.close()
            _BRIDGE_PROCESS.terminate()
            _BRIDGE_PROCESS.wait(timeout=5)
        except Exception:
            try:
                _BRIDGE_PROCESS.kill()
            except Exception:
                pass
        _BRIDGE_PROCESS = None
        _BRIDGE_READY = False


def get_live_chart(
    symbol: str,
    timeframe: str = "1D",
    range_bars: int = 100,
) -> str:
    if not symbol:
        return "Error: symbol is required"

    try:
        result = _send_command("get_chart", symbol=symbol, timeframe=timeframe, range=range_bars)

        periods = result.get("periods", [])
        if not periods:
            return f"No chart data returned for {symbol}"

        lines = ["time,open,high,low,close,volume"]
        for p in periods:
            lines.append(f"{p['time']},{p['open']},{p['high']},{p['low']},{p['close']},{p.get('volume', 0)}")

        header = (
            f"# Symbol: {result.get('symbol', symbol)}\n"
            f"# Description: {result.get('description', 'N/A')}\n"
            f"# Currency: {result.get('currency', 'N/A')}\n"
            f"# Timeframe: {result.get('timeframe', timeframe)}\n"
            f"# Bars: {len(periods)}\n"
        )
        return header + "\n".join(lines)

    except Exception as e:
        return f"Error fetching live chart data: {str(e)}"


def get_live_indicator(
    symbol: str,
    indicator: str,
    timeframe: str = "1D",
) -> str:
    if not symbol or not indicator:
        return "Error: symbol and indicator are required"

    try:
        result = _send_command("get_indicator", symbol=symbol, timeframe=timeframe, indicator=indicator)

        indicator_periods = result.get("indicatorPeriods", [])
        price_periods = result.get("pricePeriods", [])

        if not price_periods and not indicator_periods:
            return f"No indicator data returned for {symbol}"

        price_map = {}
        for p in price_periods:
            price_map[p["time"]] = f"{p['open']},{p['high']},{p['low']},{p['close']},{p.get('volume', 0)}"

        lines = ["time,indicator_value,open,high,low,close,volume"]
        for p in indicator_periods:
            t = p["time"]
            price_str = price_map.get(t, ",,,,")
            lines.append(f"{t},{p['value']},{price_str}")

        header = (
            f"# Symbol: {result.get('symbol', symbol)}\n"
            f"# Indicator: {result.get('indicator', indicator)}\n"
            f"# Timeframe: {result.get('timeframe', timeframe)}\n"
            f"# Periods: {len(indicator_periods)}\n"
        )
        return header + "\n".join(lines)

    except Exception as e:
        return f"Error fetching live indicator: {str(e)}"


def get_technical_analysis(
    symbol: str,
    timeframe: str = "1D",
) -> str:
    if not symbol:
        return "Error: symbol is required"

    try:
        result = _send_command("get_technical", symbol=symbol, timeframe=timeframe)

        if not result or result.get("error"):
            return f"No technical analysis available for {symbol}: {result.get('message', 'Unknown')}"

        lines = [f"# Technical Analysis for {symbol}"]
        lines.append(f"# Timeframe: {timeframe}")
        lines.append("")

        # TradingView getTA returns { "1D": {Other, All, MA}, "1W": {...}, ... }
        timeframes = ["1", "5", "15", "60", "240", "1D", "1W", "1M"]
        for tf in timeframes:
            if tf in result:
                data = result[tf]
                other = data.get("Other", data.get("other", 0))
                all_val = data.get("All", data.get("all", 0))
                ma = data.get("MA", data.get("ma", 0))
                lines.append(
                    f"{tf}: Other={other}, All={all_val}, MA={ma} "
                    f"({'Buy' if all_val > 0 else 'Sell' if all_val < 0 else 'Neutral'})"
                )

        # Focus on the requested timeframe for summary
        if timeframe in result:
            data = result[timeframe]
            all_val = data.get("All", data.get("all", 0))
            osc = data.get("Other", data.get("other", 0))
            ma_val = data.get("MA", data.get("ma", 0))
            lines.append("")
            lines.append(f"Summary ({timeframe}):")
            lines.append(f"  Overall:      {all_val:.3f} ({'Strong Buy' if all_val > 1 else 'Buy' if all_val > 0.5 else 'Neutral' if all_val > -0.5 else 'Sell' if all_val > -1 else 'Strong Sell'})")
            lines.append(f"  Oscillators:  {osc:.3f}")
            lines.append(f"  Mvg Averages: {ma_val:.3f}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching technical analysis: {str(e)}"


def search_symbol(query: str, type: str = "") -> str:
    if not query:
        return "Error: query is required"

    try:
        result = _send_command("search_symbol", query=query, type=type)
        records = result.get("results", [])

        if not records:
            return f"No results found for '{query}'"

        lines = ["symbol,description,type,exchange"]
        for r in records:
            symbol = r.get("id", r.get("symbol", "?"))
            desc = r.get("description", "")
            stype = r.get("type", "")
            exch = r.get("exchange", "")
            lines.append(f"{symbol},{desc},{stype},{exch}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error searching symbol: {str(e)}"
