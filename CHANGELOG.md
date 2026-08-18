# Changelog

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
