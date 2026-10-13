"""Humanoid character models (orcs, trolls, goblins and their outfits) built from primitives."""
from __future__ import annotations

import math
from typing import Any


from core.meshgen import MeshBuilder, shade
from core.rig import Rig, copy_part, swing
from core.util import clamp, set_rot

IVORY = (0.93, 0.88, 0.72, 1.0)
WOOD = (0.44, 0.29, 0.17, 1.0)
DARK_WOOD = (0.28, 0.18, 0.11, 1.0)
METAL = (0.62, 0.62, 0.66, 1.0)
DARK_METAL = (0.30, 0.29, 0.31, 1.0)
LEATHER = (0.45, 0.30, 0.18, 1.0)
CLOTH_RED = (0.62, 0.16, 0.12, 1.0)

RACES: dict[str, dict[str, Any]] = {
    "orc": {"skin": (0.36, 0.55, 0.26), "hair": (0.08, 0.07, 0.06), "height": 1.0, "bulk": 1.15,
            "hunch": 9.0, "hair_style": "topknot", "eyes": (0.95, 0.72, 0.10), "arm_len": 1.0},
    "troll": {"skin": (0.30, 0.52, 0.62), "hair": (0.86, 0.26, 0.20), "height": 1.1, "bulk": 0.9,
              "hunch": 15.0, "hair_style": "mohawk", "eyes": (0.95, 0.92, 0.45), "arm_len": 1.12},
    "goblin": {"skin": (0.46, 0.62, 0.24), "hair": (0.20, 0.14, 0.10), "height": 0.62, "bulk": 0.95,
               "hunch": 14.0, "hair_style": "bald", "eyes": (1.00, 0.35, 0.10), "arm_len": 1.08},
    "human": {"skin": (0.87, 0.69, 0.56), "hair": (0.32, 0.22, 0.13), "height": 1.0, "bulk": 0.92,
              "hunch": 2.0, "hair_style": "short", "eyes": (0.12, 0.16, 0.24), "arm_len": 1.0},
    "elf": {"skin": (0.93, 0.82, 0.71), "hair": (0.92, 0.86, 0.62), "height": 1.07, "bulk": 0.8,
            "hunch": 0.0, "hair_style": "long", "eyes": (0.25, 0.55, 0.35), "arm_len": 1.02},
}

DEFAULT_LOOK: dict[str, Any] = {
    "race": "orc", "chest_style": "bare", "shirt": None, "pants": (0.40, 0.28, 0.18),
    "boots": (0.30, 0.20, 0.12), "belt": (0.30, 0.19, 0.11), "helmet": None, "helmet_color": (0.45, 0.42, 0.40),
    "shoulders": None, "weapon": None, "weapon_color": None, "offhand": None, "bracers": None,
    "beard": False, "headdress": None, "mask": None, "scale": 1.0,
}


def _c(v: Any, a: float = 1.0) -> tuple[float, float, float, float]:
    if v is None:
        return (1, 1, 1, a)
    if len(v) == 4:
        return tuple(v)  # type: ignore[return-value]
    return (float(v[0]), float(v[1]), float(v[2]), a)


def resolve_look(look: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_LOOK)
    race = (look or {}).get("race", "orc")
    out.update(RACES.get(race, RACES["orc"]))
    if look:
        out.update({k: v for k, v in look.items() if v is not None or k in ("shirt", "helmet", "shoulders", "weapon", "offhand", "boots", "mask", "headdress")})
    out["race"] = race
    return out


def _key(look: dict[str, Any], part: str, extra: tuple = ()) -> tuple:
    def fz(v: Any) -> Any:
        if isinstance(v, (list, tuple)):
            return tuple(round(float(x), 3) for x in v)
        return v
    return (part,) + tuple((k, fz(look[k])) for k in sorted(look.keys())) + extra


# ---------------------------------------------------------------------------- parts
def _torso(L: dict[str, Any]) -> MeshBuilder:
    s, b = L["height"], L["bulk"]
    mb = MeshBuilder()
    skin = _c(L["skin"])
    shirt = _c(L["shirt"]) if L["shirt"] is not None else None
    pants = _c(L["pants"])
    style = L["chest_style"]
    # pelvis
    mb.box((0, 0.06 * s, 0), (0.56 * b * s, 0.30 * s, 0.36 * b * s), pants)
    chest_col = skin
    if style in ("tunic", "plate", "robe", "shirt") and shirt:
        chest_col = shirt
    mb.box((0, 0.47 * s, 0), (0.66 * b * s, 0.62 * s, 0.40 * b * s), chest_col, taper=1.2)
    if style == "bare":
        mb.beam((-0.3 * b * s, 0.72 * s, 0.215 * b * s), (0.28 * b * s, 0.22 * s, 0.215 * b * s), (0.07 * s, 0.03 * s), _c(L["belt"]))
    if style == "vest" and shirt:
        for sx in (-1, 1):
            mb.box((sx * 0.25 * b * s, 0.47 * s, 0.01), (0.2 * b * s, 0.64 * s, 0.44 * b * s), shirt, taper=1.2)
        mb.box((0, 0.47 * s, -0.08 * b * s), (0.62 * b * s, 0.6 * s, 0.28 * b * s), shirt, taper=1.2)
    if style == "plate" and shirt:
        mb.box((0, 0.55 * s, 0.03 * s), (0.58 * b * s, 0.34 * s, 0.4 * b * s), shade(shirt, 1.18), taper=1.1)
        mb.box((0, 0.3 * s, 0.02 * s), (0.5 * b * s, 0.12 * s, 0.42 * b * s), shade(shirt, 0.85))
    if style == "robe" and shirt:
        mb.box((0, -0.2 * s, 0), (0.62 * b * s, 0.55 * s, 0.44 * b * s), shade(shirt, 0.92), taper=0.82)
    if style == "tunic" and shirt:
        mb.box((0, -0.05 * s, 0.0), (0.6 * b * s, 0.26 * s, 0.4 * b * s), shade(shirt, 0.9))
    # belt + buckle
    mb.box((0, 0.2 * s, 0), (0.6 * b * s, 0.1 * s, 0.4 * b * s), _c(L["belt"]))
    mb.box((0, 0.2 * s, 0.2 * b * s), (0.12 * s, 0.1 * s, 0.04 * s), METAL)
    # neck
    mb.box((0, 0.8 * s, 0.02 * s), (0.22 * b * s, 0.14 * s, 0.22 * b * s), skin)
    # shoulder pads
    if L["shoulders"] is not None:
        sc = _c(L["shoulders"])
        for sx in (-1, 1):
            mb.box((sx * 0.43 * b * s, 0.76 * s, 0), (0.3 * s, 0.14 * s, 0.34 * s), sc, rot=(0, 0, sx * -18))
            if L["race"] == "orc":
                mb.cone((sx * 0.47 * b * s, 0.8 * s, 0), 0.05 * s, 0.22 * s, IVORY, rot=(0, 0, sx * -35))
    # back item: quiver for bows
    if L["weapon"] == "bow":
        mb.cylinder((0.12 * s, 0.25 * s, -0.25 * b * s), 0.09 * s, 0.6 * s, LEATHER, rot=(-12, 0, -20))
        for i in range(3):
            mb.box((0.12 * s + (i - 1) * 0.04 * s + 0.2 * s, 0.9 * s, -0.33 * b * s), (0.02 * s, 0.14 * s, 0.02 * s), (0.9, 0.9, 0.85, 1))
    if L.get("cape"):
        mb.box((0, 0.3 * s, -0.24 * b * s), (0.62 * b * s, 1.0 * s, 0.04 * s), _c(L["cape"]), taper=1.25)
    return mb


def _head(L: dict[str, Any]) -> MeshBuilder:
    s = L["height"]
    race = L["race"]
    mb = MeshBuilder()
    skin = _c(L["skin"])
    dark = shade(skin, 0.78)
    eyes = _c(L["eyes"])
    hair = _c(L["hair"])
    if race == "troll":
        mb.box((0, 0.24 * s, -0.01 * s), (0.32 * s, 0.4 * s, 0.36 * s), skin, taper=0.9)
        mb.box((0, 0.12 * s, 0.17 * s), (0.24 * s, 0.17 * s, 0.3 * s), skin)
        mb.box((0, 0.2 * s, 0.3 * s), (0.1 * s, 0.1 * s, 0.14 * s), dark)
        for sx in (-1, 1):
            mb.cone((sx * 0.09 * s, 0.08 * s, 0.28 * s), 0.035 * s, 0.24 * s, IVORY, rot=(-25, 0, sx * -12))
            mb.beam((sx * 0.15 * s, 0.26 * s, -0.02 * s), (sx * 0.46 * s, 0.37 * s, -0.12 * s), (0.04 * s, 0.13 * s), skin)
            mb.box((sx * 0.085 * s, 0.28 * s, 0.17 * s), (0.07 * s, 0.035 * s, 0.03 * s), eyes)
        mb.box((0, 0.32 * s, 0.16 * s), (0.34 * s, 0.05 * s, 0.08 * s), dark)
    elif race == "goblin":
        mb.box((0, 0.22 * s, 0), (0.42 * s, 0.4 * s, 0.4 * s), skin, taper=0.85)
        mb.cone((0, 0.2 * s, 0.2 * s), 0.07 * s, 0.24 * s, dark, rot=(90, 0, 0))
        for sx in (-1, 1):
            mb.beam((sx * 0.18 * s, 0.26 * s, 0), (sx * 0.62 * s, 0.4 * s, -0.08 * s), (0.04 * s, 0.2 * s), skin)
            mb.box((sx * 0.11 * s, 0.28 * s, 0.2 * s), (0.09 * s, 0.07 * s, 0.03 * s), eyes)
        mb.box((0, 0.08 * s, 0.14 * s), (0.3 * s, 0.07 * s, 0.14 * s), dark)
        for sx in (-1, 1):
            mb.box((sx * 0.06 * s, 0.1 * s, 0.21 * s), (0.04 * s, 0.05 * s, 0.02 * s), IVORY)
    elif race in ("human", "elf"):
        narrow = 0.86 if race == "elf" else 1.0
        mb.box((0, 0.22 * s, 0), (0.34 * s * narrow, 0.4 * s, 0.36 * s), skin, taper=0.92)
        mb.box((0, 0.2 * s, 0.19 * s), (0.07 * s, 0.12 * s, 0.07 * s), shade(skin, 0.92))
        mb.box((0, 0.07 * s, 0.1 * s), (0.28 * s * narrow, 0.1 * s, 0.24 * s), skin, taper=0.8)
        for sx in (-1, 1):
            mb.box((sx * 0.08 * s, 0.26 * s, 0.18 * s), (0.06 * s, 0.03 * s, 0.02 * s), eyes)
            mb.box((sx * 0.08 * s, 0.31 * s, 0.18 * s), (0.09 * s, 0.025 * s, 0.03 * s), shade(hair, 0.9))
            if race == "elf":
                mb.beam((sx * 0.14 * s, 0.24 * s, -0.01 * s), (sx * 0.32 * s, 0.42 * s, -0.08 * s), (0.03 * s, 0.09 * s), skin)
            else:
                mb.box((sx * 0.18 * s, 0.22 * s, 0.0), (0.04 * s, 0.1 * s, 0.07 * s), skin)
    else:  # orc
        mb.box((0, 0.24 * s, 0), (0.4 * s, 0.4 * s, 0.4 * s), skin, taper=0.9)
        mb.box((0, 0.3 * s, 0.18 * s), (0.42 * s, 0.07 * s, 0.1 * s), dark)
        mb.box((0, 0.2 * s, 0.21 * s), (0.13 * s, 0.1 * s, 0.07 * s), dark)
        mb.box((0, 0.06 * s, 0.07 * s), (0.38 * s, 0.14 * s, 0.36 * s), skin)
        for sx in (-1, 1):
            mb.cone((sx * 0.12 * s, 0.11 * s, 0.22 * s), 0.035 * s, 0.14 * s, IVORY, rot=(-8, 0, sx * -10))
            mb.box((sx * 0.1 * s, 0.25 * s, 0.2 * s), (0.08 * s, 0.035 * s, 0.03 * s), eyes)
            mb.box((sx * 0.22 * s, 0.25 * s, 0.0), (0.06 * s, 0.14 * s, 0.1 * s), skin, rot=(0, 0, sx * -25))
            mb.cone((sx * 0.25 * s, 0.3 * s, -0.02 * s), 0.035 * s, 0.1 * s, skin, rot=(0, 0, sx * -60))
    # hair
    style = L["hair_style"]
    top = 0.44 * s
    if style == "topknot":
        mb.box((0, top, -0.08 * s), (0.14 * s, 0.1 * s, 0.14 * s), hair)
        mb.beam((0, top + 0.03 * s, -0.12 * s), (0, top - 0.3 * s, -0.32 * s), 0.07 * s, hair)
    elif style == "mohawk":
        for i in range(5):
            z = 0.14 * s - i * 0.08 * s
            hgt = (0.22 + 0.06 * math.sin(i * 0.9)) * s
            mb.box((0, top + hgt * 0.4 - 0.02 * s, z), (0.09 * s, hgt * 1.15, 0.09 * s), hair, rot=(-10 + i * 6, 0, 0))
    elif style == "braids":
        for sx in (-1, 1):
            mb.beam((sx * 0.18 * s, 0.34 * s, -0.08 * s), (sx * 0.22 * s, -0.12 * s, -0.12 * s), 0.07 * s, hair)
    elif style == "long":
        mb.box((0, 0.26 * s, -0.16 * s), (0.42 * s, 0.46 * s, 0.14 * s), hair)
        mb.box((0, 0.42 * s, -0.02 * s), (0.38 * s, 0.08 * s, 0.36 * s), hair)
    elif style == "short":
        mb.box((0, 0.42 * s, -0.03 * s), (0.37 * s, 0.09 * s, 0.39 * s), hair)
        mb.box((0, 0.3 * s, -0.17 * s), (0.36 * s, 0.24 * s, 0.08 * s), hair)
    if L.get("beard"):
        mb.box((0, -0.06 * s, 0.16 * s), (0.3 * s, 0.22 * s, 0.14 * s), _c(L.get("beard_color", (0.75, 0.75, 0.72))), taper=0.6)
    # headgear
    helm = L["helmet"]
    hc = _c(L["helmet_color"])
    if helm in ("cap", "horned", "miner", "spiked"):
        mb.box((0, 0.42 * s, 0), (0.46 * s, 0.14 * s, 0.46 * s), hc, taper=0.85)
        mb.box((0, 0.36 * s, 0.02 * s), (0.48 * s, 0.05 * s, 0.48 * s), shade(hc, 0.8))
        if helm == "horned":
            for sx in (-1, 1):
                mb.cone((sx * 0.22 * s, 0.42 * s, 0), 0.06 * s, 0.3 * s, IVORY, rot=(0, 0, sx * -70))
        if helm == "spiked":
            mb.cone((0, 0.48 * s, 0), 0.06 * s, 0.26 * s, METAL)
        if helm == "miner":
            mb.box((0, 0.42 * s, 0.24 * s), (0.1 * s, 0.1 * s, 0.06 * s), (1.0, 0.85, 0.3, 1))
    elif helm == "hood":
        mb.box((0, 0.26 * s, -0.03 * s), (0.46 * s, 0.48 * s, 0.46 * s), hc, taper=0.75)
        mb.cone((0, 0.35 * s, -0.22 * s), 0.1 * s, 0.25 * s, hc, rot=(-60, 0, 0))
    elif helm == "bandana":
        mb.box((0, 0.36 * s, 0.0), (0.43 * s, 0.1 * s, 0.43 * s), hc)
        mb.beam((0, 0.37 * s, -0.2 * s), (0.05 * s, 0.18 * s, -0.34 * s), (0.04 * s, 0.1 * s), hc)
    if L.get("mask"):
        mb.box((0, 0.1 * s, 0.1 * s), (0.44 * s, 0.14 * s, 0.4 * s), _c(L["mask"]))
    if L.get("headdress"):
        hd = _c(L["headdress"])
        for i, ang in enumerate((-35, -12, 12, 35)):
            mb.beam((0, 0.4 * s, -0.05 * s), (math.sin(math.radians(ang)) * 0.3 * s, 0.85 * s, -0.12 * s),
                    (0.05 * s, 0.015 * s), hd if i % 2 else (0.95, 0.92, 0.85, 1))
        mb.box((0, 0.4 * s, 0), (0.44 * s, 0.07 * s, 0.44 * s), shade(hd, 0.7))
    return mb


def _arm(L: dict[str, Any]) -> MeshBuilder:
    s, b = L["height"], L["bulk"]
    a = L["arm_len"]
    mb = MeshBuilder()
    skin = _c(L["skin"])
    sleeve = _c(L["shirt"]) if (L["shirt"] is not None and L["chest_style"] in ("tunic", "robe", "shirt", "plate")) else skin
    mb.box((0, -0.22 * s * a, 0), (0.2 * b * s, 0.48 * s * a, 0.2 * b * s), sleeve)
    mb.box((0, -0.6 * s * a, 0), (0.18 * b * s, 0.38 * s * a, 0.18 * b * s), skin)
    if L["bracers"] is not None:
        mb.box((0, -0.66 * s * a, 0), (0.21 * b * s, 0.2 * s * a, 0.21 * b * s), _c(L["bracers"]))
    mb.box((0, -0.86 * s * a, 0.01), (0.16 * b * s, 0.14 * s, 0.17 * b * s), skin)
    return mb


def _leg(L: dict[str, Any]) -> MeshBuilder:
    s, b = L["height"], L["bulk"]
    mb = MeshBuilder()
    pants = _c(L["pants"])
    boots = _c(L["boots"]) if L["boots"] is not None else _c(L["skin"])
    mb.box((0, -0.24 * s, 0), (0.24 * b * s, 0.5 * s, 0.27 * b * s), pants)
    mb.box((0, -0.64 * s, 0), (0.2 * b * s, 0.4 * s, 0.22 * b * s), pants)
    if L["boots"] is not None:
        mb.box((0, -0.76 * s, 0.0), (0.23 * b * s, 0.26 * s, 0.25 * b * s), boots)
    mb.box((0, -0.9 * s, 0.07 * s), (0.21 * b * s, 0.1 * s, 0.34 * s), boots)
    return mb


def weapon_mesh(kind: str, color: Any = None) -> MeshBuilder:
    """Weapon in hand space: the grip is at the origin, blades point along +z (or +y for polearms)."""
    mb = MeshBuilder()
    m = _c(color) if color is not None else METAL
    if kind == "axe":
        mb.beam((0, 0, -0.18), (0, 0, 0.86), 0.045, WOOD, segments=5)
        mb.box((0, -0.14, 0.72), (0.06, 0.26, 0.2), m, taper=1.0)
        mb.box((0, -0.3, 0.72), (0.04, 0.08, 0.36), shade(m, 1.25))
        mb.cone((0, 0.02, 0.72), 0.04, 0.16, m, rot=(0, 0, 180))
    elif kind == "greataxe":
        mb.beam((0, 0, -0.35), (0, 0, 1.3), 0.055, DARK_WOOD, segments=5)
        for sy in (-1, 1):
            mb.box((0, sy * 0.2, 1.08), (0.07, 0.34, 0.34), m)
            mb.box((0, sy * 0.4, 1.08), (0.05, 0.1, 0.52), shade(m, 1.25))
    elif kind == "sword":
        mb.beam((0, 0, -0.12), (0, 0, 0.12), 0.04, LEATHER, segments=5)
        mb.box((0, 0, 0.14), (0.3, 0.06, 0.07), shade(m, 0.8))
        mb.box((0, 0, 0.62), (0.1, 0.03, 0.92), shade(m, 1.15), taper=1.0)
        mb.cone((0, 0, 1.08), 0.06, 0.16, shade(m, 1.15), rot=(90, 0, 0), segments=4)
    elif kind == "cutlass":
        mb.beam((0, 0, -0.1), (0, 0, 0.1), 0.04, LEATHER, segments=5)
        mb.box((0, 0.02, 0.12), (0.18, 0.12, 0.05), (0.8, 0.65, 0.2, 1))
        mb.beam((0, 0, 0.12), (0, -0.12, 0.8), (0.03, 0.12), shade(m, 1.2))
    elif kind == "mace":
        mb.beam((0, 0, -0.15), (0, 0, 0.7), 0.045, WOOD, segments=5)
        mb.sphere((0, 0, 0.78), 0.14, m, detail=0)
        for d in ((0.14, 0, 0.78), (-0.14, 0, 0.78), (0, 0.14, 0.78), (0, -0.14, 0.78), (0, 0, 0.92)):
            mb.box(d, (0.06, 0.06, 0.06), shade(m, 0.8))
    elif kind == "club":
        mb.beam((0, 0, -0.1), (0, 0, 0.85), 0.05, WOOD, segments=5, radius_b=0.11)
        mb.cone((0.08, 0, 0.7), 0.03, 0.12, IVORY, rot=(0, 0, -90))
    elif kind == "staff":
        mb.beam((0, -1.0, 0), (0, 1.05, 0), 0.04, WOOD, segments=5)
        mb.sphere((0, 1.12, 0), 0.1, m if color is not None else (0.3, 0.7, 0.9, 1), detail=0)
        for sx in (-1, 1):
            mb.beam((0, 0.98, 0), (sx * 0.14, 1.28, 0), (0.03, 0.02), (0.95, 0.9, 0.8, 1))
    elif kind == "spear":
        mb.beam((0, -1.0, 0), (0, 1.1, 0), 0.04, WOOD, segments=5)
        mb.cone((0, 1.08, 0), 0.07, 0.34, m, segments=4)
        mb.box((0, 0.95, 0), (0.12, 0.06, 0.06), (0.85, 0.3, 0.2, 1))
    elif kind == "bow":
        wood = _c(color) if color is not None else WOOD
        pts = [(0, 0, 0), (0, -0.1, 0.32), (0, -0.04, 0.62), (0, 0.02, 0.7)]
        for sz in (-1, 1):
            for p0, p1 in zip(pts[:-1], pts[1:]):
                mb.beam((p0[0], p0[1], p0[2] * sz), (p1[0], p1[1], p1[2] * sz), 0.035, wood, segments=4)
        mb.beam((0, 0.02, -0.7), (0, 0.02, 0.7), 0.008, (0.92, 0.9, 0.85, 1))
    elif kind == "crossbow":
        mb.box((0, 0, 0.25), (0.08, 0.1, 0.7), WOOD)
        mb.beam((-0.35, 0, 0.5), (0.35, 0, 0.5), 0.03, DARK_METAL)
    elif kind == "pickaxe":
        mb.beam((0, 0, -0.15), (0, 0, 0.8), 0.04, WOOD, segments=5)
        mb.beam((0, 0.3, 0.62), (0, -0.3, 0.76), (0.06, 0.06), m)
    elif kind == "dagger":
        mb.beam((0, 0, -0.08), (0, 0, 0.08), 0.035, LEATHER, segments=4)
        mb.box((0, 0, 0.3), (0.07, 0.025, 0.4), shade(m, 1.2))
    elif kind == "torch":
        mb.beam((0, 0, -0.1), (0, 0, 0.5), 0.04, WOOD, segments=5)
        mb.sphere((0, 0, 0.58), 0.09, (1.0, 0.6, 0.15, 1), detail=0)
    elif kind == "ladle":
        mb.beam((0, 0, -0.1), (0, 0, 0.6), 0.03, WOOD, segments=4)
        mb.sphere((0, -0.04, 0.66), 0.08, WOOD, detail=0)
    return mb


def offhand_mesh(kind: str, color: Any = None) -> MeshBuilder:
    mb = MeshBuilder()
    if kind == "shield":
        c = _c(color) if color is not None else (0.5, 0.33, 0.2, 1)
        mb.cylinder((0.1, -0.45, 0), 0.4, 0.08, c, segments=8, rot=(0, 0, 90))
        mb.sphere((0.2, -0.45, 0), 0.1, METAL, detail=0)
    elif kind == "lantern":
        mb.box((0, -0.2, 0), (0.16, 0.22, 0.16), (1.0, 0.8, 0.35, 1))
        mb.box((0, -0.06, 0), (0.2, 0.05, 0.2), DARK_METAL)
    return mb


# ----------------------------------------------------------------------------- rig
class HumanoidRig(Rig):
    """Two-legged character with animated arms, legs and head."""

    def __init__(self, look: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.look = resolve_look(look)
        self.look_yaw = 0.0
        self._build_skeleton()
        self.rebuild()

    def _build_skeleton(self) -> None:
        L = self.look
        s, b = L["height"], L["bulk"]
        self.leg_len = 0.95 * s
        self.height = (0.95 + 0.85 + 0.48) * s
        self.radius = 0.42 * b * s + 0.08
        self.hips = self.body.attachNewNode("hips")
        self.hips.setPos(0, self.leg_len, 0)
        self.torso = self.hips.attachNewNode("torso")
        self.neck = self.torso.attachNewNode("neck")
        self.neck.setPos(0, 0.86 * s, 0.03 * s)
        self.arm_l = self.torso.attachNewNode("arm_l")
        self.arm_r = self.torso.attachNewNode("arm_r")
        self.arm_l.setPos(-0.44 * b * s, 0.72 * s, 0)
        self.arm_r.setPos(0.44 * b * s, 0.72 * s, 0)
        a = L["arm_len"]
        self.hand_l = self.arm_l.attachNewNode("hand_l")
        self.hand_r = self.arm_r.attachNewNode("hand_r")
        self.hand_l.setPos(0, -0.86 * s * a, 0.02)
        self.hand_r.setPos(0, -0.86 * s * a, 0.02)
        self.leg_l = self.hips.attachNewNode("leg_l")
        self.leg_r = self.hips.attachNewNode("leg_r")
        self.leg_l.setPos(-0.17 * b * s, 0, 0)
        self.leg_r.setPos(0.17 * b * s, 0, 0)
        self.hunch = L["hunch"]
        self.weapon_kind = L["weapon"]

    def set_look(self, **changes: Any) -> None:
        """Change outfit colours/gear and rebuild the affected meshes."""
        self.look.update(changes)
        self.weapon_kind = self.look["weapon"]
        self.rebuild()

    def rebuild(self) -> None:
        L = self.look
        for pivot in (self.torso, self.neck, self.arm_l, self.arm_r, self.leg_l, self.leg_r, self.hand_l, self.hand_r):
            for child in pivot.getChildren():
                if child.getName().startswith("mesh"):
                    child.removeNode()
        copy_part(_key(L, "torso"), lambda: _torso(L), self.torso).setName("mesh_torso")
        copy_part(_key(L, "head"), lambda: _head(L), self.neck).setName("mesh_head")
        copy_part(_key(L, "arm"), lambda: _arm(L), self.arm_l).setName("mesh_arm")
        copy_part(_key(L, "arm"), lambda: _arm(L), self.arm_r).setName("mesh_arm")
        copy_part(_key(L, "leg"), lambda: _leg(L), self.leg_l).setName("mesh_leg")
        copy_part(_key(L, "leg"), lambda: _leg(L), self.leg_r).setName("mesh_leg")
        wk = L["weapon"]
        if wk:
            wkey = ("weapon", wk, tuple(L["weapon_color"]) if L["weapon_color"] else None)
            hand = self.hand_l if wk == "bow" else self.hand_r
            w = copy_part(wkey, lambda: weapon_mesh(wk, L["weapon_color"]), hand)
            w.setName("mesh_weapon")
            w.setScale(L["height"] ** 0.5)
        if L["offhand"]:
            okey = ("offhand", L["offhand"])
            o = copy_part(okey, lambda: offhand_mesh(L["offhand"]), self.hand_l)
            o.setName("mesh_offhand")

    # -------------------------------------------------------------------- animation
    def _pose(self, dt: float, speed: float, grounded: bool, swimming: bool) -> None:
        mbl = self.move_blend
        ph = self.phase
        s = self.look["height"]
        running = speed > 4.0
        amp = (42 if running else 30) * mbl
        leg = swing(ph, amp)
        arm = swing(ph, amp * 0.75)
        hips_y = self.leg_len + abs(math.sin(ph)) * 0.07 * s * mbl - 0.03 * s * mbl
        breathe = math.sin(self.idle_t * 2.2) * 0.015
        torso_x = self.hunch + (8.0 if running else 3.0) * mbl
        torso_y = swing(ph, 6 * mbl)
        la = (arm, 0.0, -6.0)
        ra = (-arm, 0.0, 6.0)
        ll = -leg
        rl = leg
        body_x = 0.0
        if self.weapon_kind in ("staff", "spear"):
            ra = (-arm * 0.3 - 10, 0.0, 6.0)
        if not grounded and not swimming:
            ll, rl = -30.0, 18.0
            la = (-40.0, 0.0, -25.0)
            ra = (-40.0, 0.0, 25.0)
        if swimming:
            body_x = 0.0
            torso_x = 55.0
            kick = swing(self.idle_t * 6.0, 22)
            ll, rl = kick, -kick
            stroke = self.idle_t * 3.0
            la = (-90 + math.sin(stroke) * 70, 0.0, -20.0)
            ra = (-90 - math.sin(stroke) * 70, 0.0, 20.0)
            hips_y = self.leg_len * 0.6

        # actions override
        act = self.action
        t = self.action_progress()
        if act == "attack":
            if t < 0.35:
                k = t / 0.35
                ra = (-arm * (1 - k) - 150 * k, 0.0, 10.0 + 10 * k)
                torso_y += -15 * k
            elif t < 0.6:
                k = (t - 0.35) / 0.25
                ra = (-150 + 170 * k, 0.0, 20.0 - 10 * k)
                torso_y += -15 + 30 * k
                torso_x += 10 * k
            else:
                k = (t - 0.6) / 0.4
                ra = (20 * (1 - k), 0.0, 10.0)
                torso_y += 15 * (1 - k)
                torso_x += 10 * (1 - k)
        elif act == "attack2":
            k = math.sin(t * math.pi)
            ra = (-80.0, -60 + 120 * t, 30 * k)
            torso_y += -30 + 60 * t
        elif act in ("cast", "channel"):
            wob = math.sin(self.idle_t * 9.0) * 6
            k = min(t * 4.0, 1.0) if act == "cast" else 1.0
            la = (-70 * k + wob, 0.0, -20.0 * k)
            ra = (-70 * k - wob, 0.0, 20.0 * k)
            torso_x += -5 * k
        elif act == "release":
            k = 1 - t
            la = (-100 * k, 0.0, -35.0 * k)
            ra = (-100 * k, 0.0, 35.0 * k)
        elif act == "shoot":
            la = (-88.0, -10.0, 0.0)
            pull = min(t * 2.5, 1.0) if t < 0.75 else 0.0
            ra = (-88.0, 55.0 * pull + 5.0, 0.0)
            torso_y += -20.0
        elif act == "hit":
            k = math.sin(t * math.pi)
            torso_x -= 14 * k
        elif act == "roar":
            k = math.sin(t * math.pi)
            la = (-140.0 * k, 0.0, -40.0 * k)
            ra = (-140.0 * k, 0.0, 40.0 * k)
            torso_x -= 18 * k
        elif act == "interact":
            k = math.sin(t * math.pi)
            torso_x += 35 * k
            ra = (-60.0 * k, 0.0, 5.0)
        elif act == "talk":
            k = math.sin(t * math.pi * 2)
            ra = (-45 + 15 * k, 10 * k, 12.0)
        elif act == "wave":
            k = math.sin(t * math.pi * 6)
            ra = (-160.0, 0.0, 30 + 20 * k)
        elif act == "stomp":
            k = math.sin(t * math.pi)
            hips_y -= 0.25 * s * k
            la = (-60.0 * k, 0.0, -50.0 * k)
            ra = (-60.0 * k, 0.0, 50.0 * k)
        elif act == "kneel":
            k = math.sin(min(t, 0.999) * math.pi)
            hips_y -= 0.35 * s * k
            ll, rl = -70 * k, 20 * k

        self.hips.setY(hips_y)
        set_rot(self.body, body_x, 0, 0)
        set_rot(self.torso, torso_x, torso_y, 0)
        self.torso.setScale(1.0, 1.0 + breathe, 1.0)
        set_rot(self.neck, -self.hunch * 0.8 - (torso_x - self.hunch) * 0.5, clamp(self.look_yaw, -60, 60), 0)
        set_rot(self.arm_l, *la)
        set_rot(self.arm_r, *ra)
        set_rot(self.leg_l, ll, 0, 0)
        set_rot(self.leg_r, rl, 0, 0)

    def _pose_death(self, t: float) -> None:
        e = 1 - (1 - t) ** 3
        set_rot(self.body, -84 * e, 0, 6 * e)
        self.body.setY(0.05 * e)
        set_rot(self.arm_l, -150 * e, 0, -30 * e)
        set_rot(self.arm_r, -120 * e, 0, 40 * e)
        set_rot(self.leg_l, -10 * e, 0, 0)
        set_rot(self.leg_r, 15 * e, 0, 0)


def build_humanoid(look: dict[str, Any] | None = None, scale: float | None = None) -> HumanoidRig:
    rig = HumanoidRig(look)
    sc = scale if scale is not None else float(rig.look.get("scale", 1.0))
    if sc != 1.0:
        rig.body.setScale(sc)
        rig.height *= sc
        rig.radius *= sc
        rig.scale = sc
    return rig


def nameplate_anchor(rig: Rig) -> float:
    return rig.height + 0.35
