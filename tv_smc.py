"""Fetch SMC indicators directly from TradingView via the bridge."""
import subprocess, json, os, logging

logger = logging.getLogger(__name__)

BRIDGE_DIR = os.path.join(os.path.dirname(__file__), "tv_bridge")
BRIDGE_SCRIPT = os.path.join(BRIDGE_DIR, "tv_bridge.mjs")

# Popular SMC indicators on TradingView
SMC_INDICATORS = {
    "order_blocks": "PUB;uAlgo+TV+Order+Blocks+%2F+OB",
    "fvg": "PUB;uAlgo+TV+Fair+Value+%2F+FVG",
    "liquidity": "PUB;uAlgo+TV+Liquidity",
    "trend_structure": "PUB;ICT+Concepts",
}


def fetch_smc(symbol="CFI:US100", timeframe="15"):
    """Fetch SMC indicators from TradingView chart.

    Returns: {order_blocks: [...], fvg: [...], liquidity: [...], price_data: [...], price: float}
    """
    if not os.path.exists(BRIDGE_SCRIPT):
        logger.warning("Bridge not found")
        return None

    results = {}

    for name, ind_id in SMC_INDICATORS.items():
        try:
            proc = subprocess.run(
                ["node", BRIDGE_SCRIPT],
                input=json.dumps({
                    "id": f"smc_{name}",
                    "command": "get_indicator",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "indicator": ind_id,
                }),
                capture_output=True, text=True, timeout=30,
                cwd=BRIDGE_DIR,
            )
            for line in proc.stdout.strip().split("\n"):
                try:
                    data = json.loads(line.strip())
                    if data.get("id") == f"smc_{name}":
                        if data.get("indicatorPeriods"):
                            results[name] = data["indicatorPeriods"]
                        if data.get("pricePeriods"):
                            results["price_data"] = data["pricePeriods"]
                            if data["pricePeriods"]:
                                results["price"] = data["pricePeriods"][-1]["close"]
                except:
                    pass
        except Exception as e:
            logger.debug("SMC fetch %s: %s", name, e)

    return results if results else None
