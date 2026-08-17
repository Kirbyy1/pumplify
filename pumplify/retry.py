import time
from collections.abc import Callable
from typing import TypeVar

import requests

T = TypeVar("T")
RETRY_STATUS_CODES = {500, 502, 503, 504}


def call_with_retries(
    operation: Callable[[], T],
    attempts: int,
    backoff_seconds: float,
    should_retry: Callable[[T], bool] | None = None,
) -> T:
    last_error: requests.RequestException | None = None
    tries = max(1, attempts + 1)

    for attempt in range(tries):
        try:
            result = operation()
        except requests.RequestException as exc:
            last_error = exc
            if attempt == tries - 1:
                raise
        else:
            if should_retry is None or not should_retry(result) or attempt == tries - 1:
                return result

        time.sleep(backoff_seconds * (attempt + 1))

    if last_error is not None:
        raise last_error
    raise RuntimeError("retry operation did not return a result")


def retry_response(response: requests.Response) -> bool:
    return response.status_code in RETRY_STATUS_CODES
