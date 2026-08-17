import json
import random
import re
import secrets
import string
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "pumplify"

import requests

from .client import (
    extract_ipfs_url,
    follow_wallet,
    get_auth_token,
    is_blocked_response,
    login,
    read_profile,
    update_profile,
    upload_profile_image,
)
from .config import PROJECT_ROOT, Settings, load_settings
from .log import log
from .proxy import choose_working_proxy, proxy_label, release_proxy
from .wallet import generate_wallet, save_wallet, load_saved_wallets, is_auth_token_valid


@dataclass
class AccountResult:
    address: str | None = None
    username: str | None = None
    ok: bool = False
    failed_step: str | None = None
    error: str | None = None


MAX_USERNAME_ATTEMPTS = 5
USERNAME_MAX_LENGTH = 15
USERNAME_SUFFIX_LENGTH = 2
USERNAME_FALLBACK_BASE = "user"
USERNAME_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_]+")
FOLLOW_BACK_COUNT_BUCKETS = (
    (90, 3, 8),
    (8, 9, 20),
    (2, 21, 40),
)


def random_suffix(length=5):
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def clean_username_base(username: str | None) -> str:
    cleaned = USERNAME_INVALID_CHARS.sub("_", (username or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or USERNAME_FALLBACK_BASE


def make_username(settings: Settings, override_username: str | None = None) -> str:
    base_username = clean_username_base(
        override_username if override_username is not None else settings.username
    )

    if settings.auto_unique_username:
        suffix = random_suffix(USERNAME_SUFFIX_LENGTH)
        base_limit = USERNAME_MAX_LENGTH - len(suffix)
        return f"{base_username[:base_limit]}{suffix}"
    return base_username[:USERNAME_MAX_LENGTH]


def make_username_candidates(
    settings: Settings,
    override_username: str | None = None,
    count: int = MAX_USERNAME_ATTEMPTS,
) -> list[str]:
    if not settings.auto_unique_username:
        return [make_username(settings, override_username)]

    return [make_username(settings, override_username) for _ in range(count)]


def response_preview(response: requests.Response) -> str:
    text = response.text.strip()
    if not text:
        return f"HTTP {response.status_code}"
    return f"HTTP {response.status_code}: {text[:500]}"


def extract_profile_username(response: requests.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None

    if not isinstance(data, dict):
        return None

    username = data.get("username")
    if isinstance(username, str):
        return username

    for key in ("user", "data", "profile"):
        nested = data.get(key)
        if isinstance(nested, dict):
            username = nested.get("username")
            if isinstance(username, str):
                return username

    return None


def extract_profile_address(response: requests.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None

    if not isinstance(data, dict):
        return None

    for key in ("address", "publicAddress", "walletAddress"):
        address = data.get(key)
        if isinstance(address, str) and address.strip():
            return address.strip()

    for key in ("user", "data", "profile"):
        nested = data.get(key)
        if isinstance(nested, dict):
            for address_key in ("address", "publicAddress", "walletAddress"):
                address = nested.get(address_key)
                if isinstance(address, str) and address.strip():
                    return address.strip()

    return None


def profile_identifier(profile: str) -> str:
    profile = profile.strip()
    parsed = urlparse(profile)
    if parsed.scheme and parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "profile":
            return parts[1]
        if parts:
            return parts[-1]
    return profile.rstrip("/")


def resolve_profile_address(
    session: requests.Session,
    auth_token: str | None,
    profile: str,
) -> str:
    identifier = profile_identifier(profile)
    response = read_profile(session, auth_token, identifier)
    if not response.ok:
        raise ValueError(f"could not resolve target profile {profile!r}: {response_preview(response)}")

    address = extract_profile_address(response)
    if not address:
        raise ValueError(f"target profile {profile!r} did not return an address")
    return address


def verify_profile_username(
    session: requests.Session,
    auth_token: str,
    address: str,
    username: str,
) -> tuple[bool, str | None, str | None]:
    response = read_profile(session, auth_token, address)
    if not response.ok:
        return False, None, response_preview(response)

    saved_username = extract_profile_username(response)
    if saved_username == username:
        return True, saved_username, None

    return False, saved_username, None


def choose_follow_back_count(available_count: int) -> int:
    if available_count <= 0:
        return 0

    roll = random.randint(1, 100)
    cumulative_weight = 0
    for weight, minimum, maximum in FOLLOW_BACK_COUNT_BUCKETS:
        cumulative_weight += weight
        if roll <= cumulative_weight:
            return min(random.randint(minimum, maximum), available_count)

    _, minimum, maximum = FOLLOW_BACK_COUNT_BUCKETS[-1]
    return min(random.randint(minimum, maximum), available_count)


def sample_follow_back_entries(entries: list[dict], target_count: int) -> list[dict]:
    if target_count <= 0:
        return []
    if target_count >= len(entries):
        return list(entries)
    return random.sample(entries, target_count)


def get_cookie_expires_at(session: requests.Session, cookie_name: str) -> float | None:
    for cookie in session.cookies:
        if cookie.name == cookie_name:
            return cookie.expires
    return None


def follow_with_existing_accounts(settings, new_address: str, max_workers: int = 2):
    wallets = load_saved_wallets(settings.wallet_output_path)

    valid_entries = [
        entry
        for entry in wallets
        if entry.get("publicAddress") != new_address
        and is_auth_token_valid(entry)
    ]

    if not valid_entries:
        print("No non-expired saved accounts available to follow back.")
        return

    target_count = choose_follow_back_count(len(valid_entries))
    selected_entries = sample_follow_back_entries(valid_entries, target_count)

    print(
        f"Using {len(selected_entries)}/{len(valid_entries)} saved account(s) "
        f"to follow {new_address}"
    )

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

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_follow_one, entry) for entry in selected_entries]
        for future in as_completed(futures):
            future.result()


def run_single_account(
        settings: Settings,
        index: int,
        override_username: str | None = None,
        override_image_url: str | None = None,
) -> AccountResult:
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
        try:
            target_address = resolve_profile_address(
                session,
                auth_token,
                settings.target_wallet,
            )
        except ValueError as exc:
            result.failed_step = "target profile"
            result.error = str(exc)
            return result

        if not settings.skip_profile_image:
            if override_image_url is not None:
                # Use the provided IPFS URL directly; skip upload.
                image_url = override_image_url
            else:
                # Original upload flow
                try:
                    response = upload_profile_image(session, auth_token, image_path, settings)
                except requests.RequestException as exc:
                    result.failed_step = "image upload"
                    result.error = f"network: {exc}"
                    return result

                if not response.ok:
                    result.failed_step = "image upload"
                    result.error = response_preview(response)
                    return result

                try:
                    image_url = extract_ipfs_url(response)
                except Exception as exc:
                    result.failed_step = "image upload"
                    result.error = f"no IPFS URL: {exc}"
                    return result

        username_errors = []
        for username in make_username_candidates(settings, override_username):
            result.username = username

            response = update_profile(
                session,
                auth_token,
                username,
                settings.bio,
                image_url,
            )
            if not response.ok:
                username_errors.append(f"{username!r}: {response_preview(response)}")
                continue

            update_result = response_preview(response)
            time.sleep(0.75)
            verified, saved_username, verify_error = verify_profile_username(
                session,
                auth_token,
                address,
                username,
            )
            if verified:
                break

            if verify_error:
                username_errors.append(f"{username!r}: verify failed: {verify_error}")
            else:
                username_errors.append(
                    f"{username!r}: profile returned {saved_username!r}; "
                    f"update response {update_result}"
                )
        else:
            result.failed_step = "profile verify"
            result.error = "username not saved; " + "; ".join(username_errors)
            return result

        response = follow_wallet(session, auth_token, target_address)
        if not response.ok:
            result.failed_step = "follow"
            result.error = response_preview(response)
            return result

        save_wallet(
            address,
            private_key,
            settings,
            selected_proxy,
            auth_token,
            auth_token_expires_at=auth_token_expires_at,
            status="completed",
            username=username,
        )

        result.ok = True
        log(f"{tag} DONE user={username} img={image_url or 'skipped'}")

        # Follow back using existing saved accounts.
        try:
            follow_with_existing_accounts(settings, address)
        except Exception as exc:
            print(f"{tag} follow-back stage failed: {exc}")
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
        entries: list[dict] | None = None,
) -> list[AccountResult]:
    """
    Create `count` accounts. If `entries` is provided, each account will use
    the username and profile_image from successive entries (cycling if needed).
    If `entries` is None or empty, the script falls back to generating random
    usernames and uploading local images as usual.
    """
    results: list[AccountResult] = []

    # Prepare overrides for each account index
    overrides = []
    if entries:
        for i in range(count):
            entry = entries[i % len(entries)]
            overrides.append((entry.get("username"), entry.get("profile_image")))
    else:
        overrides = [(None, None)] * count

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for i in range(count):
            override_username, override_image_url = overrides[i]
            futures[
                pool.submit(
                    run_single_account,
                    settings,
                    i,
                    override_username,
                    override_image_url,
                )
            ] = i

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


def load_data_entries(file_path: str | Path = "data.json") -> list[dict]:
    """Load and return the list of entries from data.json."""
    path = Path(file_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            log(f"Warning: {path} does not contain a list. Using empty list.")
            return []
        return data
    except FileNotFoundError:
        log(f"Warning: {path} not found. Proceeding without overrides.")
        return []
    except json.JSONDecodeError:
        log(f"Warning: {path} is not valid JSON. Proceeding without overrides.")
        return []


def main() -> int:
    settings = load_settings()
    entries = load_data_entries(settings.data_path) if settings.use_data_overrides else None

    results = run_multiple_accounts(
        settings,
        count=50,  # number of accounts to create
        max_workers=4,  # adjust as needed
        entries=entries,
    )
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
