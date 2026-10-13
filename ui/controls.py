"""Mouse and keyboard control of a match: selection, smart orders, targeting modes, control groups."""
from __future__ import annotations

import math
import time as _time
from typing import TYPE_CHECKING, Any

import numpy as np
from panda3d.core import TransparencyAttrib
from ursina import Entity, camera, color, held_keys, mouse, window

from core import data
from core.events import events

if TYPE_CHECKING:
    from core.actor import Actor
    from core.game import Game

DRAG_THRESHOLD = 0.012
DOUBLE_CLICK = 0.35


class Controls:
    """Translates player input into selections and orders for the local player."""

    def __init__(self, game: "Game") -> None:
        self.game = game
        self.match = game.match
        self.box_start: tuple[float, float] | None = None
        self.dragging = False
        self.box = Entity(parent=camera.ui, model="quad", origin=(-0.5, -0.5), color=color.rgba(0.3, 1.0, 0.4, 0.12),
                          z=-1, enabled=False)
        self.box_border = Entity(parent=self.box, model="wireframe_quad", origin=(-0.5, -0.5), color=color.rgba(0.4, 1, 0.5, 0.9))
        self.mode: str | None = None
        self.mode_arg: Any = None
        self.groups: dict[int, list["Actor"]] = {}
        self._last_click = (0.0, None)
        self._last_group = (0.0, -1)
        self.ghost = None
        self.ghost_ok = False
        self.hover: "Actor | None" = None
        self.enabled = True
        self.message_hook = None

    # ================================================================== helpers
    @property
    def player(self):
        return self.match.human

    def own_selection(self) -> list["Actor"]:
        p = self.player
        return [a for a in self.match.selection if a.alive and a.owner is p]

    def selected_units(self) -> list[Any]:
        return [a for a in self.own_selection() if a.is_unit]

    def notify(self, text: str) -> None:
        events.emit("notice", player=self.player, text=text)
        events.emit("sound", name="error")

    def over_ui(self) -> bool:
        # world picking is done by hand, so anything Ursina reports as hovered is a UI element
        return mouse.hovered_entity is not None

    def set_selection(self, actors: list["Actor"], add: bool = False) -> None:
        sel = self.match.selection
        if not add:
            for a in sel:
                a.selected = False
            sel.clear()
        for a in actors:
            if a.alive and a not in sel:
                sel.append(a)
                a.selected = True
        events.emit("selection_changed", selection=list(sel))

    # ================================================================== picking
    def _screen_radius(self, pts: np.ndarray, radii: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        cam = self.match.cam
        q = self.game.base.cam.getQuat(self.game.base.render)
        r = q.getRight()
        right = np.array([r.x, r.y, r.z], np.float32)
        ui, front = cam.project(pts)
        ui2, _ = cam.project(pts + right[None, :] * radii[:, None])
        rad = np.linalg.norm(ui2 - ui, axis=1)
        return ui, front, rad

    def pick(self, mx: float | None = None, my: float | None = None) -> "Actor | None":
        """The visible unit, building or mine under the cursor (closest to the camera wins ties)."""
        m = self.match
        if mx is None:
            mx, my = mouse.x, mouse.y
        cands = [u for u in m.units if u.alive and u.visible and u.on_screen]
        cands += [b for b in m.buildings if b.alive and b.node is not None and not b.node.isHidden()]
        cands += [mi for mi in m.map.mines if mi.alive and m.fog.is_explored(m.human.team if m.human else 0, m.grid.cell_of(mi.x, mi.z))]
        if not cands:
            return None
        n = len(cands)
        pts = np.empty((n, 3), np.float32)
        radii = np.empty(n, np.float32)
        for i, a in enumerate(cands):
            h = a.height * (0.35 if (a.is_building or a.is_mine) else 0.5)
            pts[i] = (a.x, a.y + h, a.z)
            radii[i] = (a.radius * 0.9 if (a.is_building or a.is_mine) else max(a.radius * 1.4, 0.75))
        ui, front, rad = self._screen_radius(pts, radii)
        d = np.hypot(ui[:, 0] - mx, ui[:, 1] - my)
        ok = front & (d <= rad + 0.006)
        if not ok.any():
            return None
        # prefer units over buildings and smaller distance relative to radius
        score = np.where(ok, d / np.maximum(rad, 1e-3) + np.array([0.0 if a.is_unit else 0.6 for a in cands]), np.inf)
        return cands[int(np.argmin(score))]

    def units_in_box(self, x0: float, y0: float, x1: float, y1: float) -> list[Any]:
        m = self.match
        lo_x, hi_x = min(x0, x1), max(x0, x1)
        lo_y, hi_y = min(y0, y1), max(y0, y1)
        own = [u for u in m.units if u.alive and u.visible and u.owner is self.player and not u.hidden]
        if not own:
            return []
        pts = np.array([(u.x, u.y + u.height * 0.4, u.z) for u in own], np.float32)
        ui, front = m.cam.project(pts)
        inside = front & (ui[:, 0] >= lo_x) & (ui[:, 0] <= hi_x) & (ui[:, 1] >= lo_y) & (ui[:, 1] <= hi_y)
        return [u for u, k in zip(own, inside) if k]

    # ================================================================== input
    def input(self, key: str) -> None:
        if not self.enabled or self.match is None or self.player is None:
            return
        m = self.match
        shift = held_keys["shift"]
        ctrl = held_keys["control"]
        if key == "left mouse down":
            if self.over_ui():
                return
            if self.mode is not None:
                self._apply_mode(shift)
                return
            self.box_start = (mouse.x, mouse.y)
            self.dragging = False
        elif key == "left mouse up":
            if self.box_start is None:
                return
            sx, sy = self.box_start
            self.box_start = None
            self.box.enabled = False
            if self.dragging:
                units = self.units_in_box(sx, sy, mouse.x, mouse.y)
                if units:
                    if shift:
                        self.set_selection(units, add=True)
                    else:
                        self.set_selection(units)
                elif not shift:
                    pass
                return
            self._click_select(shift, ctrl)
        elif key == "right mouse down":
            if self.mode is not None:
                self.cancel_mode()
                return
            if self.over_ui():
                return
            self.smart_command(shift)
        elif key == "middle mouse down":
            m.cam.begin_drag()
        elif key == "middle mouse up":
            m.cam.end_drag()
        elif key == "scroll up":
            if not self.over_ui():
                m.cam.zoom(1)
        elif key == "scroll down":
            if not self.over_ui():
                m.cam.zoom(-1)
        elif key == "escape":
            if self.mode is not None:
                self.cancel_mode()
        elif key in "123456789" and len(key) == 1:
            n = int(key)
            if ctrl:
                self.groups[n] = [a for a in self.own_selection()]
                events.emit("notice", player=self.player, text=f"Group {n} set")
            elif shift:
                self.groups.setdefault(n, [])
                for a in self.own_selection():
                    if a not in self.groups[n]:
                        self.groups[n].append(a)
            else:
                grp = [a for a in self.groups.get(n, []) if a.alive]
                self.groups[n] = grp
                if grp:
                    now = _time.time()
                    if self._last_group[1] == n and now - self._last_group[0] < DOUBLE_CLICK:
                        cx = sum(a.x for a in grp) / len(grp)
                        cz = sum(a.z for a in grp) / len(grp)
                        m.cam.look_at(cx, cz - 6)
                    self._last_group = (now, n)
                    self.set_selection(grp)
        elif key == "space":
            if m.alerts:
                _, x, z = m.alerts[-1]
                m.cam.look_at(x, z - 6)
        elif key in ("backspace", "home"):
            halls = [b for b in m.buildings if b.alive and b.owner is self.player and b.town_hall]
            if halls:
                m.cam.look_at(halls[0].x, halls[0].z - 6)
                self.set_selection([halls[0]])
        elif key == "tab":
            pass
        else:
            self.hotkey(key)

    def hotkey(self, key: str) -> None:
        """Unit command hotkeys (the command card handles its own buttons and grid keys)."""
        units = self.selected_units()
        if not units:
            return
        if key == "a" and any(u.attack for u in units):
            self.begin_mode("attack")
        elif key == "m":
            self.begin_mode("move")
        elif key == "p":
            self.begin_mode("patrol")
        elif key == "s":
            self.match.order_units(units, "stop")
        elif key == "h":
            self.match.order_units(units, "hold")

    def _click_select(self, shift: bool, ctrl: bool) -> None:
        a = self.pick()
        m = self.match
        if a is None:
            if not shift:
                self.set_selection([])
            return
        now = _time.time()
        double = self._last_click[1] is a and now - self._last_click[0] < DOUBLE_CLICK
        self._last_click = (now, a)
        if (double or ctrl) and a.owner is self.player:
            same = [u for u in (m.units if a.is_unit else m.buildings)
                    if u.alive and u.owner is self.player and u.type_id == a.type_id and (u.on_screen if a.is_unit else True)]
            self.set_selection(same, add=shift)
            return
        if shift and a.owner is self.player and a.is_unit:
            if a in m.selection:
                m.selection.remove(a)
                a.selected = False
                events.emit("selection_changed", selection=list(m.selection))
            else:
                self.set_selection([a], add=True)
            return
        self.set_selection([a])
        events.emit("sound", name="select" if a.owner is self.player else "click")

    # ================================================================== orders
    def ground_point(self) -> tuple[float, float] | None:
        return self.match.cam.ground_under_mouse()

    def smart_command(self, queue: bool) -> None:
        m = self.match
        own = self.own_selection()
        if not own:
            return
        target = self.pick()
        gp = self.ground_point()
        units = [a for a in own if a.is_unit]
        buildings = [a for a in own if a.is_building]
        if not units:
            for b in buildings:
                if b.trains():
                    if target is not None and target is not b:
                        b.rally, b.rally_target = (target.x, target.z), target
                    elif gp is not None:
                        tree = m.map.forest.tree_at(gp[0], gp[1], 1.4)
                        b.rally, b.rally_target = gp, tree
                    if b.rally is not None:
                        m.fx.ring(b.rally[0], m.terrain.height(*b.rally), b.rally[1], 1.2, (0.4, 1.0, 0.5, 0.9), 0.5)
                        events.emit("notice", player=self.player, text="Rally point set")
            return
        workers = [u for u in units if u.is_worker]
        others = [u for u in units if not u.is_worker]
        if target is not None and target.alive:
            if target.is_mine and workers:
                m.economy.order_gather(workers, target, queue)
                self._marker(target.x, target.z, (1.0, 0.85, 0.3, 0.9))
                if others:
                    m.order_units(others, "move", target.x, target.z - 6, queue=queue)
                events.emit("sound", name="ack")
                return
            if target.is_building and target.owner is self.player:
                if workers and not target.complete:
                    m.economy.order_construct(workers, target, queue)
                    if others:
                        m.order_units(others, "follow", target=target, queue=queue)
                    events.emit("sound", name="ack")
                    return
                carrying = [w for w in workers if w.carry > 0 and (w.carry_kind in target.dropoff)]
                if carrying:
                    m.economy.order_return(carrying, queue)
                    rest = [u for u in units if u not in carrying]
                    if rest:
                        m.order_units(rest, "follow", target=target, queue=queue)
                    return
            if target.team >= 0 and target.team != self.player.team:
                m.order_units(units, "attack", target=target, queue=queue)
                self._marker(target.x, target.z, (1.0, 0.25, 0.2, 0.95))
                events.emit("sound", name="ack_attack")
                return
            if target.is_unit and target.team == self.player.team and target not in units:
                m.order_units(units, "follow", target=target, queue=queue)
                self._marker(target.x, target.z, (0.4, 1.0, 0.5, 0.9))
                events.emit("sound", name="ack")
                return
        if gp is None:
            return
        if workers:
            tree = m.map.forest.tree_at(gp[0], gp[1], 1.5)
            if tree is not None:
                m.economy.order_gather(workers, tree, queue)
                self._marker(tree.x, tree.z, (1.0, 0.85, 0.3, 0.9))
                if others:
                    m.order_units(others, "move", gp[0], gp[1], queue=queue)
                events.emit("sound", name="ack")
                return
        m.order_units(units, "move", gp[0], gp[1], queue=queue)
        self._marker(gp[0], gp[1], (0.4, 1.0, 0.5, 0.9))
        events.emit("sound", name="ack")

    def _marker(self, x: float, z: float, col: tuple) -> None:
        m = self.match
        m.fx.ring(x, m.terrain.height(x, z), z, 1.4, col, 0.45)

    # ================================================================== modes
    def begin_mode(self, mode: str, arg: Any = None) -> None:
        self.cancel_mode()
        self.mode = mode
        self.mode_arg = arg
        if mode == "build":
            self._make_ghost(arg)
        events.emit("mode_changed", mode=mode, arg=arg)

    def cancel_mode(self) -> None:
        self.mode = None
        self.mode_arg = None
        if self.ghost is not None:
            self.ghost.removeNode()
            self.ghost = None
        events.emit("mode_changed", mode=None, arg=None)

    def _apply_mode(self, shift: bool) -> None:
        m = self.match
        mode = self.mode
        units = self.selected_units()
        gp = self.ground_point()
        target = self.pick()
        keep = shift
        if mode in ("attack", "move", "patrol"):
            if not units:
                self.cancel_mode()
                return
            if mode == "attack" and target is not None and target.team >= 0 and target.team != self.player.team:
                m.order_units(units, "attack", target=target, queue=shift)
                self._marker(target.x, target.z, (1.0, 0.25, 0.2, 0.95))
            elif gp is not None:
                kind = {"attack": "attack_move", "move": "move", "patrol": "patrol"}[mode]
                m.order_units(units, kind, gp[0], gp[1], queue=shift)
                self._marker(gp[0], gp[1], (1.0, 0.3, 0.2, 0.9) if mode == "attack" else (0.4, 1.0, 0.5, 0.9))
            events.emit("sound", name="ack")
        elif mode == "build":
            if gp is None:
                return
            workers = [u for u in units if u.is_worker]
            if not workers:
                self.cancel_mode()
                return
            btype = self.mode_arg
            worker = min(workers, key=lambda w: (0 if w.order is None or w.order.kind != "build" else 1,
                                                  math.hypot(w.x - gp[0], w.z - gp[1])))
            err = m.economy.order_build(worker, btype, gp[0], gp[1], queue=shift)
            if err:
                self.notify(err)
                return
            events.emit("sound", name="build")
            if keep:
                return
        elif mode == "gather":
            workers = [u for u in units if u.is_worker]
            res = target if (target is not None and target.is_mine) else None
            if res is None and gp is not None:
                res = m.map.forest.tree_at(gp[0], gp[1], 1.6)
            if res is None or not workers:
                self.notify("Must target a gold mine or a tree")
                return
            m.economy.order_gather(workers, res, shift)
            self._marker(res.x, res.z, (1.0, 0.85, 0.3, 0.9))
            events.emit("sound", name="ack")
        elif mode == "cast":
            aid = self.mode_arg
            a = data.abilities()[aid]
            point = gp
            err = m.abilities.order_cast(units, aid, target=target, point=point if a["target"] == "point" else None, queue=shift)
            if err:
                self.notify(err)
                return
        self.cancel_mode()

    # ================================================================== ghost
    def _make_ghost(self, btype: str) -> None:
        from buildings.models import _protos
        solid, glow = _protos(btype, self.player.color)
        node = self.match.fx_root.attachNewNode("ghost")
        solid.copyTo(node)
        if glow is not None:
            glow.copyTo(node)
        node.setTransparency(TransparencyAttrib.M_alpha)
        node.setDepthWrite(False)
        node.setBin("transparent", 40)
        node.setShaderInput("u_emissive", 0.6)
        self.ghost = node

    def update(self, dt: float) -> None:
        m = self.match
        if m is None or self.player is None:
            return
        if self.box_start is not None:
            sx, sy = self.box_start
            if not self.dragging and math.hypot(mouse.x - sx, mouse.y - sy) > DRAG_THRESHOLD:
                self.dragging = True
            if self.dragging:
                self.box.enabled = True
                self.box.position = (min(sx, mouse.x), min(sy, mouse.y), -1)
                self.box.scale = (max(abs(mouse.x - sx), 0.001), max(abs(mouse.y - sy), 0.001))
        if self.ghost is not None:
            gp = self.ground_point()
            if gp is None:
                self.ghost.hide()
            else:
                self.ghost.show()
                btype = self.mode_arg
                size = int(data.buildings()[btype]["footprint"])
                cx, cz = m.grid.snap_footprint(gp[0], gp[1], size)
                ok, _ = m.economy.can_place(self.player, btype, cx, cz)
                self.ghost_ok = ok
                self.ghost.setPos(cx, m.terrain.height(cx, cz), cz)
                if ok:
                    self.ghost.setColorScale(0.5, 1.4, 0.6, 0.6)
                else:
                    self.ghost.setColorScale(1.6, 0.4, 0.35, 0.6)
        self._hover_t = getattr(self, "_hover_t", 0) + 1
        if self._hover_t % 3 == 0:
            self.hover = None if self.over_ui() else self.pick()

    def destroy(self) -> None:
        self.cancel_mode()
        self.box.enabled = False
