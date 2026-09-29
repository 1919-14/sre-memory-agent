#!/usr/bin/env python
"""Convert captured dashboard screenshots into WebP for the landing page.

    venv/Scripts/python.exe scripts/optimize_screenshots.py web/.screenshots-raw web/public/screenshots

`web/scripts/capture-screenshots.mjs` writes PNGs (that is all Chrome's screenshot command
produces). A dashboard is flat, opaque colour and text, which WebP stores at a small fraction of
the size, and the landing page loads six of these — so the conversion is part of the pipeline
rather than an afterthought.

The conversion is lossless in geometry: only the width is capped, preserving aspect ratio, and
nothing is cropped here (the landing page frames the images with CSS).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def human(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="directory of captured .png files")
    parser.add_argument("target", type=Path, help="directory to write .webp files into")
    parser.add_argument("--width", type=int, default=1440, help="cap the width in pixels")
    parser.add_argument("--quality", type=int, default=82, help="WebP quality (1-100)")
    parser.add_argument(
        "--rename",
        action="append",
        default=[],
        metavar="FROM=TO",
        help="name the output after the screen it shows instead of the capture's file name",
    )
    args = parser.parse_args()

    renames = {}
    for entry in args.rename:
        if "=" not in entry:
            print(f"--rename expects FROM=TO, got {entry!r}", file=sys.stderr)
            return 1
        source_name, target_name = entry.split("=", 1)
        renames[source_name] = target_name

    if not args.source.is_dir():
        print(f"no such directory: {args.source}", file=sys.stderr)
        return 1

    sources = sorted(args.source.glob("*.png"))
    if not sources:
        print(f"no .png files in {args.source}", file=sys.stderr)
        return 1

    try:
        from PIL import Image
    except ImportError:
        print("Pillow is required: venv/Scripts/python.exe -m pip install pillow", file=sys.stderr)
        return 1

    args.target.mkdir(parents=True, exist_ok=True)
    before = after = 0

    for path in sources:
        with Image.open(path) as image:
            # WebP keeps alpha, but these captures are fully opaque; dropping the channel is
            # free and removes per-pixel work from the encoder.
            frame = image.convert("RGB")
            if frame.width > args.width:
                height = round(frame.height * (args.width / frame.width))
                frame = frame.resize((args.width, height), Image.LANCZOS)

            out = args.target / f"{renames.get(path.stem, path.stem)}.webp"
            frame.save(out, "WEBP", quality=args.quality, method=6)
            frame.close()

        source_bytes = path.stat().st_size
        target_bytes = out.stat().st_size
        before += source_bytes
        after += target_bytes
        # ASCII only: this prints to a cp1252 console on Windows as well as to a POSIX one.
        print(f"{path.name:<18} {human(source_bytes):>8}  ->  {out.name:<24} {human(target_bytes):>8}")

    print(f"\n{len(sources)} image(s): {human(before)} -> {human(after)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
