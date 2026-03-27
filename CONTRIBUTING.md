# Contributing to Atulya

Thank you for your interest in Atulya! We welcome all contributors — whether you’re reporting an issue, proposing a feature, or opening a pull request. This guide will help you get started.

---

## Quick Start for Contributors

### 1. Fork & Clone the Repository

Start by making your own copy of the project:
```bash
git clone git@github.com:eight-atulya/atulya.git
cd atulya
```

### 2. Set Up Your Environment

Copy the example environment file and edit it to add your LLM API keys and any required settings:
```bash
cp .env.example .env
```
Update `.env` as needed.

### 3. Install Dependencies

Install both Python and Node.js dependencies (the latter is managed with npm workspaces):
```bash
# Python dependencies (uses uv for speed)
uv sync --directory atulya-api/

# Node.js dependencies for frontend/CP
npm install
```

---

## Development Workflow

### Run API and Control Plane (recommended)

To develop with a realistic multi-component setup, use:
```bash
./scripts/dev/start.sh
```

**Useful script flags:**
- Start only API:  
  `./scripts/dev/start.sh --api-only`
- Start only Control Plane:  
  `./scripts/dev/start.sh --cp-only`
- Run both plus a background worker:  
  `./scripts/dev/start.sh --with-worker`
- Pick available ports automatically:  
  `./scripts/dev/start.sh --random-port`
- Enable native atulya-brain (Rust):  
  `./scripts/dev/start.sh --with-brain-native`

_Stop all services any time with `Ctrl+C`._

---

### Building with Native Acceleration (Rust Optional)

If you want to speed up the brain module with Rust, you can build and link natively:

```bash
./scripts/dev/build-brain.sh
export ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH=/absolute/path/to/libatulya_brain.dylib
ATULYA_API_BRAIN_ENABLED=true ./scripts/dev/start-api.sh
```
Or have it built automatically at startup:
```bash
ATULYA_API_BRAIN_ENABLED=true ./scripts/dev/start.sh --with-brain-native
```

---

### Run API or Control Plane Independently

API only:
```bash
./scripts/dev/start-api.sh
```

Control Plane only:
```bash
./scripts/dev/start-control-plane.sh
```

---

### Process Lifecycle & Logs

All dev scripts enforce consistent process management, readiness checks, and graceful shutdown. For details:
```bash
cat scripts/dev/PROCESS_LIFECYCLE.md
```

---

### Serve Documentation Locally

To preview or edit the docs in your browser:
```bash
./scripts/dev/start-docs.sh
```

---

### Running Tests

To run all backend tests:
```bash
cd atulya-api
uv run pytest tests/
```

---

### Code Formatting & Style

- **Python:** We use [Ruff](https://docs.astral.sh/ruff/) for formatting, linting, and typing.
- **TypeScript:** We use ESLint and Prettier.

#### Recommended: Auto-Lint Pre-Commit

Set up pre-commit git hooks so code is linted/formatted automatically:
```bash
./scripts/setup-hooks.sh
```
This will enable all checked-in hooks under `.githooks/` and run Python/TS checks in parallel including:
- `ruff check --fix`, `ruff format`, `ty check` (Python)
- `eslint --fix`, `prettier` (TS)

#### Manual Linting (Anytime)

Run all checks with:
```bash
./scripts/hooks/lint.sh
```
Or run specific Python checks:
```bash
cd atulya-api
uv run ruff check --fix .   # Check & auto-fix Python
uv run ruff format .        # Format Python code
uv run ty check atulya_api  # Type hint checking
```

#### Style Guidelines

- Use type hints in Python wherever possible
- Follow idioms and conventions already in the code
- Write focused, descriptive function and variable names

---

## Making Pull Requests (PRs)

1. Branch off of `main`.
2. Make your changes in a new feature branch.
3. Run all tests before asking for review.
4. Open a Pull Request and clearly explain your changes and why they're needed.

---

## Release Process

We use a unified release script to version, build, and publish all modules:

- Bumps version numbers
- **Regenerates OpenAPI specs and client SDKs** (Python, TS, Rust)
- Updates docs, git tags, pushes and triggers CI/CD pipelines

To cut a release:
```bash
./scripts/release.sh <version>
# For example
./scripts/release.sh 0.5.0
```

For the `v0.8.0` production baseline, where versions are already set and you only want to validate and tag the repo:
```bash
./scripts/release-preflight-v0800.sh 0.8.0
./scripts/tag-release.sh 0.8.0
# Or push the tag immediately:
./scripts/tag-release.sh 0.8.0 --push
```

**Notes for contributors:**
- During development, version changes in `__init__.py` do *not* automatically require client regeneration.
- SDK clients are refreshed only during actual releases.
- Avoid running `./scripts/generate-clients.sh` manually unless working on the codegen itself.
- The client reflects the latest released API version.
- The `v0.8.0` preflight intentionally allows the two current `ty` blockers in `atulya_api/main.py` and `atulya_api/api/http.py`, but fails on any new unexpected diagnostics.

---

## Reporting Bugs or Suggestions

Please open an issue on GitHub with:
- A clear description of the problem or suggestion
- Steps to reproduce any errors
- What you expected to happen vs what happened
- Relevant environment info (OS, Python version, etc.)

---

## Need Help or Have Questions?

Open a GitHub discussion or contact the maintainers. We're excited to have you in our community!
