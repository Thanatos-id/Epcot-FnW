import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import RawPage
from epcot_fw.parse.html_utils import soupify


def content_hash(html: str) -> str:
    """Hash the page's visible text, not its raw HTML bytes.

    Large sites (Disney's official site, AllEars) embed per-request dynamic
    content in the markup itself - cache-busting asset query params, nonces,
    analytics/session tokens, A/B test bucket markers - that changes on every
    single fetch even when nothing a reader would notice has changed. Hashing
    raw bytes made every refresh treat those pages as "changed" and reparse
    them every time, defeating the whole point of change detection. Visible
    text is far more stable since that noise mostly lives in attributes and
    script/style tags, which get_text() strips.
    """
    try:
        visible_text = soupify(html).get_text(" ")
    except Exception:
        visible_text = html
    normalized = " ".join(visible_text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class CacheResult:
    raw_page: RawPage
    is_new_or_changed: bool


def latest_raw_page(session: Session, url: str) -> RawPage | None:
    stmt = (
        select(RawPage)
        .where(RawPage.url == url, RawPage.superseded_by_id.is_(None))
        .order_by(RawPage.fetched_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def record_fetch(
    session: Session,
    *,
    source_id: int,
    url: str,
    page_kind: str,
    http_status: int,
    body_text: str,
    etag: str | None,
    last_modified: str | None,
    not_modified: bool,
) -> CacheResult:
    """Upsert a raw_pages row for this fetch, detecting whether content actually changed.

    Callers must not pass an error response here. `body_text` is taken to be
    the page's content, so a 4xx/5xx body would be hashed as a change and
    would supersede the last good copy - see the status check in
    pipeline/crawl.py::_fetch_and_stage. `not_modified` (304) is the one
    non-2xx case this handles, and it is handled as "unchanged", not as a body.
    """
    now = datetime.now(UTC)
    prior = latest_raw_page(session, url)

    if not_modified and prior is not None:
        prior.last_seen_unchanged_at = now
        session.flush()
        return CacheResult(raw_page=prior, is_new_or_changed=False)

    new_hash = content_hash(body_text)

    if prior is not None and prior.content_hash == new_hash:
        prior.last_seen_unchanged_at = now
        session.flush()
        return CacheResult(raw_page=prior, is_new_or_changed=False)

    new_page = RawPage(
        source_id=source_id,
        url=url,
        page_kind=page_kind,
        fetched_at=now,
        http_status=http_status,
        content_hash=new_hash,
        raw_html=body_text,
        etag=etag,
        last_modified=last_modified,
        first_seen_at=now,
    )
    session.add(new_page)
    session.flush()

    if prior is not None:
        prior.superseded_by_id = new_page.id
        session.flush()

    return CacheResult(raw_page=new_page, is_new_or_changed=True)
