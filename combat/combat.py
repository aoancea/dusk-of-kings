"""Damage model, attacks, splash damage and vectorised target acquisition."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
from panda3d.core import Vec3

from core import data
from core.events import events

if TYPE_CHECKING:
    from core.actor import Actor
    from core.match import Match

BUILDING_PENALTY = 7.0     # acquisition prefers units over buildings by this many world units
WORKER_PENALTY = 2.0


class CombatSystem:
    """Resolves attacks for units and towers."""

    def __init__(self, match: "Match") -> None:
        self.match = match
        cfg = data.combat()
        self.mult: dict[str, dict[str, float]] = cfg["multipliers"]
        self.dn: dict[str, float] = cfg["day_night"]
        self._acq_t = 0.0

    # ------------------------------------------------------------------ damage
    def damage_value(self, attacker: "Actor", target: "Actor", base: float | None = None,
                     attack_type: str | None = None) -> float:
        att = attacker.attack if getattr(attacker, "attack", None) else attacker.defn.get("attack", {})
        owner = attacker.owner
        if base is None:
            base = float(att.get("damage", 0))
            if owner is not None:
                base += owner.damage_bonus(attacker.defn)
        atype = attack_type or att.get("type", "normal")
        m = self.mult.get(atype, {}).get(target.armor_type, 1.0)
        dmg = base * m
        if owner is not None:
            night = self.match.is_night
            if owner.faction == "alliance" and not night:
                dmg *= 1.0 + self.dn.get("alliance_day_damage", 0.0)
            elif owner.faction == "host" and night:
                dmg *= 1.0 + self.dn.get("host_night_damage", 0.0)
        return max(1.0, dmg - target.armor)

    def apply(self, attacker: "Actor", target: "Actor", amount: float, kind: str = "blood") -> None:
        if not target.alive:
            return
        self.match.fx.hit(target, "debris" if target.is_building else kind)
        target.take_damage(amount, attacker)
        self.match.on_damaged(target, attacker)

    def strike(self, attacker: "Actor", target: "Actor") -> None:
        """Melee hit (applied immediately)."""
        dmg = self.damage_value(attacker, target)
        att = attacker.attack or {}
        if att.get("type") == "siege" and target.is_building:
            self.match.cam_shake(target, 0.15)
        events.emit("sound", name="hit", pos=(target.x, target.z))
        self.apply(attacker, target, dmg)

    def launch(self, attacker: "Actor", target: "Actor") -> None:
        """Fire the attacker's projectile at ``target``; damage happens on impact."""
        att = attacker.attack or attacker.defn.get("attack", {})
        kind = att.get("projectile", "arrow")
        splash = float(att.get("splash", 0))
        dmg_base = float(att.get("damage", 0)) + (attacker.owner.damage_bonus(attacker.defn) if attacker.owner else 0)
        atype = att.get("type", "normal")
        events.emit("sound", name="bow" if kind in ("arrow", "dark_arrow", "spear") else "throw", pos=(attacker.x, attacker.z))
        homing = splash <= 0
        point = None if homing else (target.x, target.y + 0.3, target.z)

        def on_hit(pos: Vec3, attacker=attacker, target=target) -> None:
            if splash > 0:
                self.splash(attacker, pos.x, pos.z, splash, dmg_base, atype, primary=target)
                self.match.fx.explosion(pos.x, self.match.terrain.height(pos.x, pos.z), pos.z, splash,
                                        "fire" if kind in ("fire_rock", "fireball") else "dust")
                events.emit("sound", name="explosion", pos=(pos.x, pos.z))
            elif target.alive:
                self.apply(attacker, target, self.damage_value(attacker, target, dmg_base, atype), "blood")

        self.match.fx.projectile(attacker, None if not homing else target, kind, on_hit, point)

    def splash(self, attacker: "Actor", x: float, z: float, radius: float, base: float, atype: str,
               primary: "Actor | None" = None, friendly_fire: bool = False) -> int:
        hits = 0
        for a in self.match.actors_near(x, z, radius + 3.0):
            if not a.alive or a.is_mine or a.flying:
                continue
            if a.team == attacker.team and not friendly_fire:
                continue
            d = math.hypot(a.x - x, a.z - z) - a.radius
            if d > radius:
                continue
            k = 1.0 if (a is primary or d <= radius * 0.4) else 0.5
            self.apply(attacker, a, self.damage_value(attacker, a, base * k, atype), "blood")
            hits += 1
        return hits

    # ------------------------------------------------------------------ acquisition
    def update(self, dt: float) -> None:
        self._acq_t -= dt
        if self._acq_t > 0:
            return
        self._acq_t = 0.25
        self.acquire()

    def acquire(self) -> None:
        m = self.match
        seekers = [u for u in m.units if u.alive and not u.hidden and u.wants_targets and self._needs_target(u)]
        towers = [b for b in m.buildings if b.alive and b.complete and b.attack is not None]
        if not seekers and not towers:
            return
        cands = [a for a in m.units if a.alive and not a.hidden] + [b for b in m.buildings if b.alive]
        if not cands:
            return
        cx = np.fromiter((a.x for a in cands), np.float32, len(cands))
        cz = np.fromiter((a.z for a in cands), np.float32, len(cands))
        cr = np.fromiter((a.radius for a in cands), np.float32, len(cands))
        cteam = np.fromiter((a.team for a in cands), np.int16, len(cands))
        cair = np.fromiter((a.flying for a in cands), bool, len(cands))
        cpen = np.fromiter((BUILDING_PENALTY if a.is_building else (WORKER_PENALTY if getattr(a, "is_worker", False) else 0.0)
                            for a in cands), np.float32, len(cands))
        cells = np.fromiter((m.grid.cell_of(a.x, a.z) for a in cands), np.int32, len(cands))
        vis_cache: dict[int, np.ndarray] = {}

        def visible_for(team: int) -> np.ndarray:
            v = vis_cache.get(team)
            if v is None:
                if not m.fog.enabled:
                    v = np.ones(len(cands), bool)
                else:
                    vb = np.frombuffer(bytes(m.fog.vis_bytes[team]), np.uint8)
                    v = vb[cells] > 0
                    # remembered (explored) buildings can be attacked when spotted again; units need vision
                vis_cache[team] = v
            return v

        for group in (seekers, towers):
            if not group:
                continue
            sx = np.fromiter((u.x for u in group), np.float32, len(group))
            sz = np.fromiter((u.z for u in group), np.float32, len(group))
            dist = np.sqrt((sx[:, None] - cx[None, :]) ** 2 + (sz[:, None] - cz[None, :]) ** 2) - cr[None, :]
            for k, u in enumerate(group):
                targets = (u.attack or {}).get("targets", ["ground"])
                ok = (cteam != u.team) & (cteam >= 0) & visible_for(u.team)
                if "air" not in targets:
                    ok &= ~cair
                if "ground" not in targets:
                    ok &= cair
                rng = u.acquire_range if u.is_unit else u.attack_range
                if u.is_unit and u.order is not None and u.order.kind == "hold":
                    rng = u.attack_range + 0.5
                d = dist[k] - u.radius
                ok &= d <= rng
                mn = float((u.attack or {}).get("min_range", 0))
                if mn:
                    ok &= d >= mn
                if not ok.any():
                    continue
                score = np.where(ok, d + cpen, np.inf)
                j = int(np.argmin(score))
                u.target = cands[j]

    def _needs_target(self, u) -> bool:
        t = u.target
        if t is None or not t.alive:
            return True
        # re-evaluate while the current target is out of reach (chasing): something closer may be in range
        return not u.in_attack_range(t)
