"""Walkability grid, A* pathfinding (time-sliced) and line-of-sight helpers.

The grid has one cell per ``CELL`` world units. A cell is blocked by terrain (cliffs,
deep water, the map rim) or by dynamic blockers (buildings, trees, gold mines), which are
reference counted so overlapping footprints can be removed safely.
"""
from __future__ import annotations

import heapq
import math
import time
from collections import deque
from typing import Callable, Iterator

import numpy as np

from settings import CELL, MAX_WALK_SLOPE, SEA_LEVEL, WADE_DEPTH

SQ2 = math.sqrt(2.0)
HEUR_WEIGHT = 1.25
Point = tuple[float, float]


class PathGrid:
    """Grid of walkable cells with A* search and LOS tests."""

    EDGE = 4  # outermost cells are always blocked so neighbour lookups never leave the grid

    def __init__(self, terrain) -> None:
        self.terrain = terrain
        self.cell = CELL
        self.w = int(round(terrain.size / CELL))
        self.origin = -terrain.half
        self.version = 0
        w = self.w
        h = terrain.h
        # per 1-unit quad: max absolute rise along its edges
        gx = np.abs(np.diff(h, axis=1))
        gz = np.abs(np.diff(h, axis=0))
        q = np.maximum(np.maximum(gx[:-1, :], gx[1:, :]), np.maximum(gz[:, :-1], gz[:, 1:]))
        k = int(round(CELL))
        slope = q[: w * k, : w * k].reshape(w, k, w, k).max(axis=(1, 3))
        win = np.lib.stride_tricks.sliding_window_view(h[: w * k + 1, : w * k + 1], (k + 1, k + 1))[::k, ::k]
        lowest = win.min(axis=(2, 3))
        self.cell_height = win.mean(axis=(2, 3)).astype(np.float32)
        self.slope = slope.astype(np.float32)
        blocked = (slope > MAX_WALK_SLOPE) | (lowest < SEA_LEVEL - WADE_DEPTH)
        e = self.EDGE
        blocked[:e, :] = True
        blocked[-e:, :] = True
        blocked[:, :e] = True
        blocked[:, -e:] = True
        idx = np.arange(w)
        cx = self.origin + (idx + 0.5) * CELL
        lim = terrain.half - 9.0
        blocked[:, np.abs(cx) > lim] = True
        blocked[np.abs(cx) > lim, :] = True
        self.static_blocked = blocked
        self.water = lowest < SEA_LEVEL - 0.05
        self.dyn = np.zeros((w, w), np.int16)
        self.walk = bytearray((~blocked).astype(np.uint8).ravel().tobytes())
        self.comp: list[int] = []
        self._comp_dirty = True
        self._neigh = [
            (1, 0, 1.0, 1), (-1, 0, 1.0, -1), (0, 1, 1.0, w), (0, -1, 1.0, -w),
            (1, 1, SQ2, w + 1), (-1, 1, SQ2, w - 1), (1, -1, SQ2, -w + 1), (-1, -1, SQ2, -w - 1),
        ]

    # ------------------------------------------------------------------ cells
    def cell_of(self, x: float, z: float) -> int:
        w = self.w
        i = int((x - self.origin) / self.cell)
        j = int((z - self.origin) / self.cell)
        i = 0 if i < 0 else w - 1 if i >= w else i
        j = 0 if j < 0 else w - 1 if j >= w else j
        return j * w + i

    def cell_xy(self, x: float, z: float) -> tuple[int, int]:
        c = self.cell_of(x, z)
        return c % self.w, c // self.w

    def center(self, c: int) -> Point:
        return (self.origin + (c % self.w + 0.5) * self.cell, self.origin + (c // self.w + 0.5) * self.cell)

    def walkable(self, x: float, z: float) -> bool:
        return bool(self.walk[self.cell_of(x, z)])

    def walkable_cell(self, i: int, j: int) -> bool:
        if 0 <= i < self.w and 0 <= j < self.w:
            return bool(self.walk[j * self.w + i])
        return False

    # ------------------------------------------------------------------ blockers
    def block_rect(self, i0: int, j0: int, size_i: int, size_j: int, amount: int = 1) -> None:
        """Add (or with a negative ``amount`` remove) a dynamic blocker over a cell rectangle."""
        w = self.w
        i1, j1 = min(i0 + size_i, w), min(j0 + size_j, w)
        i0, j0 = max(i0, 0), max(j0, 0)
        self.dyn[j0:j1, i0:i1] += amount
        for j in range(j0, j1):
            for i in range(i0, i1):
                self.walk[j * w + i] = 0 if (self.static_blocked[j, i] or self.dyn[j, i] > 0) else 1
        self.version += 1
        self._comp_dirty = True

    def footprint_origin(self, x: float, z: float, size: int) -> tuple[int, int]:
        """Lower-left cell of a ``size`` x ``size`` footprint centred on (x, z)."""
        i = int(round((x - self.origin) / self.cell - size / 2.0))
        j = int(round((z - self.origin) / self.cell - size / 2.0))
        return i, j

    def snap_footprint(self, x: float, z: float, size: int) -> Point:
        """World centre of the footprint whose cells best cover (x, z)."""
        i, j = self.footprint_origin(x, z, size)
        return (self.origin + (i + size / 2.0) * self.cell, self.origin + (j + size / 2.0) * self.cell)

    def area_free(self, i0: int, j0: int, size: int, allow_static_only: bool = False) -> bool:
        w = self.w
        if i0 < 0 or j0 < 0 or i0 + size > w or j0 + size > w:
            return False
        sub = self.static_blocked[j0:j0 + size, i0:i0 + size]
        if sub.any():
            return False
        if not allow_static_only and (self.dyn[j0:j0 + size, i0:i0 + size] > 0).any():
            return False
        return True

    # ------------------------------------------------------------------ components
    def _label_components(self) -> None:
        w = self.w
        walk = self.walk
        comp = [-1] * (w * w)
        label = 0
        neigh = [1, -1, w, -w]
        for start in range(w * w):
            if not walk[start] or comp[start] >= 0:
                continue
            comp[start] = label
            dq = [start]
            while dq:
                c = dq.pop()
                for d in neigh:
                    n = c + d
                    if walk[n] and comp[n] < 0:
                        comp[n] = label
                        dq.append(n)
            label += 1
        self.comp = comp
        self._comp_dirty = False

    def component(self, c: int) -> int:
        if self._comp_dirty or not self.comp:
            self._label_components()
        return self.comp[c]

    def nearest_walkable(self, c: int, comp: int | None = None, max_r: int = 30) -> int | None:
        """Closest walkable cell to ``c`` (optionally inside connected component ``comp``)."""
        w = self.w
        cx, cz = c % w, c // w

        def ok(i: int, j: int) -> bool:
            if not (0 <= i < w and 0 <= j < w):
                return False
            k = j * w + i
            if not self.walk[k]:
                return False
            return comp is None or self.component(k) == comp

        if ok(cx, cz):
            return c
        for r in range(1, max_r + 1):
            best, best_d = None, 1e9
            for di in range(-r, r + 1):
                for dj in (-r, r):
                    if ok(cx + di, cz + dj):
                        d = di * di + dj * dj
                        if d < best_d:
                            best, best_d = (cz + dj) * w + cx + di, d
            for dj in range(-r + 1, r):
                for di in (-r, r):
                    if ok(cx + di, cz + dj):
                        d = di * di + dj * dj
                        if d < best_d:
                            best, best_d = (cz + dj) * w + cx + di, d
            if best is not None:
                return best
        return None

    # ------------------------------------------------------------------ line of sight
    def line_clear(self, ax: float, az: float, bx: float, bz: float, step: float = 0.5) -> bool:
        """True if every cell along the segment is walkable."""
        dx, dz = bx - ax, bz - az
        dist = math.hypot(dx, dz)
        n = int(dist / step) + 1
        walk = self.walk
        w = self.w
        o = self.origin
        inv = 1.0 / self.cell
        last = -1
        for k in range(n + 1):
            t = k / n
            i = int((ax + dx * t - o) * inv)
            j = int((az + dz * t - o) * inv)
            c = j * w + i
            if c != last:
                if not (0 <= i < w and 0 <= j < w) or not walk[c]:
                    return False
                if last >= 0:
                    li, lj = last % w, last // w
                    if li != i and lj != j and not (walk[lj * w + i] or walk[j * w + li]):
                        return False
                last = c
        return True

    # ------------------------------------------------------------------ A*
    def search(self, sx: float, sz: float, gx: float, gz: float) -> Iterator[list[Point] | None]:
        """Generator: yields ``None`` while working, finally yields the waypoint list (or [])."""
        w = self.w
        s = self.cell_of(sx, sz)
        if not self.walk[s]:
            ns = self.nearest_walkable(s, max_r=6)
            if ns is None:
                yield []
                return
            s = ns
        comp = self.component(s)
        g = self.cell_of(gx, gz)
        goal_exact = True
        if not self.walk[g] or self.component(g) != comp:
            ng = self.nearest_walkable(g, comp, max_r=40)
            if ng is None:
                yield []
                return
            g = ng
            goal_exact = False
        if s == g:
            yield [(gx, gz)] if goal_exact else [self.center(g)]
            return
        walk = self.walk
        n = w * w
        inf = float("inf")
        gscore = [inf] * n
        came = [-1] * n
        gscore[s] = 0.0
        gcx, gcz = g % w, g // w
        heap = [(0.0, 0.0, s)]
        neigh = self._neigh
        expanded = 0
        found = False
        best, best_h = s, inf
        push, pop = heapq.heappush, heapq.heappop
        while heap:
            _, gs, cur = pop(heap)
            if gs > gscore[cur]:
                continue
            if cur == g:
                found = True
                break
            expanded += 1
            if expanded % 350 == 0:
                yield None
            cx, cz = cur % w, cur // w
            for dx, dz, cost, d in neigh:
                ni = cur + d
                if not walk[ni]:
                    continue
                if dx and dz and not (walk[cur + dx] and walk[cur + dz * w]):
                    continue
                ng = gs + cost
                if ng < gscore[ni]:
                    gscore[ni] = ng
                    came[ni] = cur
                    hx = abs(cx + dx - gcx)
                    hz = abs(cz + dz - gcz)
                    hh = (hx + hz + (SQ2 - 2.0) * (hx if hx < hz else hz))
                    if hh < best_h:
                        best, best_h = ni, hh
                    push(heap, (ng + hh * HEUR_WEIGHT, ng, ni))
        end = g if found else best
        cells = []
        c = end
        while c != -1 and c != s:
            cells.append(c)
            c = came[c]
        cells.reverse()
        pts = [self.center(c) for c in cells]
        if found and goal_exact and pts:
            pts[-1] = (gx, gz)
        yield self.smooth([(sx, sz)] + pts)[1:]

    def smooth(self, pts: list[Point]) -> list[Point]:
        """String-pull a cell path into a few straight segments."""
        if len(pts) <= 2:
            return pts
        # drop collinear cells first
        out = [pts[0]]
        for a, b, c in zip(pts, pts[1:], pts[2:]):
            if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-6:
                out.append(b)
        out.append(pts[-1])
        res = [out[0]]
        anchor = 0
        i = 1
        while i < len(out):
            if i + 1 < len(out) and self.line_clear(out[anchor][0], out[anchor][1], out[i + 1][0], out[i + 1][1]):
                i += 1
                continue
            res.append(out[i])
            anchor = i
            i += 1
        return res

    def find_path(self, sx: float, sz: float, gx: float, gz: float) -> list[Point]:
        """Blocking version of :meth:`search` (tests and short queries)."""
        result: list[Point] | None = None
        for result in self.search(sx, sz, gx, gz):
            pass
        return result or []


class PathService:
    """Runs path searches under a per-frame time budget so big orders never stall a frame."""

    def __init__(self, grid: PathGrid, budget_ms: float = 3.0) -> None:
        self.grid = grid
        self.budget = budget_ms / 1000.0
        self.queue: deque[tuple[tuple[float, float, float, float], Callable[[list[Point]], None]]] = deque()
        self._current: tuple | None = None
        self.cache: dict[tuple[int, int, int], list[Point]] = {}
        self.searches = 0

    def request(self, sx: float, sz: float, gx: float, gz: float, callback: Callable[[list[Point]], None]) -> None:
        g = self.grid
        if g.line_clear(sx, sz, gx, gz):
            callback([(gx, gz)])
            return
        key = (g.cell_of(sx, sz), g.cell_of(gx, gz), g.version)
        hit = self.cache.get(key)
        if hit is not None:
            pts = list(hit)
            if pts:
                pts[-1] = (gx, gz) if g.walkable(gx, gz) else pts[-1]
            callback(pts)
            return
        self.queue.append(((sx, sz, gx, gz), callback))

    def update(self) -> None:
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < self.budget:
            if self._current is None:
                if not self.queue:
                    return
                (sx, sz, gx, gz), cb = self.queue.popleft()
                self._current = (self.grid.search(sx, sz, gx, gz), cb, (sx, sz, gx, gz))  # type: ignore[assignment]
                self.searches += 1
            gen, cb, args = self._current  # type: ignore[misc]
            try:
                result = next(gen)
            except StopIteration:
                result = []
            if result is not None:
                self._current = None
                g = self.grid
                if len(self.cache) > 400:
                    self.cache.clear()
                self.cache[(g.cell_of(args[0], args[1]), g.cell_of(args[2], args[3]), g.version)] = list(result)
                cb(result)

    def flush(self) -> None:
        """Finish every pending search immediately (used by tests)."""
        old = self.budget
        self.budget = 10.0
        while self.queue or self._current is not None:
            self.update()
        self.budget = old
