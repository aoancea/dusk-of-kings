"""Heightfield terrain generated from a map definition (plateaus, ramps, rivers, mountains...).

The heightmap has one vertex per world unit and covers the playable square
``[-size/2, size/2]``. Heights are stored as a numpy array (``h[iz, ix]``) and as a flat
Python list for fast scalar sampling from game logic.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from panda3d.core import NodePath

from core.meshgen import grid_indices, make_geom_node, tri_normals
from core.noise import fbm, polyline_distance, ridged, smoothstep, value_noise
from settings import SEA_LEVEL

RAMP_SLOPE = 0.42          # rise per unit along a ramp
CLIFF_WIDTH = 2.4          # horizontal width of a plateau cliff
RIVER_BED = -1.1           # absolute height of a river bed (deep water)
FORD_BED = -0.32           # absolute height of a ford (wadeable)

PALETTES: dict[str, dict[str, tuple[float, float, float]]] = {
    "fen": {
        "grass": (0.34, 0.46, 0.22), "grass2": (0.44, 0.52, 0.26), "dry": (0.52, 0.50, 0.31),
        "heath": (0.42, 0.43, 0.27), "mud": (0.36, 0.31, 0.21), "silt": (0.42, 0.38, 0.27),
        "rock": (0.47, 0.45, 0.41), "rock2": (0.36, 0.35, 0.33), "peak": (0.62, 0.62, 0.64), "snow": (0.9, 0.91, 0.94),
    },
    "ash": {
        "grass": (0.40, 0.39, 0.28), "grass2": (0.46, 0.43, 0.30), "dry": (0.50, 0.44, 0.33),
        "heath": (0.37, 0.34, 0.29), "mud": (0.30, 0.27, 0.23), "silt": (0.34, 0.31, 0.27),
        "rock": (0.36, 0.33, 0.31), "rock2": (0.27, 0.25, 0.24), "peak": (0.46, 0.43, 0.41), "snow": (0.62, 0.6, 0.6),
    },
}


class Terrain:
    """Procedural heightfield plus its render mesh."""

    def __init__(self, mapdef: dict[str, Any]) -> None:
        self.defn = mapdef
        self.size = float(mapdef["size"])
        self.half = self.size / 2.0
        self.n = int(self.size) + 1
        self.seed = int(mapdef.get("seed", 1))
        self.base = float(mapdef.get("base_height", 1.2))
        xs = np.linspace(-self.half, self.half, self.n, dtype=np.float32)
        self.X, self.Z = np.meshgrid(xs, xs)
        self.ramps: list[dict[str, Any]] = []
        self.h = self._generate()
        self.hl: list[float] = self.h.ravel().tolist()
        self.has_water = bool((self.h < SEA_LEVEL - 0.05).any())

    # ------------------------------------------------------------------ generation
    def _plateau_radius(self, f: dict[str, Any], idx: int, ang: np.ndarray | float) -> np.ndarray | float:
        """Plateau radius at polar angle ``ang`` (noisy so cliffs are not perfect circles)."""
        px, pz = f["pos"]
        ca = np.cos(ang) * 9.0 + px
        sa = np.sin(ang) * 9.0 + pz
        n = fbm(np.asarray(ca, np.float32), np.asarray(sa, np.float32), 7.0, 2, self.seed + 13 * idx)
        return f["radius"] + (n - 0.5) * 7.0

    def _generate(self) -> np.ndarray:
        X, Z = self.X, self.Z
        seed = self.seed
        rough = float(self.defn.get("roughness", 1.0))
        h = self.base + (fbm(X, Z, 34.0, 4, seed) - 0.5) * 1.3 * rough
        h += (fbm(X, Z, 7.0, 2, seed + 5) - 0.5) * 0.25 * rough
        feats = self.defn.get("features", [])
        pre = h.copy()

        for i, f in enumerate(feats):
            t = f["type"]
            if t == "plateau":
                px, pz = f["pos"]
                dx, dz = X - px, Z - pz
                r = np.sqrt(dx * dx + dz * dz)
                ang = np.arctan2(dz, dx)
                R = self._plateau_radius(f, i, ang)
                m = smoothstep(R + CLIFF_WIDTH, R - 0.2, r)
                top = f["height"] + (fbm(X, Z, 12.0, 3, seed + 31 * i) - 0.5) * 0.7
                h = h * (1 - m) + top * m
            elif t == "mountain":
                px, pz = f["pos"]
                r = np.sqrt((X - px) ** 2 + (Z - pz) ** 2)
                ang = np.arctan2(Z - pz, X - px)
                wob = value_noise(np.cos(ang) * 2.5 + 7 * i, np.sin(ang) * 2.5, seed + i)
                R = f["radius"] * (0.85 + 0.3 * wob)
                m = smoothstep(R, R * 0.3, r)
                rid = ridged(X, Z, 11.0, 3, seed + 7 * i)
                h = h + f["height"] * (m ** 1.2) * (0.7 + 0.6 * rid)
            elif t == "hill":
                px, pz = f["pos"]
                r = np.sqrt((X - px) ** 2 + (Z - pz) ** 2)
                h = h + f["height"] * smoothstep(f["radius"], 0.0, r)

        # ramps cut through plateau cliffs
        for i, f in enumerate(feats):
            if f["type"] != "plateau":
                continue
            px, pz = f["pos"]
            H = f["height"]
            for rp in f.get("ramps", []):
                ax, az, width = rp
                ang = math.atan2(az - pz, ax - px)
                dirx, dirz = math.cos(ang), math.sin(ang)
                Re = float(self._plateau_radius(f, i, ang))
                drop = H - self.base
                L = max(10.0, drop / RAMP_SLOPE)
                sx = px + dirx * (Re - 4.0)
                sz = pz + dirz * (Re - 4.0)
                ex, ez = sx + dirx * L, sz + dirz * L
                low = self._sample(pre, ex, ez)
                rx, rz = X - sx, Z - sz
                s = (rx * dirx + rz * dirz) / L
                lat = np.abs(rx * -dirz + rz * dirx)
                prof = H + (low - H) * smoothstep(0.0, 1.0, s)
                m = smoothstep(width / 2 + 1.6, width / 2 - 0.4, lat) * smoothstep(-0.25, 0.0, s) * smoothstep(1.35, 1.0, s)
                h = h * (1 - m) + prof * m
                self.ramps.append({"start": (sx, sz), "end": (ex, ez), "width": width})

        # water: rivers and ponds are carved last so nothing raises their beds
        for i, f in enumerate(feats):
            t = f["type"]
            if t == "river":
                d, _ = polyline_distance(X, Z, f["points"])
                w = f["width"] / 2.0
                bed = np.full(X.shape, RIVER_BED, np.float32) + (fbm(X, Z, 6.0, 2, seed + 91) - 0.5) * 0.4
                for fx, fz, fr in f.get("fords", []):
                    fd = np.sqrt((X - fx) ** 2 + (Z - fz) ** 2)
                    k = smoothstep(fr + 3.0, fr - 2.0, fd)
                    bed = bed * (1 - k) + FORD_BED * k
                    w_ford = smoothstep(fr + 6.0, fr, fd)
                    bank = smoothstep(w + 3.5 + w_ford * 2.5, w - 0.6, d)
                    h = np.where(w_ford > 0, h * (1 - bank * w_ford) + bed * bank * w_ford, h)
                k = smoothstep(w + 3.6, w - 0.6, d)
                h = np.minimum(h, h * (1 - k) + bed * k)
            elif t == "pond":
                px, pz = f["pos"]
                r = np.sqrt((X - px) ** 2 + (Z - pz) ** 2)
                bed = SEA_LEVEL - f.get("depth", 1.8)
                k = smoothstep(f["radius"] + 4.0, f["radius"] * 0.5, r)
                h = np.minimum(h, h * (1 - k) + bed * k)

        # map rim: rugged walls frame the playable area
        e = np.maximum(np.abs(X), np.abs(Z))
        rim = smoothstep(self.half - 11.0, self.half - 1.5, e)
        h = h + rim * (9.0 + ridged(X, Z, 9.0, 3, seed + 3) * 9.0)
        return h.astype(np.float32)

    def _sample(self, arr: np.ndarray, x: float, z: float) -> float:
        ix = int(round(min(max(x + self.half, 0), self.size)))
        iz = int(round(min(max(z + self.half, 0), self.size)))
        return float(arr[iz, ix])

    # ------------------------------------------------------------------ queries
    def height(self, x: float, z: float) -> float:
        """Exact height of the rendered triangle surface at (x, z)."""
        n = self.n
        fx = x + self.half
        fz = z + self.half
        if fx < 0.0:
            fx = 0.0
        elif fx > n - 1.001:
            fx = n - 1.001
        if fz < 0.0:
            fz = 0.0
        elif fz > n - 1.001:
            fz = n - 1.001
        ix = int(fx)
        iz = int(fz)
        tx = fx - ix
        tz = fz - iz
        i = iz * n + ix
        hl = self.hl
        a = hl[i]
        c = hl[i + n + 1]
        if tx > tz:
            b = hl[i + 1]
            return a + (b - a) * tx + (c - b) * tz
        d = hl[i + n]
        return a + (d - a) * tz + (c - d) * tx

    def in_bounds(self, x: float, z: float, margin: float = 0.0) -> bool:
        lim = self.half - margin
        return -lim <= x <= lim and -lim <= z <= lim

    # ------------------------------------------------------------------ mesh
    def build_mesh(self, parent: NodePath, palette_name: str, chunk: int = 32) -> NodePath:
        """Create flat-shaded, vertex-coloured terrain chunks under ``parent``."""
        pal = PALETTES.get(palette_name, PALETTES["fen"])
        root = parent.attachNewNode("terrain")
        n = self.n
        cells = n - 1
        verts = np.stack([self.X, self.h, self.Z], -1)
        for cz in range(0, cells, chunk):
            for cx in range(0, cells, chunk):
                nx = min(chunk, cells - cx)
                nz = min(chunk, cells - cz)
                sub = verts[cz:cz + nz + 1, cx:cx + nx + 1].reshape(-1, 3)
                idx = grid_indices(nx, nz)
                tris = sub[idx]
                cols = self._face_colors(tris, pal)
                normals = np.repeat(tri_normals(tris), 3, axis=0)
                colors = np.repeat(cols, 3, axis=0)
                node = make_geom_node(tris.reshape(-1, 3), normals, colors, name=f"terrain_{cx}_{cz}")
                node.reparentTo(root)
        root.setShaderInput("u_detail", 0.55)
        return root

    def _face_colors(self, tris: np.ndarray, pal: dict[str, tuple[float, float, float]]) -> np.ndarray:
        cent = tris.mean(axis=1)
        cx, cy, cz = cent[:, 0], cent[:, 1], cent[:, 2]
        nrm = tri_normals(tris)
        up = nrm[:, 1]
        seed = self.seed
        n1 = fbm(cx, cz, 9.0, 3, seed + 201)
        n2 = fbm(cx, cz, 26.0, 3, seed + 202)
        speck = value_noise(cx * 1.7, cz * 1.7, seed + 203)

        def col(name: str) -> np.ndarray:
            return np.asarray(pal[name], np.float32)[None, :]

        grass = col("grass") * (1 - n2[:, None]) + col("grass2") * n2[:, None]
        grass = grass * (1 - smoothstep(0.62, 0.8, n1)[:, None]) + col("dry") * smoothstep(0.62, 0.8, n1)[:, None]
        high = smoothstep(3.0, 5.0, cy)[:, None]
        c = grass * (1 - high * 0.55) + col("heath") * high * 0.55
        # mud banks and silty beds
        wet = smoothstep(0.9, 0.15, cy)[:, None]
        c = c * (1 - wet) + col("mud") * wet
        under = smoothstep(-0.05, -0.5, cy)[:, None]
        c = c * (1 - under) + col("silt") * under
        # cliffs / steep rock
        steep = smoothstep(0.86, 0.66, up)[:, None]
        rock = col("rock") * (1 - speck[:, None]) + col("rock2") * speck[:, None]
        c = c * (1 - steep) + rock * steep
        # high peaks
        peak = smoothstep(9.0, 14.0, cy)[:, None]
        c = c * (1 - peak) + col("peak") * peak
        snow = (smoothstep(15.5, 18.5, cy) * smoothstep(0.55, 0.8, up))[:, None]
        c = c * (1 - snow) + col("snow") * snow
        c = c * (0.93 + 0.14 * speck[:, None])
        out = np.ones((c.shape[0], 4), np.float32)
        out[:, :3] = np.clip(c, 0, 1)
        return out
