import threading

_print_lock = threading.Lock()


def log(message: str = "") -> None:
    with _print_lock:
        print(message, flush=True)
