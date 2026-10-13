"""Procedural low-poly mesh construction.

Everything in the world is built from flat-shaded, vertex-coloured triangles that are
accumulated in numpy arrays and uploaded to Panda3D in one go. Ursina uses a y-up,
left-handed coordinate system in which front faces wind counter-clockwise on screen;
the outward normal of such a triangle (a, b, c) is ``cross(c - a, b - a)``.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexArrayFormat,
    GeomVertexData,
    GeomVertexFormat,
    InternalName,
    NodePath,
)

Color = Sequence[float]
_formats: dict[bool, GeomVertexFormat] = {}
_rng = np.random.default_rng(1234)


def _vertex_format(with_uv: bool) -> GeomVertexFormat:
    fmt = _formats.get(with_uv)
    if fmt is None:
        arr = GeomVertexArrayFormat()
        arr.addColumn(InternalName.getVertex(), 3, Geom.NT_float32, Geom.C_point)
        arr.addColumn(InternalName.getNormal(), 3, Geom.NT_float32, Geom.C_normal)
        arr.addColumn(InternalName.getColor(), 4, Geom.NT_float32, Geom.C_color)
        if with_uv:
            arr.addColumn(InternalName.getTexcoord(), 2, Geom.NT_float32, Geom.C_texcoord)
        fmt = GeomVertexFormat.registerFormat(arr)
        _formats[with_uv] = fmt
    return fmt


def make_geom_node(positions: np.ndarray, normals: np.ndarray, colors: np.ndarray,
                   uvs: np.ndarray | None = None, indices: np.ndarray | None = None,
                   name: str = "mesh", dynamic: bool = False) -> NodePath:
    """Upload vertex arrays to a new GeomNode and return it wrapped in a NodePath."""
    n = int(positions.shape[0])
    fmt = _vertex_format(uvs is not None)
    usage = Geom.UH_dynamic if dynamic else Geom.UH_static
    vdata = GeomVertexData(name, fmt, usage)
    vdata.uncleanSetNumRows(n)
    parts = [positions.reshape(n, 3), normals.reshape(n, 3), colors.reshape(n, 4)]
    if uvs is not None:
        parts.append(uvs.reshape(n, 2))
    data = np.ascontiguousarray(np.concatenate(parts, axis=1), dtype=np.float32)
    handle = vdata.modifyArray(0)
    assert handle.getArrayFormat().getStride() == data.shape[1] * 4
    memoryview(handle).cast("B")[:] = data.tobytes()

    prim = GeomTriangles(usage)
    if indices is None:
        prim.addConsecutiveVertices(0, n)
    else:
        idx = np.ascontiguousarray(indices, dtype=np.uint32).ravel()
        prim.setIndexType(Geom.NT_uint32)
        parr = prim.modifyVertices()
        parr.uncleanSetNumRows(len(idx))
        memoryview(parr).cast("B")[:] = idx.tobytes()
    prim.closePrimitive()
    geom = Geom(vdata)
    geom.addPrimitive(prim)
    node = GeomNode(name)
    node.addGeom(geom)
    return NodePath(node)


def rotation_matrix(rot: Sequence[float] | None) -> np.ndarray:
    """Rotation from (pitch_x, yaw_y, roll_z) in degrees, applied roll -> pitch -> yaw."""
    if rot is None:
        return np.eye(3, dtype=np.float32)
    px, py, pz = (math.radians(a) for a in rot)
    cx, sx = math.cos(px), math.sin(px)
    cy, sy = math.cos(py), math.sin(py)
    cz, sz = math.cos(pz), math.sin(pz)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], np.float32)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], np.float32)
    return ry @ rx @ rz


def yaw_matrix(yaw_deg: float) -> np.ndarray:
    return rotation_matrix((0.0, yaw_deg, 0.0))


def tri_normals(tris: np.ndarray) -> np.ndarray:
    """Outward normals for (n, 3, 3) triangles in Ursina's winding convention."""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    n = np.cross(c - a, b - a)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln < 1e-9] = 1.0
    return n / ln


def orient_outward(tris: np.ndarray, center: np.ndarray) -> np.ndarray:
    """Flip triangles whose normal points towards ``center`` (for convex shapes)."""
    n = tri_normals(tris)
    cent = tris.mean(axis=1)
    flip = np.einsum("ij,ij->i", n, cent - center) < 0
    if np.any(flip):
        tris = tris.copy()
        tmp = tris[flip, 1].copy()
        tris[flip, 1] = tris[flip, 2]
        tris[flip, 2] = tmp
    return tris


def orient_to(tris: np.ndarray, direction: Sequence[float]) -> np.ndarray:
    """Flip triangles so that their normals roughly follow ``direction``."""
    n = tri_normals(tris)
    flip = n @ np.asarray(direction, np.float32) < 0
    if np.any(flip):
        tris = tris.copy()
        tmp = tris[flip, 1].copy()
        tris[flip, 1] = tris[flip, 2]
        tris[flip, 2] = tmp
    return tris


# --- unit primitive templates -------------------------------------------------------

def _unit_box() -> np.ndarray:
    c = np.array([[x, y, z] for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)], np.float32)
    # corner index = xi*4 + yi*2 + zi
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = []
    for f in faces:
        tris.append([c[f[0]], c[f[1]], c[f[2]]])
        tris.append([c[f[0]], c[f[2]], c[f[3]]])
    return orient_outward(np.array(tris, np.float32), np.zeros(3, np.float32))


def _icosphere(subdiv: int) -> np.ndarray:
    t = (1.0 + 5 ** 0.5) / 2.0
    verts = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
             (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
             (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
             (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    v = np.array(verts, np.float64)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    tris = v[np.array(faces)]
    for _ in range(subdiv):
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        ab = (a + b) / 2
        bc = (b + c) / 2
        ca = (c + a) / 2
        ab /= np.linalg.norm(ab, axis=1, keepdims=True)
        bc /= np.linalg.norm(bc, axis=1, keepdims=True)
        ca /= np.linalg.norm(ca, axis=1, keepdims=True)
        tris = np.concatenate([
            np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1),
            np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1)])
    return orient_outward(tris.astype(np.float32), np.zeros(3, np.float32))


_BOX = _unit_box()
_SPHERES = {d: _icosphere(d) for d in (0, 1, 2)}


def _cylinder_tris(segments: int, r0: float, r1: float, h: float, caps: bool = True) -> np.ndarray:
    ang = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    ring0 = np.stack([np.cos(ang) * r0, np.zeros_like(ang), np.sin(ang) * r0], 1)
    ring1 = np.stack([np.cos(ang) * r1, np.full_like(ang, h), np.sin(ang) * r1], 1)
    tris = []
    for i in range(segments):
        j = (i + 1) % segments
        if r1 > 1e-6:
            tris.append([ring0[i], ring1[i], ring1[j]])
        tris.append([ring0[i], ring1[j], ring0[j]] if r1 > 1e-6 else [ring0[i], ring1[i], ring0[j]])
        if caps:
            tris.append([ring0[i], ring0[j], [0.0, 0.0, 0.0]])
            if r1 > 1e-6:
                tris.append([ring1[i], [0.0, h, 0.0], ring1[j]])
    arr = np.array(tris, np.float32)
    return orient_outward(arr, np.array([0.0, h * 0.5, 0.0], np.float32))


class MeshBuilder:
    """Accumulates coloured triangles and builds a single flat-shaded mesh."""

    def __init__(self) -> None:
        self._tris: list[np.ndarray] = []
        self._cols: list[np.ndarray] = []

    # -- core ---------------------------------------------------------------------
    def add_tris(self, tris: np.ndarray, color: Color | np.ndarray, jitter: float = 0.0) -> "MeshBuilder":
        """Add (n, 3, 3) triangles with a single RGBA colour or per-triangle colours."""
        tris = np.asarray(tris, np.float32).reshape(-1, 3, 3)
        n = tris.shape[0]
        if n == 0:
            return self
        col = np.asarray(color, np.float32)
        if col.ndim == 1:
            if col.shape[0] == 3:
                col = np.append(col, 1.0).astype(np.float32)
            col = np.broadcast_to(col, (n, 4)).copy()
        else:
            if col.shape[1] == 3:
                col = np.concatenate([col, np.ones((n, 1), np.float32)], axis=1)
            col = col.astype(np.float32).copy()
        if jitter:
            col[:, :3] *= (1.0 + (_rng.random((n, 1), dtype=np.float32) - 0.5) * 2.0 * jitter)
        self._tris.append(tris)
        self._cols.append(col)
        return self

    def _place(self, local: np.ndarray, pos: Sequence[float], rot: Sequence[float] | None,
               scale: Sequence[float] | float) -> np.ndarray:
        s = np.asarray(scale, np.float32)
        out = local * s
        if rot is not None and any(rot):
            out = out @ rotation_matrix(rot).T
        return out + np.asarray(pos, np.float32)

    @property
    def tri_count(self) -> int:
        return int(sum(t.shape[0] for t in self._tris))

    def is_empty(self) -> bool:
        return not self._tris

    # -- primitives ----------------------------------------------------------------
    def box(self, pos: Sequence[float], size: Sequence[float], color: Color,
            rot: Sequence[float] | None = None, jitter: float = 0.04,
            taper: float = 1.0) -> "MeshBuilder":
        """Axis box centred at ``pos``; ``taper`` scales the top face (for wedges/trapezoids)."""
        local = _BOX.copy()
        if taper != 1.0:
            top = local[:, :, 1] > 0
            local[:, :, 0] = np.where(top, local[:, :, 0] * taper, local[:, :, 0])
            local[:, :, 2] = np.where(top, local[:, :, 2] * taper, local[:, :, 2])
        return self.add_tris(self._place(local, pos, rot, size), color, jitter)

    def cylinder(self, pos: Sequence[float], radius: float, height: float, color: Color,
                 radius_top: float | None = None, segments: int = 7,
                 rot: Sequence[float] | None = None, jitter: float = 0.04,
                 caps: bool = True, scale: Sequence[float] = (1, 1, 1)) -> "MeshBuilder":
        """Cylinder standing on ``pos`` (base centre) along +y before rotation."""
        rt = radius if radius_top is None else radius_top
        local = _cylinder_tris(segments, radius, rt, height, caps)
        return self.add_tris(self._place(local, pos, rot, scale), color, jitter)

    def cone(self, pos: Sequence[float], radius: float, height: float, color: Color,
             segments: int = 6, rot: Sequence[float] | None = None, jitter: float = 0.04) -> "MeshBuilder":
        return self.cylinder(pos, radius, height, color, radius_top=0.0, segments=segments,
                             rot=rot, jitter=jitter)

    def sphere(self, pos: Sequence[float], radius: float | Sequence[float], color: Color,
               detail: int = 1, rot: Sequence[float] | None = None, jitter: float = 0.05,
               noise: float = 0.0, seed: int | None = None) -> "MeshBuilder":
        """Low-poly icosphere; ``noise`` displaces vertices radially for rocks."""
        local = _SPHERES[detail].copy()
        if noise > 0:
            rng = np.random.default_rng(seed)
            flat = local.reshape(-1, 3)
            keys = np.round(flat * 1000).astype(np.int64)
            uniq, inv = np.unique(keys, axis=0, return_inverse=True)
            disp = 1.0 + (rng.random(len(uniq)) - 0.5) * 2.0 * noise
            flat *= disp[inv.ravel()][:, None]
            local = flat.reshape(-1, 3, 3)
            local = orient_outward(local, np.zeros(3, np.float32))
        r = np.broadcast_to(np.asarray(radius, np.float32), (3,))
        return self.add_tris(self._place(local, pos, rot, r), color, jitter)

    def quad(self, p0: Sequence[float], p1: Sequence[float], p2: Sequence[float], p3: Sequence[float],
             color: Color, facing: Sequence[float] | None = None, double: bool = False,
             jitter: float = 0.0) -> "MeshBuilder":
        """Arbitrary quad; ``facing`` orients the front side, ``double`` adds the back side."""
        tris = np.array([[p0, p1, p2], [p0, p2, p3]], np.float32)
        if facing is not None:
            tris = orient_to(tris, facing)
        self.add_tris(tris, color, jitter)
        if double:
            self.add_tris(tris[:, ::-1, :].copy(), color, jitter)
        return self

    def triangle(self, a: Sequence[float], b: Sequence[float], c: Sequence[float], color: Color,
                 facing: Sequence[float] | None = None, double: bool = False) -> "MeshBuilder":
        tris = np.array([[a, b, c]], np.float32)
        if facing is not None:
            tris = orient_to(tris, facing)
        self.add_tris(tris, color)
        if double:
            self.add_tris(tris[:, ::-1, :].copy(), color)
        return self

    def beam(self, a: Sequence[float], b: Sequence[float], thickness: float | Sequence[float],
             color: Color, jitter: float = 0.04, segments: int = 0, radius_b: float | None = None) -> "MeshBuilder":
        """Box (or cylinder when ``segments`` > 0) spanning from point ``a`` to ``b``."""
        pa = np.asarray(a, np.float32)
        pb = np.asarray(b, np.float32)
        d = pb - pa
        length = float(np.linalg.norm(d))
        if length < 1e-6:
            return self
        d /= length
        up = np.array([0, 1, 0], np.float32) if abs(d[1]) < 0.95 else np.array([1, 0, 0], np.float32)
        x = np.cross(up, d)
        x /= np.linalg.norm(x)
        z = np.cross(d, x)
        basis = np.stack([x, d, z], axis=1)  # columns map local x,y,z -> world
        if segments > 0:
            r0 = float(thickness if np.isscalar(thickness) else thickness[0])
            r1 = r0 if radius_b is None else radius_b
            local = _cylinder_tris(segments, r0, r1, length, True)
        else:
            t = np.broadcast_to(np.asarray(thickness, np.float32), (2,)) if not np.isscalar(thickness) \
                else np.array([thickness, thickness], np.float32)
            local = _BOX.copy() * np.array([t[0], length, t[1]], np.float32)
            local[:, :, 1] += length / 2
        world = local @ basis.T + pa
        return self.add_tris(world, color, jitter)

    # -- composition --------------------------------------------------------------
    def merge(self, other: "MeshBuilder", pos: Sequence[float] = (0, 0, 0),
              rot: Sequence[float] | None = None, scale: float | Sequence[float] = 1.0,
              tint: Color | None = None) -> "MeshBuilder":
        """Append a transformed copy of ``other``."""
        if other.is_empty():
            return self
        tris, cols = other.arrays()
        s = np.asarray(scale, np.float32)
        out = tris * s
        if rot is not None and any(rot):
            out = out @ rotation_matrix(rot).T
        out = out + np.asarray(pos, np.float32)
        if np.any(s < 0) and np.prod(np.broadcast_to(s, (3,))) < 0:
            out = out[:, ::-1, :].copy()
        cols = cols.copy()
        if tint is not None:
            cols[:, :3] *= np.asarray(tint, np.float32)[:3]
        self._tris.append(out.astype(np.float32))
        self._cols.append(cols)
        return self

    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """All triangles (n, 3, 3) and per-triangle colours (n, 4)."""
        if not self._tris:
            return np.zeros((0, 3, 3), np.float32), np.zeros((0, 4), np.float32)
        tris = np.concatenate(self._tris)
        cols = np.concatenate(self._cols)
        self._tris, self._cols = [tris], [cols]
        return tris, cols

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        tris, _ = self.arrays()
        pts = tris.reshape(-1, 3)
        return pts.min(axis=0), pts.max(axis=0)

    def build(self, name: str = "mesh") -> NodePath:
        """Create the Panda3D node for everything added so far."""
        tris, cols = self.arrays()
        if tris.shape[0] == 0:
            return NodePath(name)
        normals = np.repeat(tri_normals(tris), 3, axis=0)
        colors = np.repeat(cols, 3, axis=0)
        return make_geom_node(tris.reshape(-1, 3), normals, colors, name=name)


def grid_indices(nx: int, nz: int) -> np.ndarray:
    """Triangle indices for a (nz+1) x (nx+1) vertex grid laid out row-major along x."""
    i = np.arange(nz)[:, None] * (nx + 1) + np.arange(nx)[None, :]
    a = i
    b = i + 1
    c = i + nx + 2
    d = i + nx + 1
    # triangles (a, b, c) and (a, c, d) face +y in Ursina's convention
    tris = np.stack([np.stack([a, b, c], -1), np.stack([a, c, d], -1)], -2)
    return tris.reshape(-1, 3).astype(np.uint32)


def color_lerp(a: Color, b: Color, t: float) -> tuple[float, float, float, float]:
    ca = list(a) + [1.0] * (4 - len(a))
    cb = list(b) + [1.0] * (4 - len(b))
    return tuple(ca[i] + (cb[i] - ca[i]) * t for i in range(4))  # type: ignore[return-value]


def shade(c: Color, k: float) -> tuple[float, float, float, float]:
    """Multiply an RGB colour by ``k`` keeping alpha."""
    a = c[3] if len(c) > 3 else 1.0
    return (min(1.0, c[0] * k), min(1.0, c[1] * k), min(1.0, c[2] * k), a)


def hexcol(h: str, a: float = 1.0) -> tuple[float, float, float, float]:
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0, a)


def ring_points(n: int, radius: float, y: float = 0.0, phase: float = 0.0) -> Iterable[tuple[float, float, float]]:
    for i in range(n):
        a = phase + 2 * math.pi * i / n
        yield (math.cos(a) * radius, y, math.sin(a) * radius)
