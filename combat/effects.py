"""Visual combat effects: projectiles, batched particles, shockwave rings and decals."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Callable

import numpy as np
from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData, NodePath, OmniBoundingVolume,
                          TransparencyAttrib, Vec3)

from core.meshgen import MeshBuilder, _vertex_format, make_geom_node
from core.textures import radial_texture, ring_texture

if TYPE_CHECKING:
    from core.match import Match

_protos: dict[str, NodePath] = {}


def _proto(name: str, build: Callable[[], MeshBuilder]) -> NodePath:
    if name not in _protos:
        _protos[name] = build().build(name)
    return _protos[name]


def _arrow(shaft=(0.55, 0.4, 0.25, 1), head=(0.7, 0.7, 0.72, 1), fletch=(0.9, 0.9, 0.85, 1)) -> Callable[[], MeshBuilder]:
    def b() -> MeshBuilder:
        mb = MeshBuilder()
        mb.beam((0, 0, -0.5), (0, 0, 0.5), 0.03, shaft, segments=3)
        mb.cone((0, 0, 0.5), 0.06, 0.16, head, rot=(90, 0, 0), segments=4)
        mb.box((0, 0, -0.45), (0.16, 0.01, 0.14), fletch)
        return mb
    return b


def _spear() -> MeshBuilder:
    mb = MeshBuilder()
    mb.beam((0, 0, -0.8), (0, 0, 0.8), 0.04, (0.45, 0.32, 0.2, 1), segments=3)
    mb.cone((0, 0, 0.8), 0.08, 0.3, (0.75, 0.75, 0.78, 1), rot=(90, 0, 0), segments=4)
    return mb


def _orb(color: tuple, size: float = 0.28) -> Callable[[], MeshBuilder]:
    def b() -> MeshBuilder:
        mb = MeshBuilder()
        mb.sphere((0, 0, 0), size, color, detail=1)
        mb.sphere((0, 0, 0), size * 0.6, (1.0, 0.95, 0.75, 1), detail=0)
        return mb
    return b


def _rock(fire: bool) -> Callable[[], MeshBuilder]:
    def b() -> MeshBuilder:
        mb = MeshBuilder()
        mb.sphere((0, 0, 0), 0.45, (0.42, 0.38, 0.34, 1), detail=0, noise=0.3, seed=3)
        if fire:
            mb.sphere((0, 0.1, 0), 0.38, (1.0, 0.5, 0.1, 1), detail=0, noise=0.3, seed=4)
        return mb
    return b


# kind -> (proto name, builder, speed, arc height factor, impact particle, emissive, splash ring)
PROJECTILES: dict[str, tuple] = {
    "arrow": ("arrow", _arrow(), 42.0, 0.12, "spark", 1.0),
    "dark_arrow": ("dark_arrow", _arrow((0.2, 0.15, 0.12, 1), (0.35, 0.3, 0.3, 1), (0.25, 0.05, 0.05, 1)), 42.0, 0.12, "spark", 1.0),
    "spear": ("spear", _spear, 34.0, 0.08, "spark", 1.0),
    "frost": ("frost", _orb((0.5, 0.8, 1.0, 1), 0.22), 30.0, 0.05, "frost", 1.6),
    "ember": ("ember", _orb((1.0, 0.55, 0.15, 1), 0.22), 28.0, 0.08, "fire", 1.6),
    "fireball": ("fireball", _orb((1.0, 0.45, 0.1, 1), 0.45), 22.0, 0.15, "fire", 1.8),
    "boulder": ("boulder", _rock(False), 20.0, 0.32, "dust", 1.0),
    "fire_rock": ("fire_rock", _rock(True), 20.0, 0.32, "fire", 1.3),
}

PARTICLE_COLORS = {
    "spark": (1.0, 0.85, 0.5), "fire": (1.0, 0.5, 0.12), "blood": (0.65, 0.07, 0.05), "heal": (0.35, 1.0, 0.5),
    "frost": (0.6, 0.85, 1.0), "dust": (0.72, 0.6, 0.45), "gold": (1.0, 0.85, 0.3), "wood": (0.6, 0.42, 0.22),
    "smoke": (0.25, 0.23, 0.22), "magic": (0.8, 0.5, 1.0), "debris": (0.5, 0.45, 0.4),
}


class Projectile:
    """A homing (or ground-targeted) missile that calls ``on_hit`` when it lands."""

    def __init__(self, node: NodePath, start: Vec3, target, point: Vec3 | None, speed: float, arc: float,
                 on_hit: Callable[[Vec3], None] | None, impact: str) -> None:
        self.node = node
        self.target = target
        self.point = point
        self.speed = speed
        self.on_hit = on_hit
        self.impact = impact
        self.pos = Vec3(start)
        self.start = Vec3(start)
        end = self._target_pos()
        self.total = max(0.5, (end - self.pos).length())
        self.arc = arc * self.total
        self.t = 0.0
        self.alive = True

    def _target_pos(self) -> Vec3:
        t = self.target
        if t is not None and t.alive:
            self.point = Vec3(t.x, t.y + min(t.height * 0.5, 2.0), t.z)
        return Vec3(self.point)

    def update(self, dt: float, fx: "EffectsManager") -> bool:
        self.t += dt
        tp = self._target_pos()
        d = tp - self.pos
        dist = d.length()
        step = self.speed * dt
        if dist <= step or self.t > 6.0:
            if self.on_hit:
                self.on_hit(tp)
            fx.burst(tp, self.impact, 6)
            return False
        d.normalize()
        self.pos += d * step
        done = 1.0 - dist / self.total
        lift = math.sin(max(0.0, min(done, 1.0)) * math.pi) * self.arc
        p = Vec3(self.pos.x, self.pos.y + lift, self.pos.z)
        ahead = Vec3(self.pos.x + d.x, self.pos.y + d.y + math.cos(done * math.pi) * self.arc * math.pi / self.total, self.pos.z + d.z)
        self.node.setPos(p)
        self.node.lookAt(ahead, Vec3(0, 1, 0))
        return True


class ParticleBatch:
    """Up to ``cap`` camera-facing square particles drawn in one call."""

    def __init__(self, parent: NodePath, cap: int = 900) -> None:
        self.cap = cap
        self.pos = np.zeros((cap, 3), np.float32)
        self.vel = np.zeros((cap, 3), np.float32)
        self.col = np.zeros((cap, 4), np.float32)
        self.size = np.zeros(cap, np.float32)
        self.life = np.zeros(cap, np.float32)
        self.age = np.zeros(cap, np.float32)
        self.grav = np.zeros(cap, np.float32)
        self.n = 0
        fmt = _vertex_format(True)
        self.vdata = GeomVertexData("particles", fmt, Geom.UH_dynamic)
        self.vdata.uncleanSetNumRows(cap * 4)
        self.buf = np.zeros((cap * 4, 12), np.float32)
        self.buf[:, 3:6] = (0, 1, 0)
        self.buf[:, 10:12] = np.tile(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32), (cap, 1))
        memoryview(self.vdata.modifyArray(0)).cast("B")[:] = self.buf.tobytes()  # never leave GPU memory uninitialised
        prim = GeomTriangles(Geom.UH_static)
        prim.setIndexType(Geom.NT_uint32)
        base = (np.arange(cap, dtype=np.uint32) * 4)[:, None]
        idx = (base + np.array([0, 1, 2, 0, 2, 3], np.uint32)[None, :]).ravel()
        parr = prim.modifyVertices()
        parr.uncleanSetNumRows(len(idx))
        memoryview(parr).cast("B")[:] = idx.tobytes()
        prim.closePrimitive()
        geom = Geom(self.vdata)
        geom.addPrimitive(prim)
        gn = GeomNode("particles")
        gn.addGeom(geom)
        gn.setBounds(OmniBoundingVolume())
        gn.setFinal(True)
        self.node = parent.attachNewNode(gn)
        self.node.setTexture(radial_texture(32, 0.0, 1.0, (255, 255, 255), power=1.2), 1)
        self.node.setTransparency(TransparencyAttrib.M_alpha)
        self.node.setDepthWrite(False)
        self.node.setBin("transparent", 30)
        self.node.setShaderInput("u_emissive", 1.0)
        self.node.setTwoSided(True)

    def emit(self, pos: tuple[float, float, float], color: tuple[float, float, float], count: int, speed: float,
             life: float, size: float, gravity: float = 9.0, up: float = 1.0, alpha: float = 1.0) -> None:
        count = min(count, self.cap - self.n)
        if count <= 0:
            return
        s = slice(self.n, self.n + count)
        v = np.random.uniform(-1, 1, (count, 3)).astype(np.float32)
        v[:, 1] = np.random.uniform(0.2, 1.0, count) * up
        v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-6
        self.pos[s] = pos
        self.vel[s] = v * speed * np.random.uniform(0.4, 1.0, (count, 1))
        self.col[s, :3] = color
        self.col[s, 3] = alpha
        self.size[s] = size * np.random.uniform(0.6, 1.3, count)
        self.life[s] = life * np.random.uniform(0.7, 1.2, count)
        self.age[s] = 0
        self.grav[s] = gravity
        self.n += count

    def update(self, dt: float, cam_right: np.ndarray, cam_up: np.ndarray) -> None:
        n = self.n
        if n:
            self.age[:n] += dt
            alive = self.age[:n] < self.life[:n]
            if not alive.all():
                k = int(alive.sum())
                for arr in (self.pos, self.vel, self.col, self.size, self.life, self.age, self.grav):
                    arr[:k] = arr[:n][alive]
                n = self.n = k
        buf = self.buf
        prev_used = getattr(self, "_used", 0)
        if n:
            self.vel[:n, 1] -= self.grav[:n] * dt
            self.vel[:n] *= (1.0 - 1.2 * dt)
            self.pos[:n] += self.vel[:n] * dt
            fade = np.clip(1.0 - self.age[:n] / self.life[:n], 0, 1)
            s = self.size[:n, None]
            r = cam_right[None, :] * s
            u = cam_up[None, :] * s
            p = self.pos[:n]
            v = buf[: n * 4].reshape(n, 4, 12)
            v[:, 0, 0:3] = p - r - u
            v[:, 1, 0:3] = p + r - u
            v[:, 2, 0:3] = p + r + u
            v[:, 3, 0:3] = p - r + u
            c = self.col[:n].copy()
            c[:, 3] *= fade
            v[:, :, 6:10] = c[:, None, :]
        if prev_used > n:
            buf[n * 4: prev_used * 4, 0:3] = 0
            buf[n * 4: prev_used * 4, 9] = 0
        self._used = n
        if n or prev_used:
            memoryview(self.vdata.modifyArray(0)).cast("B")[:] = buf.tobytes()


class Ring:
    """Expanding flat ring (shockwaves, splash, ability feedback)."""

    def __init__(self, fx: "EffectsManager", x: float, y: float, z: float, radius: float,
                 color: tuple, life: float) -> None:
        self.node = fx.flat_quad("ring", fx.ring_tex)
        self.node.reparentTo(fx.root)
        self.node.setPos(x, y + 0.2, z)
        self.node.setColorScale(*color)
        self.radius = radius
        self.life = life
        self.t = 0.0
        self.color = color

    def update(self, dt: float, fx: "EffectsManager") -> bool:
        self.t += dt
        k = self.t / self.life
        self.node.setScale(self.radius * (0.3 + 0.7 * k))
        self.node.setAlphaScale(max(0.0, 1.0 - k) * self.color[3])
        return self.t < self.life


class EffectsManager:
    """Owns all short-lived effects of a match."""

    def __init__(self, match: "Match") -> None:
        self.match = match
        self.root = match.fx_root.attachNewNode("effects")
        self.projectiles: list[Projectile] = []
        self.rings: list[Ring] = []
        self.particles = ParticleBatch(self.root)
        self.ring_tex = ring_texture(128, 0.16)
        self._quad_proto: NodePath | None = None

    def flat_quad(self, name: str, tex) -> NodePath:
        if self._quad_proto is None:
            pos = np.array([[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]], np.float32)
            uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
            nrm = np.tile(np.array([0, 1, 0], np.float32), (4, 1))
            col = np.ones((4, 4), np.float32)
            self._quad_proto = make_geom_node(pos, nrm, col, uvs=uvs, indices=np.array([0, 1, 2, 0, 2, 3], np.uint32), name=name)
        node = self._quad_proto.copyTo(self.root)
        node.setTexture(tex, 1)
        node.setTransparency(TransparencyAttrib.M_alpha)
        node.setDepthWrite(False)
        node.setBin("transparent", 6)
        node.setShaderInput("u_emissive", 1.0)
        node.setTwoSided(True)
        return node

    # ------------------------------------------------------------------ spawners
    def projectile(self, source, target, kind: str, on_hit: Callable[[Vec3], None] | None = None,
                   point: tuple[float, float, float] | None = None) -> None:
        name, build, speed, arc, impact, emissive = PROJECTILES.get(kind, PROJECTILES["arrow"])
        node = _proto(name, build).copyTo(self.root)
        if emissive > 1.0:
            node.setShaderInput("u_emissive", emissive)
        if not source.visible:
            node.hide()
        h = min(source.height * 0.7, 2.6) if not source.is_building else source.height * 0.85
        start = Vec3(source.x, source.y + h, source.z)
        pt = Vec3(*point) if point is not None else None
        self.projectiles.append(Projectile(node, start, target, pt, speed, arc, on_hit, impact))

    def burst(self, pos, kind: str = "spark", count: int = 8, speed: float = 4.0, life: float = 0.45,
              size: float = 0.13, gravity: float = 9.0, up: float = 1.0) -> None:
        c = PARTICLE_COLORS.get(kind, PARTICLE_COLORS["spark"])
        self.particles.emit((pos[0], pos[1], pos[2]), c, count, speed, life, size, gravity, up)

    def hit(self, actor, kind: str = "blood") -> None:
        if actor.visible:
            self.burst((actor.x, actor.y + min(actor.height, 3.0) * 0.55, actor.z), kind, 5, 3.5, 0.4, 0.11)

    def explosion(self, x: float, y: float, z: float, radius: float, kind: str = "fire") -> None:
        self.burst((x, y + 0.5, z), kind, 26, 7.0 * radius / 2.5, 0.7, 0.28, gravity=6.0)
        self.burst((x, y + 0.5, z), "smoke", 12, 2.5, 1.4, 0.45, gravity=-1.5)
        self.rings.append(Ring(self, x, y, z, radius * 1.2, (1.0, 0.7, 0.4, 0.9), 0.45))

    def ring(self, x: float, y: float, z: float, radius: float, color: tuple, life: float = 0.5) -> None:
        self.rings.append(Ring(self, x, y, z, radius, color, life))

    def heal(self, actor) -> None:
        self.burst((actor.x, actor.y + 0.6, actor.z), "heal", 14, 2.0, 0.9, 0.14, gravity=-4.0)

    def collapse(self, x: float, y: float, z: float, size: float) -> None:
        self.burst((x, y + 1.0, z), "debris", 40, 6.0, 1.0, 0.35, gravity=9.0)
        self.burst((x, y + 1.0, z), "smoke", 30, 3.0, 2.2, 0.9, gravity=-1.2)
        self.burst((x, y + 1.0, z), "fire", 18, 4.0, 0.8, 0.35, gravity=-2.0)

    # ------------------------------------------------------------------ update
    def update(self, dt: float, cam_right: np.ndarray, cam_up: np.ndarray) -> None:
        keep = []
        for p in self.projectiles:
            if p.update(dt, self):
                keep.append(p)
            else:
                p.node.removeNode()
        self.projectiles = keep
        rk = []
        for r in self.rings:
            if r.update(dt, self):
                rk.append(r)
            else:
                r.node.removeNode()
        self.rings = rk
        self.particles.update(dt, cam_right, cam_up)

    def clear(self) -> None:
        for p in self.projectiles:
            p.node.removeNode()
        for r in self.rings:
            r.node.removeNode()
        self.projectiles.clear()
        self.rings.clear()
