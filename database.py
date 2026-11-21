import sqlite3
import hashlib
import os
import pandas as pd

DB_NAME = "living_money.db"


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def _norm_user(username: str | None) -> str:
    clean = (username or "default").strip().lower()
    return clean if clean else "default"


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(r[1]) for r in rows]


def _migrate_old_schema(conn: sqlite3.Connection) -> None:
    """Automatically upgrades old single-user tables to per-user schema if needed."""
    prof_cols = _table_columns(conn, "profile")
    if prof_cols and "username" not in prof_cols:
        conn.execute("ALTER TABLE profile RENAME TO profile_old")
        conn.execute("""
            CREATE TABLE profile (
                username TEXT PRIMARY KEY,
                monthly_income REAL DEFAULT 60000,
                fixed_costs REAL DEFAULT 25000,
                emergency_fund REAL DEFAULT 50000,
                emergency_target REAL DEFAULT 150000
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO profile (username, monthly_income, fixed_costs, emergency_fund, emergency_target)
            SELECT 'default', monthly_income, fixed_costs, emergency_fund, emergency_target
            FROM profile_old LIMIT 1
        """)
        conn.execute("DROP TABLE profile_old")

    goal_cols = _table_columns(conn, "goals")
    if goal_cols and "username" not in goal_cols:
        conn.execute("ALTER TABLE goals ADD COLUMN username TEXT NOT NULL DEFAULT 'default'")

    tx_cols = _table_columns(conn, "transactions")
    if tx_cols and "username" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN username TEXT NOT NULL DEFAULT 'default'")

    rule_cols = _table_columns(conn, "rules")
    if rule_cols and "username" not in rule_cols:
        conn.execute("ALTER TABLE rules RENAME TO rules_old")
        conn.execute("""
            CREATE TABLE rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT 'default',
                merchant_keyword TEXT NOT NULL,
                category TEXT NOT NULL,
                UNIQUE(username, merchant_keyword)
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO rules (username, merchant_keyword, category)
            SELECT 'default', merchant_keyword, category FROM rules_old
        """)
        conn.execute("DROP TABLE rules_old")


def init_db() -> None:
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            username TEXT PRIMARY KEY,
            monthly_income REAL DEFAULT 60000,
            fixed_costs REAL DEFAULT 25000,
            emergency_fund REAL DEFAULT 50000,
            emergency_target REAL DEFAULT 150000
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL,
            target_amount REAL NOT NULL,
            saved_amount REAL DEFAULT 0,
            target_date TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL DEFAULT 'default',
            date TEXT NOT NULL,
            merchant TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            source TEXT DEFAULT 'manual'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL DEFAULT 'default',
            merchant_keyword TEXT NOT NULL,
            category TEXT NOT NULL,
            UNIQUE(username, merchant_keyword)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)

    _migrate_old_schema(conn)
    conn.commit()
    conn.close()


def ensure_user_profile(username: str) -> None:
    user = _norm_user(username)
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO profile (username) VALUES (?)", (user,))
    conn.commit()
    conn.close()


def get_profile(username: str = "default") -> dict:
    user = _norm_user(username)
    ensure_user_profile(user)
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM profile WHERE username = ?", conn, params=(user,))
    conn.close()
    if df.empty:
        return {
            "username": user,
            "monthly_income": 60000.0,
            "fixed_costs": 25000.0,
            "emergency_fund": 50000.0,
            "emergency_target": 150000.0,
        }
    return df.iloc[0].to_dict()


def update_profile(
    username: str,
    income: float,
    fixed_costs: float,
    emergency_fund: float,
    emergency_target: float,
) -> None:
    user = _norm_user(username)
    ensure_user_profile(user)
    conn = get_conn()
    conn.execute(
        """
        UPDATE profile
        SET monthly_income = ?, fixed_costs = ?, emergency_fund = ?, emergency_target = ?
        WHERE username = ?
        """,
        (income, fixed_costs, emergency_fund, emergency_target, user),
    )
    conn.commit()
    conn.close()


def get_goals(username: str = "default") -> pd.DataFrame:
    user = _norm_user(username)
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM goals WHERE username = ? ORDER BY id DESC", conn, params=(user,))
    conn.close()
    return df


def add_goal(
    username: str,
    name: str,
    target_amount: float,
    saved_amount: float,
    target_date: str,
) -> None:
    user = _norm_user(username)
    conn = get_conn()
    conn.execute(
        "INSERT INTO goals (username, name, target_amount, saved_amount, target_date) VALUES (?, ?, ?, ?, ?)",
        (user, name, target_amount, saved_amount, target_date),
    )
    conn.commit()
    conn.close()


def update_goal_saved(goal_id: int, new_saved_amount: float, username: str | None = None) -> None:
    conn = get_conn()
    val = max(float(new_saved_amount), 0.0)
    if username:
        conn.execute(
            "UPDATE goals SET saved_amount = ? WHERE id = ? AND username = ?",
            (val, goal_id, _norm_user(username)),
        )
    else:
        conn.execute("UPDATE goals SET saved_amount = ? WHERE id = ?", (val, goal_id))
    conn.commit()
    conn.close()


def delete_goal(goal_id: int, username: str | None = None) -> None:
    conn = get_conn()
    if username:
        conn.execute(
            "DELETE FROM goals WHERE id = ? AND username = ?",
            (goal_id, _norm_user(username)),
        )
    else:
        conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    conn.commit()
    conn.close()


def get_transactions(username: str = "default") -> pd.DataFrame:
    user = _norm_user(username)
    conn = get_conn()
    df = pd.read_sql(
        "SELECT * FROM transactions WHERE username = ? ORDER BY date DESC, id DESC",
        conn,
        params=(user,),
    )
    conn.close()
    return df


def add_transactions(tx_list: list[dict], username: str = "default") -> None:
    user = _norm_user(username)
    if not tx_list:
        return
    conn = get_conn()
    conn.executemany(
        "INSERT INTO transactions (username, date, merchant, amount, category, source) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                user,
                t["date"],
                t["merchant"],
                float(t["amount"]),
                t["category"],
                t.get("source", "upload"),
            )
            for t in tx_list
        ],
    )
    conn.commit()
    conn.close()


def update_transaction_category(tx_id: int, new_category: str, username: str | None = None) -> None:
    conn = get_conn()
    if username:
        conn.execute(
            "UPDATE transactions SET category = ? WHERE id = ? AND username = ?",
            (new_category, tx_id, _norm_user(username)),
        )
    else:
        conn.execute(
            "UPDATE transactions SET category = ? WHERE id = ?",
            (new_category, tx_id),
        )
    conn.commit()
    conn.close()


def get_rules(username: str = "default") -> dict[str, str]:
    user = _norm_user(username)
    conn = get_conn()
    df = pd.read_sql(
        "SELECT merchant_keyword, category FROM rules WHERE username = ?",
        conn,
        params=(user,),
    )
    conn.close()
    if df.empty:
        return {}
    return dict(zip(df["merchant_keyword"].str.upper(), df["category"]))


def save_rule(merchant_keyword: str, category: str, username: str = "default") -> None:
    user = _norm_user(username)
    keyword = merchant_keyword.strip().upper()
    if not keyword:
        return
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO rules (username, merchant_keyword, category) VALUES (?, ?, ?)
        ON CONFLICT(username, merchant_keyword) DO UPDATE SET category = excluded.category
        """,
        (user, keyword, category),
    )
    conn.commit()
    conn.close()


def _hash_password(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = os.urandom(16).hex()
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
    return f"{salt}:{pwd_hash}"


def _verify_password(password: str, stored_hash: str) -> bool:
    salt, _ = stored_hash.split(":")
    return _hash_password(password, salt) == stored_hash


def register_user(username: str, password: str) -> tuple[bool, str]:
    user = _norm_user(username)
    if not user or not password:
        return False, "Username and password cannot be empty."
    if len(password) < 4:
        return False, "Password must be at least 4 characters."
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (user, _hash_password(password)),
        )
        conn.commit()
        ensure_user_profile(user)
        return True, "Account created! You can now log in."
    except sqlite3.IntegrityError:
        return False, "Username already exists. Try another one."
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> bool:
    user = _norm_user(username)
    conn = get_conn()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username = ?",
        (user,),
    ).fetchone()
    conn.close()
    if row and _verify_password(password, row[0]):
        ensure_user_profile(user)
        return True
    return False