# First-time setup (Atulya)

Run these from the **`atulya/`** repo root (where `package.json` lives).

## 1. Environment

```bash
cp .env.example .env
```

Edit `.env` and point the LLM at **Ollama**, **LM Studio**, or **OpenAI** (see the comments in `.env.example`). Defaults are fine to get running—swap providers later if you want.

## 2. Node.js and frontend deps

The Control Plane (Next.js) needs **Node.js ≥ 20.9**. Check:

```bash
node -v   # should be v20.9.0 or newer (v22 LTS is fine)
```

If `node` is missing or older, install a current Node **20+** build—**do not** rely on `apt install npm` alone on Debian/Ubuntu; it often ships Node 18.

**Linux — [nvm](https://github.com/nvm-sh/nvm) (recommended)**

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
# restart the shell, then:
nvm install 22
nvm use 22
```

**Linux — [NodeSource](https://github.com/nodesource/distributions)** (system-wide `.deb`)

Follow their README for your distro to install **Node 22.x**, then `node -v` again.

**macOS** (Homebrew)

```bash
brew install node
node -v   # confirm >= v20.9
```

Then install JS dependencies:

```bash
npm install
```

Always run `npm install` **on the machine you develop on**. Do **not** copy `node_modules` from macOS or another PC: tools like Tailwind use **native binaries** (`lightningcss` loads `lightningcss-linux-x64-gnu` on Linux glibc x64, and different packages on macOS/Windows). A tree built on a Mac will not include the Linux `.node` files.

If the Control Plane errors with `Cannot find module'`, wipe and reinstall on this host. This repo uses **npm workspaces**; dependencies are mostly hoisted under `atulya/`, but a workspace can still have its own `atulya-control-plane/node_modules`. Remove **both** so nothing stale or wrong-platform is left:

```bash
rm -rf node_modules atulya-control-plane/node_modules
npm install
```

If you ever installed inside other workspaces, you can clear those too (e.g. `atulya-docs/node_modules`, `atulya-clients/typescript/node_modules`) before `npm install`.

## 3. `uv` (Python toolchain)

Install [uv](https://docs.astral.sh/uv/) from Astral—official docs: [Installation](https://docs.astral.sh/uv/getting-started/installation/).

**macOS and Linux (recommended)**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal (or `source` your shell profile) so `uv` is on your `PATH`, then confirm:

```bash
uv --version
```

## 4. First-time bootstrap (API)

This prepares what the API needs on a fresh machine:

```bash
./scripts/dev/start-api.sh
```

## 5. After setup — run the stack

Next time (and normally), start API + Control Plane (UI) together:

```bash
./scripts/dev/start.sh
```

By default you get:

- **Control Plane (UI):** [http://localhost:9999](http://localhost:9999)
- **API:** [http://localhost:8888](http://localhost:8888) (see `ATULYA_API_PORT` in `.env` if you change it)
