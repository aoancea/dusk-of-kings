"""Square minimap: terrain, fog of war, units, buildings, mines, camera frame; click to look / order."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import SamplerState, Texture as PTexture
from ursina import Entity, color, held_keys, mouse

from core.events import events
from settings import SEA_LEVEL

if TYPE_CHECKING:
    from core.game import Game

RES = 224


class Minimap:
    """Composited every few frames in numpy and uploaded as one texture."""

    def __init__(self, game: "Game", parent: Entity, center: tuple[float, float], size: float) -> None:
        self.game = game
        self.size = size
        self.center = center
        self.frame = Entity(parent=parent, model="quad", position=(center[0], center[1], 0.004), scale=size + 0.01,
                            color=color.rgba(0.55, 0.42, 0.22, 1))
        self.entity = Entity(parent=parent, model="quad", position=(center[0], center[1], -0.002), scale=size,
                             collider="box", color=color.white)
        self.tex = PTexture("minimap")
        self.tex.setup2dTexture(RES, RES, PTexture.T_unsigned_byte, PTexture.F_rgb8)
        self.tex.setMinfilter(SamplerState.FT_linear)
        self.tex.setMagfilter(SamplerState.FT_linear)
        self.tex.setWrapU(SamplerState.WM_clamp)
        self.tex.setWrapV(SamplerState.WM_clamp)
        self.entity.model.setTexture(self.tex, 1)
        self.base_img: np.ndarray | None = None
        self.match = None
        self._t = 0.0
        self.dragging = False
        self.pings: list[tuple[float, float, float]] = []
        events.on("alert", self._on_alert)

    # ------------------------------------------------------------------ setup
    def attach(self, match) -> None:
        self.match = match
        ter = match.terrain
        h = ter.h[:-1, :-1]
        h = (h + ter.h[1:, 1:]) * 0.5
        from world.terrain import PALETTES
        pal = PALETTES.get(match.map.palette, PALETTES["fen"])
        g = np.asarray(pal["grass"], np.float32)
        hi = np.asarray(pal["heath"], np.float32)
        rock = np.asarray(pal["rock"], np.float32)
        mud = np.asarray(pal["mud"], np.float32)
        gx = np.abs(np.gradient(ter.h, axis=1))[:-1, :-1]
        gz = np.abs(np.gradient(ter.h, axis=0))[:-1, :-1]
        slope = np.maximum(gx, gz)
        k = np.clip((h - 2.5) / 4.0, 0, 1)[..., None]
        img = g[None, None, :] * (1 - k) + hi[None, None, :] * k
        steep = np.clip((slope - 0.6) / 0.6, 0, 1)[..., None]
        img = img * (1 - steep) + rock[None, None, :] * steep
        peak = np.clip((h - 9.0) / 6.0, 0, 1)[..., None]
        img = img * (1 - peak) + np.asarray(pal["peak"], np.float32)[None, None, :] * peak
        wet = np.clip((0.8 - h) / 0.7, 0, 1)[..., None]
        img = img * (1 - wet) + mud[None, None, :] * wet
        water = (h < SEA_LEVEL - 0.05)[..., None]
        deep = np.clip(-h / 1.5, 0, 1)[..., None]
        wcol = np.array([0.25, 0.55, 0.62], np.float32) * (1 - deep) + np.array([0.1, 0.28, 0.45], np.float32) * deep
        img = np.where(water, wcol[..., :] if wcol.ndim == 3 else wcol, img)
        shade = np.clip(1.0 + (np.gradient(ter.h, axis=1)[:-1, :-1] - np.gradient(ter.h, axis=0)[:-1, :-1]) * 0.25, 0.7, 1.25)
        img = img * shade[..., None]
        if img.shape[0] != RES:
            ys = (np.arange(RES) * img.shape[0] / RES).astype(int)
            img = img[ys][:, ys]
        self.base_img = np.clip(img, 0, 1).astype(np.float32)
        self._t = 0.0
        self.pings.clear()
        self.redraw()

    def detach(self) -> None:
        self.match = None

    def _on_alert(self, x: float, z: float, **_) -> None:
        if self.match is not None:
            self.pings.append((self.match.time, x, z))

    # ------------------------------------------------------------------ mapping
    def world_to_px(self, x: float, z: float) -> tuple[int, int]:
        m = self.match
        half = m.terrain.half
        px = int((x + half) / m.terrain.size * RES)
        pz = int((z + half) / m.terrain.size * RES)
        return px, pz

    def mouse_to_world(self) -> tuple[float, float] | None:
        cx, cy = self.center
        s = self.size
        u = (mouse.x - (cx - s / 2)) / s
        v = (mouse.y - (cy - s / 2)) / s
        if not (0 <= u <= 1 and 0 <= v <= 1):
            return None
        m = self.match
        half = m.terrain.half
        return -half + u * m.terrain.size, -half + v * m.terrain.size

    def hovered(self) -> bool:
        return self.entity.hovered

    # ------------------------------------------------------------------ input
    def input(self, key: str) -> bool:
        if self.match is None or not self.entity.hovered:
            if key == "left mouse up":
                self.dragging = False
            return False
        p = self.mouse_to_world()
        if p is None:
            return False
        ctl = self.game.controls
        if key == "left mouse down":
            if ctl is not None and ctl.mode in ("attack", "move", "patrol"):
                units = ctl.selected_units()
                kind = {"attack": "attack_move", "move": "move", "patrol": "patrol"}[ctl.mode]
                self.match.order_units(units, kind, p[0], p[1], queue=bool(held_keys["shift"]))
                ctl.cancel_mode()
                return True
            self.dragging = True
            self.match.cam.look_at(p[0], p[1] - 8, instant=False)
            return True
        if key == "right mouse down" and ctl is not None:
            units = ctl.selected_units()
            if units:
                self.match.order_units(units, "move", p[0], p[1], queue=bool(held_keys["shift"]))
                events.emit("sound", name="ack")
            else:
                for b in ctl.own_selection():
                    if b.is_building and b.trains():
                        b.rally, b.rally_target = p, None
            return True
        if key == "left mouse up":
            self.dragging = False
            return True
        return False

    # ------------------------------------------------------------------ drawing
    def update(self, dt: float) -> None:
        if self.match is None:
            return
        if self.dragging:
            if held_keys["left mouse"]:
                p = self.mouse_to_world()
                if p is not None:
                    self.match.cam.look_at(p[0], p[1] - 8, instant=False)
            else:
                self.dragging = False
        self._t -= dt
        if self._t <= 0:
            self._t = 0.2
            self.redraw()

    def redraw(self) -> None:
        m = self.match
        if m is None or self.base_img is None:
            return
        img = self.base_img.copy()
        human = m.human
        fog_on = m.fog.display_team >= 0 and human is not None
        k = RES // m.grid.w
        # trees
        for t in m.map.forest.trees:
            if t.alive:
                px, pz = self.world_to_px(t.x, t.z)
                img[max(pz - 1, 0):pz + 1, max(px - 1, 0):px + 1] = (0.1, 0.28, 0.12)
        for mine in m.map.mines:
            if mine.alive:
                px, pz = self.world_to_px(mine.x, mine.z)
                img[max(pz - 3, 0):pz + 4, max(px - 3, 0):px + 4] = (1.0, 0.85, 0.2)
        # fog
        if fog_on:
            f = np.repeat(np.repeat(m.fog.disp, k, axis=0), k, axis=1)[:RES, :RES]
            img *= np.clip(f * 1.15, 0.1, 1.0)[..., None]
        # buildings
        for b in m.buildings:
            if not b.alive or b.node is None:
                continue
            if fog_on and b.owner is not human and not b.remembered:
                continue
            px, pz = self.world_to_px(b.x, b.z)
            r = max(2, int(b.footprint * k * 0.5))
            col = b.owner.color
            img[max(pz - r, 0):pz + r, max(px - r, 0):px + r] = (col[0] * 0.7 + 0.15, col[1] * 0.7 + 0.15, col[2] * 0.7 + 0.15)
        # units
        for u in m.units:
            if not u.alive or u.hidden:
                continue
            if fog_on and u.owner is not human and not u.visible:
                continue
            px, pz = self.world_to_px(u.x, u.z)
            c = (0.35, 1.0, 0.4) if u.selected else u.owner.color
            img[max(pz - 1, 0):pz + 2, max(px - 1, 0):px + 2] = c
        # alert pings
        now = m.time
        self.pings = [p for p in self.pings if now - p[0] < 3.0]
        for t0, x, z in self.pings:
            px, pz = self.world_to_px(x, z)
            r = int(4 + (now - t0) * 6) % 14 + 3
            self._ring(img, px, pz, r, (1.0, 0.2, 0.15))
        # camera frame
        cam = m.cam
        corners = []
        from ursina import window
        ax = window.aspect_ratio * 0.5
        for sx, sy in ((-ax, -0.24), (ax, -0.24), (ax, 0.5), (-ax, 0.5)):
            gp = cam.ground_under_mouse(sx, sy, flat=True)
            if gp is None:
                gp = (cam.fx, cam.fz)
            corners.append(self.world_to_px(*gp))
        for a, b in zip(corners, corners[1:] + corners[:1]):
            self._line(img, a, b, (0.95, 0.95, 0.95))
        out = (np.clip(img, 0, 1) * 255).astype(np.uint8)
        self.tex.setRamImageAs(out.tobytes(), "RGB")

    @staticmethod
    def _line(img: np.ndarray, a: tuple[int, int], b: tuple[int, int], col) -> None:
        n = max(abs(b[0] - a[0]), abs(b[1] - a[1]), 1)
        xs = np.clip(np.linspace(a[0], b[0], n + 1).astype(int), 0, RES - 1)
        zs = np.clip(np.linspace(a[1], b[1], n + 1).astype(int), 0, RES - 1)
        img[zs, xs] = col

    @staticmethod
    def _ring(img: np.ndarray, cx: int, cz: int, r: int, col) -> None:
        a = np.linspace(0, math.tau, 48)
        xs = np.clip((cx + np.cos(a) * r).astype(int), 0, RES - 1)
        zs = np.clip((cz + np.sin(a) * r).astype(int), 0, RES - 1)
        img[zs, xs] = col

    def destroy(self) -> None:
        events.off("alert", self._on_alert)
        self.entity.disable()
        self.frame.disable()
