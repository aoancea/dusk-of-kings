"""Fog of war: per-team visible/explored grids, the high-ground sight rule and the fog texture."""
from __future__ import annotations

import math

import numpy as np
from panda3d.core import LColor, SamplerState, Texture as PTexture

UNEXPLORED = 0.06
EXPLORED = 0.42
HIGH_GROUND = 3.0


class FogOfWar:
    """Visibility for each team. Team ``display_team`` drives the fog texture used by the shaders."""

    def __init__(self, grid, teams: int = 2) -> None:
        self.grid = grid
        w = grid.w
        self.w = w
        self.visible = [np.zeros((w, w), bool) for _ in range(teams)]
        self.explored = [np.zeros((w, w), bool) for _ in range(teams)]
        self.vis_bytes = [bytearray(w * w) for _ in range(teams)]
        self.cell_h = grid.cell_height
        self.enabled = True
        self.display_team = 0
        self._masks: dict[int, np.ndarray] = {}
        self.disp = np.full((w, w), UNEXPLORED, np.float32)
        self.tex = PTexture("fog")
        self.tex.setup2dTexture(w, w, PTexture.T_unsigned_byte, PTexture.F_luminance)
        self.tex.setMinfilter(SamplerState.FT_linear)
        self.tex.setMagfilter(SamplerState.FT_linear)
        self.tex.setWrapU(SamplerState.WM_border_color)
        self.tex.setWrapV(SamplerState.WM_border_color)
        self.tex.setBorderColor(LColor(0, 0, 0, 1))
        self._upload(snap=True)

    def _mask(self, r: int) -> np.ndarray:
        m = self._masks.get(r)
        if m is None:
            k = np.arange(-r, r + 1)
            m = (k[None, :] ** 2 + k[:, None] ** 2) <= (r + 0.35) ** 2
            self._masks[r] = m
        return m

    def compute(self, viewers: list[list[tuple[float, float, float, bool]]]) -> None:
        """``viewers[team]`` = list of (x, z, sight, flying). Recomputes visibility for every team."""
        g = self.grid
        w = self.w
        inv = 1.0 / g.cell
        o = g.origin
        ch = self.cell_h
        for team, lst in enumerate(viewers):
            vis = self.visible[team]
            vis[:] = False
            for x, z, sight, flying in lst:
                ci = int((x - o) * inv)
                cj = int((z - o) * inv)
                r = int(math.ceil(sight * inv))
                m = self._mask(r)
                i0, j0 = ci - r, cj - r
                a0, b0 = max(i0, 0), max(j0, 0)
                a1, b1 = min(ci + r + 1, w), min(cj + r + 1, w)
                if a0 >= a1 or b0 >= b1:
                    continue
                sub = m[b0 - j0:b1 - j0, a0 - i0:a1 - i0]
                if not flying and 0 <= ci < w and 0 <= cj < w:
                    sub = sub & (ch[b0:b1, a0:a1] <= ch[cj, ci] + HIGH_GROUND)
                vis[b0:b1, a0:a1] |= sub
            self.explored[team] |= vis
            self.vis_bytes[team][:] = vis.astype(np.uint8).tobytes()

    def reveal_all(self, team: int) -> None:
        self.visible[team][:] = True
        self.explored[team][:] = True
        self.vis_bytes[team][:] = b"\x01" * (self.w * self.w)

    def is_visible(self, team: int, cell: int) -> bool:
        if not self.enabled:
            return True
        return bool(self.vis_bytes[team][cell])

    def is_explored(self, team: int, cell: int) -> bool:
        if not self.enabled:
            return True
        return bool(self.explored[team].flat[cell])

    def update_display(self, dt: float) -> None:
        self._upload(dt=dt)

    def _upload(self, dt: float = 0.0, snap: bool = False) -> None:
        if not self.enabled or self.display_team < 0:
            target = np.ones((self.w, self.w), np.float32)
        else:
            t = self.display_team
            target = np.where(self.visible[t], 1.0, np.where(self.explored[t], EXPLORED, UNEXPLORED)).astype(np.float32)
        if snap:
            self.disp[:] = target
        else:
            self.disp += (target - self.disp) * min(1.0, dt * 6.0)
        img = (np.clip(self.disp, 0, 1) * 255).astype(np.uint8)
        self.tex.setRamImage(img.tobytes())
