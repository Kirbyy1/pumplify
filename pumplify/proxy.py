import random
import threading
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from .config import DEFAULT_HEADERS, Settings
from .log import log

_proxy_cache_lock = threading.Lock()
_proxy_candidates_cache: dict[tuple[str, ...], list[str]] = {}
_proxy_lease_lock = threading.Lock()
_leased_proxies: set[str] = set()


def normalize_proxy_line(line: str) -> str:
    """Normalize common text proxy formats to a requests proxy URL."""
    value = line.strip()
    if not value or value.startswith("#"):
        return ""

    if value.startswith(("http://", "https://")):
        return value

    parts = value.split(":", 3)
    if len(parts) == 2:
        return f"http://{value}"

    if len(parts) == 4:
        host, port, username, password = parts
        username = quote(username, safe="")
        password = quote(password, safe="")
        return f"http://{username}:{password}@{host}:{port}"

    if "@" in value:
        return f"http://{value}"

    raise ValueError(f"Unsupported proxy format: {value!r}")


def proxy_label(proxy_url: str) -> str:
    """Return a safe label without exposing proxy credentials."""
    parsed = urlparse(proxy_url)
    if parsed.hostname and parsed.port:
        return f"{parsed.hostname}:{parsed.port}"
    return "<proxy>"


def load_proxy_file(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Proxy file not found: {path.resolve()}")

    proxies = []
    seen = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        proxy = normalize_proxy_line(raw)
        if proxy and proxy not in seen:
            seen.add(proxy)
            proxies.append(proxy)

    if not proxies:
        raise RuntimeError(f"No usable proxies found in {path.resolve()}")

    return proxies


def load_proxy_candidates(settings: Settings) -> list[str]:
    cache_key = (
        settings.proxy_mode,
        str(settings.proxy_file),
    )
    with _proxy_cache_lock:
        cached = _proxy_candidates_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        if settings.proxy_mode == "off":
            candidates = []
        elif settings.proxy_mode == "file":
            candidates = load_proxy_file(settings.proxy_file)
        else:
            raise ValueError("PROXY_MODE must be 'file' or 'off'.")

        _proxy_candidates_cache[cache_key] = list(candidates)
        return list(candidates)


def apply_proxy(session: requests.Session, proxy_url: str) -> None:
    session.proxies.clear()
    session.proxies.update({
        "http": proxy_url,
        "https": proxy_url,
    })


def _try_lease_proxy(proxy_url: str) -> bool:
    with _proxy_lease_lock:
        if proxy_url in _leased_proxies:
            return False
        _leased_proxies.add(proxy_url)
        return True


def release_proxy(proxy_url: str | None) -> None:
    if not proxy_url:
        return
    with _proxy_lease_lock:
        _leased_proxies.discard(proxy_url)


def choose_working_proxy(
    session: requests.Session,
    settings: Settings,
) -> str | None:
    candidates = load_proxy_candidates(settings)
    if not candidates:
        log("[PROXY] Disabled; using direct connection.")
        return None

    random.shuffle(candidates)

    attempts = min(settings.max_proxy_attempts, len(candidates))
    last_error = None
    tested = 0

    for proxy_url in candidates:
        if tested >= attempts:
            break
        if not _try_lease_proxy(proxy_url):
            continue

        tested += 1
        label = proxy_label(proxy_url)
        apply_proxy(session, proxy_url)

        if not settings.test_proxy_before_use:
            log(f"[PROXY] Using {label} (preflight disabled).")
            return proxy_url

        log(f"[PROXY] Testing {label} ({tested}/{attempts})...")
        try:
            response = session.get(
                settings.proxy_test_url,
                headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]},
                timeout=settings.proxy_test_timeout,
            )
            response.raise_for_status()

            exit_ip = None
            try:
                data = response.json()
                if isinstance(data, dict):
                    exit_ip = data.get("ip")
            except ValueError:
                pass

            if exit_ip:
                log(f"[PROXY] PASS {label} -> exit IP {exit_ip}")
            else:
                log(f"[PROXY] PASS {label}")
            return proxy_url
        except requests.RequestException as exc:
            last_error = exc
            release_proxy(proxy_url)
            log(f"[PROXY] FAIL {label}: {exc}")

    session.proxies.clear()
    if tested == 0:
        raise RuntimeError("No proxy is currently available; all candidates are in use.")
    raise RuntimeError(
        f"No working proxy found after {tested} attempts. Last error: {last_error}"
    )
