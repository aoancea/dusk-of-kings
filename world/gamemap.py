"""Builds a playable map from maps.json: terrain mesh, pathing grid, water, trees, gold mines, decor."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

import numpy as np
from panda3d.core import NodePath

from core import data
from core.meshgen import MeshBuilder, make_geom_node, shade
from core.textures import np_to_texture
from core.util import yaw_to
from economy.mine import GoldMine
from settings import SEA_LEVEL
from world.forest import Forest
from world.pathing import PathGrid
from world.terrain import Terrain
from world.water import Water

if TYPE_CHECKING:
    from core.match import Match


class GameMap:
    """Static world of one match."""

    def __init__(self, match: "Match", map_id: str) -> None:
        self.match = match
        self.id = map_id
        self.defn: dict[str, Any] = data.maps()[map_id]
        self.name = self.defn["name"]
        self.palette = self.defn.get("palette", "fen")
        self.terrain = Terrain(self.defn)
        self.grid = PathGrid(self.terrain)
        self.root: NodePath = match.map_root
        self.terrain_node = self.terrain.build_mesh(self.root, self.palette)
        self.water: Water | None = None
        if self.terrain.has_water:
            self._build_water()
        self._build_outer()
        self.starts: list[dict[str, Any]] = self.defn["starts"]
        self.mines: list[GoldMine] = []
        self.forest = Forest(self.root, self.terrain, self.grid, self.palette)

    def populate(self) -> None:
        """Place mines, trees and decor (needs the match's actor roots to exist)."""
        starts = [s["pos"] for s in self.starts]
        for m in self.defn["mines"]:
            mx, mz = m["pos"]
            near = min(starts, key=lambda s: math.hypot(s[0] - mx, s[1] - mz))
            if math.hypot(near[0] - mx, near[1] - mz) < 40:
                facing = yaw_to(near[0] - mx, near[1] - mz)
            else:
                facing = yaw_to(-mx, -mz)
            gx, gz = self.grid.snap_footprint(mx, mz, 3)
            self.mines.append(GoldMine(self.match, gx, gz, int(m["gold"]), facing))
        avoid = [(s[0], s[1], 11.0) for s in starts]
        for mine in self.mines:
            ex, ez = mine.entrance
            avoid.append((mine.x, mine.z, 6.5))
            avoid.append((ex, ez, 4.0))
            for s in starts:
                if math.hypot(s[0] - mine.x, s[1] - mine.z) < 40:
                    # keep the mining lane between mine and town hall clear
                    for k in range(1, 6):
                        t = k / 6
                        avoid.append((mine.x + (s[0] - mine.x) * t, mine.z + (s[1] - mine.z) * t, 5.0))
        self.forest.plant(self.defn.get("groves", []), avoid, self.defn.get("seed", 1))
        self._build_decor(avoid)

    # ------------------------------------------------------------------ water
    def _build_water(self) -> None:
        h = self.terrain.h
        depth = np.clip((SEA_LEVEL - h) / 12.0, 0, 1)
        img = (depth[::-1] * 255).astype(np.uint8)
        tex = np_to_texture(img, "depth", mipmap=False, repeat=False)
        half = self.terrain.half
        self.water = Water(self.root, tex, (-half, -half, self.terrain.size, self.terrain.size),
                           size=self.terrain.size + 8, cells=116)
        self.water.node.setPos(0, SEA_LEVEL, 0)

    def _build_outer(self) -> None:
        """Dark frame around the playable square so the void is never visible."""
        half = self.terrain.half
        far = 900.0
        y = 9.0
        mb = MeshBuilder()
        col = (0.05, 0.05, 0.05, 1)
        for x0, z0, x1, z1 in ((-far, -far, far, -half), (-far, half, far, far), (-far, -half, -half, half), (half, -half, far, half)):
            mb.quad((x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1), col, facing=(0, 1, 0))
        node = mb.build("outer")
        node.reparentTo(self.root)

    # ------------------------------------------------------------------ decor
    def _build_decor(self, avoid: list[tuple[float, float, float]]) -> None:
        dec = self.defn.get("decor", {})
        rng = random.Random(self.defn.get("seed", 1) + 99)
        ter = self.terrain
        grid = self.grid
        mb = MeshBuilder()
        half = ter.half - 10
        rock = (0.48, 0.45, 0.41, 1) if self.palette == "fen" else (0.36, 0.33, 0.31, 1)
        placed = 0
        tries = 0
        while placed < dec.get("rocks", 0) and tries < 4000:
            tries += 1
            x, z = rng.uniform(-half, half), rng.uniform(-half, half)
            if any(math.hypot(x - ax, z - az) < ar for ax, az, ar in avoid):
                continue
            c = grid.cell_of(x, z)
            if c in self.forest.by_cell or grid.water.flat[c]:
                continue
            s = rng.uniform(0.25, 0.8)
            mb.sphere((x, ter.height(x, z) + s * 0.2, z), (s * 1.3, s * 0.8, s), shade(rock, rng.uniform(0.85, 1.15)),
                      detail=0, noise=0.3, seed=rng.randrange(1000))
            placed += 1
        # reeds along the water
        reeds = dec.get("reeds", 0)
        if reeds:
            cand = np.argwhere((ter.h > 0.02) & (ter.h < 0.4))
            if len(cand):
                for k in rng.sample(range(len(cand)), min(reeds, len(cand))):
                    iz, ix = cand[k]
                    x, z = float(ter.X[iz, ix]), float(ter.Z[iz, ix])
                    if abs(x) > half or abs(z) > half:
                        continue
                    y = ter.height(x, z)
                    for j in range(4):
                        a = rng.random() * math.tau
                        ox, oz = math.cos(a) * 0.3, math.sin(a) * 0.3
                        top = (x + ox * 2, y + rng.uniform(0.8, 1.5), z + oz * 2)
                        mb.beam((x + ox, y - 0.1, z + oz), top, 0.035, (0.45, 0.5, 0.25, 1), jitter=0.1)
        # ruins
        stone = (0.62, 0.6, 0.55, 1) if self.palette == "fen" else (0.45, 0.42, 0.4, 1)
        for rx, rz in dec.get("ruins", []):
            for k in range(5):
                a = k / 5 * math.tau + rng.random() * 0.4
                x, z = rx + math.cos(a) * 3.0, rz + math.sin(a) * 3.0
                y = ter.height(x, z)
                hgt = rng.uniform(0.8, 3.2)
                mb.cylinder((x, y - 0.2, z), 0.35, hgt, shade(stone, rng.uniform(0.85, 1.1)), segments=6)
                if hgt > 2.5:
                    mb.box((x, y + hgt - 0.1, z), (0.9, 0.25, 0.9), shade(stone, 0.9))
            mb.box((rx, ter.height(rx, rz) + 0.1, rz), (2.6, 0.3, 1.2), shade(stone, 0.8), rot=(0, rng.random() * 90, 6))
        if not mb.is_empty():
            mb.build("decor").reparentTo(self.root)

    # ------------------------------------------------------------------ helpers
    def start_info(self, idx: int) -> dict[str, Any]:
        return self.starts[idx % len(self.starts)]

    def mine_near(self, x: float, z: float, max_d: float = 30.0) -> GoldMine | None:
        best, bd = None, max_d
        for m in self.mines:
            if m.alive and not m.depleted:
                d = math.hypot(m.x - x, m.z - z)
                if d < bd:
                    best, bd = m, d
        return best

    def update(self, dt: float) -> None:
        self.forest.update()
