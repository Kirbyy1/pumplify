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


def _with_global_proxy_credentials(host_port: str, settings: Settings) -> str:
    if not settings.proxyscrape_proxy_username:
        return f"http://{host_port}"

    username = quote(settings.proxyscrape_proxy_username, safe="")
    password = quote(settings.proxyscrape_proxy_password, safe="")
    return f"http://{username}:{password}@{host_port}"


def normalize_proxy_line(line: str, settings: Settings) -> str:
    """Normalize common ProxyScrape/text proxy formats to a requests proxy URL."""
    value = line.strip()
    if not value or value.startswith("#"):
        return ""

    if value.startswith(("http://", "https://")):
        return value

    if "@" in value:
        return f"http://{value}"

    parts = value.split(":")
    if len(parts) == 2:
        return _with_global_proxy_credentials(value, settings)

    if len(parts) == 4:
        host, port, username, password = parts
        username = quote(username, safe="")
        password = quote(password, safe="")
        return f"http://{username}:{password}@{host}:{port}"

    raise ValueError(f"Unsupported proxy format: {value!r}")


def proxy_label(proxy_url: str) -> str:
    """Return a safe label without exposing proxy credentials."""
    parsed = urlparse(proxy_url)
    if parsed.hostname and parsed.port:
        return f"{parsed.hostname}:{parsed.port}"
    return "<proxy>"


def fetch_proxyscrape_premium_http_proxies(settings: Settings) -> list[str]:
    if not settings.proxyscrape_api_token:
        raise RuntimeError(
            "PROXYSCRAPE_API_TOKEN is required when PROXY_MODE=proxyscrape."
        )
    if not settings.proxyscrape_subaccount_id:
        raise RuntimeError(
            "PROXYSCRAPE_SUBACCOUNT_ID is required when PROXY_MODE=proxyscrape."
        )

    url = (
        "https://api.proxyscrape.com/v4/account/"
        f"{settings.proxyscrape_subaccount_id}/datacenter_shared/proxy-list"
    )
    params = [
        ("type", "getproxies"),
        ("protocol", "http"),
        ("format", "normal"),
    ]
    if settings.proxyscrape_country:
        params.append(("country[]", settings.proxyscrape_country))

    response = requests.get(
        url,
        headers={"api-token": settings.proxyscrape_api_token},
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    raw_items = None
    try:
        data = response.json()
        if isinstance(data, str):
            raw_items = data.splitlines()
        elif isinstance(data, list):
            raw_items = [str(item) for item in data]
        elif isinstance(data, dict):
            for key in ("proxies", "data", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    raw_items = [str(item) for item in value]
                    break
                if isinstance(value, str):
                    raw_items = value.splitlines()
                    break
    except ValueError:
        pass

    if raw_items is None:
        raw_items = response.text.splitlines()

    proxies = []
    seen = set()
    for raw in raw_items:
        raw = raw.strip().strip('"')
        if not raw:
            continue
        proxy = normalize_proxy_line(raw, settings)
        if proxy and proxy not in seen:
            seen.add(proxy)
            proxies.append(proxy)

    if not proxies:
        raise RuntimeError("ProxyScrape returned an empty Premium HTTP proxy list.")

    return proxies


def load_proxy_file(path: Path, settings: Settings) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Proxy file not found: {path.resolve()}")

    proxies = []
    seen = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        proxy = normalize_proxy_line(raw, settings)
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
        settings.proxyscrape_subaccount_id,
        settings.proxyscrape_country,
        settings.proxyscrape_api_token,
        settings.proxyscrape_proxy_username,
        settings.proxyscrape_proxy_password,
    )
    with _proxy_cache_lock:
        cached = _proxy_candidates_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        if settings.proxy_mode == "off":
            candidates = []
        elif settings.proxy_mode == "proxyscrape":
            candidates = fetch_proxyscrape_premium_http_proxies(settings)
        elif settings.proxy_mode == "file":
            candidates = load_proxy_file(settings.proxy_file, settings)
        else:
            raise ValueError(f"Unknown PROXY_MODE: {settings.proxy_mode!r}")

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
