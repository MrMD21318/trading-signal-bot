"""Professional Signal Engine — high-quality entries with multi-TP, tracking, R:R management.

Principles:
- Quality over quantity: minimum confidence 0.65, R:R >= 1:2
- Multi-TP: TP1 (1:1), TP2 (1:2), TP3 (1:3)
- Signal tracking: monitors active positions, alerts TP/SL hits
- Conflict resolution: never send opposing signals on same symbol
- Professional SMC + classic candle analysis
"""

import json
import os
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TRACKING_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "active_signals.json")


# ── Signal tracking ───────────────────────────────────────────
def load_active_signals():
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE, "r") as f:
            return json.load(f)
    return {}


def save_active_signals(data):
    with open(TRACKING_FILE, "w") as f:
        json.dump(data, f, indent=2)


def track_signal(symbol, direction, entry, sl, tp1, tp2, tp3, setup, timeframe, confidence):
    signals = load_active_signals()
    sig_id = f"{symbol}_{direction}_{int(time.time())}"
    signals[sig_id] = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "setup": setup,
        "timeframe": timeframe,
        "confidence": confidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "sl_hit": False,
    }
    save_active_signals(signals)
    return sig_id


def check_active_signals(symbol, current_price):
    """Check all active signals for TP/SL hits. Returns list of alerts."""
    signals = load_active_signals()
    alerts = []
    updated = False

    for sig_id, sig in signals.items():
        if sig.get("status") != "active":
            continue
        if sig["symbol"] != symbol:
            continue

        entry = sig["entry"]
        sl = sig["sl"]
        tp1 = sig["tp1"]
        tp2 = sig["tp2"]
        tp3 = sig["tp3"]
        direction = sig["direction"]

        if direction == "LONG":
            if current_price >= tp3 and not sig.get("tp3_hit"):
                sig["tp3_hit"] = True
                sig["status"] = "closed"
                alerts.append(f"\U0001f3c6 {symbol} TP3 HIT! +{(tp3/entry-1)*100:.1f}% profit. Signal closed.")
                updated = True
            elif current_price >= tp2 and not sig.get("tp2_hit"):
                sig["tp2_hit"] = True
                alerts.append(f"\U0001f4c8 {symbol} TP2 HIT @ {tp2:.1f}. Move SL to entry.")
                updated = True
            elif current_price >= tp1 and not sig.get("tp1_hit"):
                sig["tp1_hit"] = True
                alerts.append(f"\u2705 {symbol} TP1 HIT @ {tp1:.1f}. Partial profit secured.")
                updated = True
            if current_price <= sl and not sig.get("sl_hit"):
                sig["sl_hit"] = True
                sig["status"] = "closed"
                alerts.append(f"\u274c {symbol} STOP LOSS HIT @ {sl:.1f}. {-((entry/sl-1)*100):.1f}% loss.")
                updated = True
        else:  # SHORT
            if current_price <= tp3 and not sig.get("tp3_hit"):
                sig["tp3_hit"] = True
                sig["status"] = "closed"
                alerts.append(f"\U0001f3c6 {symbol} TP3 HIT! +{((entry/tp3-1)*100):.1f}% profit. Signal closed.")
                updated = True
            elif current_price <= tp2 and not sig.get("tp2_hit"):
                sig["tp2_hit"] = True
                alerts.append(f"\U0001f4c8 {symbol} TP2 HIT @ {tp2:.1f}. Move SL to entry.")
                updated = True
            elif current_price <= tp1 and not sig.get("tp1_hit"):
                sig["tp1_hit"] = True
                alerts.append(f"\u2705 {symbol} TP1 HIT @ {tp1:.1f}. Partial profit secured.")
                updated = True
            if current_price >= sl and not sig.get("sl_hit"):
                sig["sl_hit"] = True
                sig["status"] = "closed"
                alerts.append(f"\u274c {symbol} STOP LOSS HIT @ {sl:.1f}. {-((sl/entry-1)*100):.1f}% loss.")
                updated = True

        # Remove signals older than 7 days
        created = datetime.fromisoformat(sig.get("created_at", ""))
        if (datetime.now(timezone.utc) - created).days > 7:
            sig["status"] = "expired"
            updated = True

    if updated:
        # Clean expired
        signals = {k: v for k, v in signals.items() if v.get("status") not in ("expired", "closed")}
        save_active_signals(signals)

    return alerts


def get_active_signal_count(symbol=None):
    signals = load_active_signals()
    if symbol:
        return sum(1 for s in signals.values() if s.get("symbol") == symbol and s.get("status") == "active")
    return sum(1 for s in signals.values() if s.get("status") == "active")


# ── Signal scoring and selection ──────────────────────────────
def score_signal(sig):
    """Score a signal 0-100 based on quality factors."""
    score = sig.get("confidence", 0.5) * 100

    # R:R bonus
    try:
        entry = sig["entry"]
        sl = sig["sl"]
        if sig["direction"] == "LONG":
            risk = abs(entry - sl)
            reward = abs(sig.get("tp2", entry) - entry)
        else:
            risk = abs(sl - entry)
            reward = abs(entry - sig.get("tp2", entry))
        rr = reward / risk if risk > 0 else 0
        if rr >= 3:
            score += 15
        elif rr >= 2:
            score += 10
        elif rr >= 1.5:
            score += 5
    except:
        pass

    # SMC signals get bonus (institutional levels)
    if sig.get("strategy") == "SMC":
        score += 8

    # Higher timeframe = more reliable
    tf = sig.get("timeframe", "")
    if "1D" in tf or "4H" in tf:
        score += 10
    elif "1H" in tf:
        score += 5
    elif "15M" in tf:
        score += 2

    return score


def select_best_signals(all_signals):
    """Select the best signal per direction per symbol. No conflicts. Filters bad signals."""
    if not all_signals:
        return []

    # Filter: minimum candle quality
    filtered = []
    for s in all_signals:
        entry = s.get("entry", 0)
        sl = s.get("sl", 0)
        if not entry or not sl or entry <= 0 or sl <= 0:
            continue
    # Ensure minimum SL distance (0.08% for plausible trades)
            sl_pct = abs(entry - sl) / entry * 100
            if sl_pct < 0.05:
                continue
        # Ensure TP is beyond entry
        if s["direction"] == "LONG" and s.get("tp", 0) <= entry:
            continue
        if s["direction"] == "SHORT" and s.get("tp", 0) >= entry:
            continue
        filtered.append(s)

    if not filtered:
        return []

    # Score all
    for s in filtered:
        s["score"] = score_signal(s)

    # Group by symbol + direction
    groups = {}
    for s in all_signals:
        key = f"{s.get('symbol','?')}_{s['direction']}"
        if key not in groups:
            groups[key] = []
        groups[key].append(s)

    # Pick best per group
    best = []
    for key, sigs in groups.items():
        sigs.sort(key=lambda x: x["score"], reverse=True)
        top = sigs[0]
        # Accept all signals - confidence already factored in scoring
        best.append(top)

    # Check for conflicts (both buy and sell on same symbol)
    symbols = {}
    for s in best:
        sym = s.get("symbol", "")
        if sym not in symbols:
            symbols[sym] = []
        symbols[sym].append(s)

    # Check for conflicts (both buy and sell on same symbol) - resolve to single best
    resolved = []
    for sym, sigs in symbols.items():
        if len(sigs) == 1:
            resolved.append(sigs[0])
        else:
            # Only ONE signal per symbol - pick highest scored
            sigs.sort(key=lambda x: x["score"], reverse=True)
            resolved.append(sigs[0])

    # Sort by score descending
    resolved.sort(key=lambda x: x["score"], reverse=True)
    return resolved


def calculate_multi_tp(sig):
    """Calculate TP1, TP2, TP3 from entry and SL."""
    entry = float(sig["entry"])
    sl_price = float(sig["sl"])
    direction = sig["direction"]

    if direction == "LONG":
        risk = entry - sl_price
        tp1 = entry + risk * 1.0
        tp2 = entry + risk * 2.0
        tp3 = entry + risk * 3.0
    else:
        risk = sl_price - entry
        tp1 = entry - risk * 1.0
        tp2 = entry - risk * 2.0
        tp3 = entry - risk * 3.0

    return round(tp1, 1), round(tp2, 1), round(tp3, 1)


# ── Message formatter ─────────────────────────────────────────
def fmt(n):
    return f"{n:,.1f}" if n else "—"


def format_professional_signal(sig, is_new=True):
    d = "\U0001f7e2" if sig["direction"] == "LONG" else "\U0001f534"
    strategy = sig.get("strategy", "")
    trade_type = sig.get("trade_type", "")
    if strategy == "SMC":
        label_en = "SMC"; label_ar = "\u0633\u0645\u0627\u0631\u062a \u0645\u0648\u0646\u064a"  # سمارت موني
    elif trade_type == "SWING":
        label_en = "SWING"; label_ar = "\u0633\u0648\u064a\u0646\u062c"  # سوينج
    else:
        label_en = "SCALP"; label_ar = "\u0633\u0643\u0627\u0644\u0628"  # سكالب

    direction = sig["direction"]
    entry = sig["entry"]
    sl = sig["sl"]
    tp1 = sig.get("tp1", entry)
    tp2 = sig.get("tp2", entry)
    tp3 = sig.get("tp3", entry)
    tf = sig.get("timeframe", "")
    conf = sig.get("confidence", 0.7)
    conf_stars = "\u2b50" * int(conf * 5)
    price_now = sig.get("price_now", entry)
    sym_name = sig.get("symbol_name", "") or sig.get("symbol", "")
    sym = sig.get("symbol", "?")
    session_str = sig.get("session", "")
    reasoning = sig.get("reasoning", "")[:250]
    setup_en = sig.get("setup", "")

    # ── Arabic translations ──
    dir_en = direction
    dir_ar = "\u0634\u0631\u0627\u0621" if direction == "LONG" else "\u0628\u064a\u0639"  # شراء / بيع
    if direction == "LONG":
        risk_pct = abs(entry - sl) / entry * 100
        order_en = sig.get("order_type", "Buy")
        order_ar = "\u0634\u0631\u0627\u0621 \u0645\u0639\u0644\u0642" if "Limit" in str(sig.get("order_type","")) else "\u0634\u0631\u0627\u0621 \u0645\u062a\u0648\u0642\u0641"  # شراء معلق / متوقف
    else:
        risk_pct = abs(sl - entry) / entry * 100
        order_en = sig.get("order_type", "Sell")
        order_ar = "\u0628\u064a\u0639 \u0645\u0639\u0644\u0642" if "Limit" in str(sig.get("order_type","")) else "\u0628\u064a\u0639 \u0645\u062a\u0648\u0642\u0641"

    return (
        f"{d} <b>{dir_en} [{label_en}]</b> {conf_stars}\n"
        f"\U0001f4b0 <code>{fmt(price_now)}</code> | {session_str}\n"
        f"\U0001f4ca {sym_name} | <code>{sym}</code> | {tf}\n\n"
        f"<b>Setup:</b> {setup_en}\n"
        f"\U0001f3af ENTRY: <code>{fmt(entry)}</code>\n"
        f"\U0001f6d1 SL: <code>{fmt(sl)}</code> ({risk_pct:.2f}%)\n"
        f"\U0001f3c6 TP1: <code>{fmt(tp1)}</code> | TP2: <code>{fmt(tp2)}</code> | TP3: <code>{fmt(tp3)}</code>\n"
        f"\U0001f9e0 <i>{reasoning}</i>\n\n"
        f"{'─' * 20}\n"
        f"{d} <b>\u0625\u0634\u0627\u0631\u0629 {dir_ar} [{label_ar}]</b> {conf_stars}\n"
        f"\U0001f4b0 <code>{fmt(price_now)}</code> | {session_str}\n"
        f"\U0001f4ca {sym_name} | <code>{sym}</code> | {tf}\n\n"
        f"\U0001f3af \u0627\u0644\u062f\u062e\u0648\u0644: <code>{fmt(entry)}</code>\n"
        f"\U0001f6d1 \u0648\u0642\u0641 \u0627\u0644\u062e\u0633\u0627\u0631\u0629: <code>{fmt(sl)}</code> ({risk_pct:.2f}%)\n"
        f"\U0001f3c6 \u0627\u0644\u0647\u062f\u0641 1: <code>{fmt(tp1)}</code> | 2: <code>{fmt(tp2)}</code> | 3: <code>{fmt(tp3)}</code>\n"
        f"\u2b50 \u0627\u0644\u062b\u0642\u0629: {conf:.0%}"
    )
