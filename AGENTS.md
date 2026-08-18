# Orientation for agents (and humans) working on this code

The app is **one file**, `workbench.html` (~2,900 lines), deliberately
dependency-free: no build step, no framework, no external requests except
`https://api.anthropic.com`. Keep it that way — single-file portability is the
core design decision, not an accident.

## Workflow

1. Read the relevant section of `workbench.html` — the script is organised in
   numbered, commented sections (helpers → storage → model gating → request/SSE
   → state → rendering → import/backup → wiring/boot).
2. Make the change.
3. **Run `python tools/verify.py` — it must print `ALL CHECKS PASSED`.** The
   harness ports the app's pure logic (zip reader, SSE parser, import mapping,
   model gating, pricing) to Python, tests the ported logic, then asserts the
   HTML still contains the same code. When you add a feature, extend the
   harness the same way.
4. Untrusted content (imported files, API responses, error messages) must reach
   the DOM through `textContent`/`el()` — never through `innerHTML` with
   interpolated strings.

`docs/SPEC.md` is the original build spec (data model, import mapping rules,
UI contract). `docs/smoke-results.md` is the raw evidence for the API facts
below. `fixtures/synthetic-prompts.json` deliberately exercises the importer's
awkward cases (a `human` role, a fake-signature thinking block, an old model
id, out-of-order indices, an empty prompt name, a trailing assistant prefill).

## Places you'll most likely touch

- **`modelCaps()`** (section 3) — all model gating in one function. Two
  hardcoded denylists (`PREFILL_DENY`, `SAMPLING_DENY` — deliberately
  *different* sets, prefix-matched so dated snapshots resolve), plus effort
  levels read live from `GET /v1/models` `capabilities` with an offline table
  as fallback. A new model launch should be a few lines here.
- **`PRICES`** (section 3, beside `modelCaps`) — $/MTok, prefix-matched,
  longest prefix first so `claude-opus-4` can't shadow `claude-opus-4-8`.
  Hardcoded because there's no pricing endpoint; last verified 2026-06-24.
  Update it here and both the estimate and the post-run cost follow.
- **Section 4** — request building and the SSE parser.
- **Section 7b** — the file auto-save. Two invariants it must keep: writes are
  serialised (one in flight, single trailing re-run), and neither side is ever
  clobbered silently — both directions go through `importBackup()`'s merge.
- **`applyLayout()`** (section 8) — split vs stacked. It physically moves the
  completion card and the run bar between slots; anything querying them should
  use the helpers rather than assuming a parent. Stream-follow scrolling goes
  through `completionScroller()`.

## Hard-won API facts — verified live 2026-08-17; do NOT "fix" from priors

These were all confirmed by running `tools/api-probe.py` against the real API
(transcripts in `docs/smoke-results.md`). If one seems wrong, re-run the probe
before changing code.

- **Two DIFFERENT model denylists.** Prefill (trailing assistant message)
  returns 400 on 4.6 and newer (fable-5, mythos, opus-5, sonnet-5,
  opus/sonnet-4-6/4-7/4-8). `temperature`/`top_p`/`top_k` return 400 only on
  4.7+, opus-5, sonnet-5, and fable — **4.6 accepts temperature but rejects
  prefill.** Both lists live in `modelCaps()` with prefix matching.
- Prefill responses return the **continuation only**; the app concatenates
  prefill + stream for display and for "Add to conversation".
- `GET /v1/models` has a per-model `capabilities` object (effort levels etc.),
  used live for effort gating; prefill/sampling support are NOT in it.
  Paginates via `has_more`/`last_id`.
- Deprecated models can still work for an account while absent from
  `/v1/models` — hence the merged picker plus the custom-id option. Never drop
  a model from a chat just because the listing doesn't include it.
- Consecutive same-role messages are **accepted** by the API; the app
  deliberately never merges them.
- The response's `model` field differs from the request's (aliases resolve to
  dated ids); never compare them.
- SSE quirks: `data:` lines carry trailing whitespace; `ping` events interleave
  anywhere; `stop_details` is present-but-null on normal stops. A bad model id
  returns **404** (not 400) with a terse `"model: <id>"` message — the one
  error the app rewrites into something friendlier.
- `POST /v1/messages/count_tokens` is free; used for the exact input-cost
  estimate, with a chars/3.5 fallback marked `~`.
- `anthropic-dangerous-direct-browser-access: true` is accepted on every
  endpoint the app uses.
- No `thinking` parameter is ever sent — deliberate; see the comment in
  `buildRequest()`.

## Data formats (compatibility promises)

- **Backup JSON** (`Back up all`, the linked auto-save file): `app` field is
  `"claude-local-workbench"`, `formatVersion: 1`, chats with versions nested.
  The importer must **forever** also accept the pre-release id
  `"michelle-workbench"` — existing users' backups carry it.
- **IndexedDB**: database `claude-local-workbench` v2 (stores: `chats`,
  `versions`, `meta`). `migrateLegacyDB()` copies data from the pre-release
  database name once, when the new DB is empty; don't remove it casually.
- **Official Workbench export**: `prompts.json` schema is documented in
  `docs/SPEC.md`; the zip reader is minimal but harness-tested.

## Non-negotiables

- The API key must never appear in backups, the linked save file, URLs, or
  console output — it lives only in `localStorage` (`wb.apiKey`), or purely in
  memory when the "this page only" option is ticked, and in the `x-api-key`
  request header to `api.anthropic.com`. The ephemeral mode must never write
  the key to any storage, including `sessionStorage`.
- The API base URL is hardcoded; never make it derivable from imported data.
- Never overwrite user data silently: imports and merges add and prefer newer,
  they never delete.
- No external resources (scripts, fonts, CDNs, telemetry). One file, forever.
