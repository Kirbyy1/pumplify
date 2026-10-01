"""Fetchers for public KOL wallet lists.

Each fetcher returns a list of dicts with at least `address` and `name`, plus
any of: x, telegram, avatar, pnl, wins, losses, timeframe, url.
Fetchers that need an API key read it from the environment and are skipped
(by sync_kols.py) when it isn't set.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (pumpscan)"}
TIMEOUT = 20


def x_handle(value: str | None) -> str | None:
    """Normalise 'https://x.com/foo', '@foo' or 'foo' to 'foo'."""
    if not value:
        return None
    m = re.search(r"(?:x|twitter)\.com/@?([A-Za-z0-9_]{1,15})", value)
    if m:
        return m.group(1)
    m = re.fullmatch(r"@?([A-Za-z0-9_]{1,15})", value.strip())
    return m.group(1) if m else None


# --- kolscan.io ---------------------------------------------------------------
# No public API (its /api/* rejects non-browser clients). The leaderboard page
# embeds the full KOL roster in Next.js flight chunks, split at arbitrary
# byte boundaries; decode and join them, then pull out each wallet object.

_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_OBJ_RE = re.compile(r'\{"wallet_address":')


def kolscan() -> list[dict]:
    r = requests.get("https://kolscan.io/leaderboard", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    text = "".join(json.loads(m.group(1)) for m in _CHUNK_RE.finditer(r.text))
    decoder = json.JSONDecoder()
    merged: dict[str, dict] = {}
    for m in _OBJ_RE.finditer(text):
        try:
            obj, _ = decoder.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        addr, name = obj.get("wallet_address"), obj.get("name")
        if not addr or not name:
            continue
        e = merged.setdefault(addr, {
            "address": addr, "name": name, "url": f"https://kolscan.io/account/{addr}",
        })
        # Same KOL shows up per timeframe; keep the first value of each field,
        # but prefer 30-day stats when they exist.
        for key, val in (("x", x_handle(obj.get("twitter"))),
                         ("telegram", obj.get("telegram")),
                         ("avatar", obj.get("pfp"))):
            if val and not e.get(key):
                e[key] = val
        if "profit" in obj and (obj.get("timeframe") == 30 or "pnl" not in e):
            e.update(pnl=obj["profit"], wins=obj.get("wins"),
                     losses=obj.get("losses"), timeframe=obj.get("timeframe"))
    return list(merged.values())


# --- MadeOnSol (https://madeonsol.com/pricing — free key, 200 calls/day) -------
# The leaderboard caps at 100 rows and has no paging, so sweep every
# period x strategy x sort combination (75 calls) to cover the roster.

MADEONSOL_KEY = "MADEONSOL_API_KEY"


def madeonsol() -> list[dict]:
    key = os.environ[MADEONSOL_KEY]
    headers = {**UA, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    periods = ["today", "7d", "30d", "90d", "180d"]
    strategies = ["scalper", "day_trader", "swing_trader", "hodler", "mixed"]
    sorts = ["pnl", "winrate", "volume"]
    merged: dict[str, dict] = {}
    for period, strategy, sort in itertools.product(periods, strategies, sorts):
        r = requests.get(
            "https://madeonsol.com/api/v1/kol/leaderboard",
            params={"period": period, "strategy": strategy, "sort": sort, "limit": 100},
            headers=headers, timeout=TIMEOUT,
        )
        if r.status_code == 429:
            break  # daily quota used up; keep what we have
        r.raise_for_status()
        for row in r.json().get("leaderboard", []):
            addr = row.get("wallet")
            if not addr or not row.get("name") or addr in merged:
                continue
            merged[addr] = {
                "address": addr,
                "name": row["name"],
                "pnl": row.get("pnl") if period == "30d" else None,
                "timeframe": 30 if period == "30d" else None,
            }
        time.sleep(0.3)
    return list(merged.values())


# --- Solana Tracker (https://www.solanatracker.io — free key, 2.5k req/month) ---

SOLANATRACKER_KEY = "SOLANATRACKER_API_KEY"


def solanatracker() -> list[dict]:
    key = os.environ[SOLANATRACKER_KEY]
    r = requests.get(
        "https://data.solanatracker.io/v2/pnl/leaderboard/kols",
        params={"sort": "total", "direction": "desc", "limit": 1000},
        headers={**UA, "x-api-key": key}, timeout=TIMEOUT,
    )
    r.raise_for_status()
    out = []
    for t in r.json().get("traders", []):
        # Field name for the address isn't pinned down in their docs.
        addr = t.get("wallet") or t.get("address") or t.get("owner")
        if not addr or not t.get("name"):
            continue
        pnl = t.get("pnl") or {}
        out.append({
            "address": addr,
            "name": t["name"],
            "x": x_handle(t.get("twitter")),
            "pnl": pnl.get("total") if isinstance(pnl, dict) else None,
        })
    return out


# name -> (fetcher, env var holding its API key or None)
SOURCES = {
    "kolscan": (kolscan, None),
    "MadeOnSol": (madeonsol, MADEONSOL_KEY),
    "Solana Tracker": (solanatracker, SOLANATRACKER_KEY),
}
