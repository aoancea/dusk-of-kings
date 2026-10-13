"""Developer tool: print a cost-efficiency table for every unit (DPS x HP per cost^2).

    python tools/unit_stats.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import data


def eff_dps(att: dict, armor_type: str, armor: float) -> float:
    m = data.combat()["multipliers"][att["type"]][armor_type]
    dmg = max(1.0, att["damage"] * m - armor)
    splash = 1.0 + (0.8 if att.get("splash") else 0.0)
    return dmg / att["cooldown"] * splash


def main() -> None:
    units = data.units()
    print(f"{'unit':18} {'fac':8} {'cost':>5} {'sup':>3} {'hp':>4} {'arm':>3} {'dpsL':>5} {'dpsH':>5} {'dpsF':>5} {'power/cost^2 L':>14} {'H':>6}")
    for uid, u in units.items():
        if u["role"] == "worker":
            continue
        c = u["cost"]["gold"] + u["cost"]["timber"]
        att = u["attack"]
        hp = u["hp"]
        # effective HP vs a typical 10-damage normal attack
        ehp = hp * 10.0 / max(1.0, 10.0 - u["armor"])
        dl = eff_dps(att, "light", 0.5)
        dh = eff_dps(att, "heavy", 1.5)
        df = eff_dps(att, "fortified", 4)
        pl = dl * ehp / c / c * 1000
        ph = dh * ehp / c / c * 1000
        print(f"{uid:18} {u['faction']:8} {c:5} {u['supply']:3} {hp:4} {u['armor']:3} {dl:5.1f} {dh:5.1f} {df:5.1f} {pl:14.2f} {ph:6.2f}")


if __name__ == "__main__":
    main()
