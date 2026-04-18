# Linux Systemd Autostart For Long-Running Dev Services (e.g. Atulya `start.sh`)

Date: 2026-04-18  
Repo: atulya  
Area: Linux operations, systemd, developer ergonomics, service supervision

## Trigger

We needed a **proven, standard** way to run `./scripts/dev/start.sh` (or any long-lived app) **automatically after system restart**, with restart-on-failure and observable logs—without ad-hoc `cron @reboot` hacks.

## What “Cortex” Stores Here

`atulya-cortex/life/40_knowledge/17_lessons_learned/` holds **durable operational learning**: what broke, what worked, and **repeatable procedures**. This file is **not** wired into the Atulya API—it is **versioned knowledge** next to the product. Runtime “memory” still lives in banks via **retain** / Control Plane; cortex is the **human-auditable playbook**.

## Standard Answer On Linux: systemd

On mainstream distros (Ubuntu, Debian, Fedora, Arch, etc.), **systemd** is the supported mechanism for:

- start at boot (or at user session, see below)
- restart on crash
- logging via `journalctl`
- explicit dependencies (`After=network-online.target`)

**Alternatives (when not to use them for daemons):**

| Mechanism | Good for | Weak for |
|-----------|----------|----------|
| **systemd unit** | Long-running services, reboot policy, logs | Quick one-liners (overkill) |
| **`cron` `@reboot`** | One-shot scripts, background `nohup` patterns | Supervision, structured logs, dependency ordering |
| **Desktop autostart** (`~/.config/autostart`) | GUI apps at **login** | Headless boot, services before login |
| **`/etc/rc.local`** | Legacy | Deprecated / inconsistent on systemd systems |

## When To Use Which systemd Flavor

| Goal | Approach |
|------|----------|
| Run **as root** or fixed system user, **at boot** | **System unit**: `/etc/systemd/system/<name>.service` + `enable --now` |
| Run **as your user**, start **without interactive login** | **User unit** + **`loginctl enable-linger`** for that user |
| Run **only after graphical login** | User unit **without** linger, or desktop autostart |

For a **dev stack** (Atulya API + Control Plane), a **user-scoped systemd service** + **linger** often matches “my machine, my user, starts on boot” without running the dev server as root.

## How: System Unit (runs at boot, typical for fixed path + dedicated user)

### 1. Prerequisites

- Script is executable: `chmod +x scripts/dev/start.sh`
- You know **absolute paths** to repo and to `node`/`uv` if not on default `PATH` for systemd (often **not** the same as your interactive shell—**nvm/fnm/pyenv** usually need a **wrapper script**).

### 2. Unit file (example)

Path (system-wide): `/etc/systemd/system/atulya-dev.service`

```ini
[Unit]
Description=Atulya dev stack (scripts/dev/start.sh)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
Group=YOUR_GROUP
WorkingDirectory=/absolute/path/to/atulya
# If node/uv are not in systemd's PATH, use a wrapper script for ExecStart:
ExecStart=/absolute/path/to/atulya/scripts/dev/start.sh
Restart=on-failure
RestartSec=5
# Optional: EnvironmentFile=-/absolute/path/to/atulya/.env

[Install]
WantedBy=multi-user.target
```

### 3. Enable and verify

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now atulya-dev.service
sudo systemctl status atulya-dev.service
journalctl -u atulya-dev.service -f
```

### 4. Stop / disable

```bash
sudo systemctl disable --now atulya-dev.service
```

## How: User Unit + Linger (same user, start at boot without login)

### 1. Unit file

Path: `~/.config/systemd/user/atulya-dev.service` (contents similar to above, but **omit** `User=` / `Group=`—it runs as you.)

### 2. Allow user services at boot

```bash
sudo loginctl enable-linger "$USER"
```

### 3. Enable

```bash
systemctl --user daemon-reload
systemctl --user enable --now atulya-dev.service
systemctl --user status atulya-dev.service
journalctl --user -u atulya-dev.service -f
```

## What-If Matrix

### What if `ExecStart` fails with `node: not found` or `uv: not found`?

**Cause:** systemd does not load your `.bashrc` / nvm.  
**Fix:** Use a **wrapper** `/home/you/bin/atulya-start.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
source "$HOME/.nvm/nvm.sh"   # or: export PATH="$HOME/.local/bin:$PATH"
cd /absolute/path/to/atulya
exec ./scripts/dev/start.sh
```

Point `ExecStart=` at the wrapper; `chmod +x` the wrapper.

### What if ports 8888 / 9999 are already in use?

**Cause:** Another process or a **previous** run still bound the port.  
**Fix:** Before enabling the unit, ensure clean shutdown; adjust `.env` ports if needed; use `ss -tlnp` / `lsof -i` to find conflicts.

### What if the service “starts” but exits immediately?

**Cause:** `start.sh` expects a TTY, or a child crashes on boot before network is ready.  
**Fix:** Keep `After=network-online.target`; inspect `journalctl -u ... -b`; consider `Restart=on-failure` and longer `RestartSec`.

### What if I use Docker instead?

**Cause:** Different lifecycle—compose or container restart policies.  
**Fix:** Prefer **compose** or **podman** unit generation; do not duplicate the same dev stack in both systemd and Docker unless intentional.

### What if this is production?

**Cause:** `start.sh` is a **dev** orchestrator (hot reload, local UX).  
**Fix:** Production should use **packaged** services, secrets management, split API/UI units, and hardening—not a blind copy of the dev unit.

## Practical Rules

1. **Prefer systemd** over `@reboot` cron for anything that should **stay up** and be **debuggable**.
2. **Never assume PATH** matches your shell—use a **wrapper** when using nvm/fnm/pyenv.
3. **Use `journalctl`** as the first debug step; it replaces scattered log files.
4. **User units + linger** for personal dev machines; **system units** for shared servers or fixed service accounts.
5. **Document** the unit name and path in cortex (this file) when the team depends on it.

## Validation Checklist

After enabling:

- [ ] `systemctl status` shows **active (running)** (or user equivalent).
- [ ] `curl -sSf http://localhost:8888/health` (or your API port) succeeds.
- [ ] Control Plane URL loads on expected port (default **9999**).
- [ ] Reboot once and confirm services come back without manual `./start.sh`.

## Expected Benefits

- Predictable restarts after machine reboot
- Crash recovery via `Restart=on-failure`
- Centralized logs for ops and support
- Clear separation from one-off cron hacks

## Cortex Links

- Local dev setup: [scripts/dev/SETUP.md](../../../../scripts/dev/SETUP.md) (repo root `atulya/`)
