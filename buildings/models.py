"""Procedural building models for both factions.

Alliance: pale stone, slate-blue roofs, timber frames, team-coloured banners.
Host: dark stone, rusted iron, hides, bone and spikes, fires.
Each model has a solid mesh and an optional glowing mesh (fires, forges, magic).
"""
from __future__ import annotations

import math
import random
from typing import Any, Callable

from panda3d.core import NodePath

from core.meshgen import MeshBuilder, shade
from settings import CELL

Col = tuple[float, float, float, float]

# Alliance palette
STONE = (0.72, 0.70, 0.66, 1)
STONE_D = (0.58, 0.56, 0.53, 1)
SLATE = (0.30, 0.36, 0.52, 1)
PLASTER = (0.86, 0.82, 0.72, 1)
TIMBER = (0.42, 0.29, 0.17, 1)
THATCH = (0.55, 0.43, 0.25, 1)
GOLDEN = (0.95, 0.78, 0.3, 1)
# Host palette
DSTONE = (0.30, 0.28, 0.29, 1)
DSTONE_L = (0.40, 0.37, 0.37, 1)
IRON = (0.36, 0.26, 0.22, 1)
DWOOD = (0.27, 0.19, 0.14, 1)
HIDE = (0.46, 0.36, 0.27, 1)
BONE = (0.86, 0.81, 0.68, 1)
FIRE = (1.0, 0.55, 0.12, 1)
EMBER = (1.0, 0.3, 0.05, 1)
DARK = (0.06, 0.05, 0.05, 1)

_cache: dict[tuple, tuple[NodePath, NodePath | None]] = {}


# ============================================================================ kit
def gable_roof(mb: MeshBuilder, cx: float, cz: float, w: float, d: float, y0: float, h: float, col: Col,
               along_z: bool = True, over: float = 0.35) -> None:
    """Pitched roof over a w x d rectangle; ridge runs along z (or x)."""
    hw, hd = w / 2 + over, d / 2 + over
    if along_z:
        a, b = (cx - hw, y0, cz - hd), (cx - hw, y0, cz + hd)
        c, e = (cx + hw, y0, cz + hd), (cx + hw, y0, cz - hd)
        r0, r1 = (cx, y0 + h, cz - hd), (cx, y0 + h, cz + hd)
        mb.quad(a, b, r1, r0, col, facing=(-1, 1, 0), double=False)
        mb.quad(e, r0, r1, c, shade(col, 0.88), facing=(1, 1, 0))
        mb.triangle((cx - w / 2, y0, cz - d / 2), (cx + w / 2, y0, cz - d / 2), (cx, y0 + h * (w / 2) / hw, cz - d / 2),
                    shade(col, 0.7), facing=(0, 0, -1))
        mb.triangle((cx - w / 2, y0, cz + d / 2), (cx + w / 2, y0, cz + d / 2), (cx, y0 + h * (w / 2) / hw, cz + d / 2),
                    shade(col, 0.7), facing=(0, 0, 1))
        mb.box((cx, y0 + h, cz), (0.18, 0.12, d + over * 2), shade(col, 0.7))
    else:
        a, b = (cx - hw, y0, cz - hd), (cx + hw, y0, cz - hd)
        c, e = (cx + hw, y0, cz + hd), (cx - hw, y0, cz + hd)
        r0, r1 = (cx - hw, y0 + h, cz), (cx + hw, y0 + h, cz)
        mb.quad(a, b, r1, r0, col, facing=(0, 1, -1))
        mb.quad(e, r0, r1, c, shade(col, 0.88), facing=(0, 1, 1))
        mb.triangle((cx - w / 2, y0, cz - d / 2), (cx - w / 2, y0, cz + d / 2), (cx - w / 2, y0 + h * (d / 2) / hd, cz),
                    shade(col, 0.7), facing=(-1, 0, 0))
        mb.triangle((cx + w / 2, y0, cz - d / 2), (cx + w / 2, y0, cz + d / 2), (cx + w / 2, y0 + h * (d / 2) / hd, cz),
                    shade(col, 0.7), facing=(1, 0, 0))
        mb.box((cx, y0 + h, cz), (w + over * 2, 0.12, 0.18), shade(col, 0.7))


def crenels(mb: MeshBuilder, cx: float, cz: float, w: float, d: float, y: float, col: Col, step: float = 0.9) -> None:
    for side in range(4):
        length = w if side < 2 else d
        n = max(2, int(length / step))
        for k in range(n):
            t = (k + 0.5) / n - 0.5
            if side == 0:
                p = (cx + t * w, y, cz - d / 2)
            elif side == 1:
                p = (cx + t * w, y, cz + d / 2)
            elif side == 2:
                p = (cx - w / 2, y, cz + t * d)
            else:
                p = (cx + w / 2, y, cz + t * d)
            if k % 2 == 0:
                mb.box(p, (0.45, 0.5, 0.45), col)


def round_tower(mb: MeshBuilder, x: float, z: float, r: float, h: float, wall: Col, roof: Col | None,
                roof_h: float = 2.2, segments: int = 8, y0: float = 0.0) -> None:
    mb.cylinder((x, y0, z), r, h, wall, radius_top=r * 0.92, segments=segments)
    if roof is not None:
        mb.cone((x, y0 + h, z), r * 1.25, roof_h, roof, segments=segments)
    else:
        for k in range(segments):
            a = k / segments * math.tau
            if k % 2 == 0:
                mb.box((x + math.cos(a) * r * 0.9, y0 + h + 0.25, z + math.sin(a) * r * 0.9), (0.4, 0.5, 0.4), wall)


def banner(mb: MeshBuilder, x: float, y: float, z: float, team: Col, h: float = 1.6, pole: float = 2.2) -> None:
    mb.beam((x, y, z), (x, y + pole, z), 0.05, TIMBER, segments=4)
    mb.quad((x, y + pole - 0.1, z), (x + 0.9, y + pole - 0.25, z), (x + 0.9, y + pole - 0.1 - h, z), (x, y + pole - 0.1 - h * 0.9, z),
            team, facing=(0, 0, 1), double=True)


def wall_banner(mb: MeshBuilder, x: float, y: float, z: float, team: Col, facing_z: float = 1.0, w: float = 0.9,
                h: float = 1.7) -> None:
    zz = z + 0.05 * facing_z
    mb.quad((x - w / 2, y, zz), (x + w / 2, y, zz), (x + w / 2, y - h, zz), (x - w / 2, y - h * 0.85, zz),
            team, facing=(0, 0, facing_z), double=True)
    mb.box((x, y - h * 0.45, zz + 0.02 * facing_z), (w * 0.35, w * 0.35, 0.03), GOLDEN, rot=(0, 0, 45))


def spikes(mb: MeshBuilder, cx: float, cz: float, radius: float, n: int, y: float, h: float, col: Col,
           seed: int = 0, tilt: float = 18.0) -> None:
    rng = random.Random(seed)
    for k in range(n):
        a = k / n * math.tau
        x, z = cx + math.cos(a) * radius, cz + math.sin(a) * radius
        hh = h * (0.75 + rng.random() * 0.5)
        mb.cone((x, y, z), 0.16, hh, col, segments=4, rot=(math.sin(a) * tilt, 0, -math.cos(a) * tilt))


def palisade_ring(mb: MeshBuilder, cx: float, cz: float, w: float, d: float, h: float, col: Col, gap: float = 2.2,
                  seed: int = 0) -> None:
    rng = random.Random(seed)
    per = 0.42
    for side in range(4):
        length = w if side < 2 else d
        n = int(length / per)
        for k in range(n):
            t = (k + 0.5) / n - 0.5
            if side == 0 and abs(t * length) < gap / 2:
                continue  # gate on the -z (front) side
            if side == 0:
                p = (cx + t * w, 0, cz - d / 2)
            elif side == 1:
                p = (cx + t * w, 0, cz + d / 2)
            elif side == 2:
                p = (cx - w / 2, 0, cz + t * d)
            else:
                p = (cx + w / 2, 0, cz + t * d)
            hh = h * (0.85 + rng.random() * 0.3)
            mb.cylinder(p, 0.2, hh, shade(col, 0.9 + rng.random() * 0.2), segments=4)
            mb.cone((p[0], hh, p[2]), 0.2, 0.45, shade(col, 0.8), segments=4)


def brazier(glow: MeshBuilder, mb: MeshBuilder, x: float, y: float, z: float, s: float = 1.0) -> None:
    mb.cylinder((x, y, z), 0.12 * s, 1.1 * s, IRON, segments=4)
    mb.cylinder((x, y + 1.1 * s, z), 0.35 * s, 0.3 * s, IRON, radius_top=0.45 * s, segments=6)
    glow.cone((x, y + 1.35 * s, z), 0.32 * s, 0.7 * s, FIRE, segments=5)


def fire(glow: MeshBuilder, x: float, y: float, z: float, s: float = 1.0) -> None:
    glow.cone((x, y, z), 0.7 * s, 1.6 * s, FIRE, segments=6)
    glow.cone((x + 0.15 * s, y, z - 0.1 * s), 0.45 * s, 2.2 * s, (1.0, 0.75, 0.25, 1), segments=5)
    glow.cone((x - 0.2 * s, y, z + 0.15 * s), 0.4 * s, 1.3 * s, EMBER, segments=5)


def door(mb: MeshBuilder, x: float, z: float, w: float, h: float, facing: float = -1.0, col: Col = DARK) -> None:
    mb.box((x, h / 2, z + facing * 0.02), (w, h, 0.12), col)
    mb.cylinder((x, h, z + facing * 0.02), w / 2, 0.12, col, segments=8, rot=(90, 0, 0))


# ============================================================================ alliance
def a_keep(mb: MeshBuilder, glow: MeshBuilder, team: Col, castle: bool = False) -> None:
    s = 1.12 if castle else 1.0
    if castle:
        # curtain wall
        for (x0, z0, x1, z1) in ((-4.4, -4.4, 4.4, -4.4), (-4.4, 4.4, 4.4, 4.4), (-4.4, -4.4, -4.4, 4.4), (4.4, -4.4, 4.4, 4.4)):
            mb.beam((x0, 0, z0), (x1, 0, z1), 0.01, STONE_D)
        for (cx, cz, w, d) in ((0, -4.3, 8.8, 0.7), (0, 4.3, 8.8, 0.7), (-4.3, 0, 0.7, 8.8), (4.3, 0, 0.7, 8.8)):
            mb.box((cx, 1.4, cz), (w, 2.8, d), STONE_D)
        crenels(mb, 0, 0, 8.8, 8.8, 3.0, STONE_D)
        door(mb, 0, -4.66, 2.0, 2.4)
    mb.box((0, 2.6 * s, 0.4), (6.0 * s, 5.2 * s, 5.6 * s), STONE)
    mb.box((0, 0.4, 0.4), (6.4 * s, 0.8, 6.0 * s), STONE_D)
    crenels(mb, 0, 0.4, 6.0 * s, 5.6 * s, 5.45 * s, STONE)
    door(mb, 0, 0.4 - 2.8 * s, 1.8, 2.6)
    for x in (-1.8, 1.8):
        mb.box((x * s, 3.9 * s, 0.4 - 2.82 * s), (0.5, 0.9, 0.1), DARK)
    for sx in (-1, 1):
        for sz in (-1, 1):
            round_tower(mb, sx * 3.2 * s, 0.4 + sz * 3.0 * s, 1.1 * s, 6.6 * s, STONE_D, SLATE, 2.4 * s)
    round_tower(mb, 0.8, 1.2, 1.7 * s, 9.5 * s if castle else 8.4, STONE, SLATE, 3.2 * s, segments=10)
    banner(mb, 0.8, 9.5 * s + 3.0 * s if castle else 8.4 + 3.0, 1.2, team, h=1.4, pole=1.6)
    wall_banner(mb, -1.6 * s, 4.8 * s, 0.4 - 2.83 * s, team, -1)
    wall_banner(mb, 1.6 * s, 4.8 * s, 0.4 - 2.83 * s, team, -1)
    glow.box((0, 1.0, 0.4 - 2.86 * s), (1.0, 1.4, 0.05), (1.0, 0.7, 0.3, 1))


def a_house(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.box((0, 0.3, 0), (4.6, 0.6, 3.8), STONE_D)
    mb.box((0, 1.6, 0), (4.2, 2.2, 3.4), PLASTER)
    for x in (-2.05, -0.7, 0.7, 2.05):
        mb.box((x, 1.6, -1.72), (0.18, 2.2, 0.06), TIMBER)
        mb.box((x, 1.6, 1.72), (0.18, 2.2, 0.06), TIMBER)
    mb.box((0, 2.65, -1.72), (4.2, 0.18, 0.06), TIMBER)
    gable_roof(mb, 0, 0, 4.2, 3.4, 2.7, 1.9, THATCH, along_z=False, over=0.4)
    mb.box((1.3, 3.6, 0.6), (0.6, 1.6, 0.6), STONE_D)
    door(mb, -0.9, -1.72, 0.9, 1.5, col=shade(TIMBER, 0.6))
    glow.box((0.9, 1.7, -1.75), (0.6, 0.55, 0.04), (1.0, 0.75, 0.35, 1))
    mb.box((-1.6, 2.3, -1.8), (0.5, 0.6, 0.05), team)


def a_barracks(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.box((0, 1.3, 0.3), (6.6, 2.6, 4.8), STONE)
    mb.box((0, 3.1, 0.3), (6.4, 1.0, 4.6), PLASTER)
    for x in (-3.1, -1.5, 0.0, 1.5, 3.1):
        mb.box((x, 3.1, 0.3 - 2.32), (0.2, 1.0, 0.06), TIMBER)
    gable_roof(mb, 0, 0.3, 6.4, 4.6, 3.6, 2.2, SLATE, along_z=False, over=0.4)
    door(mb, 0, 0.3 - 2.42, 1.8, 2.2)
    wall_banner(mb, -2.2, 3.4, 0.3 - 2.42, team, -1)
    wall_banner(mb, 2.2, 3.4, 0.3 - 2.42, team, -1)
    round_tower(mb, -3.3, 2.6, 0.9, 5.2, STONE_D, SLATE, 1.8)
    # training yard
    for x in (2.4, 3.4):
        mb.cylinder((x, 0, -3.4), 0.1, 1.6, TIMBER, segments=4)
        mb.cylinder((x, 0.7, -3.4), 0.28, 0.7, THATCH, segments=6)
    mb.box((-2.8, 0.7, -3.4), (1.6, 0.1, 0.2), TIMBER)
    for k in range(4):
        mb.beam((-3.4 + k * 0.4, 0.0, -3.5), (-3.4 + k * 0.4, 1.5, -3.3), 0.03, (0.7, 0.7, 0.72, 1))


def a_lumber_mill(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    for x in (-2.0, 2.0):
        for z in (-1.4, 1.6):
            mb.box((x, 1.4, z), (0.3, 2.8, 0.3), TIMBER)
    mb.box((0, 1.4, 1.65), (4.2, 2.8, 0.2), shade(TIMBER, 1.2))
    gable_roof(mb, 0, 0.1, 4.4, 3.4, 2.8, 1.5, THATCH, along_z=False, over=0.3)
    mb.cylinder((0.8, 1.2, 0.2), 0.9, 0.06, (0.75, 0.75, 0.78, 1), segments=12, rot=(90, 0, 0))
    mb.box((0.0, 0.8, 0.2), (2.8, 0.16, 0.9), TIMBER)
    for k in range(5):
        mb.cylinder((-2.6, 0.25 + (k % 3) * 0.42, -2.6 + k * 0.32), 0.22, 2.2, (0.55, 0.38, 0.22, 1),
                    segments=6, rot=(0, 0, 90))
    for k in range(3):
        mb.cylinder((1.2 + k * 0.45, 0.22, -2.4), 0.22, 2.0, (0.5, 0.35, 0.2, 1), segments=6, rot=(90, 0, 0))
    banner(mb, 2.4, 0, -1.6, team)


def a_blacksmith(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.box((0, 1.2, 0.5), (4.2, 2.4, 3.6), STONE_D)
    gable_roof(mb, 0, 0.5, 4.2, 3.6, 2.4, 1.6, SLATE, along_z=True)
    mb.box((1.6, 2.8, 1.6), (0.9, 3.6, 0.9), STONE_D)
    glow.box((1.6, 4.65, 1.6), (0.6, 0.12, 0.6), EMBER)
    mb.box((-0.4, 0.6, -1.9), (2.6, 1.2, 1.2), STONE)
    glow.box((-0.4, 1.25, -1.9), (1.6, 0.1, 0.7), FIRE)
    mb.box((1.6, 0.45, -2.0), (0.7, 0.4, 0.4), (0.3, 0.3, 0.32, 1))
    mb.box((1.6, 0.75, -2.0), (0.9, 0.2, 0.35), (0.35, 0.35, 0.37, 1))
    wall_banner(mb, -1.0, 2.2, 0.5 - 1.82, team, -1)


def a_sanctum(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    white = (0.9, 0.9, 0.88, 1)
    mb.cylinder((0, 0, 0), 2.7, 0.5, STONE_D, segments=12)
    mb.cylinder((0, 0.5, 0), 2.0, 3.0, white, segments=12)
    for k in range(8):
        a = k / 8 * math.tau
        mb.cylinder((math.cos(a) * 2.45, 0.5, math.sin(a) * 2.45), 0.2, 3.2, white, segments=6)
    mb.cylinder((0, 3.6, 0), 2.7, 0.3, white, segments=12)
    mb.sphere((0, 3.9, 0), (2.0, 1.8, 2.0), (0.55, 0.7, 0.95, 1), detail=2)
    mb.cone((0, 5.6, 0), 0.2, 1.2, GOLDEN, segments=6)
    glow.sphere((0, 2.0, -2.02), (0.45, 0.6, 0.1), (0.6, 0.85, 1.0, 1), detail=1)
    glow.sphere((0, 6.9, 0), 0.25, (0.7, 0.9, 1.0, 1), detail=1)
    banner(mb, -2.2, 0.5, -2.2, team)


def a_guard_tower(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.cylinder((0, 0, 0), 1.5, 0.6, STONE_D, segments=8)
    mb.cylinder((0, 0.6, 0), 1.25, 5.6, STONE, radius_top=1.05, segments=8)
    mb.cylinder((0, 6.2, 0), 1.55, 0.35, TIMBER, segments=8)
    for k in range(8):
        a = k / 8 * math.tau
        mb.box((math.cos(a) * 1.45, 6.85, math.sin(a) * 1.45), (0.18, 1.0, 0.18), TIMBER)
    mb.cone((0, 7.35, 0), 1.9, 2.0, SLATE, segments=8)
    mb.box((0, 3.6, -1.2), (0.3, 0.7, 0.1), DARK)
    wall_banner(mb, 0, 5.4, -1.12, team, -1, w=0.7, h=1.4)
    glow.box((0, 6.7, -1.2), (0.5, 0.35, 0.05), (1.0, 0.7, 0.3, 1))


def a_stables(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.box((0, 1.4, 1.2), (6.6, 2.8, 3.4), shade(TIMBER, 1.25))
    for x in (-3.2, -1.6, 0, 1.6, 3.2):
        mb.box((x, 1.4, 1.2 - 1.72), (0.2, 2.8, 0.08), TIMBER)
    gable_roof(mb, 0, 1.2, 6.6, 3.4, 2.8, 1.7, THATCH, along_z=False, over=0.4)
    for x in (-2.4, 0.0, 2.4):
        door(mb, x, 1.2 - 1.72, 1.1, 1.6, col=(0.15, 0.1, 0.07, 1))
    # paddock fence
    for x in range(-3, 4):
        mb.box((x * 1.05, 0.5, -3.2), (0.12, 1.0, 0.12), TIMBER)
    mb.box((0, 0.75, -3.2), (6.6, 0.1, 0.08), TIMBER)
    mb.box((0, 0.4, -3.2), (6.6, 0.1, 0.08), TIMBER)
    for sx in (-3.2, 3.2):
        mb.box((sx, 0.6, -1.6), (0.08, 0.1, 3.2), TIMBER)
    mb.box((2.0, 0.35, -2.0), (0.9, 0.7, 0.7), THATCH)
    mb.box((1.2, 0.3, -2.2), (0.8, 0.6, 0.6), shade(THATCH, 0.9))
    banner(mb, -3.0, 0, -2.6, team)


def a_siegeworks(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.box((0, 1.8, 1.0), (6.6, 3.6, 4.2), STONE_D)
    gable_roof(mb, 0, 1.0, 6.6, 4.2, 3.6, 1.8, SLATE, along_z=False, over=0.3)
    door(mb, -0.8, 1.0 - 2.12, 3.2, 3.0, col=(0.2, 0.14, 0.1, 1))
    # crane
    mb.beam((2.6, 0, -2.6), (2.6, 5.8, -2.6), 0.18, TIMBER)
    mb.beam((2.6, 5.6, -2.6), (0.2, 5.0, -3.2), 0.14, TIMBER)
    mb.beam((0.2, 5.0, -3.2), (0.2, 2.0, -3.2), 0.02, (0.8, 0.75, 0.6, 1))
    mb.box((0.2, 1.8, -3.2), (0.6, 0.4, 0.6), (0.4, 0.4, 0.42, 1))
    for k in range(4):
        mb.cylinder((-3.0 + k * 0.5, 0.25, -3.0), 0.24, 2.4, (0.55, 0.38, 0.22, 1), segments=6, rot=(90, 0, 0))
    wall_banner(mb, 2.4, 3.2, 1.0 - 2.12, team, -1)


def a_aerie(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.cylinder((0, 0, 0.6), 2.0, 1.0, STONE_D, segments=10)
    mb.cylinder((0, 1.0, 0.6), 1.6, 6.0, STONE, radius_top=1.3, segments=10)
    mb.cylinder((0, 7.0, 0.6), 2.9, 0.4, TIMBER, segments=12)
    for k in range(14):
        a = k / 14 * math.tau
        mb.beam((math.cos(a) * 2.6, 7.3, 0.6 + math.sin(a) * 2.6), (math.cos(a) * 3.2, 8.0, 0.6 + math.sin(a) * 3.2),
                0.09, (0.5, 0.38, 0.24, 1))
    mb.sphere((0, 7.6, 0.6), (2.2, 0.5, 2.2), (0.55, 0.42, 0.25, 1), detail=1, noise=0.15, seed=3)
    for k in range(3):
        a = k * 2.1
        mb.box((math.cos(a) * 1.2, 7.95, 0.6 + math.sin(a) * 1.2), (0.6, 0.12, 0.25), (0.92, 0.9, 0.85, 1), rot=(0, k * 50, 20))
    banner(mb, 1.4, 7.4, -0.8, team, pole=2.4)
    door(mb, 0, 0.6 - 1.62, 1.1, 1.8)
    wall_banner(mb, 0, 5.8, 0.6 - 1.36, team, -1, w=0.8, h=1.6)


# ============================================================================ host
def h_pit(mb: MeshBuilder, glow: MeshBuilder, team: Col, stronghold: bool = False) -> None:
    s = 1.12 if stronghold else 1.0
    palisade_ring(mb, 0, 0, 9.2, 9.2, 2.6 if stronghold else 2.0, DWOOD, gap=2.4, seed=5)
    mb.cylinder((0, 0, 0.6), 3.4 * s, 2.6 * s, DSTONE, radius_top=3.0 * s, segments=9)
    mb.cylinder((0, 2.6 * s, 0.6), 2.2 * s, 3.0 * s, DSTONE_L, radius_top=1.4 * s, segments=7)
    spikes(mb, 0, 0.6, 3.2 * s, 12, 2.4 * s, 1.4, IRON, seed=1, tilt=35)
    spikes(mb, 0, 0.6, 1.5 * s, 7, 5.3 * s, 1.0, BONE, seed=2, tilt=25)
    if stronghold:
        mb.cylinder((0, 5.6 * s, 0.6), 1.2, 4.5, DSTONE, radius_top=0.5, segments=6)
        mb.cone((0, 10.1 * s, 0.6), 0.6, 2.0, IRON, segments=5)
        for sx in (-1, 1):
            mb.cylinder((sx * 3.6, 0, -3.0), 0.9, 6.0, DSTONE, radius_top=0.4, segments=6)
            mb.cone((sx * 3.6, 6.0, -3.0), 0.5, 1.6, IRON, segments=5)
        glow.sphere((0, 9.0, 0.6 - 1.0), 0.32, EMBER, detail=1)
    else:
        mb.cone((0, 5.6, 0.6), 1.6, 1.6, IRON, segments=7)
    door(mb, 0, 0.6 - 3.3 * s, 1.8, 2.0)
    glow.box((0, 0.9, 0.6 - 3.36 * s), (1.2, 1.3, 0.05), EMBER)
    for sx in (-1, 1):
        brazier(glow, mb, sx * 2.0, 0, -4.2)
    banner(mb, -3.6, 0, -3.8, team, pole=3.2, h=2.0)
    banner(mb, 3.2, 0, -3.8, team, pole=3.2, h=2.0)


def h_warren(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.sphere((0, 0.2, 0.3), (2.5, 1.8, 2.3), HIDE, detail=1, noise=0.12, seed=4)
    mb.cone((0, 1.6, 0.3), 1.4, 1.8, shade(HIDE, 0.8), segments=7)
    for k in range(6):
        a = k / 6 * math.tau
        mb.beam((math.cos(a) * 2.1, 0, 0.3 + math.sin(a) * 1.9), (math.cos(a) * 0.4, 3.7, 0.3 + math.sin(a) * 0.4), 0.08, DWOOD)
    door(mb, 0, 0.3 - 2.15, 1.0, 1.2)
    mb.box((0.0, 2.4, 0.3 - 1.6), (0.8, 0.9, 0.05), team, rot=(-35, 0, 0))
    for k in range(3):
        mb.sphere((1.8 - k * 0.3, 0.2, -1.8 + k * 0.2), 0.22, BONE, detail=0)


def h_war_camp(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    palisade_ring(mb, 0, 0, 7.6, 7.6, 2.2, DWOOD, gap=2.2, seed=7)
    mb.box((0, 1.2, 1.0), (5.6, 2.4, 3.6), DWOOD)
    gable_roof(mb, 0, 1.0, 5.6, 3.6, 2.4, 2.0, HIDE, along_z=False, over=0.5)
    spikes(mb, 0, 1.0, 2.6, 8, 3.9, 1.1, BONE, seed=3, tilt=30)
    door(mb, 0, 1.0 - 1.82, 1.6, 1.9)
    mb.cylinder((-2.6, 0, -2.4), 0.12, 3.2, DWOOD, segments=4)
    mb.sphere((-2.6, 3.3, -2.4), 0.3, BONE, detail=0)
    for k in range(4):
        mb.beam((1.6 + k * 0.4, 0, -2.6), (1.6 + k * 0.4, 1.6, -2.4), 0.04, IRON)
    mb.box((2.2, 1.1, -2.5), (1.8, 0.1, 0.12), DWOOD)
    banner(mb, -2.0, 0, -3.0, team, pole=3.0, h=1.8)
    brazier(glow, mb, 0.9, 0, -3.0, 0.8)


def h_sawpit(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.box((0, 0.15, 0), (4.6, 0.3, 4.0), shade(DSTONE, 0.9))
    for x in (-1.8, 1.8):
        mb.beam((x, 0, -1.2), (x * 0.6, 3.2, 0.0), 0.15, DWOOD)
        mb.beam((x, 0, 1.2), (x * 0.6, 3.2, 0.0), 0.15, DWOOD)
    mb.box((0, 3.2, 0), (2.4, 0.2, 0.2), DWOOD)
    mb.box((0, 1.8, 0), (0.1, 2.6, 1.2), IRON)
    mb.cylinder((-1.8, 0.9, 0), 0.4, 3.6, (0.45, 0.32, 0.2, 1), segments=7, rot=(90, 0, 0))
    for k in range(6):
        mb.cylinder((1.8 + (k % 2) * 0.1, 0.25 + (k // 2) * 0.42, -1.8 + (k % 3) * 0.4), 0.22, 2.0,
                    (0.42, 0.3, 0.2, 1), segments=6, rot=(0, 0, 90))
    banner(mb, -2.0, 0, -1.9, team)


def h_bone_forge(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.box((0, 1.3, 0.6), (4.2, 2.6, 3.4), DSTONE)
    mb.cone((0, 2.6, 0.6), 2.6, 1.6, IRON, segments=4, rot=(0, 45, 0))
    mb.cylinder((1.4, 2.0, 1.3), 0.6, 3.8, DSTONE_L, radius_top=0.4, segments=6)
    glow.cylinder((1.4, 5.8, 1.3), 0.38, 0.15, EMBER, segments=6)
    mb.box((-0.6, 0.55, -1.6), (2.6, 1.1, 1.4), DSTONE_L)
    glow.box((-0.6, 1.12, -1.6), (2.0, 0.06, 1.0), (1.0, 0.4, 0.05, 1))
    for k in range(5):
        mb.beam((-2.1 + k * 0.15, 0, -2.4), (-2.3 + k * 0.25, 1.2, -2.7), 0.06, BONE)
    mb.sphere((1.9, 0.35, -2.1), 0.35, BONE, detail=0)
    wall_banner(mb, 0.0, 2.4, 0.6 - 1.72, team, -1)
    spikes(mb, 0, 0.6, 2.2, 6, 2.6, 0.8, BONE, seed=9, tilt=40)


def h_kennels(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    for k in range(3):
        x = -2.4 + k * 2.4
        mb.box((x, 0.1, 1.2), (2.0, 0.2, 2.6), DWOOD)
        for b in range(6):
            mb.box((x - 0.9 + b * 0.36, 1.0, 1.2 - 1.25), (0.08, 1.8, 0.08), IRON)
        mb.box((x, 1.95, 1.2), (2.1, 0.25, 2.7), DWOOD)
        mb.box((x, 2.2, 1.2), (2.2, 0.15, 2.8), HIDE)
    palisade_ring(mb, 0, -0.4, 7.6, 7.0, 1.6, DWOOD, gap=2.0, seed=11)
    for k in range(4):
        mb.sphere((-2.6 + k * 0.4, 0.2, -2.6), 0.2, BONE, detail=0)
    banner(mb, 3.0, 0, -2.8, team, pole=2.6)


def h_ritual_pyre(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.cylinder((0, 0, 0), 2.6, 0.35, DSTONE, segments=10)
    for k in range(7):
        a = k / 7 * math.tau
        x, z = math.cos(a) * 2.4, math.sin(a) * 2.4
        mb.cylinder((x, 0.3, z), 0.3, 2.6 + (k % 2) * 0.8, DSTONE_L, radius_top=0.08, segments=5)
        mb.sphere((x, 3.0 + (k % 2) * 0.8, z), 0.2, BONE, detail=0)
    for k in range(8):
        a = k / 8 * math.tau
        mb.beam((math.cos(a) * 0.9, 0.35, math.sin(a) * 0.9), (math.cos(a) * 0.1, 1.4, math.sin(a) * 0.1), 0.12, DWOOD)
    fire(glow, 0, 0.6, 0, 1.15)
    for sx in (-1, 1):
        mb.quad((sx * 1.4, 3.2, -1.9), (sx * 1.4 + 0.8 * sx, 3.0, -1.9), (sx * 1.4 + 0.8 * sx, 1.4, -1.9), (sx * 1.4, 1.6, -1.9),
                team, facing=(0, 0, -1), double=True)
        mb.beam((sx * 1.4, 0, -1.9), (sx * 1.4, 3.4, -1.9), 0.05, DWOOD)


def h_watch_spire(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.cylinder((0, 0, 0), 1.5, 0.6, DSTONE, segments=6)
    mb.cylinder((0, 0.6, 0), 1.2, 6.2, DSTONE, radius_top=0.65, segments=6)
    mb.cylinder((0, 6.8, 0), 1.3, 0.5, IRON, segments=6)
    spikes(mb, 0, 0, 1.2, 6, 6.9, 1.2, IRON, seed=5, tilt=35)
    mb.cone((0, 7.3, 0), 0.7, 2.2, DSTONE_L, segments=6)
    glow.sphere((0, 7.0, -0.95), (0.25, 0.32, 0.12), EMBER, detail=1)
    mb.quad((-0.5, 5.6, -1.0), (0.5, 5.6, -1.0), (0.5, 4.0, -1.08), (-0.5, 4.2, -1.08), team, facing=(0, 0, -1), double=True)


def h_ogre_den(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    rng = random.Random(21)
    for k in range(9):
        a = math.pi * (0.15 + 0.7 * k / 8)
        mb.sphere((math.cos(a) * 2.8, 0.8 + math.sin(a) * 2.2, 0.8), (1.3, 1.2, 1.6), shade(DSTONE_L, 0.85 + rng.random() * 0.3),
                  detail=1, noise=0.25, seed=k)
    mb.sphere((0, 1.4, 2.0), (3.4, 2.6, 2.4), DSTONE, detail=1, noise=0.2, seed=40)
    mb.box((0, 1.2, -0.4), (2.6, 2.4, 0.4), DARK)
    for sx in (-1, 1):
        mb.beam((sx * 1.4, 0, -0.7), (sx * 1.2, 3.4, -0.9), 0.25, DWOOD)
        mb.cone((sx * 2.6, 0, -2.4), 0.25, 2.6, BONE, segments=4, rot=(-15, 0, sx * 10))
    mb.box((0, 3.5, -0.9), (3.2, 0.3, 0.3), DWOOD)
    mb.sphere((0, 4.0, -0.9), 0.45, BONE, detail=0)
    banner(mb, 2.8, 0, -1.0, team, pole=3.0)
    brazier(glow, mb, -2.4, 0, -2.8, 0.9)


def h_siege_pit(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    mb.box((0, 0.1, 0.4), (7.0, 0.2, 6.2), shade(DSTONE, 0.8))
    for x in (-2.6, 2.6):
        mb.beam((x, 0, -2.0), (x * 0.8, 4.2, 0.4), 0.2, DWOOD)
        mb.beam((x, 0, 2.8), (x * 0.8, 4.2, 0.4), 0.2, DWOOD)
    mb.box((0, 4.2, 0.4), (4.6, 0.25, 0.25), DWOOD)
    mb.beam((0, 4.2, 0.4), (0, 1.5, 0.4), 0.03, (0.6, 0.55, 0.45, 1))
    mb.box((0, 1.3, 0.4), (1.6, 0.6, 0.6), IRON)
    for sx in (-1, 1):
        mb.cylinder((sx * 2.0, 0.6, -2.4), 0.6, 0.18, DWOOD, segments=8, rot=(0, 0, 90))
    for k in range(5):
        mb.sphere((2.4 + (k % 2) * 0.5, 0.35 + (k // 2) * 0.4, 2.2), 0.35, DSTONE_L, detail=0, noise=0.2, seed=k)
    mb.box((-2.4, 1.0, 2.4), (1.6, 2.0, 1.4), HIDE)
    banner(mb, -3.2, 0, -2.8, team, pole=3.0)
    brazier(glow, mb, 3.0, 0, -2.8, 0.9)


def h_drake_roost(mb: MeshBuilder, glow: MeshBuilder, team: Col) -> None:
    rng = random.Random(33)
    mb.cylinder((0, 0, 0.5), 2.6, 1.2, DSTONE, radius_top=2.2, segments=7)
    mb.cylinder((0, 1.2, 0.5), 1.8, 5.5, DSTONE_L, radius_top=0.7, segments=6)
    for k in range(5):
        a = k / 5 * math.tau
        mb.beam((math.cos(a) * 1.2, 3.0 + k * 0.6, 0.5 + math.sin(a) * 1.2),
                (math.cos(a) * 3.0, 3.6 + k * 0.6, 0.5 + math.sin(a) * 3.0), 0.14, DWOOD)
        mb.cone((math.cos(a) * 3.0, 3.6 + k * 0.6, 0.5 + math.sin(a) * 3.0), 0.12, 0.6, BONE, segments=3)
    mb.cone((0, 6.7, 0.5), 0.8, 2.2, IRON, segments=6)
    for k in range(6):
        mb.beam((rng.uniform(-2.5, 2.5), 0, rng.uniform(-2.5, -1.2)), (rng.uniform(-2.5, 2.5), 0.4, rng.uniform(-2.5, -1.2)),
                0.07, BONE)
    mb.quad((-0.6, 5.0, 0.5 - 1.2), (0.6, 5.0, 0.5 - 1.2), (0.6, 3.2, 0.5 - 1.5), (-0.6, 3.4, 0.5 - 1.5), team,
            facing=(0, 0, -1), double=True)
    glow.sphere((0, 2.2, 0.5 - 1.75), (0.5, 0.6, 0.12), EMBER, detail=1)


BUILDERS: dict[str, Callable[[MeshBuilder, MeshBuilder, Col], None]] = {
    "keep": a_keep,
    "castle": lambda mb, g, t: a_keep(mb, g, t, castle=True),
    "house": a_house,
    "barracks": a_barracks,
    "lumber_mill": a_lumber_mill,
    "blacksmith": a_blacksmith,
    "sanctum": a_sanctum,
    "guard_tower": a_guard_tower,
    "stables": a_stables,
    "siegeworks": a_siegeworks,
    "aerie": a_aerie,
    "pit": h_pit,
    "stronghold": lambda mb, g, t: h_pit(mb, g, t, stronghold=True),
    "warren": h_warren,
    "war_camp": h_war_camp,
    "sawpit": h_sawpit,
    "bone_forge": h_bone_forge,
    "kennels": h_kennels,
    "ritual_pyre": h_ritual_pyre,
    "watch_spire": h_watch_spire,
    "ogre_den": h_ogre_den,
    "siege_pit": h_siege_pit,
    "drake_roost": h_drake_roost,
}


def _protos(type_id: str, team: tuple[float, float, float]) -> tuple[NodePath, NodePath | None]:
    key = (type_id, tuple(round(c, 3) for c in team))
    hit = _cache.get(key)
    if hit is None:
        mb, glow = MeshBuilder(), MeshBuilder()
        BUILDERS.get(type_id, a_house)(mb, glow, (team[0], team[1], team[2], 1.0))
        solid = mb.build(type_id)
        g = glow.build(type_id + "_glow") if not glow.is_empty() else None
        if g is not None:
            g.setShaderInput("u_emissive", 1.6)
        hit = (solid, g)
        _cache[key] = hit
    return hit


def build_building_node(type_id: str, faction: str, team: tuple[float, float, float], parent: NodePath,
                        drop: float) -> NodePath:
    """Attach a building model (plus a foundation reaching ``drop`` units below) and return its root."""
    from core import data
    root = parent.attachNewNode("model")
    solid, glow = _protos(type_id, team)
    solid.copyTo(root)
    if glow is not None:
        glow.copyTo(root)
    fp = int(data.buildings()[type_id]["footprint"]) * CELL * 0.92
    found = _foundation(faction)
    f = found.copyTo(parent)
    f.setScale(fp, drop + 0.7, fp)
    f.setPos(0, -drop - 0.5, 0)
    return root


_found: dict[str, NodePath] = {}


def _foundation(faction: str) -> NodePath:
    p = _found.get(faction)
    if p is None:
        mb = MeshBuilder()
        col = STONE_D if faction == "alliance" else shade(DSTONE, 0.9)
        mb.box((0, 0.5, 0), (1, 1, 1), col, jitter=0.02, taper=0.97)
        p = mb.build("foundation")
        _found[faction] = p
    return p
