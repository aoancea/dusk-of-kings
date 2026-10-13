"""Animated sea surface that follows the camera, plus a sea-floor skirt under it."""
from __future__ import annotations

import numpy as np
from panda3d.core import NodePath, TransparencyAttrib, Vec3

from core import shaders
from core.meshgen import grid_indices, make_geom_node
from settings import SEA_LEVEL


class Water:
    """A camera-following grid (snapped to its cell size so waves don't swim)."""

    def __init__(self, render: NodePath, depth_tex, depth_rect: tuple[float, float, float, float],
                 size: float = 640.0, cells: int = 128) -> None:
        self.cell = size / cells
        n = cells
        xs = (np.arange(n + 1, dtype=np.float32) - n / 2) * self.cell
        X, Z = np.meshgrid(xs, xs)
        pos = np.stack([X, np.zeros_like(X), Z], -1).reshape(-1, 3)
        nrm = np.tile(np.array([0, 1, 0], np.float32), (pos.shape[0], 1))
        col = np.ones((pos.shape[0], 4), np.float32)
        self.node = make_geom_node(pos, nrm, col, indices=grid_indices(n, n), name="water")
        self.node.reparentTo(render)
        self.node.setShader(shaders.water_shader())
        self.node.setShaderInput("u_depth_tex", depth_tex)
        self.node.setShaderInput("u_depth_rect", depth_rect)
        self.node.setTransparency(TransparencyAttrib.M_alpha)
        self.node.setBin("transparent", 10)
        self.node.setDepthWrite(False)
        self.node.setTwoSided(True)

        # sea floor skirt so the void is never visible through the water
        s = 3000.0
        fpos = np.array([[-s, -12.8, -s], [s, -12.8, -s], [s, -12.8, s], [-s, -12.8, s]], np.float32)
        fn = np.tile(np.array([0, 1, 0], np.float32), (4, 1))
        fc = np.tile(np.array([0.52, 0.44, 0.34, 1], np.float32), (4, 1))
        self.floor = make_geom_node(fpos, fn, fc, indices=np.array([0, 1, 2, 0, 2, 3], np.uint32), name="seafloor")

    def attach_floor(self, world_root: NodePath) -> None:
        self.floor.reparentTo(world_root)

    def update(self, cam_pos: Vec3) -> None:
        c = self.cell * 4
        self.node.setPos(round(cam_pos.x / c) * c, SEA_LEVEL, round(cam_pos.z / c) * c)

    def set_visible(self, visible: bool) -> None:
        if visible:
            self.node.show()
            self.floor.show()
        else:
            self.node.hide()
            self.floor.hide()
