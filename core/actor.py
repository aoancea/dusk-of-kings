"""Common base for everything that lives on the battlefield (units, buildings, gold mines)."""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from settings import CELL

if TYPE_CHECKING:
    from core.match import Match
    from core.player import Player

_ids = itertools.count(1)


@dataclass(eq=False)
class Order:
    """A queued command. ``kind`` is one of move, attack_move, attack, follow, patrol, hold, gather,
    return, build, cast."""

    kind: str
    x: float = 0.0
    z: float = 0.0
    target: Any = None
    data: dict[str, Any] = field(default_factory=dict)


class Actor:
    """Anything with a position, an owner, hit points and a scene node."""

    is_unit = False
    is_building = False
    is_mine = False
    flying = False

    def __init__(self, match: "Match", owner: "Player | None", type_id: str, defn: dict[str, Any],
                 x: float, z: float) -> None:
        self.id = next(_ids)
        self.match = match
        self.owner = owner
        self.team = owner.team if owner is not None else -1
        self.type_id = type_id
        self.defn = defn
        self.name: str = defn.get("name", type_id)
        self.x = x
        self.z = z
        self.y = match.terrain.height(x, z)
        self.yaw = 0.0
        self.max_hp = float(defn.get("hp", 100))
        self.hp = self.max_hp
        self.alive = True
        self.radius = float(defn.get("radius", 0.5))
        self.sight = float(defn.get("sight", 10))
        self.base_armor = float(defn.get("armor", 0))
        self.armor_type: str = defn.get("armor_type", "light")
        self.height = 2.0
        self.selected = False
        self.visible = True          # visible to the local (human) player this frame
        self.node = None
        self.last_attacker: Actor | None = None
        self.last_hit_time = -99.0

    # ------------------------------------------------------------------ helpers
    @property
    def armor(self) -> float:
        return self.base_armor

    def dist_to(self, other: "Actor") -> float:
        return math.hypot(self.x - other.x, self.z - other.z)

    def edge_dist(self, other: "Actor") -> float:
        """Gap between the two actors' edges (buildings and mines are squares, units are circles)."""
        if other.is_building or other.is_mine:
            return max(0.0, other.box_dist(self.x, self.z) - (0.0 if (self.is_building or self.is_mine) else self.radius))
        if self.is_building or self.is_mine:
            return max(0.0, self.box_dist(other.x, other.z) - other.radius)
        return max(0.0, self.dist_to(other) - self.radius - other.radius)

    def box_dist(self, x: float, z: float) -> float:
        """Distance from a point to this actor's square footprint (0 inside)."""
        half = getattr(self, "footprint", 1) * CELL * 0.5
        dx = max(abs(x - self.x) - half, 0.0)
        dz = max(abs(z - self.z) - half, 0.0)
        return math.hypot(dx, dz)

    def is_enemy(self, other: "Actor") -> bool:
        return self.team >= 0 and other.team >= 0 and self.team != other.team

    @property
    def hp_frac(self) -> float:
        return self.hp / self.max_hp if self.max_hp > 0 else 0.0

    def take_damage(self, amount: float, attacker: "Actor | None") -> bool:
        """Apply damage; returns True if this killed the actor."""
        if not self.alive:
            return False
        self.hp -= amount
        self.last_attacker = attacker
        self.last_hit_time = self.match.time
        if self.hp <= 0:
            self.hp = 0
            self.match.kill(self, attacker)
            return True
        return False

    def heal(self, amount: float) -> float:
        before = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp - before

    def destroy(self) -> None:
        if self.node is not None:
            self.node.removeNode()
            self.node = None
