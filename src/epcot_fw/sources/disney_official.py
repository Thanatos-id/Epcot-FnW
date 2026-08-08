import datetime
import re

from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.html_utils import clean_text, soupify
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter

BASE_URL = "https://disneyworld.disney.go.com"
FESTIVAL_PATH = "/events-tours/epcot/epcot-international-food-and-wine-festival/"

# "Embark on a culinary adventure across 6 different continents—from August 27
#  to November 21, 2026." - as published on the live overview page 2026-08-08.
_DATE_RANGE_RE = re.compile(
    r"from\s+([A-Z][a-z]+\s+\d{1,2})\s+to\s+([A-Z][a-z]+\s+\d{1,2}),?\s+(\d{4})"
)


class DisneyOfficialAdapter(SourceAdapter):
    key = "disney_official"
    priority_rank = 1

    def seed_urls(self, festival_year: int) -> list[SeedUrl]:
        return [
            SeedUrl(url=f"{BASE_URL}{FESTIVAL_PATH}", page_kind="festival_overview"),
        ]

    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
        soup = soupify(raw_html)
        main = soup.find("main") or soup
        text = clean_text(main.get_text(" "))
        records: list[ExtractedRecordDTO] = []

        title_tag = soup.find("h1")
        name = clean_text(title_tag.get_text()) if title_tag else "EPCOT International Food & Wine Festival"

        date_match = _DATE_RANGE_RE.search(text)
        start_date: datetime.date | None = None
        end_date: datetime.date | None = None
        year: int | None = None
        if date_match:
            start_str, end_str, year_str = date_match.groups()
            year = int(year_str)
            try:
                start_date = datetime.datetime.strptime(f"{start_str} {year}", "%B %d %Y").date()
                end_date = datetime.datetime.strptime(f"{end_str} {year}", "%B %d %Y").date()
            except ValueError:
                pass

        records.append(
            ExtractedRecordDTO(
                entity_type="festival",
                natural_key_hint=normalize_name(name),
                payload={
                    "name": name,
                    "year": year,
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "official_url": url,
                },
            )
        )

        # Global Marketplaces (booth) listings are published closer to the
        # festival start; the live page shows "Check back soon for more
        # details!" as a placeholder until then. When real booth cards exist
        # they render as headed list items - pick up anything under a
        # "Global Marketplace" heading that isn't the placeholder copy.
        marketplace_heading = main.find(
            string=re.compile(r"Global Marketplaces?", re.IGNORECASE)
        )
        if marketplace_heading and "check back soon" not in text.lower():
            heading_tag = marketplace_heading.find_parent(["h2", "h3", "h4"])
            if heading_tag:
                for item in heading_tag.find_all_next(["h3", "h4", "li"], limit=100):
                    label = clean_text(item.get_text())
                    if not label or len(label) > 80:
                        continue
                    records.append(
                        ExtractedRecordDTO(
                            entity_type="booth",
                            natural_key_hint=normalize_name(label),
                            payload={"name": label, "category": "global_marketplace"},
                        )
                    )

        return records
