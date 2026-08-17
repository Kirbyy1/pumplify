from .config import Settings


def validate_settings(settings: Settings) -> None:
    errors = []

    if not settings.target_wallet.strip():
        errors.append("TARGET_PROFILE is required.")

    if settings.account_count <= 0:
        errors.append("ACCOUNT_COUNT must be greater than 0.")
    if settings.account_workers <= 0:
        errors.append("ACCOUNT_WORKERS must be greater than 0.")
    if settings.followback_workers <= 0:
        errors.append("FOLLOWBACK_WORKERS must be greater than 0.")
    if settings.http_retries < 0:
        errors.append("HTTP_RETRIES must be 0 or greater.")
    if settings.retry_backoff_seconds < 0:
        errors.append("RETRY_BACKOFF_SECONDS must be 0 or greater.")

    if settings.use_data_overrides and not settings.data_path.exists():
        errors.append(f"PROFILE_DATA_PATH does not exist: {settings.data_path}")
    if (
        settings.use_data_overrides
        and settings.data_path.exists()
        and not settings.data_path.is_file()
    ):
        errors.append(f"PROFILE_DATA_PATH must be a file: {settings.data_path}")

    if not settings.skip_profile_image and not settings.pfp_path.exists():
        errors.append(f"PFP_PATH does not exist: {settings.pfp_path}")
    if (
        not settings.skip_profile_image
        and settings.pfp_path.exists()
        and not settings.pfp_path.is_file()
    ):
        errors.append(f"PFP_PATH must be a file: {settings.pfp_path}")

    if settings.proxy_mode not in {"file", "off"}:
        errors.append("PROXY_MODE must be 'file' or 'off'.")
    if settings.proxy_mode == "file" and not settings.proxy_file.exists():
        errors.append(f"PROXY_FILE does not exist: {settings.proxy_file}")
    if (
        settings.proxy_mode == "file"
        and settings.proxy_file.exists()
        and not settings.proxy_file.is_file()
    ):
        errors.append(f"PROXY_FILE must be a file: {settings.proxy_file}")
    if settings.test_proxy_before_use:
        if not settings.proxy_test_url.strip():
            errors.append("PROXY_TEST_URL is required when TEST_PROXY_BEFORE_USE is enabled.")
        if settings.proxy_test_timeout <= 0:
            errors.append("PROXY_TEST_TIMEOUT must be greater than 0.")

    if settings.max_proxy_attempts <= 0:
        errors.append("MAX_PROXY_ATTEMPTS must be greater than 0.")
    if settings.run_log_dir.exists() and not settings.run_log_dir.is_dir():
        errors.append(f"RUN_LOG_DIR must be a directory: {settings.run_log_dir}")
    if settings.wallet_output_path.exists() and settings.wallet_output_path.is_dir():
        errors.append(f"WALLET_OUTPUT_PATH must be a file: {settings.wallet_output_path}")

    if errors:
        raise ValueError("\n".join(errors))
