# Pumplify

Single-account Pump.fun profile setup test.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

Configuration is loaded from `.env`, with real environment variables taking
precedence. Use `.env.example` as the template.

- `TARGET_PROFILE`
- `ENV_FILE_OVERRIDE`
- `USE_PROFILE_DATA`
- `PROFILE_DATA_PATH`
- `PUMP_USERNAME`
- `PUMP_BIO`
- `PFP_PATH`
- `SKIP_PROFILE_IMAGE`
- `AUTO_UNIQUE_USERNAME`
- `PROXY_MODE`
- `PROXY_FILE`
- `TEST_PROXY_BEFORE_USE`
- `PROXY_TEST_URL`
- `PROXY_TEST_TIMEOUT`
- `MAX_PROXY_ATTEMPTS`
- `WALLET_OUTPUT_PATH`

Generated wallets are appended to `WALLET_OUTPUT_PATH` as a JSON array. Each
entry includes `publicAddress`, `privateKey`, creation time, profile URLs, and
the pinned proxy label when one was used.

## Structure

- `main.py` - minimal CLI entry point.
- `pumplify/config.py` - settings and constants.
- `pumplify/proxy.py` - proxy parsing, loading, testing, and session setup.
- `pumplify/wallet.py` - wallet generation and wallet-file persistence.
- `pumplify/client.py` - Pump.fun HTTP client helpers.
- `pumplify/runner.py` - single-account workflow orchestration.
