#!/usr/bin/env node
/*
 * whatsapp-bridge.js — atulya-cortex <-> WhatsApp Web (Baileys).
 *
 * Wire format (matches sensors/whatsapp.py BaileysBackend):
 *
 *   - INBOUND  : one JSON object per line on stdout, e.g.
 *                {"from": "919999999999@s.whatsapp.net", "body": "hi"}
 *   - OUTBOUND : HTTP POST {"to": "<jid>", "text": "<msg>"} to /send on
 *                127.0.0.1:${CORTEX_WA_BRIDGE_PORT}.
 *
 * Diagnostic / status events go to stderr (so they never pollute the
 * inbound JSON stream the Python side parses).
 *
 * Environment:
 *   CORTEX_WA_AUTH_DIR     directory for Baileys multi-file auth state
 *                          (default: ./session)
 *   CORTEX_WA_BRIDGE_PORT  HTTP port for the /send endpoint (default 7732)
 *   CORTEX_WA_PRINT_QR     "1" prints the QR to stderr as ASCII
 *   CORTEX_WA_PAIR_ONLY    "1" exits with code 0 once connection.update
 *                          fires with connection === "open"
 */

"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");

let baileys;
try {
  baileys = require("@whiskeysockets/baileys");
} catch (err) {
  process.stderr.write(
    "[bridge] FATAL: @whiskeysockets/baileys is not installed. " +
      "Run `npm install` in this directory.\n",
  );
  process.exit(2);
}

const {
  default: makeWASocket,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  useMultiFileAuthState,
} = baileys;

let pino;
try {
  pino = require("pino");
} catch (_) {
  pino = () => ({
    level: "silent",
    info() {},
    warn() {},
    error() {},
    debug() {},
    child() {
      return this;
    },
  });
}

let qrcode;
try {
  qrcode = require("qrcode-terminal");
} catch (_) {
  qrcode = null;
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const AUTH_DIR = path.resolve(process.env.CORTEX_WA_AUTH_DIR || "./session");
const BRIDGE_PORT = parseInt(process.env.CORTEX_WA_BRIDGE_PORT || "7732", 10);
const PRINT_QR = (process.env.CORTEX_WA_PRINT_QR || "0") === "1";
const PAIR_ONLY = (process.env.CORTEX_WA_PAIR_ONLY || "0") === "1";

fs.mkdirSync(AUTH_DIR, { recursive: true });

const logger = pino({ level: "silent" });

// ---------------------------------------------------------------------------
// Inbound -> stdout JSON lines
// ---------------------------------------------------------------------------

let socketRef = null;
let connectionState = "init"; // init | qr | connecting | open | close
let pendingCredsSave = Promise.resolve();
const pendingSends = [];
const MAX_PENDING_SENDS = 100;
const MAX_PENDING_SEND_AGE_MS = 30_000;

function emitInbound(obj) {
  try {
    process.stdout.write(JSON.stringify(obj) + "\n");
  } catch (err) {
    process.stderr.write(`[bridge] failed to emit inbound: ${err}\n`);
  }
}

function emitStatus(event, extra = {}) {
  // Plain JSON; the Python pump adds its own `[bridge] ` prefix.
  process.stderr.write(JSON.stringify({ event, ...extra }) + "\n");
}

async function persistCreds(saveCreds) {
  pendingCredsSave = pendingCredsSave
    .then(async () => {
      await saveCreds();
    })
    .catch((err) => {
      emitStatus("save_creds_error", { error: String(err) });
    });
  await pendingCredsSave;
}

function pruneExpiredPendingSends() {
  const now = Date.now();
  while (pendingSends.length > 0) {
    const first = pendingSends[0];
    if (!first || now - first.enqueuedAt <= MAX_PENDING_SEND_AGE_MS) break;
    const stale = pendingSends.shift();
    if (stale) {
      stale.reject(new Error("send queue timeout while WhatsApp reconnecting"));
    }
  }
}

async function flushPendingSends() {
  pruneExpiredPendingSends();
  if (!socketRef || connectionState !== "open") return;
  while (pendingSends.length > 0 && socketRef && connectionState === "open") {
    const item = pendingSends.shift();
    if (!item) continue;
    try {
      await socketRef.sendMessage(normalizeJid(item.to), { text: item.text });
      item.resolve();
    } catch (err) {
      item.reject(err);
    }
  }
}

function queueOrSend(to, text) {
  if (socketRef && connectionState === "open") {
    return socketRef.sendMessage(normalizeJid(to), { text });
  }

  const reconnecting = connectionState === "connecting" || connectionState === "qr" || connectionState === "close";
  if (!reconnecting) {
    return Promise.reject(new Error(`bridge not ready (state=${connectionState})`));
  }

  pruneExpiredPendingSends();
  if (pendingSends.length >= MAX_PENDING_SENDS) {
    return Promise.reject(new Error("send queue full while WhatsApp reconnecting"));
  }

  return new Promise((resolve, reject) => {
    pendingSends.push({ to, text, resolve, reject, enqueuedAt: Date.now() });
  });
}

function extractText(message) {
  if (!message) return "";
  if (typeof message.conversation === "string") return message.conversation;
  if (message.extendedTextMessage && typeof message.extendedTextMessage.text === "string") {
    return message.extendedTextMessage.text;
  }
  if (message.imageMessage && typeof message.imageMessage.caption === "string") {
    return message.imageMessage.caption;
  }
  if (message.videoMessage && typeof message.videoMessage.caption === "string") {
    return message.videoMessage.caption;
  }
  if (message.buttonsResponseMessage && typeof message.buttonsResponseMessage.selectedDisplayText === "string") {
    return message.buttonsResponseMessage.selectedDisplayText;
  }
  if (message.listResponseMessage && message.listResponseMessage.title) {
    return String(message.listResponseMessage.title);
  }
  return "";
}

function shouldRelay(msg) {
  // We only relay 1:1 user chats by default. Skip status broadcasts, our own
  // outbound echo, and group chats (until cortex has explicit group support).
  if (!msg || !msg.key) return false;
  if (msg.key.fromMe) return false;
  const remoteJid = msg.key.remoteJid || "";
  if (!remoteJid || remoteJid === "status@broadcast") return false;
  if (remoteJid.endsWith("@g.us")) return false;
  return true;
}

// ---------------------------------------------------------------------------
// Outbound HTTP server (POST /send)
// ---------------------------------------------------------------------------

function startHttpServer() {
  const server = http.createServer(async (req, res) => {
    if (req.method !== "POST" || req.url !== "/send") {
      res.statusCode = 404;
      res.end("not found");
      return;
    }
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        req.destroy();
      }
    });
    req.on("end", async () => {
      let payload;
      try {
        payload = JSON.parse(body || "{}");
      } catch (err) {
        res.statusCode = 400;
        res.end("invalid json");
        return;
      }
      const to = payload.to;
      const text = payload.text;
      if (typeof to !== "string" || typeof text !== "string") {
        res.statusCode = 400;
        res.end("missing 'to' or 'text'");
        return;
      }
      try {
        await queueOrSend(to, text);
        res.statusCode = 200;
        res.end("ok");
      } catch (err) {
        emitStatus("send_error", { to, error: String(err) });
        res.statusCode = 500;
        res.end(String(err));
      }
    });
  });
  server.listen(BRIDGE_PORT, "127.0.0.1", () => {
    emitStatus("http_listening", { port: BRIDGE_PORT });
  });
  server.on("error", (err) => {
    emitStatus("http_error", { error: String(err) });
  });
  return server;
}

function normalizeJid(jid) {
  if (jid.includes("@")) return jid;
  // Bare numeric msisdn -> @s.whatsapp.net (1:1)
  return `${jid}@s.whatsapp.net`;
}

// ---------------------------------------------------------------------------
// Baileys socket lifecycle
// ---------------------------------------------------------------------------

let reconnectTimer = null;

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    logger,
    printQRInTerminal: false,
    browser: ["atulya-cortex", "cli", "0.1.0"],
    syncFullHistory: false,
    markOnlineOnConnect: false,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    // Needed on Baileys 7+: without getMessage, message retry/decrypt paths
    // can break and clients may show "Waiting for this message".
    getMessage: async () => ({ conversation: "" }),
  });

  socketRef = sock;

  sock.ev.on("creds.update", async () => {
    await persistCreds(saveCreds);
  });

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      connectionState = "qr";
      emitStatus("qr", { length: qr.length });
      if (PRINT_QR && qrcode) {
        try {
          process.stderr.write("Scan this QR in WhatsApp -> Linked Devices:\n");
          qrcode.generate(qr, { small: true }, (rendered) => {
            process.stderr.write(rendered + "\n");
          });
        } catch (err) {
          emitStatus("qr_render_error", { error: String(err) });
        }
      }
    }
    if (connection === "connecting") {
      connectionState = "connecting";
      emitStatus("connecting");
    }
    if (connection === "open") {
      connectionState = "open";
      emitStatus("connected");
      await flushPendingSends();
      if (PAIR_ONLY) {
        emitStatus("pair_complete");
        // Allow a tick so the status line flushes.
        setTimeout(() => process.exit(0), 100);
      }
    }
    if (connection === "close") {
      connectionState = "close";
      const code =
        lastDisconnect && lastDisconnect.error && lastDisconnect.error.output
          ? lastDisconnect.error.output.statusCode
          : null;
      emitStatus("disconnected", { code });
      const loggedOut = code === DisconnectReason.loggedOut;
      if (loggedOut) {
        emitStatus("logged_out");
        process.exit(1);
      }
      // Code 515 = restartRequired. Baileys emits this *immediately after*
      // a successful first pair: "your creds are saved, now reconnect to
      // start the real session". We have to reconnect even in PAIR_ONLY
      // mode — without it the user sees a confusing "disconnected 515"
      // and the session never reaches "open". See:
      //   https://github.com/WhiskeySockets/Baileys/issues/170
      const restartRequired =
        code === (DisconnectReason.restartRequired ?? 515) || code === 515;

      if (restartRequired || !PAIR_ONLY) {
        await pendingCredsSave;
        if (reconnectTimer === null) {
          // 250ms is enough for `creds.update -> saveCreds` to flush; we
          // don't want to race the rename before reconnecting.
          reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            emitStatus("reconnecting", { reason: restartRequired ? "restartRequired" : String(code) });
            connect().catch((err) => emitStatus("reconnect_error", { error: String(err) }));
          }, restartRequired ? 250 : 2000);
        }
        return;
      }

      // PAIR_ONLY + non-recoverable close: bail.
      emitStatus("pair_failed", { code });
      process.exit(1);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;
    for (const msg of messages) {
      if (!shouldRelay(msg)) continue;
      const text = extractText(msg.message);
      if (!text) continue;
      const from = msg.key.remoteJid;
      emitInbound({
        from,
        body: text,
        id: msg.key.id || null,
        timestamp: Number(msg.messageTimestamp || 0) || null,
        pushName: msg.pushName || null,
      });
    }
  });
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

(async function main() {
  emitStatus("starting", { authDir: AUTH_DIR, port: BRIDGE_PORT, pairOnly: PAIR_ONLY });
  if (!PAIR_ONLY) {
    startHttpServer();
  }
  try {
    await connect();
  } catch (err) {
    emitStatus("fatal", { error: String(err) });
    process.exit(1);
  }
})();

process.on("SIGINT", () => {
  emitStatus("sigint");
  process.exit(0);
});
process.on("SIGTERM", () => {
  emitStatus("sigterm");
  process.exit(0);
});
process.on("uncaughtException", (err) => {
  emitStatus("uncaught", { error: String(err) });
});
process.on("unhandledRejection", (err) => {
  emitStatus("unhandled_rejection", { error: String(err) });
});
