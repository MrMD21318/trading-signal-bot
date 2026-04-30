"""SQLite database for users, subscriptions, and alert history."""

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "trading_bot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            phone TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            telegram_name TEXT DEFAULT '',
            active INTEGER DEFAULT 0,
            alerts_received INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT '',
            last_alert_at TEXT DEFAULT '',
            subscription_expiry TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS user_symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            symbol_name TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            FOREIGN KEY(chat_id) REFERENCES users(chat_id) ON DELETE CASCADE,
            UNIQUE(chat_id, symbol)
        );

        CREATE TABLE IF NOT EXISTS alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            setup TEXT NOT NULL,
            entry REAL,
            sl REAL,
            tp REAL,
            strategy TEXT DEFAULT '',
            timeframe TEXT DEFAULT '',
            confidence REAL DEFAULT 0,
            sent_at TEXT DEFAULT '',
            FOREIGN KEY(chat_id) REFERENCES users(chat_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_alerts_chat ON alert_log(chat_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_time ON alert_log(sent_at);
        CREATE INDEX IF NOT EXISTS idx_user_syms ON user_symbols(chat_id);
    """)
    conn.commit()
    conn.close()


# ── Users ─────────────────────────────────────────────────────
def upsert_user(chat_id, first_name="", username="", phone=""):
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute("SELECT chat_id FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    telegram_name = f"{first_name} {username}".strip() or f"User_{chat_id}"
    if existing:
        conn.execute(
            "UPDATE users SET first_name=?, username=?, telegram_name=?, phone=? WHERE chat_id=?",
            (first_name, username, telegram_name, phone or "", chat_id),
        )
    else:
        conn.execute(
            "INSERT INTO users (chat_id, phone, first_name, username, telegram_name, active, joined_at) VALUES (?,?,?,?,?,0,?)",
            (chat_id, phone, first_name, username, telegram_name, now),
        )
    conn.commit()
    conn.close()


def get_all_users():
    conn = get_conn()
    rows = conn.execute(
        "SELECT u.*, COUNT(DISTINCT us.symbol) as sym_count FROM users u "
        "LEFT JOIN user_symbols us ON u.chat_id=us.chat_id AND us.active=1 "
        "GROUP BY u.chat_id ORDER BY u.joined_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user(chat_id):
    conn = get_conn()
    r = conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    return dict(r) if r else None


def set_user_active(chat_id, active):
    conn = get_conn()
    conn.execute("UPDATE users SET active=?, alerts_received=0 WHERE chat_id=?", (int(active), chat_id))
    conn.commit()
    conn.close()


def set_user_expiry(chat_id, days=30):
    """Set subscription expiry to N days from now."""
    from datetime import timedelta
    expiry = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    conn = get_conn()
    conn.execute("UPDATE users SET subscription_expiry=? WHERE chat_id=?", (expiry, chat_id))
    conn.commit()
    conn.close()
    return expiry


def is_subscription_valid(chat_id):
    conn = get_conn()
    u = conn.execute("SELECT active, subscription_expiry FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    if not u or not u["active"]:
        return False
    if u["subscription_expiry"]:
        from datetime import timezone as tz
        expiry = datetime.fromisoformat(u["subscription_expiry"])
        if datetime.now(tz.utc) > expiry:
            return False
    return True


def get_pending_users():
    """Users who are not active (pending admin approval)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM users WHERE active=0 ORDER BY joined_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_user_phone(chat_id, phone):
    conn = get_conn()
    conn.execute("UPDATE users SET phone=? WHERE chat_id=?", (phone, chat_id))
    conn.commit()
    conn.close()


# ── Subscriptions ─────────────────────────────────────────────
def add_user_symbol(chat_id, symbol, symbol_name=""):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO user_symbols (chat_id, symbol, symbol_name, active) VALUES (?,?,?,1)",
        (chat_id, symbol, symbol_name),
    )
    conn.commit()
    conn.close()


def remove_user_symbol(chat_id, symbol):
    conn = get_conn()
    conn.execute("DELETE FROM user_symbols WHERE chat_id=? AND symbol=?", (chat_id, symbol))
    conn.commit()
    conn.close()


def get_user_symbols(chat_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT symbol, symbol_name, active FROM user_symbols WHERE chat_id=? AND active=1", (chat_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_users_for_symbol(symbol):
    """Get active users who are subscribed to a given symbol."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT u.chat_id, u.first_name, u.telegram_name FROM users u "
        "JOIN user_symbols us ON u.chat_id=us.chat_id "
        "WHERE u.active=1 AND us.symbol=? AND us.active=1",
        (symbol,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_users_with_subs():
    """Get all active users with their symbol lists."""
    conn = get_conn()
    users = conn.execute("SELECT * FROM users WHERE active=1").fetchall()
    result = []
    for u in users:
        ud = dict(u)
        syms = conn.execute(
            "SELECT symbol, symbol_name FROM user_symbols WHERE chat_id=? AND active=1", (ud["chat_id"],)
        ).fetchall()
        ud["symbols"] = [dict(s) for s in syms]
        result.append(ud)
    conn.close()
    return result


def user_has_symbol(chat_id, symbol):
    conn = get_conn()
    r = conn.execute(
        "SELECT 1 FROM user_symbols WHERE chat_id=? AND symbol=? AND active=1", (chat_id, symbol)
    ).fetchone()
    conn.close()
    return r is not None


# ── Alert Log ─────────────────────────────────────────────────
def log_alert(chat_id, symbol, direction, setup, entry, sl, tp, strategy="", timeframe="", confidence=0):
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO alert_log (chat_id, symbol, direction, setup, entry, sl, tp, strategy, timeframe, confidence, sent_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (chat_id, symbol, direction, setup, entry, sl, tp, strategy, timeframe, confidence, now),
    )
    conn.execute(
        "UPDATE users SET alerts_received = alerts_received + 1, last_alert_at = ? WHERE chat_id = ?",
        (now, chat_id),
    )
    conn.commit()
    conn.close()


def get_user_alerts(chat_id, limit=50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM alert_log WHERE chat_id=? ORDER BY sent_at DESC LIMIT ?", (chat_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_alert_count(chat_id):
    conn = get_conn()
    r = conn.execute("SELECT alerts_received FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    return r["alerts_received"] if r else 0


def get_recent_alerts(limit=100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT al.*, u.first_name, u.telegram_name FROM alert_log al "
        "LEFT JOIN users u ON al.chat_id=u.chat_id "
        "ORDER BY al.sent_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_total_stats():
    conn = get_conn()
    users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    active = conn.execute("SELECT COUNT(*) as c FROM users WHERE active=1").fetchone()["c"]
    alerts = conn.execute("SELECT COUNT(*) as c FROM alert_log").fetchone()["c"]
    conn.close()
    return {"total_users": users, "active_users": active, "total_alerts": alerts}


# Initialize on import
init_db()
# Migration: add subscription_expiry if column doesn't exist
try:
    conn = get_conn()
    conn.execute("ALTER TABLE users ADD COLUMN subscription_expiry TEXT DEFAULT ''")
    conn.commit()
    conn.close()
except:
    pass
