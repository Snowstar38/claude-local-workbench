# claude-local-workbench

A local replacement for the retired Anthropic Workbench, with the one thing it
never had: **every Run is saved as a version you can go back to.**

Everything is one file — `workbench.html`. No install, no build step, no server,
no dependencies, no analytics. Your conversations live in your browser on your
machine and go nowhere else; the only thing the page ever contacts is
`api.anthropic.com`, with your own API key.

> **Not affiliated with Anthropic.** This is a community tool. It talks to the
> official Anthropic API using your own key, under Anthropic's documented
> [direct browser access](https://docs.anthropic.com/) header. "Workbench" here
> is used as a plain word for a place you work, nothing more.

## Security — read this first

- **Your API key is stored in the browser's `localStorage`** for whatever
  address you open the app on, and sent only to `api.anthropic.com`. Use the app
  only on devices you trust; anyone with access to the browser profile can read
  the key. Clearing site data clears it.
- Prefer not to store it at all? Tick **"This page only"** next to the key in
  Settings: the key then lives in memory, is written nowhere, and is forgotten
  the moment you refresh or close the page — you paste it again next visit.
- **Only run copies of `workbench.html` you got from this repository** (or built
  yourself from source you've read). It's a single HTML file — a modified copy
  from anywhere else could quietly send your key or your chats somewhere.
- Consider a **dedicated API key** for the app (created in the Anthropic
  Console), so you can revoke it independently and see its spend on its own line.
- **If you host your own copy on GitHub Pages**, note that all of your
  project Pages share one origin (`https://<you>.github.io`), so any script on
  any of your other Pages sites could read the key from `localStorage`. If you
  host other pages there — especially ones with third-party dependencies — run
  the app from a local file or a dedicated origin instead.
- The page ships a strict Content-Security-Policy: it loads no external
  resources and can only ever connect to `api.anthropic.com`.
- Your chats stay in the browser's IndexedDB and in any backup files you create.
  Nothing is uploaded anywhere.

## First run

Two equally good ways in:

- **Hosted**: open the GitHub Pages copy of this repo. Nothing is shared between
  devices or with anyone — the page is static and all data stays in your browser.
- **Local**: download `workbench.html` and double-click it.

Then:

1. Click **Settings** (bottom-left) and paste your Anthropic API key.
   **Test key** checks it works before you save.
2. Click **Save**. The model list loads from the API, and you're ready.

**If Run fails immediately with a network or CORS error** on a local copy, your
browser is refusing the direct call from a `file://` page. Serve the folder
instead — open a terminal in the folder containing `workbench.html` and run:

```
python -m http.server 8000
```

then open <http://localhost:8000/workbench.html>. Everything works the same.

> One gotcha: browsers keep storage separate per address, so chats saved under
> `file://` won't show up under `localhost` or the hosted page (and vice versa).
> If you've already got work saved, use **Back up all** on the old address and
> **Restore** on the new one.

## Importing your old Workbench export

If you exported your data before the official Workbench shut down, you have a
zip file — and this app opens it.

Click **Import export**, or drag the file anywhere onto the window. It accepts
either:

- `prompts.json` on its own, or
- the whole export **`.zip`** — it finds `workbench/prompts.json` inside and
  unpacks it itself (no unzipping needed).

Each prompt becomes one chat, named from the prompt's name, with its system
prompt, model, temperature, max tokens, and full message history. Old `human`
roles become `user`. Thinking blocks from old conversations are kept and shown
collapsed under the message, marked *"not sent"* — they're part of your record,
but old signatures don't replay across models, so they're stripped from anything
sent to the API.

Importing the same file twice is safe: chats already imported are skipped and
the banner tells you how many.

## How versioning works

This is the heart of it.

- **Run** takes a snapshot first — system prompt, settings, every message,
  exactly as they are — and *then* sends the request. When the response finishes
  it's attached to that same snapshot. If the API rejects the request, the
  snapshot still exists.
- Snapshots appear in the **Versions** rail on the right, newest first, with the
  time, model, message count, and a preview.
- **Click a version to restore it.** The draft becomes that snapshot again, and
  its saved response comes back with it.
- Restoring never costs you anything: if your current draft has unsaved changes,
  it's snapshotted first as *"(auto-saved before restore)"* before the restore
  happens.
- **Save version** snapshots without running — handy before a big rewrite.
- The pencil icon labels a version ("the good one", "before I broke it").
  Labels are editable any time.

Nothing is ever overwritten and nothing expires. History grows without limit,
which is the point — but see **Backups** below, because it lives in one browser.

**Add to conversation** appends the response to the conversation as an assistant
message and leaves a fresh user turn ready. That doesn't make a version by
itself; the next Run captures it.

## Two layouts

The **▥ / ▤** button in the top bar switches between them, and your choice is
remembered:

- **Split** — the conversation on the left and **Response** on the right, each
  with its own scrollbar, like the old Workbench. The top bar stays put, with
  **Run** in it, so you can start a run from anywhere in a long conversation.
  The response streams into the right-hand pane and follows along as it
  arrives — unless you've scrolled up to re-read something, in which case it
  leaves you where you are.
- **Stacked** — one column, response underneath. Better for narrow windows and
  phones.

Until you press the button, the layout follows the room the editor actually
has — the window minus whichever side panels are open. After you've chosen, your
choice sticks. (A too-narrow editor always uses stacked, since there isn't room
for two readable columns, and returns to your choice as soon as there is.)

**☰** and **⧉** hide the chat list and the versions rail, which gives the editor
back 264px and 312px respectively — on a 1000px-wide window, hiding both is the
difference between a cramped stacked column and a comfortable split view.
Hiding a panel re-evaluates the layout for you.

## Backups (please do this)

Everything is stored in this browser's IndexedDB. That's fast and private, but
it is also *one basket*: clearing site data, resetting the browser, or moving to
a new machine loses it.

- **Back up all** downloads a single JSON file with every chat and every
  version.
- **Restore** merges a backup back in — chats are matched by id, the newer copy
  wins, and versions are added without duplicating. Restoring an old backup on
  top of newer work is safe; it adds, it doesn't replace.

To read your chats **on your phone**: open the hosted page (or drop
`workbench.html` on any static host), paste your key, and **Restore** your
backup file. Same app, same data.

### Auto-saving to a real file

Rather than remembering to press **Back up all**, you can link one file and let
the app keep it up to date by itself.

**Settings → Create or pick a save file…** opens a normal save dialog. You
don't need an existing file — saving under the suggested name
(`workbench-data.json`) creates one; put it in a synced folder if you want it
backed up off the machine. From then on, roughly two seconds after any change — an edit, a
run, an import, a deletion — the same complete backup document is written to
that file. The sidebar shows a small **file: saved ✓** while it's working.

Things worth knowing:

- **Chrome and Edge on desktop only.** This uses the File System Access API,
  which Firefox and Safari don't have, and phones don't either. If your browser
  lacks it, the Settings panel says so and **Back up all** / **Restore** remain
  the way to do it.
- **After a browser restart, Chrome needs one click** to hand file access back.
  You'll see a *"Reconnect your save file"* banner with a button. Until you
  click it, your work still saves normally inside the browser — just not into
  the file.
- **Nothing is ever overwritten silently, in either direction.** Link a file
  that already contains chats and it offers to merge them in *before* the first
  write. And if the linked file looks newer than this browser — you worked on
  another machine — you get a banner offering to merge it in. Merging uses the
  same rules as **Restore**: it adds what's missing and keeps the newer copy of
  anything in both. It never deletes.
- The file is an ordinary backup JSON, identical to what **Back up all**
  produces, so **Restore** reads it anywhere — including on your phone.
- **Unlink** stops the auto-saving and leaves the file exactly as it is.

The app also asks the browser to mark this data as persistent, so it isn't
evicted when storage runs low. Settings tells you whether the browser agreed.

## Browser support

| | Chrome / Edge (desktop) | Firefox / Safari | Phones |
|---|---|---|---|
| Everything else | ✓ | ✓ | ✓ (stacked layout) |
| Linked auto-save file | ✓ | manual **Back up all** / **Restore** | manual |

## Model quirks worth knowing

These were verified against the live API on **2026-08-17**, and the app already
gates them for you — this is just so nothing surprises you.

**Prefill** (putting text in a trailing *assistant* message so the model
continues it) still works on Claude 3-era, 4.5-era, and Haiku 4.5 models. It
returns an error on Opus/Sonnet 4.6, 4.7, 4.8, Sonnet 5, Opus 5, and Fable 5 —
those need the conversation to end with a user turn. When your last message is
an assistant turn, the message shows a `prefill` tag, and the run bar warns you
in advance if the current model will reject it. You can still press Run; the
error comes back verbatim.

The response to a prefill contains only the *continuation*. The completion pane
shows your prefill in grey followed by what the model added, and **Add to
conversation** joins them into the one assistant message — same as the old
Workbench.

**Temperature** is gone on Fable 5, Opus 5, Sonnet 5, Opus 4.7 and 4.8 (the
slider greys out and the parameter isn't sent). It still works on Opus/Sonnet
4.6 and older. Note these are two *different* lists: the 4.6 models refuse
prefill but are perfectly happy with temperature. On a model that supports it
the box starts **ticked at 1.0** — the API's own default — so the slider is
ready to use. Untick it and temperature stops being sent for that chat, and
stays unticked next time you open it.

**Effort** (low → max) is read live from the API's own model data, so each model
offers exactly the levels it supports — `xhigh` doesn't appear on 4.6, and
Haiku 4.5 has no effort control at all. Left on "default", nothing is sent.

**Thinking** is left alone deliberately — no thinking parameter is sent, so
every model uses its normal default. If a model does return reasoning, it
appears above the answer in a collapsible grey block.

**Refusals** on Fable 5 arrive as a normal successful response with
`stop: refusal`. You'll see a red note with the model's explanation rather than
a silent empty answer.

**The model list** merges what the API returns with a built-in list, so models
that have been deprecated but still work for your account never disappear from
the picker. If you need something not listed at all, choose **Custom model
id…** at the bottom and type it; it's remembered for next time. A chat that's
set to an unusual model keeps that model, always — the app will never quietly
switch it on you.

## Small things

- **Ctrl+Enter** runs (and stops a run). **Ctrl+Shift+N** starts a new chat.
  **Esc** stops a run.
- The **⚙** button (top bar or sidebar) opens Settings: API key, theme
  (light / dark / follow-system), and the linked auto-save file, all in one
  place. **▥/▤** switches layout, and **☰** / **⧉** hide the chat list and
  the versions rail.
- Message boxes grow as you type and never scroll internally.
- Max tokens is a log-scale slider (256 → 128,000) with an exact number beside
  it. The hint shows the selected model's own ceiling when the API reports one.
- Token usage and stop reason are shown under every completion, along with what
  the run actually cost.
- Before you Run, the bar shows the **input** cost: *"12,400 input tokens ≈
  $0.062"*, counted exactly by the API a second or so after you stop typing. A
  leading `~` means it's a local approximation instead (no key yet, or the
  counter was unreachable) — hover for the reason. Output isn't estimated,
  because its length can't be known in advance. Prices come from a table inside
  the file (last verified **2026-06-24**) and can go stale; an unfamiliar model
  shows a token count and no dollar figure rather than a wrong one.
- Consecutive messages with the same role are sent exactly as you arranged
  them — the API accepts them now, so the app doesn't merge anything behind
  your back.
- Errors from the API are shown in full, in their own words, in a dismissible
  banner.

## Files

| File | What it is |
|---|---|
| `workbench.html` | The whole app. This is the only file you need. |
| `README.md` | This guide. |
| `AGENTS.md` | Orientation for AI agents (and humans) working on the code. |
| `LICENSE` | MIT. |
| `CHANGELOG.md` | What changed, by version. |
| `fixtures/synthetic-prompts.json` | A fake export, for testing the importer without touching real data. |
| `tools/verify.py` | Offline test harness — run after any edit to `workbench.html`. |
| `tools/api-probe.py` | Live API smoke test (needs a key; costs a few cents). |
| `docs/SPEC.md` | The build spec. |
| `docs/smoke-results.md` | Evidence for the model-quirk claims above. |

## Contributing, maintaining — and forking!

Start with `AGENTS.md` — it's the orientation document for anyone (human or AI
agent) touching the code, and it points into `docs/`. The short version: the
app is one file organised in commented sections, model gating lives in one
function (`modelCaps()`), prices in one table (`PRICES`), and
`python tools/verify.py` must pass after every change.

**Please fork this.** It's MIT-licensed on purpose: if you want different
layouts, another storage scheme, support for other APIs, or something we'd
never think of — take the file and make it yours. It's one HTML file with no
build step, which makes it about the easiest thing in the world to fork, and
`AGENTS.md` was written so an AI assistant can get productive in it in one
sitting. You don't need permission, and you don't need to upstream anything
(though PRs are welcome too). The whole point of this project is that your
conversations and your tools belong to you.
