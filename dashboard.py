"""Signal Dashboard — Flask backend for the SPA frontend.

Serves:
  GET  /                → templates/index.html (SPA)
  GET  /static/*        → static assets

API endpoints:
  GET  /api/status      → System status
  GET  /api/users       → All users
  POST /api/users       → Add user
  GET  /api/users/<id>  → User detail
  PATCH /api/users/<id> → Update user (active, etc.)
  DELETE /api/users/<id> → Delete user
  POST /api/users/<id>/phone → Set phone
  GET  /api/users/<id>/symbols → User's symbols
  POST /api/users/<id>/symbols → Add symbol to user
  DELETE /api/users/<id>/symbols/<sym> → Remove
  GET  /api/alerts      → Alert log
  GET  /api/symbols     → Managed symbols
  POST /api/symbols     → Add symbol
  DELETE /api/symbols/<sym> → Remove
  PATCH /api/symbols/<sym> → Toggle
  POST /api/symbols/search → Search TV
  POST /api/chart-data  → Price chart OHLCV data
"""

import json
import os
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_from_directory

from database import (
    get_all_users, get_user, set_user_active, set_user_phone,
    add_user_symbol, remove_user_symbol, get_user_symbols,
    get_recent_alerts, get_total_stats, upsert_user,
    set_user_expiry, is_subscription_valid, get_pending_users,
)

app = Flask(__name__, static_folder="static", template_folder="templates")
bot_start_time = datetime.now()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


# ── API ────────────────────────────────────────────────────────

@app.route("/api/debug")
def api_debug():
    """Show current monitoring state."""
    from run_us100_monitor import get_candles
    from symbol_manager import get_active_symbols
    syms = list(get_active_symbols().keys()) if get_active_symbols() else ["CFI:US100"]
    result = {"active_symbols": syms, "candles": {}}
    for sym in syms[:3]:
        for tf in ["5", "15", "1D"]:
            c = get_candles(sym, tf, 5)
            last = c[0][4] if c else 0
            result["candles"][f"{sym}_{tf}"] = {"count": len(c), "price": last}
    from database import get_total_stats
    result["stats"] = get_total_stats()
    return jsonify(result)


@app.route("/api/status")
def api_status():
    stats = get_total_stats()
    delta = datetime.now() - bot_start_time
    return jsonify({
        "running": True,
        "uptime_seconds": int(delta.total_seconds()),
        "started_at": bot_start_time.isoformat(),
        **stats,
    })


@app.route("/api/test-signal")
def api_test_signal():
    """Send a test signal to verify pipeline."""
    symbol = "CFI:US100"
    try:
        from run_us100_monitor import get_candles, fmt
        m1 = get_candles(symbol, "1", 5)
        m5 = get_candles(symbol, "5", 5)
        d1 = get_candles(symbol, "1D", 10)
        price = m5[0][4] if m5 else (m1[0][4] if m1 else (d1[0][4] if d1 else 0))
        candle_count_1m = len(m1) if m1 else 0
        candle_count_5m = len(m5) if m5 else 0
        candle_count_1d = len(d1) if d1 else 0

        TOK = os.getenv("TELEGRAM_BOT_TOKEN", "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A")
        from database import get_active_users_with_subs
        users = get_active_users_with_subs()
        sent_count = 0
        if users and price > 0:
            import requests as req
            for u in users:
                r = req.post(f"https://api.telegram.org/bot{TOK}/sendMessage", json={
                    "chat_id": u["chat_id"],
                    "text": f"\U0001f6e0 <b>System Test</b>\n\nSymbol: {symbol}\nPrice: <code>{fmt(price)}</code>\n1M: {candle_count_1m} candles | 5M: {candle_count_5m} | 1D: {candle_count_1d}\n\nData pipeline: {'OK' if price>0 else 'FAIL'}",
                    "parse_mode": "HTML",
                }, timeout=10)
                if r.status_code == 200:
                    sent_count += 1

        return jsonify({
            "ok": True,
            "price": price,
            "candles_1m": candle_count_1m,
            "candles_5m": candle_count_5m,
            "candles_1d": candle_count_1d,
            "users_notified": sent_count,
            "active_users": len(users),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    stats = get_total_stats()
    delta = datetime.now() - bot_start_time
    return jsonify({
        "running": True,
        "uptime_seconds": int(delta.total_seconds()),
        "started_at": bot_start_time.isoformat(),
        **stats,
    })


@app.route("/api/users", methods=["GET", "POST"])
def api_users():
    if request.method == "GET":
        users = []
        for u in get_all_users():
            u["symbols"] = get_user_symbols(u["chat_id"])
            users.append(u)
        return jsonify(users)
    data = request.get_json()
    chat_id = int(data.get("chat_id", 0))
    if not chat_id:
        return jsonify({"error": "chat_id required"}), 400
    upsert_user(chat_id, data.get("first_name", ""), data.get("username", ""))
    return jsonify({"ok": True})


@app.route("/api/users/<int:chat_id>", methods=["GET", "PATCH", "DELETE"])
def api_user(chat_id):
    if request.method == "GET":
        u = get_user(chat_id)
        if not u:
            return jsonify({"error": "not found"}), 404
        u["symbols"] = get_user_symbols(chat_id)
        return jsonify(u)
    if request.method == "PATCH":
        data = request.get_json() or {}
        if "active" in data:
            set_user_active(chat_id, data["active"])
            if data["active"]:
                # Set default 30-day subscription when activating
                set_user_expiry(chat_id, data.get("days", 30))
            # Send notification to user
            TOK = os.getenv("TELEGRAM_BOT_TOKEN", "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A")
            if data["active"]:
                syms = get_user_symbols(chat_id)
                syms_str = ", ".join(s["symbol"] for s in syms) if syms else "None"
                import requests as req
                req.post(f"https://api.telegram.org/bot{TOK}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": f"\u2705 <b>Activated!</b>\n\nMarkets: <code>{syms_str}</code>\nSubscription: {data.get('days', 30)} days\n\nYou will now receive trading signals.",
                    "parse_mode": "HTML",
                }, timeout=10)
        if "days" in data:
            set_user_expiry(chat_id, data["days"])
        if "phone" in data:
            set_user_phone(chat_id, data["phone"])
        return jsonify({"ok": True})
    if request.method == "DELETE":
        from database import get_conn
        conn = get_conn()
        conn.execute("DELETE FROM user_symbols WHERE chat_id=?", (chat_id,))
        conn.execute("DELETE FROM alert_log WHERE chat_id=?", (chat_id,))
        conn.execute("DELETE FROM users WHERE chat_id=?", (chat_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})


@app.route("/api/users/<int:chat_id>/phone", methods=["POST"])
def api_user_phone(chat_id):
    set_user_phone(chat_id, request.get_json().get("phone", ""))
    return jsonify({"ok": True})


@app.route("/api/users/<int:chat_id>/symbols", methods=["GET", "POST"])
def api_user_syms(chat_id):
    if request.method == "GET":
        return jsonify(get_user_symbols(chat_id))
    data = request.get_json()
    symbols_list = data.get("symbols", [])  # bulk: [{"symbol":"CFI:US100","symbol_name":"Nasdaq"},...]
    if symbols_list:
        # Bulk assign — replace all existing
        conn = __import__("database").get_conn()
        conn.execute("DELETE FROM user_symbols WHERE chat_id=?", (chat_id,))
        conn.commit()
        for s in symbols_list:
            add_user_symbol(chat_id, s.get("symbol", ""), s.get("symbol_name", ""))
        conn.close()
        # Notify user
        syms_str = ", ".join(s["symbol"] for s in symbols_list)
        TOK = os.getenv("TELEGRAM_BOT_TOKEN", "8644679098:AAF0Ag9nNOElhldvpTXXO2rHLB7dPmOtM5A")
        import requests as req
        req.post(f"https://api.telegram.org/bot{TOK}/sendMessage", json={
            "chat_id": chat_id,
            "text": f"\U0001f4cb <b>Markets Assigned</b>\n\n<code>{syms_str}</code>\n\nYou will receive signals for these markets.",
            "parse_mode": "HTML",
        }, timeout=10)
        return jsonify({"ok": True})
    # Single symbol add
    add_user_symbol(chat_id, data["symbol"], data.get("symbol_name", ""))
    return jsonify({"ok": True})


@app.route("/api/users/<int:chat_id>/symbols/<path:symbol>", methods=["DELETE"])
def api_user_sym_del(chat_id, symbol):
    remove_user_symbol(chat_id, symbol)
    return jsonify({"ok": True})


@app.route("/api/alerts")
def api_alerts():
    return jsonify(get_recent_alerts(request.args.get("limit", 50, type=int)))


@app.route("/api/symbols", methods=["GET", "POST"])
def api_symbols():
    if request.method == "GET":
        from symbol_manager import load_symbols
        return jsonify(load_symbols())
    data = request.get_json()
    from symbol_manager import add_symbol as add_sym
    add_sym(data["symbol"], data.get("name", data["symbol"]))
    return jsonify({"ok": True})


@app.route("/api/symbols/<path:symbol>", methods=["DELETE", "PATCH"])
def api_symbol(symbol):
    if request.method == "DELETE":
        from symbol_manager import remove_symbol as rm_sym
        rm_sym(symbol)
        return jsonify({"ok": True})
    from symbol_manager import toggle_symbol as tog
    data = request.get_json() or {}
    tog(symbol, data.get("active"))
    return jsonify({"ok": True})


@app.route("/api/symbols/search", methods=["POST"])
def api_symbol_search():
    from symbol_manager import search_tv_symbol
    return jsonify(search_tv_symbol(request.get_json().get("query", "")))


@app.route("/api/chart-data", methods=["POST"])
def api_chart_data():
    data = request.get_json() or {}
    symbol = data.get("symbol", "CFI:US100")
    timeframe = data.get("timeframe", "1D")
    bars = min(data.get("bars", 30), 500)
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
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_dashboard(host="0.0.0.0", port=5000, debug=False):
    print(f"\n  Dashboard: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_dashboard(debug=True)
