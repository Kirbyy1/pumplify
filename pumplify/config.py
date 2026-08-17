import os
from dataclasses import dataclass
from pathlib import Path


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


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    target_wallet: str = "2vKnXF4RWm3YNYuTo3xXvfkoum3Cfc9HYgReNbTTxbsz"
    username: str = "katakama"
    bio: str = "the sexiest king"
    pfp_path: Path = Path("pfp.jpg")
    skip_profile_image: bool = False
    auto_unique_username: bool = True
    wallet_output_path: Path = Path("generated_pump_profile_wallet.json")

    proxy_mode: str = "file"
    proxyscrape_api_token: str = ""
    proxyscrape_subaccount_id: str = ""
    proxyscrape_country: str = ""
    proxyscrape_proxy_username: str = ""
    proxyscrape_proxy_password: str = ""
    proxy_file: Path = Path("proxies.txt")
    test_proxy_before_use: bool = True
    proxy_test_url: str = "https://api.ipify.org?format=json"
    proxy_test_timeout: float = 10
    max_proxy_attempts: int = 10


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        target_wallet=os.getenv(
            "PUMP_TARGET_WALLET",
            "2vKnXF4RWm3YNYuTo3xXvfkoum3Cfc9HYgReNbTTxbsz",
        ).strip(),
        username=os.getenv("PUMP_USERNAME", "katakama").strip(),
        bio=os.getenv("PUMP_BIO", "the sexiest king"),
        pfp_path=Path(os.getenv("PFP_PATH", "pfp.jpg")),
        skip_profile_image=os.getenv("SKIP_PROFILE_IMAGE", "0") == "1",
        auto_unique_username=os.getenv("AUTO_UNIQUE_USERNAME", "1") != "0",
        wallet_output_path=Path(
            os.getenv("WALLET_OUTPUT_PATH", "generated_pump_profile_wallet.json")
        ),
        proxy_mode=os.getenv("PROXY_MODE", "file").strip().lower(),
        proxyscrape_api_token=os.getenv("PROXYSCRAPE_API_TOKEN", "").strip(),
        proxyscrape_subaccount_id=os.getenv("PROXYSCRAPE_SUBACCOUNT_ID", "").strip(),
        proxyscrape_country=os.getenv("PROXYSCRAPE_COUNTRY", "").strip().upper(),
        proxyscrape_proxy_username=os.getenv(
            "PROXYSCRAPE_PROXY_USERNAME", ""
        ).strip(),
        proxyscrape_proxy_password=os.getenv(
            "PROXYSCRAPE_PROXY_PASSWORD", ""
        ).strip(),
        proxy_file=Path(os.getenv("PROXY_FILE", "proxies.txt")),
        test_proxy_before_use=os.getenv("TEST_PROXY_BEFORE_USE", "1") != "0",
        proxy_test_url=os.getenv(
            "PROXY_TEST_URL",
            "https://api.ipify.org?format=json",
        ),
        proxy_test_timeout=float(os.getenv("PROXY_TEST_TIMEOUT", "10")),
        max_proxy_attempts=int(os.getenv("MAX_PROXY_ATTEMPTS", "10")),
    )
