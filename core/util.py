"""Small math and scene-graph helpers shared by all systems."""
from __future__ import annotations

import math
import random
from typing import Sequence

from panda3d.core import NodePath


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def smoothstep(e0: float, e1: float, x: float) -> float:
    t = clamp((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def approach(current: float, target: float, max_delta: float) -> float:
    if current < target:
        return min(current + max_delta, target)
    return max(current - max_delta, target)


def damp(current: float, target: float, rate: float, dt: float) -> float:
    """Frame-rate independent exponential smoothing."""
    return target + (current - target) * math.exp(-rate * dt)


def angle_diff(a: float, b: float) -> float:
    """Signed smallest difference b - a in degrees, in [-180, 180)."""
    return (b - a + 180.0) % 360.0 - 180.0


def damp_angle(current: float, target: float, rate: float, dt: float) -> float:
    return current + angle_diff(current, target) * (1 - math.exp(-rate * dt))


def yaw_to(dx: float, dz: float) -> float:
    """Ursina-style yaw in degrees (0 = +z/north, 90 = +x/east)."""
    return math.degrees(math.atan2(dx, dz))


def yaw_vector(yaw: float) -> tuple[float, float]:
    r = math.radians(yaw)
    return math.sin(r), math.cos(r)


def dist2d(ax: float, az: float, bx: float, bz: float) -> float:
    return math.hypot(ax - bx, az - bz)


def set_rot(np_: NodePath, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
    """Rotate a raw NodePath using Ursina's convention (x = pitch down, y = yaw right, z = roll)."""
    np_.setHpr(-y, -x, z)


def set_yaw(np_: NodePath, yaw: float) -> None:
    np_.setH(-yaw)


def rand_range(a: float, b: float, rng: random.Random | None = None) -> float:
    return (rng or random).uniform(a, b)


def weighted_choice(options: Sequence[tuple[object, float]], rng: random.Random | None = None) -> object:
    r = (rng or random).random() * sum(w for _, w in options)
    for value, w in options:
        r -= w
        if r <= 0:
            return value
    return options[-1][0]


def fmt_time(seconds: float) -> str:
    s = int(math.ceil(seconds))
    if s >= 60:
        return f"{s // 60}m"
    return f"{s}"
