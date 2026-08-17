import random
import secrets
import string
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests

from .client import (
    extract_ipfs_url,
    follow_wallet,
    get_auth_token,
    is_blocked_response,
    login,
    set_name_and_bio,
    set_profile_image,
    upload_profile_image,
)
from .config import Settings, load_settings
from .log import log
from .proxy import choose_working_proxy, proxy_label, release_proxy
from .wallet import generate_wallet, save_wallet


@dataclass
class AccountResult:
    address: str | None = None
    username: str | None = None
    ok: bool = False
    failed_step: str | None = None
    error: str | None = None


def random_suffix(length=5):
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def make_username(settings: Settings) -> str:
    if settings.auto_unique_username:
        return f"{settings.username}{random_suffix()}"
    return settings.username


def get_cookie_expires_at(session: requests.Session, cookie_name: str) -> float | None:
    for cookie in session.cookies:
        if cookie.name == cookie_name:
            return cookie.expires
    return None


def run_single_account(settings: Settings, index: int) -> AccountResult:
    tag = f"[acct {index}]"
    result = AccountResult()
    selected_proxy = None
    image_path = settings.pfp_path
    image_url = None

    try:
        if not settings.skip_profile_image and not image_path.exists():
            result.failed_step = "image file"
            result.error = f"Profile image not found: {image_path.resolve()}"
            return result

        session = requests.Session()
        try:
            selected_proxy = choose_working_proxy(session, settings)
        except Exception as exc:
            result.failed_step = "proxy"
            result.error = str(exc)
            return result

        signing_key, address, private_key = generate_wallet()
        result.address = address

        log(f"{tag} Wallet: {address} | https://pump.fun/profile/{address}")
        if selected_proxy:
            log(f"{tag} Proxy: {proxy_label(selected_proxy)}")

        try:
            response = login(session, signing_key, address)
        except requests.RequestException as exc:
            result.failed_step = "login"
            result.error = f"network: {exc}"
            return result

        if not response.ok:
            result.failed_step = "login"
            if is_blocked_response(response):
                result.error = "blocked by Pump.fun/Cloudflare"
            else:
                result.error = f"HTTP {response.status_code}"
            return result

        auth_token = get_auth_token(session)
        if not auth_token:
            result.failed_step = "login"
            result.error = "no auth_token cookie"
            return result

        auth_token_expires_at = get_cookie_expires_at(session, "auth_token")

        username = make_username(settings)
        result.username = username
        response = set_name_and_bio(session, auth_token, username, settings.bio)
        if not response.ok:
            result.failed_step = "username/bio"
            result.error = f"HTTP {response.status_code}"
            return result

        if not settings.skip_profile_image:
            try:
                response = upload_profile_image(session, auth_token, image_path, settings)
            except requests.RequestException as exc:
                result.failed_step = "image upload"
                result.error = f"network: {exc}"
                return result

            if not response.ok:
                result.failed_step = "image upload"
                result.error = f"HTTP {response.status_code}"
                return result

            try:
                image_url = extract_ipfs_url(response)
            except Exception as exc:
                result.failed_step = "image upload"
                result.error = f"no IPFS URL: {exc}"
                return result

            response = set_profile_image(session, auth_token, image_url, settings.bio)
            if not response.ok:
                result.failed_step = "image save"
                result.error = f"HTTP {response.status_code}"
                return result

        response = follow_wallet(session, auth_token, settings.target_wallet)
        if not response.ok:
            result.failed_step = "follow"
            result.error = f"HTTP {response.status_code}"
            return result

        save_wallet(
            address,
            private_key,
            settings,
            selected_proxy,
            auth_token,
            auth_token_expires_at=auth_token_expires_at,
            status="completed",
        )

        result.ok = True
        log(f"{tag} DONE user={username} img={image_url or 'skipped'}")
        return result
    finally:
        release_proxy(selected_proxy)


def summarize_results(results: list[AccountResult]) -> str:
    ok = sum(result.ok for result in results)
    failed = len(results) - ok
    by_step = Counter(
        result.failed_step or "unknown"
        for result in results
        if not result.ok
    )

    lines = [f"Done: {ok}/{len(results)} accounts succeeded."]
    if failed:
        lines.append(f"Failed: {failed}")
        for step, count in sorted(by_step.items()):
            lines.append(f"- {step}: {count}")
    return "\n".join(lines)


def run_multiple_accounts(
    settings: Settings,
    count: int,
    max_workers: int = 5,
) -> list[AccountResult]:
    results: list[AccountResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(run_single_account, settings, i): i
            for i in range(count)
        }
        for future in as_completed(futures):
            i = futures[future]
            result = future.result()
            results.append(result)

            status = "OK" if result.ok else f"FAIL at {result.failed_step} ({result.error})"
            log(f"[acct {i}] {status} wallet={result.address}")

            time.sleep(random.uniform(1.0, 3.0))

    log("")
    log(summarize_results(results))
    return results


def main() -> int:
    results = run_multiple_accounts(load_settings(), 10, 2)
    return 0 if all(r.ok for r in results) else 1
