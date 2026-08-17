import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .client import follow_wallet
from .config import Settings
from .wallet import is_auth_token_valid, load_saved_wallets


def choose_follow_back_count(
    available_count: int,
    buckets: tuple[tuple[int, int, int], ...],
) -> int:
    if available_count <= 0:
        return 0

    roll = random.randint(1, 100)
    cumulative_weight = 0
    for weight, minimum, maximum in buckets:
        cumulative_weight += weight
        if roll <= cumulative_weight:
            return min(random.randint(minimum, maximum), available_count)

    _, minimum, maximum = buckets[-1]
    return min(random.randint(minimum, maximum), available_count)


def sample_follow_back_entries(entries: list[dict], target_count: int) -> list[dict]:
    if target_count <= 0:
        return []
    if target_count >= len(entries):
        return list(entries)
    return random.sample(entries, target_count)


def follow_with_existing_accounts(
    settings: Settings,
    new_address: str,
    max_workers: int | None = None,
) -> tuple[int, int]:
    wallets = load_saved_wallets(settings.wallet_output_path)
    valid_entries = [
        entry
        for entry in wallets
        if entry.get("publicAddress") != new_address
        and is_auth_token_valid(entry)
    ]

    if not valid_entries:
        return 0, 0

    target_count = choose_follow_back_count(
        len(valid_entries),
        settings.followback_buckets,
    )
    selected_entries = sample_follow_back_entries(valid_entries, target_count)

    def _follow_one(entry: dict) -> bool:
        session = requests.Session()
        proxy_url = entry.get("proxyUrl")
        if proxy_url:
            session.proxies.update({"http": proxy_url, "https": proxy_url})

        auth_token = entry.get("authToken")
        if not auth_token:
            return False

        session.cookies.set("auth_token", auth_token, domain="pump.fun", path="/")

        try:
            response = follow_wallet(session, auth_token, new_address)
        except requests.RequestException:
            return False

        return response.ok

    workers = max_workers if max_workers is not None else settings.followback_workers
    ok = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_follow_one, entry) for entry in selected_entries]
        for future in as_completed(futures):
            ok += int(future.result())

    return ok, len(selected_entries)
