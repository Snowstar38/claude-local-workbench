# Claude API smoke results — Workbench replacement app

Empirical verification run **2026-08-17** against `https://api.anthropic.com`, raw HTTP
(Python 3.14 stdlib `urllib`). The probe script is preserved as `tools/api-probe.py`;
re-run it (it costs a few cents) to re-verify these behaviors after API changes.

Headers sent on **every** request:

```
x-api-key: <key>
anthropic-version: 2023-06-01
content-type: application/json
anthropic-dangerous-direct-browser-access: true
```

**The `anthropic-dangerous-direct-browser-access: true` header was accepted on every
request** (GET and POST, streaming and non-streaming) — no rejection, no warning header.
Safe for the browser→API direct-call design.

## Headline: both documented gating rules are CONFIRMED exactly as written

| Rule | Verdict |
|---|---|
| Prefill → 400 on fable-5 / opus-5 / sonnet-5 / opus 4.6–4.8 / sonnet 4.6; works on haiku-4-5 and older | **Confirmed** |
| `temperature`/`top_p`/`top_k` → 400 on fable-5 / opus-5 / sonnet-5 / opus-4-7 / opus-4-8; allowed on 4.6 and older | **Confirmed** |

Note the two sets are **not** the same: Opus 4.6 and Sonnet 4.6 reject prefill but *accept*
`temperature`. The app needs two separate capability lists, not one "modern model" flag.

Two surprises worth acting on, both detailed below:

1. `GET /v1/models` now returns a per-model `capabilities` object — the app can gate
   `effort`, thinking types, structured outputs, PDF/image input, batch, and context
   management **from live data** instead of a hardcoded table. (Prefill and sampling params
   are *not* in `capabilities`; those two still need a hardcoded list.)
2. Two consecutive same-role user messages are **accepted** (HTTP 200). No coalescing needed.

---

## 1. GET /v1/models

**Request:** `GET /v1/models` (and `?limit=5`, `?limit=5&after_id=…`)

**Status:** `200`

**Shape:** top-level keys are exactly `["data", "has_more", "first_id", "last_id"]`.
It **does paginate**, cursor-style via `after_id` / `before_id` + `limit`.

- `GET /v1/models` → 11 models, `has_more: false`, `first_id: "claude-opus-5"`, `last_id: "claude-3-opus-20240229"`
- `GET /v1/models?limit=5` → 5 models, `has_more: true`, `last_id: "claude-opus-4-7"`
- `GET /v1/models?limit=5&after_id=claude-opus-4-7` → next 5, `has_more: true`

Default page size returned the full list here (11 < default limit), but **the app should
still follow `has_more`/`last_id`** rather than assume one page.

**Full id list, in returned order (newest first):**

```
claude-opus-5, claude-sonnet-5, claude-fable-5, claude-opus-4-8, claude-opus-4-7,
claude-sonnet-4-6, claude-opus-4-6, claude-opus-4-5-20251101, claude-haiku-4-5-20251001,
claude-sonnet-4-5-20250929, claude-3-opus-20240229
```

Note current-generation models are returned **undated** (`claude-opus-5`), while 4.5-era and
older are returned **dated** (`claude-haiku-4-5-20251001`). Aliases still resolve: requesting
`claude-haiku-4-5` works and the response's `model` field echoes back the dated
`claude-haiku-4-5-20251001`. **Don't string-compare the request model against the response
model** — they legitimately differ.

**Per-model object keys:** `type`, `id`, `display_name`, `created_at`, `max_input_tokens`,
`max_tokens`, `capabilities`. There is no `context_window` field — the context window is
`max_input_tokens`, the output cap is `max_tokens`.

Sample entry (truncated capabilities):

```json
{
  "type": "model",
  "id": "claude-opus-5",
  "display_name": "Claude Opus 5",
  "created_at": "2026-07-24T00:00:00Z",
  "max_input_tokens": 1000000,
  "max_tokens": 128000,
  "capabilities": {
    "batch": {"supported": true},
    "citations": {"supported": true},
    "code_execution": {"supported": true},
    "context_management": {"supported": true, "clear_tool_uses_20250919": {"supported": true},
      "clear_thinking_20251015": {"supported": true}, "compact_20260112": {"supported": true}},
    "effort": {"supported": true, "low": {"supported": true}, "medium": {"supported": true},
      "high": {"supported": true}, "xhigh": {"supported": true}, "max": {"supported": true}},
    "image_input": {"supported": true},
    "pdf_input": {"supported": true},
    "structured_outputs": {"supported": true},
    "thinking": {"supported": true, "types": {"enabled": {"supported": false}, "adaptive": {"supported": true}}}
  }
}
```

`GET /v1/models/claude-haiku-4-5` returns the same object shape for a single model (also 200).

### Capability data usable for gating

| Model | effort | effort.xhigh | thinking.enabled | thinking.adaptive | compact_20260112 | code_execution |
|---|---|---|---|---|---|---|
| claude-opus-5 | yes | yes | **no** | yes | yes | yes |
| claude-sonnet-5 | yes | yes | **no** | yes | yes | yes |
| claude-fable-5 | yes | yes | **no** | yes | yes | yes |
| claude-opus-4-8 | yes | yes | **no** | yes | yes | yes |
| claude-opus-4-7 | yes | yes | **no** | yes | yes | yes |
| claude-sonnet-4-6 | yes | **no** | yes | yes | yes | yes |
| claude-opus-4-6 | yes | **no** | yes | yes | yes | yes |
| claude-opus-4-5-20251101 | yes (low/med/high only) | no | yes | **no** | no | yes |
| claude-haiku-4-5-20251001 | **no** | no | yes | **no** | no | **no** |
| claude-sonnet-4-5-20250929 | **no** | no | yes | no | no | yes |

`thinking.types.enabled.supported == false` turns out to be a perfect proxy for the
**sampling-parameter** ban (exactly opus-5, sonnet-5, fable-5, opus-4-8, opus-4-7 — see §5).
It is **not** a proxy for the prefill ban, which also covers the 4.6 models. Prefill support
is not exposed in `capabilities` at all, so keep a hardcoded prefill denylist.

---

## 2. Streaming — claude-haiku-4-5

**Request:** `POST /v1/messages`, `{"model":"claude-haiku-4-5","max_tokens":40,"stream":true,"messages":[{"role":"user","content":"Say hi in 3 words."}]}`

**Status:** `200`, `content-type: text/event-stream; charset=utf-8`

Event sequence observed (each `event:` line followed by a `data:` line, then a blank line):

```
event: message_start
data: {"type":"message_start","message":{"model":"claude-haiku-4-5-20251001","id":"msg_011Ce9LTG5UYrssoLtfkbmUT","type":"message","role":"assistant","content":[],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":15,"cache_creation_input_tokens":0,"cache_read_input_t…[truncated]

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}     }

event: ping
data: {"type": "ping"}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hey"} }

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":", how's it?"}   }

event: content_block_stop
data: {"type":"content_block_stop","index":0             }

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null,"stop_details":null},"usage":{"input_tokens":15,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":9}     }

event: message_stop
data: {"type":"message_stop"       }
```

Implementation notes for the browser SSE parser:

- Order: `message_start` → (`content_block_start` → `ping`? → `content_block_delta`* → `content_block_stop`)* → `message_delta` → `message_stop`.
- `ping` events can appear **anywhere** in the stream, including between content blocks. Ignore them by `type`, don't let them break a state machine.
- The `data:` JSON is **padded with trailing spaces** (visible above). Parse with `JSON.parse`, never by byte length or string equality.
- The `type` field inside `data` duplicates the `event:` name — dispatching on the parsed `data.type` is sufficient and simpler than reading the `event:` line.
- `message_start` carries `usage.input_tokens` immediately; final `output_tokens` arrives on `message_delta`. `stop_reason` is `null` in `message_start` and populated in `message_delta`.
- `stop_details` is present and `null` on non-refusal responses — always null-guard before reading `.category`.
- The final `message_stop` has no useful payload.
- Errors mid-stream would arrive as an `error` event; not exercised in this run.

---

## 3. Prefill — claude-haiku-4-5 (works)

**Request:** `{"model":"claude-haiku-4-5","max_tokens":40,"messages":[{"role":"user","content":"Say the alphabet."},{"role":"assistant","content":"A B C"}]}`

**Status:** `200` — **continues from the prefill**, and does not repeat it.

```json
{"model":"claude-haiku-4-5-20251001","id":"msg_011Ce9LTKzcs3KK8oUi2NALS","type":"message","role":"assistant",
 "content":[{"type":"text","text":" D E F G H I J K L M N O P Q R S T U V W X Y Z"}],
 "stop_reason":"end_turn","stop_sequence":null,"stop_details":null,
 "usage":{"input_tokens":14,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,
  "cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":0},
  "output_tokens":26,"service_tier":"standard","inference_geo":"not_available"}}
```

The returned text is the **continuation only** (`" D E F …"`, leading space preserved). If the
app renders a prefill conversation, it must concatenate the prefill text with the response
text itself — the API does not echo the prefill back.

---

## 4. Prefill — rejected models

Same message array, per model. All `400`:

| Model | Status |
|---|---|
| claude-sonnet-5 | 400 |
| claude-opus-5 | 400 |
| claude-fable-5 | 400 |
| claude-sonnet-4-6 | 400 |
| claude-opus-4-6 | 400 |

**Exact error JSON** (byte-identical across all five, only `request_id` differs):

```json
{"type":"error",
 "error":{"type":"invalid_request_error",
          "message":"This model does not support assistant message prefill. The conversation must end with a user message."},
 "request_id":"req_011Ce9LTNa9ZiYeCNTxRHF9o"}
```

The `request_id` appears **both** as a top-level field on the error envelope and in the
`request-id` response header — the app can surface either.

**UI messaging suggestion:** the server's own wording ("The conversation must end with a user
message") is already user-grade; the app can surface `error.message` verbatim rather than
inventing copy.

---

## 5. Sampling parameters

### 5a. `temperature: 0.7` on claude-sonnet-5 → `400`

```json
{"type":"error",
 "error":{"type":"invalid_request_error","message":"`temperature` is deprecated for this model."},
 "request_id":"req_011Ce9LTUZp6jYcyfCgNjfGs"}
```

### 5b. `temperature: 0.7` on claude-haiku-4-5 → `200`

```json
{"model":"claude-haiku-4-5-20251001","id":"msg_011Ce9LTWH124U3a1r7dNcR2","type":"message","role":"assistant",
 "content":[{"type":"text","text":"Hello! 👋 How can I help you today?"}],
 "stop_reason":"end_turn","stop_sequence":null,"stop_details":null,
 "usage":{"input_tokens":8,"output_tokens":16,"service_tier":"standard","inference_geo":"not_available", …}}
```

### Full sweep — `temperature: 0.7`

| Model | Status |
|---|---|
| claude-fable-5 | **400** `` `temperature` is deprecated for this model. `` |
| claude-opus-5 | **400** (same message) |
| claude-opus-4-8 | **400** (same message) |
| claude-opus-4-7 | **400** (same message) |
| claude-sonnet-5 | **400** (same message) |
| claude-opus-4-6 | **200** |
| claude-sonnet-4-6 | **200** |
| claude-haiku-4-5 | **200** |

### `top_p` / `top_k` on claude-sonnet-5 — same treatment, param name interpolated

```json
{"type":"error","error":{"type":"invalid_request_error","message":"`top_p` is deprecated for this model."},"request_id":"req_011Ce9LTti8KXAoFmn7SW8xU"}
```

```json
{"type":"error","error":{"type":"invalid_request_error","message":"`top_k` is deprecated for this model."},"request_id":"req_011Ce9LTvBRxmGvwNhJ8xESc"}
```

Note the message says **"deprecated"**, not "unsupported" — but it is a hard `400`, not a
warning. Don't let the wording mislead the UI copy; the request genuinely fails.

Only the **first** offending parameter is reported — verified by sending `temperature` +
`top_p` + `top_k` together on `claude-sonnet-5` (`req_011Ce9LctDrZTCLSB3FApPFX`), which
returned `400` naming only `` `temperature` ``. The app should therefore gray out all three
controls together rather than letting the user fix them one round-trip at a time.

---

## 6. Two consecutive same-role user messages — ACCEPTED

**Request:** `{"model":"claude-haiku-4-5","max_tokens":40,"messages":[{"role":"user","content":"What is 2+2?"},{"role":"user","content":"Answer in one word."}]}`

**Status:** `200`

```json
{"model":"claude-haiku-4-5-20251001","id":"msg_011Ce9LTwx63YNphVRJacEPK","type":"message","role":"assistant",
 "content":[{"type":"text","text":"Four."}],"stop_reason":"end_turn","stop_sequence":null,"stop_details":null,
 "usage":{"input_tokens":20,"output_tokens":5,"service_tier":"standard","inference_geo":"not_available", …}}
```

Both messages were clearly honored (the answer respects the second message's format
instruction). **The app does not need to coalesce consecutive same-role messages** — this is a
behavior change from the older API, which used to 400 on role alternation violations. Only
tested on haiku-4-5 and only for `user`/`user`; if the app wants to rely on this for
assistant/assistant or on other models, re-verify.

---

## 7. `output_config: {effort: "low"}` on claude-haiku-4-5 → `400`

**Request:** `{"model":"claude-haiku-4-5","max_tokens":40,"output_config":{"effort":"low"},"messages":[…]}`

**Status:** `400`

```json
{"type":"error",
 "error":{"type":"invalid_request_error","message":"This model does not support the effort parameter."},
 "request_id":"req_011Ce9LTzDGewwdWxBfkVa6G"}
```

This is consistent with the Models API: `claude-haiku-4-5` reports
`capabilities.effort.supported: false`. **The app should gate the effort control from
`capabilities.effort`** — including per-level gating, since `xhigh` is `supported: false` on
Opus 4.6 / Sonnet 4.6 while `low`/`medium`/`high`/`max` are `true`, and Opus 4.5 supports only
`low`/`medium`/`high`.

---

## 8. Bad model id → `404` (not 400)

### 8a. `POST /v1/messages` with `"model": "claude-not-a-real-model"`

**Status:** `404`

```json
{"type":"error",
 "error":{"type":"not_found_error","message":"model: claude-not-a-real-model"},
 "request_id":"req_011Ce9LU1GmaAzT6EuvGKnKW"}
```

### 8b. `GET /v1/models/claude-not-a-real-model`

**Status:** `404` — identical body shape:

```json
{"type":"error","error":{"type":"not_found_error","message":"model: claude-not-a-real-model"},"request_id":"req_011Ce9LU2H3JiNf1AcyTk2QA"}
```

The message is terse (`"model: <id>"`) and **not** user-grade prose — this is the one case
where the app should substitute its own copy, e.g. "Unknown model `claude-not-a-real-model`",
rather than surfacing `error.message` raw.

---

## Consolidated notes for the app

**Error envelope is uniform** across every failure observed:

```json
{"type": "error", "error": {"type": <string>, "message": <string>}, "request_id": <string>}
```

`error.type` seen: `invalid_request_error` (400), `not_found_error` (404). Branch on the HTTP
status for retry logic and on `error.type` for classification; render `error.message` for
everything except the 404 case.

**Gating strategy:**

- **From live `GET /v1/models` `capabilities`:** effort (and per-level), thinking types
  (`enabled` vs `adaptive`), structured outputs, image/PDF input, batch, code execution,
  context management / compaction.
- **From a hardcoded list (not exposed in `capabilities`):**
  - *Prefill denylist:* `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`,
    `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6`.
  - *Sampling (`temperature`/`top_p`/`top_k`) denylist:* `claude-fable-5`, `claude-opus-5`,
    `claude-sonnet-5`, `claude-opus-4-8`, `claude-opus-4-7`. (Equivalently:
    `capabilities.thinking.types.enabled.supported === false` matched this set exactly across
    all 11 models — usable as a live-data heuristic, but it is a correlation, not a
    documented contract.)

**Alias handling:** request `claude-haiku-4-5`, response `model` is
`claude-haiku-4-5-20251001`. Never compare request vs response model strings for equality.

**Cost of this run:** ~10 billable completions on `claude-haiku-4-5` / `claude-opus-4-6` /
`claude-sonnet-4-6` at `max_tokens: 40` (largest was 26 output tokens); every request to an
expensive model returned 400 and was not billed. Total well under one cent.
