# Data ledger

Builds `docs/index.html` — a self-contained page showing the current state of
the crawled festival database, what changed since the previous snapshot, and
how well tested the pipeline producing those numbers is.

## Building

```bash
python tools/data_ledger/export_snapshot.py   # DB  -> epcot_db_snapshot.json
python tools/data_ledger/fetch_images.py      # adds inlined booth photos
python tools/data_ledger/build_artifact.py    # -> docs/index.html
```

`epcot_db_snapshot.json` is gitignored — it is a build input, regenerated from
the database, and carries ~1.3MB of inlined image data.

## Change tracking

`build_artifact.py` records each snapshot's aggregate metrics into
`ledger_history.json` (committed) and renders a **What changed** section
comparing the current snapshot with the previous one. Metric direction is
declared in `metrics.py`: most counts are better when they rise, while
`open_conflicts` is better when it falls, so a drop there renders as a gain
rather than a loss.

Rebuilding without a fresh crawl does not append a duplicate row — an entry
whose metrics match the newest one replaces it in place, so the page never
shows a fabricated "no change" comparison against itself.

The first entry is a **baseline**: with nothing to compare against, the page
says so instead of rendering zero-deltas.

## Pipeline confidence

`pipeline_metrics.json` holds the test-coverage readings shown in the
confidence panel. Refresh the `current` block after a coverage run:

```bash
python -m pytest --cov=src/epcot_fw --cov-report=json:coverage.json -q
python tools/data_ledger/record_pipeline_metrics.py coverage.json <test-count>
```

The `baseline` block is a fixed historical measurement of a specific commit
and is intentionally not recomputed.

## Layout

The page is responsive and is expected to be read on a phone as well as a
desktop. Two things to preserve when editing the template:

- the `<meta name="viewport">` tag — without it, mobile browsers lay the page
  out at ~980px and scale it down, which is what made the ledger unreadable on
  a phone before;
- no element may exceed the viewport width. `tools/data_ledger` has no browser
  test harness, so check by loading `docs/index.html` at 320px, 390px, 768px
  and 1440px and confirming `document.documentElement.scrollWidth` never
  exceeds `clientWidth`.
