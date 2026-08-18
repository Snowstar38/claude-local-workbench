# claude-local-workbench — Build Spec

A local, self-contained replacement for the retired Anthropic Workbench, with the one feature
Anthropic removed: **version history of every edit/run**.

## Architecture (decided — don't revisit)

- **One single self-contained HTML file**: `workbench.html`.
  No build step, no CDN, no external requests except to `https://api.anthropic.com`.
  Rationale: portable — works from `file://` today, and the same file can be dropped on
  any static host and opened on a phone. Desktop-first layout is fine; mobile-friendly
  is a stretch goal, not required now.
- **Direct browser → API calls** with header `anthropic-dangerous-direct-browser-access: true`
  plus `x-api-key`, `anthropic-version: 2023-06-01`, `content-type: application/json`.
- **Storage**: IndexedDB for chats + versions (unbounded history is a *feature* — full
  history is the point, and the space cost is accepted). `localStorage` for the API key and UI prefs.
- **Backup/portability**: "Export all data" button → single JSON file of every chat + version.
  "Import backup" restores it (merge by chat id, keep newer). This is how data moves to another
  device, since IndexedDB is per-browser.

## Core data model

```
Chat: { id, name, createdAt, updatedAt, versions: [...], currentDraft }
Version (snapshot): {
  id, createdAt, label?,           // label optional, user-editable later
  settings: { model, maxTokens, temperature?, system },
  messages: [ { role: "user"|"assistant", content: [blocks] } ],
  completion?: { content: [blocks], stopReason, usage, model }  // the run's result
}
```

Store versions as full snapshots (simple, robust; she chose space over cleverness).

## Versioning semantics (the heart of the app)

- Hitting **Run** snapshots the *current edited state* (messages + system + settings) as a new
  version, then streams the completion; when the stream finishes, the completion is saved onto
  that same version. Only the most recent completion per version is kept.
- **Add to conversation** appends the completion as an assistant message to the current draft
  (normal workbench behavior). Doesn't create a version by itself; the next Run snapshots it.
- **Versions panel** per chat: newest first, showing timestamp, model, message count, and a short
  preview (first ~60 chars of the last message — content is hers, fine to show in her own UI).
- **Restore**: loads that snapshot as the current draft. If the current draft has unsaved changes
  (differs from the newest version), auto-snapshot it first as "(auto-saved before restore)" so
  nothing is ever lost. Also show the version's saved completion, if any.
- Optional nice-to-have: "Save version now" manual button.

## Editor UI (Workbench-style)

- Sidebar: chat list (rename, delete with confirm, new chat), import buttons, settings (API key).
- Main pane: collapsible System Prompt textarea; the message list — each message has a
  role toggle (User/Assistant), auto-growing textarea, delete, and insert-below; an
  "＋ Add message" at the end.
- **Prefill**: a trailing *assistant* message acts as the prefill, exactly like the old Workbench.
  On Run, if the last message is `assistant`, it's sent as prefill. See model gating below.
- **Completion pane**: streams the response live (render thinking summary, if any, as a muted
  collapsible block above the text). Buttons: "Add to conversation", "Retry" (new Run), Stop.
  Show stop_reason and token usage after each run.
- Settings bar: model picker, max-tokens slider (log-ish scale, 256 → 128000, editable number
  next to it), temperature slider (only when the model supports it), effort dropdown
  (low/medium/high/xhigh/max, only for models supporting it; omit param when "default").
- Errors: parse API error JSON `{type:"error", error:{type, message}}` and show it in a
  dismissible banner, verbatim message included.

## Model picker

- On load (when an API key exists), `GET https://api.anthropic.com/v1/models` (same headers)
  and populate; cache in localStorage. Fall back to a hardcoded list if the fetch fails:
  claude-fable-5, claude-opus-5, claude-opus-4-8, claude-opus-4-7, claude-opus-4-6,
  claude-sonnet-5, claude-sonnet-4-6, claude-haiku-4-5, claude-opus-4-5-20251101,
  claude-sonnet-4-5-20250929, claude-3-7-sonnet-20250219, claude-3-opus-20240229 (she has old
  chats on 3-era models; keep whatever /v1/models returns as the source of truth).

## Model capability gating (verified against skill docs; smoke tests will confirm)

- **Prefill (trailing assistant message)**: returns **400** on claude-fable-5, claude-opus-5,
  claude-sonnet-5, and the opus/sonnet 4.6/4.7/4.8 family. Still works on claude-haiku-4-5,
  4.5-era and older (3.x etc.). When the last message is assistant and the model doesn't
  support prefill: show a small inline warning ("this model rejects prefill — Run will fail")
  but still allow the attempt; surface the API error cleanly.
- **temperature/top_p/top_k**: removed (400) on fable-5, opus-5, sonnet-5, opus-4-7/4-8.
  Allowed on 4.6 and older. Hide/disable the slider accordingly; never send the param when
  unsupported or when unset.
- **thinking param**: do NOT send a `thinking` parameter at all (default behavior is fine on
  every model; fable is always-adaptive; older models simply don't think). Keep it simple.
- **effort**: `output_config: {effort}` supported on opus-4.6+ / sonnet-5 / fable (fable also
  supports xhigh/max; 4.6 supports low/medium/high/max). Only send when the user picks
  something; a plain dropdown with "default" + the five levels is fine, and if the API rejects
  a level for that model, the error banner tells her.
- Implement gating as one function keyed on model-id patterns so it's easy to update.
- **Fable 5 note**: `stop_reason: "refusal"` can occur (HTTP 200); show a clear notice with
  `stop_details.explanation` if present.

## Request building

- Roles: the export uses "human" — convert to "user" on import. API wants "user"/"assistant".
- Merge consecutive same-role messages? No — just send as-is; the API accepts alternation
  violations poorly, so instead **coalesce consecutive same-role messages** into one with
  joined text ("\n\n") at request-build time only (keep the draft as she arranged it).
- **Strip thinking blocks** from outgoing messages (old signatures don't replay across models);
  keep them in storage for display, collapsed.
- Always `stream: true`; parse SSE: `message_start`, `content_block_start`,
  `content_block_delta` (`text_delta`, `thinking_delta`), `content_block_stop`,
  `message_delta` (stop_reason, usage), `message_stop`, and `error` events. Support Abort via
  AbortController (Stop button).
- With prefill, the first text delta continues the prefill text — display accordingly
  (completion pane shows prefill in dimmed text followed by the streamed continuation).

## Import (official Workbench export)

File picker + drag-drop accepting **either** `prompts.json` **or** the whole export `.zip`.

- Zip parsing must be dependency-free: read the End of Central Directory, walk the central
  directory, find `workbench/prompts.json`, inflate with
  `new DecompressionStream("deflate-raw")` (method 8) or slice directly (method 0).
- `prompts.json` format (redacted schema from her real export — 15 prompts):

```
[ { uuid, name, workspace_uuid, created_by:{...}, created_at, updated_at,
    latest_revision: {
      uuid, name, created_by, created_at,
      system_prompt: string,
      model: string,            // e.g. "claude-3-opus-20240229", "claude-fable-5"
      temperature: number, max_tokens: number,
      variables: [], tools: [], forced_tool: null,
      thinking: null | {type:"adaptive", display:null, ...},
      output_config: null | {effort: string},
      messages: [ { uuid, index, role: "human"|"assistant",
                    content: [ { type:"text"|"thinking", text?, thinking?, signature?,
                                 citations:null, cache_reference:null } ] } ]
    } } ]
```

- Each prompt → one Chat named from `name` (fallback: "Imported <date>"), with **one initial
  version** built from the revision (settings from model/temperature/max_tokens/system_prompt,
  messages sorted by `index`). Preserve thinking blocks in storage (display-only).
- Import must be idempotent-ish: if a chat with the same source uuid already exists, skip it
  and report (store source uuid on the chat).

## Look and feel

Load the `artifact-design` skill? No — this is a local tool, not an artifact. But do make it
pleasant: clean, calm, readable; light + dark via `prefers-color-scheme`; system font stack;
the vibe of the old Workbench (left sidebar, centered editor column, right versions rail).
The primary use case is daily long-form creative conversations — prioritize comfortable reading
and editing of long text. Textareas must auto-grow and never fight the writer.

## Privacy constraints (hard rules)

- Real Workbench exports are private. Do NOT build or test the importer against anyone's
  real export — use a **synthetic** fixture matching the schema above
  (`fixtures/synthetic-prompts.json` is exactly that).
- The app never embeds an API key; the user pastes it into the UI once and it's
  localStorage-only.

## Deliverables

- `C:\Fable 5\workbench\workbench.html` — the app.
- `C:\Fable 5\workbench\README.md` — short guide: first-run (paste key), import steps,
  what versioning does, how to back up / move to phone, known model quirks (prefill/temp).
- `C:\Fable 5\workbench\fixtures\synthetic-prompts.json` — the synthetic test fixture.
