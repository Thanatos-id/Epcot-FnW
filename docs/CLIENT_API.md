# Client data feed

One file, versioned, static:

```
https://thanatos-id.github.io/Epcot-FnW/v1/snapshot.json
```

Everything an app needs for one festival — booths, dishes, concerts,
seminars — in a single response. ~84 KB, ~18 KB over the wire once GitHub
Pages gzips it.

## Why a file and not a server

At 33 booths and 229 dishes there is nothing an API would buy that a file
does not already give: it is edge-cached, has no uptime to lose, costs
nothing, and answers a re-check with a 304 and no body. A live
`/api/v1/snapshot` exists in this repo and serves **the same bytes from the
same builder**, so moving to it later is a URL change and nothing else.

Keep the URL configurable in the app from day one. GitHub Pages frames itself
as project hosting rather than production infrastructure (~100 GB/month), which
is effectively unlimited at 18 KB a fetch but is the thing to outgrow first.

## Shape

```jsonc
{
  "schema_version": 1,          // bumped only for a breaking change
  "data_updated_at": "2026-08-22T22:17:48.564329Z",
  "min_app_version": null,      // see below
  "festival":  { "name": "...", "start_date": "...", "status": "upcoming" },
  "booths":    [ /* … */ ],
  "menu_items":[ /* … */ ],     // flat, keyed to booths by booth_id
  "events":    [ /* … */ ],
  "seminars":  [ /* … */ ]
}
```

Menu items are flat rather than nested inside booths so a client can index
them however it likes — by booth, by dietary tag, by price — without walking
a tree.

### Fields that matter

| field | why |
|---|---|
| `public_id` | **Save this, never `id`.** A UUID that survives rebuilds; `id` is an autoincrement that renumbers, so a favourite keyed on it comes back pointing at a different dish. |
| `latitude` / `longitude` | Null for most booths. Only 8 are placed today. |
| `location_precision` | `surveyed` (GPS at the booth, metres), `anchored` (pavilion coordinate standing in, 30–50 m), or `null`. **Qualify the distance you show for an anchored booth** — "about 200 ft" — rather than presenting it as measured. |
| `dietary_tags` | Keyword matches against a food blog's copy, **not Disney allergen data**. Fine for filtering a menu, never an allergen check. Say so in the UI. |
| `is_active` | Always true here; retired rows are filtered out before publishing. |
| `data_updated_at` | When the data last changed, not when the file was built — so an unchanged database produces an identical file and a stable ETag. |
| `min_app_version` | Null today. Setting it is how a future breaking change gets rolled out: publish `/v2/`, then set this on `/v1/` so old builds show "please update" instead of quietly misreading data. Read it and honour it from your first release, or it is useless when you need it. |

## Fetching it

```swift
var request = URLRequest(url: snapshotURL)
request.cachePolicy = .useProtocolCachePolicy   // URLCache handles the ETag

let decoder = JSONDecoder()
decoder.dateDecodingStrategy = .iso8601WithFractionalSeconds
```

`price_usd` is a **string** (`"6.50"`), not a float — decimal money should not
round-trip through binary floating point. Decode it to `Decimal`.

Three rules worth building in from the start:

1. **Ship a copy in the app bundle.** First launch works with no network, and
   so does App Review — which happens in Cupertino, 2,500 miles from the
   nearest booth. An empty screen there is a rejection.
2. **Never block on the fetch.** Render what you have, refresh in the
   background, swap in the newer copy. A failed request should be invisible.
3. **Treat `schema_version` as a gate.** A version you don't recognise means
   keep the bundled copy rather than decoding something you may misread.

## Regenerating

Written by `tools/data_ledger/export_snapshot.py` alongside the ledger's own
snapshot, in one database session, so the published feed and the ledger can
never disagree about what is in the database.

```bash
epcot-fw refresh
python tools/data_ledger/export_snapshot.py
git add docs/v1/snapshot.json && git commit && git push
```

GitHub Pages redeploys on push, usually within a minute.

## Changing the shape

Adding an optional field is safe. Anything else — renaming, removing,
retyping — is not, because builds already installed cannot be taught the new
shape. Publish `/v2/snapshot.json` beside this one and leave `/v1/` serving
until the old builds are gone.
