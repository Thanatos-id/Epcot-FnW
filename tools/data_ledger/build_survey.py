"""Renders docs/survey.html, the in-park coordinate capture tool.

Not one of the seven crawled sources publishes a booth coordinate, and the
festival kiosks are seasonal so they are not in OpenStreetMap either. The
only way to get metre-accurate positions is for someone to stand at each
booth - which is a fine plan when you are walking World Showcase anyway, and
an awful one if it means typing decimal degrees into JSON on a phone.

So: a page that lists every booth, takes a GPS fix on one tap, keeps the lap
in local storage so a dropped signal or a closed tab does not lose the
morning, and hands back the exact block to paste into
`data/manual/booth_locations.json`.

docs/studio.html can place the same booths from a map at a desk, which is
the better plan before the festival opens and the worse one once you are
standing in it. The two share `survey_booths` so they can never disagree
about which booths exist.

Rendered by build_artifact.py alongside the ledger. `render()` is pure -
snapshot in, HTML out - so it can be tested without a browser or a database.
"""

from __future__ import annotations

import json
from typing import Any

# Shared with docs/studio.html rather than duplicated, so the two pages can
# never disagree about which booths exist. Re-exported: the tests import it
# from here, where it lived before the studio needed it too.
from snapshot_rows import survey_booths

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light dark" />
<meta name="description" content="Capture GPS coordinates for Epcot Food &amp; Wine Festival booths, one tap per booth, and export them for the crawler's curated data file." />
<title>Booth Survey — Epcot Food &amp; Wine</title>

<link rel="manifest" href="manifest.json" />
<link rel="icon" href="icons/favicon.ico" sizes="any" />
<link rel="icon" type="image/svg+xml" href="icons/icon.svg" />
<link rel="apple-touch-icon" sizes="180x180" href="icons/apple-touch-icon.png" />
<meta name="apple-mobile-web-app-title" content="Booth Survey" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="theme-color" content="#efe8d8" media="(prefers-color-scheme: light)" />
<meta name="theme-color" content="#1b1510" media="(prefers-color-scheme: dark)" />
<style>
:root {
  --bg: #efe8d8; --surface: #fbf7ee; --surface-2: #f3ebd8; --ink: #241c16;
  --ink-muted: #6b5d4f; --accent: #7a2036; --accent-soft: #f0dce0; --gold: #a9752b;
  --gold-soft: #f1e2c4; --border: #ddd0b5; --good: #4f7a45; --good-soft: #e1ebdb;
  --warn: #bb5a2c; --warn-soft: #f3e1d2;
  --shadow: 0 1px 2px rgba(36,28,22,0.06), 0 8px 24px rgba(36,28,22,0.06);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #1b1510; --surface: #241d16; --surface-2: #2c231a; --ink: #f3ecdd;
    --ink-muted: #b8aa93; --accent: #e0899c; --accent-soft: #3a2029; --gold: #d9a24b;
    --gold-soft: #3a2e18; --border: #3a2f23; --good: #8fc97f; --good-soft: #24301f;
    --warn: #e0935c; --warn-soft: #3a2618;
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

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.5; -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
  padding-bottom: env(safe-area-inset-bottom);
}
.wrap { max-width: 760px; margin: 0 auto; padding: clamp(18px, 5vw, 32px) clamp(14px, 4vw, 22px) 120px; }
.display { font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif; }
.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-variant-numeric: tabular-nums; }

.eyebrow {
  display: inline-flex; align-items: center; gap: 8px; font-size: 11px;
  letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent);
  font-weight: 600; margin-bottom: 10px;
}
.eyebrow::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
h1 { font-size: clamp(22px, 6vw, 30px); margin: 0 0 8px; font-weight: 600; letter-spacing: -0.01em; }
.subtitle { color: var(--ink-muted); font-size: 14.5px; max-width: 60ch; }
.subtitle a { color: var(--accent); }

.panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  box-shadow: var(--shadow); padding: 14px; margin: 18px 0;
}
.panel.note { background: var(--surface-2); font-size: 13.5px; color: var(--ink-muted); }
.panel.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }

.tallies { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 8px; }
.tally {
  background: var(--surface); border: 1px solid var(--border); border-radius: 20px;
  padding: 5px 12px; font-size: 12.5px; color: var(--ink-muted);
}
.tally b { color: var(--ink); font-family: ui-monospace, Menlo, monospace; }

.controls { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0; }
button {
  font: inherit; font-size: 14px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--surface); color: var(--ink); padding: 9px 14px; cursor: pointer;
  min-height: 44px;
}
button:active { transform: translateY(1px); }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
button.primary:disabled { opacity: 0.55; }
button.chip { min-height: 36px; padding: 6px 12px; font-size: 13px; }
button.chip.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 600; }

.booth-list { display: flex; flex-direction: column; gap: 10px; margin-top: 6px; }
.booth {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; box-shadow: var(--shadow);
}
.booth.captured { border-color: var(--good); }
.booth-top { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.booth-name { font-weight: 600; font-size: 15.5px; overflow-wrap: break-word; min-width: 0; }
.pill {
  font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 20px; white-space: nowrap;
}
.pill.surveyed { background: var(--good-soft); color: var(--good); }
.pill.anchored { background: var(--gold-soft); color: var(--gold); }
.pill.unplaced { background: var(--accent-soft); color: var(--accent); }
.pill.new { background: var(--good); color: #fff; }
.booth-meta { color: var(--ink-muted); font-size: 12.5px; margin-top: 3px; overflow-wrap: break-word; }
.booth-actions { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.fix { font-size: 12.5px; color: var(--ink-muted); }
.fix b { color: var(--ink); }
.fix.rough { color: var(--warn); }

textarea {
  width: 100%; min-height: 240px; font-family: ui-monospace, Menlo, monospace; font-size: 12px;
  background: var(--surface-2); color: var(--ink); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px; resize: vertical;
}
.sticky {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 5;
  background: var(--surface); border-top: 1px solid var(--border);
  padding: 10px clamp(14px, 4vw, 22px) calc(10px + env(safe-area-inset-bottom));
  display: flex; gap: 8px; align-items: center; justify-content: space-between; flex-wrap: wrap;
}
.sticky .count { font-size: 13px; color: var(--ink-muted); }
footer { margin-top: 28px; color: var(--ink-muted); font-size: 12.5px; }
footer a { color: var(--accent); }
.hidden { display: none !important; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="eyebrow">In-park capture</div>
    <h1 class="display">Booth Survey</h1>
    <p class="subtitle">
      Walk up to a booth, tap <b>Capture</b>, and this records your phone's GPS fix for it.
      Nothing leaves the phone until you copy it out. <a href="index.html">Back to the ledger</a>.
    </p>
  </header>

  <div id="unsupported" class="panel warn hidden"></div>

  <div class="panel note" id="fix-banner">Waiting for a GPS fix…</div>

  <div class="tallies" id="tallies"></div>

  <div class="panel note">
    Hold still for a second before tapping — a fix taken mid-stride is the main source of
    bad coordinates. Anything worse than 25&nbsp;m accuracy is flagged so you can retake it.
    Captures are kept on this device, so closing the tab won't lose your lap.
  </div>

  <div class="controls">
    <button type="button" class="chip" id="sort-toggle">Sort by nearest</button>
    <button type="button" class="chip" id="filter-toggle">Hide surveyed</button>
  </div>

  <div class="booth-list" id="booth-list"></div>

  <section id="export-section" style="margin-top: 26px;">
    <h2 class="display" style="font-size: 19px; margin-bottom: 6px;">Export</h2>
    <p class="subtitle" style="margin-top: 0;">
      Replace the <code class="mono">booths</code> array in
      <code class="mono">data/manual/booth_locations.json</code> with this, then run
      <code class="mono">epcot-fw manual</code>.
    </p>
    <textarea id="export" readonly spellcheck="false"></textarea>
  </section>

  <footer>
    Coordinates are WGS84 decimal degrees, six places (~0.1&nbsp;m — far finer than any phone fix).
    Anchored entries come from the Wikipedia/Wikidata pavilion coordinates and are replaced
    the moment you survey that booth.
  </footer>
</div>

<div class="sticky">
  <span class="count" id="capture-count"></span>
  <span style="display:flex; gap:8px;">
    <button type="button" id="clear">Clear</button>
    <button type="button" class="primary" id="copy">Copy JSON</button>
  </span>
</div>

<script id="booth-data" type="application/json">__BOOTHS_JSON__</script>
<script>
(function () {
  var BOOTHS = JSON.parse(document.getElementById('booth-data').textContent);
  var STORE_KEY = 'epcot-booth-survey-v1';
  var ROUGH_ACCURACY_M = 25;
  // Far enough from a known position that the likeliest explanation is the
  // wrong row was tapped, not that the anchor was off.
  var SUSPICIOUS_DRIFT_M = 400;

  var STALE_FIX_MS = 30000;
  var PENDING_TIMEOUT_MS = 25000;

  var state = {
    captures: load(),
    fix: null,          // newest position from the running watch
    fixError: null,     // 'denied' | 'unavailable'
    pending: null,      // booth name waiting on the next fix
    sortByNearest: false,
    unplacedOnly: false
  };

  function load() {
    try {
      return JSON.parse(localStorage.getItem(STORE_KEY) || '{}') || {};
    } catch (e) {
      return {};  // private mode, cleared site data, storage disabled - start empty
    }
  }
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state.captures)); } catch (e) {}
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // Both arguments are {lat, lon}; a live fix carries extra keys, ignored.
  function metresBetween(a, b) {
    var R = 6371000;
    var toRad = Math.PI / 180;
    var dLat = (b.lat - a.lat) * toRad;
    var dLon = (b.lon - a.lon) * toRad;
    var lat1 = a.lat * toRad, lat2 = b.lat * toRad;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.sin(dLon / 2) * Math.sin(dLon / 2) * Math.cos(lat1) * Math.cos(lat2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function fmtDistance(m) {
    if (m === null || m === undefined) return '';
    if (m < 1000) return Math.round(m) + ' m';
    return (m / 1000).toFixed(1) + ' km';
  }

  // Effective position: a capture beats whatever the database had.
  function positionOf(booth) {
    var cap = state.captures[booth.name];
    if (cap) return { lat: cap.latitude, lon: cap.longitude, precision: 'surveyed', fresh: true };
    if (booth.latitude !== null && booth.latitude !== undefined) {
      return { lat: Number(booth.latitude), lon: Number(booth.longitude), precision: booth.precision, fresh: false };
    }
    return null;
  }

  // ---- geolocation ----
  var supported = 'geolocation' in navigator;
  if (!supported || (!window.isSecureContext && location.protocol !== 'file:')) {
    var box = document.getElementById('unsupported');
    box.classList.remove('hidden');
    box.textContent = supported
      ? 'Location needs a secure connection. Open this page over https (the published copy) rather than plain http.'
      : 'This browser has no Geolocation API, so capture is unavailable. The list below still shows what has been surveyed.';
  }

  // One continuous watch feeds both the distance readouts and capture.
  //
  // Capture used to fire its own getCurrentPosition with maximumAge 0, which
  // is the obvious way to write it and the wrong one: a cold GPS answers a
  // one-shot request by sitting on it, so the surveyor gets a "Locating…"
  // button that does nothing for twenty seconds and then fails. Reading from
  // the stream that is already running makes capture instant once there is a
  // fix, and honest when there isn't - the tap is remembered and completes on
  // the next update.
  if (supported) {
    navigator.geolocation.watchPosition(onFix, onFixError, {
      enableHighAccuracy: true, maximumAge: 5000, timeout: 30000
    });
  }

  function onFix(pos) {
    state.fix = {
      lat: pos.coords.latitude,
      lon: pos.coords.longitude,
      accuracy: Math.round(pos.coords.accuracy),
      at: Date.now()
    };
    state.fixError = null;
    if (state.pending) {
      var name = state.pending;
      state.pending = null;
      commit(name);
      return;  // commit() renders
    }
    render();
  }

  function onFixError(err) {
    state.fixError = (err && err.code === err.PERMISSION_DENIED) ? 'denied' : 'unavailable';
    state.pending = null;
    render();
  }

  function commit(name) {
    state.captures[name] = {
      latitude: Number(state.fix.lat.toFixed(6)),
      longitude: Number(state.fix.lon.toFixed(6)),
      accuracy_m: state.fix.accuracy,
      captured_at: new Date().toISOString()
    };
    save();
    render();
  }

  function capture(booth) {
    if (state.fix && Date.now() - state.fix.at < STALE_FIX_MS) {
      commit(booth.name);
      return;
    }
    // No usable fix yet. Remember the tap and let the watch finish it, rather
    // than storing a stale position from somewhere back up the walkway.
    state.pending = booth.name;
    render();
    setTimeout(function () {
      if (state.pending === booth.name) {
        state.pending = null;
        state.fixError = state.fixError || 'unavailable';
        render();
      }
    }, PENDING_TIMEOUT_MS);
  }

  // ---- render ----
  var list = document.getElementById('booth-list');

  function render() {
    var rows = BOOTHS.slice();

    if (state.unplacedOnly) {
      rows = rows.filter(function (b) { return !positionOf(b) || positionOf(b).precision !== 'surveyed'; });
    }

    if (state.sortByNearest && state.fix) {
      rows.sort(function (a, b) {
        var pa = positionOf(a), pb = positionOf(b);
        // A booth with no coordinate cannot be ranked by distance. It sorts
        // last rather than first: you cannot walk toward something you have
        // no position for, and burying it under "unknown" would hide the
        // very rows the survey exists to fill.
        var da = pa ? metresBetween(state.fix, pa) : Infinity;
        var db = pb ? metresBetween(state.fix, pb) : Infinity;
        return da - db || a.name.localeCompare(b.name);
      });
    }

    list.innerHTML = '';
    rows.forEach(function (booth) {
      var cap = state.captures[booth.name];
      var pos = positionOf(booth);
      var card = document.createElement('div');
      card.className = 'booth' + (cap ? ' captured' : '');

      var pillClass = cap ? 'new' : pos ? (pos.precision === 'surveyed' ? 'surveyed' : 'anchored') : 'unplaced';
      var pillText = cap ? 'Captured' : pos ? (pos.precision === 'surveyed' ? 'Surveyed' : pos.precision === 'mapped' ? 'Mapped' : 'Anchored') : 'Not placed';

      var distance = (state.fix && pos) ? metresBetween(state.fix, pos) : null;

      var metaBits = [];
      if (booth.location_description) metaBits.push(esc(booth.location_description));
      if (pos) metaBits.push('<span class="mono">' + pos.lat.toFixed(5) + ', ' + pos.lon.toFixed(5) + '</span>');
      if (distance !== null) metaBits.push(fmtDistance(distance) + ' away');

      var fixHtml = '';
      if (cap) {
        var rough = cap.accuracy_m > ROUGH_ACCURACY_M;
        fixHtml = '<span class="fix' + (rough ? ' rough' : '') + '">' +
          (rough ? '&#9888; ' : '&#10003; ') + '&plusmn;<b>' + cap.accuracy_m + ' m</b>' +
          (rough ? ' — hold still and retake' : '') + '</span>';

        var known = (booth.latitude !== null && booth.latitude !== undefined)
          ? { lat: Number(booth.latitude), lon: Number(booth.longitude) } : null;
        if (known && metresBetween(known, { lat: cap.latitude, lon: cap.longitude }) > SUSPICIOUS_DRIFT_M) {
          fixHtml += '<span class="fix rough">&#9888; far from where this booth was expected — right one?</span>';
        }
      }

      card.innerHTML =
        '<div class="booth-top">' +
          '<span class="booth-name">' + esc(booth.name) + '</span>' +
          '<span class="pill ' + pillClass + '">' + pillText + '</span>' +
        '</div>' +
        (metaBits.length ? '<div class="booth-meta">' + metaBits.join(' · ') + '</div>' : '') +
        '<div class="booth-actions"></div>';

      var actions = card.querySelector('.booth-actions');
      var waiting = state.pending === booth.name;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = waiting ? 'Waiting for a fix…' : cap ? 'Retake' : 'Capture';
      btn.disabled = !supported || waiting;
      btn.addEventListener('click', function () { capture(booth); });
      actions.appendChild(btn);

      if (cap) {
        var undo = document.createElement('button');
        undo.type = 'button';
        undo.textContent = 'Discard';
        undo.addEventListener('click', function () {
          delete state.captures[booth.name];
          save();
          render();
        });
        actions.appendChild(undo);
      }
      if (fixHtml) {
        var fix = document.createElement('span');
        fix.innerHTML = fixHtml;
        actions.appendChild(fix);
      }

      list.appendChild(card);
    });

    renderTallies();
    renderFix();
    renderExport();
  }

  function renderFix() {
    var el = document.getElementById('fix-banner');
    if (!supported) { el.classList.add('hidden'); return; }
    el.classList.remove('hidden');
    if (state.fixError === 'denied') {
      el.className = 'panel warn';
      el.textContent = 'Location permission is off for this page. Turn it on in your browser settings, then reload.';
    } else if (state.fixError === 'unavailable') {
      el.className = 'panel warn';
      el.textContent = 'No GPS fix yet. Step into the open, away from an overhang, and give it a moment.';
    } else if (!state.fix) {
      el.className = 'panel note';
      el.textContent = 'Waiting for a GPS fix…';
    } else {
      el.className = 'panel note';
      var rough = state.fix.accuracy > ROUGH_ACCURACY_M;
      el.innerHTML = 'Current fix: <b>&plusmn;' + state.fix.accuracy + ' m</b>' +
        (rough ? ' — worth waiting for it to settle before capturing.' : ' — good to capture.');
    }
  }

  function renderTallies() {
    var surveyed = 0, anchored = 0, unplaced = 0;
    BOOTHS.forEach(function (b) {
      var pos = positionOf(b);
      if (!pos) unplaced++;
      else if (pos.precision === 'surveyed') surveyed++;
      else anchored++;
    });
    document.getElementById('tallies').innerHTML =
      '<span class="tally">Surveyed <b>' + surveyed + '</b></span>' +
      '<span class="tally">Anchored <b>' + anchored + '</b></span>' +
      '<span class="tally">Not placed <b>' + unplaced + '</b></span>' +
      '<span class="tally">Booths <b>' + BOOTHS.length + '</b></span>';

    var n = Object.keys(state.captures).length;
    document.getElementById('capture-count').textContent =
      n === 0 ? 'Nothing captured yet' : n + (n === 1 ? ' booth captured' : ' booths captured');
    document.getElementById('copy').disabled = n === 0;
  }

  // The whole array, not just today's captures: the file is replaced
  // wholesale, so anything already placed has to survive the paste.
  function renderExport() {
    var entries = [];
    BOOTHS.forEach(function (b) {
      var cap = state.captures[b.name];
      if (cap) {
        entries.push({
          name: b.name,
          latitude: cap.latitude,
          longitude: cap.longitude,
          location_precision: 'surveyed',
          location_description: b.location_description || undefined
        });
      } else if (b.latitude !== null && b.latitude !== undefined) {
        entries.push({
          name: b.name,
          latitude: Number(b.latitude),
          longitude: Number(b.longitude),
          location_precision: b.precision || 'anchored',
          location_description: b.location_description || undefined
        });
      }
    });
    document.getElementById('export').value = JSON.stringify({ booths: entries }, null, 2);
  }

  // ---- controls ----
  var sortBtn = document.getElementById('sort-toggle');
  sortBtn.addEventListener('click', function () {
    state.sortByNearest = !state.sortByNearest;
    sortBtn.classList.toggle('active', state.sortByNearest);
    render();
  });
  var filterBtn = document.getElementById('filter-toggle');
  filterBtn.addEventListener('click', function () {
    state.unplacedOnly = !state.unplacedOnly;
    filterBtn.classList.toggle('active', state.unplacedOnly);
    render();
  });
  document.getElementById('clear').addEventListener('click', function () {
    if (!Object.keys(state.captures).length) return;
    if (!confirm('Discard every capture on this device?')) return;
    state.captures = {};
    save();
    render();
  });
  document.getElementById('copy').addEventListener('click', function () {
    var area = document.getElementById('export');
    var done = function () {
      var btn = document.getElementById('copy');
      btn.textContent = 'Copied';
      setTimeout(function () { btn.textContent = 'Copy JSON'; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(area.value).then(done, function () { area.select(); });
    } else {
      area.select();
      try { document.execCommand('copy'); done(); } catch (e) {}
    }
  });

  render();
})();
</script>
</body>
</html>
"""


def render(snapshot: dict[str, Any]) -> str:
    """Snapshot in, complete self-contained page out."""
    booths = survey_booths(snapshot)
    # Substituted rather than f-stringed: booth names are scraped text and can
    # contain braces and "__"-style runs. `</` is broken up because the blob
    # sits inside a <script> element, where the HTML parser ends the element at
    # the first `</script>` regardless of JSON quoting.
    payload = json.dumps(booths, default=str).replace("</", "<\\/")
    return TEMPLATE.replace("__BOOTHS_JSON__", payload)
