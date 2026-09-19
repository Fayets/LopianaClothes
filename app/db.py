"""SQLite local: esquema, conexión y helpers."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("LOPIANA_DB", DATA_DIR / "lopiana.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  category TEXT DEFAULT '',
  price REAL NOT NULL DEFAULT 0,
  transfer_price REAL,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS product_images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  thumb TEXT NOT NULL,
  original TEXT,
  width INTEGER, height INTEGER,
  position INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'gallery',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS product_colors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  hex TEXT NOT NULL DEFAULT '#000000',
  position INTEGER NOT NULL DEFAULT 0,
  UNIQUE(product_id, name)
);
CREATE TABLE IF NOT EXISTS product_sizes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  size TEXT NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0,
  position INTEGER NOT NULL DEFAULT 0,
  UNIQUE(product_id, size)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  product_id INTEGER,
  size TEXT,
  session_id TEXT,
  meta TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_events_type_date ON events(type, created_at);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,
  customer_name TEXT DEFAULT '',
  customer_phone TEXT DEFAULT '',
  note TEXT DEFAULT '',
  payment TEXT NOT NULL DEFAULT 'transferencia',
  status TEXT NOT NULL DEFAULT 'pendiente',
  subtotal REAL NOT NULL DEFAULT 0,
  total REAL NOT NULL DEFAULT 0,
  session_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER,
  product_name TEXT NOT NULL,
  size TEXT,
  color TEXT,
  qty INTEGER NOT NULL DEFAULT 1,
  unit_price REAL NOT NULL DEFAULT 0,
  list_price REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  expires_at TEXT NOT NULL,
  ip TEXT,
  user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS subscribers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  session_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS login_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ip TEXT NOT NULL,
  ok INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_login_ip_date ON login_attempts(ip, created_at);
CREATE TABLE IF NOT EXISTS stock_moves (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL,
  size TEXT,
  delta INTEGER NOT NULL,
  reason TEXT NOT NULL,
  order_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

DEFAULT_SETTINGS = {
    "brand_name": "Lopiana Clothes",
    "whatsapp_number": "5491154845533",
    "whatsapp_greeting": "Hola Lopiana! Quiero hacer este pedido:",
    "transfer_discount_pct": "30",
    "banner_text": "ENVÍOS GRATIS A CABA · DESCUENTO ABONANDO EN EFECTIVO O TRANSFERENCIA · ENVÍOS A TODO EL PAÍS",
    "address": "Gran Galería Devoto · Local 55, Villa Devoto, CABA",
    "instagram": "lopiana.clothes",
    "email": "caritomuller77@hotmail.com",
    "image_width": "1200",
    "image_height": "1600",
    "image_mode": "cover",
    "size_chart_note": "Medidas tomadas sobre la prenda apoyada, en centímetros. Ante la duda escribinos y te ayudamos a elegir.",
}


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 8000")  # dos pedidos a la vez no se pisan
    con.execute("PRAGMA synchronous = NORMAL")
    return con


def _migrate(con) -> None:
    """Agrega columnas nuevas sobre bases ya creadas (no hay downgrade)."""
    def cols(table: str) -> set:
        return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}

    if "kind" not in cols("product_images"):
        con.execute("ALTER TABLE product_images ADD COLUMN kind TEXT NOT NULL DEFAULT 'gallery'")
    if "color" not in cols("order_items"):
        con.execute("ALTER TABLE order_items ADD COLUMN color TEXT")
    # el PIN dejó de guardarse en claro: si quedaba uno viejo, se hashea y se borra
    old = con.execute("SELECT value FROM settings WHERE key = 'admin_pin'").fetchone()
    if old:
        from .security import hash_pin
        con.execute(
            "INSERT INTO settings(key, value) VALUES ('admin_pin_hash', ?) ON CONFLICT(key) DO NOTHING",
            (hash_pin(old["value"]),),
        )
        con.execute(
            "INSERT INTO settings(key, value) VALUES ('pin_is_default', ?) ON CONFLICT(key) DO NOTHING",
            ("1" if old["value"].strip() in ("1234", "0000") else "0",),
        )
        con.execute("DELETE FROM settings WHERE key = 'admin_pin'")


def init_db() -> None:
    con = connect()
    with con:
        con.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        _migrate(con)
        _init_pin(con)
        # limpieza de lo que caduca
        con.execute("DELETE FROM sessions WHERE expires_at < datetime('now','localtime')")
        con.execute("DELETE FROM login_attempts WHERE created_at < datetime('now','localtime','-1 day')")
    con.close()


def _init_pin(con) -> None:
    """El PIN inicial sale de LOPIANA_ADMIN_PIN. Sin variable, queda '1234' marcado como
    provisorio: el panel obliga a cambiarlo antes de dejar entrar."""
    from .security import hash_pin
    if con.execute("SELECT 1 FROM settings WHERE key = 'admin_pin_hash'").fetchone():
        return
    env_pin = os.environ.get("LOPIANA_ADMIN_PIN", "").strip()
    pin = env_pin or "1234"
    con.execute("INSERT INTO settings(key, value) VALUES ('admin_pin_hash', ?)", (hash_pin(pin),))
    con.execute("INSERT INTO settings(key, value) VALUES ('pin_is_default', ?)", ("0" if env_pin else "1",))


@contextmanager
def get_db():
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def get_settings(con) -> dict:
    return {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM settings")}


def set_setting(con, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]
