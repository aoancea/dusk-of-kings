"""Base class for procedurally animated low-poly characters built from rigid parts."""
from __future__ import annotations

import math

import numpy as np
from panda3d.core import NodePath, TransparencyAttrib

from core.meshgen import MeshBuilder, make_geom_node
from core.textures import radial_texture
from core.util import set_rot

_mesh_cache: dict[tuple, NodePath] = {}
part_arrays: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}   # key -> (triangles, colours) for GPU skinning
_shadow_tex = None


def copy_part(key: tuple, build, parent: NodePath) -> NodePath:
    """Attach a copy of a cached part mesh to ``parent``, building it on first use.

    ``build`` is a zero-argument function returning a MeshBuilder; copies share vertex data.
    The node is tagged with ``key`` so :mod:`units.skinning` can rebuild it as a skinned mesh.
    """
    proto = _mesh_cache.get(key)
    if proto is None:
        mb: MeshBuilder = build()
        tris, cols = mb.arrays()
        part_arrays[key] = (tris.copy(), cols.copy())
        proto = mb.build(str(key[0]))
        _mesh_cache[key] = proto
    node = proto.copyTo(parent)
    node.setPythonTag("part_key", key)
    return node


def blob_shadow(parent: NodePath, radius: float) -> NodePath:
    """Soft dark disc laid on the ground under a character."""
    global _shadow_tex
    if _shadow_tex is None:
        _shadow_tex = radial_texture(64, 0.0, 1.0, (0, 0, 0), power=1.3)
    r = radius
    pos = np.array([[-r, 0, -r], [r, 0, -r], [r, 0, r], [-r, 0, r]], np.float32)
    uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
    nrm = np.tile(np.array([0, 1, 0], np.float32), (4, 1))
    col = np.tile(np.array([1, 1, 1, 0.6], np.float32), (4, 1))
    idx = np.array([0, 1, 2, 0, 2, 3], np.uint32)
    node = make_geom_node(pos, nrm, col, uvs=uvs, indices=idx, name="shadow")
    node.reparentTo(parent)
    node.setTexture(_shadow_tex, 1)
    node.setTransparency(TransparencyAttrib.M_alpha)
    node.setDepthWrite(False)
    node.setBin("transparent", 0)
    node.setShaderInput("u_emissive", 1.0)
    node.setTwoSided(True)
    return node


class Rig:
    """A character model: ``root`` holds rigid part NodePaths animated in code."""

    height = 2.0
    radius = 0.5

    def __init__(self) -> None:
        self.root = NodePath("rig")
        self.body = self.root.attachNewNode("body")
        self.parts: dict[str, NodePath] = {}
        self.phase = 0.0
        self.move_blend = 0.0
        self.action: str | None = None
        self.action_t = 0.0
        self.action_dur = 0.0
        self.dead = False
        self.death_t = 0.0
        self.flash_t = 0.0
        self.idle_t = 0.0
        self.scale = 1.0

    # --- actions ----------------------------------------------------------------
    def play(self, action: str, duration: float = 0.4) -> None:
        if self.dead and action != "death":
            return
        self.action = action
        self.action_t = 0.0
        self.action_dur = max(duration, 0.05)

    def action_progress(self) -> float:
        if not self.action:
            return 0.0
        return min(self.action_t / self.action_dur, 1.0)

    def die(self) -> None:
        self.dead = True
        self.death_t = 0.0
        self.action = None

    def revive(self) -> None:
        self.dead = False
        self.death_t = 0.0
        set_rot(self.body, 0, 0, 0)
        self.body.setPos(0, 0, 0)

    def flash(self, duration: float = 0.12) -> None:
        self.flash_t = duration

    # --- per frame ---------------------------------------------------------------
    def update(self, dt: float, speed: float, grounded: bool = True, swimming: bool = False) -> None:
        """``speed`` is horizontal speed in units/second."""
        self.idle_t += dt
        target_blend = min(speed / 5.0, 1.0)
        self.move_blend += (target_blend - self.move_blend) * min(dt * 10.0, 1.0)
        self.phase += dt * (2.0 + speed * 1.35)
        if self.action:
            self.action_t += dt
            if self.action_t >= self.action_dur:
                self.action = None
        if self.flash_t > 0:
            self.flash_t -= dt
            k = 1.0 + 2.2 * max(self.flash_t, 0) / 0.12
            self.root.setColorScale(k, k * 0.8, k * 0.8, 1)
            if self.flash_t <= 0:
                self.root.clearColorScale()
        if self.dead:
            self.death_t += dt
            self._pose_death(min(self.death_t / 0.6, 1.0))
        else:
            self._pose(dt, speed, grounded, swimming)

    def _pose(self, dt: float, speed: float, grounded: bool, swimming: bool) -> None:
        pass

    def _pose_death(self, t: float) -> None:
        e = 1 - (1 - t) ** 3
        set_rot(self.body, -85 * e, 0, 8 * e)
        self.body.setY(-0.1 * e)

    def destroy(self) -> None:
        self.root.removeNode()


def swing(phase: float, amount: float) -> float:
    return math.sin(phase) * amount
