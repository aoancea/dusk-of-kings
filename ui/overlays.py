"""Batched dynamic quads: blob shadows, selection rings (3D) and health bars (2D), one draw call each."""
from __future__ import annotations

import numpy as np
from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData, NodePath, OmniBoundingVolume,
                          TransparencyAttrib)

from core.meshgen import _vertex_format


class QuadBatch:
    """Up to ``capacity`` textured, coloured quads rewritten every frame.

    3D mode lays quads flat on the ground (x, y, z, half-size). 2D mode draws screen-aligned
    rectangles in Ursina UI coordinates (x0, y0, x1, y1).
    """

    def __init__(self, parent: NodePath, capacity: int, texture=None, name: str = "quads", flat3d: bool = True) -> None:
        self.cap = capacity
        self.flat3d = flat3d
        n = capacity * 4
        fmt = _vertex_format(True)
        self.vdata = GeomVertexData(name, fmt, Geom.UH_dynamic)
        self.vdata.uncleanSetNumRows(n)
        self.buf = np.zeros((n, 12), np.float32)
        if flat3d:
            self.buf[:, 3:6] = (0, 1, 0)
        else:
            self.buf[:, 3:6] = (0, 0, -1)
        uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
        self.buf[:, 10:12] = np.tile(uv, (capacity, 1))
        memoryview(self.vdata.modifyArray(0)).cast("B")[:] = self.buf.tobytes()
        prim = GeomTriangles(Geom.UH_static)
        prim.setIndexType(Geom.NT_uint32)
        base = (np.arange(capacity, dtype=np.uint32) * 4)[:, None]
        idx = (base + np.array([0, 1, 2, 0, 2, 3], np.uint32)[None, :]).ravel()
        if not flat3d:
            idx = (base + np.array([0, 2, 1, 0, 3, 2], np.uint32)[None, :]).ravel()
        parr = prim.modifyVertices()
        parr.uncleanSetNumRows(len(idx))
        memoryview(parr).cast("B")[:] = idx.tobytes()
        prim.closePrimitive()
        geom = Geom(self.vdata)
        geom.addPrimitive(prim)
        node = GeomNode(name)
        node.addGeom(geom)
        node.setBounds(OmniBoundingVolume())
        node.setFinal(True)
        self.node = parent.attachNewNode(node)
        if texture is not None:
            self.node.setTexture(texture, 1)
        self.node.setTransparency(TransparencyAttrib.M_alpha)
        self.node.setDepthWrite(False)
        self.node.setTwoSided(True)
        self.count = 0
        self._pos = np.zeros((capacity, 4), np.float32)
        self._col = np.zeros((capacity, 4), np.float32)

    def set(self, rects: np.ndarray, colors: np.ndarray) -> None:
        """Replace all quads. ``rects``: (n, 4); ``colors``: (n, 4) RGBA."""
        n = min(len(rects), self.cap)
        buf = self.buf
        if n:
            r = rects[:n]
            v = buf[: n * 4].reshape(n, 4, 12)
            if self.flat3d:
                x, y, z, s = r[:, 0], r[:, 1], r[:, 2], r[:, 3]
                v[:, 0, 0], v[:, 0, 2] = x - s, z - s
                v[:, 1, 0], v[:, 1, 2] = x + s, z - s
                v[:, 2, 0], v[:, 2, 2] = x + s, z + s
                v[:, 3, 0], v[:, 3, 2] = x - s, z + s
                v[:, :, 1] = y[:, None]
            else:
                x0, y0, x1, y1 = r[:, 0], r[:, 1], r[:, 2], r[:, 3]
                v[:, 0, 0], v[:, 0, 1] = x0, y0
                v[:, 1, 0], v[:, 1, 1] = x1, y0
                v[:, 2, 0], v[:, 2, 1] = x1, y1
                v[:, 3, 0], v[:, 3, 1] = x0, y1
                v[:, :, 2] = 0
            v[:, :, 6:10] = colors[:n, None, :]
        if self.count > n:
            buf[n * 4: self.count * 4, 0:3] = 0
            buf[n * 4: self.count * 4, 6:10] = 0
        self.count = n
        handle = self.vdata.modifyArray(0)
        memoryview(handle).cast("B")[:] = buf.tobytes()

    def clear(self) -> None:
        self.set(np.zeros((0, 4), np.float32), np.zeros((0, 4), np.float32))

    def destroy(self) -> None:
        self.node.removeNode()
