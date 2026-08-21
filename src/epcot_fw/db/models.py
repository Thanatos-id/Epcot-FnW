import datetime
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from epcot_fw.db.base import Base

# --------------------------------------------------------------------------
# Provenance / staging layer
# --------------------------------------------------------------------------


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    crawl_delay_sec: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=5)
    notes: Mapped[str | None] = mapped_column(Text)


class RawPage(Base):
    __tablename__ = "raw_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    page_kind: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    raw_html: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_unchanged_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("raw_pages.id"))

    source: Mapped["Source"] = relationship()

    __table_args__ = (
        Index("ix_raw_pages_url", "url"),
        Index("ix_raw_pages_source_hash", "source_id", "content_hash"),
    )


class ExtractedRecord(Base):
    __tablename__ = "extracted_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_page_id: Mapped[int] = mapped_column(ForeignKey("raw_pages.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    extractor_version: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    natural_key_hint: Mapped[str | None] = mapped_column(Text)
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("extracted_records.id"))

    source: Mapped["Source"] = relationship()
    raw_page: Mapped["RawPage"] = relationship()

    __table_args__ = (Index("ix_extracted_entity_key", "entity_type", "natural_key_hint"),)


class CanonicalLink(Base):
    __tablename__ = "canonical_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_id: Mapped[int] = mapped_column(Integer, nullable=False)
    extracted_record_id: Mapped[int] = mapped_column(
        ForeignKey("extracted_records.id"), nullable=False, unique=True
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    match_method: Mapped[str | None] = mapped_column(Text)
    matched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_canonical_links_entity", "entity_type", "canonical_id"),)


class EntityFieldProvenance(Base):
    __tablename__ = "entity_field_provenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_id: Mapped[int] = mapped_column(Integer, nullable=False)
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    extracted_record_id: Mapped[int] = mapped_column(
        ForeignKey("extracted_records.id"), nullable=False
    )
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source: Mapped["Source"] = relationship()

    __table_args__ = (
        Index("ix_field_prov_entity", "entity_type", "canonical_id", "field_name"),
        UniqueConstraint(
            "entity_type",
            "canonical_id",
            "field_name",
            "source_id",
            "extracted_record_id",
            name="uq_field_prov_candidate",
        ),
    )


class MergeConflict(Base):
    __tablename__ = "merge_conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_id: Mapped[int | None] = mapped_column(Integer)
    field_name: Mapped[str | None] = mapped_column(Text)
    candidate_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    resolution_value: Mapped[dict | None] = mapped_column(JSONB)
    opened_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_type: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_by: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    stats: Mapped[dict | None] = mapped_column(JSONB)


# --------------------------------------------------------------------------
# Canonical entity layer
# --------------------------------------------------------------------------


class Festival(Base):
    __tablename__ = "festivals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="upcoming")
    official_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    booths: Mapped[list["Booth"]] = relationship(back_populates="festival")
    concert_events: Mapped[list["ConcertEvent"]] = relationship(back_populates="festival")
    seminars: Mapped[list["Seminar"]] = relationship(back_populates="festival")


class Booth(Base):
    __tablename__ = "booths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stable handle for anything outside this database - saved favourites, deep
    # links, client-side caches. `id` is an autoincrement that a rebuild
    # renumbers and `slug` is derived from a name that sources revise mid-
    # season, so neither can safely be stored by a client.
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=func.gen_random_uuid(), unique=True, nullable=False
    )
    festival_id: Mapped[int] = mapped_column(ForeignKey("festivals.id"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    region_theme: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    location_description: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    image_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    festival: Mapped["Festival"] = relationship(back_populates="booths")
    menu_items: Mapped[list["MenuItem"]] = relationship(back_populates="booth")

    __table_args__ = (UniqueConstraint("festival_id", "slug", name="uq_booths_festival_slug"),)


class DietaryTag(Base):
    __tablename__ = "dietary_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # See Booth.public_id - a favourited dish has to survive both a rename and
    # a full re-resolution of the canonical layer.
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=func.gen_random_uuid(), unique=True, nullable=False
    )
    booth_id: Mapped[int] = mapped_column(ForeignKey("booths.id"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    # Photo of this specific dish/drink, sourced from per-booth photo posts
    # (see sources/disney_food_blog.py). Booth-level photos live on Booth.
    image_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    booth: Mapped["Booth"] = relationship(back_populates="menu_items")
    dietary_tags: Mapped[list["DietaryTag"]] = relationship(
        secondary="menu_item_dietary_tags", backref="menu_items"
    )


class MenuItemDietaryTag(Base):
    __tablename__ = "menu_item_dietary_tags"

    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), primary_key=True)
    dietary_tag_id: Mapped[int] = mapped_column(ForeignKey("dietary_tags.id"), primary_key=True)


class ConcertEvent(Base):
    __tablename__ = "concert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    festival_id: Mapped[int] = mapped_column(ForeignKey("festivals.id"), nullable=False)
    series: Mapped[str] = mapped_column(Text, nullable=False, default="eat_to_the_beat")
    artist_name: Mapped[str] = mapped_column(Text, nullable=False)
    performance_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    venue: Mapped[str] = mapped_column(Text, nullable=False, default="America Gardens Theatre")
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    festival: Mapped["Festival"] = relationship(back_populates="concert_events")
    showtimes: Mapped[list["ConcertShowtime"]] = relationship(back_populates="concert_event")


class ConcertShowtime(Base):
    __tablename__ = "concert_showtimes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    concert_event_id: Mapped[int] = mapped_column(
        ForeignKey("concert_events.id"), nullable=False
    )
    start_time: Mapped[datetime.time] = mapped_column(Time, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    concert_event: Mapped["ConcertEvent"] = relationship(back_populates="showtimes")


class Seminar(Base):
    __tablename__ = "seminars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    festival_id: Mapped[int] = mapped_column(ForeignKey("festivals.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    seminar_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    presenter_names: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[datetime.date | None] = mapped_column(Date)
    start_time: Mapped[datetime.time | None] = mapped_column(Time)
    end_time: Mapped[datetime.time | None] = mapped_column(Time)
    venue: Mapped[str | None] = mapped_column(Text)
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    requires_reservation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    festival: Mapped["Festival"] = relationship(back_populates="seminars")
