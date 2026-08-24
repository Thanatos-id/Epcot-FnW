"""Discovering a past season's per-booth photo posts.

discover_new_urls() always reads the undated hub, which only ever shows the
current season. Backfilling photos from prior years needs a way to point at
one specific past season instead - historical_detail_seeds() does that by
reading that year's own dated hub, the same URL pattern seed_urls() already
uses for the current year.
"""

from pathlib import Path

import httpx
import pytest
import respx

from epcot_fw.fetch import rate_limiter
from epcot_fw.sources.disney_food_blog import BASE_URL, DisneyFoodBlogAdapter

FIXTURES = Path(__file__).parent.parent.parent / "fixtures/html_snapshots/disney_food_blog"
HUB_2025 = FIXTURES / "booth_menus_hub.html"
DATED_HUB_URL = f"{BASE_URL}/2025-epcot-food-and-wine-festival-booths-menus-and-food-photos/"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)


def test_reads_that_years_own_dated_hub_not_the_undated_one():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(DATED_HUB_URL).mock(return_value=httpx.Response(200, text=HUB_2025.read_text()))

        seeds = DisneyFoodBlogAdapter().historical_detail_seeds(2025)

    assert seeds, "expected real per-booth photo-post links from the 2025 fixture"
    assert all(s.page_kind == "booth_detail" for s in seeds)
    urls = {s.url for s in seeds}
    assert any("the-alps-2025-epcot-food-and-wine-festival" in u for u in urls)
    assert any("belgium-2025-epcot-food-and-wine-festival" in u for u in urls)


def test_a_season_that_doesnt_exist_yields_nothing_rather_than_raising():
    """Not every year necessarily used this URL pattern; one missing season
    should not stop a backfill run across several."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(f"{BASE_URL}/2019-epcot-food-and-wine-festival-booths-menus-and-food-photos/").mock(
            return_value=httpx.Response(404, text="<html>not found</html>")
        )

        seeds = DisneyFoodBlogAdapter().historical_detail_seeds(2019)

    assert seeds == []


def test_only_that_years_links_are_returned():
    """The dated hub for one year could in principle still carry a stray link
    to a different year's post; historical_detail_seeds must not pick those
    up any more than the current-year discovery does."""
    html = """
    <article>
    <p><strong><a href="https://www.disneyfoodblog.com/italy-2025-epcot-food-and-wine-festival/">Italy</a>
    &lt;&#8211; CLICK TO SEE PHOTOS OF MENU ITEMS!</strong></p>
    <p><strong><a href="https://www.disneyfoodblog.com/italy-2024-epcot-food-and-wine-festival/">Italy (last year)</a>
    &lt;&#8211; CLICK TO SEE PHOTOS OF MENU ITEMS!</strong></p>
    </article>
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(DATED_HUB_URL).mock(return_value=httpx.Response(200, text=html))

        seeds = DisneyFoodBlogAdapter().historical_detail_seeds(2025)

    urls = {s.url for s in seeds}
    assert any("italy-2025" in u for u in urls)
    assert not any("italy-2024" in u for u in urls)
