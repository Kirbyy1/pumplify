import re
import secrets
import string
from urllib.parse import urlparse

import requests

from .client import read_profile
from .config import Settings

MAX_USERNAME_ATTEMPTS = 5
USERNAME_MAX_LENGTH = 15
USERNAME_SUFFIX_LENGTH = 2
USERNAME_FALLBACK_BASE = "user"
USERNAME_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_]+")


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
