import time
from urllib.parse import urlparse

_last_request_at: dict[str, float] = {}


def wait_for_domain(url: str, min_delay_sec: float) -> None:
    """Block until at least min_delay_sec has passed since the last request to this domain."""
    domain = urlparse(url).netloc
    now = time.monotonic()
    last = _last_request_at.get(domain)
    if last is not None:
        elapsed = now - last
        remaining = min_delay_sec - elapsed
        if remaining > 0:
            time.sleep(remaining)
    _last_request_at[domain] = time.monotonic()
