"""Caster abilities: Heal and Slow (Loremaster), Fireball and Dark Frenzy (Pyre Witch)."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from core import data
from core.actor import Order
from core.events import events
from core.util import yaw_to

if TYPE_CHECKING:
    from core.match import Match
    from units.unit import Unit


class Abilities:
    """Validates, executes and auto-casts unit abilities."""

    def __init__(self, match: "Match") -> None:
        self.match = match
        self._auto_t = 0.0

    def defn(self, aid: str) -> dict[str, Any]:
        return data.abilities()[aid]

    def ready(self, u: "Unit", aid: str) -> bool:
        a = self.defn(aid)
        return u.alive and aid in u.abilities and u.mana >= a["mana"] and aid not in u.ability_cd

    # ------------------------------------------------------------------ commands
    def order_cast(self, units: list["Unit"], aid: str, target: Any = None, point: tuple[float, float] | None = None,
                   queue: bool = False) -> str | None:
        """Pick the best caster in ``units`` and order the cast. Returns an error or None."""
        a = self.defn(aid)
        casters = [u for u in units if u.alive and aid in u.abilities]
        if not casters:
            return "No caster selected"
        ready = [u for u in casters if self.ready(u, aid)]
        if not ready:
            if all(u.mana < a["mana"] for u in casters):
                return "Not enough mana"
            return "Ability is not ready"
        tgt_kind = a["target"]
        if tgt_kind == "ally_unit" and (target is None or not target.is_unit or target.team != casters[0].team):
            return "Must target a friendly unit"
        if tgt_kind == "enemy_unit" and (target is None or not target.is_unit or target.team == casters[0].team or target.team < 0):
            return "Must target an enemy unit"
        if tgt_kind == "point" and point is None:
            if target is not None:
                point = (target.x, target.z)
            else:
                return "Must target a location"
        ref = target if target is not None else None
        px, pz = point if point else ((ref.x, ref.z) if ref else (casters[0].x, casters[0].z))
        caster = min(ready, key=lambda u: math.hypot(u.x - px, u.z - pz) - u.mana * 0.01)
        caster.command(Order("cast", px, pz, target=target, data={"ability": aid}), queue)
        return None

    # ------------------------------------------------------------------ execution
    def update_cast(self, u: "Unit", o: Order, dt: float) -> bool:
        aid = o.data["ability"]
        a = self.defn(aid)
        if not self.ready(u, aid):
            return False
        tgt = o.target
        if a["target"] in ("ally_unit", "enemy_unit") and (tgt is None or not tgt.alive):
            return False
        if a["target"] == "self":
            self.execute(u, aid, None, (u.x, u.z))
            return False
        tx, tz = (tgt.x, tgt.z) if tgt is not None else (o.x, o.z)
        rng = float(a.get("range", 8))
        d = math.hypot(tx - u.x, tz - u.z) - (tgt.radius if tgt is not None else 0.0)
        if d > rng:
            if u.goal is None or math.hypot(u.goal[0] - tx, u.goal[1] - tz) > 2.0:
                u.move_to(tx, tz, arrive=rng * 0.8)
            u._follow_path(dt)
            return True
        u.halt()
        if not u._turn_towards(yaw_to(tx - u.x, tz - u.z), dt):
            return True
        self.execute(u, aid, tgt, (tx, tz))
        return False

    def execute(self, u: "Unit", aid: str, tgt: Any, point: tuple[float, float]) -> None:
        a = self.defn(aid)
        m = self.match
        u.mana -= a["mana"]
        u.ability_cd[aid] = float(a.get("cooldown", 1.0))
        u.rig.play("cast", 0.5)
        events.emit("ability_used", unit=u, ability=aid)
        if aid == "heal":
            tgt.heal(float(a["amount"]))
            m.fx.heal(tgt)
            events.emit("sound", name="heal", pos=(tgt.x, tgt.z))
        elif aid == "slow":
            tgt.buffs["slow"] = float(a["duration"])
            m.fx.burst((tgt.x, tgt.y + 1.0, tgt.z), "frost", 16, 2.5, 0.8, 0.16, gravity=-1)
            m.fx.ring(tgt.x, tgt.y, tgt.z, 1.6, (0.6, 0.85, 1.0, 0.9), 0.5)
            events.emit("sound", name="cast", pos=(tgt.x, tgt.z))
        elif aid == "fireball":
            px, pz = point
            py = m.terrain.height(px, pz)
            radius = float(a["radius"])
            dmg = float(a["damage"])

            dtype = a.get("damage_type", "magic")

            def boom(pos, u=u) -> None:
                m.combat.splash(u, pos.x, pos.z, radius, dmg, dtype)
                m.fx.explosion(pos.x, m.terrain.height(pos.x, pos.z), pos.z, radius, "fire")
                events.emit("sound", name="explosion", pos=(pos.x, pos.z))

            m.fx.projectile(u, None, "fireball", boom, (px, py + 0.4, pz))
            events.emit("sound", name="fire", pos=(u.x, u.z))
        elif aid == "dark_frenzy":
            r = float(a["radius"])
            for ally in m.units:
                if ally.alive and ally.team == u.team and ally.attack is not None and math.hypot(ally.x - u.x, ally.z - u.z) <= r:
                    ally.buffs["frenzy"] = float(a["duration"])
                    if ally.on_screen:
                        m.fx.burst((ally.x, ally.y + 1.2, ally.z), "fire", 5, 2.0, 0.5, 0.12, gravity=-3)
            m.fx.ring(u.x, u.y, u.z, r, (1.0, 0.3, 0.15, 0.9), 0.6)
            events.emit("sound", name="roar", pos=(u.x, u.z))

    # ------------------------------------------------------------------ autocast
    def update(self, dt: float) -> None:
        self._auto_t -= dt
        if self._auto_t > 0:
            return
        self._auto_t = 0.4
        m = self.match
        for u in m.units:
            if not u.alive or not u.abilities or u.hidden:
                continue
            if u.order is not None and u.order.kind in ("move", "cast"):
                continue
            if "heal" in u.abilities and "heal" in u.autocast and self.ready(u, "heal"):
                rng = float(self.defn("heal")["range"]) + 2.0
                best, worst = None, 0.85
                for ally in m.units:
                    if ally.alive and ally.team == u.team and not ally.hidden and ally.max_hp - ally.hp >= 25:
                        if ally.hp_frac < worst and math.hypot(ally.x - u.x, ally.z - u.z) <= rng:
                            best, worst = ally, ally.hp_frac
                if best is not None:
                    self.execute(u, "heal", best, (best.x, best.z))
                    continue
            if u.owner.is_ai:
                self._ai_cast(u)

    def _ai_cast(self, u: "Unit") -> None:
        """Simple battlefield casting for computer-controlled casters."""
        m = self.match
        enemies = [e for e in m.units if e.alive and e.team != u.team and e.team >= 0 and not e.hidden
                   and math.hypot(e.x - u.x, e.z - u.z) < 14 and m.is_visible_to(e, u.team)]
        if not enemies:
            return
        if "fireball" in u.abilities and self.ready(u, "fireball"):
            best, score = None, 2
            for e in enemies:
                n = sum(1 for f in enemies if math.hypot(f.x - e.x, f.z - e.z) < 3.5)
                if n > score:
                    best, score = e, n
            if best is not None:
                self.execute(u, "fireball", None, (best.x, best.z))
                return
        if "dark_frenzy" in u.abilities and self.ready(u, "dark_frenzy"):
            allies = sum(1 for f in m.units if f.alive and f.team == u.team and f.attack and math.hypot(f.x - u.x, f.z - u.z) < 7)
            if allies >= 4 and len(enemies) >= 3:
                self.execute(u, "dark_frenzy", None, (u.x, u.z))
                return
        if "slow" in u.abilities and self.ready(u, "slow"):
            big = [e for e in enemies if e.supply >= 2 and "slow" not in e.buffs and math.hypot(e.x - u.x, e.z - u.z) < 12]
            if big:
                self.execute(u, "slow", max(big, key=lambda e: e.hp), (0, 0))
