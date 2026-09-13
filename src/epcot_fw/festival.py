"""Which festival is current, and what state it is in.

Both questions used to be answered at each call site, and both answers went
wrong in the same window - the weeks when the festival is actually running.

`status` was a column written once at seed time and revised by nothing, so
the published feed announced `upcoming` through the whole of a running
festival. It is derived from the dates here instead: a stored status cannot
stay true without something to move it, and there was no such thing.

`current_festival` was `ORDER BY year DESC` at six call sites - "the newest
row" standing in for "the festival happening now". Those two agree only
while there is one row. A second row for next year has to exist before that
festival opens, or there is nothing to crawl into; from the moment it does,
year-ordering hands every pipeline an empty future festival while this
year's is still serving. Picking by date keeps the running festival current
until it actually ends.
"""

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import Festival

# Statuses derived from the dates. `status` on the row is free-form and older
# rows carry other words; these three are what a client actually receives.
UPCOMING = "upcoming"
RUNNING = "running"
ENDED = "ended"

# The month a festival year rolls over for seeding. Food & Wine runs from
# late August to late November, so December is the first month in which
# "next year's festival" is unambiguously the one to be working toward.
# October is not: the festival is mid-run, and a row for next year seeded
# then used to capture every `ORDER BY year DESC` lookup in the codebase.
ROLLOVER_MONTH = 12


def festival_year_for(today: datetime.date | None = None) -> int:
    """The festival year to seed when no row exists yet."""
    today = today or datetime.date.today()
    return today.year + 1 if today.month >= ROLLOVER_MONTH else today.year


def festival_status(
    start_date: datetime.date | None,
    end_date: datetime.date | None,
    today: datetime.date | None = None,
) -> str | None:
    """`upcoming`, `running` or `ended` from the dates and the calendar.

    Returns None when either date is unknown - a freshly seeded row has
    neither until a crawl fills them in, and a guess would be worse than the
    stored value the caller falls back to.

    Both bounds are inclusive: the festival is running on its opening day and
    on its closing day.
    """
    if start_date is None or end_date is None:
        return None
    today = today or datetime.date.today()
    if today < start_date:
        return UPCOMING
    if today > end_date:
        return ENDED
    return RUNNING


def current_festival(session: Session) -> Festival | None:
    """The festival to read and write as "now", or None if there are no rows.

    In order: the one running today, else the soonest still to come, else the
    newest by year. The last is what a row with no dates yet falls back to -
    seeding creates one before any crawl has found out when the festival
    runs, and it is the only row there is at that point.
    """
    today = datetime.date.today()

    running = session.scalars(
        select(Festival)
        .where(Festival.start_date <= today, Festival.end_date >= today)
        .order_by(Festival.start_date.desc())
    ).first()
    if running is not None:
        return running

    upcoming = session.scalars(
        select(Festival).where(Festival.start_date > today).order_by(Festival.start_date)
    ).first()
    if upcoming is not None:
        return upcoming

    return session.scalars(select(Festival).order_by(Festival.year.desc())).first()


def require_current_festival(session: Session) -> Festival:
    """`current_festival`, for the pipelines that cannot proceed without one."""
    festival = current_festival(session)
    if festival is None:
        raise RuntimeError("No festival row found - run `epcot-fw db seed` first.")
    return festival
