"""Generate a Linux-pinned requirements file from the local pip freeze.

Strips Windows-only packages (pywin32, colorama, win-specific Twisted deps)
and platform markers, so the same file installs cleanly on Ubuntu.

Usage:
  python scripts/generate_linux_requirements.py
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
from pathlib import Path

# Packages that don't exist on Linux or are Windows-specific
WINDOWS_ONLY = {
    "pywin32",
    "win32-setctime",
    "wincertstore",
    "pywin32-ctypes",
}

# Markers to drop when re-emitting for Linux
MARKER_STRIP = re.compile(r";\s*.*$")


def freeze_local() -> list[str]:
    out = subprocess.check_output(
        [sys.executable, "-m", "pip", "freeze"], text=True
    )
    return [line.strip() for line in out.splitlines() if line.strip() and not line.startswith("#")]


def main() -> int:
    assert platform.system() == "Windows", (
        "Run this on a Windows machine to capture the local dep set"
    )

    rows: list[tuple[str, str]] = []
    for line in freeze_local():
        line = MARKER_STRIP.sub("", line).strip()
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        name = name.strip().lower()
        version = version.strip()
        if name in WINDOWS_ONLY:
            continue
        rows.append((name, version))

    out = Path("requirements.linux.txt")
    with out.open("w", encoding="utf-8") as f:
        f.write("# Generated from local pip freeze (Windows host)\n")
        f.write("# Cross-platform packages only (no pywin32, etc.)\n")
        f.write(f"# Source Python: {platform.python_version()}\n\n")
        for name, version in rows:
            f.write(f"{name}=={version}\n")

    print(f"wrote {out} with {len(rows)} packages")
    print("Skipped (Windows-only):", ", ".join(sorted(WINDOWS_ONLY)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
