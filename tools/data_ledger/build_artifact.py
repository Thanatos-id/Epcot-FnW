"""Renders docs/index.html from the exported snapshot.

    python tools/data_ledger/export_snapshot.py
    python tools/data_ledger/fetch_images.py
    python tools/data_ledger/build_artifact.py

Beyond rendering the snapshot, this records the snapshot's aggregate metrics
into ledger_history.json (see metrics.py) so the page can show what was
gained and lost since the previous build, and reads pipeline_metrics.json for
the test-coverage confidence panel.
"""

import datetime
import html
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import build_editor  # noqa: E402
import build_map  # noqa: E402
import build_survey  # noqa: E402
import metrics  # noqa: E402

TOOL_DIR = pathlib.Path(__file__).parent
ASSETS_DIR = TOOL_DIR / "assets"
DOCS_DIR = TOOL_DIR.parent.parent / "docs"

data = json.loads((TOOL_DIR / "epcot_db_snapshot.json").read_text())

PIPELINE_PATH = TOOL_DIR / "pipeline_metrics.json"
pipeline = json.loads(PIPELINE_PATH.read_text()) if PIPELINE_PATH.exists() else {}

_last_run = (data.get("runs") or [{}])[0]
history, current_entry, previous_entry = metrics.record_snapshot(
    data,
    pipeline=pipeline.get("current"),
    label=_last_run.get("started_at") or "snapshot",
)
diff_rows = metrics.diff_metrics(
    previous_entry["data"] if previous_entry else None, current_entry["data"]
)

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light dark" />
<meta name="description" content="Data quality ledger for the crawled Epcot International Food &amp; Wine Festival database: booths, menus, sources, conflicts, and snapshot-over-snapshot change tracking." />
<title>Epcot Food &amp; Wine — Data Ledger</title>

<!-- Icons. Paths are relative on purpose: docs/ is published at a project
     subpath (…github.io/Epcot-FnW/), so root-absolute "/icons/…" would 404.
     Relative also keeps the page working opened straight off disk.
     These are real files rather than inlined data: URIs because iOS ignores
     data: URIs for apple-touch-icon, which is the one that matters for
     "Add to Home Screen". -->
<link rel="manifest" href="manifest.json" />
<link rel="icon" href="icons/favicon.ico" sizes="any" />
<link rel="icon" type="image/svg+xml" href="icons/icon.svg" />
<!-- Required (in addition to the manifest) for iOS to use this on the home
     screen. 180x180 and fully opaque - iOS fills transparent pixels black. -->
<link rel="apple-touch-icon" sizes="180x180" href="icons/apple-touch-icon.png" />
<meta name="apple-mobile-web-app-title" content="Epcot F&amp;W" />
<meta name="application-name" content="Epcot F&amp;W" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="default" />
<!-- Browser/OS chrome is tinted to match the page rather than the icon's
     navy, so an installed window doesn't sit under a mismatched bar. The
     manifest keeps the brand navy for the launch splash. -->
<meta name="theme-color" content="#efe8d8" media="(prefers-color-scheme: light)" />
<meta name="theme-color" content="#1b1510" media="(prefers-color-scheme: dark)" />
<style>
:root {
  --bg: #efe8d8;
  --surface: #fbf7ee;
  --surface-2: #f3ebd8;
  --ink: #241c16;
  --ink-muted: #6b5d4f;
  --accent: #7a2036;
  --accent-soft: #f0dce0;
  --gold: #a9752b;
  --gold-soft: #f1e2c4;
  --border: #ddd0b5;
  --good: #4f7a45;
  --good-soft: #e1ebdb;
  --warn: #bb5a2c;
  --warn-soft: #f3e1d2;
  --shadow: 0 1px 2px rgba(36,28,22,0.06), 0 8px 24px rgba(36,28,22,0.06);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #1b1510;
    --surface: #241d16;
    --surface-2: #2c231a;
    --ink: #f3ecdd;
    --ink-muted: #b8aa93;
    --accent: #e0899c;
    --accent-soft: #3a2029;
    --gold: #d9a24b;
    --gold-soft: #3a2e18;
    --border: #3a2f23;
    --good: #8fc97f;
    --good-soft: #24301f;
    --warn: #e0935c;
    --warn-soft: #3a2618;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
  }
}
:root[data-theme="dark"] {
  --bg: #1b1510; --surface: #241d16; --surface-2: #2c231a; --ink: #f3ecdd;
  --ink-muted: #b8aa93; --accent: #e0899c; --accent-soft: #3a2029; --gold: #d9a24b;
  --gold-soft: #3a2e18; --border: #3a2f23; --good: #8fc97f; --good-soft: #24301f;
  --warn: #e0935c; --warn-soft: #3a2618;
  --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
}
:root[data-theme="light"] {
  --bg: #efe8d8; --surface: #fbf7ee; --surface-2: #f3ebd8; --ink: #241c16;
  --ink-muted: #6b5d4f; --accent: #7a2036; --accent-soft: #f0dce0; --gold: #a9752b;
  --gold-soft: #f1e2c4; --border: #ddd0b5; --good: #4f7a45; --good-soft: #e1ebdb;
  --warn: #bb5a2c; --warn-soft: #f3e1d2;
  --shadow: 0 1px 2px rgba(36,28,22,0.06), 0 8px 24px rgba(36,28,22,0.06);
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
}
img { max-width: 100%; }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
}
.wrap {
  max-width: 1080px; margin: 0 auto;
  padding: clamp(20px, 5vw, 40px) clamp(14px, 4vw, 24px) 72px;
}

.display { font-family: Georgia, "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif; }
.mono { font-family: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace; font-variant-numeric: tabular-nums; }

/* ---------- header ---------- */
header.top { margin-bottom: 28px; }
.eyebrow {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--accent); font-weight: 600; margin-bottom: 10px;
}
.eyebrow::before {
  content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--accent);
}
h1.display {
  font-size: clamp(24px, 6vw, 34px); margin: 0 0 8px; text-wrap: balance; font-weight: 600;
  letter-spacing: -0.01em; overflow-wrap: break-word;
}
.subtitle { color: var(--ink-muted); font-size: clamp(14px, 3.4vw, 15px); max-width: 62ch; }
.subtitle b { color: var(--ink); font-weight: 600; }

/* ---------- stat strip ---------- */
.stats {
  display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px;
  margin: 24px 0 32px;
}
@media (max-width: 900px) { .stats { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 460px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; } }
.stat {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: clamp(11px, 3vw, 16px); box-shadow: var(--shadow); min-width: 0;
}
.stat .num {
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-variant-numeric: tabular-nums;
  font-size: clamp(18px, 5vw, 26px); font-weight: 600; color: var(--ink);
  overflow-wrap: break-word;
}
.stat .label {
  font-size: clamp(10px, 2.6vw, 12px); color: var(--ink-muted); margin-top: 2px;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.stat.accent .num { color: var(--accent); }
.stat.warn .num { color: var(--warn); }

/* ---------- section shell ---------- */
section { margin-bottom: 34px; }
.section-head {
  display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
  margin-bottom: 14px; flex-wrap: wrap;
}
h2.display { font-size: clamp(17px, 4.4vw, 20px); margin: 0; font-weight: 600; }
.section-note { font-size: clamp(12px, 3vw, 13px); color: var(--ink-muted); }

/* ---------- change ledger ---------- */
.panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--shadow); overflow: hidden;
}
.panel-banner {
  padding: 11px 14px; font-size: 12.5px; color: var(--ink-muted);
  background: var(--surface-2); border-bottom: 1px solid var(--border);
}
.panel-banner b { color: var(--ink); font-weight: 600; }
.delta-row {
  display: grid; grid-template-columns: minmax(0,1fr) auto auto;
  gap: 8px 12px; align-items: center;
  padding: 11px 14px; border-bottom: 1px solid var(--border);
}
.delta-row:last-child { border-bottom: none; }
.delta-row:nth-child(even) { background: var(--surface-2); }
.delta-label { font-size: 13.5px; min-width: 0; overflow-wrap: break-word; }
.delta-sub { display: block; font-size: 11.5px; color: var(--ink-muted); margin-top: 1px; }
.delta-value {
  font-family: ui-monospace, monospace; font-variant-numeric: tabular-nums;
  font-size: 14px; font-weight: 600; white-space: nowrap;
}
.delta-chip {
  font-family: ui-monospace, monospace; font-variant-numeric: tabular-nums;
  font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 20px;
  white-space: nowrap; min-width: 52px; text-align: center;
}
.delta-chip.gain { background: var(--good-soft); color: var(--good); }
.delta-chip.loss { background: var(--warn-soft); color: var(--warn); }
.delta-chip.same { background: var(--surface-2); color: var(--ink-muted); }
.delta-chip.none { background: transparent; color: var(--ink-muted); }
@media (max-width: 460px) {
  .delta-row { grid-template-columns: minmax(0,1fr) auto; row-gap: 4px; }
  .delta-chip { grid-column: 2; }
  .delta-value { grid-column: 1; grid-row: 2; font-size: 13px; }
}

/* ---------- pipeline confidence ---------- */
.confidence-grid {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 14px;
}
@media (max-width: 560px) { .confidence-grid { grid-template-columns: minmax(0, 1fr); } }
.confidence-metric {
  border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; background: var(--surface-2);
  min-width: 0;
}
.confidence-metric h4 {
  margin: 0 0 8px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--ink-muted); font-weight: 600;
}
.confidence-nums { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.confidence-before {
  font-family: ui-monospace, monospace; font-size: 14px; color: var(--ink-muted);
  text-decoration: line-through;
}
.confidence-arrow { color: var(--ink-muted); font-size: 12px; }
.confidence-after {
  font-family: ui-monospace, monospace; font-size: clamp(20px, 5vw, 24px); font-weight: 700; color: var(--good);
}
.meter {
  margin-top: 10px; height: 7px; border-radius: 20px; background: var(--border); overflow: hidden;
}
.meter > span { display: block; height: 100%; border-radius: 20px; background: var(--good); }
.confidence-foot { padding: 0 14px 14px; font-size: 12px; color: var(--ink-muted); }

/* ---------- sources ---------- */
.sources-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px;
}
@media (max-width: 420px) { .sources-grid { grid-template-columns: minmax(0, 1fr); } }
.source-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; min-width: 0;
}
.source-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.source-name { font-weight: 600; font-size: 13.5px; min-width: 0; overflow-wrap: break-word; }
.source-url { font-size: 12px; color: var(--ink-muted); overflow-wrap: anywhere; }
.pill {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 20px; white-space: nowrap;
}
.pill.on { background: var(--good-soft); color: var(--good); }
.pill.off { background: var(--surface-2); color: var(--ink-muted); }
.priority-tag { font-size: 11px; color: var(--ink-muted); font-family: ui-monospace, monospace; }

/* ---------- filter bar ---------- */
.filter-bar {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 12px; margin-bottom: 16px; position: sticky; top: 12px; z-index: 5;
  box-shadow: var(--shadow);
}
/* On a phone a sticky filter bar with wrapped chip rows can eat half the
   viewport, so it scrolls away with the page instead. */
@media (max-width: 700px) { .filter-bar { position: static; } }
#search {
  flex: 1 1 220px; min-width: 0; background: var(--bg); color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 16px;
  font-family: inherit;
}
@media (max-width: 700px) { #search { flex-basis: 100%; } }
#search:focus-visible, .chip:focus-visible, summary:focus-visible, a:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; min-width: 0; }
.chip {
  border: 1px solid var(--border); background: var(--surface); color: var(--ink-muted);
  border-radius: 20px; padding: 8px 13px; font-size: 12.5px; cursor: pointer;
  font-family: inherit; transition: background 0.12s, color 0.12s, border-color 0.12s;
  min-height: 36px;
}
.chip:hover { border-color: var(--accent); color: var(--ink); }
.chip.active { background: var(--accent); border-color: var(--accent); color: var(--surface); }
#result-count { font-size: 12.5px; color: var(--ink-muted); white-space: nowrap; }

/* ---------- booths ---------- */
.booth-list { display: flex; flex-direction: column; gap: 8px; }
details.booth {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  overflow: hidden;
}
details.booth[open] { box-shadow: var(--shadow); }
summary.booth-head {
  list-style: none; cursor: pointer; padding: 12px 14px;
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  min-height: 44px; flex-wrap: wrap;
}
summary.booth-head::-webkit-details-marker { display: none; }
.booth-title { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1 1 auto; }
.booth-caret { color: var(--ink-muted); font-size: 11px; transition: transform 0.15s; flex: none; }
details[open] .booth-caret { transform: rotate(90deg); }
.booth-name {
  font-family: Georgia, "Iowan Old Style", serif; font-weight: 600;
  font-size: clamp(14.5px, 3.8vw, 16px); min-width: 0; overflow-wrap: break-word;
}
.booth-meta {
  display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--ink-muted);
  flex-wrap: wrap;
}
@media (max-width: 460px) {
  .booth-meta { width: 100%; padding-left: 50px; }
}
.item-count { font-family: ui-monospace, monospace; font-size: 12.5px; color: var(--ink-muted); }

.booth-thumb {
  width: 40px; height: 40px; border-radius: 8px; object-fit: cover; flex: none;
  border: 1px solid var(--border); background: var(--surface-2);
}
.booth-thumb-placeholder {
  width: 40px; height: 40px; border-radius: 8px; flex: none;
  border: 1px dashed var(--border); background: var(--surface-2);
  display: flex; align-items: center; justify-content: center;
  color: var(--ink-muted); font-size: 15px;
}

.booth-photo {
  width: 100%; max-height: clamp(160px, 40vw, 240px); object-fit: cover; display: block;
  border-bottom: 1px solid var(--border);
}

.item-table { border-top: 1px solid var(--border); }
.item-row {
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 10px; align-items: baseline;
  padding: 9px 14px; border-bottom: 1px solid var(--border);
}
.item-row:last-child { border-bottom: none; }
.item-row:nth-child(even) { background: var(--surface-2); }
.cat-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex: none; }
.cat-dot.food { background: var(--gold); }
.cat-dot.alcoholic_beverage { background: var(--accent); }
.cat-dot.non_alcoholic_beverage { background: var(--ink-muted); }
.item-main { min-width: 0; }
.item-name { font-size: 13.5px; overflow-wrap: break-word; }
.item-desc {
  font-size: 12.5px; color: var(--ink-muted); line-height: 1.45; margin-top: 3px;
  overflow-wrap: break-word;
}
.item-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }
.tag {
  font-size: 10px; padding: 2px 7px; border-radius: 20px; background: var(--gold-soft);
  color: var(--gold); font-weight: 600; letter-spacing: 0.02em;
}
.item-price { font-family: ui-monospace, monospace; font-size: 13px; font-variant-numeric: tabular-nums; color: var(--ink); white-space: nowrap; }
.item-price.unknown { color: var(--ink-muted); font-style: italic; font-family: inherit; font-size: 12px; }

/* Dish photo floats beside the name so a row without one keeps its
   existing compact height. */
.dish-thumb {
  float: left; width: 64px; height: 64px; object-fit: cover; border-radius: 8px;
  border: 1px solid var(--border); background: var(--surface-2);
  margin: 0 10px 6px 0;
}
.item-row.has-photo .item-main::after { content: ""; display: block; clear: both; }
@media (max-width: 460px) { .dish-thumb { width: 52px; height: 52px; } }

/* ---------- conflicts ---------- */
.conflict-list { display: flex; flex-direction: column; gap: 8px; }
.conflict {
  background: var(--warn-soft); border: 1px solid var(--warn); border-radius: 8px;
  padding: 10px 13px; font-size: 13px; display: flex; gap: 10px; align-items: flex-start;
  flex-wrap: wrap;
}
.conflict-badge {
  flex: none; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  color: var(--warn); background: var(--surface); border: 1px solid var(--warn);
  padding: 2px 7px; border-radius: 20px; margin-top: 1px;
}
.conflict-text { color: var(--ink); overflow-wrap: break-word; }
.conflict-text b { font-weight: 600; }

/* ---------- runs / footer ---------- */
.run-row {
  display: flex; justify-content: space-between; gap: 10px; padding: 10px 13px;
  border-bottom: 1px solid var(--border); font-size: 13px; flex-wrap: wrap;
}
.run-row:last-child { border-bottom: none; }
.run-badge { font-family: ui-monospace, monospace; font-size: 11px; color: var(--ink-muted); }
.runs-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
}

footer {
  margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);
  font-size: 12.5px; color: var(--ink-muted); display: flex; justify-content: space-between;
  gap: 10px; flex-wrap: wrap;
}
.empty-state { padding: 26px; text-align: center; color: var(--ink-muted); font-size: 13.5px; }

.tag-caveat {
  background: var(--warn-soft); color: var(--warn); border: 1px solid var(--warn);
  border-radius: 8px; padding: 11px 13px; font-size: 13px; line-height: 1.5;
  margin: 0 0 14px;
}
.tag-caveat b { display: block; margin-bottom: 2px; }

.survey-link {
  display: inline-block; font-weight: 600; color: var(--accent); text-decoration: none;
  border: 1px solid var(--accent); border-radius: 8px; padding: 9px 14px; margin-right: 10px;
  min-height: 44px; line-height: 24px;
}
.survey-link:hover, .survey-link:focus { background: var(--accent-soft); }

.overflow-x { overflow-x: auto; -webkit-overflow-scrolling: touch; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>

<div class="wrap">
  <h2 class="sr-only">Interactive browser of the crawled Epcot Food &amp; Wine Festival database: booths, menu items, data sources, unresolved merge conflicts, and data-quality change tracking.</h2>

  <header class="top">
    <div class="eyebrow">Live database snapshot</div>
    <h1 class="display">Epcot Food &amp; Wine — Data Ledger</h1>
    <p class="subtitle">
      <b>__FESTIVAL_NAME__</b> · __FESTIVAL_DATES__ · __FESTIVAL_STATUS__.
      Crawled from __ENABLED_COUNT__ of __SOURCE_TOTAL__ sources, last run __LAST_RUN__.
    </p>
  </header>

  <div class="stats">
    <div class="stat accent"><div class="num mono">__BOOTH_COUNT__</div><div class="label">Booths</div></div>
    <div class="stat accent"><div class="num mono">__ITEM_COUNT__</div><div class="label">Menu items</div></div>
    <div class="stat"><div class="num mono">__ENABLED_COUNT__/__SOURCE_TOTAL__</div><div class="label">Sources enabled</div></div>
    <div class="stat warn"><div class="num mono">__CONFLICT_COUNT__</div><div class="label">Unresolved conflicts</div></div>
    <div class="stat"><div class="num mono">__PRICED_COUNT__</div><div class="label">Items priced</div></div>
    <div class="stat accent"><div class="num mono">__TAGGED_COUNT__</div><div class="label">Items with dietary tags</div></div>
  </div>

  <section id="change-section">
    <div class="section-head">
      <h2 class="display">What changed</h2>
      <span class="section-note">__CHANGE_NOTE__</span>
    </div>
    <div class="panel">
      __CHANGE_BANNER__
      __CHANGE_ROWS__
    </div>
  </section>

  <section id="confidence-section">
    <div class="section-head">
      <h2 class="display">Pipeline confidence</h2>
      <span class="section-note">How much of the code producing these numbers is covered by tests</span>
    </div>
    <div class="panel">
      __CONFIDENCE_BODY__
    </div>
  </section>

  <section id="sources-section">
    <div class="section-head">
      <h2 class="display">Sources</h2>
      <span class="section-note">Ranked by trust — used to break ties when sources disagree</span>
    </div>
    <div class="sources-grid" id="sources-grid"></div>
  </section>

  <section id="map-section">
    <div class="section-head">
      <h2 class="display">Putting booths on a map</h2>
      <span class="section-note">Nobody publishes coordinates — these get surveyed on foot</span>
    </div>
    <div class="panel">
      <p style="margin: 0 0 12px;">
        Eight booths named for a World Showcase pavilion borrow that pavilion's published
        coordinate, good to roughly 30–50&nbsp;m. <b>__UNPLACED_COUNT__</b> have no position at
        all — no source publishes one, and seasonal kiosks never make it into OpenStreetMap.
      </p>
      <p style="margin: 0;">
        <a class="survey-link" href="survey.html">Open the survey tool →</a>
        <a class="survey-link" href="map.html">Open the map tool →</a>
        <a class="survey-link" href="editor.html">Edit the database →</a>
        <span class="section-note">One tap per booth while you're standing there, or drop a pin from a desk.</span>
      </p>
    </div>
  </section>

  <section id="feed-section">
    <div class="section-head">
      <h2 class="display">Data feed</h2>
      <span class="section-note">What a client app downloads</span>
    </div>
    <div class="panel">
      <p style="margin: 0 0 12px;">
        The whole festival in one versioned file — <b>__ITEM_COUNT__</b> dishes across
        <b>__BOOTH_COUNT__</b> booths, about 18&nbsp;KB gzipped. Re-checking it costs nothing:
        unchanged data produces an identical file, so a returning client gets a 304 and no body.
      </p>
      <p style="margin: 0;">
        <a class="survey-link mono" href="v1/snapshot.json">v1/snapshot.json</a>
        <a class="survey-link" href="CLIENT_API.md">Integration notes →</a>
      </p>
    </div>
  </section>

  <section id="booths-section">
    <div class="section-head">
      <h2 class="display">Booths &amp; menus</h2>
      <span class="section-note" id="preseason-note"></span>
    </div>

    <div class="filter-bar">
      <input id="search" type="text" placeholder="Search booths, dishes or ingredients…" autocomplete="off" />
      <div class="chip-row" id="category-chips"></div>
      <div class="chip-row" id="tag-chips"></div>
      <div class="chip-row" id="extra-chips"></div>
      <span id="result-count"></span>
    </div>

    <p class="tag-caveat">
      <b>Dietary tags are inferred from menu wording, not from Disney's allergen data.</b>
      A description names what a dish is sold on, not everything in it — "Carrot Cake" says
      nothing about the walnuts. Treat these as a way to browse, never as an allergen check,
      and ask at the booth.
    </p>

    <div class="booth-list" id="booth-list"></div>
  </section>

  <section id="conflicts-section">
    <div class="section-head">
      <h2 class="display">Needs a human look</h2>
      <span class="section-note">Fuzzy matches in the 70–89 confidence band, or menu items whose booth couldn't be confidently linked</span>
    </div>
    <div class="conflict-list" id="conflict-list"></div>
  </section>

  <section id="runs-section">
    <div class="section-head">
      <h2 class="display">Crawl history</h2>
    </div>
    <div class="runs-card" id="runs-card"></div>
  </section>

  <footer>
    <span>epcot_fw · PostgreSQL + FastAPI · <code class="mono">epcot-fw refresh</code> runs weekly</span>
    <span id="generated-at">Built __GENERATED_AT__</span>
  </footer>
</div>

<script id="epcot-data" type="application/json">__DATA_JSON__</script>
<script>
(function () {
  var DATA = JSON.parse(document.getElementById('epcot-data').textContent);

  function fmtDateTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var CATEGORY_LABEL = { food: 'Food', alcoholic_beverage: 'Alcoholic', non_alcoholic_beverage: 'Non-alcoholic' };
  var TAG_LABEL = {
    vegetarian: 'Vegetarian', vegan: 'Vegan', gluten_free: 'Gluten-Free', plant_based: 'Plant-Based',
    contains_alcohol: 'Contains Alcohol', spicy: 'Spicy', contains_nuts: 'Contains Nuts'
  };

  var allItems = [];
  DATA.booths.forEach(function (b) {
    b.items.forEach(function (it) { allItems.push(it); });
  });
  var pricedCount = allItems.filter(function (it) { return it.price !== null && it.price !== undefined; }).length;

  document.getElementById('preseason-note').textContent =
    pricedCount === 0
      ? 'No prices yet — sources haven’t published 2026 pricing this far ahead of opening day'
      : pricedCount + ' of ' + allItems.length + ' items have a published price so far';

  // ---- sources ----
  var sourcesGrid = document.getElementById('sources-grid');
  DATA.sources.forEach(function (s) {
    var card = document.createElement('div');
    card.className = 'source-card';
    card.innerHTML =
      '<div class="source-top"><span class="source-name">' + escapeHtml(s.name) + '</span>' +
      '<span class="pill ' + (s.enabled ? 'on' : 'off') + '">' + (s.enabled ? 'Enabled' : 'Off') + '</span></div>' +
      '<span class="source-url mono">' + escapeHtml(s.url.replace(/^https?:\/\//, '')) + '</span>' +
      '<span class="priority-tag">priority ' + s.priority + '</span>';
    sourcesGrid.appendChild(card);
  });

  // ---- filter chips ----
  var state = { q: '', category: null, tag: null, photoOnly: false };
  var categoryChips = document.getElementById('category-chips');
  var tagChips = document.getElementById('tag-chips');
  var extraChips = document.getElementById('extra-chips');

  function makeChip(container, label, onClick) {
    var chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.textContent = label;
    chip.addEventListener('click', onClick);
    container.appendChild(chip);
    return chip;
  }

  var photoChip = makeChip(extraChips, '📷 Has photo', function () {
    state.photoOnly = !state.photoOnly;
    photoChip.classList.toggle('active', state.photoOnly);
    render();
  });

  var catChipEls = {};
  ['food', 'alcoholic_beverage', 'non_alcoholic_beverage'].forEach(function (cat) {
    catChipEls[cat] = makeChip(categoryChips, CATEGORY_LABEL[cat], function () {
      state.category = state.category === cat ? null : cat;
      Object.keys(catChipEls).forEach(function (k) { catChipEls[k].classList.toggle('active', k === state.category); });
      render();
    });
  });

  var presentTags = {};
  allItems.forEach(function (it) { (it.tags || []).forEach(function (t) { presentTags[t] = true; }); });
  var tagChipEls = {};
  Object.keys(presentTags).sort().forEach(function (tag) {
    tagChipEls[tag] = makeChip(tagChips, TAG_LABEL[tag] || tag, function () {
      state.tag = state.tag === tag ? null : tag;
      Object.keys(tagChipEls).forEach(function (k) { tagChipEls[k].classList.toggle('active', k === state.tag); });
      render();
    });
  });

  document.getElementById('search').addEventListener('input', function (e) {
    state.q = e.target.value.trim().toLowerCase();
    render();
  });

  // ---- booth list render ----
  var boothList = document.getElementById('booth-list');
  var resultCount = document.getElementById('result-count');

  function itemMatches(it) {
    if (state.category && it.category !== state.category) return false;
    if (state.tag && (it.tags || []).indexOf(state.tag) === -1) return false;
    if (state.q) {
      var haystack = (it.name + ' ' + (it.description || '')).toLowerCase();
      if (haystack.indexOf(state.q) === -1) return false;
    }
    return true;
  }

  function renderItemRow(it) {
    var tagsHtml = (it.tags || []).map(function (t) {
      return '<span class="tag">' + escapeHtml(TAG_LABEL[t] || t) + '</span>';
    }).join('');
    var priceHtml = (it.price !== null && it.price !== undefined)
      ? '<span class="item-price">$' + Number(it.price).toFixed(2) + '</span>'
      : '<span class="item-price unknown">not yet priced</span>';
    var dishHtml = it.image_data_uri
      ? '<img class="dish-thumb" src="' + it.image_data_uri + '" alt="Photo of ' + escapeHtml(it.name) + '" loading="lazy" />'
      : '';
    return (
      '<div class="item-row' + (dishHtml ? ' has-photo' : '') + '">' +
        '<span class="cat-dot ' + it.category + '" title="' + (CATEGORY_LABEL[it.category] || it.category) + '"></span>' +
        '<div class="item-main">' +
          dishHtml +
          '<div class="item-name">' + escapeHtml(it.name) + '</div>' +
          (it.description ? '<div class="item-desc">' + escapeHtml(it.description) + '</div>' : '') +
          (tagsHtml ? '<div class="item-tags">' + tagsHtml + '</div>' : '') +
        '</div>' +
        priceHtml +
      '</div>'
    );
  }

  function render() {
    boothList.innerHTML = '';
    var shownBooths = 0, shownItems = 0;

    DATA.booths.forEach(function (b, idx) {
      if (state.photoOnly && !b.image_data_uri) return;

      var matchedItems = b.items.filter(itemMatches);
      var boothNameMatches = !state.q || b.name.toLowerCase().indexOf(state.q) !== -1;
      var hasFilter = state.category || state.tag || state.q;

      var itemsToShow = matchedItems;
      if (!hasFilter) itemsToShow = b.items;
      else if (boothNameMatches && !state.category && !state.tag) itemsToShow = b.items;

      if (hasFilter && itemsToShow.length === 0 && !(boothNameMatches && !state.category && !state.tag)) return;

      shownBooths++; shownItems += itemsToShow.length;

      var det = document.createElement('details');
      det.className = 'booth';
      if (idx < 3 && !hasFilter && !state.photoOnly) det.open = true;

      var rowsHtml = itemsToShow.length
        ? itemsToShow.map(renderItemRow).join('')
        : '<div class="empty-state">No menu yet — booth confirmed, dishes not published</div>';

      var thumbHtml = b.image_data_uri
        ? '<img class="booth-thumb" src="' + b.image_data_uri + '" alt="" loading="lazy" />'
        : '<span class="booth-thumb-placeholder">🍽</span>';

      var photoHtml = b.image_data_uri
        ? '<img class="booth-photo" src="' + b.image_data_uri + '" alt="Menu board photo of ' + escapeHtml(b.name) + '" loading="lazy" />'
        : '';

      det.innerHTML =
        '<summary class="booth-head"><span class="booth-title">' +
          '<span class="booth-caret">&#9654;</span>' +
          thumbHtml +
          '<span class="booth-name">' + escapeHtml(b.name) + '</span></span>' +
          '<span class="booth-meta">' +
            '<span class="item-count">' + b.items.length + ' item' + (b.items.length === 1 ? '' : 's') + '</span></span>' +
        '</summary>' +
        photoHtml +
        '<div class="item-table">' + rowsHtml + '</div>';

      boothList.appendChild(det);
    });

    resultCount.textContent = shownBooths + ' booth' + (shownBooths === 1 ? '' : 's') +
      (state.q || state.category || state.tag ? ', ' + shownItems + ' item' + (shownItems === 1 ? '' : 's') : '');

    if (shownBooths === 0) {
      boothList.innerHTML = '<div class="empty-state">No booths or dishes match that search.</div>';
    }
  }
  render();

  // ---- conflicts ----
  var conflictList = document.getElementById('conflict-list');
  if (DATA.conflicts.length === 0) {
    conflictList.innerHTML = '<div class="empty-state">Nothing queued for a human look.</div>';
  } else {
    DATA.conflicts.forEach(function (c) {
      var row = document.createElement('div');
      row.className = 'conflict';
      var badge = c.entity_type === 'booth' ? 'Booth match' : (c.field ? 'Field conflict' : 'Menu match');
      var text = '';
      if (c.field) {
        var vals = Object.keys(c.values).map(function (k) { return escapeHtml(String(c.values[k])); });
        text = 'Sources disagree on <b>' + escapeHtml(c.field) + '</b>: ' + vals.join(' vs. ');
      } else if (c.values.item) {
        text = '<b>' + escapeHtml(c.values.item) + '</b> couldn’t be linked to booth "' + escapeHtml(c.values.booth_name || '?') + '"';
      } else {
        text = '<b>' + escapeHtml(c.values.extracted_name || '(unnamed)') + '</b> is a ' +
          (c.values.score ? Math.round(c.values.score) + '% ' : '') + 'match — not confident enough to auto-merge';
      }
      row.innerHTML = '<span class="conflict-badge">' + badge + '</span>' +
        '<div><div class="conflict-text">' + text + '</div></div>';
      conflictList.appendChild(row);
    });
  }

  // ---- crawl runs ----
  var runsCard = document.getElementById('runs-card');
  if (!DATA.runs || DATA.runs.length === 0) {
    runsCard.innerHTML = '<div class="empty-state">No crawl runs recorded yet.</div>';
  } else {
    DATA.runs.forEach(function (r) {
      var row = document.createElement('div');
      row.className = 'run-row';
      var s = r.stats || {};
      row.innerHTML =
        '<span><b>' + escapeHtml(r.type) + '</b> · ' + escapeHtml(r.status) + '</span>' +
        '<span class="run-badge">' + fmtDateTime(r.started_at) + '</span>' +
        '<span class="run-badge">' + (s.pages_fetched || 0) + ' fetched · ' + (s.pages_changed || 0) + ' changed · ' +
          (s.records_extracted || 0) + ' extracted · ' + (s.canonical_upserts || 0) + ' upserted</span>';
      runsCard.appendChild(row);
    });
  }
})();
</script>
</body>
</html>
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "date TBC"
    try:
        return datetime.date.fromisoformat(iso[:10]).strftime("%b %-d, %Y")
    except ValueError:
        return iso


def fmt_datetime(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%b %-d, %Y")
    except ValueError:
        return iso


def render_change_rows(rows: list[dict]) -> str:
    out = []
    for row in rows:
        if row["delta"] is None:
            chip = '<span class="delta-chip none">—</span>'
        elif row["delta"] == 0:
            chip = '<span class="delta-chip same">no change</span>'
        else:
            sign = "+" if row["delta"] > 0 else "−"
            chip = (
                f'<span class="delta-chip {row["verdict"]}">{sign}{abs(row["delta"])}</span>'
            )

        sub = ""
        if row["current_pct"] is not None:
            sub = f'<span class="delta-sub">{row["current_pct"]}% coverage'
            if row["previous_pct"] is not None and row["previous_pct"] != row["current_pct"]:
                sub += f' (was {row["previous_pct"]}%)'
            sub += "</span>"

        out.append(
            '<div class="delta-row">'
            f'<span class="delta-label">{esc(row["label"])}{sub}</span>'
            f'<span class="delta-value">{row["current"]}</span>'
            f"{chip}"
            "</div>"
        )
    return "".join(out)


def render_confidence(pipe: dict) -> str:
    baseline, current = pipe.get("baseline"), pipe.get("current")
    if not current:
        return '<div class="empty-state">No coverage measurement recorded yet.</div>'

    def block(title: str, key: str, suffix: str = "") -> str:
        after = current.get(key)
        before = baseline.get(key) if baseline else None
        before_html = (
            f'<span class="confidence-before">{before}{suffix}</span>'
            f'<span class="confidence-arrow">→</span>'
            if before is not None
            else ""
        )
        meter = ""
        if key == "coverage_pct" and isinstance(after, (int, float)):
            meter = f'<div class="meter"><span style="width:{min(after, 100)}%"></span></div>'
        return (
            '<div class="confidence-metric">'
            f"<h4>{esc(title)}</h4>"
            f'<div class="confidence-nums">{before_html}'
            f'<span class="confidence-after">{after}{suffix}</span></div>'
            f"{meter}"
            "</div>"
        )

    covered = current.get("covered_lines")
    statements = current.get("num_statements")
    foot = (
        f'<div class="confidence-foot">{covered} of {statements} statements in '
        f"<code>epcot_fw</code> executed by the suite"
    )
    if baseline:
        foot += (
            f' · baseline measured at commit <code>{esc(baseline.get("commit", "?"))}</code>'
        )
    if current.get("commit"):
        foot += f' · current at <code>{esc(current["commit"])}</code>'
    foot += "</div>"

    return (
        '<div class="confidence-grid">'
        + block("Line coverage", "coverage_pct", "%")
        + block("Tests", "tests")
        + "</div>"
        + foot
    )


festival = data.get("festival") or {}
counts = current_entry["data"]
source_total = len(data.get("sources") or [])
last_run_at = (data.get("runs") or [{}])[0].get("started_at")

if previous_entry:
    change_note = f"Compared with the snapshot recorded {fmt_datetime(previous_entry.get('recorded_at'))}"
    change_banner = ""
else:
    change_note = "Baseline snapshot"
    change_banner = (
        '<div class="panel-banner">'
        "<b>This is the first tracked snapshot.</b> Its metrics are now the baseline — "
        "gains and losses will appear here from the next crawl onward."
        "</div>"
    )

html_out = TEMPLATE
replacements = {
    "__FESTIVAL_NAME__": esc(festival.get("name", "Festival")),
    "__FESTIVAL_DATES__": f"{fmt_date(festival.get('start'))} – {fmt_date(festival.get('end'))}",
    "__FESTIVAL_STATUS__": esc(festival.get("status", "unknown")),
    "__ENABLED_COUNT__": str(counts["sources_enabled"]),
    "__SOURCE_TOTAL__": str(source_total),
    "__LAST_RUN__": fmt_datetime(last_run_at),
    "__BOOTH_COUNT__": str(counts["booths"]),
    "__ITEM_COUNT__": str(counts["menu_items"]),
    "__CONFLICT_COUNT__": str(counts["open_conflicts"]),
    "__PRICED_COUNT__": f"{counts['items_priced']} / {counts['menu_items']}",
    "__TAGGED_COUNT__": f"{counts['items_tagged']} / {counts['menu_items']}",
    "__CHANGE_NOTE__": esc(change_note),
    "__CHANGE_BANNER__": change_banner,
    "__CHANGE_ROWS__": render_change_rows(diff_rows),
    "__CONFIDENCE_BODY__": render_confidence(pipeline),
    "__GENERATED_AT__": datetime.datetime.now(datetime.UTC).strftime("%b %-d, %Y"),
    # Counted off the survey page's own list rather than the raw snapshot, so
    # the two pages cannot disagree about how much is left to walk. It drops
    # the "Additional Festival Locations" heading, which is not a place.
    "__UNPLACED_COUNT__": str(
        sum(1 for b in build_survey.survey_booths(data) if b["latitude"] is None)
    ),
}
for token, value in replacements.items():
    html_out = html_out.replace(token, value)

# Substituted last: the snapshot blob can itself contain "__"-style tokens in
# scraped text, and replacing it first would let those be rewritten.
html_out = html_out.replace("__DATA_JSON__", json.dumps(data))

DOCS_DIR.mkdir(exist_ok=True)
out_path = DOCS_DIR / "index.html"
out_path.write_text(html_out)
print(f"wrote {out_path} ({len(html_out)} bytes)")

# Built here rather than as its own command so the two pages can never
# disagree about which booths exist - a survey page listing last season's
# lineup would send someone to a booth that isn't there.
survey_path = DOCS_DIR / "survey.html"
survey_html = build_survey.render(data)
survey_path.write_text(survey_html)
print(f"wrote {survey_path} ({len(survey_html)} bytes)")

map_path = DOCS_DIR / "map.html"
map_html = build_map.render(data)
map_path.write_text(map_html)
print(f"wrote {map_path} ({len(map_html)} bytes)")

editor_path = DOCS_DIR / "editor.html"
editor_html = build_editor.render(data, generated_at=replacements["__GENERATED_AT__"])
editor_path.write_text(editor_html)
print(f"wrote {editor_path} ({len(editor_html)} bytes)")
print(f"history: {len(history)} snapshot(s), previous={'yes' if previous_entry else 'none (baseline)'}")

# Icons and the manifest are copied rather than inlined: iOS ignores data:
# URIs for apple-touch-icon, so "Add to Home Screen" needs real files sitting
# next to index.html. Copying on every build keeps docs/ a pure build output.
copied = 0
if ASSETS_DIR.is_dir():
    shutil.copytree(ASSETS_DIR / "icons", DOCS_DIR / "icons", dirs_exist_ok=True)
    copied = len(list((DOCS_DIR / "icons").iterdir()))
    shutil.copy2(ASSETS_DIR / "manifest.json", DOCS_DIR / "manifest.json")
    print(f"copied {copied} icon file(s) + manifest.json into {DOCS_DIR}")

# A missing icon silently degrades to a blank home-screen tile, so fail loudly
# instead of shipping a build whose <link> targets aren't there.
missing = [
    ref
    for ref in ("icons/favicon.ico", "icons/icon.svg", "icons/apple-touch-icon.png", "manifest.json")
    if not (DOCS_DIR / ref).exists()
]
if missing:
    raise SystemExit(f"referenced asset(s) missing from {DOCS_DIR}: {', '.join(missing)}")
