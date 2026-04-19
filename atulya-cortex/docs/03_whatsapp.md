# WhatsApp quickstart

`atulya-cortex` speaks WhatsApp through one of two backends:

| Backend | Use when | Pros | Cons |
| --- | --- | --- | --- |
| `baileys` (default) | dev, personal use, fast iteration | no Meta Business account; QR pair from phone | unofficial protocol — can break on protocol updates |
| `cloud` | production, business numbers | official Meta API, ban-immune | requires Meta Business + verified number + webhook gateway |

This doc walks through the `baileys` path; the `cloud` path is referenced at the end.

## 1. Prerequisites

- Node.js >= 18 on `PATH`. Verify: `node --version`.
- `atulya-cortex` installed and `atulya-cortex setup` already run (so config + persona + skills are seeded).
- Your phone, with WhatsApp installed and you signed in.

## 2. Install the bridge (one-time)

```bash
cd /home/atulya-agent/atulya-agent/atulya/atulya-cortex/scripts/whatsapp-bridge
npm install
```

`npm install` pulls Baileys + pino + qrcode-terminal (~80 MB). The bridge itself is a single ~250-line file you can read at `whatsapp-bridge.js` if you want to audit it.

## 3. Enable WhatsApp in config

```bash
uv run --package atulya-cortex atulya-cortex config set whatsapp.enabled true
```

Then health-check:

```bash
uv run --package atulya-cortex atulya-cortex whatsapp doctor
```

Expect:

```
  node        PATH  ->  found
  bridge      scripts/whatsapp-bridge  ->  /…/scripts/whatsapp-bridge
  session     ~/.atulya/cortex/whatsapp/session  ->  exists
  creds.json  ~/.atulya/cortex/whatsapp/session/creds.json  ->  absent (run `atulya-cortex whatsapp pair`)
```

## 4. Pair your phone

```bash
uv run --package atulya-cortex atulya-cortex whatsapp pair
```

You'll see bridge logs and a QR rendered in the terminal. On your phone:

1. WhatsApp -> Settings -> Linked Devices -> "Link a device"
2. Scan the QR.

Wait for `[bridge] {"event":"connected"}` -> `{"event":"pair_complete"}` -> the process exits with code 0. Your auth state is stored under `~/.atulya/cortex/whatsapp/session/creds.json` (chmod 600). Back this directory up if you don't want to re-pair.

If pairing times out (default 180s), re-run with `--timeout 300`.

## 5. Run the loop

```bash
uv run --package atulya-cortex atulya-cortex whatsapp start
```

Stays in the foreground. Ctrl-C to stop.

The first message from any new contact will trigger DMPairing — they get a friendly "waiting on operator" reply. To approve them:

```bash
uv run --package atulya-cortex atulya-cortex pairing list
uv run --package atulya-cortex atulya-cortex pairing approve whatsapp:919999999999@s.whatsapp.net
```

After approval their next message reaches the cortex. To revoke:

```bash
uv run --package atulya-cortex atulya-cortex pairing revoke whatsapp:919999999999@s.whatsapp.net
```

### Bypass DMPairing (private numbers only)

If you're on your own number and don't want a per-contact approval step:

```bash
uv run --package atulya-cortex atulya-cortex whatsapp start --default-allow
```

This auto-allows every WhatsApp peer. **Don't use this on a number that anyone can message you on.**

### Echo mode (transport sanity check)

```bash
uv run --package atulya-cortex atulya-cortex whatsapp start --default-allow --echo
```

Skips the LLM and just echoes back. Useful to verify the bridge plumbing works before paying for token costs.

## 6. One-shot test send

To verify outbound works without messaging the bot from your phone:

```bash
# in another terminal while `whatsapp start` is running:
uv run --package atulya-cortex atulya-cortex whatsapp send 919999999999 "hello from cortex"
```

You can also run `send` standalone — it'll spawn the bridge briefly, send, then exit. (Requires you've already paired.)

## 7. Common issues

- **"node not found"** — install Node 18+ and re-open the shell.
- **"@whiskeysockets/baileys is not installed"** — `npm install` in `scripts/whatsapp-bridge` (you skipped step 2).
- **Bridge prints `disconnected code=401`** — your session was logged out (e.g. you removed the linked device from your phone). Re-pair with `whatsapp pair`.
- **Group messages don't reach the bot** — by design. The bridge filters out `*@g.us` JIDs in v1; group support is a follow-up.
- **No reply / empty reply** — your LLM provider isn't reachable. Run `atulya-cortex doctor` first; LM Studio / Ollama need to be running.
- **`POST /send` returns 503** — the bridge connected but is reconnecting. Retry after a second.

## 8. Cloud backend (production)

```bash
uv run --package atulya-cortex atulya-cortex config set whatsapp.backend '"cloud"'
# Add to ~/.atulya/cortex/.env:
#   WHATSAPP_PHONE_NUMBER_ID=...
#   WHATSAPP_ACCESS_TOKEN=...
#   WHATSAPP_VERIFY_TOKEN=...
```

The cloud backend has no `pair` step; pairing happens in Meta's UI when you register the number. Inbound messages arrive via a webhook — that surface lands in Batch E together with `atulya-cortex gateway`. You can already use `atulya-cortex whatsapp send <jid> <text>` and `atulya-cortex whatsapp doctor` against the cloud backend.

## 9. What's wired

```
phone (you)
   |
   v
WhatsApp Web (Meta)
   |
   v
scripts/whatsapp-bridge/whatsapp-bridge.js   <-- Baileys (Node)
   |  stdout: {"from":"…@s.whatsapp.net","body":"…"}
   |  POST 127.0.0.1:7732/send {"to":"…","text":"…"}
   v
sensors/whatsapp.py::BaileysBackend
   |
   v
sensors/whatsapp.py::WhatsAppEar
   |
   v
brainstem.Router  -- reflexes: DMPairing
   |
   v
cortex.Cortex  (persona + skills + LLM via cortex.language)
   |
   v
motors.Reply  -- egress: ear.send(jid, text)
```

Everything past `BaileysBackend` is shared with `tui` and (future) `telegram`. Switching providers, adding skills, or editing your persona changes WhatsApp replies the same way it changes TUI replies.
