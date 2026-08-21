# Curated data

Hand-surveyed facts that no crawled source publishes.

## Why this exists

Sorting booths by distance needs coordinates, and not one of the seven
crawled sources emits a latitude. Booth positions are stable season to
season, so this is worth surveying once and keeping.

## How to survey

Open **`docs/survey.html`** on a phone in the park — published alongside the
ledger, so it's one tap from the home-screen icon. Walk up to a booth, hit
Capture, and the browser's own GPS fix goes into the list. It keeps what you
capture in local storage, so closing the tab or losing signal mid-lap doesn't
lose the morning's work, and Copy JSON at the end gives you exactly the block
below to paste in.

By hand, an entry looks like this:

```json
{
  "booths": [
    {
      "name": "The Alps",
      "latitude": 28.370536,
      "longitude": -81.549472,
      "location_precision": "surveyed",
      "location_description": "World Showcase, between Germany and Italy"
    }
  ]
}
```

Then apply it:

```bash
epcot-fw manual        # stage + re-resolve
```

## Two grades of coordinate

`location_precision` records what a number is worth, because two very
different things end up in the same column:

- **`surveyed`** — a GPS fix taken standing at the booth. Good to a few
  metres. This is the real thing.
- **`anchored`** — the published coordinate of the pavilion a booth is named
  after, standing in until someone surveys it. Good to 30–50 m: enough to put
  a booth on the right side of World Showcase, not enough to order two booths
  you can see at the same time.

Eight booths ship anchored, from the Wikipedia/Wikidata pavilion coordinates.
Everything else — Refreshment Outpost, Brew-Wing Lab, and every themed kiosk
like Swirled Showcase or Bramblewood Bites — has no coordinate at all,
because nobody publishes one. A surveyed fix always supersedes an anchor: it
lands in the same file, and later wins on recency.

A client that shows a distance is expected to qualify an anchored one
("about 200 ft, approximate") rather than presenting it as measured.

This also runs automatically at the start of every crawl and refresh, so an
edit is picked up on the next scheduled run either way.

## Rules worth knowing

- **`name` is matched fuzzily** against booths for the current festival,
  exactly the way a crawled record is, so it needn't be byte-identical to the
  canonical name. A name that matches nothing confidently is left alone
  rather than guessed at.
- **Omit what you haven't surveyed.** A missing field stays open for a source
  to fill later; a wrong number wins forever. Nulls are never merged.
- **These values beat every crawled source.** The `manual` source has
  `priority_rank = 0`, so a correction entered here is never overwritten by a
  later refresh — and `/api/v1/booths/{id}/provenance` will show the value
  came from curation.
- **Editing a value supersedes it.** Re-applying an unchanged file is a
  no-op; changing one stages a correction that wins on recency.
- Coordinates are decimal degrees (WGS84). Five decimal places is roughly a
  metre, far more precision than distance-sorting needs.
