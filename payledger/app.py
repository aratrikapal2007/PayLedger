"""PayLedger - a mock peer-to-peer payment / expense-splitting app.

Local demo only. All money and users are fake. Do not deploy it.
"""
import os
import secrets
import sqlite3
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")
app.config["SECRET_KEY"] = os.environ.get("PAYLEDGER_SECRET") or secrets.token_hex(32)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["DATABASE"] = os.environ.get("PAYLEDGER_DB", os.path.join(BASE, "payledger.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL,
  balance_cents INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sender_id INTEGER NOT NULL REFERENCES users(id),
  recipient_id INTEGER NOT NULL REFERENCES users(id),
  amount_cents INTEGER NOT NULL,
  memo TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

SEED_USERS = [
    ("alice", "alice123", "Alice Menon", 125000),
    ("bob", "bob123", "Bob D'Souza", 80000),
    ("carol", "carol123", "Carol Iyer", 54000),
    ("dave", "dave123", "Dave Shah", 20000),
]
SEED_TXNS = [
    ("alice", "bob", 25000, "Goa trip - hotel share"),
    ("bob", "alice", 8000, "Dinner at Bandra"),
    ("carol", "alice", 12000, "Electricity bill split"),
    ("alice", "carol", 4500, "Cab to airport"),
    ("dave", "bob", 3000, "Chai and snacks"),
    ("carol", "dave", 15000, "Concert tickets"),
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(seed=True):
    db = sqlite3.connect(app.config["DATABASE"])
    db.executescript(SCHEMA)
    if seed and db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        for u, p, n, b in SEED_USERS:
            db.execute(
                "INSERT INTO users (username, password_hash, display_name, balance_cents) VALUES (?,?,?,?)",
                (u, generate_password_hash(p), n, b),
            )
        ids = {r[1]: r[0] for r in db.execute("SELECT id, username FROM users")}
        for s, r, a, m in SEED_TXNS:
            db.execute(
                "INSERT INTO transactions (sender_id, recipient_id, amount_cents, memo) VALUES (?,?,?,?)",
                (ids[s], ids[r], a, m),
            )
    db.commit()
    db.close()


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if "user_id" not in session:
            return jsonify(error="Sign in required"), 401
        return fn(*a, **kw)

    return wrapper


TXN_SELECT = """
SELECT t.id, t.sender_id, t.recipient_id, t.amount_cents, t.memo, t.created_at,
       s.display_name AS sender_name, r.display_name AS recipient_name
FROM transactions t
JOIN users s ON s.id = t.sender_id
JOIN users r ON r.id = t.recipient_id
"""


def row(r):
    return {k: r[k] for k in r.keys()}


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    user = get_db().execute(
        "SELECT * FROM users WHERE username = ?", (data.get("username", ""),)
    ).fetchone()
    if not user or not check_password_hash(user["password_hash"], data.get("password", "")):
        return jsonify(error="Wrong username or password"), 401
    session["user_id"] = user["id"]
    return jsonify(id=user["id"], username=user["username"], display_name=user["display_name"])


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
@login_required
def me():
    u = get_db().execute("SELECT id, username, display_name, balance_cents FROM users WHERE id = ?",
                         (session["user_id"],)).fetchone()
    return jsonify(row(u))


@app.get("/api/users")
@login_required
def users():
    rows = get_db().execute(
        "SELECT id, username, display_name FROM users WHERE id != ? ORDER BY display_name",
        (session["user_id"],),
    ).fetchall()
    return jsonify([row(r) for r in rows])


@app.get("/api/transactions")
@login_required
def list_transactions():
    uid = session["user_id"]
    rows = get_db().execute(
        TXN_SELECT + " WHERE t.sender_id = ? OR t.recipient_id = ? ORDER BY t.id DESC", (uid, uid)
    ).fetchall()
    return jsonify([row(r) for r in rows])


@app.get("/api/transactions/search")
@login_required
def search_transactions():
    uid = session["user_id"]
    q = request.args.get("q", "").strip()
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = get_db().execute(
        TXN_SELECT
        + " WHERE (t.sender_id = ? OR t.recipient_id = ?) AND t.memo LIKE ? ESCAPE '\\'"
        + " ORDER BY t.id DESC",
        (uid, uid, pattern),
    ).fetchall()
    return jsonify([row(r) for r in rows])


@app.get("/api/transactions/<int:txn_id>")
@login_required
def get_transaction(txn_id):
    uid = session["user_id"]
    r = get_db().execute(
        TXN_SELECT + " WHERE t.id = ? AND (t.sender_id = ? OR t.recipient_id = ?)",
        (txn_id, uid, uid),
    ).fetchone()
    if not r:
        return jsonify(error="Transaction not found"), 404
    return jsonify(row(r))


@app.post("/api/transactions")
@login_required
def send_money():
    data = request.get_json(silent=True) or {}
    try:
        recipient_id = int(data.get("recipient_id"))
        amount_cents = int(round(float(data.get("amount")) * 100))
    except (TypeError, ValueError):
        return jsonify(error="Enter a valid recipient and amount"), 400
    memo = str(data.get("memo", ""))[:200]
    uid = session["user_id"]
    db = get_db()
    if amount_cents <= 0:
        return jsonify(error="Amount must be greater than zero"), 400
    if recipient_id == uid or not db.execute("SELECT 1 FROM users WHERE id = ?", (recipient_id,)).fetchone():
        return jsonify(error="Pick a different recipient"), 400
    bal = db.execute("SELECT balance_cents FROM users WHERE id = ?", (uid,)).fetchone()[0]
    if bal < amount_cents:
        return jsonify(error="Not enough balance"), 400
    db.execute("UPDATE users SET balance_cents = balance_cents - ? WHERE id = ?", (amount_cents, uid))
    db.execute("UPDATE users SET balance_cents = balance_cents + ? WHERE id = ?", (amount_cents, recipient_id))
    cur = db.execute(
        "INSERT INTO transactions (sender_id, recipient_id, amount_cents, memo) VALUES (?,?,?,?)",
        (uid, recipient_id, amount_cents, memo),
    )
    db.commit()
    return jsonify(id=cur.lastrowid), 201


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)
