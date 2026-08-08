from urllib.parse import urljoin, urlparse

import httpx
from protego import Protego

from epcot_fw.config import settings

_robots_cache: dict[str, Protego] = {}


def _fetch_robots_txt(domain_root: str) -> Protego:
    robots_url = urljoin(domain_root, "/robots.txt")
    try:
        resp = httpx.get(
            robots_url,
            headers={"User-Agent": settings.user_agent},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            # No robots.txt or inaccessible -> treat as "allow everything"
            return Protego.parse("")
        return Protego.parse(resp.text)
    except httpx.HTTPError:
        # Fail closed is tempting, but a transient network error shouldn't
        # permanently block a source; treat as allow and let the real
        # request retry/fail on its own.
        return Protego.parse("")


def is_allowed(url: str) -> bool:
    parsed = urlparse(url)
    domain_root = f"{parsed.scheme}://{parsed.netloc}"
    if domain_root not in _robots_cache:
        _robots_cache[domain_root] = _fetch_robots_txt(domain_root)
    return _robots_cache[domain_root].can_fetch(url, settings.user_agent)
