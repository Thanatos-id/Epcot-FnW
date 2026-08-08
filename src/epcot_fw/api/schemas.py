import datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Meta(BaseModel):
    total: int
    page: int
    page_size: int


class ListResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: Meta


class DietaryTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    label: str


class FestivalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    year: int
    name: str
    slug: str
    start_date: datetime.date | None
    end_date: datetime.date | None
    status: str
    official_url: str | None


class BoothOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    festival_id: int
    canonical_name: str
    slug: str
    category: str | None
    region_theme: str | None
    description: str | None
    location_description: str | None
    image_url: str | None
    is_active: bool
    average_rating: float | None = None
    review_count: int = 0


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reviewer_name: str | None
    rating: Decimal
    rating_raw: Decimal | None
    recommended: bool | None
    review_text: str | None
    review_url: str | None
    reviewed_at: datetime.date | None
    match_method: str
    is_user_submitted: bool


class ReviewCreate(BaseModel):
    reviewer_name: str | None = None
    rating: Decimal
    review_text: str | None = None


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    booth_id: int
    canonical_name: str
    description: str | None
    category: str
    price_usd: Decimal | None
    is_active: bool
    dietary_tags: list[DietaryTagOut] = []


class BoothDetailOut(BoothOut):
    menu_items: list[MenuItemOut] = []


class ConcertShowtimeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    start_time: datetime.time
    notes: str | None


class ConcertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    festival_id: int
    series: str
    artist_name: str
    performance_date: datetime.date
    venue: str
    description: str | None
    image_url: str | None
    showtimes: list[ConcertShowtimeOut] = []


class SeminarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    festival_id: int
    title: str
    seminar_type: str
    description: str | None
    presenter_names: str | None
    event_date: datetime.date | None
    start_time: datetime.time | None
    end_time: datetime.time | None
    venue: str | None
    price_usd: Decimal | None
    requires_reservation: bool


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    display_name: str
    base_url: str
    priority_rank: int
    enabled: bool


class CrawlRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_type: str
    triggered_by: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    status: str
    stats: dict | None


class FieldProvenanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    field_name: str
    source_key: str
    value: object
    observed_at: datetime.datetime
    is_selected: bool
