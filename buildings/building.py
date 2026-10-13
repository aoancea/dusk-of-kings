"""Buildings: placement footprint, construction, production and research queues, towers."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from core import data
from core.actor import Actor, Order
from core.events import events
from core.util import set_yaw, yaw_to
from settings import CELL

if TYPE_CHECKING:
    from core.match import Match
    from core.player import Player

MAX_QUEUE = 5


class QueueItem:
    """One entry in a building's production queue (a unit, an upgrade or a town-hall upgrade)."""

    def __init__(self, kind: str, type_id: str, time: float, cost: dict[str, int]) -> None:
        self.kind = kind          # unit | research | upgrade_hall
        self.type_id = type_id
        self.time = time
        self.cost = cost
        self.progress = 0.0

    @property
    def frac(self) -> float:
        return min(1.0, self.progress / self.time) if self.time > 0 else 1.0


class Building(Actor):
    """A structure on the grid. Created as a construction site unless ``complete``."""

    is_building = True

    def __init__(self, match: "Match", owner: "Player", type_id: str, x: float, z: float, complete: bool = False) -> None:
        defn = data.buildings()[type_id]
        self.footprint = int(defn["footprint"])
        grid = match.grid
        self.cell_origin = grid.footprint_origin(x, z, self.footprint)
        cx = grid.origin + (self.cell_origin[0] + self.footprint / 2.0) * CELL
        cz = grid.origin + (self.cell_origin[1] + self.footprint / 2.0) * CELL
        super().__init__(match, owner, type_id, defn, cx, cz)
        self.radius = self.footprint * CELL * 0.5
        self.sight = float(defn.get("sight", 10))
        self.attack: dict[str, Any] | None = defn.get("attack")
        self.attack_cd = 0.0
        self.target: Actor | None = None
        self.complete = complete
        self.build_progress = 1.0 if complete else 0.0
        self.build_time = float(defn.get("build_time", 30))
        self.builders: list[Any] = []
        self.self_building = owner.fdef.get("builders_stay") is False
        self.hp = self.max_hp if complete else max(1.0, self.max_hp * 0.1)
        self.queue: list[QueueItem] = []
        self.rally: tuple[float, float] | None = None
        self.rally_target: Actor | None = None
        self.seen_by: set[int] = {owner.team}
        self.remembered = False
        self.town_hall = bool(defn.get("town_hall"))
        self.dropoff: list[str] = list(defn.get("dropoff", []))
        ys = [match.terrain.height(cx + dx, cz + dz) for dx in (-self.radius, 0, self.radius) for dz in (-self.radius, 0, self.radius)]
        self.y = sum(ys) / len(ys)
        self.base_y = min(ys)
        grid.block_rect(*self.cell_origin, self.footprint, self.footprint, 1)
        from buildings.models import build_building_node
        self.node = match.building_root.attachNewNode(f"bld_{type_id}")
        self.model = build_building_node(type_id, owner.faction, owner.color, self.node, self.y - self.base_y)
        self.height = float(self.model.getTightBounds()[1].y) if self.model.getTightBounds() else 4.0
        self.node.setPos(self.x, self.y, self.z)
        # the model's front (-z) faces the camera (south) so doors and banners are visible
        self.yaw = 0.0
        set_yaw(self.node, self.yaw)
        self.light = None
        self._apply_construction_visual()
        if complete:
            self._on_complete(initial=True)

    # ================================================================== state
    @property
    def armor(self) -> float:
        return self.base_armor

    @property
    def attack_range(self) -> float:
        return float(self.attack.get("range", 0)) if self.attack else 0.0

    def can_attack(self, other: Actor) -> bool:
        if not self.attack or not other.alive or other.is_mine:
            return False
        targets = self.attack.get("targets", ["ground"])
        return ("air" in targets) if other.flying else ("ground" in targets)

    def in_attack_range(self, other: Actor) -> bool:
        return self.edge_dist(other) <= self.attack_range

    @property
    def is_upgrading(self) -> bool:
        return any(q.kind == "upgrade_hall" for q in self.queue)

    @property
    def front(self) -> tuple[float, float]:
        """Unit vector the building's door faces."""
        r = math.radians(self.yaw + 180.0)
        return math.sin(r), math.cos(r)

    def trains(self) -> list[str]:
        return list(self.defn.get("trains", []))

    def researches(self) -> list[str]:
        return list(self.defn.get("research", []))

    # ================================================================== construction
    def add_progress(self, dt: float) -> None:
        if self.complete or not self.alive:
            return
        step = dt / self.build_time
        self.build_progress = min(1.0, self.build_progress + step)
        self.hp = min(self.max_hp, self.hp + self.max_hp * 0.9 * step)
        self._apply_construction_visual()
        if self.build_progress >= 1.0:
            self._on_complete()

    def _apply_construction_visual(self) -> None:
        if self.model is None:
            return
        if self.complete:
            self.model.setScale(1.0)
            self.model.setColorScale(1, 1, 1, 1)
            return
        k = self.build_progress
        self.model.setScale(1.0, 0.15 + 0.85 * k, 1.0)
        shade = 0.55 + 0.45 * k
        self.model.setColorScale(shade, shade * 0.95, shade * 0.9, 1)

    def _add_light(self) -> None:
        from world.sky import PointLight
        fx, fz = self.front
        r = self.footprint * CELL * 0.5
        warm = (1.0, 0.62, 0.3) if self.owner.faction == "alliance" else (1.0, 0.42, 0.15)
        self.light = PointLight((self.x + fx * (r + 1.0), self.y + 2.5, self.z + fz * (r + 1.0)), 9.0 + r, warm, 0.08,
                                flicker=0.15, night_boost=4.0)
        self.match.env.add_light(self.light)

    def _on_complete(self, initial: bool = False) -> None:
        self.complete = True
        self.build_progress = 1.0
        self._apply_construction_visual()
        self._add_light()
        p = self.owner
        p.completed[self.type_id] += 1
        p.supply_cap += int(self.defn.get("supply", 0))
        if not initial:
            p.stats["buildings_built"] += 1
            events.emit("building_complete", building=self)
        self.match.economy.on_building_complete(self)

    # ================================================================== production
    def can_queue(self) -> bool:
        return self.complete and self.alive and len(self.queue) < MAX_QUEUE

    def enqueue_unit(self, unit_type: str) -> str | None:
        """Start training a unit. Returns an error message or None."""
        p = self.owner
        udef = data.units()[unit_type]
        if unit_type not in self.trains():
            return "Cannot train that here"
        if not self.can_queue():
            return "Queue is full" if self.complete else "Building is not finished"
        if self.is_upgrading:
            return "Building is upgrading"
        missing = p.missing_requirements(udef)
        if missing:
            return "Requires " + ", ".join(missing)
        cost = udef["cost"]
        if not p.can_afford(cost):
            return "Not enough gold" if p.gold < cost.get("gold", 0) else "Not enough timber"
        p.spend(cost)
        self.queue.append(QueueItem("unit", unit_type, float(udef["build_time"]), cost))
        return None

    def enqueue_research(self, up_id: str) -> str | None:
        p = self.owner
        u = data.upgrades()[up_id]
        if not self.can_queue():
            return "Queue is full" if self.complete else "Building is not finished"
        if up_id in p.upgrades or up_id in p.researching:
            return "Already researched"
        missing = p.missing_requirements(u)
        if missing:
            return "Requires " + ", ".join(missing)
        if not p.can_afford(u["cost"]):
            return "Not enough gold" if p.gold < u["cost"].get("gold", 0) else "Not enough timber"
        p.spend(u["cost"])
        p.researching.add(up_id)
        kind = "upgrade_hall" if u.get("town_hall_upgrade") else "research"
        self.queue.append(QueueItem(kind, up_id, float(u["time"]), u["cost"]))
        return None

    def cancel(self, index: int = -1) -> None:
        """Cancel a queue entry (refunded) or, with an empty queue, a construction site (75% refund)."""
        if self.queue:
            item = self.queue.pop(index)
            self.owner.refund(item.cost)
            if item.kind != "unit":
                self.owner.researching.discard(item.type_id)
            return
        if not self.complete:
            self.owner.refund(self.defn["cost"], 0.75)
            self.match.kill(self, None)

    def _finish_item(self, item: QueueItem) -> bool:
        """Complete the head of the queue. Returns False if it must wait (e.g. supply)."""
        p = self.owner
        if item.kind == "unit":
            udef = data.units()[item.type_id]
            if not p.has_supply(int(udef.get("supply", 1))):
                if not getattr(self, "_supply_warned", False):
                    self._supply_warned = True
                    events.emit("notice", player=p, text="Not enough supply - build more " +
                                data.buildings()[p.fdef["supply_building"]]["name"] + "s")
                return False
            self._supply_warned = False
            x, z = self._spawn_point(udef)
            u = self.match.spawn_unit(p, item.type_id, x, z, self.yaw)
            p.stats["units_trained"] += 1
            self._send_to_rally(u)
            events.emit("unit_trained", unit=u, building=self)
        elif item.kind == "research":
            p.researching.discard(item.type_id)
            p.upgrades.add(item.type_id)
            events.emit("research_complete", player=p, upgrade=item.type_id)
        elif item.kind == "upgrade_hall":
            p.researching.discard(item.type_id)
            new_type = data.upgrades()[item.type_id]["town_hall_upgrade"]
            self.transform(new_type)
        return True

    def _spawn_point(self, udef: dict[str, Any]) -> tuple[float, float]:
        if udef.get("flying"):
            return self.x, self.z
        grid = self.match.grid
        fx, fz = self.front
        tx, tz = self.rally if self.rally else (self.x + fx * (self.radius + 4), self.z + fz * (self.radius + 4))
        best, bd = None, 1e9
        i0, j0 = self.cell_origin
        f = self.footprint
        for j in range(j0 - 1, j0 + f + 1):
            for i in range(i0 - 1, i0 + f + 1):
                if i0 <= i < i0 + f and j0 <= j < j0 + f:
                    continue
                if grid.walkable_cell(i, j):
                    cx, cz = grid.center(j * grid.w + i)
                    d = (cx - tx) ** 2 + (cz - tz) ** 2
                    if d < bd:
                        best, bd = (cx, cz), d
        return best if best else (self.x, self.z - self.radius - 1)

    def _send_to_rally(self, u: Any) -> None:
        if self.rally_target is not None and self.rally_target.alive:
            t = self.rally_target
            if u.is_worker and (t.is_mine or getattr(t, "is_tree", False)):
                self.match.economy.order_gather([u], t)
                return
            self.match.order_units([u], "follow" if t.team == u.team else "attack", target=t)
            return
        if self.rally is not None:
            self.match.order_units([u], "move", *self.rally)
        elif u.is_worker:
            mine = self.match.map.mine_near(self.x, self.z, 30)
            if mine is not None:
                self.match.economy.order_gather([u], mine)

    def transform(self, new_type: str) -> None:
        """Upgrade in place (Keep -> Castle): swap definition and model, keep hp ratio."""
        p = self.owner
        frac = self.hp_frac
        p.completed[self.type_id] -= 1
        p.supply_cap -= int(self.defn.get("supply", 0))
        self.type_id = new_type
        self.defn = data.buildings()[new_type]
        self.name = self.defn["name"]
        self.max_hp = float(self.defn["hp"])
        self.hp = self.max_hp * frac
        self.base_armor = float(self.defn.get("armor", 0))
        self.sight = float(self.defn.get("sight", self.sight))
        p.completed[new_type] += 1
        p.supply_cap += int(self.defn.get("supply", 0))
        if self.model is not None:
            self.model.removeNode()
        from buildings.models import build_building_node
        self.model = build_building_node(new_type, p.faction, p.color, self.node, self.y - self.base_y)
        b = self.model.getTightBounds()
        self.height = float(b[1].y) if b else self.height
        events.emit("building_upgraded", building=self)

    # ================================================================== update
    def update(self, dt: float) -> None:
        if not self.complete:
            if self.self_building:
                self.add_progress(dt)
            return
        if self.queue:
            item = self.queue[0]
            item.progress += dt
            if item.progress >= item.time:
                if self._finish_item(item):
                    self.queue.pop(0)
                else:
                    item.progress = item.time
        if self.attack is not None:
            self._tower(dt)

    def _tower(self, dt: float) -> None:
        if self.attack_cd > 0:
            self.attack_cd -= dt
        t = self.target
        if t is None or not t.alive or not self.in_attack_range(t) or not self.match.is_visible_to(t, self.team):
            self.target = None
            return
        if self.attack_cd <= 0:
            self.attack_cd = float(self.attack.get("cooldown", 1.5))
            self.match.combat.launch(self, t)

    # ================================================================== visuals
    def present(self, dt: float, human_team: int, vis_bytes) -> None:
        """Show if visible, or remembered from an earlier sighting (fog of war)."""
        if self.node is None:
            return
        if vis_bytes is None or self.team == human_team:
            vis = True
        else:
            seen = vis_bytes[self.match.grid.cell_of(self.x, self.z)] > 0
            if seen:
                self.remembered = True
            vis = self.remembered
            self.visible = seen
            if self.node.isHidden() == vis:
                if vis:
                    self.node.show()
                else:
                    self.node.hide()
            return
        self.visible = vis
        if self.node.isHidden():
            self.node.show()

    def on_destroyed(self) -> None:
        """Remove from the world: unblock cells, refund supply, collapse effect."""
        self.alive = False
        p = self.owner
        if self.complete:
            p.completed[self.type_id] -= 1
            p.supply_cap -= int(self.defn.get("supply", 0))
        for item in self.queue:
            if item.kind != "unit":
                p.researching.discard(item.type_id)
        self.queue.clear()
        p.stats["buildings_lost"] += 1
        self.match.grid.block_rect(*self.cell_origin, self.footprint, self.footprint, -1)
        if self.light is not None:
            self.match.env.remove_light(self.light)
            self.light = None
        self.match.economy.on_building_destroyed(self)
        if self.visible or self.remembered:
            self.match.fx.collapse(self.x, self.y, self.z, self.radius)
        events.emit("sound", name="collapse", pos=(self.x, self.z))
        self.destroy()
