from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from epcot_fw.config import settings
from epcot_fw.fetch import rate_limiter, robots


class RobotsDisallowedError(Exception):
    """Raised when robots.txt disallows fetching a URL. Never bypass this."""


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str
    etag: str | None
    last_modified: str | None
    not_modified: bool


@retry(
    retry=retry_if_exception_type(httpx.TransportError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
)
def _get(client: httpx.Client, url: str, headers: dict) -> httpx.Response:
    return client.get(url, headers=headers)


def fetch(
    url: str,
    *,
    crawl_delay_sec: float = 5.0,
    etag: str | None = None,
    last_modified: str | None = None,
) -> FetchResult:
    """Fetch a URL, respecting robots.txt and per-domain rate limits.

    Conditional GET headers are sent when a prior etag/last_modified is known,
    so unchanged pages cost a cheap 304 instead of a full re-download.
    """
    if not robots.is_allowed(url):
        raise RobotsDisallowedError(f"robots.txt disallows fetching {url}")

    rate_limiter.wait_for_domain(url, crawl_delay_sec)

    headers = {"User-Agent": settings.user_agent}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    with httpx.Client(timeout=20, follow_redirects=True) as client:
        resp = _get(client, url, headers)

    return FetchResult(
        url=str(resp.url),
        status_code=resp.status_code,
        text=resp.text if resp.status_code != 304 else "",
        etag=resp.headers.get("ETag"),
        last_modified=resp.headers.get("Last-Modified"),
        not_modified=resp.status_code == 304,
    )
