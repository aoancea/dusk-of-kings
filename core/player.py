"""A participant in a match: resources, supply, tech and upgrades."""
from __future__ import annotations

from collections import Counter
from typing import Any

from core import data
from settings import SUPPLY_LIMIT, START_GOLD, START_TIMBER


class Player:
    """Economy and tech state for one side (human or computer)."""

    def __init__(self, pid: int, faction: str, color: tuple[float, float, float], is_ai: bool,
                 name: str = "") -> None:
        self.id = pid
        self.team = pid
        self.faction = faction
        self.fdef: dict[str, Any] = data.factions()[faction]
        self.color = color
        self.is_ai = is_ai
        self.name = name or self.fdef["name"]
        self.gold = START_GOLD
        self.timber = START_TIMBER
        self.supply_used = 0
        self.supply_cap = 0
        self.upgrades: set[str] = set()
        self.researching: set[str] = set()
        self.completed: Counter[str] = Counter()   # finished buildings by type
        self.defeated = False
        self.gather_mult = 1.0          # AI difficulty bonus / handicap on gathered resources
        self._gather_frac = {"gold": 0.0, "timber": 0.0}
        self.stats = {"units_trained": 0, "units_lost": 0, "kills": 0, "buildings_built": 0,
                      "buildings_lost": 0, "gold_mined": 0, "timber_cut": 0, "gold_spent": 0, "timber_spent": 0}

    # ------------------------------------------------------------------ resources
    def can_afford(self, cost: dict[str, int]) -> bool:
        return self.gold >= cost.get("gold", 0) and self.timber >= cost.get("timber", 0)

    def spend(self, cost: dict[str, int]) -> bool:
        if not self.can_afford(cost):
            return False
        g, t = cost.get("gold", 0), cost.get("timber", 0)
        self.gold -= g
        self.timber -= t
        self.stats["gold_spent"] += g
        self.stats["timber_spent"] += t
        return True

    def refund(self, cost: dict[str, int], fraction: float = 1.0) -> None:
        g = int(cost.get("gold", 0) * fraction)
        t = int(cost.get("timber", 0) * fraction)
        self.gold += g
        self.timber += t
        self.stats["gold_spent"] -= g
        self.stats["timber_spent"] -= t

    def add(self, kind: str, amount: int) -> None:
        if self.gather_mult != 1.0:
            exact = amount * self.gather_mult + self._gather_frac[kind]
            amount = int(exact)
            self._gather_frac[kind] = exact - amount
        if kind == "gold":
            self.gold += amount
            self.stats["gold_mined"] += amount
        else:
            self.timber += amount
            self.stats["timber_cut"] += amount

    @property
    def supply_max(self) -> int:
        return min(self.supply_cap, SUPPLY_LIMIT)

    def has_supply(self, amount: int) -> bool:
        return self.supply_used + amount <= self.supply_max

    # ------------------------------------------------------------------ tech
    @property
    def tier(self) -> int:
        th2 = [k for k, v in data.buildings().items() if v.get("faction") == self.faction and v.get("upgrade_of")]
        return 2 if any(self.completed[k] > 0 for k in th2) else 1

    def owns(self, btype: str) -> bool:
        if self.completed[btype] > 0:
            return True
        # an upgraded town hall still counts as its base form
        for k, v in data.buildings().items():
            if v.get("upgrade_of") == btype and self.completed[k] > 0:
                return True
        return False

    def missing_requirements(self, defn: dict[str, Any]) -> list[str]:
        """Names of the buildings / tier still needed before ``defn`` (unit, building or upgrade) is allowed."""
        out = []
        bdefs = data.buildings()
        if defn.get("tier", 1) >= 2 and self.tier < 2:
            th = self.fdef["town_hall"]
            out.append(bdefs[bdefs[th]["upgrades_to"]]["name"])
        for req in defn.get("requires", []):
            if not self.owns(req):
                out.append(bdefs[req]["name"])
        up = defn.get("requires_upgrade")
        if up and up not in self.upgrades:
            out.append(data.upgrades()[up]["name"])
        return out

    # ------------------------------------------------------------------ upgrades
    def damage_bonus(self, udef: dict[str, Any]) -> int:
        bonus = 0
        att = udef.get("attack") or {}
        role = udef.get("role")
        for uid in self.upgrades:
            u = data.upgrades()[uid]
            eff = u.get("effects", {})
            if "damage" not in eff:
                continue
            if "attack_type" in u and att.get("type") != u["attack_type"]:
                continue
            if "roles" in u and role not in u["roles"]:
                continue
            bonus += eff["damage"]
        return bonus

    def armor_bonus(self, udef: dict[str, Any]) -> int:
        bonus = 0
        role = udef.get("role")
        for uid in self.upgrades:
            u = data.upgrades()[uid]
            eff = u.get("effects", {})
            if "armor" in eff and ("roles" not in u or role in u["roles"]):
                bonus += eff["armor"]
        return bonus
