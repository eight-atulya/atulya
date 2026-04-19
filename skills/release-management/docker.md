# End-to-End Toolchain Setup

This playbook installs every host-side prerequisite that
[`scripts/generate-clients.sh`](../../scripts/generate-clients.sh) needs to
regenerate the Rust, Python, TypeScript, and Go API clients on a fresh
**Ubuntu 24.04 (Noble), x86_64** workstation.

The script orchestrates four codegen backends:

| Leg        | Tool                           | Host requirement       |
| ---------- | ------------------------------ | ---------------------- |
| Rust       | `progenitor` (run from build.rs) | `cargo` / `rustc`      |
| Python     | `openapi-generator` (Java)     | Docker **or** Java + `openapi-generator-cli` |
| TypeScript | `@hey-api/openapi-ts`          | `node` / `npm`         |
| Go         | `ogen`                         | `go`                   |

Run the phases below in order. Each is idempotent; re-running won't break a working install.

---

## Phase 1 — Install Docker Engine (system-wide, auto-start on boot)

Installs Docker CE from the upstream APT repo, enables it under systemd, and
adds `$USER` to the `docker` group so the CLI works without `sudo` — which is
the exact precondition `generate-clients.sh` checks for via `docker info`.

```bash
set -euxo pipefail

# 1. Remove any conflicting older packages (safe if none are installed).
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y "$pkg" 2>/dev/null || true
done

# 2. Prereqs.
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# 3. Add Docker's official GPG key.
sudo install -m 0755 -d /etc/apt/keyrings
sudo rm -f /etc/apt/keyrings/docker.gpg
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 4. Add the Docker APT repo for noble.
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

# 5. Install Engine + CLI + containerd + buildx + compose plugins.
sudo apt-get update
sudo apt-get install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin

# 6. Enable + start the daemon AND containerd at boot.
sudo systemctl enable --now docker.service
sudo systemctl enable --now containerd.service

# 7. Add your user to the docker group so 'docker info' works without sudo.
sudo groupadd -f docker
sudo usermod -aG docker "$USER"

# 8. Sanity checks (these use sudo because the new group isn't active yet in this shell).
sudo docker --version
sudo docker compose version
sudo docker run --rm hello-world

echo
echo "============================================================"
echo "Docker installed. systemd will start it on every boot:"
systemctl is-enabled docker
systemctl is-active docker
echo "============================================================"
```

Expected tail:

```
enabled
active
```

---

## Phase 2 — Refresh your shell's group membership (gotcha)

`usermod -aG docker $USER` only takes effect for **new login sessions**. Until
you log out and back in (or run `newgrp docker`), your current shell will see
"Permission denied" from `docker info`, which makes `generate-clients.sh` print:

```
❌ Error: OpenAPI Generator backend unavailable.
   Docker is installed only if 'docker info' succeeds, because the release
   path needs a reachable daemon, not just the client binary.
```

Pick **one** of these to fix it:

```bash
# Option A — refresh just this shell (no logout)
newgrp docker
docker info | head -5     # must print Client/Engine info, no permission errors

# Option B — proper logout/login (also confirms Phase 1 step 6 survives reboot)
exit  # then start a fresh session
docker info | head -5

# Option C — one-shot for a single command (useful in scripts/CI)
sg docker -c 'docker info | head -5'
```

Don't proceed to Phase 3 until `docker info` works **without `sudo`** in the
shell you'll run the script from.

---

## Phase 3 — Install Rust

`generate-clients.sh` runs `cargo` from the `atulya-clients/rust/` build script
to drive `progenitor`. Use rustup so the toolchain installs entirely under
`$HOME/.cargo` — no `sudo` required, easy to keep current.

```bash
# Rust — official rustup, installs to $HOME/.cargo, no sudo needed
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
. "$HOME/.cargo/env"
rustc --version && cargo --version
```

Add the env-loader to your shell rc so future sessions pick it up automatically:

```bash
grep -qxF '. "$HOME/.cargo/env"' ~/.bashrc || echo '. "$HOME/.cargo/env"' >> ~/.bashrc
```

---

## Phase 4 — Install Go

`ogen` (the Go-client generator) needs Go ≥ 1.22, which is what Ubuntu 24.04
ships. The distro package is fine for this script.

```bash
# Go — distro package is fine for ogen (Ubuntu 24.04 ships 1.22)
sudo apt-get install -y golang-go
go version
```

> **Need a newer Go?** If you want 1.23.x (current stable) instead:
>
> ```bash
> GO_VER=1.23.4
> curl -fsSL https://go.dev/dl/go${GO_VER}.linux-amd64.tar.gz | sudo tar -C /usr/local -xz
> echo 'export PATH=$PATH:/usr/local/go/bin' | sudo tee /etc/profile.d/go.sh >/dev/null
> export PATH=$PATH:/usr/local/go/bin
> go version
> ```

---

## Phase 5 — Run the client generator end-to-end

```bash
# Then re-run end to end
cd /home/atulya-agent/atulya-agent/atulya
bash scripts/generate-clients.sh
```

A successful run prints, in order:

```
✓ OpenAPI spec found
✓ OpenAPI Generator backend: Docker (v7.10.0)
✓ Client-generation spec prepared: /tmp/atulya-openapi-client-spec.XXXXXX
== Generating Rust client ==
== Generating Python client ==
== Generating TypeScript client ==
== Generating Go client ==
✓ All clients regenerated
```

---

## Phase 6 — Post-regen verification

The codegen output should compile cleanly across every surface that consumes
it. Run these one after another; each must finish with exit 0.

```bash
cd /home/atulya-agent/atulya-agent/atulya

# 1. Rust client + CLI compile against the regenerated types.
( cd atulya-clients/rust && cargo check )
( cd atulya-cli         && cargo check )

# 2. TypeScript client builds.
( cd atulya-clients/typescript && npm run build )

# 3. Control-plane typechecks against the regenerated TS types.
( cd atulya-control-plane && npx tsc --noEmit )

# 4. Python suite — run sequentially, the local LLM at .env's
#    ATULYA_LLM_BASE_URL is slow enough to flake xdist.
( cd atulya-api && uv run pytest -p no:xdist --timeout=180 )
```

Quick "did the regen actually land the new fields" smoke test (each path
should return a non-zero count):

```bash
grep -c 'tag_groups\|update_mode\|max_observations_per_scope' \
  atulya-docs/static/openapi.json \
  atulya-clients/python/atulya_client_api/models/memory_item.py \
  atulya-clients/typescript/src/atulya-client-api/types.gen.ts \
  atulya-clients/go/atulya_client_api/oas_schemas_gen.go \
  atulya-clients/rust/src/types.rs 2>/dev/null
```

If the Rust file's count is `0`, `progenitor` overwrote the hand-maintained
recursive `TagGroup` enum (it can't express the boxed-recursive variant
cleanly). Re-apply that patch before `cargo check`.

---

## Troubleshooting

### `❌ OpenAPI Generator backend unavailable`
You're running the script in a shell that can't reach the Docker daemon. The
daemon is fine (`sudo systemctl status docker` proves it); your shell just
hasn't picked up the `docker` group yet. Re-do **Phase 2**.

### `mktemp: too few X's in template ...`
Already fixed in `scripts/generate-clients.sh` line 84 — the template now ends
in `.XXXXXX` so it works on both GNU mktemp (Linux) and BSD mktemp (macOS).
If you ever see this on macOS again it means the suffix got dropped; restore
`mktemp -t atulya-openapi-client-spec.XXXXXX`.

### `cargo: command not found` / `go: command not found`
Phase 3 / Phase 4 wasn't run, or your current shell hasn't sourced
`$HOME/.cargo/env` / `/etc/profile.d/go.sh`. Open a new shell or
`source ~/.bashrc`.

### `permission denied while trying to connect to the Docker daemon socket`
Same root cause as the first item — group not active. `newgrp docker` or
re-login.

### Docker didn't auto-start after reboot
Confirm both units are enabled:

```bash
systemctl is-enabled docker containerd
# both must print "enabled"
```

If not, re-run **Phase 1 step 6**.
