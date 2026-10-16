#!/usr/bin/env python
"""Stitch the screenshot script's frames into the README's demo GIF.

    make_gif.py FRAMES_DIR OUT.gif

Frames are shown in filename order; each holds for 2.2 seconds.
"""

import sys
from pathlib import Path

from PIL import Image

frames_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
frames = [Image.open(p).convert("RGB").resize((1200, 750), Image.LANCZOS) for p in sorted(frames_dir.glob("*.png"))]
if not frames:
    sys.exit(f"no frames in {frames_dir}")
palette = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f in frames]
palette[0].save(out, save_all=True, append_images=palette[1:], duration=2200, loop=0, optimize=True)
print(f"{out} — {len(frames)} frames, {out.stat().st_size // 1024} KB")
