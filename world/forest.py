"""Harvestable trees, grouped into groves that each render as one batched mesh."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from panda3d.core import NodePath

from core.meshgen import MeshBuilder, shade

TREE_TIMBER = 48


@dataclass(eq=False)
class Tree:
    """A single tree: occupies one pathing cell and holds timber."""

    is_tree = True
    x: float
    z: float
    y: float
    cell: int
    grove: int
    kind: int
    scale: float
    yaw: float
    timber: int = TREE_TIMBER
    alive: bool = True
    choppers: int = 0
    shake: float = 0.0

    @property
    def radius(self) -> float:
        return 0.9


@dataclass(eq=False)
class Grove:
    gid: int
    trees: list[Tree] = field(default_factory=list)
    node: NodePath | None = None
    dirty: bool = False


def _pine(palette: str, variant: int) -> MeshBuilder:
    mb = MeshBuilder()
    if palette == "ash":
        bark = (0.26, 0.21, 0.18, 1)
        greens = [(0.20, 0.27, 0.20, 1), (0.24, 0.30, 0.22, 1), (0.18, 0.23, 0.19, 1)]
    else:
        bark = (0.36, 0.25, 0.16, 1)
        greens = [(0.14, 0.33, 0.17, 1), (0.18, 0.39, 0.19, 1), (0.12, 0.29, 0.16, 1)]
    g = greens[variant % 3]
    mb.cylinder((0, 0, 0), 0.22, 1.4, bark, radius_top=0.16, segments=5)
    for i, (y, r, h) in enumerate(((1.0, 1.35, 1.9), (2.0, 1.05, 1.7), (2.9, 0.72, 1.5))):
        mb.cone((0, y, 0), r, h, shade(g, 1.0 + 0.08 * i), segments=7, jitter=0.06)
    return mb


def _broadleaf(palette: str, variant: int) -> MeshBuilder:
    mb = MeshBuilder()
    bark = (0.38, 0.28, 0.19, 1)
    leaves = [(0.25, 0.45, 0.19, 1), (0.32, 0.5, 0.2, 1), (0.36, 0.44, 0.17, 1)][variant % 3]
    mb.cylinder((0, 0, 0), 0.26, 1.9, bark, radius_top=0.18, segments=5)
    mb.beam((0, 1.5, 0), (0.6, 2.3, 0.2), 0.09, bark, segments=4)
    mb.sphere((0, 2.6, 0), (1.35, 1.1, 1.3), leaves, detail=1, noise=0.18, seed=variant, jitter=0.07)
    mb.sphere((0.55, 3.15, 0.25), (0.8, 0.7, 0.8), shade(leaves, 1.12), detail=0, noise=0.15, seed=variant + 5)
    mb.sphere((-0.5, 2.3, -0.35), (0.85, 0.7, 0.8), shade(leaves, 0.9), detail=0, noise=0.15, seed=variant + 9)
    return mb


def _deadwood(palette: str, variant: int) -> MeshBuilder:
    """Gnarled dark tree for the ash palette (still full of timber)."""
    mb = MeshBuilder()
    bark = (0.24, 0.2, 0.18, 1)
    mb.cylinder((0, 0, 0), 0.3, 2.4, bark, radius_top=0.2, segments=6)
    rng = random.Random(variant)
    for k in range(4):
        a = k * 1.57 + rng.random() * 0.6
        y0 = 1.4 + k * 0.3
        tip = (math.cos(a) * 1.3, y0 + 1.2 + rng.random() * 0.5, math.sin(a) * 1.3)
        mb.beam((0, y0, 0), tip, 0.1, bark, segments=4, radius_b=0.04)
        mb.sphere(tip, (0.55, 0.42, 0.55), (0.28, 0.27, 0.2, 1), detail=0, noise=0.2, seed=variant + k)
    mb.sphere((0, 3.0, 0), (0.9, 0.6, 0.9), (0.3, 0.28, 0.21, 1), detail=0, noise=0.25, seed=variant + 11)
    return mb


class Forest:
    """All trees of a map. Depleted trees disappear and their grove mesh is rebuilt."""

    def __init__(self, parent: NodePath, terrain, grid, palette: str) -> None:
        self.root = parent.attachNewNode("forest")
        self.terrain = terrain
        self.grid = grid
        self.palette = palette
        self.groves: list[Grove] = []
        self.trees: list[Tree] = []
        self.by_cell: dict[int, Tree] = {}
        self._protos: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def _proto(self, kind: int) -> tuple[np.ndarray, np.ndarray]:
        p = self._protos.get(kind)
        if p is None:
            variant = kind % 3
            if self.palette == "ash":
                mb = _deadwood(self.palette, variant) if kind >= 3 else _pine(self.palette, variant)
            else:
                mb = _broadleaf(self.palette, variant) if kind >= 3 else _pine(self.palette, variant)
            p = mb.arrays()
            self._protos[kind] = p
        return p

    def plant(self, groves: list[list[float]], avoid: list[tuple[float, float, float]], seed: int) -> None:
        """Scatter trees in each grove circle, skipping blocked cells and ``avoid`` circles (x, z, r)."""
        rng = random.Random(seed)
        g = self.grid
        for gid, (cx, cz, r) in enumerate(groves):
            grove = Grove(gid)
            self.groves.append(grove)
            i0, j0 = g.cell_xy(cx - r, cz - r)
            i1, j1 = g.cell_xy(cx + r, cz + r)
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    c = j * g.w + i
                    x, z = g.center(c)
                    d = math.hypot(x - cx, z - cz)
                    edge = d / max(r, 1.0)
                    if edge > 1.0 or rng.random() < (0.12 + 0.45 * edge ** 3):
                        continue
                    if not g.walk[c] or c in self.by_cell:
                        continue
                    if g.slope[j, i] > 0.75:
                        continue
                    if any(math.hypot(x - ax, z - az) < ar for ax, az, ar in avoid):
                        continue
                    jx = x + (rng.random() - 0.5) * 0.7
                    jz = z + (rng.random() - 0.5) * 0.7
                    kind = rng.randrange(6) if rng.random() < 0.55 else rng.randrange(3)
                    t = Tree(jx, jz, self.terrain.height(jx, jz), c, gid, kind, 0.85 + rng.random() * 0.35, rng.random() * 360)
                    grove.trees.append(t)
                    self.trees.append(t)
                    self.by_cell[c] = t
        for t in self.trees:
            ti, tj = t.cell % g.w, t.cell // g.w
            g.block_rect(ti, tj, 1, 1, 1)
        for grove in self.groves:
            self._build(grove)

    def _build(self, grove: Grove) -> None:
        if grove.node is not None:
            grove.node.removeNode()
            grove.node = None
        live = [t for t in grove.trees if t.alive]
        if not live:
            return
        tris_l, cols_l = [], []
        for t in live:
            tris, cols = self._proto(t.kind)
            a = math.radians(t.yaw)
            ca, sa = math.cos(a), math.sin(a)
            rot = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]], np.float32)
            tris_l.append(tris @ rot.T * t.scale + np.array([t.x, t.y - 0.1, t.z], np.float32))
            cols_l.append(cols)
        mb = MeshBuilder()
        mb.add_tris(np.concatenate(tris_l), np.concatenate(cols_l))
        grove.node = mb.build(f"grove_{grove.gid}")
        grove.node.reparentTo(self.root)
        grove.dirty = False

    # ------------------------------------------------------------------ queries
    def nearest(self, x: float, z: float, max_dist: float = 40.0, exclude: Any = None) -> Tree | None:
        best, bd = None, max_dist * max_dist
        for t in self.trees:
            if not t.alive or t is exclude:
                continue
            d = (t.x - x) ** 2 + (t.z - z) ** 2
            if d < bd:
                best, bd = t, d
        return best

    def tree_at(self, x: float, z: float, radius: float = 1.4) -> Tree | None:
        best, bd = None, radius * radius
        for t in self.trees:
            if t.alive:
                d = (t.x - x) ** 2 + (t.z - z) ** 2
                if d < bd:
                    best, bd = t, d
        return best

    def harvest(self, tree: Tree, amount: int) -> int:
        """Take timber from a tree; removes it (and unblocks its cell) when empty."""
        if not tree.alive:
            return 0
        got = min(amount, tree.timber)
        tree.timber -= got
        if tree.timber <= 0:
            tree.alive = False
            self.by_cell.pop(tree.cell, None)
            g = self.grid
            g.block_rect(tree.cell % g.w, tree.cell // g.w, 1, 1, -1)
            self.groves[tree.grove].dirty = True
        return got

    def update(self) -> None:
        for grove in self.groves:
            if grove.dirty:
                self._build(grove)

    def alive_count(self) -> int:
        return sum(1 for t in self.trees if t.alive)
