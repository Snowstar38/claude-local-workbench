import json, os, sys, urllib.request, urllib.error

# Live smoke-test of the API behaviors workbench.html depends on (prefill and
# sampling denylists, SSE shape, error shapes). Each run costs a few cents.
# Pass the key for this run only: ANTHROPIC_API_KEY=sk-ant-... python api-probe.py
KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not KEY:
    sys.exit("Set ANTHROPIC_API_KEY in the environment for this run.")
BASE = "https://api.anthropic.com"
H = {
    "x-api-key": KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
    "anthropic-dangerous-direct-browser-access": "true",
}

def call(method, path, body=None, stream=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=H, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, dict(r.headers), raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, dict(e.headers), raw

def show(name, status, hdrs, raw, limit=2500):
    print("=" * 70)
    print("### " + name)
    print("STATUS:", status)
    print("req-id:", hdrs.get("request-id"))
    print("BODY:")
    print(raw[:limit] + ("\n...[truncated]" if len(raw) > limit else ""))
    print()

def msg(model, messages, **kw):
    b = {"model": model, "max_tokens": 40, "messages": messages}
    b.update(kw)
    return b

# 1. models list
s, h, r = call("GET", "/v1/models?limit=5")
show("1a. GET /v1/models?limit=5", s, h, r, 4000)
s, h, r = call("GET", "/v1/models")
show("1b. GET /v1/models (no params)", s, h, r, 8000)

# 2. streaming
print("=" * 70)
print("### 2. streaming on claude-haiku-4-5")
body = msg("claude-haiku-4-5", [{"role": "user", "content": "Say hi in 3 words."}], stream=True)
req = urllib.request.Request(BASE + "/v1/messages", data=json.dumps(body).encode(), headers=H, method="POST")
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        print("STATUS:", resp.status)
        print("content-type:", resp.headers.get("content-type"))
        for line in resp:
            line = line.decode("utf-8", "replace").rstrip("\n")
            if len(line) > 300:
                line = line[:300] + "...[truncated]"
            print(repr(line))
except urllib.error.HTTPError as e:
    print("STATUS:", e.code, e.read().decode("utf-8", "replace"))
print()

PREFILL = [{"role": "user", "content": "Say the alphabet."}, {"role": "assistant", "content": "A B C"}]

# 3
s, h, r = call("POST", "/v1/messages", msg("claude-haiku-4-5", PREFILL))
show("3. prefill on claude-haiku-4-5", s, h, r)

# 4
s, h, r = call("POST", "/v1/messages", msg("claude-sonnet-5", PREFILL))
show("4. prefill on claude-sonnet-5", s, h, r)

# 4b extra: prefill on opus-5 and fable-5 and haiku via 4.6
for m in ["claude-opus-5", "claude-fable-5", "claude-sonnet-4-6", "claude-opus-4-6"]:
    s, h, r = call("POST", "/v1/messages", msg(m, PREFILL))
    show("4x. prefill on " + m, s, h, r, 1200)

# 5
s, h, r = call("POST", "/v1/messages", msg("claude-sonnet-5", [{"role": "user", "content": "Hi"}], temperature=0.7))
show("5a. temperature=0.7 on claude-sonnet-5", s, h, r)
s, h, r = call("POST", "/v1/messages", msg("claude-haiku-4-5", [{"role": "user", "content": "Hi"}], temperature=0.7))
show("5b. temperature=0.7 on claude-haiku-4-5", s, h, r)
for m in ["claude-fable-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6"]:
    s, h, r = call("POST", "/v1/messages", msg(m, [{"role": "user", "content": "Hi"}], temperature=0.7))
    show("5x. temperature=0.7 on " + m, s, h, r, 1200)
# top_p / top_k on sonnet-5
s, h, r = call("POST", "/v1/messages", msg("claude-sonnet-5", [{"role": "user", "content": "Hi"}], top_p=0.9))
show("5y. top_p on claude-sonnet-5", s, h, r, 1200)
s, h, r = call("POST", "/v1/messages", msg("claude-sonnet-5", [{"role": "user", "content": "Hi"}], top_k=5))
show("5z. top_k on claude-sonnet-5", s, h, r, 1200)

# 6 consecutive same-role
s, h, r = call("POST", "/v1/messages", msg("claude-haiku-4-5", [
    {"role": "user", "content": "What is 2+2?"},
    {"role": "user", "content": "Answer in one word."},
]))
show("6. two consecutive user messages on claude-haiku-4-5", s, h, r)

# 7 output_config effort
s, h, r = call("POST", "/v1/messages", msg("claude-haiku-4-5", [{"role": "user", "content": "Hi"}], output_config={"effort": "low"}))
show("7. output_config effort=low on claude-haiku-4-5", s, h, r)

# 8 bad model
s, h, r = call("POST", "/v1/messages", msg("claude-not-a-real-model", [{"role": "user", "content": "Hi"}]))
show("8a. bad model id POST /v1/messages", s, h, r)
s, h, r = call("GET", "/v1/models/claude-not-a-real-model")
show("8b. GET /v1/models/claude-not-a-real-model", s, h, r)
