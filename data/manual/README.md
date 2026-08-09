# Curated data

Hand-surveyed facts that no crawled source publishes.

## Why this exists

Sorting booths by distance needs coordinates, and not one of the seven
crawled sources emits a latitude. Booth positions are stable season to
season, so this is worth surveying once and keeping.

## How to survey

Stand at the booth, take the coordinate from any phone maps app, and add an
entry to `booth_locations.json`:

```json
{
  "booths": [
    {
      "name": "The Alps",
      "latitude": 28.370536,
      "longitude": -81.549472,
      "location_description": "World Showcase, between Germany and Italy"
    }
  ]
}
```

Then apply it:

```bash
epcot-fw manual        # stage + re-resolve
```

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
