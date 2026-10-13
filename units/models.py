"""Unit models for the RTS: lightweight rigs with few parts so hundreds of units stay cheap to draw.

Every rig follows :class:`core.rig.Rig` (``update(dt, speed)``, ``play(action)``, ``die()``).
``build_unit_rig(spec, team_color)`` turns a ``model`` entry from units.json into a rig.
"""
from __future__ import annotations

import math
from typing import Any

from panda3d.core import NodePath

from core.meshgen import MeshBuilder, shade
from core.rig import Rig, copy_part, swing
from core.util import set_rot
from units.humanoid import (METAL, WOOD, DARK_WOOD, HumanoidRig, _arm, _head, _key, _leg, _torso,
                            offhand_mesh, resolve_look, weapon_mesh)

IVORY = (0.92, 0.87, 0.72, 1.0)
DARK = (0.08, 0.06, 0.05, 1.0)
Color = tuple[float, float, float, float]


def _c(v: Any, a: float = 1.0) -> Color:
    return (float(v[0]), float(v[1]), float(v[2]), a)


def resolve_team(obj: Any, color: tuple[float, float, float]) -> Any:
    """Replace every ``"team"`` placeholder in a (nested) model spec with the team colour."""
    if isinstance(obj, str) and obj == "team":
        return list(color)
    if isinstance(obj, dict):
        return {k: resolve_team(v, color) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_team(v, color) for v in obj]
    return obj


def _ck(col: Any) -> tuple:
    return tuple(round(float(c), 3) for c in col) if col is not None else ()


# ============================================================================ humanoid
class UnitHumanoidRig(HumanoidRig):
    """Humanoid with head merged into the torso and weapons merged into the arms (5 draw calls)."""

    def rebuild(self) -> None:
        L = self.look
        s = L["height"]
        for pivot in (self.torso, self.neck, self.arm_l, self.arm_r, self.leg_l, self.leg_r, self.hand_l, self.hand_r):
            for child in pivot.getChildren():
                if child.getName().startswith("mesh"):
                    child.removeNode()
        neck = (0, 0.86 * s, 0.03 * s)
        hand = (0, -0.86 * s * L["arm_len"], 0.02)
        wk = L["weapon"]
        wscale = s ** 0.5

        def body() -> MeshBuilder:
            mb = _torso(L)
            mb.merge(_head(L), pos=neck, rot=(-L["hunch"] * 0.8, 0, 0))
            return mb

        def arm_r() -> MeshBuilder:
            mb = _arm(L)
            if wk and wk != "bow":
                mb.merge(weapon_mesh(wk, L["weapon_color"]), pos=hand, scale=wscale)
            return mb

        def arm_l() -> MeshBuilder:
            mb = _arm(L)
            if wk == "bow":
                mb.merge(weapon_mesh(wk, L["weapon_color"]), pos=hand, scale=wscale)
            if L.get("offhand"):
                mb.merge(offhand_mesh(L["offhand"], L.get("offhand_color")), pos=hand)
            return mb

        copy_part(_key(L, "u_body"), body, self.torso).setName("mesh_body")
        copy_part(_key(L, "u_arm_r"), arm_r, self.arm_r).setName("mesh_arm")
        copy_part(_key(L, "u_arm_l"), arm_l, self.arm_l).setName("mesh_arm")
        copy_part(_key(L, "leg"), lambda: _leg(L), self.leg_l).setName("mesh_leg")
        copy_part(_key(L, "leg"), lambda: _leg(L), self.leg_r).setName("mesh_leg")


# ============================================================================ riders
class RiderRig(Rig):
    """A mount (horse or hound) carrying a humanoid rider."""

    def __init__(self, mount: str, mount_color: Any, barding: Any, look: dict[str, Any]) -> None:
        super().__init__()
        self.mount = mount
        self.mcol = _c(mount_color)
        self.barding = _c(barding) if barding is not None else None
        hound = mount == "hound"
        self.hip = 1.05 if hound else 1.3
        self.blen = 1.7 if hound else 2.0
        self.leg_len = 0.95 if hound else 1.25
        self.torso = self.body.attachNewNode("mount")
        self.torso.setY(self.hip)
        key = ("mount", mount, _ck(self.mcol), _ck(self.barding) if self.barding else ())
        copy_part(key + ("body",), self._mount_body, self.torso)
        self.legs: list[NodePath] = []
        for sx, sz in ((-1, 1), (1, 1), (-1, -1), (1, -1)):
            leg = self.torso.attachNewNode("leg")
            leg.setPos(sx * 0.26, -0.15, sz * self.blen * 0.36)
            copy_part(key + ("leg",), self._mount_leg, leg)
            self.legs.append(leg)
        # rider
        L = resolve_look(look)
        self.look = L
        s = L["height"]
        self.rider = self.torso.attachNewNode("rider")
        self.rider.setPos(0, 0.25, -0.1)
        rider_scale = 0.9 if not hound else 0.95
        self.rider.setScale(rider_scale)

        def rider_body() -> MeshBuilder:
            mb = _torso(L)
            mb.merge(_head(L), pos=(0, 0.86 * s, 0.03 * s))
            leg = _leg(L)
            for sx in (-1, 1):
                mb.merge(leg, pos=(sx * 0.28 * s, 0.05, 0.12), rot=(-70, 0, sx * 18))
            return mb

        copy_part(_key(L, "rider_body"), rider_body, self.rider)
        self.arm_r = self.rider.attachNewNode("arm_r")
        self.arm_r.setPos(0.44 * L["bulk"] * s, 0.72 * s, 0)
        self.arm_l = self.rider.attachNewNode("arm_l")
        self.arm_l.setPos(-0.44 * L["bulk"] * s, 0.72 * s, 0)
        hand = (0, -0.86 * s * L["arm_len"], 0.02)
        wk = L["weapon"]

        def arm_r() -> MeshBuilder:
            mb = _arm(L)
            if wk:
                mb.merge(weapon_mesh(wk, L["weapon_color"]), pos=hand, scale=s ** 0.5)
            return mb

        copy_part(_key(L, "rider_arm_r"), arm_r, self.arm_r)
        copy_part(_key(L, "arm"), lambda: _arm(L), self.arm_l)
        self.height = self.hip + 0.25 + 2.0 * s * rider_scale
        self.radius = 0.9

    def _mount_body(self) -> MeshBuilder:
        mb = MeshBuilder()
        c = self.mcol
        L = self.blen
        if self.mount == "horse":
            mb.box((0, 0.0, 0), (0.62, 0.62, L), c, taper=0.95)
            mb.beam((0, 0.15, L * 0.42), (0, 0.85, L * 0.62), (0.3, 0.42), c)
            mb.box((0, 0.95, L * 0.72), (0.26, 0.3, 0.62), c, rot=(28, 0, 0))
            mb.box((0, 0.88, L * 0.86), (0.22, 0.2, 0.2), shade(c, 0.75), rot=(28, 0, 0))
            for sx in (-1, 1):
                mb.box((sx * 0.08, 1.14, L * 0.62), (0.05, 0.14, 0.06), shade(c, 0.85))
            mb.box((0, 0.62, L * 0.55), (0.06, 0.4, 0.5), shade(c, 0.35), rot=(30, 0, 0))
            mb.beam((0, 0.15, -L * 0.48), (0, -0.55, -L * 0.62), 0.08, shade(c, 0.35), segments=4, radius_b=0.12)
        else:  # hound
            mb.box((0, 0.05, 0.1), (0.7, 0.72, L), c, taper=0.85, rot=(-8, 0, 0))
            mb.box((0, 0.5, 0.25), (0.2, 0.25, 1.0), shade(c, 0.6), rot=(-10, 0, 0))
            mb.box((0, 0.35, L * 0.62), (0.56, 0.52, 0.58), c)
            mb.box((0, 0.22, L * 0.86), (0.36, 0.3, 0.42), shade(c, 0.85))
            for sx in (-1, 1):
                mb.cone((sx * 0.2, 0.62, L * 0.55), 0.09, 0.3, shade(c, 0.6), segments=4)
                mb.box((sx * 0.14, 0.45, L * 0.88), (0.07, 0.05, 0.04), (1.0, 0.45, 0.1, 1))
                mb.cone((sx * 0.1, 0.08, L * 1.02), 0.04, 0.14, IVORY, rot=(160, 0, 0), segments=3)
            mb.beam((0, 0.2, -L * 0.45), (0, 0.4, -L * 0.8), 0.07, shade(c, 0.7), segments=3)
        if self.barding is not None:
            b = self.barding
            mb.box((0, 0.12, -0.05), (0.72, 0.5, L * 0.62), b, taper=1.0)
            mb.box((0, 0.38, -0.05), (0.5, 0.06, 0.6), shade(b, 0.6))
            mb.box((0, 0.42, -0.05), (0.3, 0.08, 0.45), (0.3, 0.2, 0.12, 1))
        return mb

    def _mount_leg(self) -> MeshBuilder:
        mb = MeshBuilder()
        L = self.leg_len
        c = shade(self.mcol, 0.85)
        w = 0.17 if self.mount == "horse" else 0.2
        mb.box((0, -L * 0.45, 0), (w, L * 0.9, w * 1.1), c)
        mb.box((0, -L * 0.96, 0.03), (w * 1.15, 0.12, w * 1.4), shade(c, 0.5))
        return mb

    def _pose(self, dt: float, speed: float, grounded: bool, swimming: bool) -> None:
        mbl = self.move_blend
        ph = self.phase * 1.25
        amp = 42 * mbl
        for i, leg in enumerate(self.legs):
            off = (0.0, 0.6, math.pi, math.pi + 0.6)[i]
            set_rot(leg, swing(ph + off, amp), 0, 0)
        bob = abs(math.sin(ph)) * 0.1 * mbl + math.sin(self.idle_t * 2.0) * 0.01
        self.torso.setY(self.hip + bob)
        set_rot(self.torso, math.sin(ph) * 3 * mbl, 0, 0)
        ra = (-30.0, 0.0, 10.0)
        la = (-35.0, 0.0, -10.0)
        act, t = self.action, self.action_progress()
        if act == "attack":
            if t < 0.4:
                k = t / 0.4
                ra = (-30 - 120 * k, 0.0, 10 + 10 * k)
            else:
                k = (t - 0.4) / 0.6
                ra = (-150 + 150 * min(k * 1.6, 1), 0.0, 20.0)
        elif act == "hit":
            set_rot(self.rider, -10 * math.sin(t * math.pi), 0, 0)
        set_rot(self.arm_r, *ra)
        set_rot(self.arm_l, *la)

    def _pose_death(self, t: float) -> None:
        e = 1 - (1 - t) ** 3
        set_rot(self.body, 0, 0, 85 * e)
        self.body.setY(0.3 * e)
        set_rot(self.rider, -40 * e, 0, -30 * e)


# ============================================================================ ogre
class OgreRig(Rig):
    """A towering stone ogre with a huge club."""

    def __init__(self, skin: Any, accent: Any) -> None:
        super().__init__()
        self.skin = _c(skin)
        self.acc = _c(accent) if accent is not None else (0.4, 0.1, 0.1, 1)
        key = ("ogre", _ck(self.skin), _ck(self.acc))
        self.hips = self.body.attachNewNode("hips")
        self.hips.setY(1.25)
        self.torso = self.hips.attachNewNode("torso")
        copy_part(key + ("torso",), self._torso, self.torso)
        self.arms: list[NodePath] = []
        for side in (-1, 1):
            arm = self.torso.attachNewNode("arm")
            arm.setPos(side * 0.95, 1.75, 0.1)
            copy_part(key + ("arm", side), lambda side=side: self._arm(side), arm)
            self.arms.append(arm)
        self.legs: list[NodePath] = []
        for side in (-1, 1):
            leg = self.hips.attachNewNode("leg")
            leg.setPos(side * 0.45, 0, 0)
            copy_part(key + ("leg",), self._leg, leg)
            self.legs.append(leg)
        self.height = 3.6
        self.radius = 1.2

    def _torso(self) -> MeshBuilder:
        mb = MeshBuilder()
        s = self.skin
        mb.box((0, 0.2, 0), (1.15, 0.6, 0.85), self.acc)
        mb.box((0, 1.1, 0.05), (1.75, 1.4, 1.2), s, taper=1.2)
        mb.box((0, 1.0, 0.62), (1.3, 0.9, 0.15), shade(s, 1.12))
        for i, x in enumerate((-0.5, 0.0, 0.5)):
            mb.sphere((x, 1.6, -0.55), (0.42, 0.32, 0.3), shade(s, 0.8), detail=0, noise=0.25, seed=i)
        mb.box((0, 2.05, 0.35), (0.62, 0.55, 0.6), s)
        mb.box((0, 1.92, 0.68), (0.5, 0.2, 0.12), shade(s, 0.75))
        for sx in (-1, 1):
            mb.box((sx * 0.15, 2.15, 0.66), (0.12, 0.06, 0.04), (1.0, 0.6, 0.15, 1))
            mb.cone((sx * 0.2, 1.88, 0.72), 0.05, 0.2, IVORY, rot=(-20, 0, 0), segments=3)
        mb.box((0, 0.55, 0.45), (0.5, 0.5, 0.08), self.acc)
        return mb

    def _arm(self, side: int) -> MeshBuilder:
        mb = MeshBuilder()
        s = self.skin
        mb.sphere((side * 0.05, 0.05, 0), (0.42, 0.36, 0.42), shade(s, 0.85), detail=0, noise=0.15, seed=side + 3)
        mb.beam((0, 0, 0), (side * 0.2, -0.95, 0.1), 0.3, s, segments=6)
        mb.beam((side * 0.2, -0.95, 0.1), (side * 0.25, -1.75, 0.3), 0.27, shade(s, 0.95), segments=6)
        mb.sphere((side * 0.25, -1.95, 0.35), (0.34, 0.3, 0.34), shade(s, 0.85), detail=0)
        if side > 0:
            mb.beam((side * 0.25, -1.95, 0.0), (side * 0.25, -1.9, 1.9), 0.12, DARK_WOOD, segments=5, radius_b=0.3)
            for k in range(4):
                mb.cone((side * 0.25 + (0.2 if k % 2 else -0.2), -1.9, 1.3 + k * 0.15), 0.06, 0.25,
                        (0.5, 0.5, 0.52, 1), rot=(0, 0, 90 if k % 2 else -90), segments=3)
        return mb

    def _leg(self) -> MeshBuilder:
        mb = MeshBuilder()
        mb.box((0, -0.5, 0), (0.55, 1.05, 0.6), shade(self.skin, 0.9))
        mb.box((0, -1.15, 0.12), (0.62, 0.22, 0.85), shade(self.skin, 0.7))
        return mb

    def _pose(self, dt: float, speed: float, grounded: bool, swimming: bool) -> None:
        ph = self.phase * 0.8
        amp = 24 * self.move_blend
        set_rot(self.legs[0], swing(ph, amp), 0, 0)
        set_rot(self.legs[1], swing(ph + math.pi, amp), 0, 0)
        al = [swing(ph + math.pi, amp * 0.6), 0, -10]
        ar = [swing(ph, amp * 0.6) - 15, 0, 10]
        tx = 12 + math.sin(self.idle_t * 1.3) * 2
        act, t = self.action, self.action_progress()
        if act == "attack":
            if t < 0.5:
                k = t / 0.5
                ar = [-15 - 140 * k, 0, 15]
                tx = 12 - 12 * k
            else:
                k = min((t - 0.5) / 0.25, 1.0)
                ar = [-155 + 175 * k, 0, 15]
                tx = 25 * k
        elif act == "hit":
            tx -= 8 * math.sin(t * math.pi)
        set_rot(self.arms[0], *al)
        set_rot(self.arms[1], *ar)
        set_rot(self.torso, tx, 0, 0)
        self.hips.setY(1.25 + abs(math.sin(ph)) * 0.08 * self.move_blend)

    def _pose_death(self, t: float) -> None:
        e = 1 - (1 - t) ** 3
        set_rot(self.body, -82 * e, 0, 8 * e)
        self.body.setY(0.25 * e)


# ============================================================================ siege
class SiegeRig(Rig):
    """Trebuchet or catapult on wheels; the throwing arm animates when firing."""

    def __init__(self, style: str, team: Any) -> None:
        super().__init__()
        self.style = style
        self.team = _c(team)
        key = ("siege", style, _ck(self.team))
        self.frame = self.body.attachNewNode("frame")
        copy_part(key + ("frame",), self._frame, self.frame)
        self.arm = self.frame.attachNewNode("arm")
        self.arm.setPos(0, 2.0 if style == "trebuchet" else 1.0, -0.2)
        copy_part(key + ("arm",), self._arm, self.arm)
        self.height = 3.6 if style == "trebuchet" else 2.4
        self.radius = 1.2
        self.wheel_t = 0.0

    def _frame(self) -> MeshBuilder:
        mb = MeshBuilder()
        wood = (0.5, 0.36, 0.22, 1) if self.style == "trebuchet" else (0.3, 0.22, 0.17, 1)
        dark = shade(wood, 0.65)
        mb.box((0, 0.55, 0), (1.5, 0.25, 2.6), wood)
        for sx in (-1, 1):
            for sz in (-1, 1):
                mb.cylinder((sx * 0.85, 0.42, sz * 0.9), 0.42, 0.14, dark, segments=8, rot=(0, 0, 90))
                mb.box((sx * 0.92, 0.42, sz * 0.9), (0.06, 0.12, 0.12), METAL)
        if self.style == "trebuchet":
            for sx in (-1, 1):
                mb.beam((sx * 0.6, 0.65, -0.9), (sx * 0.35, 2.1, -0.2), 0.16, wood)
                mb.beam((sx * 0.6, 0.65, 0.6), (sx * 0.35, 2.1, -0.2), 0.16, wood)
            mb.box((0, 2.1, -0.2), (0.9, 0.16, 0.16), dark)
            mb.box((0, 0.75, 1.2), (1.2, 0.2, 0.15), self.team)
            mb.box((0.7, 1.0, -1.1), (0.08, 0.9, 0.5), self.team)
        else:
            mb.box((0, 0.85, -0.4), (1.1, 0.35, 0.4), dark)
            for sx in (-1, 1):
                mb.beam((sx * 0.55, 0.65, -0.3), (sx * 0.45, 1.3, -0.1), 0.15, wood)
                mb.cone((sx * 0.75, 0.75, 1.3), 0.08, 0.5, (0.85, 0.82, 0.75, 1), rot=(70, 0, 0), segments=3)
            mb.box((0, 1.3, -0.1), (1.0, 0.14, 0.14), dark)
            mb.box((0, 0.72, 1.32), (1.3, 0.25, 0.08), self.team)
        return mb

    def _arm(self) -> MeshBuilder:
        mb = MeshBuilder()
        wood = (0.45, 0.32, 0.2, 1) if self.style == "trebuchet" else (0.32, 0.24, 0.18, 1)
        if self.style == "trebuchet":
            mb.beam((0, 0, 1.0), (0, 0, -2.6), 0.13, wood)
            mb.box((0, -0.35, 1.05), (0.6, 0.6, 0.6), (0.4, 0.4, 0.42, 1))
            mb.beam((0, 0, -2.6), (0, -0.6, -2.7), 0.03, (0.8, 0.75, 0.6, 1))
        else:
            mb.beam((0, 0, 0), (0, 0, 1.7), 0.12, wood)
            mb.box((0, 0.1, 1.75), (0.5, 0.2, 0.5), shade(wood, 0.8))
            mb.sphere((0, 0.32, 1.75), 0.2, (1.0, 0.45, 0.1, 1), detail=0)
        return mb

    def _pose(self, dt: float, speed: float, grounded: bool, swimming: bool) -> None:
        act, t = self.action, self.action_progress()
        rest = 35.0 if self.style == "trebuchet" else -20.0
        a = rest
        if act in ("attack", "shoot"):
            if self.style == "trebuchet":
                a = rest - 120 * math.sin(min(t * 2.2, 1.0) * math.pi * 0.5) if t < 0.6 else rest - 120 * (1 - (t - 0.6) / 0.4)
            else:
                a = rest + 95 * math.sin(min(t * 2.5, 1.0) * math.pi * 0.5) if t < 0.5 else rest + 95 * (1 - (t - 0.5) / 0.5)
        set_rot(self.arm, a, 0, 0)
        self.frame.setY(abs(math.sin(self.phase * 2.0)) * 0.04 * self.move_blend)

    def _pose_death(self, t: float) -> None:
        e = 1 - (1 - t) ** 3
        set_rot(self.body, 0, 0, 25 * e)
        self.body.setY(-0.4 * e)


# ============================================================================ flyers
class FlyerRig(Rig):
    """Skyhawk (with rider) or carrion drake: a body and two flapping wings."""

    def __init__(self, style: str, color: Any, accent: Any) -> None:
        super().__init__()
        self.style = style
        self.col = _c(color)
        self.acc = _c(accent) if accent is not None else shade(self.col, 0.6)
        key = ("flyer", style, _ck(self.col), _ck(self.acc))
        self.torso = self.body.attachNewNode("torso")
        copy_part(key + ("body",), self._body, self.torso)
        self.wings: list[NodePath] = []
        for side in (-1, 1):
            w = self.torso.attachNewNode("wing")
            w.setPos(side * 0.35, 0.25, 0.25)
            copy_part(key + ("wing", side), lambda side=side: self._wing(side), w)
            self.wings.append(w)
        self.height = 1.6
        self.radius = 1.2

    def _body(self) -> MeshBuilder:
        mb = MeshBuilder()
        c, a = self.col, self.acc
        if self.style == "hawk":
            mb.sphere((0, 0, 0), (0.48, 0.45, 0.95), c, detail=1)
            mb.sphere((0, 0.25, 0.95), (0.3, 0.3, 0.34), (0.92, 0.9, 0.85, 1), detail=1)
            mb.cone((0, 0.2, 1.22), 0.06, 0.26, (0.85, 0.6, 0.2, 1), rot=(100, 0, 0), segments=4)
            for sx in (-1, 1):
                mb.box((sx * 0.16, 0.32, 1.1), (0.05, 0.05, 0.04), DARK)
            mb.quad((-0.35, 0.05, -0.8), (0.35, 0.05, -0.8), (0.5, 0.1, -1.6), (-0.5, 0.1, -1.6), shade(c, 0.8),
                    facing=(0, 1, 0), double=True)
            # rider
            mb.box((0, 0.62, 0.1), (0.38, 0.5, 0.3), a)
            mb.box((0, 0.98, 0.12), (0.24, 0.24, 0.24), (0.87, 0.69, 0.56, 1))
            mb.box((0, 1.12, 0.1), (0.28, 0.1, 0.28), (0.65, 0.65, 0.7, 1))
            mb.beam((0.25, 0.6, 0.0), (0.3, 1.0, 1.1), 0.03, WOOD)
            mb.box((0, 0.42, 0.1), (0.62, 0.08, 0.5), a)
        else:
            mb.sphere((0, 0, 0), (0.5, 0.45, 1.0), c, detail=1)
            mb.beam((0, 0.15, 0.7), (0, 0.6, 1.5), (0.26, 0.3), c)
            mb.box((0, 0.6, 1.7), (0.34, 0.3, 0.6), c, taper=0.75)
            mb.box((0, 0.48, 1.85), (0.28, 0.12, 0.5), shade(c, 0.7))
            for sx in (-1, 1):
                mb.box((sx * 0.12, 0.72, 1.82), (0.06, 0.05, 0.05), (1.0, 0.5, 0.1, 1))
                mb.cone((sx * 0.12, 0.78, 1.45), 0.05, 0.4, IVORY, rot=(-60, 0, 0), segments=3)
            mb.beam((0, 0.0, -0.8), (0, -0.2, -2.4), 0.2, c, segments=5, radius_b=0.04)
            for k in range(5):
                mb.cone((0, 0.42 - k * 0.04, 0.7 - k * 0.35), 0.06, 0.25, a, segments=3)
            mb.box((0, 0.42, 0.05), (0.6, 0.08, 0.6), a)
        return mb

    def _wing(self, side: int) -> MeshBuilder:
        mb = MeshBuilder()
        c = self.col if self.style == "hawk" else shade(self.col, 0.85)
        tip = shade(c, 0.7) if self.style == "hawk" else self.acc
        mb.quad((0, 0, 0.4), (side * 1.6, 0.08, 0.15), (side * 1.5, 0.0, -0.5), (0, 0, -0.45), c, facing=(0, 1, 0), double=True)
        mb.quad((side * 1.6, 0.08, 0.15), (side * 2.6, 0.0, -0.15), (side * 2.3, -0.02, -0.75), (side * 1.5, 0.0, -0.5),
                tip, facing=(0, 1, 0), double=True)
        return mb

    def _pose(self, dt: float, speed: float, grounded: bool, swimming: bool) -> None:
        t = self.idle_t
        fs = 7.5 if self.action == "attack" else 4.5
        flap = math.sin(t * fs) * (22 + 14 * self.move_blend)
        for j, w in enumerate(self.wings):
            side = -1 if j == 0 else 1
            set_rot(w, 0, 0, side * (flap + 4))
        bank = 0.0
        act, p = self.action, self.action_progress()
        dive = 18 * math.sin(p * math.pi) if act == "attack" else 0.0
        set_rot(self.torso, 4 * self.move_blend + dive, 0, bank)
        self.torso.setY(math.sin(t * fs) * 0.12)

    def _pose_death(self, t: float) -> None:
        e = 1 - (1 - t) ** 3
        set_rot(self.body, 30 * e, 0, 120 * e)


# ============================================================================ factory
def build_unit_rig(model: dict[str, Any], team_color: tuple[float, float, float]) -> Rig:
    """Create the rig described by a units.json ``model`` entry, painted in ``team_color``."""
    spec = resolve_team(model, team_color)
    kind = spec.get("kind", "humanoid")
    if kind == "rider":
        rig: Rig = RiderRig(spec.get("mount", "horse"), spec.get("mount_color", (0.5, 0.4, 0.3)), spec.get("barding"),
                            spec.get("look", {}))
    elif kind == "ogre":
        rig = OgreRig(spec.get("skin", (0.5, 0.47, 0.42)), spec.get("accent"))
    elif kind == "siege":
        rig = SiegeRig(spec.get("style", "catapult"), team_color)
    elif kind == "flyer":
        rig = FlyerRig(spec.get("style", "hawk"), spec.get("color", (0.5, 0.4, 0.3)), spec.get("accent"))
    else:
        look = dict(spec.get("look", {}))
        rig = UnitHumanoidRig(look)
    sc = float(spec.get("scale", 1.0))
    if kind == "humanoid":
        sc *= float(rig.look.get("scale", 1.0))  # type: ignore[attr-defined]
    if sc != 1.0:
        rig.body.setScale(sc)
        rig.height *= sc
        rig.radius *= sc
        rig.scale = sc
    return rig
