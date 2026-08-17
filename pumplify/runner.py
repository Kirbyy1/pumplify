import argparse
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

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
    update_profile,
    upload_profile_image,
)
from .config import Settings, load_settings, project_path
from .data_source import load_data_entries
from .followback import follow_with_existing_accounts
from .log import log
from .profile import (
    make_username_candidates,
    resolve_profile_address,
    response_preview,
    verify_profile_username,
)
from .proxy import choose_working_proxy, proxy_label, release_proxy
from .retry import call_with_retries, retry_response
from .runlog import RunLogger
from .validation import validate_settings
from .wallet import generate_wallet, save_wallet


@dataclass
class AccountResult:
    address: str | None = None
    username: str | None = None
    ok: bool = False
    failed_step: str | None = None
    error: str | None = None


def get_cookie_expires_at(session: requests.Session, cookie_name: str) -> float | None:
    for cookie in session.cookies:
        if cookie.name == cookie_name:
            return cookie.expires
    return None


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


def retry_call(settings: Settings, operation):
    return call_with_retries(
        operation,
        attempts=settings.http_retries,
        backoff_seconds=settings.retry_backoff_seconds,
        should_retry=retry_response,
    )


def run_single_account(
    settings: Settings,
    index: int,
    target_address: str,
    run_logger: RunLogger,
    override_username: str | None = None,
    override_image_url: str | None = None,
) -> AccountResult:
    tag = f"[acct {index}]"
    result = AccountResult()
    selected_proxy = None
    image_url = None
    address = None
    private_key = None
    auth_token = None
    auth_token_expires_at = None

    def fail(step: str, error: str) -> AccountResult:
        result.failed_step = step
        result.error = error
        if address and private_key:
            save_wallet(
                address,
                private_key,
                settings,
                selected_proxy,
                auth_token,
                auth_token_expires_at=auth_token_expires_at,
                status="failed",
                failed_step=step,
                username=result.username,
                error=error,
            )
        run_logger.event(
            "account_failed",
            index=index,
            address=address,
            username=result.username,
            failed_step=step,
            error=error,
            proxy=proxy_label(selected_proxy) if selected_proxy else None,
        )
        return result

    try:
        session = requests.Session()
        try:
            selected_proxy = choose_working_proxy(session, settings)
        except Exception as exc:
            return fail("proxy", str(exc))

        signing_key, address, private_key = generate_wallet()
        result.address = address
        run_logger.event("wallet_created", index=index, address=address)

        log(f"{tag} Wallet: {address} | https://pump.fun/profile/{address}")
        if selected_proxy:
            log(f"{tag} Proxy: {proxy_label(selected_proxy)}")

        try:
            response = retry_call(
                settings,
                lambda: login(session, signing_key, address),
            )
        except requests.RequestException as exc:
            return fail("login", f"network: {exc}")

        if not response.ok:
            if is_blocked_response(response):
                return fail("login", "blocked by Pump.fun/Cloudflare")
            return fail("login", response_preview(response))

        auth_token = get_auth_token(session)
        if not auth_token:
            return fail("login", "no auth_token cookie")

        auth_token_expires_at = get_cookie_expires_at(session, "auth_token")

        if not settings.skip_profile_image:
            if override_image_url is not None:
                image_url = override_image_url
            else:
                try:
                    response = retry_call(
                        settings,
                        lambda: upload_profile_image(
                            session,
                            auth_token,
                            settings.pfp_path,
                            settings,
                        ),
                    )
                except requests.RequestException as exc:
                    return fail("image upload", f"network: {exc}")

                if not response.ok:
                    return fail("image upload", response_preview(response))

                try:
                    image_url = extract_ipfs_url(response)
                except Exception as exc:
                    return fail("image upload", f"no IPFS URL: {exc}")

        username_errors = []
        username = None
        for username in make_username_candidates(settings, override_username):
            result.username = username
            try:
                response = retry_call(
                    settings,
                    lambda: update_profile(
                        session,
                        auth_token,
                        username,
                        settings.bio,
                        image_url,
                    ),
                )
            except requests.RequestException as exc:
                username_errors.append(f"{username!r}: network: {exc}")
                continue

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
            return fail("profile verify", "username not saved; " + "; ".join(username_errors))

        try:
            response = retry_call(
                settings,
                lambda: follow_wallet(session, auth_token, target_address),
            )
        except requests.RequestException as exc:
            return fail("follow", f"network: {exc}")

        if not response.ok:
            return fail("follow", response_preview(response))

        save_wallet(
            address,
            private_key,
            settings,
            selected_proxy,
            auth_token,
            auth_token_expires_at=auth_token_expires_at,
            status="completed",
            username=username,
            target_address=target_address,
        )

        result.ok = True
        run_logger.event(
            "account_completed",
            index=index,
            address=address,
            username=username,
            proxy=proxy_label(selected_proxy) if selected_proxy else None,
        )
        log(f"{tag} DONE user={username} img={image_url or 'skipped'}")

        try:
            followed, attempted = follow_with_existing_accounts(settings, address)
            run_logger.event(
                "followback_completed",
                index=index,
                address=address,
                followed=followed,
                attempted=attempted,
            )
            if attempted:
                log(f"{tag} Follow-back: {followed}/{attempted}")
        except Exception as exc:
            run_logger.event(
                "followback_failed",
                index=index,
                address=address,
                error=str(exc),
            )
            log(f"{tag} follow-back stage failed: {exc}")

        return result
    finally:
        release_proxy(selected_proxy)


def build_overrides(count: int, entries: list[dict] | None) -> list[tuple[str | None, str | None]]:
    if not entries:
        return [(None, None)] * count

    return [
        (
            entries[i % len(entries)].get("username"),
            entries[i % len(entries)].get("profile_image"),
        )
        for i in range(count)
    ]


def run_multiple_accounts(
    settings: Settings,
    target_address: str,
    run_logger: RunLogger,
    entries: list[dict] | None = None,
) -> list[AccountResult]:
    results: list[AccountResult] = []
    overrides = build_overrides(settings.account_count, entries)

    with ThreadPoolExecutor(max_workers=settings.account_workers) as pool:
        futures = {}
        for i, (override_username, override_image_url) in enumerate(overrides):
            futures[
                pool.submit(
                    run_single_account,
                    settings,
                    i,
                    target_address,
                    run_logger,
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

    summary = summarize_results(results)
    run_logger.event("run_summary", summary=summary)
    log("")
    log(summary)
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, help="Number of accounts to create.")
    parser.add_argument("--workers", type=int, help="Concurrent account workers.")
    parser.add_argument("--target", help="Target profile URL, username, or wallet address.")
    parser.add_argument("--profile-data-path", help="Path to profile data JSON.")
    parser.add_argument("--use-profile-data", action="store_true", help="Use profile data JSON.")
    parser.add_argument("--no-profile-data", action="store_true", help="Ignore profile data JSON.")
    parser.add_argument("--proxy-mode", choices=("file", "off"), help="Proxy mode.")
    parser.add_argument("--proxy-file", help="Proxy file path.")
    parser.add_argument("--run-log-dir", help="Directory for JSONL run logs.")
    return parser.parse_args(argv)


def apply_cli_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    updates = {}
    if args.count is not None:
        updates["account_count"] = args.count
    if args.workers is not None:
        updates["account_workers"] = args.workers
    if args.target:
        updates["target_wallet"] = args.target
    if args.profile_data_path:
        updates["data_path"] = project_path(args.profile_data_path)
    if args.use_profile_data:
        updates["use_data_overrides"] = True
    if args.no_profile_data:
        updates["use_data_overrides"] = False
    if args.proxy_mode:
        updates["proxy_mode"] = args.proxy_mode
    if args.proxy_file:
        updates["proxy_file"] = project_path(args.proxy_file)
    if args.run_log_dir:
        updates["run_log_dir"] = project_path(args.run_log_dir)
    return replace(settings, **updates)


def main(argv: list[str] | None = None) -> int:
    settings = apply_cli_overrides(load_settings(), parse_args(argv))
    try:
        validate_settings(settings)
    except ValueError as exc:
        log(f"Configuration error:\n{exc}")
        return 2

    run_logger = RunLogger(settings.run_log_dir)
    entries = load_data_entries(settings.data_path) if settings.use_data_overrides else None

    try:
        target_address = call_with_retries(
            lambda: resolve_profile_address(
                requests.Session(),
                None,
                settings.target_wallet,
            ),
            attempts=settings.http_retries,
            backoff_seconds=settings.retry_backoff_seconds,
        )
    except (requests.RequestException, ValueError) as exc:
        log(f"Target profile error: {exc}")
        run_logger.event("target_profile_failed", target=settings.target_wallet, error=str(exc))
        return 2

    run_logger.event(
        "run_started",
        account_count=settings.account_count,
        account_workers=settings.account_workers,
        target=settings.target_wallet,
        target_address=target_address,
        profile_data=str(settings.data_path) if settings.use_data_overrides else None,
        proxy_mode=settings.proxy_mode,
    )

    results = run_multiple_accounts(settings, target_address, run_logger, entries)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
