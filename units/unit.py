"""Mobile units: order queue, path following, target acquisition hooks and attacks."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from panda3d.core import BoundingSphere, Point3

from core import data
from core.actor import Actor, Order
from core.util import angle_diff, set_yaw, yaw_to
from settings import FLY_HEIGHT
from units.models import build_unit_rig
from units.skinning import Skin

if TYPE_CHECKING:
    from core.match import Match
    from core.player import Player

LEASH = 14.0             # idle units chase this far from where they stood
MELEE_RANGE = 1.5        # attacks with range below this are melee swings
WAYPOINT_REACH = 0.9


class GroupPath:
    """A path shared by every unit of one group order (computed once, followed by all)."""

    def __init__(self) -> None:
        self.pts: list[tuple[float, float]] | None = None

    @property
    def ready(self) -> bool:
        return self.pts is not None


class Unit(Actor):
    """A unit that can move, fight, gather and build according to its order queue."""

    is_unit = True

    def __init__(self, match: "Match", owner: "Player", type_id: str, x: float, z: float, yaw: float = 0.0) -> None:
        defn = data.units()[type_id]
        super().__init__(match, owner, type_id, defn, x, z)
        self.role: str = defn.get("role", "melee")
        self.flying = bool(defn.get("flying", False))
        self.speed = float(defn["speed"])
        self.supply = int(defn.get("supply", 1))
        self.attack: dict[str, Any] | None = defn.get("attack")
        self.turn_rate = float(defn.get("turn_rate", 720.0))
        self.is_worker = self.role == "worker"
        self.max_mana = float(defn.get("mana", 0))
        self.mana = self.max_mana * 0.5
        self.mana_regen = float(defn.get("mana_regen", 0))
        self.abilities: list[str] = list(defn.get("abilities", []))
        self.ability_cd: dict[str, float] = {}
        self.autocast: set[str] = {a for a in self.abilities if data.abilities()[a].get("autocast")}
        self.buffs: dict[str, float] = {}
        self.yaw = yaw
        # orders & movement
        self.orders: list[Order] = []
        self.order: Order | None = None
        self.path: list[tuple[float, float]] = []
        self.path_i = 0
        self.goal: tuple[float, float] | None = None
        self.arrive = 0.4
        self._req = 0
        self.path_pending = False
        self._group: GroupPath | None = None
        self._prog_t = 0.0
        self._prog_d = 0.0
        self._stalls = 0
        self.anchor = (x, z)
        self.moving = False
        self.cur_speed = 0.0
        self._px, self._pz = x, z
        # combat
        self.target: Actor | None = None
        self.attack_cd = random.random() * 0.4
        self.acquire_t = random.random() * 0.3
        self._chase_t = 0.0
        self._windup: tuple[float, Actor] | None = None
        # economy
        self.carry_kind: str | None = None
        self.carry = 0
        self.work: dict[str, Any] = {}
        self.hidden = False          # inside a gold mine
        self.on_screen = False
        self.anim_dt = 0.0
        self._synced = (None, None, None, None)
        self.corpse_t = 0.0
        # visuals
        self.rig = build_unit_rig(defn["model"], owner.color)
        self.height = self.rig.height
        self.node = match.unit_root.attachNewNode(f"unit_{type_id}")
        self.rig.root.reparentTo(self.node)
        try:
            self.skin: Skin | None = Skin(self.rig, (type_id, tuple(round(c, 3) for c in owner.color)))
        except ValueError:
            self.skin = None
        # cull the whole unit as one sphere instead of testing every animated part
        r = max(self.rig.height, self.rig.radius * 2.0) * 0.75 + 0.5
        self.node.node().setBounds(BoundingSphere(Point3(0, self.rig.height * 0.5, 0), r))
        self.node.node().setFinal(True)
        if self.flying:
            self.y = self.fly_height()
        self.sync_node()

    # ================================================================== properties
    @property
    def armor(self) -> float:
        return self.base_armor + self.owner.armor_bonus(self.defn)

    @property
    def attack_range(self) -> float:
        return float(self.attack.get("range", 0)) if self.attack else 0.0

    @property
    def is_melee(self) -> bool:
        return self.attack_range < MELEE_RANGE

    @property
    def move_speed(self) -> float:
        s = self.speed
        if "slow" in self.buffs:
            s *= 0.5
        return s

    def fly_height(self) -> float:
        return max(self.match.terrain.height(self.x, self.z), 0.0) + FLY_HEIGHT

    def can_attack(self, other: Actor) -> bool:
        if self.attack is None or not other.alive or other.is_mine:
            return False
        targets = self.attack.get("targets", ["ground"])
        if other.flying:
            return "air" in targets
        return "ground" in targets

    def in_attack_range(self, other: Actor) -> bool:
        d = self.edge_dist(other)
        if d > self.attack_range + (0.25 if self.is_melee else 0.0):
            return False
        mn = float(self.attack.get("min_range", 0)) if self.attack else 0.0
        return d >= mn

    @property
    def wants_targets(self) -> bool:
        """Should the acquisition system look for enemies for this unit?"""
        if self.attack is None or self.is_worker:
            return False
        o = self.order
        return o is None or o.kind in ("attack_move", "patrol", "hold")

    @property
    def acquire_range(self) -> float:
        return max(self.attack_range + 3.0, min(self.sight, 12.0))

    # ================================================================== orders
    def command(self, order: Order, queue: bool = False) -> None:
        if not self.alive:
            return
        if queue and (self.order is not None or self.orders):
            self.orders.append(order)
            return
        self._abort_work()
        self.orders = [order]
        self.order = None
        self.target = None
        self._windup = None
        self.halt()

    def stop(self) -> None:
        self._abort_work()
        self.orders.clear()
        self.order = None
        self.target = None
        self._windup = None
        self.halt()
        self.anchor = (self.x, self.z)

    def _abort_work(self) -> None:
        if self.work:
            self.match.economy.abort(self)

    def _next_order(self) -> None:
        self._abort_work()
        self.order = None
        self.target = None
        self.halt()
        if not self.orders:
            self.anchor = (self.x, self.z)

    def _start(self, o: Order) -> None:
        self.order = o
        if o.kind == "patrol":
            o.data.setdefault("from", (self.x, self.z))
        if o.kind == "attack":
            self.target = o.target
        if o.kind in ("move", "attack_move", "patrol"):
            self.move_to(o.x, o.z, o.data.get("arrive", 0.4), o.data.get("group"))
        if o.kind == "hold":
            self.halt()
            self.anchor = (self.x, self.z)

    # ================================================================== movement
    def move_to(self, x: float, z: float, arrive: float = 0.4, group: GroupPath | None = None) -> None:
        self.goal = (x, z)
        self.arrive = arrive
        self.path = []
        self.path_i = 0
        self._group = None
        self._prog_t = 0.0
        self._prog_d = math.hypot(x - self.x, z - self.z)
        self._stalls = 0
        m = self.match
        if self.flying or m.grid.line_clear(self.x, self.z, x, z):
            self.path = [(x, z)]
            self.path_pending = False
            return
        if group is not None:
            self._group = group
            self.path_pending = True
            if group.ready:
                self._join_group()
            return
        self._request_path(x, z)

    def _request_path(self, x: float, z: float) -> None:
        self._req += 1
        req = self._req
        self.path_pending = True

        def done(pts: list[tuple[float, float]], req: int = req) -> None:
            if req != self._req or not self.alive:
                return
            self.path = pts or []
            self.path_i = 0
            self.path_pending = False

        self.match.paths.request(self.x, self.z, x, z, done)

    def _join_group(self) -> None:
        """Hop onto the shared group path at the furthest waypoint we can see."""
        g = self._group
        assert g is not None and g.pts is not None
        self._group = None
        gx, gz = self.goal or (self.x, self.z)
        pts = g.pts[:-1]
        grid = self.match.grid
        for k in range(len(pts) - 1, -1, -1):
            wx, wz = pts[k]
            if grid.line_clear(self.x, self.z, wx, wz):
                tail = pts[k:]
                lx, lz = tail[-1]
                if grid.line_clear(lx, lz, gx, gz):
                    self.path = tail + [(gx, gz)]
                    self.path_i = 0
                    self.path_pending = False
                    return
                break
        self._request_path(gx, gz)

    def halt(self) -> None:
        self.goal = None
        self.path = []
        self.path_i = 0
        self.path_pending = False
        self._group = None
        self._req += 1
        self.moving = False

    def _follow_path(self, dt: float) -> bool:
        """Advance along the path; returns True once the goal is reached (or given up on)."""
        if self.goal is None:
            return True
        if self._group is not None:
            if self._group.ready:
                self._join_group()
            else:
                return False
        if self.path_pending:
            return False
        if self.path_i >= len(self.path):
            self.moving = False
            return True
        gx, gz = self.goal
        wx, wz = self.path[self.path_i]
        last = self.path_i == len(self.path) - 1
        dx, dz = wx - self.x, wz - self.z
        d = math.hypot(dx, dz)
        reach = self.arrive if last else WAYPOINT_REACH
        if d <= reach:
            self.path_i += 1
            if self.path_i >= len(self.path):
                self.moving = False
                return True
            return False
        step = self.move_speed * dt
        if step > d:
            step = d
        nx = self.x + dx / d * step
        nz = self.z + dz / d * step
        if not self.flying:
            grid = self.match.grid
            if not grid.walkable(nx, nz):
                if grid.walkable(nx, self.z):
                    nz = self.z
                elif grid.walkable(self.x, nz):
                    nx = self.x
                elif not grid.walkable(self.x, self.z):
                    pass  # already inside a blocked cell (pushed): allow escaping
                else:
                    nx, nz = self.x, self.z
        self.x, self.z = nx, nz
        self.moving = True
        self._turn_towards(yaw_to(dx, dz), dt)
        # progress / stall detection
        self._prog_t += dt
        if self._prog_t >= 0.5:
            dist_goal = math.hypot(gx - self.x, gz - self.z)
            if self._prog_d - dist_goal < self.move_speed * 0.5 * 0.2:
                self._stalls += 1
                crowd = 2.0 + math.sqrt(self.match.crowd_hint(self)) * 1.1
                if dist_goal < crowd and self._stalls >= 2:
                    self.moving = False
                    return True
                if self._stalls >= 4 and not self.flying:
                    self._stalls = 0
                    self._request_path(gx, gz)
            else:
                self._stalls = 0
            self._prog_d = dist_goal
            self._prog_t = 0.0
        return False

    def _turn_towards(self, yaw: float, dt: float) -> bool:
        diff = angle_diff(self.yaw, yaw)
        mx = self.turn_rate * dt
        if abs(diff) <= mx:
            self.yaw = yaw
            return True
        self.yaw += mx if diff > 0 else -mx
        return False

    # ================================================================== combat
    def _fight(self, dt: float, target: Actor, can_chase: bool = True) -> bool:
        """Engage ``target``. Returns False when the target is no longer valid."""
        if not target.alive or not self.can_attack(target) or not self.match.is_visible_to(target, self.team):
            return False
        if self.in_attack_range(target):
            if self.moving or self.goal is not None:
                self.halt()
            facing = self._turn_towards(yaw_to(target.x - self.x, target.z - self.z), dt)
            if self.attack_cd <= 0 and self._windup is None and (facing or abs(angle_diff(self.yaw, yaw_to(target.x - self.x, target.z - self.z))) < 35):
                self._begin_attack(target)
            return True
        if not can_chase:
            return False
        mn = float(self.attack.get("min_range", 0)) if self.attack else 0.0
        if mn and self.edge_dist(target) < mn:
            return False
        self._chase_t -= dt
        if self.goal is None or self._chase_t <= 0 or math.hypot(self.goal[0] - target.x, self.goal[1] - target.z) > 2.0:
            self._chase_t = 0.5
            self.move_to(target.x, target.z, arrive=0.1)
        self._follow_path(dt)
        return True

    def _begin_attack(self, target: Actor) -> None:
        a = self.attack
        assert a is not None
        cd = float(a.get("cooldown", 1.5))
        if "frenzy" in self.buffs:
            cd /= 1.35
        if "slow" in self.buffs:
            cd *= 1.5
        self.attack_cd = cd
        melee = self.is_melee
        if self.role == "siege" and not melee:
            self.rig.play("attack", min(cd * 0.8, 1.8))
            wind = 0.55
        elif melee:
            self.rig.play("attack", min(cd * 0.6, 0.65))
            wind = 0.24
        elif self.role == "caster":
            self.rig.play("cast", 0.5)
            wind = 0.3
        else:
            self.rig.play("shoot", min(cd * 0.7, 0.8))
            wind = 0.32
        self._windup = (wind, target)

    def _release_attack(self) -> None:
        assert self._windup is not None
        _, target = self._windup
        self._windup = None
        if not target.alive or not self.alive:
            return
        if self.is_melee:
            if self.edge_dist(target) <= self.attack_range + 1.2:
                self.match.combat.strike(self, target)
        else:
            self.match.combat.launch(self, target)

    # ================================================================== update
    def update(self, dt: float) -> None:
        if not self.alive:
            return
        if self.attack_cd > 0:
            self.attack_cd -= dt
        if self.buffs:
            for k in list(self.buffs):
                self.buffs[k] -= dt
                if self.buffs[k] <= 0:
                    del self.buffs[k]
        if self.max_mana:
            self.mana = min(self.max_mana, self.mana + self.mana_regen * dt)
        for k in list(self.ability_cd):
            self.ability_cd[k] -= dt
            if self.ability_cd[k] <= 0:
                del self.ability_cd[k]
        if self._windup is not None:
            t, tgt = self._windup
            t -= dt
            if t <= 0:
                self._windup = (0.0, tgt)
                self._release_attack()
            else:
                self._windup = (t, tgt)
        if self.order is None and self.orders:
            self._start(self.orders.pop(0))
        o = self.order
        if o is None:
            self._idle(dt)
        elif o.kind == "move":
            if self._follow_path(dt):
                self._next_order()
        elif o.kind == "attack":
            if not self._fight(dt, o.target):
                self._next_order()
        elif o.kind in ("attack_move", "patrol"):
            if self.target is not None and self._fight(dt, self.target):
                pass
            else:
                self.target = None
                if self.goal is None or math.hypot(self.goal[0] - o.x, self.goal[1] - o.z) > 0.5:
                    self.move_to(o.x, o.z, o.data.get("arrive", 0.4), None)
                if self._follow_path(dt):
                    if o.kind == "patrol":
                        fx, fz = o.data["from"]
                        o.data["from"] = (o.x, o.z)
                        o.x, o.z = fx, fz
                        self.move_to(o.x, o.z)
                    else:
                        self._next_order()
        elif o.kind == "hold":
            if self.target is not None and not self._fight(dt, self.target, can_chase=False):
                self.target = None
        elif o.kind == "follow":
            t = o.target
            if not t.alive:
                self._next_order()
            elif self.dist_to(t) > self.radius + t.radius + 2.5:
                self._chase_t -= dt
                if self.goal is None or self._chase_t <= 0:
                    self._chase_t = 0.8
                    self.move_to(t.x, t.z, arrive=self.radius + t.radius + 1.5)
                self._follow_path(dt)
            elif self.goal is not None:
                self.halt()
        elif o.kind in ("gather", "return", "build"):
            if not self.match.economy.update_worker(self, o, dt):
                self._next_order()
        elif o.kind == "cast":
            if not self.match.abilities.update_cast(self, o, dt):
                self._next_order()
        else:
            self._next_order()

    def _idle(self, dt: float) -> None:
        if self.target is not None:
            ax, az = self.anchor
            if math.hypot(self.x - ax, self.z - az) > LEASH or not self._fight(dt, self.target):
                self.target = None
                self.move_to(ax, az, arrive=0.6)
            return
        if self.goal is not None:
            if self._follow_path(dt):
                self.halt()

    # ================================================================== visuals
    def sync_node(self) -> None:
        node = self.node
        if node is None:
            return
        if self.flying and self.alive:
            target_y = self.fly_height()
            self.y += (target_y - self.y) * 0.08
        elif self.alive:
            key = (self.x, self.z, self.yaw)
            if key == self._synced[:3]:
                return
            self.y = self.match.terrain.height(self.x, self.z)
        self._synced = (self.x, self.z, self.yaw, self.y)
        node.setPos(self.x, self.y, self.z)
        set_yaw(node, self.yaw)

    def animate(self, dt: float) -> None:
        moved = math.hypot(self.x - self._px, self.z - self._pz)
        self._px, self._pz = self.x, self.z
        inst = moved / dt if dt > 0 else 0.0
        self.cur_speed += (inst - self.cur_speed) * min(1.0, dt * 12.0)
        self.rig.update(dt, self.cur_speed if self.cur_speed > 0.4 else 0.0)
        if self.skin is not None:
            self.skin.update()

    def die(self) -> None:
        self.alive = False
        self.orders.clear()
        self.order = None
        self.target = None
        self.halt()
        self.rig.die()
        self.corpse_t = 0.0
