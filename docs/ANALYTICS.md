# Analytics

Anonymous, aggregate usage data from Epcot Events, sent through [PostHog](https://posthog.com).
The source of truth for the numbers is the PostHog project dashboard; `docs/studio.html`'s
Insights tab reads a summary of the same data client-side (see below).

## Why PostHog

Chosen over TelemetryDeck for cost headroom at an early launch that may grow: PostHog's free tier
is 1,000,000 events/month against TelemetryDeck's 50,000/month, and paid usage beyond that scales
gradually rather than jumping to a flat tier. It's also open-source and self-hostable, so outgrowing
the SaaS plan is a config change, not a rewrite. No server of this project's own is involved —
`src/epcot_fw` and the Postgres database are untouched by any of this.

Autocapture and session replay are off in `AnalyticsService.swift`. The app only ever sends the
named events below — nothing ambient.

## Privacy

- Every event goes through `AnalyticsTracking` (`Epcot Events/Epcot Events/Model/AnalyticsService.swift`),
  never the PostHog SDK directly, so the vendor could change later without touching a call site.
- Payloads are counts, ids, and enum-like strings only — **never** user-authored text (note bodies,
  task titles).
- Settings → Privacy → "Share Analytics" (on by default) is checked on every event; turning it off
  stops new events immediately, no restart needed.
- PostHog's default anonymous, per-install identifier is used — not IDFA — so no App Tracking
  Transparency prompt is required.

## Events

| Event | Fired when | Payload | Source |
|---|---|---|---|
| `session.started` | Cold launch, or resume after 5+ minutes inactive | — | `ContentView.swift` |
| `session.ended` | App goes inactive/background | `durationSeconds` | `ContentView.swift` |
| `screen.viewed` | A pushed page appears | `screen` (see list below) | `.trackScreen(_:)`, applied per page |
| `wishlist.itemAdded` | A dish is favorited | `wishlistCount` (count after the change) | `FestivalStore.addFavorite` |
| `wishlist.itemRemoved` | A dish is unfavorited | `wishlistCount` | `FestivalStore.removeFavorite` |
| `note.created` | A blank note gets its first content | — | `PlannerStore.updateNote` |
| `note.deleted` | A note with content is deleted | — | `PlannerStore.deleteNote` |
| `task.added` | A favorite is promoted to a Plans task | — | `PlannerStore.toggleTask` |
| `task.completed` | A task is checked off | — | `PlannerStore.setComplete` |
| `itinerary.saved` | A newly generated route is filed (not the idempotent re-file on re-appearance) | `stopCount` | `ItineraryHistoryStore.record` |
| `itinerary.deleted` | A saved itinerary is removed | — | `ItineraryHistoryStore.delete` |
| `feedback.sent` | A feedback message is handed off (mail sent, or `mailto:` opened successfully) | `category` (`bug` \| `idea`) | `FeedbackComposerView.send` |

`screen.viewed`'s `screen` values in use today: `Wishlist`, `Plans`, `Notes`, `NoteDetail`,
`Itinerary`, `ItineraryHistory`, `Settings`, `Filters`, `AppIcon`, `Premium`, `About`, `Feedback`.
The root map + sheet home isn't tracked as a screen — it's always visible, not a navigation event.

Keep this table in sync when a new page or mutation point is added. If it drifts, the numbers in
Studio stop meaning what this file says they mean.

## Studio's Insights tab

`docs/studio.html` has an Insights tab that reads a handful of aggregates back from PostHog's
Query API — daily/weekly active devices, average session length, top screens, a wishlist-size
distribution, and note/itinerary/task creation counts over the trailing 30 days.

It asks for a **scoped, read-only** PostHog personal API key the first time it's opened, and keeps
it in that browser's `localStorage` only. **Never put this key in the HTML itself** —
`docs/studio.html` is published to GitHub Pages with no auth (see `docs/WORKFLOW.md`), so anything
baked into the page is visible to anyone with the URL. Create the key in PostHog's project settings,
scoped to read-only access on this one project, and paste it into Studio once per browser.

If Studio ever needs re-pointing at a different PostHog project, the key is the only thing to
change — clear it from `localStorage` (the tab prompts again) and paste the new one.
