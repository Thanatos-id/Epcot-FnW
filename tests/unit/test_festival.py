"""The festival's own two questions: which one is current, and where in its
run it is. `current_festival` needs a database and is covered in
tests/integration/test_festival_selection.py; everything here is pure.
"""

import datetime

import pytest

from epcot_fw.api.schemas import FestivalOut
from epcot_fw.festival import ENDED, RUNNING, UPCOMING, festival_status, festival_year_for

# The 2026 run, which is what the fixtures and the published feed describe.
START = datetime.date(2026, 8, 27)
END = datetime.date(2026, 11, 21)


# ---------------------------------------------------------------------------
# festival_status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "today,expected",
    [
        (datetime.date(2026, 8, 26), UPCOMING),
        (datetime.date(2026, 8, 27), RUNNING),  # opening day is running
        (datetime.date(2026, 9, 13), RUNNING),
        (datetime.date(2026, 11, 21), RUNNING),  # so is closing day
        (datetime.date(2026, 11, 22), ENDED),
    ],
)
def test_status_follows_the_calendar(today, expected):
    assert festival_status(START, END, today=today) == expected


def test_a_running_festival_does_not_report_upcoming():
    """The bug this replaced: the published feed announced `upcoming` for the
    whole of a festival that had been open for weeks, because the column was
    written once at seed time and revised by nothing."""
    eighteen_days_in = datetime.date(2026, 9, 13)

    assert festival_status(START, END, today=eighteen_days_in) == RUNNING


@pytest.mark.parametrize("start,end", [(None, END), (START, None), (None, None)])
def test_unknown_dates_derive_nothing(start, end):
    """A row between seeding and the first crawl has no dates. None tells the
    caller to keep the stored value rather than guess."""
    assert festival_status(start, end, today=datetime.date(2026, 9, 13)) is None


# ---------------------------------------------------------------------------
# festival_year_for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "today,expected",
    [
        (datetime.date(2026, 1, 4), 2026),
        (datetime.date(2026, 8, 15), 2026),
        (datetime.date(2026, 10, 5), 2026),  # mid-festival: stays put
        (datetime.date(2026, 11, 21), 2026),  # closing day: still this year's
        (datetime.date(2026, 12, 1), 2027),
    ],
)
def test_the_year_rolls_over_in_december(today, expected):
    assert festival_year_for(today) == expected


def test_october_does_not_roll_the_year_over():
    """October used to roll over, which seeded a row for next year while this
    year's festival was still serving - and every `ORDER BY year DESC` lookup
    in the codebase then followed the empty future row."""
    mid_festival = datetime.date(2026, 10, 5)

    assert festival_year_for(mid_festival) == 2026


# ---------------------------------------------------------------------------
# what a client actually receives
# ---------------------------------------------------------------------------


def _festival_out(status: str, start=START, end=END) -> FestivalOut:
    return FestivalOut.model_validate(
        {
            "id": 1,
            "year": 2026,
            "name": "EPCOT International Food & Wine Festival",
            "slug": "epcot-food-wine-2026",
            "start_date": start,
            "end_date": end,
            "status": status,
            "official_url": None,
        }
    )


def test_the_payload_overrides_a_stale_stored_status():
    """A row saying `upcoming` during its own run is corrected on the way out,
    so no client has to know the column went stale.

    Dated relative to today so this keeps testing a *running* festival after
    the 2026 dates are history.
    """
    today = datetime.date.today()
    out = _festival_out(
        "upcoming",
        start=today - datetime.timedelta(days=10),
        end=today + datetime.timedelta(days=10),
    )

    assert out.status == RUNNING


def test_the_payload_reports_a_finished_festival_as_ended():
    today = datetime.date.today()
    out = _festival_out(
        "upcoming",
        start=today - datetime.timedelta(days=40),
        end=today - datetime.timedelta(days=10),
    )

    assert out.status == ENDED


def test_the_payload_reports_a_future_festival_as_upcoming():
    today = datetime.date.today()
    out = _festival_out(
        "ended",
        start=today + datetime.timedelta(days=10),
        end=today + datetime.timedelta(days=40),
    )

    assert out.status == UPCOMING


def test_the_payload_keeps_the_stored_status_when_dates_are_unknown():
    """Between seeding and the first crawl there are no dates to derive from,
    and the column is all there is."""
    assert _festival_out("upcoming", start=None, end=None).status == "upcoming"


def test_status_is_one_of_the_three_derived_words():
    assert {UPCOMING, RUNNING, ENDED} == {"upcoming", "running", "ended"}
