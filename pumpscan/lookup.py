"""Wallet ownership lookup across Solana, Ethereum and BNB Chain.

Every signal comes from a public source: pump.fun profiles, on-chain naming
services (SNS / ENS / SPACE ID), a local list of known entity labels, a
local snapshot of public KOL lists (kolscan, MadeOnSol, Solana Tracker) and a
local snapshot of Fomo profiles with their bound wallets.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import base58
import requests

PUMP_API = "https://frontend-api-v3.pump.fun"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
EVM_RPCS = {
    "ethereum": "https://ethereum-rpc.publicnode.com",
    "bnb": "https://bsc-dataseed.binance.org",
}
EXPLORERS = {
    "solana": "https://solscan.io/account/{}",
    "ethereum": "https://etherscan.io/address/{}",
    "bnb": "https://bscscan.com/address/{}",
}
NATIVE = {"solana": ("SOL", 9), "ethereum": ("ETH", 18), "bnb": ("BNB", 18)}

TIMEOUT = 8
CACHE_TTL = 60
HEADERS = {"User-Agent": "pumpscan/1.0", "Accept": "application/json"}

EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
B58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

LABELS = {
    k.lower() if k.startswith("0x") else k: v
    for k, v in json.loads((Path(__file__).parent / "labels.json").read_text()).items()
}

_session = requests.Session()
_session.headers.update(HEADERS)
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


class AddressError(ValueError):
    pass


def detect_chains(address: str, chain: str = "auto") -> list[str]:
    if EVM_RE.match(address):
        family = ["ethereum", "bnb"]
    elif B58_RE.match(address):
        try:
            if len(base58.b58decode(address)) != 32:
                raise ValueError
        except ValueError:
            raise AddressError("That doesn't look like a valid Solana address.")
        family = ["solana"]
    else:
        raise AddressError("Paste a Solana (base58) or EVM (0x…) wallet address.")

    if chain == "auto":
        return family
    if chain not in family:
        raise AddressError(f"Address format doesn't match the {chain} network.")
    return [chain]


def _get(url: str, **kw):
    r = _session.get(url, timeout=TIMEOUT, **kw)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _rpc(url: str, method: str, params: list):
    r = _session.post(
        url, timeout=TIMEOUT, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )
    r.raise_for_status()
    return r.json().get("result")


# --- identity sources -------------------------------------------------------

def pump_profile(address: str) -> dict | None:
    data = _get(f"{PUMP_API}/users/{address}")
    if not data or not data.get("username"):
        return None
    return {
        "source": "pump.fun profile",
        "name": data["username"],
        "x": data.get("x_username"),
        "bio": data.get("bio"),
        "avatar": data.get("profile_image"),
        "followers": data.get("followers", 0),
        "following": data.get("following", 0),
        "banned": data.get("is_banned", False),
        "url": f"https://pump.fun/profile/{address}",
    }


def pump_coins(address: str) -> list[dict]:
    data = _get(
        f"{PUMP_API}/coins",
        params={"creator": address, "limit": 12, "offset": 0, "includeNsfw": "false"},
    )
    return [
        {
            "mint": c.get("mint"),
            "name": c.get("name"),
            "symbol": c.get("symbol"),
            "image": c.get("image_uri"),
            "market_cap": c.get("usd_market_cap"),
            "created": c.get("created_timestamp"),
            "complete": c.get("complete", False),
        }
        for c in (data or [])
        if isinstance(c, dict)
    ]


def sns_domain(address: str) -> dict | None:
    data = _get(f"https://sdk-proxy.sns.id/favorite-domain/{address}")
    # The proxy answers 200 with {"s": "error"} when no favourite is set.
    if not data or data.get("s") != "ok" or not isinstance(data.get("result"), dict):
        return None
    result = data["result"]
    name = result.get("reverse")
    if not name or result.get("stale"):
        # A stale favourite means the domain moved to another owner.
        return None
    return {"source": "Solana Name Service", "name": f"{name}.sol", "url": f"https://www.sns.id/domain?domain={name}"}


def ens_name(address: str) -> dict | None:
    data = _get(f"https://api.ensdata.net/{address}")
    name = (data or {}).get("ens_primary") or (data or {}).get("ens")
    if not name:
        return None
    return {
        "source": "ENS",
        "name": name,
        "x": data.get("twitter"),
        "github": data.get("github"),
        "website": data.get("url"),
        "bio": data.get("description"),
        "avatar": data.get("avatar_small") or data.get("avatar_url"),
        "url": f"https://app.ens.domains/{name}",
    }


def bnb_name(address: str) -> dict | None:
    data = _get("https://api.prd.space.id/v1/getName", params={"tld": "bnb", "address": address})
    name = (data or {}).get("name")
    if not name:
        return None
    return {"source": "SPACE ID", "name": name, "url": f"https://space.id/name/{name}"}


FOMO_DB = Path(os.environ.get(
    "PUMPSCAN_FOMO_DB", Path(__file__).parent / "data" / "fomo_wallets.db"
))
_fomo: tuple[float, dict[str, dict], dict[str, dict]] = (-1.0, {}, {})
_fomo_lock = threading.Lock()


def addr_key(address: str) -> str:
    return address.lower() if address.startswith("0x") else address


def _fomo_index() -> tuple[dict[str, dict], dict[str, dict]]:
    """(address -> user, lowercase handle -> user), reloaded when the DB changes.

    `addresses.address` has no index, so per-request SQL would full-scan;
    52k rows fit comfortably in memory instead.
    """
    global _fomo
    try:
        mtime = FOMO_DB.stat().st_mtime
    except OSError:
        return {}, {}
    if mtime == _fomo[0]:
        return _fomo[1], _fomo[2]
    with _fomo_lock:
        if mtime == _fomo[0]:
            return _fomo[1], _fomo[2]
        conn = sqlite3.connect(f"file:{FOMO_DB}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT u.user_id, a.address, a.chain, u.handle, u.display_name,"
                " u.followers, u.following, u.trades, u.last_seen"
                " FROM addresses a JOIN users u USING (user_id)"
            ).fetchall()
        finally:
            conn.close()
        users: dict[str, dict] = {}
        by_addr: dict[str, dict] = {}
        for uid, addr, chain, handle, display, followers, following, trades, last_seen in rows:
            user = users.setdefault(uid, {
                "handle": handle,
                "display_name": display,
                "followers": followers,
                "following": following,
                "trades": trades,
                "last_seen": last_seen,
                "wallets": [],
            })
            user["wallets"].append({"address": addr, "chain": chain})
            by_addr[addr_key(addr)] = user
        by_handle = {u["handle"].lower(): u for u in users.values() if u["handle"]}
        _fomo = (mtime, by_addr, by_handle)
        return by_addr, by_handle


def fomo_profile(address: str) -> dict | None:
    user = _fomo_index()[0].get(addr_key(address))
    if not user or not user["handle"]:
        return None
    display = user["display_name"]
    return {
        "source": "Fomo",
        "name": user["handle"],
        "display_name": display if display and display != user["handle"] else None,
        "followers": user["followers"] or 0,
        "following": user["following"] or 0,
        "trades": user["trades"],
        "last_seen": user["last_seen"],
        "other_wallets": [w for w in user["wallets"] if addr_key(w["address"]) != addr_key(address)],
    }


# --- KOL lists (kolscan, MadeOnSol, Solana Tracker) ---------------------------
# sync_kols.py downloads every list into data/kols.db; lookups only read that.

KOL_DB = Path(__file__).parent / "data" / "kols.db"
KOL_MAX_AGE = 24 * 3600
_kols: tuple[float, dict[str, dict], dict[str, list[str]]] = (-1.0, {}, {})
_kol_lock = threading.Lock()
_kol_syncing = threading.Event()


def _refresh_kols_async() -> None:
    if _kol_syncing.is_set():
        return
    _kol_syncing.set()

    def run():
        try:
            import sync_kols
            sync_kols.sync()
        except Exception:
            pass  # keep serving the previous snapshot
        finally:
            _kol_syncing.clear()

    threading.Thread(target=run, daemon=True).start()


def _load_kols() -> tuple[dict[str, dict], dict[str, list[str]], int]:
    conn = sqlite3.connect(f"file:{KOL_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM kol_wallets ORDER BY source = 'kolscan' DESC, source"
        ).fetchall()
        oldest = conn.execute("SELECT MIN(synced_at) FROM sync_log WHERE error IS NULL").fetchone()[0]
    finally:
        conn.close()
    by_addr: dict[str, dict] = {}
    for r in rows:
        # kolscan rows come first, so its name/stats win; others fill gaps.
        kol = by_addr.setdefault(r["address"], {"name": r["name"], "lists": []})
        kol["lists"].append(r["source"])
        for f in ("x", "telegram", "avatar", "url"):
            if r[f] and not kol.get(f):
                kol[f] = r[f]
        if r["pnl"] is not None and "pnl" not in kol:
            kol.update(pnl=r["pnl"], wins=r["wins"], losses=r["losses"],
                       timeframe=r["timeframe"], pnl_source=r["source"])
    by_name: dict[str, list[str]] = {}
    for addr, kol in by_addr.items():
        for key in {kol["name"].lower(), (kol.get("x") or "").lower()} - {""}:
            by_name.setdefault(key, []).append(addr)
    return by_addr, by_name, oldest or 0


def _kol_index() -> tuple[dict[str, dict], dict[str, list[str]]]:
    """(address -> merged KOL, lowercase name/X handle -> addresses)."""
    global _kols
    try:
        mtime = KOL_DB.stat().st_mtime
    except OSError:
        _refresh_kols_async()
        return {}, {}
    if mtime != _kols[0]:
        with _kol_lock:
            if mtime != _kols[0]:
                by_addr, by_name, oldest = _load_kols()
                _kols = (mtime, by_addr, by_name)
                if time.time() - oldest > KOL_MAX_AGE:
                    _refresh_kols_async()
    return _kols[1], _kols[2]


def kol_profile(address: str) -> dict | None:
    kol = _kol_index()[0].get(address)
    if not kol:
        return None
    return {
        "source": " + ".join(kol["lists"]),
        "name": kol["name"],
        "lists": kol["lists"],
        "x": kol.get("x"),
        "telegram": kol.get("telegram"),
        "avatar": kol.get("avatar"),
        "pnl": kol.get("pnl"),
        "wins": kol.get("wins"),
        "losses": kol.get("losses"),
        "timeframe": kol.get("timeframe"),
        "kind": "KOL",
        "url": kol.get("url"),
    }


def known_label(address: str) -> dict | None:
    label = LABELS.get(addr_key(address))
    if not label:
        return None
    return {"source": "Known entity", "name": label["name"], "kind": label.get("kind")}


def native_balance(chain: str, address: str) -> dict:
    symbol, decimals = NATIVE[chain]
    if chain == "solana":
        raw = (_rpc(SOLANA_RPC, "getBalance", [address]) or {}).get("value", 0)
    else:
        raw = int(_rpc(EVM_RPCS[chain], "eth_getBalance", [address, "latest"]) or "0x0", 16)
    amount = raw / 10**decimals
    price = usd_prices().get(chain)
    return {
        "chain": chain,
        "symbol": symbol,
        "amount": amount,
        "usd": amount * price if price else None,
    }


_prices: tuple[float, dict] = (0.0, {})
COINGECKO_IDS = {"solana": "solana", "ethereum": "ethereum", "bnb": "binancecoin"}


def usd_prices() -> dict[str, float]:
    global _prices
    if time.time() - _prices[0] < 300:
        return _prices[1]
    try:
        data = _get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(COINGECKO_IDS.values()), "vs_currencies": "usd"},
        ) or {}
        prices = {c: data[g]["usd"] for c, g in COINGECKO_IDS.items() if g in data}
    except Exception:
        return _prices[1]  # stale prices beat none
    _prices = (time.time(), prices)
    return prices


# --- aggregate --------------------------------------------------------------

# --- name -> address ---------------------------------------------------------

NAME_RE = re.compile(r"^[^\x00-\x1f/?#]{1,100}$")
DOMAIN_RE = re.compile(r"^[^\s.]+(\.(eth|sol|bnb))?$")
TLD_CHAIN = {"eth": "ethereum", "sol": "solana", "bnb": "bnb"}
MAX_MATCHES = 12


def resolve_ens(name: str) -> str | None:
    return (_get(f"https://api.ensdata.net/{name}") or {}).get("address")


def resolve_sns(name: str) -> str | None:
    data = _get(f"https://sdk-proxy.sns.id/resolve/{name.removesuffix('.sol')}") or {}
    return data.get("result") if data.get("s") == "ok" else None


def resolve_bnb(name: str) -> str | None:
    data = _get("https://api.prd.space.id/v1/getAddress", params={"tld": "bnb", "domain": name}) or {}
    addr = data.get("address")
    return addr if addr and int(addr, 16) else None  # unregistered names resolve to 0x0


RESOLVERS = {"eth": resolve_ens, "sol": resolve_sns, "bnb": resolve_bnb}


def _domain_matches(name: str) -> list[dict]:
    """Resolve `name.tld`, or try a bare name against every naming service."""
    if not DOMAIN_RE.match(name):
        return []
    stem, _, tld = name.rpartition(".")
    candidates = [name] if stem else [f"{name}.{t}" for t in RESOLVERS]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {c: pool.submit(_safe, RESOLVERS[c.rsplit(".", 1)[1]], c) for c in candidates}
    matches = []
    for cand, fut in futures.items():
        res = fut.result()
        if res["ok"] and res["data"]:
            tld = cand.rsplit(".", 1)[1]
            via = {"eth": "ENS", "sol": "SNS", "bnb": "SPACE ID"}[tld]
            matches.append({"label": cand, "via": via, "address": res["data"], "chain": TLD_CHAIN[tld]})
    return matches


def _kol_matches(name: str) -> list[dict]:
    by_addr, by_name = _kol_index()
    addrs = by_name.get(name) or ([
        a for key, lst in by_name.items() if key.startswith(name) for a in lst
    ] if len(name) >= 3 else [])
    out = []
    for addr in dict.fromkeys(addrs):
        kol = by_addr[addr]
        out.append({
            "label": kol["name"],
            "via": " + ".join(kol["lists"]),
            "detail": f"@{kol['x']}" if kol.get("x") else None,
            "avatar": kol.get("avatar"),
            "address": addr,
            "chain": "solana",
        })
    return out


def _fomo_matches(name: str) -> list[dict]:
    _, by_handle = _fomo_index()
    users = [by_handle[name]] if name in by_handle else ([
        u for key, u in by_handle.items() if key.startswith(name)
    ][:MAX_MATCHES] if len(name) >= 3 else [])
    return [
        {
            "label": u["handle"],
            "via": "Fomo",
            "detail": f"{u['followers'] or 0:,} followers",
            "address": w["address"],
            "chain": "solana" if w["chain"] == "solana" else "evm",
        }
        for u in users
        for w in u["wallets"]
    ]


def resolve_name(query: str) -> list[dict]:
    """Every wallet a name points at: naming services, KOL lists, Fomo handles.

    Local sources match exactly (case-insensitive, leading @ ignored); only if
    nothing matches exactly do we fall back to prefix matches.
    """
    name = query.strip().lstrip("@").lower()
    if not NAME_RE.match(name):
        raise AddressError("That isn't a wallet address or a name we can look up.")

    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(_safe, fn, name) for fn in (_domain_matches, _kol_matches, _fomo_matches)]
    matches, seen = [], set()
    for job in jobs:
        res = job.result()
        for m in (res["data"] or []) if res["ok"] else []:
            key = (addr_key(m["address"]), m["via"])
            if key not in seen:
                seen.add(key)
                matches.append(m)
    return matches[:MAX_MATCHES * 2]


def search(query: str, chain: str = "auto") -> dict:
    """Entry point for the search box: an address, or a name to resolve first."""
    query = query.strip()
    if EVM_RE.match(query) or B58_RE.match(query):
        return lookup(query, chain)

    matches = resolve_name(query)
    if not matches:
        raise AddressError(
            f"Nothing found for “{query}” on ENS, SNS, SPACE ID, the KOL lists or Fomo."
        )
    if len({addr_key(m["address"]) for m in matches}) > 1:
        return {"query": query, "matches": matches}
    m = matches[0]
    scope = m["chain"] if m["chain"] in ("solana", "bnb") else "auto"
    result = dict(lookup(m["address"], scope))
    result["resolved_from"] = {"label": m["label"], "via": m["via"]}
    return result


# How much each source on its own says about ownership. Labels are curated;
# KOL-list wallets are ones KOLs publicise; Fomo wallets are bound to the
# profile by the app; naming services need the owner to opt in; pump.fun
# names are auto-generated unless the user links an X account.
SOURCE_WEIGHT = {"label": 90, "kol": 75, "fomo": 65, "ens": 55, "sns": 50, "spaceid": 45, "pump": 30}


def confidence_score(hits: list[dict]) -> int:
    score = 0.0
    for h in hits:
        w = min(95, SOURCE_WEIGHT[h["key"]] + (25 if h.get("x") else 0))
        score += (100 - score) * w / 100  # each extra source closes part of the gap
    return round(score)


def _safe(fn, *args):
    try:
        return {"ok": True, "data": fn(*args)}
    except Exception as exc:  # one flaky source shouldn't sink the lookup
        return {"ok": False, "error": type(exc).__name__}


def lookup(address: str, chain: str = "auto") -> dict:
    address = address.strip()
    chains = detect_chains(address, chain)

    cache_key = (address, ",".join(chains))
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    identity_jobs = {
        "label": (known_label, address),
        "fomo": (fomo_profile, address),
        "pump": (pump_profile, address),
    }
    if "solana" in chains:
        identity_jobs["kol"] = (kol_profile, address)
        identity_jobs["sns"] = (sns_domain, address)
        identity_jobs["coins"] = (pump_coins, address)
    if "ethereum" in chains:
        identity_jobs["ens"] = (ens_name, address)
    if "bnb" in chains:
        identity_jobs["spaceid"] = (bnb_name, address)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {k: pool.submit(_safe, *job) for k, job in identity_jobs.items()}
        bal_futures = [pool.submit(_safe, native_balance, c, address) for c in chains]
        results = {k: f.result() for k, f in futures.items()}
        balances = [f.result() for f in bal_futures]

    coins = results.pop("coins", {"ok": True, "data": []})
    sources = []
    for key, res in results.items():
        sources.append({"key": key, "ok": res["ok"], "found": bool(res.get("data")), **(res.get("data") or {})})

    # Order matters: the first hit becomes the headline owner.
    priority = ["label", "kol", "fomo", "ens", "sns", "spaceid", "pump"]
    hits = sorted((s for s in sources if s["found"]), key=lambda s: priority.index(s["key"]))
    owner = None
    if hits:
        top = hits[0]
        owner = {
            "name": top["name"],
            "source": top["source"],
            "avatar": next((h.get("avatar") for h in hits if h.get("avatar")), None),
            "x": next((h.get("x") for h in hits if h.get("x")), None),
            "bio": next((h.get("bio") for h in hits if h.get("bio")), None),
            "kind": top.get("kind"),
        }

    payload = {
        "address": address,
        "chains": chains,
        "owner": owner,
        "confidence": "high" if len(hits) >= 2 or (hits and hits[0]["key"] == "label") else "medium" if hits else "none",
        "score": confidence_score(hits),
        "sources": sources,
        "balances": [b["data"] for b in balances if b["ok"]],
        "coins": coins.get("data") or [],
        "explorers": {c: EXPLORERS[c].format(address) for c in chains},
    }
    _cache[cache_key] = (time.time(), payload)
    return payload
