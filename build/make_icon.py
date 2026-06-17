#!/usr/bin/env python3
"""
Generate the EXO app icon from build/exo_logo.png.

Outputs:
  build/icon.png   (1024x1024 master)
  build/icon.ico   (Windows, multi-size)
The mac build script turns icon.png into icon.icns via iconutil.

Requires Pillow:  pip install pillow
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

OUT = Path(__file__).parent
SOURCE = OUT / "exo_logo.png"


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing logo source: {SOURCE}")
    img = Image.open(SOURCE).convert("RGBA")
    # Square master at 1024 for crisp icons across platforms.
    master = img.resize((1024, 1024), Image.LANCZOS)
    master.save(OUT / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    master.save(OUT / "icon.ico", sizes=[(s, s) for s in sizes])
    print(f"wrote {OUT/'icon.png'} and {OUT/'icon.ico'} from {SOURCE.name}")


if __name__ == "__main__":
    main()
