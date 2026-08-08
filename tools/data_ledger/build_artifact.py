import json
import pathlib

TOOL_DIR = pathlib.Path(__file__).parent
DOCS_DIR = TOOL_DIR.parent.parent / "docs"
data = json.loads((TOOL_DIR / "epcot_db_snapshot.json").read_text())

TEMPLATE = r"""<title>Epcot Food & Wine — Data Ledger</title>
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
  :root {
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
body {
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
}
.wrap { max-width: 1080px; margin: 0 auto; padding: 40px 24px 80px; }

.display { font-family: Georgia, "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif; }
.mono { font-family: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace; font-variant-numeric: tabular-nums; }

/* ---------- header ---------- */
header.top { margin-bottom: 32px; }
.eyebrow {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--accent); font-weight: 600; margin-bottom: 10px;
}
.eyebrow::before {
  content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--accent);
}
h1.display {
  font-size: 34px; margin: 0 0 8px; text-wrap: balance; font-weight: 600;
  letter-spacing: -0.01em;
}
.subtitle { color: var(--ink-muted); font-size: 15px; max-width: 62ch; }
.subtitle b { color: var(--ink); font-weight: 600; }

/* ---------- stat strip ---------- */
.stats {
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px;
  margin: 28px 0 32px;
}
@media (max-width: 800px) { .stats { grid-template-columns: repeat(2, 1fr); } }
.stat {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px; box-shadow: var(--shadow);
}
.stat .num { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-variant-numeric: tabular-nums; font-size: 26px; font-weight: 600; color: var(--ink); }
.stat .label { font-size: 12px; color: var(--ink-muted); margin-top: 2px; text-transform: uppercase; letter-spacing: 0.04em; }
.stat.accent .num { color: var(--accent); }
.stat.warn .num { color: var(--warn); }

/* ---------- section shell ---------- */
section { margin-bottom: 36px; }
.section-head {
  display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
  margin-bottom: 14px; flex-wrap: wrap;
}
h2.display { font-size: 20px; margin: 0; font-weight: 600; }
.section-note { font-size: 13px; color: var(--ink-muted); }

/* ---------- sources ---------- */
.sources-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px;
}
.source-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; display: flex; flex-direction: column; gap: 6px;
}
.source-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.source-name { font-weight: 600; font-size: 13.5px; }
.source-url { font-size: 12px; color: var(--ink-muted); word-break: break-all; }
.pill {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 20px; white-space: nowrap;
}
.pill.on { background: var(--good-soft); color: var(--good); }
.pill.off { background: var(--surface-2); color: var(--ink-muted); }
.priority-tag { font-size: 11px; color: var(--ink-muted); font-family: ui-monospace, monospace; }

/* ---------- filter bar ---------- */
.filter-bar {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; margin-bottom: 18px; position: sticky; top: 12px; z-index: 5;
  box-shadow: var(--shadow);
}
#search {
  flex: 1 1 220px; min-width: 160px; background: var(--bg); color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; font-size: 14px;
  font-family: inherit;
}
#search:focus-visible, .chip:focus-visible, summary:focus-visible, a:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  border: 1px solid var(--border); background: var(--surface); color: var(--ink-muted);
  border-radius: 20px; padding: 6px 12px; font-size: 12.5px; cursor: pointer;
  font-family: inherit; transition: background 0.12s, color 0.12s, border-color 0.12s;
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
  list-style: none; cursor: pointer; padding: 13px 16px;
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
}
summary.booth-head::-webkit-details-marker { display: none; }
.booth-title { display: flex; align-items: center; gap: 10px; }
.booth-caret { color: var(--ink-muted); font-size: 11px; transition: transform 0.15s; }
details[open] .booth-caret { transform: rotate(90deg); }
.booth-name { font-family: Georgia, "Iowan Old Style", serif; font-weight: 600; font-size: 16px; }
.booth-meta { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--ink-muted); }
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

.rating { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.stars { color: var(--gold); font-size: 13px; letter-spacing: 1px; }
.stars .empty { color: var(--border); }
.rating-num { font-family: ui-monospace, monospace; font-size: 12px; color: var(--ink-muted); font-variant-numeric: tabular-nums; }
.rating.unrated { color: var(--ink-muted); font-size: 12px; font-style: italic; }

.booth-photo {
  width: 100%; max-height: 240px; object-fit: cover; display: block;
  border-bottom: 1px solid var(--border);
}

.reviews-section { border-top: 1px solid var(--border); padding: 14px 16px; background: var(--surface-2); }
.reviews-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.reviews-head h4 { margin: 0; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-muted); font-weight: 600; }
.review-list { display: flex; flex-direction: column; gap: 8px; }
.review-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; font-size: 13px;
}
.review-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
.review-who { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.review-date { color: var(--ink-muted); font-size: 11.5px; font-family: ui-monospace, monospace; }
.review-text { color: var(--ink); line-height: 1.5; }
.review-rec {
  font-size: 10px; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase;
  padding: 2px 7px; border-radius: 20px;
}
.review-rec.yes { background: var(--good-soft); color: var(--good); }
.review-rec.no { background: var(--warn-soft); color: var(--warn); }
.review-user-badge {
  font-size: 10px; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase;
  padding: 2px 7px; border-radius: 20px; background: var(--accent-soft); color: var(--accent);
}

.item-table { border-top: 1px solid var(--border); }
.item-row {
  display: grid; grid-template-columns: auto 1fr auto; gap: 12px; align-items: baseline;
  padding: 9px 16px; border-bottom: 1px solid var(--border);
}
.item-row:last-child { border-bottom: none; }
.item-row:nth-child(even) { background: var(--surface-2); }
.cat-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex: none; }
.cat-dot.food { background: var(--gold); }
.cat-dot.alcoholic_beverage { background: var(--accent); }
.cat-dot.non_alcoholic_beverage { background: var(--ink-muted); }
.item-main { min-width: 0; }
.item-name { font-size: 13.5px; }
.item-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }
.tag {
  font-size: 10px; padding: 2px 7px; border-radius: 20px; background: var(--gold-soft);
  color: var(--gold); font-weight: 600; letter-spacing: 0.02em;
}
.item-price { font-family: ui-monospace, monospace; font-size: 13px; font-variant-numeric: tabular-nums; color: var(--ink); white-space: nowrap; }
.item-price.unknown { color: var(--ink-muted); font-style: italic; font-family: inherit; font-size: 12px; }

/* ---------- conflicts ---------- */
.conflict-list { display: flex; flex-direction: column; gap: 8px; }
.conflict {
  background: var(--warn-soft); border: 1px solid var(--warn); border-radius: 8px;
  padding: 10px 14px; font-size: 13px; display: flex; gap: 10px; align-items: flex-start;
}
.conflict-badge {
  flex: none; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  color: var(--warn); background: var(--surface); border: 1px solid var(--warn);
  padding: 2px 7px; border-radius: 20px; margin-top: 1px;
}
.conflict-text { color: var(--ink); }
.conflict-text b { font-weight: 600; }
.conflict-sub { color: var(--ink-muted); font-size: 12px; margin-top: 2px; }

/* ---------- runs / footer ---------- */
.run-row {
  display: flex; justify-content: space-between; gap: 12px; padding: 9px 14px;
  border-bottom: 1px solid var(--border); font-size: 13px; flex-wrap: wrap;
}
.run-row:last-child { border-bottom: none; }
.run-badge { font-family: ui-monospace, monospace; font-size: 11px; color: var(--ink-muted); }
.runs-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
}

footer {
  margin-top: 44px; padding-top: 20px; border-top: 1px solid var(--border);
  font-size: 12.5px; color: var(--ink-muted); display: flex; justify-content: space-between;
  gap: 12px; flex-wrap: wrap;
}
.empty-state { padding: 28px; text-align: center; color: var(--ink-muted); font-size: 13.5px; }

.overflow-x { overflow-x: auto; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>

<div class="wrap">
  <h2 class="sr-only">Interactive browser of the crawled Epcot Food &amp; Wine Festival database: booths, menu items, data sources, and open review conflicts.</h2>

  <header class="top">
    <div class="eyebrow">Live database snapshot</div>
    <h1 class="display">Epcot Food &amp; Wine — Data Ledger</h1>
    <p class="subtitle">
      <b>__FESTIVAL_NAME__</b> · __FESTIVAL_DATES__ · __FESTIVAL_STATUS__.
      Crawled from __ENABLED_COUNT__ of 7 sources, last run __LAST_RUN__.
    </p>
  </header>

  <div class="stats">
    <div class="stat accent"><div class="num mono">__BOOTH_COUNT__</div><div class="label">Booths</div></div>
    <div class="stat accent"><div class="num mono">__ITEM_COUNT__</div><div class="label">Menu items</div></div>
    <div class="stat"><div class="num mono">__ENABLED_COUNT__/7</div><div class="label">Sources enabled</div></div>
    <div class="stat warn"><div class="num mono">__CONFLICT_COUNT__</div><div class="label">Open for review</div></div>
    <div class="stat"><div class="num mono">__PRICED_COUNT__</div><div class="label">Items priced</div></div>
    <div class="stat accent"><div class="num mono">__REVIEW_COUNT__</div><div class="label">Reviews mined</div></div>
  </div>

  <section id="sources-section">
    <div class="section-head">
      <h2 class="display">Sources</h2>
      <span class="section-note">Ranked by trust — used to break ties when sources disagree</span>
    </div>
    <div class="sources-grid" id="sources-grid"></div>
  </section>

  <section id="booths-section">
    <div class="section-head">
      <h2 class="display">Booths &amp; menus</h2>
      <span class="section-note" id="preseason-note"></span>
    </div>

    <div class="filter-bar">
      <input id="search" type="text" placeholder="Search booths or dishes…" autocomplete="off" />
      <div class="chip-row" id="category-chips"></div>
      <div class="chip-row" id="tag-chips"></div>
      <div class="chip-row" id="extra-chips"></div>
      <span id="result-count"></span>
    </div>

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
    <span id="generated-at"></span>
  </footer>
</div>

<script id="epcot-data" type="application/json">__DATA_JSON__</script>
<script>
(function () {
  var DATA = JSON.parse(document.getElementById('epcot-data').textContent);

  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }
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

  function renderStars(rating) {
    var full = Math.round(rating);
    var out = '';
    for (var i = 1; i <= 5; i++) out += i <= full ? '★' : '<span class="empty">★</span>';
    return out;
  }
  function renderRating(booth) {
    if (!booth.average_rating || !booth.review_count) {
      return '<span class="rating unrated">Not yet reviewed</span>';
    }
    return '<span class="rating"><span class="stars">' + renderStars(booth.average_rating) + '</span>' +
      '<span class="rating-num">' + booth.average_rating.toFixed(2) + ' (' + booth.review_count + ')</span></span>';
  }

  var allItems = [];
  DATA.booths.forEach(function (b) {
    b.items.forEach(function (it) { allItems.push(it); });
  });
  var pricedCount = allItems.filter(function (it) { return it.price !== null && it.price !== undefined; }).length;
  var enabledCount = DATA.sources.filter(function (s) { return s.enabled; }).length;
  var lastRun = DATA.runs && DATA.runs[0];

  document.getElementById('generated-at').textContent = 'Snapshot rendered ' + new Date().toLocaleString();

  // ---- header stat fill-ins ----
  document.title = 'Epcot Food & Wine — Data Ledger';
  document.querySelector('.subtitle').innerHTML =
    '<b>' + escapeHtml(DATA.festival.name) + '</b> · ' +
    fmtDate(DATA.festival.start) + '–' + fmtDate(DATA.festival.end) + ' · ' +
    escapeHtml(DATA.festival.status) + '. Crawled from ' + enabledCount + ' of 7 sources' +
    (lastRun ? ', last run ' + fmtDateTime(lastRun.started_at) + '.' : '.');

  var totalReviews = DATA.booths.reduce(function (sum, b) { return sum + (b.review_count || 0); }, 0);

  var stats = document.querySelectorAll('.stat .num');
  stats[0].textContent = DATA.booths.length;
  stats[1].textContent = allItems.length;
  stats[2].textContent = enabledCount + '/7';
  stats[3].textContent = DATA.conflicts.length;
  stats[4].textContent = pricedCount + ' / ' + allItems.length;
  stats[5].textContent = totalReviews;

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
  var state = { q: '', category: null, tag: null, ratedOnly: false, photoOnly: false };
  var categoryChips = document.getElementById('category-chips');
  var tagChips = document.getElementById('tag-chips');
  var extraChips = document.getElementById('extra-chips');

  var ratedChip = makeChip(extraChips, '★ Rated', function () {
    state.ratedOnly = !state.ratedOnly;
    ratedChip.classList.toggle('active', state.ratedOnly);
    render();
  });
  var photoChip = makeChip(extraChips, '📷 Has photo', function () {
    state.photoOnly = !state.photoOnly;
    photoChip.classList.toggle('active', state.photoOnly);
    render();
  });

  function makeChip(container, label, onClick) {
    var chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.textContent = label;
    chip.addEventListener('click', onClick);
    container.appendChild(chip);
    return chip;
  }

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
    if (state.q && it.name.toLowerCase().indexOf(state.q) === -1) return false;
    return true;
  }

  function renderItemRow(it) {
    var tagsHtml = (it.tags || []).map(function (t) {
      return '<span class="tag">' + escapeHtml(TAG_LABEL[t] || t) + '</span>';
    }).join('');
    var priceHtml = (it.price !== null && it.price !== undefined)
      ? '<span class="item-price">$' + Number(it.price).toFixed(2) + '</span>'
      : '<span class="item-price unknown">not yet priced</span>';
    return (
      '<div class="item-row">' +
        '<span class="cat-dot ' + it.category + '" title="' + (CATEGORY_LABEL[it.category] || it.category) + '"></span>' +
        '<div class="item-main"><div class="item-name">' + escapeHtml(it.name) + '</div>' +
        (tagsHtml ? '<div class="item-tags">' + tagsHtml + '</div>' : '') +
        '</div>' +
        priceHtml +
      '</div>'
    );
  }

  function renderReviewCard(r) {
    var recHtml = r.recommended === true ? '<span class="review-rec yes">Recommended</span>'
      : r.recommended === false ? '<span class="review-rec no">Not recommended</span>' : '';
    var userHtml = r.is_user ? '<span class="review-user-badge">You</span>' : '';
    return (
      '<div class="review-card">' +
        '<div class="review-top">' +
          '<span class="review-who">' +
            '<span class="stars">' + renderStars(r.rating) + '</span>' +
            escapeHtml(r.reviewer_name || 'Anonymous') + userHtml + recHtml +
          '</span>' +
          '<span class="review-date">' + fmtDate(r.reviewed_at) + '</span>' +
        '</div>' +
        '<div class="review-text">' + escapeHtml(r.text || '') + '</div>' +
      '</div>'
    );
  }

  function render() {
    boothList.innerHTML = '';
    var shownBooths = 0, shownItems = 0;

    DATA.booths.forEach(function (b, idx) {
      if (state.ratedOnly && !b.review_count) return;
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
      if (idx < 3 && !hasFilter && !state.ratedOnly && !state.photoOnly) det.open = true;

      var rowsHtml = itemsToShow.length
        ? itemsToShow.map(renderItemRow).join('')
        : '<div class="empty-state">No menu yet — booth confirmed, dishes not published</div>';

      var thumbHtml = b.image_data_uri
        ? '<img class="booth-thumb" src="' + b.image_data_uri + '" alt="" loading="lazy" />'
        : '<span class="booth-thumb-placeholder">🍽</span>';

      var photoHtml = b.image_data_uri
        ? '<img class="booth-photo" src="' + b.image_data_uri + '" alt="Menu board photo of ' + escapeHtml(b.name) + '" loading="lazy" />'
        : '';

      var reviewsHtml = '';
      if (b.reviews && b.reviews.length) {
        reviewsHtml =
          '<div class="reviews-section">' +
            '<div class="reviews-head"><h4>Reviews (' + b.reviews.length + ')</h4></div>' +
            '<div class="review-list">' + b.reviews.map(renderReviewCard).join('') + '</div>' +
          '</div>';
      }

      det.innerHTML =
        '<summary class="booth-head"><span class="booth-title">' +
          '<span class="booth-caret">&#9654;</span>' +
          thumbHtml +
          '<span class="booth-name">' + escapeHtml(b.name) + '</span></span>' +
          '<span class="booth-meta">' + renderRating(b) +
            '<span class="item-count">' + b.items.length + ' item' + (b.items.length === 1 ? '' : 's') + '</span></span>' +
        '</summary>' +
        photoHtml +
        '<div class="item-table">' + rowsHtml + '</div>' +
        reviewsHtml;

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
    conflictList.innerHTML = '<div class="empty-state">Nothing queued for review.</div>';
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
"""

html = TEMPLATE
html = html.replace("__FESTIVAL_NAME__", data["festival"]["name"])
html = html.replace("__FESTIVAL_DATES__", "placeholder")
html = html.replace("__FESTIVAL_STATUS__", "placeholder")
html = html.replace("__ENABLED_COUNT__", "placeholder")
html = html.replace("__LAST_RUN__", "placeholder")
html = html.replace("__BOOTH_COUNT__", "placeholder")
html = html.replace("__ITEM_COUNT__", "placeholder")
html = html.replace("__CONFLICT_COUNT__", "placeholder")
html = html.replace("__PRICED_COUNT__", "placeholder")
html = html.replace("__DATA_JSON__", json.dumps(data))

DOCS_DIR.mkdir(exist_ok=True)
out_path = DOCS_DIR / "index.html"
out_path.write_text(html)
print("wrote", out_path, len(html), "bytes")
