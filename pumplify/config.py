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


def env_bool(*keys: str, default: str = "0") -> bool:
    for key in keys:
        value = os.getenv(key)
        if value is not None:
            return value.strip() == "1"
    return default == "1"


def env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)).strip())


def env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)).strip())


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

    override = values.get("ENV_FILE_OVERRIDE", "0") == "1"
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
    run_log_dir: Path = Path("runs")
    account_count: int = 50
    account_workers: int = 4

    proxy_mode: str = "file"
    proxy_file: Path = Path("proxies.txt")
    test_proxy_before_use: bool = True
    proxy_test_url: str = "https://api.ipify.org?format=json"
    proxy_test_timeout: float = 10
    max_proxy_attempts: int = 10
    http_retries: int = 2
    retry_backoff_seconds: float = 0.75
    followback_workers: int = 2
    followback_buckets: tuple[tuple[int, int, int], ...] = (
        (90, 3, 8),
        (8, 9, 20),
        (2, 21, 40),
    )


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        target_wallet=os.getenv(
            "TARGET_PROFILE",
            "2vKnXF4RWm3YNYuTo3xXvfkoum3Cfc9HYgReNbTTxbsz",
        ).strip(),
        username=os.getenv("PUMP_USERNAME", "katakama").strip(),
        bio=os.getenv("PUMP_BIO", "the sexiest king"),
        pfp_path=project_path(os.getenv("PFP_PATH", "pfp.jpg")),
        skip_profile_image=env_bool("SKIP_PROFILE_IMAGE"),
        auto_unique_username=os.getenv("AUTO_UNIQUE_USERNAME", "1").strip() != "0",
        use_data_overrides=env_bool("USE_PROFILE_DATA"),
        data_path=project_path(os.getenv("PROFILE_DATA_PATH", "data.json")),
        wallet_output_path=project_path(
            os.getenv("WALLET_OUTPUT_PATH", "generated_pump_profile_wallet.json")
        ),
        run_log_dir=project_path(os.getenv("RUN_LOG_DIR", "runs")),
        account_count=env_int("ACCOUNT_COUNT", 50),
        account_workers=env_int("ACCOUNT_WORKERS", 4),
        proxy_mode=os.getenv("PROXY_MODE", "file").strip().lower(),
        proxy_file=project_path(os.getenv("PROXY_FILE", "proxies.txt")),
        test_proxy_before_use=os.getenv("TEST_PROXY_BEFORE_USE", "1").strip() != "0",
        proxy_test_url=os.getenv(
            "PROXY_TEST_URL",
            "https://api.ipify.org?format=json",
        ),
        proxy_test_timeout=env_float("PROXY_TEST_TIMEOUT", 10),
        max_proxy_attempts=env_int("MAX_PROXY_ATTEMPTS", 10),
        http_retries=env_int("HTTP_RETRIES", 2),
        retry_backoff_seconds=env_float("RETRY_BACKOFF_SECONDS", 0.75),
        followback_workers=env_int("FOLLOWBACK_WORKERS", 2),
    )
