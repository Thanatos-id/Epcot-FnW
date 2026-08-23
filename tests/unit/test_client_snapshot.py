"""The published client contract.

`docs/v1/snapshot.json` is what an installed app downloads. Once a build is
on someone's phone the shape cannot be taken back, so these guard the file as
committed - not the code that writes it.
"""

import json
from pathlib import Path

import pytest

from epcot_fw.api.routers.snapshot import SCHEMA_VERSION
from epcot_fw.api.schemas import SnapshotOut

PUBLISHED = Path(__file__).parent.parent.parent / "docs/v1/snapshot.json"


@pytest.fixture(scope="module")
def raw() -> str:
    assert PUBLISHED.exists(), "the client snapshot must be published, not just built locally"
    return PUBLISHED.read_text()


@pytest.fixture(scope="module")
def payload(raw) -> dict:
    return json.loads(raw)


def test_the_published_file_is_the_schema_the_api_serves(payload):
    """The promise the whole design rests on: a client can point at the static
    file or a live /api/v1/snapshot and decode both with the same code."""
    SnapshotOut.model_validate(payload)


def test_it_announces_which_contract_it_is(payload):
    assert payload["schema_version"] == SCHEMA_VERSION
    assert "data_updated_at" in payload
    assert "min_app_version" in payload, "reserved now; unaddable later without breaking clients"


def test_everything_a_client_can_save_has_a_stable_id(payload):
    """Favourites outlive rebuilds. `id` is an autoincrement that renumbers,
    so a saved favourite keyed on it would come back pointing at some other
    dish entirely."""
    for row in payload["booths"] + payload["menu_items"]:
        assert row["public_id"], row["canonical_name"]
    ids = [r["public_id"] for r in payload["booths"] + payload["menu_items"]]
    assert len(ids) == len(set(ids))


def test_every_item_belongs_to_a_booth_in_the_same_payload(payload):
    booth_ids = {b["id"] for b in payload["booths"]}
    orphans = [i["canonical_name"] for i in payload["menu_items"] if i["booth_id"] not in booth_ids]
    assert orphans == []


def test_retired_rows_are_not_shipped(payload):
    """A booth that stopped running would send a guest somewhere that is not
    there. See pipeline/reconcile.py."""
    assert all(b["is_active"] for b in payload["booths"])
    assert all(i["is_active"] for i in payload["menu_items"])


def test_it_is_written_compactly_so_the_etag_holds_still(raw):
    """Pretty-printing would churn whitespace on every build, changing the
    ETag and making returning clients re-download a payload they already
    have. Sorted keys and no spaces mean an unchanged database writes an
    identical file."""
    assert ", " not in raw[:400], "expected compact separators"
    assert raw.endswith("\n")
    reserialised = json.dumps(
        json.loads(raw), sort_keys=True, separators=(",", ":"), default=str
    )
    assert raw.rstrip("\n") == reserialised, "keys should already be sorted on disk"


def test_it_stays_small_enough_to_fetch_on_a_park_wifi(raw):
    """Not a style rule - it is why this can be a static file at all. If it
    ever grows past a megabyte, that is the signal to paginate or split."""
    assert len(raw.encode()) < 1_000_000
