"""Worker behaviour: mining gold, chopping timber, returning cargo and constructing buildings."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from core import data
from core.actor import Order
from core.events import events
from core.meshgen import MeshBuilder
from core.rig import copy_part
from settings import CELL, CHOP_TIME, GOLD_PER_TRIP, MINE_TIME, TIMBER_PER_TRIP

if TYPE_CHECKING:
    from core.match import Match
    from core.player import Player
    from units.unit import Unit

HALL_MINE_GAP = 9.5      # town halls must be at least this far from gold mines (centre to centre)


def _sack() -> MeshBuilder:
    mb = MeshBuilder()
    mb.sphere((0, 0, 0), (0.28, 0.24, 0.26), (0.6, 0.48, 0.3, 1), detail=0)
    mb.sphere((0, 0.18, 0), (0.14, 0.1, 0.14), (1.0, 0.82, 0.25, 1), detail=0)
    return mb


def _logs() -> MeshBuilder:
    mb = MeshBuilder()
    for k in range(3):
        mb.cylinder((-0.35, (k % 2) * 0.16, -0.1 + k * 0.1), 0.09, 0.7, (0.55, 0.38, 0.22, 1), segments=5, rot=(0, 0, 90))
    return mb


class Economy:
    """Drives every worker's gather/return/build orders for a match."""

    def __init__(self, match: "Match") -> None:
        self.match = match

    # ================================================================== commands
    def order_gather(self, workers: list["Unit"], resource: Any, queue: bool = False) -> None:
        for w in workers:
            if w.alive and w.is_worker:
                w.command(Order("gather", resource.x, resource.z, target=resource), queue)

    def order_return(self, workers: list["Unit"], queue: bool = False) -> None:
        for w in workers:
            if w.alive and w.is_worker and w.carry > 0:
                w.command(Order("return"), queue)

    def order_build(self, worker: "Unit", type_id: str, x: float, z: float, queue: bool = False) -> str | None:
        """Pay for a building and send ``worker`` to start it. Returns an error message or None."""
        p = worker.owner
        bdef = data.buildings()[type_id]
        ok, why = self.can_place(p, type_id, x, z)
        if not ok:
            return why
        missing = p.missing_requirements(bdef)
        if missing:
            return "Requires " + ", ".join(missing)
        if not p.spend(bdef["cost"]):
            return "Not enough gold" if p.gold < bdef["cost"].get("gold", 0) else "Not enough timber"
        cx, cz = self.match.grid.snap_footprint(x, z, int(bdef["footprint"]))
        worker.command(Order("build", cx, cz, data={"type": type_id, "site": None, "paid": True}), queue)
        return None

    def order_construct(self, workers: list["Unit"], site: Any, queue: bool = False) -> None:
        """Send workers to help finish (or repair-continue) an unfinished building."""
        for w in workers:
            if w.alive and w.is_worker and w.owner is site.owner:
                w.command(Order("build", site.x, site.z, target=site, data={"type": site.type_id, "site": site, "paid": True}), queue)

    # ================================================================== placement
    def can_place(self, player: "Player", type_id: str, x: float, z: float) -> tuple[bool, str]:
        m = self.match
        bdef = data.buildings()[type_id]
        if bdef.get("buildable") is False:
            return False, "Cannot build that"
        size = int(bdef["footprint"])
        grid = m.grid
        i0, j0 = grid.footprint_origin(x, z, size)
        if not grid.area_free(i0, j0, size):
            return False, "Can't build there"
        cx, cz = grid.snap_footprint(x, z, size)
        hs = [grid.cell_height[j, i] for j in range(j0, j0 + size) for i in range(i0, i0 + size)]
        if max(hs) - min(hs) > 1.6:
            return False, "Ground is too uneven"
        if m.fog.display_team >= 0 and player is m.human:
            if not m.fog.explored[player.team][j0:j0 + size, i0:i0 + size].all():
                return False, "Can't build in unexplored land"
        if bdef.get("town_hall"):
            for mine in m.map.mines:
                if mine.alive and math.hypot(mine.x - cx, mine.z - cz) < HALL_MINE_GAP:
                    return False, "Too close to the gold mine"
        else:
            for mine in m.map.mines:
                if mine.alive:
                    ex, ez = mine.entrance
                    if math.hypot(ex - cx, ez - cz) < size * CELL * 0.5 + 1.5:
                        return False, "Blocks the mine entrance"
        return True, ""

    # ================================================================== helpers
    def dropoffs(self, player: "Player", kind: str) -> list[Any]:
        return [b for b in self.match.buildings if b.alive and b.complete and b.owner is player and kind in b.dropoff]

    def nearest_dropoff(self, unit: "Unit", kind: str) -> Any:
        best, bd = None, 1e9
        for b in self.dropoffs(unit.owner, kind):
            d = math.hypot(b.x - unit.x, b.z - unit.z) - b.radius
            if d < bd:
                best, bd = b, d
        return best

    def approach_point(self, unit: "Unit", b: Any) -> tuple[float, float]:
        """Closest walkable point just outside a building's footprint."""
        half = b.footprint * CELL * 0.5 + 0.7
        px = min(max(unit.x, b.x - half), b.x + half)
        pz = min(max(unit.z, b.z - half), b.z + half)
        if abs(px - b.x) < half and abs(pz - b.z) < half:
            # unit is inside the box (should not happen) -> push to nearest side
            dx, dz = unit.x - b.x, unit.z - b.z
            if abs(dx) > abs(dz):
                px = b.x + math.copysign(half, dx)
            else:
                pz = b.z + math.copysign(half, dz)
        g = self.match.grid
        if not g.walkable(px, pz):
            c = g.nearest_walkable(g.cell_of(px, pz), max_r=4)
            if c is not None:
                px, pz = g.center(c)
        return px, pz

    def tree_access(self, tree: Any, ux: float, uz: float) -> tuple[float, float] | None:
        """A walkable spot next to ``tree`` (closest to the worker), or None if it is enclosed."""
        g = self.match.grid
        w = g.w
        ti, tj = tree.cell % w, tree.cell // w
        best, bd = None, 1e9
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                if g.walkable_cell(ti + di, tj + dj):
                    cx, cz = g.center((tj + dj) * w + ti + di)
                    d = (cx - ux) ** 2 + (cz - uz) ** 2
                    if d < bd:
                        best, bd = (cx, cz), d
        return best

    def find_tree(self, unit: "Unit", near: tuple[float, float], exclude: Any = None, max_dist: float = 45.0) -> Any:
        forest = self.match.map.forest
        nx, nz = near
        cands = sorted((t for t in forest.trees if t.alive and t is not exclude and
                        (t.x - nx) ** 2 + (t.z - nz) ** 2 < max_dist * max_dist),
                       key=lambda t: (t.x - nx) ** 2 + (t.z - nz) ** 2 + t.choppers * 6.0)
        for t in cands[:40]:
            if self.tree_access(t, unit.x, unit.z) is not None:
                return t
        return None

    def _set_carry(self, unit: "Unit", kind: str | None, amount: int) -> None:
        unit.carry_kind = kind if amount > 0 else None
        unit.carry = amount
        old = getattr(unit, "carry_node", None)
        if old is not None:
            old.removeNode()
        if amount > 0 and unit.node is not None:
            if kind == "gold":
                n = copy_part(("carry_sack",), _sack, unit.rig.body)
                n.setPos(0.0, unit.rig.height * 0.55, -0.35)
            else:
                n = copy_part(("carry_logs",), _logs, unit.rig.body)
                n.setPos(0.35, unit.rig.height * 0.62, -0.25)
            unit.carry_node = n
        else:
            unit.carry_node = None

    def _hide(self, unit: "Unit", hidden: bool) -> None:
        unit.hidden = hidden
        if unit.node is not None:
            if hidden:
                unit.node.hide()
            else:
                unit.node.show()

    # ================================================================== per-frame worker logic
    def update_worker(self, u: "Unit", o: Order, dt: float) -> bool:
        """Advance a worker order. Returns False when the order is finished."""
        if o.kind == "gather":
            return self._gather(u, o, dt)
        if o.kind == "return":
            return self._return(u, o, dt)
        if o.kind == "build":
            return self._build(u, o, dt)
        return False

    def _gather(self, u: "Unit", o: Order, dt: float) -> bool:
        w = u.work
        res = o.target
        is_tree = getattr(res, "is_tree", False)
        kind = "timber" if is_tree else "gold"
        w["ghost"] = True
        w.setdefault("phase", "to_res")
        u.work["last_res"] = res
        if res is None or not res.alive or (not is_tree and res.depleted):
            # find a replacement of the same kind nearby
            rx, rz = (res.x, res.z) if res is not None else (u.x, u.z)
            if is_tree:
                nres = self.find_tree(u, (rx, rz), exclude=res)
            else:
                nres = self.match.map.mine_near(rx, rz, 45)
            if nres is None:
                if u.carry > 0 and w["phase"] != "to_drop":
                    w["phase"] = "to_drop"
                elif u.carry <= 0:
                    return False
            else:
                o.target = res = nres
                o.x, o.z = res.x, res.z
                if w["phase"] in ("to_res", "wait", "chop"):
                    w["phase"] = "to_res"
                    w.pop("dest", None)
        phase = w["phase"]
        if phase == "to_res" and u.carry > 0 and (u.carry_kind != kind or u.carry >= (GOLD_PER_TRIP if kind == "gold" else TIMBER_PER_TRIP)):
            phase = w["phase"] = "to_drop"
            w.pop("dest", None)
        if phase == "to_res":
            if is_tree:
                dest = w.get("dest")
                if dest is None:
                    dest = self.tree_access(res, u.x, u.z)
                    if dest is None:
                        nres = self.find_tree(u, (res.x, res.z), exclude=res)
                        if nres is None:
                            return False
                        o.target = nres
                        return True
                    w["dest"] = dest
                    u.move_to(dest[0], dest[1], arrive=0.35)
                if u.goal is None and math.hypot(u.x - dest[0], u.z - dest[1]) > 0.6:
                    u.move_to(dest[0], dest[1], arrive=0.35)
                if u._follow_path(dt):
                    w["phase"] = "chop"
                    w["t"] = CHOP_TIME
                    w["swing"] = 0.0
                    res.choppers += 1
                    w.pop("dest", None)
            else:
                ex, ez = res.entrance
                if u.goal is None or math.hypot(u.goal[0] - ex, u.goal[1] - ez) > 0.5:
                    u.move_to(ex, ez, arrive=1.1)
                if u._follow_path(dt) or math.hypot(u.x - ex, u.z - ez) < 1.3:
                    u.halt()
                    w["phase"] = "wait"
                    w["t"] = 0.0
            return True
        if phase == "wait":
            if res.has_room():
                res.inside.append(u)
                self._hide(u, True)
                w["phase"] = "inside"
                w["t"] = MINE_TIME
            return True
        if phase == "inside":
            w["t"] -= dt
            if w["t"] <= 0:
                got = res.take(GOLD_PER_TRIP)
                if u in res.inside:
                    res.inside.remove(u)
                ex, ez = res.entrance
                u.x, u.z = ex, ez
                self._hide(u, False)
                self._set_carry(u, "gold", got)
                w["phase"] = "to_drop"
                w.pop("dest", None)
            return True
        if phase == "chop":
            if not res.alive:
                w["phase"] = "to_res"
                return True
            from core.util import yaw_to
            u._turn_towards(yaw_to(res.x - u.x, res.z - u.z), dt)
            w["swing"] -= dt
            if w["swing"] <= 0:
                w["swing"] = 0.9
                u.rig.play("attack", 0.6)
                res.shake = 0.3
                if u.on_screen:
                    self.match.fx.burst((res.x, res.y + 1.2, res.z), "wood", 3, 2.5, 0.4, 0.08)
                    events.emit("sound", name="chop", pos=(res.x, res.z))
            w["t"] -= dt
            if w["t"] <= 0:
                res.choppers = max(0, res.choppers - 1)
                got = self.match.map.forest.harvest(res, TIMBER_PER_TRIP)
                self._set_carry(u, "timber", got)
                w["phase"] = "to_drop"
                w.pop("dest", None)
            return True
        if phase == "to_drop":
            drop = self.nearest_dropoff(u, u.carry_kind or kind)
            if drop is None:
                u.halt()
                return True  # wait until a drop-off exists
            dest = w.get("dest")
            if dest is None or w.get("drop") is not drop:
                dest = self.approach_point(u, drop)
                w["dest"] = dest
                w["drop"] = drop
                u.move_to(dest[0], dest[1], arrive=0.6)
            arrived = u._follow_path(dt) or u.edge_dist(drop) < 1.0
            if arrived:
                u.halt()
                if u.carry > 0:
                    u.owner.add(u.carry_kind or kind, u.carry)
                    events.emit("deposit", unit=u, kind=u.carry_kind, amount=u.carry)
                self._set_carry(u, None, 0)
                w["phase"] = "to_res"
                w.pop("dest", None)
                w.pop("drop", None)
            return True
        return False

    def _return(self, u: "Unit", o: Order, dt: float) -> bool:
        if u.carry <= 0:
            return False
        drop = self.nearest_dropoff(u, u.carry_kind or "gold")
        if drop is None:
            return False
        w = u.work
        if w.get("drop") is not drop:
            dest = self.approach_point(u, drop)
            w["drop"] = drop
            u.move_to(dest[0], dest[1], arrive=0.6)
        if u._follow_path(dt) or u.edge_dist(drop) < 1.0:
            u.owner.add(u.carry_kind or "gold", u.carry)
            self._set_carry(u, None, 0)
            last = w.get("last_res")
            w.pop("drop", None)
            if last is not None and last.alive and not u.orders:
                u.orders.append(Order("gather", last.x, last.z, target=last))
            return False
        return True

    def _build(self, u: "Unit", o: Order, dt: float) -> bool:
        w = u.work
        m = self.match
        site = o.data.get("site")
        btype = o.data["type"]
        bdef = data.buildings()[btype]
        if site is None:
            half = int(bdef["footprint"]) * CELL * 0.5
            dist = max(abs(u.x - o.x), abs(u.z - o.z)) - half
            if dist > 1.4:
                if u.goal is None:
                    tx, tz = self._edge_point(u, o.x, o.z, half + 0.8)
                    u.move_to(tx, tz, arrive=0.8)
                if not u._follow_path(dt):
                    return True
            u.halt()
            ok, why = self.can_place(u.owner, btype, o.x, o.z)
            if not ok:
                if o.data.get("paid"):
                    u.owner.refund(bdef["cost"])
                    o.data["paid"] = False
                events.emit("notice", player=u.owner, text=why)
                return False
            site = m.spawn_building(u.owner, btype, o.x, o.z, complete=False)
            o.data["site"] = site
            o.data["paid"] = False
            events.emit("construction_started", building=site, worker=u)
            events.emit("sound", name="build", pos=(site.x, site.z))
            if site.self_building:
                m.fx.burst((site.x, site.y + 1, site.z), "magic", 24, 4.0, 0.8, 0.22, gravity=-2)
                return False  # Host thralls summon the structure and walk away
        if not site.alive:
            return False
        if site.complete:
            if site.hp < site.max_hp and not site.self_building:
                site.hp = min(site.max_hp, site.hp + site.max_hp / site.build_time * dt * 0.5)
                if site.hp >= site.max_hp:
                    return False
            else:
                return False
        if u.edge_dist(site) > 1.3:
            if u.goal is None:
                tx, tz = self.approach_point(u, site)
                u.move_to(tx, tz, arrive=0.6)
            u._follow_path(dt)
            return True
        u.halt()
        from core.util import yaw_to
        u._turn_towards(yaw_to(site.x - u.x, site.z - u.z), dt)
        if not site.complete:
            helpers = sum(1 for b in m.units if b.alive and b.order is not None and b.order.kind == "build"
                          and b.order.data.get("site") is site and b.edge_dist(site) <= 1.3)
            rate = 1.0 if helpers <= 1 else (1.0 + 0.6 * (helpers - 1)) / helpers
            site.add_progress(dt * rate)
        w["hammer"] = w.get("hammer", 0.0) - dt
        if w["hammer"] <= 0:
            w["hammer"] = 0.7
            u.rig.play("attack", 0.5)
            if u.on_screen:
                m.fx.burst((u.x, u.y + 0.8, u.z), "dust", 3, 2.0, 0.35, 0.1)
        return True

    def _edge_point(self, u: "Unit", cx: float, cz: float, half: float) -> tuple[float, float]:
        px = min(max(u.x, cx - half), cx + half)
        pz = min(max(u.z, cz - half), cz + half)
        if abs(px - cx) < half and abs(pz - cz) < half:
            px = cx + math.copysign(half, u.x - cx)
        g = self.match.grid
        if not g.walkable(px, pz):
            c = g.nearest_walkable(g.cell_of(px, pz), max_r=5)
            if c is not None:
                px, pz = g.center(c)
        return px, pz

    # ================================================================== bookkeeping
    def abort(self, u: "Unit") -> None:
        """Clean up when a worker's order is interrupted."""
        w = u.work
        o = u.order
        if o is not None and o.kind == "gather" and o.target is not None:
            res = o.target
            if w.get("phase") == "inside" and u in getattr(res, "inside", []):
                res.inside.remove(u)
                ex, ez = res.entrance
                u.x, u.z = ex, ez
                self._hide(u, False)
            if w.get("phase") == "chop" and getattr(res, "is_tree", False):
                res.choppers = max(0, res.choppers - 1)
        last = w.get("last_res")
        w.clear()
        if last is not None:
            w["last_res"] = last

    def on_unit_died(self, u: "Unit") -> None:
        if u.is_worker:
            o = u.order
            for mine in self.match.map.mines:
                if u in mine.inside:
                    mine.inside.remove(u)
            if o is not None and o.kind == "gather" and getattr(o.target, "is_tree", False) and u.work.get("phase") == "chop":
                o.target.choppers = max(0, o.target.choppers - 1)
            if getattr(u, "carry_node", None) is not None:
                u.carry_node.removeNode()
                u.carry_node = None
            u.work.clear()

    def on_building_complete(self, b: Any) -> None:
        pass

    def on_building_destroyed(self, b: Any) -> None:
        pass

    def update(self, dt: float) -> None:
        pass
