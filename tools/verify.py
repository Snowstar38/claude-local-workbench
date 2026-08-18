"""
Verification harness for workbench.html.

Ports the three fiddly algorithms from the app's JS to Python line-for-line and
runs them against real inputs, so offset/logic mistakes surface without a browser:

  A. readZip()          — EOCD -> central directory -> local header -> inflate
  B. SSE frame parsing  — against the exact capture in smoke-results.md
  C. promptToChat()     — against fixtures/synthetic-prompts.json
  D. structural scan of the <script> block (bracket balance, string/regex aware)
"""
import io, json, re, struct, sys, zipfile, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILS = []

def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -- " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

# ─── A. zip reader ────────────────────────────────────────────────────────────

def read_zip(buf: bytes):
    """Port of readZip() in workbench.html."""
    SIG_EOCD, SIG_EOCD64, SIG_LOC64 = 0x06054b50, 0x06064b50, 0x07064b50
    SIG_CD, SIG_LFH = 0x02014b50, 0x04034b50
    u32 = lambda off: struct.unpack_from("<I", buf, off)[0]
    u16 = lambda off: struct.unpack_from("<H", buf, off)[0]
    u64 = lambda off: struct.unpack_from("<Q", buf, off)[0]

    eocd = -1
    floor = max(0, len(buf) - 66 * 1024)
    for i in range(len(buf) - 22, floor - 1, -1):
        if u32(i) == SIG_EOCD:
            eocd = i
            break
    if eocd < 0:
        raise ValueError("no EOCD")

    count = u16(eocd + 10)
    cd_offset = u32(eocd + 16)
    if count == 0xFFFF or cd_offset == 0xFFFFFFFF:
        loc = eocd - 20
        if loc >= 0 and u32(loc) == SIG_LOC64:
            rec = u64(loc + 8)
            if u32(rec) == SIG_EOCD64:
                count = u64(rec + 32)
                cd_offset = u64(rec + 48)

    entries, p = [], cd_offset
    for _ in range(count):
        if p + 46 > len(buf) or u32(p) != SIG_CD:
            break
        method = u16(p + 10)
        csize, usize = u32(p + 20), u32(p + 24)
        nlen, elen, clen = u16(p + 28), u16(p + 30), u16(p + 32)
        lho = u32(p + 42)
        name = buf[p + 46:p + 46 + nlen].decode("utf-8")
        if 0xFFFFFFFF in (csize, usize, lho):
            q, end = p + 46 + nlen, p + 46 + nlen + elen
            while q + 4 <= end:
                tag, size = u16(q), u16(q + 2)
                if tag == 0x0001:
                    r = q + 4
                    if usize == 0xFFFFFFFF: usize = u64(r); r += 8
                    if csize == 0xFFFFFFFF: csize = u64(r); r += 8
                    if lho == 0xFFFFFFFF:   lho = u64(r); r += 8
                    break
                q += 4 + size
        entries.append(dict(name=name, method=method, csize=csize, usize=usize, lho=lho))
        p += 46 + nlen + elen + clen

    def extract(e):
        if u32(e["lho"]) != SIG_LFH:
            raise ValueError("broken local header for " + e["name"])
        nlen, elen = u16(e["lho"] + 26), u16(e["lho"] + 28)
        start = e["lho"] + 30 + nlen + elen
        raw = buf[start:start + e["csize"]]
        if e["method"] == 0:
            return raw
        if e["method"] == 8:
            return zlib.decompress(raw, -15)   # == DecompressionStream("deflate-raw")
        raise ValueError("unsupported method %d" % e["method"])

    return entries, extract


print("A. zip reader")
prompts_text = (ROOT / "fixtures" / "synthetic-prompts.json").read_text(encoding="utf-8")

for label, mode, comment, extra_files in [
    ("deflated, nested path", zipfile.ZIP_DEFLATED, b"", True),
    ("stored (method 0)",     zipfile.ZIP_STORED,   b"", False),
    ("with archive comment",  zipfile.ZIP_DEFLATED, b"x" * 300, True),
]:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", mode) as z:
        if extra_files:
            z.writestr("workbench/README.txt", "unrelated file, should be skipped\n")
            z.writestr("workbench/settings.json", '{"unrelated": true}')
        z.writestr("workbench/prompts.json", prompts_text)
        if extra_files:
            z.writestr("other/prompts.json", "[]")   # decoy after the real one
        z.comment = comment
    data = bio.getvalue()

    entries, extract = read_zip(data)
    names = [e["name"] for e in entries]
    check(f"[{label}] entry names read", "workbench/prompts.json" in names, names)

    # Same selection order as importZip()
    target = (next((e for e in entries if e["name"] == "workbench/prompts.json"), None)
              or next((e for e in entries if e["name"].replace("\\", "/").endswith("/prompts.json")), None)
              or next((e for e in entries if e["name"] == "prompts.json"), None))
    check(f"[{label}] picked workbench/prompts.json", target and target["name"] == "workbench/prompts.json")
    out = extract(target).decode("utf-8")
    check(f"[{label}] inflated bytes match source", out == prompts_text,
          f"{len(out)} vs {len(prompts_text)} bytes")
    check(f"[{label}] inflated text parses as JSON", json.loads(out) == json.loads(prompts_text))

# Non-zip input must be rejected, not misparsed.
try:
    read_zip(b"this is not a zip file at all" * 10)
    check("non-zip input rejected", False, "no error raised")
except ValueError:
    check("non-zip input rejected", True)

# ─── B. SSE parsing ───────────────────────────────────────────────────────────

def parse_sse(chunks):
    """Port of the buffer/frame loop + handle() in streamMessage()."""
    out = {"content": {}, "stopReason": None, "stopDetails": None, "usage": {}, "model": None, "done": False}
    buf = ""
    seen_types = []

    def handle(evt):
        t = evt.get("type")
        seen_types.append(t)
        if t == "message_start":
            out["model"] = (evt.get("message") or {}).get("model") or out["model"]
            out["usage"].update((evt.get("message") or {}).get("usage") or {})
        elif t == "content_block_start":
            b = dict(evt.get("content_block") or {"type": "text"})
            if b.get("type") == "text" and b.get("text") is None: b["text"] = ""
            if b.get("type") == "thinking" and b.get("thinking") is None: b["thinking"] = ""
            out["content"][evt["index"]] = b
        elif t == "content_block_delta":
            b = out["content"].setdefault(evt["index"], {"type": "text", "text": ""})
            d = evt.get("delta") or {}
            if d.get("type") == "text_delta":       b["text"] = b.get("text", "") + d["text"]
            elif d.get("type") == "thinking_delta": b["thinking"] = b.get("thinking", "") + d["thinking"]
            elif d.get("type") == "signature_delta": b["signature"] = d["signature"]
        elif t == "message_delta":
            d = evt.get("delta") or {}
            if d.get("stop_reason"):  out["stopReason"] = d["stop_reason"]
            if d.get("stop_details"): out["stopDetails"] = d["stop_details"]
            if evt.get("stop_details"): out["stopDetails"] = evt["stop_details"]
            out["usage"].update(evt.get("usage") or {})
        elif t == "message_stop":
            out["done"] = True
        elif t == "error":
            raise RuntimeError(evt["error"]["message"])
        # ping and anything unknown: ignored

    for chunk in chunks:
        buf += chunk
        while True:
            m = re.search(r"\r?\n\r?\n", buf)
            if not m:
                break
            frame, buf = buf[:m.start()], buf[m.start() + (4 if buf[m.start()] == "\r" else 2):]
            data = "\n".join(l[5:].strip() for l in re.split(r"\r?\n", frame) if l.startswith("data:"))
            if not data or data == "[DONE]":
                continue
            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                continue
            handle(evt)

    out["content"] = [out["content"][k] for k in sorted(out["content"])]
    out["seen"] = seen_types
    return out


print("\nB. SSE parsing (exact capture from smoke-results.md, padded + ping)")
STREAM = (
 'event: message_start\n'
 'data: {"type":"message_start","message":{"model":"claude-haiku-4-5-20251001","id":"msg_01","type":"message",'
 '"role":"assistant","content":[],"stop_reason":null,"stop_sequence":null,"stop_details":null,'
 '"usage":{"input_tokens":15,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":1}}}\n'
 '\n'
 'event: content_block_start\n'
 'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}     }\n'
 '\n'
 'event: ping\n'
 'data: {"type": "ping"}\n'
 '\n'
 'event: content_block_delta\n'
 'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hey"} }\n'
 '\n'
 'event: content_block_delta\n'
 'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":", how\'s it?"}   }\n'
 '\n'
 'event: content_block_stop\n'
 'data: {"type":"content_block_stop","index":0             }\n'
 '\n'
 'event: message_delta\n'
 'data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null,"stop_details":null},'
 '"usage":{"input_tokens":15,"output_tokens":9}     }\n'
 '\n'
 'event: message_stop\n'
 'data: {"type":"message_stop"       }\n'
 '\n')

# Whole thing at once
r = parse_sse([STREAM])
check("text assembled", r["content"][0]["text"] == "Hey, how's it?", r["content"])
check("stop_reason read", r["stopReason"] == "end_turn")
check("null stop_details stays None", r["stopDetails"] is None)
check("usage merged (in 15 / out 9)", r["usage"]["input_tokens"] == 15 and r["usage"]["output_tokens"] == 9)
check("response model captured verbatim", r["model"] == "claude-haiku-4-5-20251001")
check("ping seen and ignored", "ping" in r["seen"] and r["done"])

# Split at every single byte boundary: frames must survive arbitrary chunking.
ok_all = True
for i in range(1, len(STREAM)):
    rr = parse_sse([STREAM[:i], STREAM[i:]])
    if not (rr["content"] and rr["content"][0]["text"] == "Hey, how's it?" and rr["stopReason"] == "end_turn"):
        ok_all = False
        check("chunk split at byte %d" % i, False, rr)
        break
check("survives every possible 2-way chunk split (%d boundaries)" % (len(STREAM) - 1), ok_all)

# CRLF variant
r_crlf = parse_sse([STREAM.replace("\n", "\r\n")])
check("CRLF line endings", r_crlf["content"] and r_crlf["content"][0]["text"] == "Hey, how's it?"
      and r_crlf["stopReason"] == "end_turn", r_crlf["content"])

# Thinking deltas + refusal stop_details
THINK = (
 'event: content_block_start\n'
 'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}\n'
 '\n'
 'event: content_block_delta\n'
 'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"weighing it"}}\n'
 '\n'
 'event: content_block_delta\n'
 'data: {"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"sig123"}}\n'
 '\n'
 'event: message_delta\n'
 'data: {"type":"message_delta","delta":{"stop_reason":"refusal","stop_details":{"type":"refusal","category":"cyber","explanation":"declined"}},"usage":{"output_tokens":3}}\n'
 '\n')
rt = parse_sse([THINK])
check("thinking_delta accumulates", rt["content"][0]["thinking"] == "weighing it")
check("signature_delta captured", rt["content"][0]["signature"] == "sig123")
check("refusal stop_details captured", rt["stopReason"] == "refusal"
      and rt["stopDetails"]["explanation"] == "declined")

# ─── C. import mapping ────────────────────────────────────────────────────────

def prompt_to_chat(p):
    """Port of promptToChat()."""
    rev = p.get("latest_revision") or {}
    messages = []
    for m in sorted(rev.get("messages") or [], key=lambda x: x.get("index") or 0):
        blocks = []
        for b in (m.get("content") or []):
            if b.get("type") == "thinking":
                blocks.append({"type": "thinking", "thinking": b.get("thinking") or "",
                               "signature": b.get("signature") or ""})
            else:
                blocks.append({"type": "text", "text": b.get("text") if b.get("text") is not None else ""})
        role = "user" if m.get("role") == "human" else ("assistant" if m.get("role") == "assistant" else "user")
        messages.append({"role": role, "content": blocks})
    settings = {
        "model": rev.get("model") or "claude-opus-5",
        "maxTokens": min(128000, max(256, rev.get("max_tokens") or 4096)),
        "temperature": rev["temperature"] if isinstance(rev.get("temperature"), (int, float)) else None,
        "effort": (rev.get("output_config") or {}).get("effort") or "",
        "system": rev.get("system_prompt") or "",
    }
    name = (p.get("name") or rev.get("name") or "").strip() or "Imported <date>"
    return {"name": name, "sourceUuid": p.get("uuid"), "settings": settings, "messages": messages}


print("\nC. import mapping (synthetic fixture)")
prompts = json.loads(prompts_text)
chats = [prompt_to_chat(p) for p in prompts]

c0, c1, c2 = chats
check("3 prompts -> 3 chats", len(chats) == 3)
check("human role converted to user", all(m["role"] in ("user", "assistant") for c in chats for m in c["messages"]))
check("no 'human' role survives", not any(m["role"] == "human" for c in chats for m in c["messages"]))
check("old model id preserved", c0["settings"]["model"] == "claude-3-opus-20240229")
check("system prompt carried", c0["settings"]["system"].startswith("You are a patient co-writer"))
check("temperature carried as number", c0["settings"]["temperature"] == 1.0)
check("effort carried from output_config", c1["settings"]["effort"] == "high")
check("max_tokens clamped into slider range", all(256 <= c["settings"]["maxTokens"] <= 128000 for c in chats))
check("thinking block preserved with signature",
      c1["messages"][1]["content"][0]["type"] == "thinking"
      and c1["messages"][1]["content"][0]["signature"].startswith("FAKE_SIGNATURE"))
check("thinking + text kept in order",
      [b["type"] for b in c1["messages"][1]["content"]] == ["thinking", "text"])
check("empty name falls back", c2["name"] == "Imported <date>")
check("messages sorted by index, not file order",
      [m["role"] for m in c2["messages"]] == ["user", "assistant"]
      and c2["messages"][0]["content"][0]["text"].startswith("Describe the contents"))
check("source uuid recorded for idempotent re-import", all(c["sourceUuid"] for c in chats))

# What buildRequest() will send: thinking stripped, empties dropped, order kept.
def build_messages(msgs):
    out = []
    for m in msgs:
        text = "\n\n".join(b["text"] for b in m["content"] if b["type"] == "text").strip()
        if not text:
            continue
        out.append({"role": m["role"], "content": text})
    return out

built = build_messages(c1["messages"])
check("thinking stripped from outgoing request",
      "weighing" not in json.dumps(built) and "FAKE_SIGNATURE" not in json.dumps(built))
check("outgoing messages keep their arrangement",
      [m["role"] for m in built] == ["user", "assistant"])

# ─── D. structural scan of the script block ───────────────────────────────────

print("\nD. structural scan of workbench.html")
html = (ROOT / "workbench.html").read_text(encoding="utf-8")
m = re.search(r"<script>\n(.*)\n</script>", html, re.S)
check("script block found", bool(m))
js = m.group(1)

def scan(js):
    """Bracket balance, aware of strings, template literals, comments, regex."""
    stack, i, n = [], 0, len(js)
    prev = ""           # last significant char, to tell regex from division
    line = 1
    while i < n:
        ch = js[i]
        if ch == "\n":
            line += 1; i += 1; continue
        if ch in " \t":
            i += 1; continue
        two = js[i:i + 2]
        if two == "//":
            i = js.find("\n", i);  i = n if i < 0 else i;  continue
        if two == "/*":
            j = js.find("*/", i + 2)
            if j < 0: return "unterminated block comment at line %d" % line
            line += js.count("\n", i, j); i = j + 2; continue
        if ch in "\"'`":
            quote, j = ch, i + 1
            while j < n:
                if js[j] == "\\": j += 2; continue
                if js[j] == "\n":
                    line += 1
                    if quote != "`": return "unterminated string at line %d" % line
                if js[j] == quote: break
                if quote == "`" and js[j:j + 2] == "${":
                    depth, j = 1, j + 2      # skip the interpolation
                    while j < n and depth:
                        if js[j] == "{": depth += 1
                        elif js[j] == "}": depth -= 1
                        elif js[j] == "\n": line += 1
                        j += 1
                    continue
                j += 1
            if j >= n: return "unterminated string at line %d" % line
            prev = "x"; i = j + 1; continue
        if ch == "/" and prev in "" or (ch == "/" and prev in "(,=:[!&|?{};+-*%<>~^"):
            j = i + 1                        # regex literal
            in_class = False
            while j < n:
                if js[j] == "\\": j += 2; continue
                if js[j] == "[": in_class = True
                elif js[j] == "]": in_class = False
                elif js[j] == "/" and not in_class: break
                elif js[j] == "\n": return "unterminated regex at line %d" % line
                j += 1
            prev = "x"; i = j + 1; continue
        if ch in "([{":
            stack.append((ch, line))
        elif ch in ")]}":
            if not stack:
                return "unmatched closing %r at line %d" % (ch, line)
            open_ch, open_line = stack.pop()
            if "([{".index(open_ch) != ")]}".index(ch):
                return "mismatched %r (line %d) closed by %r (line %d)" % (open_ch, open_line, ch, line)
        prev = ch
        i += 1
    if stack:
        return "unclosed %r opened at line %d" % (stack[-1][0], stack[-1][1])
    return None

err = scan(js)
check("brackets balanced in script block", err is None, err)
check("no stray </" + "script> inside the JS", "</scr" + "ipt>" not in js)
check("no CDN / external asset references",
      not re.search(r"(src|href)\s*=\s*[\"']https?://", html))
check("only api.anthropic.com is contacted",
      set(re.findall(r"https?://[a-zA-Z0-9.\-]+", html)) <= {"https://api.anthropic.com"},
      set(re.findall(r"https?://[a-zA-Z0-9.\-]+", html)))

for fn in ["readZip", "streamMessage", "promptToChat", "importBackup", "exportAll",
           "modelCaps", "snapshot", "restoreVersion", "addToConversation", "modelOptions"]:
    check("defines " + fn + "()", re.search(r"function %s\b" % fn, js) is not None)

for ref in ["anthropic-dangerous-direct-browser-access", "anthropic-version",
            'DecompressionStream("deflate-raw")', "after_id", "output_config"]:
    check("mentions " + ref, ref in js)

# ─── E. model capability gating ───────────────────────────────────────────────

EFFORT_5 = ["low", "medium", "high", "xhigh", "max"]
EFFORT_4 = ["low", "medium", "high", "max"]
EFFORT_3 = ["low", "medium", "high"]
PREFILL_DENY = ["claude-fable-5", "claude-mythos-5", "claude-mythos-preview",
                "claude-opus-5", "claude-sonnet-5",
                "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6"]
SAMPLING_DENY = ["claude-fable-5", "claude-mythos-5", "claude-mythos-preview",
                 "claude-opus-5", "claude-sonnet-5",
                 "claude-opus-4-8", "claude-opus-4-7"]

def starts_with_any(i, lst):
    return any(i == p or i.startswith(p + "-") for p in lst)

def model_caps(mid, info=None):
    """Port of modelCaps()."""
    m = (mid or "").lower()
    prefill = False if starts_with_any(m, PREFILL_DENY) else None
    temperature = False if starts_with_any(m, SAMPLING_DENY) else None
    known = True

    if prefill is None or temperature is None:
        if re.match(r"^claude-3(-|$)", m):
            prefill = True if prefill is None else prefill
            temperature = True if temperature is None else temperature
        else:
            mm = re.match(r"^claude-(opus|sonnet|haiku)-(\d+)(?:-(\d+))?", m)
            if mm:
                minor = int(mm.group(3)) if mm.group(3) and len(mm.group(3)) <= 2 else 0
                v = int(mm.group(2)) + minor / 10
                if prefill is None: prefill = v <= 4.5
                if temperature is None: temperature = v <= 4.6
            else:
                prefill = True if prefill is None else prefill
                temperature = True if temperature is None else temperature
                known = False

    if info and info.get("capabilities"):
        e = info["capabilities"].get("effort")
        if not e or not e.get("supported"):
            effort = None
        else:
            lv = [l for l in EFFORT_5 if e.get(l, {}).get("supported")]
            effort = lv or EFFORT_5
    elif re.match(r"^claude-(fable|mythos)", m):
        effort = EFFORT_5
    elif re.match(r"^claude-3(-|$)", m):
        effort = None
    else:
        mm = re.match(r"^claude-(opus|sonnet|haiku)-(\d+)(?:-(\d+))?", m)
        if not mm:
            effort = EFFORT_5
        else:
            minor = int(mm.group(3)) if mm.group(3) and len(mm.group(3)) <= 2 else 0
            v = int(mm.group(2)) + minor / 10
            if v >= 4.7: effort = EFFORT_5
            elif v == 4.6: effort = EFFORT_4
            elif v == 4.5 and mm.group(1) == "opus": effort = EFFORT_3
            else: effort = None
    return dict(prefill=prefill, temperature=temperature, effort=effort, known=known)


print("\nE. capability gating (offline table vs. the smoke-tested matrix)")
# (model, prefill, temperature, effort) — exactly as measured on 2026-08-17.
MATRIX = [
    ("claude-fable-5",              False, False, EFFORT_5),
    ("claude-mythos-5",             False, False, EFFORT_5),
    ("claude-opus-5",               False, False, EFFORT_5),
    ("claude-sonnet-5",             False, False, EFFORT_5),
    ("claude-opus-4-8",             False, False, EFFORT_5),
    ("claude-opus-4-7",             False, False, EFFORT_5),
    ("claude-opus-4-6",             False, True,  EFFORT_4),
    ("claude-sonnet-4-6",           False, True,  EFFORT_4),
    ("claude-opus-4-5-20251101",    True,  True,  EFFORT_3),
    ("claude-haiku-4-5",            True,  True,  None),
    ("claude-haiku-4-5-20251001",   True,  True,  None),
    ("claude-sonnet-4-5-20250929",  True,  True,  None),
    ("claude-3-7-sonnet-20250219",  True,  True,  None),
    ("claude-3-opus-20240229",      True,  True,  None),
]
for mid, pf, tmp, eff in MATRIX:
    c = model_caps(mid)
    check(f"{mid}: prefill={pf}", c["prefill"] == pf, c)
    check(f"{mid}: temperature={tmp}", c["temperature"] == tmp, c)
    check(f"{mid}: effort={eff}", c["effort"] == eff, c)

check("prefill and sampling denylists are genuinely different sets",
      model_caps("claude-opus-4-6")["prefill"] is False
      and model_caps("claude-opus-4-6")["temperature"] is True)
check("unknown non-Claude id stays permissive",
      model_caps("some-other-model") == dict(prefill=True, temperature=True, effort=EFFORT_5, known=False))
check("dated snapshot of a denied model still denied",
      model_caps("claude-opus-4-6-20260101")["prefill"] is False)

# Live capabilities must override the offline table (per-level flags included).
CAP46 = {"capabilities": {"effort": {"supported": True, "low": {"supported": True},
         "medium": {"supported": True}, "high": {"supported": True},
         "xhigh": {"supported": False}, "max": {"supported": True}}}}
CAP_HAIKU = {"capabilities": {"effort": {"supported": False}}}
check("live capabilities drop xhigh on 4.6", model_caps("claude-opus-4-6", CAP46)["effort"] == EFFORT_4)
check("live capabilities disable effort on haiku", model_caps("claude-haiku-4-5", CAP_HAIKU)["effort"] is None)

# The denylists in the harness must match the ones in the app, character for character.
for name, lst in [("PREFILL_DENY", PREFILL_DENY), ("SAMPLING_DENY", SAMPLING_DENY)]:
    block = re.search(name + r"\s*=\s*\[(.*?)\]", js, re.S)
    ids = re.findall(r'"([^"]+)"', block.group(1)) if block else []
    check(f"app's {name} matches this harness", ids == lst, ids)

# ─── F. DOM wiring ────────────────────────────────────────────────────────────

print("\nF. DOM wiring")
markup = html[:html.index("<script>")]
declared = set(re.findall(r'\bid="([^"]+)"', markup))
used = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"', js))
missing = sorted(used - declared)
check("every id the script queries exists in the markup", not missing, missing)

unused = sorted(declared - used - {"app", "main"})
print("       (ids declared but never queried: %s)" % (", ".join(unused) or "none"))

# CSS selectors the JS toggles must exist in the stylesheet.
css = html[html.index("<style>"):html.index("</style>")]
for cls in ["disabled-field", "banner", "thinkblock", "blink", "no-sidebar", "no-rail",
            "ver", "chat-item", "msg", "pill", "empty-note", "roles"]:
    check("stylesheet defines ." + cls, ("." + cls) in css)

# Theme tokens must be defined on bare :root, not only inside a media query.
root_block = re.search(r":root\{(.*?)\}", css, re.S).group(1)
for tok in ["--bg", "--panel", "--border", "--text", "--muted", "--accent", "--danger"]:
    check("token %s defined on bare :root" % tok, tok + ":" in root_block)
check("dark theme via prefers-color-scheme", "prefers-color-scheme: dark" in css)
check('explicit dark override via [data-theme="dark"]', ':root[data-theme="dark"]' in css)

# ─── G. file auto-save: write serialization ───────────────────────────────────

print("\nG. file auto-save serialization (simulated)")
import asyncio, random

class SyncSim:
    """Port of scheduleFileSave() / flushFileSave() — the in-flight + trailing-rerun pair."""
    DELAY = 0.01
    def __init__(self):
        self.status = "ready"; self.in_flight = False; self.pending = False
        self.task = None
        self.data = 0           # newest mutation counter
        self.written = None     # last payload written to "disk"
        self.concurrent = 0; self.max_concurrent = 0; self.writes = 0

    def schedule(self):
        if self.status not in ("ready", "saving"):
            return
        if self.task and not self.task.done():
            self.task.cancel()                     # clearTimeout
        self.task = asyncio.ensure_future(self._later())

    async def _later(self):
        try:
            await asyncio.sleep(self.DELAY)
        except asyncio.CancelledError:
            return
        await self.flush()

    async def flush(self):
        if self.status not in ("ready", "saving"):
            return
        if self.in_flight:
            self.pending = True
            return
        self.in_flight = True; self.status = "saving"
        try:
            payload = self.data                    # buildBackupPayload()
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
            await asyncio.sleep(random.uniform(0.001, 0.02))   # the actual write
            self.concurrent -= 1
            self.written = payload; self.writes += 1
            self.status = "ready"
        finally:
            self.in_flight = False
            if self.pending:
                self.pending = False
                self.schedule()

async def burst(n=40):
    sim = SyncSim()
    for i in range(1, n + 1):
        sim.data = i                     # a mutation
        sim.schedule()                   # afterMutation()
        await asyncio.sleep(random.uniform(0, 0.008))
    # let everything settle
    for _ in range(60):
        await asyncio.sleep(0.01)
        if not sim.in_flight and not sim.pending and (sim.task is None or sim.task.done()):
            break
    return sim

random.seed(7)
for trial in range(6):
    s = asyncio.run(burst())
    check(f"trial {trial}: writes never overlap", s.max_concurrent <= 1, s.max_concurrent)
    check(f"trial {trial}: last change reached the file", s.written == s.data,
          f"wrote {s.written}, data was {s.data}")
    check(f"trial {trial}: writes coalesced (not one per change)", s.writes < 40, s.writes)

# A paused sync (permission lapsed) must not write, and must resume cleanly.
async def paused():
    sim = SyncSim(); sim.status = "needs-permission"
    sim.data = 5; sim.schedule()
    await asyncio.sleep(0.05)
    no_write = sim.written is None
    sim.status = "ready"; sim.data = 6; sim.schedule()
    await asyncio.sleep(0.08)
    return no_write, sim.written
nw, after = asyncio.run(paused())
check("no writes while permission is missing", nw)
check("resumes and writes the newest data afterwards", after == 6, after)

# Wiring: every mutating DB helper must funnel through afterMutation().
for helper in ["dbPutChat", "dbPutVersion", "dbDelVersion"]:
    pat = helper + r"\s*=\s*\([^)]*\)\s*=>\s*\n?\s*txn\([^;]*?\.then\(afterMutation\)"
    check(helper + " calls afterMutation", re.search(pat, js, re.S) is not None)
check("dbDeleteChat calls afterMutation",
      re.search(r"function dbDeleteChat[\s\S]*?\.then\(afterMutation\)", js) is not None)
check("bulk import queues a file save", js.count("afterMutation();") >= 2)
check("File System Access API is feature-detected",
      'typeof window.showSaveFilePicker === "function"' in js)
check("permission re-grant is gated behind a click",
      "requestPermission" in js and "reconnectSaveFile" in js)
check("navigator.storage.persist() requested", "navigator.storage.persist" in js)
check("save handle stored in IndexedDB meta store",
      'createObjectStore("meta"' in js and "SAVE_FILE_KEY" in js)
check("DB upgrade is additive (v1 data survives)",
      js.count('if (!d.objectStoreNames.contains(') == 3)

# ─── H. layout modes ──────────────────────────────────────────────────────────

print("\nH. layout modes")
check("split mode CSS present", "body.split #responsePane" in css)
check("both panes scroll independently",
      "#responseBody{" in css.replace(" ", "") or "#responseBody {" in css)
check("run controls restyled for the top bar", "body.split #runbar" in css)
check("layout choice persisted", 'localStorage.getItem("wb.layout")' in js)
check("stream-follow uses the per-mode scroller", "completionScroller()" in js)
check("a hard floor forces stacked when the editor is too narrow",
      "SPLIT_FLOOR_MAIN" in js and "if (avail < SPLIT_FLOOR_MAIN) return \"stacked\";" in js)
for i in ["responsePane", "responseBody", "stackedSlot", "topRunSlot", "toggleLayout", "respEmpty"]:
    check("markup has #" + i, ('id="%s"' % i) in markup)

# ─── I. pricing / input cost estimate ─────────────────────────────────────────

print("\nI. pricing and the input cost estimate")

# Parse the PRICES table straight out of the app so the two can't drift.
block = re.search(r"const PRICES = \[(.*?)\n\];", js, re.S).group(1)
APP_PRICES = [(m.group(1), float(m.group(2)), float(m.group(3)))
              for m in re.finditer(r'\["([^"]+)",\s*([\d.]+),\s*([\d.]+)\]', block)]
check("price table parsed from the app", len(APP_PRICES) == 19, len(APP_PRICES))

def price_for(mid):
    m = (mid or "").lower()
    for prefix, i, o in APP_PRICES:
        if m == prefix or m.startswith(prefix + "-"):
            return (i, o)
    return None

def fmt_usd(v):
    if v < 0.01: return "$%.4f" % v
    if v < 1:    return "$%.3f" % v
    return "$%.2f" % v

EXPECTED = [
    ("claude-fable-5",             10,   50),
    ("claude-mythos-5",            10,   50),
    ("claude-opus-5",               5,   25),
    ("claude-opus-4-8",             5,   25),
    ("claude-opus-4-7",             5,   25),
    ("claude-opus-4-6",             5,   25),
    ("claude-opus-4-5-20251101",    5,   25),
    ("claude-opus-4-1-20250805",   15,   75),
    ("claude-opus-4-20250514",     15,   75),
    ("claude-3-opus-20240229",     15,   75),
    ("claude-sonnet-5",             3,   15),
    ("claude-sonnet-4-6",           3,   15),
    ("claude-sonnet-4-5-20250929",  3,   15),
    ("claude-sonnet-4-20250514",    3,   15),
    ("claude-3-7-sonnet-20250219",  3,   15),
    ("claude-3-5-sonnet-20241022",  3,   15),
    ("claude-haiku-4-5-20251001",   1,    5),
    ("claude-3-5-haiku-20241022",   0.8,  4),
    ("claude-3-haiku-20240307",     0.25, 1.25),
]
for mid, pin, pout in EXPECTED:
    check(f"price {mid} = ${pin}/${pout}", price_for(mid) == (pin, pout), price_for(mid))

# The ordering trap: a short prefix must not shadow a longer, more specific one.
check("claude-opus-4 does not shadow claude-opus-4-8", price_for("claude-opus-4-8")[0] == 5)
check("claude-opus-4 does not shadow claude-opus-4-5", price_for("claude-opus-4-5")[0] == 5)
check("claude-3-haiku does not shadow claude-3-5-haiku", price_for("claude-3-5-haiku")[0] == 0.8)
check("unknown model has no price", price_for("claude-not-a-real-model") is None)
check("empty model id has no price", price_for("") is None)
check("a future model has no price rather than a wrong one",
      price_for("claude-opus-6") is None)

# Money formatting, and the coordinator's worked example.
check("sub-cent shows 4 decimals", fmt_usd(0.0062) == "$0.0062", fmt_usd(0.0062))
check("dollars show 2 decimals", fmt_usd(1.5) == "$1.50", fmt_usd(1.5))
check("12,400 tokens on opus-5 reads $0.062",
      fmt_usd(12400 / 1e6 * price_for("claude-opus-5")[0]) == "$0.062",
      fmt_usd(12400 / 1e6 * price_for("claude-opus-5")[0]))

# A realistic long-conversation figure, sanity-checked by hand.
cost = 250000 / 1e6 * price_for("claude-fable-5")[0]
check("250k input tokens on fable-5 = $2.50", fmt_usd(cost) == "$2.50", fmt_usd(cost))

# Heuristic fallback ratio.
check("fallback heuristic is chars/3.5", "CHARS_PER_TOKEN = 3.5" in js)
check("count_tokens endpoint used", "/v1/messages/count_tokens" in js)
check("count_tokens body omits generation-only params",
      re.search(r"const payload = \{ model: body\.model, messages: body\.messages \};", js) is not None)
check("estimate debounced ~1.5s", "ESTIMATE_DELAY = 1500" in js)
check("estimate skipped while streaming",
      re.search(r"function runEstimate\(\)[\s\S]{0,160}state\.running", js) is not None)
check("stale estimate responses are discarded", "estimateSeq" in js)
check("in-flight estimate is abortable", "estimateCtrl" in js)
check("estimate failures are silent (no showError in runEstimate)",
      "showError" not in re.search(r"async function runEstimate\(\)([\s\S]*?)\n\}", js).group(1))
check("approximate estimates marked with ~",
      re.search(r'const approx = e\.exact \? "" : "~"', js) is not None)
check("post-run actual cost uses the response model",
      re.search(r"const price = priceFor\(c\.model\)", js) is not None)
check("output price only used post-run, never in the estimate",
      "price.output" in js and "price.output" not in
      re.search(r"function renderEstimate\(\)([\s\S]*?)\n\}", js).group(1))

# ─── J. grid placement when panes are hidden (the ☰ bug) ─────────────────────

print("\nJ. pane layout with the sidebar / rail hidden")

# Explicit column assignments, read out of the stylesheet.
COLS = {}
for sel in ["#sidebar", "#main", "#rail"]:
    # Note the [^}]* — it can't cross a closing brace, so a grouped rule like
    # "#sidebar,#rail{...}" that carries no grid-column is skipped over.
    got = re.search(re.escape(sel) + r"\{[^}]*grid-column:\s*(\d+)", css)
    COLS[sel] = int(got.group(1)) if got else None
check("#sidebar pinned to column 1", COLS["#sidebar"] == 1, COLS)
check("#main pinned to column 2", COLS["#main"] == 2, COLS)
check("#rail pinned to column 3", COLS["#rail"] == 3, COLS)

SIDEBAR_W, RAIL_W = 264, 312

def grid_widths(viewport, no_sidebar, no_rail, explicit):
    """
    Model CSS grid placement of #app.
    template: [--sb, 1fr, --vr]; --sb/--vr collapse to 0 when hidden.
    With `explicit` False, hidden children are removed and the remaining ones
    AUTO-PLACE into the leftmost free columns — the actual bug.
    """
    track = [0 if no_sidebar else SIDEBAR_W, None, 0 if no_rail else RAIL_W]
    free = viewport - track[0] - track[2]
    track[1] = max(0, free)                       # the single 1fr column

    kids = ([] if no_sidebar else ["#sidebar"]) + ["#main"] + ([] if no_rail else ["#rail"])
    if explicit:
        placed = {k: COLS[k] - 1 for k in kids}
    else:
        placed = {k: i for i, k in enumerate(kids)}   # auto-placement
    return {k: track[i] for k, i in placed.items()}

# The bug, reproduced against the old (auto-placement) behaviour.
buggy = grid_widths(1440, no_sidebar=True, no_rail=False, explicit=False)
check("REGRESSION GUARD: auto-placement really did squeeze #main to 0px",
      buggy["#main"] == 0, buggy)

# The fix: #main is sane in all four show/hide combinations, at several widths.
for viewport in (1000, 1280, 1440, 1920):
    for no_sb in (False, True):
        for no_rail in (False, True):
            w = grid_widths(viewport, no_sb, no_rail, explicit=True)
            expect = viewport - (0 if no_sb else SIDEBAR_W) - (0 if no_rail else RAIL_W)
            label = f"{viewport}px sidebar={'off' if no_sb else 'on'} rail={'off' if no_rail else 'on'}"
            check(f"[{label}] #main gets the full middle column", w["#main"] == expect, w)
            check(f"[{label}] #main is a usable width", w["#main"] >= 400, w["#main"])
            if not no_sb:
                check(f"[{label}] sidebar keeps its own column", w["#sidebar"] == SIDEBAR_W, w)
            if not no_rail:
                check(f"[{label}] rail keeps its own column", w["#rail"] == RAIL_W, w)

# Split mode must only engage when the EDITOR (not the window) has room,
# and each pane must stay readable.
SPLIT_WANTS_MAIN = int(re.search(r"SPLIT_WANTS_MAIN = (\d+)", js).group(1))
SPLIT_FLOOR_MAIN = int(re.search(r"SPLIT_FLOOR_MAIN = (\d+)", js).group(1))
check("thresholds read from the app", (SPLIT_WANTS_MAIN, SPLIT_FLOOR_MAIN) == (700, 620),
      (SPLIT_WANTS_MAIN, SPLIT_FLOOR_MAIN))
def layout_for(viewport, no_sb, no_rail, pref=""):
    avail = max(0, viewport - (0 if no_sb else SIDEBAR_W) - (0 if no_rail else RAIL_W))
    if avail < SPLIT_FLOOR_MAIN: return "stacked", avail
    return (pref or ("split" if avail >= SPLIT_WANTS_MAIN else "stacked")), avail

for src, name in [(js, "app")]:
    check("layout decided on available width, not window width",
          "availableMainWidth()" in src and "window.innerWidth - sb - rail" in src)

cases = [
    # viewport, sidebar-off, rail-off, pref, expected
    (1000, False, False, "",      "stacked"),   # 424px editor: under the floor
    (1000, True,  False, "",      "stacked"),   # 688px editor: just under the 700 line
    (1000, True,  True,  "",      "split"),     # 1000px editor
    (1440, False, False, "",      "split"),     # 864px editor
    (1000, False, False, "split", "stacked"),   # explicit split, under the floor
    (1440, False, False, "split", "split"),
    (1920, False, False, "",      "split"),
]
for viewport, no_sb, no_rail, pref, expected in cases:
    got, avail = layout_for(viewport, no_sb, no_rail, pref)
    check(f"layout at {viewport}px sb={'off' if no_sb else 'on'} rail={'off' if no_rail else 'on'}"
          f" pref={pref or 'auto'} -> {expected} ({avail}px editor)", got == expected, got)

for viewport, no_sb, no_rail, pref in [(1440, False, False, ""), (1920, False, False, ""),
                                       (1000, True, True, "")]:
    mode, avail = layout_for(viewport, no_sb, no_rail, pref)
    if mode == "split":
        check(f"split panes readable at {viewport}px ({avail//2}px each)", avail / 2 >= 280, avail / 2)

check("toggling a side panel re-evaluates the layout",
      len(re.findall(r"classList\.toggle\(\"no-(sidebar|rail)\"\);\s*\n\s*prefs\.ui[^;]*;\s*\n\s*applyLayout\(\);", js)) == 2)

# Top bar must fit its controls without clipping in the tightest split case.
# Run and Stop are never visible at the same time, so only the wider counts.
TOPBAR = {"hamburger": 32, "title": 60, "run_or_stop": 92, "keypill": 62,
          "layout": 32, "theme": 32, "railtoggle": 32, "estimate": 150}
GAPS = 8 * 8 + 24    # flex gaps + horizontal padding
NEEDED = sum(TOPBAR.values()) + GAPS
check(f"split top bar ({NEEDED}px of controls) fits the {SPLIT_FLOOR_MAIN}px floor",
      NEEDED <= SPLIT_FLOOR_MAIN, NEEDED)
# Stacked mode has no run controls up there at all, so it fits anywhere.
STACKED_NEEDED = NEEDED - TOPBAR["run_or_stop"] - TOPBAR["estimate"]
check("stacked top bar fits even a phone-width window", STACKED_NEEDED <= 360, STACKED_NEEDED)
check("top bar clips rather than overlaps", re.search(r"#topbar\{[^}]*overflow:hidden", css) is not None)
check("top bar controls do not shrink",
      "#topbar > .btn, #topbar > #keyState{flex:0 0 auto}" in css)
check("Save version and the hint yield on a narrow split top bar",
      "body.split #saveVersion{display:none}" in css.replace("\n", "").replace("  ", "") or
      re.search(r"@media \(max-width:1240px\)\{[^}]*body\.split #saveVersion\{display:none\}", css, re.S) is not None)

# ─── K. temperature default ───────────────────────────────────────────────────

print("\nK. temperature default")
TEMP_DEFAULT = 1

def effective_temperature(settings, caps_temp):
    """Port of effectiveTemperature()."""
    if not caps_temp: return None
    t = settings.get("temperature", None)
    if isinstance(t, (int, float)) and not isinstance(t, bool): return t
    if t is False: return None
    return TEMP_DEFAULT

check("new chat defaults to 1.0 on a temp-capable model",
      effective_temperature({"temperature": None}, True) == 1)
check("chat with no temperature key defaults to 1.0",
      effective_temperature({}, True) == 1)
check("imported temperature is respected",
      effective_temperature({"temperature": 0.3}, True) == 0.3)
check("temperature 0 is respected (not treated as unset)",
      effective_temperature({"temperature": 0}, True) == 0)
check("explicitly unticked stays off",
      effective_temperature({"temperature": False}, True) is None)
check("unticked persists per chat, even though the default is on",
      effective_temperature({"temperature": False}, True) is None)
check("never sent on a model that rejects it",
      effective_temperature({"temperature": 0.7}, False) is None)
check("never sent on a rejecting model even when undecided",
      effective_temperature({"temperature": None}, False) is None)
check("unticking writes false, not null",
      re.search(r'e\.target\.checked \? Number\(\$\("#tempNum"\)\.value \|\| TEMP_DEFAULT\) : false', js) is not None)
check("request builder goes through effectiveTemperature",
      re.search(r"const temp = effectiveTemperature\(s, caps\);\s*\n\s*if \(temp != null\) body\.temperature = temp;", js) is not None)
check("effort default-unset behaviour untouched",
      'el("option", { value: "" }, "default (not sent)")' in js and
      "if (s.effort) body.output_config = { effort: s.effort };" in js)

# ─── L. public release hardening ─────────────────────────────────────────────

print("\nL. public release hardening")

check("CSP meta present with tight connect-src",
      'http-equiv="Content-Security-Policy"' in html and
      "connect-src https://api.anthropic.com" in html and
      "default-src 'none'" in html)
csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html).group(1)
check("connect-src allows only api.anthropic.com",
      re.search(r"connect-src ([^;]+)", csp).group(1).strip() == "https://api.anthropic.com")
check("no innerHTML anywhere", "innerHTML" not in js)
check("no eval/Function/document.write",
      not re.search(r"\beval\(|new Function\(|document\.write", js))
check("no console logging (keys must never leak there)", "console." not in js)
fetch_targets = re.findall(r"fetch\((\w+)", js)
check("API base is a const and the only fetch target",
      'const API_BASE = "https://api.anthropic.com"' in js and
      set(fetch_targets) == {"API_BASE", "url"} and
      "const url = API_BASE +" in js)

check("backup identifies as claude-local-workbench",
      'const APP_ID = "claude-local-workbench"' in js and "app: APP_ID" in js)
check("legacy backup id accepted forever",
      'const LEGACY_APP_ID = "michelle-workbench"' in js and
      js.count("data.app === APP_ID || data.app === LEGACY_APP_ID") == 2)
check("database renamed with one-time legacy migration",
      'const DB_NAME = "claude-local-workbench"' in js and
      'const LEGACY_DB_NAME = "michelle-workbench"' in js and
      "await migrateLegacyDB();" in js)
check("migration only probes via indexedDB.databases (never creates the old DB)",
      'if (typeof indexedDB.databases !== "function") return;' in js)
check("migration never merges into existing data",
      re.search(r"if \(\(await dbAllChats\(\)\)\.length\) return;", js) is not None)

check("imported chats are sanitized before put",
      "sanitizeChat(" in js and "sanitizeVersion(" in js and
      re.search(r"const incoming = sanitizeChat\(raw\);", js) is not None)
check("imported timestamps clamped against future-pinning",
      re.search(r"Date\.now\(\) \+ 86400000", js) is not None)
check("txn aborts on synchronous throw (no partial imports)",
      re.search(r"catch \(e\) \{ try \{ t\.abort\(\); \} catch \{\} rej\(e\); return; \}", js) is not None)

check("zip decompression capped (declared and actual size)",
      "MAX_EXTRACT" in js and "entry.usize > MAX_EXTRACT" in js and
      "total > MAX_EXTRACT" in js)

# Port of importMs(): clamp future timestamps, repair garbage.
NOW = 1755400000000
def import_ms(n, now=NOW):
    cap = now + 86400000
    if isinstance(n, (int, float)) and not isinstance(n, bool) and n > 0:
        return min(n, cap)
    return now
check("importMs clamps a far-future timestamp", import_ms(9007199254740991) == NOW + 86400000)
check("importMs keeps a sane timestamp", import_ms(NOW - 5000) == NOW - 5000)
check("importMs repairs garbage", import_ms(None) == NOW and import_ms(-5) == NOW)

check("test key never persists (finally restores)",
      re.search(r"finally \{\s*\n\s*prefs\.key = saved;", js) is not None)
check("linked file never silently overwritten when unrecognised",
      "this app doesn't recognise" in js)
check("stream usage merged without __proto__",
      'k === "__proto__"' in js and "mergeUsage(evt.usage)" in js and
      "Object.assign(out.usage" not in js)
check("stream block index validated",
      "Number.isInteger(i) && i >= 0 && i < 10000" in js)
check("version string wired into Settings",
      re.search(r'const APP_VERSION = "\d+\.\d+\.\d+"', js) is not None and
      'textContent = "claude-local-workbench v" + APP_VERSION' in js)

check("no personal names/paths in the shipped file",
      not re.search(r"(?i)michelle(?!-workbench)|snowstar|catsr|C:\\\\Fable", js + html))
check("message and system textareas opt out of spellcheck",
      'spellcheck: "false"' in js and '<textarea id="sysText" spellcheck="false"' in html)

# ─── M. consolidated settings + ephemeral key ────────────────────────────────

print("\nM. consolidated settings + ephemeral key")

check("gear opens Settings from the top bar",
      'id="topSettingsBtn"' in html and '$("#topSettingsBtn").onclick = openSettings;' in js)
check("backup and restore reachable from the Settings dialog",
      'id="exportAllDlg"' in html and 'id="restoreAllDlg"' in html and
      '$("#exportAllDlg").onclick = exportAll;' in js and
      '$("#restoreAllDlg").onclick = () => $("#filePick").click();' in js)
check("key pill is a warning only (hidden once a key is set)",
      "pill.hidden = !!prefs.key;" in js and '"key set"' not in js)
check("[hidden] attribute beats author display rules",
      "[hidden]{display:none !important}" in html)
check("theme control lives in the Settings dialog",
      html.count('type="radio" name="themeSel"') == 3 and
      all(f'name="themeSel" value="{v}"' in html for v in ("light", "dark", "system")))
check("theme applies immediately on change",
      "prefs.theme = r.value; applyTheme();" in js)
check("old standalone theme button is gone",
      "toggleTheme" not in html and "toggleTheme" not in js)
check("openSettings reflects the saved theme",
      'input[name="themeSel"][value="system"]' in js)

check("ephemeral key checkbox exists",
      'id="keyEphemeral"' in html)
check("ephemeral key lives in memory only",
      "let memoryKey" in js and
      "this.keyEphemeral ? memoryKey" in js and
      "sessionStorage." not in js)   # the word may appear in comments; calls may not
check("enabling ephemeral wipes the stored key",
      re.search(r'if \(this\.keyEphemeral\) \{ memoryKey = v; localStorage\.removeItem\("wb\.apiKey"\); \}', js) is not None)
check("disabling ephemeral clears the memory copy",
      re.search(r'localStorage\.setItem\("wb\.apiKey", v\); memoryKey = "";', js) is not None)
check("toggle moves the key immediately, not on Save",
      re.search(r"const k = prefs\.key;\s*\n\s*prefs\.keyEphemeral = e\.target\.checked;\s*\n\s*prefs\.key = k;", js) is not None)

# Port of the prefs.key storage contract.
class PrefsPort:
    def __init__(self):
        self.local = {}
        self.memory_key = ""
    @property
    def key_ephemeral(self):
        return self.local.get("wb.keyEphemeral") == "1"
    @key_ephemeral.setter
    def key_ephemeral(self, v):
        self.local["wb.keyEphemeral"] = "1" if v else "0"
    @property
    def key(self):
        return self.memory_key if self.key_ephemeral else self.local.get("wb.apiKey", "")
    @key.setter
    def key(self, v):
        if self.key_ephemeral:
            self.memory_key = v
            self.local.pop("wb.apiKey", None)
        else:
            self.local["wb.apiKey"] = v
            self.memory_key = ""

p = PrefsPort()
p.key = "sk-test-1"
check("normal mode stores the key", p.local.get("wb.apiKey") == "sk-test-1")
k = p.key; p.key_ephemeral = True; p.key = k        # the toggle handler's move
check("toggling on wipes storage but keeps the key usable",
      "wb.apiKey" not in p.local and p.key == "sk-test-1")
p.memory_key = ""                                    # simulate a page refresh
check("refresh forgets an ephemeral key", p.key == "")
p.key = "sk-test-2"
k = p.key; p.key_ephemeral = False; p.key = k
check("toggling off stores the key again and clears memory",
      p.local.get("wb.apiKey") == "sk-test-2" and p.memory_key == "")

print("\n" + ("ALL CHECKS PASSED" if not FAILS else "FAILURES: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
