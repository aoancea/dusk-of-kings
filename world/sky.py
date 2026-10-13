"""Day/night cycle, sky dome, fog and the global lighting uniforms shared by all shaders."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from panda3d.core import (LVecBase4f, NodePath, PTA_LVecBase4f, TransparencyAttrib, Vec3)

from core import shaders
from core.meshgen import _icosphere, make_geom_node
from core.textures import detail_texture
from core.util import clamp, lerp, smoothstep
from settings import DAY_LENGTH_SECONDS, START_HOUR

RGB = tuple[float, float, float]

# hour -> (zenith, horizon, light colour, ambient sky, ambient ground, fog)
_KEYS: list[tuple[float, tuple[RGB, RGB, RGB, RGB, RGB, RGB]]] = [
    (0.0, ((0.02, 0.03, 0.08), (0.08, 0.09, 0.17), (0.30, 0.36, 0.58), (0.26, 0.29, 0.45), (0.14, 0.13, 0.18), (0.07, 0.08, 0.14))),
    (4.6, ((0.03, 0.04, 0.10), (0.12, 0.11, 0.20), (0.30, 0.35, 0.56), (0.27, 0.29, 0.44), (0.15, 0.13, 0.18), (0.10, 0.10, 0.17))),
    (6.0, ((0.24, 0.34, 0.58), (0.96, 0.56, 0.36), (1.00, 0.58, 0.32), (0.46, 0.40, 0.45), (0.30, 0.19, 0.15), (0.86, 0.56, 0.42))),
    (8.0, ((0.26, 0.50, 0.84), (0.86, 0.76, 0.64), (1.00, 0.87, 0.70), (0.50, 0.50, 0.58), (0.36, 0.24, 0.18), (0.86, 0.75, 0.62))),
    (13.0, ((0.22, 0.46, 0.86), (0.92, 0.83, 0.70), (1.00, 0.93, 0.80), (0.52, 0.52, 0.60), (0.40, 0.27, 0.20), (0.91, 0.80, 0.66))),
    (16.5, ((0.24, 0.46, 0.80), (0.94, 0.78, 0.60), (1.00, 0.84, 0.64), (0.50, 0.47, 0.52), (0.38, 0.24, 0.17), (0.92, 0.75, 0.58))),
    (18.6, ((0.20, 0.24, 0.50), (0.98, 0.46, 0.26), (1.00, 0.48, 0.22), (0.42, 0.32, 0.36), (0.27, 0.15, 0.12), (0.82, 0.44, 0.31))),
    (20.0, ((0.05, 0.06, 0.18), (0.34, 0.20, 0.30), (0.32, 0.34, 0.56), (0.28, 0.28, 0.45), (0.15, 0.12, 0.15), (0.19, 0.14, 0.21))),
    (24.0, ((0.02, 0.03, 0.08), (0.08, 0.09, 0.17), (0.30, 0.36, 0.58), (0.26, 0.29, 0.45), (0.14, 0.13, 0.18), (0.07, 0.08, 0.14))),
]

_UNDERGROUND = ((0.0, 0.0, 0.0), (0.02, 0.015, 0.01), (0.10, 0.08, 0.07), (0.20, 0.16, 0.14),
                (0.12, 0.09, 0.08), (0.02, 0.016, 0.012))


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return (lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t))


@dataclass
class PointLight:
    """A light source that the world shader can use when it is near the camera."""

    pos: tuple[float, float, float]
    radius: float
    color: RGB
    intensity: float = 1.0
    flicker: float = 0.0
    night_boost: float = 1.0
    enabled: bool = True


class Environment:
    """Owns time of day and pushes lighting/fog uniforms to the render root every frame."""

    MAX_LIGHTS = 8

    def __init__(self, render: NodePath, view_distance: float) -> None:
        self.render = render
        self.hour = START_HOUR
        self.time_scale = 1.0
        self.view_distance = view_distance
        self.underground = False
        self.lights: list[PointLight] = []
        self.focus: tuple[float, float] | None = None
        self._light_timer = 0.0
        self._active: list[PointLight] = []
        self._t = 0.0
        self.night = 0.0
        self.sun_dir = Vec3(0, 1, 0)
        self.light_color: RGB = (1, 1, 1)
        self.fog_color: RGB = (0.8, 0.7, 0.6)
        self.palette = _KEYS[0][1]

        self._pos = PTA_LVecBase4f.emptyArray(self.MAX_LIGHTS)
        self._col = PTA_LVecBase4f.emptyArray(self.MAX_LIGHTS)
        r = render
        r.setShaderInput("u_lights_pos", self._pos)
        r.setShaderInput("u_lights_col", self._col)
        r.setShaderInput("u_num_lights", 0)
        r.setShaderInput("u_emissive", 0.0)
        r.setShaderInput("u_detail", 0.0)
        r.setShaderInput("u_rim", 0.0)
        r.setShaderInput("u_flame", 0.0)
        r.setShaderInput("u_detail_tex", detail_texture())
        r.setShaderInput("u_underground", 0.0)
        self._apply_uniforms(Vec3(0, 0, 0))
        self.sky = self._build_sky()

    # ------------------------------------------------------------------ building
    def _build_sky(self) -> NodePath:
        tris = _icosphere(2)[:, ::-1, :].copy()  # inward facing
        n = tris.shape[0] * 3
        node = make_geom_node(tris.reshape(-1, 3), np.zeros((n, 3), np.float32),
                              np.ones((n, 4), np.float32), name="sky")
        node.reparentTo(self.render)
        node.setShader(shaders.sky_shader())
        node.setBin("background", 0)
        node.setDepthWrite(False)
        node.setDepthTest(False)
        node.setLightOff(1)
        node.setTransparency(TransparencyAttrib.M_none)
        node.setScale(400)
        return node

    # ------------------------------------------------------------------- lights
    def add_light(self, light: PointLight) -> PointLight:
        self.lights.append(light)
        return light

    def remove_light(self, light: PointLight) -> None:
        if light in self.lights:
            self.lights.remove(light)

    def _update_lights(self, dt: float, cam: Vec3) -> None:
        self._light_timer -= dt
        if self._light_timer <= 0:
            self._light_timer = 0.25
            cands = [l for l in self.lights if l.enabled]
            fx, fz = self.focus if self.focus is not None else (cam.x, cam.z)
            cands.sort(key=lambda l: (l.pos[0] - fx) ** 2 + (l.pos[2] - fz) ** 2)
            self._active = cands[: self.MAX_LIGHTS]
        t = self._t
        boost = 1.0 + self.night * 1.4 if not self.underground else 2.2
        for i, l in enumerate(self._active):
            k = l.intensity * (1.0 + (boost - 1.0) * l.night_boost)
            if l.flicker:
                k *= 1.0 + l.flicker * (math.sin(t * 13.0 + i * 1.7) * 0.5 + math.sin(t * 7.3 + i) * 0.5)
            self._pos.setElement(i, LVecBase4f(l.pos[0], l.pos[1], l.pos[2], l.radius))
            self._col.setElement(i, LVecBase4f(l.color[0], l.color[1], l.color[2], k))
        self.render.setShaderInput("u_num_lights", len(self._active))

    # --------------------------------------------------------------------- time
    def _palette(self) -> tuple[RGB, ...]:
        h = self.hour
        for (h0, p0), (h1, p1) in zip(_KEYS[:-1], _KEYS[1:]):
            if h0 <= h <= h1:
                t = (h - h0) / (h1 - h0)
                t = t * t * (3 - 2 * t)
                return tuple(_mix(a, b, t) for a, b in zip(p0, p1))
        return _KEYS[0][1]

    def set_underground(self, value: bool) -> None:
        self.underground = value
        if value:
            self.sky.hide()
        else:
            self.sky.show()
        self.render.setShaderInput("u_underground", 1.0 if value else 0.0)

    def update(self, dt: float, cam_pos: Vec3) -> None:
        self._t += dt
        self.hour = (self.hour + dt * 24.0 / DAY_LENGTH_SECONDS * self.time_scale) % 24.0
        self._apply_uniforms(cam_pos)
        self._update_lights(dt, cam_pos)
        self.sky.setPos(cam_pos)

    def _apply_uniforms(self, cam_pos: Vec3) -> None:
        a = (self.hour - 6.0) / 12.0 * math.pi
        sun = Vec3(math.cos(a), math.sin(a), -0.38)
        sun.normalize()
        moon = Vec3(-sun.x, -sun.y, -0.3)
        moon.normalize()
        self.night = clamp((0.12 - sun.y) / 0.3, 0.0, 1.0)
        if self.underground:
            pal = _UNDERGROUND
            light_dir = Vec3(0.3, 1.0, 0.2)
        else:
            pal = self._palette()
            src = sun if sun.y > -0.02 else moon
            light_dir = Vec3(src.x, max(src.y, 0.2), src.z)
        light_dir.normalize()
        zen, hor, lc, amb_s, amb_g, fog = pal
        horizon_dim = smoothstep(-0.08, 0.12, abs(sun.y))
        lc = tuple(c * (0.55 + 0.45 * horizon_dim) for c in lc)
        self.palette = pal
        self.sun_dir = light_dir
        self.light_color = lc  # type: ignore[assignment]
        self.fog_color = fog
        r = self.render
        r.setShaderInput("u_sun_dir", light_dir)
        r.setShaderInput("u_sun_color", Vec3(*lc))
        r.setShaderInput("u_amb_sky", Vec3(*amb_s))
        r.setShaderInput("u_amb_ground", Vec3(*amb_g))
        r.setShaderInput("u_fog_color", Vec3(*fog))
        vd = self.view_distance if not self.underground else 70.0
        start = vd * (0.30 if not self.underground else 0.15)
        r.setShaderInput("u_fog_range", (start, vd))
        r.setShaderInput("u_cam_pos", cam_pos)
        r.setShaderInput("u_sky_zenith", Vec3(*zen))
        r.setShaderInput("u_sky_horizon", Vec3(*hor))
        r.setShaderInput("u_moon_dir", moon)
        r.setShaderInput("u_night", self.night)
        r.setShaderInput("u_sky_sun", sun)

    @property
    def clock_text(self) -> str:
        h = int(self.hour)
        m = int((self.hour - h) * 60)
        return f"{h:02d}:{m:02d}"
