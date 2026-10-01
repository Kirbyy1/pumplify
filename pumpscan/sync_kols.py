"""Download every KOL list into data/kols.db so lookups never hit those sites.

    python sync_kols.py              # every source that has its API key set
    python sync_kols.py kolscan      # just one source

API keys come from the environment or pumpscan/.env (see .env.example).
A source that fails keeps its previous rows; the others still update.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from kol_sources import SOURCES

HERE = Path(__file__).parent
DB = HERE / "data" / "kols.db"
FIELDS = ("name", "x", "telegram", "avatar", "pnl", "wins", "losses", "timeframe", "url")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kol_wallets (
    address   TEXT NOT NULL,
    source    TEXT NOT NULL,
    name      TEXT NOT NULL,
    x         TEXT,
    telegram  TEXT,
    avatar    TEXT,
    pnl       REAL,
    wins      INTEGER,
    losses    INTEGER,
    timeframe INTEGER,
    url       TEXT,
    synced_at INTEGER NOT NULL,
    PRIMARY KEY (address, source)
);
CREATE INDEX IF NOT EXISTS kol_wallets_name ON kol_wallets (name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS kol_wallets_x ON kol_wallets (x COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS sync_log (
    source TEXT PRIMARY KEY, synced_at INTEGER, count INTEGER, error TEXT
);
"""


def load_env() -> None:
    env = HERE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, val = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), val.strip().strip('"\''))


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    return conn


def sync_source(conn: sqlite3.Connection, name: str) -> str:
    fetch, key_env = SOURCES[name]
    if key_env and not os.environ.get(key_env):
        return f"{name}: skipped (set {key_env})"
    now = int(time.time())
    try:
        rows = fetch()
        if not rows:
            raise RuntimeError("returned no wallets; format may have changed")
    except Exception as exc:
        conn.execute("INSERT OR REPLACE INTO sync_log VALUES (?, ?, ?, ?)",
                     (name, now, None, f"{type(exc).__name__}: {exc}"))
        conn.commit()
        return f"{name}: FAILED ({type(exc).__name__}: {exc}); kept previous data"

    with conn:  # swap this source's rows atomically
        conn.execute("DELETE FROM kol_wallets WHERE source = ?", (name,))
        conn.executemany(
            f"INSERT OR REPLACE INTO kol_wallets (address, source, {', '.join(FIELDS)}, synced_at)"
            f" VALUES (?, ?, {', '.join('?' * len(FIELDS))}, ?)",
            [(r["address"], name, *(r.get(f) for f in FIELDS), now) for r in rows],
        )
        conn.execute("INSERT OR REPLACE INTO sync_log VALUES (?, ?, ?, NULL)", (name, now, len(rows)))
    return f"{name}: {len(rows)} wallets"


def migrate_kolscan_json(conn: sqlite3.Connection) -> None:
    """One-off import of the earlier data/kolscan.json snapshot."""
    old = HERE / "data" / "kolscan.json"
    if not old.exists() or conn.execute("SELECT 1 FROM kol_wallets LIMIT 1").fetchone():
        return
    data = json.loads(old.read_text(encoding="utf-8"))
    with conn:
        for addr, k in data["wallets"].items():
            conn.execute(
                f"INSERT OR IGNORE INTO kol_wallets (address, source, {', '.join(FIELDS)}, synced_at)"
                f" VALUES (?, 'kolscan', {', '.join('?' * len(FIELDS))}, ?)",
                (addr, k["name"], k.get("x"), k.get("telegram"), k.get("avatar"), k.get("profit"),
                 k.get("wins"), k.get("losses"), k.get("timeframe"),
                 f"https://kolscan.io/account/{addr}", data.get("synced_at", 0)),
            )


def sync(names: list[str] | None = None) -> list[str]:
    load_env()
    conn = connect()
    try:
        migrate_kolscan_json(conn)
        return [sync_source(conn, n) for n in (names or SOURCES)]
    finally:
        conn.close()


if __name__ == "__main__":
    unknown = [n for n in sys.argv[1:] if n not in SOURCES]
    if unknown:
        sys.exit(f"unknown source(s): {unknown}; choose from {list(SOURCES)}")
    for line in sync(sys.argv[1:] or None):
        print(line)
    conn = sqlite3.connect(DB)
    total = conn.execute("SELECT COUNT(DISTINCT address) FROM kol_wallets").fetchone()[0]
    print(f"total unique KOL wallets: {total}")
