# usage.py
import sqlite3, datetime, os

DB_PATH = os.path.join(os.path.dirname(__file__), "db.sqlite")

# Limites par plan
PLAN_LIMITS = {
    "basic": 1200,      # 1200 messages / mois
    "pro": 5000,        # 5000 messages / mois
    "illimite": None,   # None = pas de limite
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Compteurs mensuels
    cur.execute("""
      CREATE TABLE IF NOT EXISTS usage (
        client_id   TEXT,
        month       TEXT,
        messages    INTEGER DEFAULT 0,
        tokens_used INTEGER DEFAULT 0,
        PRIMARY KEY (client_id, month)
      )
    """)

    # Tenants (plan + id Stripe)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS tenants (
        client_id TEXT PRIMARY KEY,
        plan      TEXT NOT NULL DEFAULT 'basic',
        stripe_customer_id TEXT
      )
    """)
    conn.commit()
    conn.close()

def _month_today():
    return datetime.date.today().strftime("%Y-%m")

# --------- USAGE ----------
def get_usage(client_id: str):
    month = _month_today()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT messages, tokens_used FROM usage WHERE client_id=? AND month=?",
        (client_id, month),
    )
    row = cur.fetchone()
    conn.close()
    return row or (0, 0)

def log_usage(client_id: str, tokens: int):
    month = _month_today()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO usage (client_id, month, messages, tokens_used)
      VALUES (?, ?, 1, ?)
      ON CONFLICT(client_id, month)
      DO UPDATE SET
        messages = messages + 1,
        tokens_used = tokens_used + excluded.tokens_used
    """, (client_id, month, tokens))
    conn.commit()
    conn.close()

# --------- PLANS ----------
def get_plan(client_id: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT plan FROM tenants WHERE client_id=?", (client_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else "basic"

def set_plan(client_id: str, plan: str):
    if plan not in PLAN_LIMITS:
        raise ValueError(f"Plan inconnu: {plan}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO tenants (client_id, plan)
      VALUES (?, ?)
      ON CONFLICT(client_id) DO UPDATE SET plan=excluded.plan
    """, (client_id, plan))
    conn.commit()
    conn.close()

def get_limit(client_id: str):
    """Renvoie la limite messages/mois pour ce client (None = illimité)."""
    plan = get_plan(client_id)
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["basic"])

# --------- STRIPE CUSTOMER ----------
def set_stripe_customer_id(client_id: str, customer_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO tenants (client_id, plan, stripe_customer_id)
      VALUES (?, COALESCE((SELECT plan FROM tenants WHERE client_id=?),'basic'), ?)
      ON CONFLICT(client_id) DO UPDATE SET stripe_customer_id=excluded.stripe_customer_id
    """, (client_id, client_id, customer_id))
    conn.commit()
    conn.close()

def get_stripe_customer_id(client_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT stripe_customer_id FROM tenants WHERE client_id=?", (client_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else None
