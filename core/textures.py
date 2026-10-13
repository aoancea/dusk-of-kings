"""Procedurally generated textures (numpy -> Panda3D / Ursina)."""
from __future__ import annotations

import numpy as np
from panda3d.core import SamplerState, Texture as PTexture


def np_to_texture(img: np.ndarray, name: str = "tex", mipmap: bool = True,
                  repeat: bool = True, nearest: bool = False) -> PTexture:
    """Convert an (h, w, 1|3|4) uint8 array (row 0 = top) to a Panda3D texture."""
    if img.ndim == 2:
        img = img[:, :, None]
    h, w, c = img.shape
    if c == 1:
        img = np.repeat(img, 3, axis=2)
        c = 3
    if c == 3:
        img = np.concatenate([img, np.full((h, w, 1), 255, np.uint8)], axis=2)
    tex = PTexture(name)
    tex.setup2dTexture(w, h, PTexture.T_unsigned_byte, PTexture.F_rgba8)
    tex.setRamImageAs(np.ascontiguousarray(img[::-1]).tobytes(), "RGBA")
    wrap = SamplerState.WM_repeat if repeat else SamplerState.WM_clamp
    tex.setWrapU(wrap)
    tex.setWrapV(wrap)
    if nearest:
        tex.setMinfilter(SamplerState.FT_nearest)
        tex.setMagfilter(SamplerState.FT_nearest)
    elif mipmap:
        tex.setMinfilter(SamplerState.FT_linear_mipmap_linear)
        tex.setMagfilter(SamplerState.FT_linear)
        tex.setAnisotropicDegree(4)
    else:
        tex.setMinfilter(SamplerState.FT_linear)
        tex.setMagfilter(SamplerState.FT_linear)
    return tex


def tileable_noise(size: int = 256, octaves: int = 5, base_period: int = 8, seed: int = 7,
                   persistence: float = 0.55) -> np.ndarray:
    """Tileable value noise in [0, 1] of shape (size, size)."""
    rng = np.random.default_rng(seed)
    out = np.zeros((size, size), np.float32)
    amp, total = 1.0, 0.0
    period = base_period
    coords = np.arange(size, dtype=np.float32)
    for _ in range(octaves):
        grid = rng.random((period, period)).astype(np.float32)
        f = coords * period / size
        i0 = np.floor(f).astype(int) % period
        i1 = (i0 + 1) % period
        t = f - np.floor(f)
        t = t * t * (3 - 2 * t)
        # interpolate along x then z
        g00 = grid[i0[:, None], i0[None, :]]
        g10 = grid[i0[:, None], i1[None, :]]
        g01 = grid[i1[:, None], i0[None, :]]
        g11 = grid[i1[:, None], i1[None, :]]
        tx = t[None, :]
        tz = t[:, None]
        layer = (g00 * (1 - tx) + g10 * tx) * (1 - tz) + (g01 * (1 - tx) + g11 * tx) * tz
        out += layer * amp
        total += amp
        amp *= persistence
        period *= 2
    return out / total


def detail_texture() -> PTexture:
    """Grainy sand/rock detail used by the terrain shader."""
    n = tileable_noise(256, 6, 8, seed=11)
    grain = np.random.default_rng(3).random((256, 256)).astype(np.float32)
    v = np.clip(n * 0.75 + grain * 0.25, 0, 1)
    img = (v * 255).astype(np.uint8)
    return np_to_texture(img, "detail")


def radial_texture(size: int = 64, inner: float = 0.0, outer: float = 1.0,
                   color: tuple[int, int, int] = (0, 0, 0), power: float = 1.5) -> PTexture:
    """Soft radial alpha gradient (blob shadows, glows)."""
    c = (np.arange(size) + 0.5) / size * 2 - 1
    r = np.sqrt(c[None, :] ** 2 + c[:, None] ** 2)
    a = np.clip((outer - r) / max(outer - inner, 1e-5), 0, 1) ** power
    img = np.zeros((size, size, 4), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = color
    img[..., 3] = (a * 255).astype(np.uint8)
    return np_to_texture(img, "radial", mipmap=True, repeat=False)


def ring_texture(size: int = 128, width: float = 0.12, color: tuple[int, int, int] = (255, 255, 255)) -> PTexture:
    """Thin ring with soft edges (selection circles, telegraphs)."""
    c = (np.arange(size) + 0.5) / size * 2 - 1
    r = np.sqrt(c[None, :] ** 2 + c[:, None] ** 2)
    a = np.clip(1 - np.abs(r - (1 - width)) / width, 0, 1) ** 1.2
    img = np.zeros((size, size, 4), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = color
    img[..., 3] = (a * 255).astype(np.uint8)
    return np_to_texture(img, "ring", mipmap=True, repeat=False)


def telegraph_texture(size: int = 128) -> PTexture:
    """Filled danger circle with a bright rim."""
    c = (np.arange(size) + 0.5) / size * 2 - 1
    r = np.sqrt(c[None, :] ** 2 + c[:, None] ** 2)
    fill = np.where(r < 1, 0.35 + 0.25 * r ** 3, 0)
    rim = np.clip(1 - np.abs(r - 0.95) / 0.05, 0, 1)
    a = np.clip(fill + rim, 0, 1)
    img = np.zeros((size, size, 4), np.uint8)
    img[..., 0] = 255
    img[..., 1] = (60 + rim * 120).astype(np.uint8)
    img[..., 2] = 30
    img[..., 3] = (a * 255).astype(np.uint8)
    return np_to_texture(img, "telegraph", mipmap=True, repeat=False)
