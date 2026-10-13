"""Vectorised value noise helpers (numpy)."""
from __future__ import annotations

import numpy as np


def _hash(ix: np.ndarray, iz: np.ndarray, seed: int) -> np.ndarray:
    n = (ix.astype(np.int64) * 374761393 + iz.astype(np.int64) * 668265263 + seed * 144269504) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    n = n ^ (n >> 16)
    return (n & 0xFFFFFF).astype(np.float32) / float(0xFFFFFF)


def value_noise(x: np.ndarray, z: np.ndarray, seed: int = 0) -> np.ndarray:
    """Smooth value noise in [0, 1] sampled at arrays ``x``/``z`` (lattice spacing 1)."""
    x0 = np.floor(x)
    z0 = np.floor(z)
    fx = (x - x0).astype(np.float32)
    fz = (z - z0).astype(np.float32)
    fx = fx * fx * (3 - 2 * fx)
    fz = fz * fz * (3 - 2 * fz)
    ix = x0.astype(np.int64)
    iz = z0.astype(np.int64)
    a = _hash(ix, iz, seed)
    b = _hash(ix + 1, iz, seed)
    c = _hash(ix, iz + 1, seed)
    d = _hash(ix + 1, iz + 1, seed)
    return (a * (1 - fx) + b * fx) * (1 - fz) + (c * (1 - fx) + d * fx) * fz


def fbm(x: np.ndarray, z: np.ndarray, scale: float, octaves: int = 4, seed: int = 0,
        gain: float = 0.5, lacunarity: float = 2.0) -> np.ndarray:
    """Fractal value noise in roughly [0, 1]."""
    total = np.zeros(np.broadcast(x, z).shape, np.float32)
    amp, norm, freq = 1.0, 0.0, 1.0 / scale
    for o in range(octaves):
        total += value_noise(x * freq, z * freq, seed + o * 101) * amp
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


def ridged(x: np.ndarray, z: np.ndarray, scale: float, octaves: int = 4, seed: int = 0) -> np.ndarray:
    """Ridged multifractal-ish noise in [0, 1] (sharp crests)."""
    total = np.zeros(np.broadcast(x, z).shape, np.float32)
    amp, norm, freq = 1.0, 0.0, 1.0 / scale
    for o in range(octaves):
        n = value_noise(x * freq, z * freq, seed + o * 57)
        n = 1.0 - np.abs(n * 2.0 - 1.0)
        total += n * n * amp
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm


def smoothstep(e0: float, e1: float, x: np.ndarray | float) -> np.ndarray:
    t = np.clip((np.asarray(x, np.float32) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def polyline_distance(px: np.ndarray, pz: np.ndarray, pts: list[list[float]]) -> tuple[np.ndarray, np.ndarray]:
    """Distance from points to a polyline and the interpolated third coordinate (height) if present.

    ``pts`` items are [x, z] or [x, z, h]. Returns (distance, height_or_nan).
    """
    best = np.full(px.shape, np.inf, np.float32)
    best_h = np.full(px.shape, np.nan, np.float32)
    for a, b in zip(pts[:-1], pts[1:]):
        ax, az, bx, bz = a[0], a[1], b[0], b[1]
        dx, dz = bx - ax, bz - az
        ll = dx * dx + dz * dz
        if ll < 1e-9:
            continue
        t = np.clip(((px - ax) * dx + (pz - az) * dz) / ll, 0.0, 1.0)
        qx = ax + t * dx
        qz = az + t * dz
        d = np.sqrt((px - qx) ** 2 + (pz - qz) ** 2).astype(np.float32)
        closer = d < best
        best = np.where(closer, d, best)
        if len(a) > 2 and len(b) > 2 and a[2] is not None and b[2] is not None:
            h = (a[2] + (b[2] - a[2]) * t).astype(np.float32)
            best_h = np.where(closer, h, best_h)
        else:
            best_h = np.where(closer, np.nan, best_h)
    return best, best_h
