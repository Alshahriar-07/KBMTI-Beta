"""Public entry point: redirect every direct Python launch to the official EXE.

The application runtime lives in :mod:`kbmti.runtime` and requires a signed
backend launch ticket. ``python -m kbmti`` never initializes Qt, the backend or
the frontend; it only starts ``KBMTI-RAW-TEST.exe`` and exits with its status.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OFFICIAL_LAUNCHER_NAME = "KBMTI-RAW-TEST.exe"


def official_launcher() -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).with_name(OFFICIAL_LAUNCHER_NAME))
    candidates.extend(
        (
            Path(__file__).resolve().parents[1] / OFFICIAL_LAUNCHER_NAME,
            Path.cwd() / OFFICIAL_LAUNCHER_NAME,
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def main(argv: list[str] | None = None) -> int:
    launcher = official_launcher()
    if launcher is None:
        print(
            "KBMTI must be started with the official launcher "
            f"'{OFFICIAL_LAUNCHER_NAME}'. Direct Python execution is not supported.",
            file=sys.stderr,
        )
        return 3
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        completed = subprocess.run([str(launcher), *arguments], check=False)
    except OSError as exc:
        print(f"Could not start {launcher}: {exc}", file=sys.stderr)
        return 3
    return int(completed.returncode)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
