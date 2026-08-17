import json
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

import base58
from nacl import signing

from .config import Settings
from .proxy import proxy_label

_wallet_save_lock = threading.Lock()
TOKEN_FALLBACK_TTL_SECONDS = 24 * 60 * 60
MAX_CREATED_AT_FUTURE_SKEW_SECONDS = 5


def generate_wallet():
    signing_key = signing.SigningKey.generate()
    seed = signing_key.encode()
    public_key = signing_key.verify_key.encode()
    secret_key_64 = seed + public_key

    address = base58.b58encode(public_key).decode("utf-8")
    private_key = base58.b58encode(secret_key_64).decode("utf-8")

    return signing_key, address, private_key


def _load_saved_wallets(path: Path) -> list[dict]:
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if isinstance(data.get("wallets"), list):
            return data["wallets"]
        return [data]

    raise ValueError(f"Wallet output file must contain a JSON object or array: {path}")


def load_saved_wallets(file_path: Path | str) -> list[dict]:
    path = Path(file_path)
    try:
        wallets = _load_saved_wallets(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    return [entry for entry in wallets if isinstance(entry, dict)]


def is_auth_token_valid(entry: dict, now: float | None = None) -> bool:
    if not entry.get("authToken"):
        return False

    now = now if now is not None else datetime.now(UTC).timestamp()

    exp = entry.get("authTokenExpiresAt")
    if exp is not None:
        try:
            return float(exp) > now
        except (TypeError, ValueError):
            return False

    created = entry.get("createdAt")
    if created:
        try:
            created_ts = datetime.fromisoformat(created).timestamp()
            age_seconds = now - created_ts
            return (
                age_seconds >= -MAX_CREATED_AT_FUTURE_SKEW_SECONDS
                and age_seconds < TOKEN_FALLBACK_TTL_SECONDS
            )
        except (TypeError, ValueError):
            return False

    return False


def save_wallet(
    address: str,
    private_key: str,
    settings: Settings,
    proxy_url: str | None = None,
    auth_token: str | None = None,
    auth_token_expires_at: float | None = None,
    status: str = "completed",
    failed_step: str | None = None,
) -> Path:
    output_path = settings.wallet_output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with _wallet_save_lock:
        wallets = _load_saved_wallets(output_path)
        wallets.append(
            {
                "publicAddress": address,
                "privateKey": private_key,
                "authToken": auth_token,
                "authTokenExpiresAt": auth_token_expires_at,
                "createdAt": datetime.now(UTC).isoformat(),
                "status": status,
                "failedStep": failed_step,
                "pumpProfile": f"https://pump.fun/profile/{address}",
                "targetProfile": f"https://pump.fun/profile/{settings.target_wallet}",
                "proxy": proxy_label(proxy_url) if proxy_url else None,
                "proxyUrl": proxy_url,
            }
        )

        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output_path.parent,
            delete=False,
        ) as temp_file:
            temp_file.write(json.dumps(wallets, indent=2))
            temp_file.write("\n")
            temp_path = Path(temp_file.name)

        temp_path.replace(output_path)
    return output_path
