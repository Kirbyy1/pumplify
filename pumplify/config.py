import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

API_BASE = "https://frontend-api-v3.pump.fun"
LOGIN_URL = f"{API_BASE}/auth/login"
PROFILE_UPDATE_URL = f"{API_BASE}/users"
IPFS_UPLOAD_URL = "https://pump.fun/api/ipfs-file"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
}


def project_path(path: Path | str) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def env_first(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value is not None:
            return value
    return default


def env_bool(*keys: str, default: str = "0") -> bool:
    return env_first(*keys, default=default).strip() == "1"


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    if not path.exists():
        return

    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value

    override = values.get("ENV_FILE_OVERRIDE", values.get("DOTENV_OVERRIDE", "0")) == "1"
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    target_wallet: str = "2vKnXF4RWm3YNYuTo3xXvfkoum3Cfc9HYgReNbTTxbsz"
    username: str = "katakama"
    bio: str = "the sexiest king"
    pfp_path: Path = Path("pfp.jpg")
    skip_profile_image: bool = False
    auto_unique_username: bool = True
    use_data_overrides: bool = False
    data_path: Path = Path("data.json")
    wallet_output_path: Path = Path("generated_pump_profile_wallet.json")

    proxy_mode: str = "file"
    proxy_file: Path = Path("proxies.txt")
    test_proxy_before_use: bool = True
    proxy_test_url: str = "https://api.ipify.org?format=json"
    proxy_test_timeout: float = 10
    max_proxy_attempts: int = 10


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        target_wallet=env_first(
            "TARGET_PROFILE",
            "PUMP_TARGET_WALLET",
            default="2vKnXF4RWm3YNYuTo3xXvfkoum3Cfc9HYgReNbTTxbsz",
        ).strip(),
        username=os.getenv("PUMP_USERNAME", "katakama").strip(),
        bio=os.getenv("PUMP_BIO", "the sexiest king"),
        pfp_path=project_path(os.getenv("PFP_PATH", "pfp.jpg")),
        skip_profile_image=env_bool("SKIP_PROFILE_IMAGE"),
        auto_unique_username=env_first(
            "AUTO_UNIQUE_USERNAME",
            default="1",
        ).strip() != "0",
        use_data_overrides=env_bool("USE_PROFILE_DATA", "USE_DATA_OVERRIDES"),
        data_path=project_path(env_first("PROFILE_DATA_PATH", "DATA_PATH", default="data.json")),
        wallet_output_path=project_path(
            os.getenv("WALLET_OUTPUT_PATH", "generated_pump_profile_wallet.json")
        ),
        proxy_mode=os.getenv("PROXY_MODE", "file").strip().lower(),
        proxy_file=project_path(os.getenv("PROXY_FILE", "proxies.txt")),
        test_proxy_before_use=env_first(
            "TEST_PROXY_BEFORE_USE",
            default="1",
        ).strip() != "0",
        proxy_test_url=os.getenv(
            "PROXY_TEST_URL",
            "https://api.ipify.org?format=json",
        ),
        proxy_test_timeout=float(os.getenv("PROXY_TEST_TIMEOUT", "10")),
        max_proxy_attempts=int(os.getenv("MAX_PROXY_ATTEMPTS", "10")),
    )
