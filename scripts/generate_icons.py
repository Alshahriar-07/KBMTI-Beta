"""Generate the KBMTI application icons with the Python standard library only.

Run from the repository root:
    python scripts/generate_icons.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parents[1] / "apps" / "desktop" / "src-tauri" / "icons"


def _pixel(x: int, y: int, size: int) -> tuple[int, int, int, int]:
    cx = cy = (size - 1) / 2
    nx = (x - cx) / (size / 2)
    ny = (y - cy) / (size / 2)
    radius = math.hypot(nx, ny)

    # Rounded-square mask with soft edges.
    if max(abs(nx), abs(ny)) > 0.96:
        return (0, 0, 0, 0)

    # Dark graphite background with a subtle vertical gradient.
    shade = 0.55 + 0.45 * (1.0 - y / max(1, size - 1))
    base = (int(5 * shade) + 3, int(14 * shade) + 4, int(26 * shade) + 6, 255)

    # Emerald ring.
    if 0.62 < radius < 0.78:
        glow = 1.0 - min(1.0, abs(radius - 0.70) / 0.08)
        green = int(120 + 100 * glow)
        return (int(18 + 20 * glow), green, int(110 + 50 * glow), 255)

    # Stylised "K": vertical bar plus two diagonals, clipped to the inner circle.
    if radius < 0.56:
        bar = abs(nx + 0.20) < 0.075 and abs(ny) < 0.42
        upper = abs((ny + 0.42) - (nx + 0.20)) < 0.10 and -0.15 < nx < 0.38 and -0.55 < ny < 0.05
        lower = abs((ny - 0.42) - (nx + 0.20)) < 0.10 and -0.15 < nx < 0.38 and -0.05 < ny < 0.55
        if bar or upper or lower:
            return (232, 252, 240, 255)

    return base


def _png(size: int) -> bytes:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(_pixel(x, y, size))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _ico(images: list[tuple[int, bytes]]) -> bytes:
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = bytearray()
    for size, payload in images:
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                0 if size >= 256 else size,
                0 if size >= 256 else size,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        offset += len(payload)
    return header + bytes(entries) + b"".join(payload for _, payload in images)


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    sizes = {16: "icon-16.png", 32: "32x32.png", 128: "128x128.png", 256: "128x128@2x.png"}
    rendered: dict[int, bytes] = {}
    for size, name in sizes.items():
        payload = _png(size)
        rendered[size] = payload
        (ICON_DIR / name).write_bytes(payload)
    (ICON_DIR / "icon.png").write_bytes(rendered[256])
    (ICON_DIR / "icon.ico").write_bytes(_ico([(16, rendered[16]), (32, rendered[32]), (256, rendered[256])]))
    print(f"Generated {len(sizes) + 2} icon files in {ICON_DIR}")


if __name__ == "__main__":
    main()
