"""Allow `python -m cortex` to dispatch the CLI.

Equivalent to `atulya-cortex` once the package is installed; useful from a
checkout (`python -m cortex setup`) and from `scripts/install.sh` when the
console-script symlink hasn't been resolved yet.
"""

from __future__ import annotations

from cortex.cli import main_console

if __name__ == "__main__":
    main_console()
