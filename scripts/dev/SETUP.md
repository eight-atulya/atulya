# First-time setup (Atulya)

Run these from the **`atulya/`** repo root (where `package.json` lives).

## 1. Environment

```bash
cp .env.example .env
```

Edit `.env` and point the LLM at **Ollama**, **LM Studio**, or **OpenAI** (see the comments in `.env.example`). Defaults are fine to get running—swap providers later if you want.

## 2. Node.js and frontend deps

**Linux (Debian/Ubuntu)**

```bash
sudo apt update
sudo apt install -y npm
```

**macOS** (Homebrew)

```bash
brew install node
```

Then install JS dependencies:

```bash
npm install
```

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
