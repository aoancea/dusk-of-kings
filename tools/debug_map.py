"""Developer tool: render height/walkability images of the maps and time some path searches.

    python tools/debug_map.py            -> writes screenshots/debug_<map>.png
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from core import data
from settings import SCREENSHOT_DIR
from world.pathing import PathGrid
from world.terrain import Terrain


def render(map_id: str) -> None:
    mdef = data.maps()[map_id]
    t0 = time.perf_counter()
    ter = Terrain(mdef)
    t1 = time.perf_counter()
    grid = PathGrid(ter)
    t2 = time.perf_counter()
    print(f"{map_id}: terrain {1000 * (t1 - t0):.0f} ms, grid {1000 * (t2 - t1):.0f} ms, "
          f"h range {ter.h.min():.2f}..{ter.h.max():.2f}, walkable {sum(grid.walk)} / {grid.w ** 2}")
    w = grid.w
    hn = (ter.h[:-1:2, :-1:2] - ter.h.min()) / (ter.h.max() - ter.h.min())
    img = np.zeros((w, w, 3), np.float32)
    img[..., 0] = hn
    img[..., 1] = hn
    img[..., 2] = hn
    blocked = np.frombuffer(bytes(grid.walk), np.uint8).reshape(w, w) == 0
    img[blocked] = img[blocked] * 0.4 + np.array([0.6, 0.1, 0.1]) * 0.6
    img[grid.water] = img[grid.water] * 0.5 + np.array([0.1, 0.3, 0.8]) * 0.5
    starts = mdef["starts"]
    t3 = time.perf_counter()
    a, b = starts[0]["pos"], starts[1]["pos"]
    path = grid.find_path(a[0] + 10, a[1] + 10, b[0] - 10, b[1] - 10)
    t4 = time.perf_counter()
    print(f"  base->base path: {len(path)} waypoints in {1000 * (t4 - t3):.1f} ms")
    pts = [(a[0] + 10, a[1] + 10)] + path
    for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
        for k in range(60):
            x = x0 + (x1 - x0) * k / 60
            z = z0 + (z1 - z0) * k / 60
            c = grid.cell_of(x, z)
            img[c // w, c % w] = (1.0, 0.9, 0.1)
    for m in mdef["mines"]:
        c = grid.cell_of(*m["pos"])
        img[c // w, c % w] = (1.0, 0.8, 0.0)
    for s in starts:
        c = grid.cell_of(*s["pos"])
        img[c // w, c % w] = (0.2, 1.0, 0.2)
    out = (np.clip(img[::-1], 0, 1) * 255).astype(np.uint8)
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    Image.fromarray(out).resize((w * 5, w * 5), Image.NEAREST).save(SCREENSHOT_DIR / f"debug_{map_id}.png")


if __name__ == "__main__":
    for mid in data.maps():
        render(mid)
