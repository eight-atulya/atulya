# atulya-cortex-whatsapp-bridge

Local Node bridge that lets `atulya-cortex` (Python) talk to WhatsApp Web via
[Baileys](https://github.com/WhiskeySockets/Baileys).

## Why this exists

WhatsApp does not offer an unofficial official API. Baileys speaks the WhatsApp
Web protocol from Node, so we run it as a child process of `atulya-cortex` and
exchange newline-delimited JSON over stdout / a tiny HTTP server on
`127.0.0.1:7732`. The Python side (`sensors/whatsapp.py::BaileysBackend`) is
backend-agnostic; switching to Meta's WhatsApp Cloud API later does not touch
this directory.

## One-time install

```bash
cd scripts/whatsapp-bridge
npm install
```

Requires Node.js >= 18. The first install pulls Baileys, pino, and
`qrcode-terminal` (~80 MB on disk).

## Pair your phone

```bash
# from the atulya monorepo root:
uv run --package atulya-cortex atulya-cortex whatsapp pair
```

This launches the bridge with `CORTEX_WA_PAIR_ONLY=1`, prints a QR to your
terminal, waits for `connection.update == "open"`, then exits. Open WhatsApp
on your phone -> Linked Devices -> "Link a device" -> scan.

The Baileys auth state is written to `~/.atulya/cortex/whatsapp/session/`.
Back this directory up if you don't want to re-pair.

## Run the loop

```bash
uv run --package atulya-cortex atulya-cortex whatsapp start
```

Inbound messages -> JSON lines on the bridge's stdout -> Python `WhatsAppEar`
-> reflex chain (DMPairing) -> Cortex -> Reply motor -> bridge HTTP `POST /send`
-> WhatsApp Web. First message from a new contact returns a "waiting on
operator" reply; approve them with:

```bash
uv run --package atulya-cortex atulya-cortex pairing approve whatsapp:<jid>
```

## Wire format (kept stable for the Python side)

### Bridge -> Python (stdout, one JSON object per line)

```json
{"from":"919999999999@s.whatsapp.net","body":"hi","id":"...", "timestamp":1700000000,"pushName":"Atul"}
```

The Python side requires `from` and `body`; everything else is optional and
preserved on `Stimulus.raw`.

### Python -> Bridge (HTTP POST `/send`)

```http
POST /send HTTP/1.1
Host: 127.0.0.1:7732
Content-Type: application/json

{"to":"919999999999@s.whatsapp.net","text":"hello back"}
```

Bare numeric msisdn (no `@s.whatsapp.net`) is auto-normalized.

### Diagnostics (stderr only — never goes to stdout)

```
[bridge] {"event":"starting","authDir":"...","port":7732,"pairOnly":false}
[bridge] {"event":"qr","length":248}
[bridge] {"event":"connected"}
[bridge] {"event":"disconnected","code":401}
```

Anything on stderr is logged through to `atulya-cortex` so `whatsapp pair` /
`whatsapp start` show real-time bridge state.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `CORTEX_WA_AUTH_DIR` | `./session` | Where Baileys multi-file auth state lives. The Python side passes `~/.atulya/cortex/whatsapp/session`. |
| `CORTEX_WA_BRIDGE_PORT` | `7732` | HTTP port for `POST /send`. |
| `CORTEX_WA_PRINT_QR` | `0` | `1` renders the QR in this terminal (only useful when running interactively). |
| `CORTEX_WA_PAIR_ONLY` | `0` | `1` exits with code 0 once pairing succeeds. |

## Caveats

- Group chats and channel broadcasts are filtered out — only 1:1 user chats
  reach the cortex. Group support belongs in a follow-up batch with explicit
  consent UX.
- Multimedia (voice notes, images, documents) are not forwarded yet; the
  bridge only relays text + image/video captions. Track this in the
  `cortex/dream/skill_distill.md` follow-ups doc.
- WhatsApp's unofficial protocol can change unannounced. If pairing or send
  starts failing, `npm update @whiskeysockets/baileys` is the first thing to
  try.
