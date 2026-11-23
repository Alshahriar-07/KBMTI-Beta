"""`python -m app` starts the local backend."""

from __future__ import annotations

import sys

import uvicorn

from app.core.config import get_settings
from app.launch_guard import LaunchDenied, preflight


def main() -> None:
    try:
        preflight()
    except LaunchDenied as exc:
        print(f"KBMTI backend cannot start: {exc.message}", file=sys.stderr)
        raise SystemExit(3) from exc
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
