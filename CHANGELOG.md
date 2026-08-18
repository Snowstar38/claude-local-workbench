# Changelog

## 1.0.9 — 2026-08-18

- Chat rows now show a single ⋯ menu on hover offering Duplicate, Rename, and
  Delete (replacing the separate rename/delete icons). Duplicate copies the
  draft and the chat's entire version history.

## 1.0.8 — 2026-08-18

- Chat-list dates outside the current year now include the year. The list has
  always been sorted newest-first, but "Nov 30" below "Jan 18" looked broken
  when they were different years.

## 1.0.7 — 2026-08-18

- The max-tokens "4096" number box no longer pokes past the settings card's
  right edge when both side panels squeeze the middle column: the slider row
  and the number box can now shrink a little (the box floors at a width that
  still fits 128000), and field hints ellipsize instead of setting a minimum.

## 1.0.6 — 2026-08-18

- The cost estimate no longer overflows the top bar's right edge when both
  side panels are open in split view: the run controls block was missing
  `min-width:0`, so it refused to shrink and the estimate couldn't ellipsize.

## 1.0.5 — 2026-08-18

- Prefill indicators now work without hover (so, on phones): the model picker
  says "supports prefill" in plain text next to any model that accepts it, and
  an empty trailing assistant turn explains the mechanic — or the model's
  refusal of it — in its placeholder. The run-bar chip and the per-message
  prefill pill are gone; the run bar now only reports `unsaved` and streaming.

## 1.0.4 — 2026-08-18

- The run-bar status ("Trailing assistant turn will be sent as a prefill",
  the rejects-prefill warning, unsaved changes) is now a compact chip —
  `prefill`, `prefill ✗`, `unsaved` — with the full sentence in its tooltip.
  Small enough that narrow windows keep it instead of hiding it.

## 1.0.3 — 2026-08-18

- The panel toggles no longer run away from the pointer: each open panel now
  has its own hide arrow (◂ in the chat list header, ▸ in the versions
  header) sitting in the same screen corner the top-bar toggle occupies while
  that panel is closed, so showing and hiding happens in one place.

## 1.0.2 — 2026-08-18

- Fixed the whole page scrolling (top bar sliding away) on long conversations:
  the app grid's row was sized to content instead of the viewport, so the
  conversation pane never scrolled internally as designed.

## 1.0.1 — 2026-08-18

- The three header rows (chat list, top bar, versions rail) share one height,
  so their bottom borders draw a single line across the window and the
  version-count pill no longer sits higher than the buttons beside it.
- README now actively encourages forks.

## 1.0.0 — 2026-08-17

First public release.

- Single-file app: chats, per-Run version history, restore, labels.
- Import of official Workbench export zips (or bare `prompts.json`).
- Direct browser → Anthropic API calls with streaming (SSE).
- Prefill support with accurate per-model gating; separate temperature gating
  (the two denylists really are different — see `AGENTS.md`).
- Effort levels read live from the Models API; deprecated-model access via a
  merged picker plus custom model ids.
- Exact input-cost estimate via `count_tokens`; per-run cost from a built-in
  price table (last verified 2026-06-24).
- Backups: one-file export/restore with safe merging, plus an optional linked
  auto-save file (Chromium desktop, File System Access API).
- Split and stacked layouts, light/dark/system theme.
- Offline verification harness (`tools/verify.py`, 319 checks) and a live API
  probe (`tools/api-probe.py`).
- One ⚙ Settings dialog holding the API key, the linked save file, and the
  theme (light / dark / follow-system).
- Optional "this page only" key mode: the key is kept in memory, written to no
  storage, and forgotten on refresh or close.
- Hardened for public release after an independent security review: strict
  Content-Security-Policy (connect-src locked to `api.anthropic.com`),
  sanitized backup imports, zip-bomb cap on the export unpacker, and a
  confirmation before an unrecognized linked file could ever be overwritten.
