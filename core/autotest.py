"""Scripted smoke tests: drive a match for a while, take screenshots, log checks, quit.

Run with ``python main.py --autotest m1`` (see SCRIPTS below). Screenshots go to screenshots/autotest.
"""
from __future__ import annotations

import json
import math
import traceback
from typing import Any, Callable

from panda3d.core import Filename
from ursina import application, held_keys

from core.match import MatchConfig, PlayerConfig
from settings import SCREENSHOT_DIR

Step = tuple


def config_for(name: str, map_id: str) -> MatchConfig:
    """Match setup used by each test."""
    spec = CONFIGS.get(name.split("_")[0], {})
    players = [PlayerConfig(spec.get("me", "alliance"), spec.get("me_ai", False), spec.get("diff", "normal")),
               PlayerConfig(spec.get("them", "host"), True, spec.get("diff", "normal"))]
    return MatchConfig(map_id=spec.get("map", map_id), players=players, human=None if spec.get("spectate") else 0,
                       fog=spec.get("fog", True), seed=spec.get("seed", 1), ai_enabled=spec.get("ai", False))


class AutoTest:
    """Executes a list of timed steps against the running game."""

    def __init__(self, game, name: str) -> None:
        self.game = game
        self.name = name
        self.steps: list[Step] = list(SCRIPTS[name](game))
        self.t = 0.0
        self.next_at = 0.0
        self.log: list[str] = []
        self.out = SCREENSHOT_DIR / "autotest"
        self.out.mkdir(parents=True, exist_ok=True)
        self.released: list[tuple[float, str]] = []
        self.failures = 0
        self._until_start: float | None = None
        if game.match is not None:
            game.match.cam.edge_scroll = False   # the OS cursor may rest on a window edge during tests

    def say(self, msg: str) -> None:
        print(f"[autotest] {msg}", flush=True)
        self.log.append(msg)

    def update(self, dt: float) -> None:
        self.t += dt
        for at, key in list(self.released):
            if self.t >= at:
                held_keys[key] = 0
                self.released.remove((at, key))
        while self.steps and self.t >= self.next_at:
            step = self.steps.pop(0)
            try:
                self._run(step)
            except Exception:
                self.failures += 1
                self.say("STEP FAILED " + repr(step[:1]) + "\n" + traceback.format_exc())

    def _run(self, step: Step) -> None:
        g = self.game
        m = g.match
        op = step[0]
        if op == "wait":
            self.next_at = self.t + step[1]
        elif op == "until":
            pred, timeout = step[1], step[2]
            if self._until_start is None:
                self._until_start = self.t
            if not pred(g) and self.t - self._until_start < timeout:
                self.steps.insert(0, step)
                self.next_at = self.t + 0.25
            else:
                waited = self.t - self._until_start
                self._until_start = None
                if len(step) > 3:
                    self.say(f"until '{step[3]}' after {waited:.1f}s")
        elif op == "time":
            m.env.hour = float(step[1])
        elif op == "cam":
            m.cam.look_at(step[1], step[2])
            if len(step) > 3:
                m.cam.distance = m.cam.target_distance = step[3]
            m.cam.pitch_override = step[4] if len(step) > 4 else None
            m.cam.apply()
        elif op == "shot":
            path = self.out / f"{step[1]}.png"
            application.base.win.saveScreenshot(Filename.fromOsSpecific(str(path)))
            self.say(f"screenshot {path.name}")
        elif op == "hold":
            held_keys[step[1]] = 1
            self.released.append((self.t + step[2], step[1]))
        elif op == "press":
            from ursina.main import keyboard_keys
            key = step[1]
            if len(key) == 1 and key in keyboard_keys:
                g.app.input(key, is_raw=True)
            else:
                g.app.input(key)
        elif op == "speed":
            g.fast_forward = float(step[1])
        elif op == "call":
            result = step[1](g)
            if result is not None:
                self.say(f"{step[2] if len(step) > 2 else 'call'}: {result}")
        elif op == "check":
            ok = bool(step[1](g))
            if not ok:
                self.failures += 1
            self.say(f"CHECK {'OK ' if ok else 'FAIL'} {step[2]}")
        elif op == "fps":
            self.say(f"avg fps: {g.average_fps():.1f}  sim+present ms: {g.average_sim_ms():.2f}  units: {len(m.units)}")
        elif op == "quit":
            self.say(f"finished with {self.failures} failure(s)")
            (self.out / f"{self.name}_log.json").write_text(json.dumps(self.log, indent=1), encoding="utf-8")
            application.quit()
        else:
            raise ValueError(f"unknown step {op}")


# ====================================================================== helpers
def _me(g):
    return g.match.players[0]


def _them(g):
    return g.match.players[1]


def _units(g, player=None, type_id: str | None = None) -> list:
    m = g.match
    return [u for u in m.units if u.alive and (player is None or u.owner is player) and (type_id is None or u.type_id == type_id)]


def _spawn(g, player, type_id: str, x: float, z: float, n: int = 1, cols: int = 6, spacing: float = 1.6) -> list:
    m = g.match
    out = []
    for k in range(n):
        r, c = divmod(k, cols)
        out.append(m.spawn_unit(player, type_id, x + (c - (cols - 1) / 2) * spacing, z + r * spacing))
    return out


def _all_near(units: list, x: float, z: float, r: float) -> bool:
    return all(math.hypot(u.x - x, u.z - z) <= r for u in units if u.alive)


def _select_box(g, x0=-2.0, y0=-0.6, x1=2.0, y1=0.6) -> list:
    units = g.controls.units_in_box(x0, y0, x1, y1)
    g.controls.set_selection(units)
    return units


# ====================================================================== scripts
def _m1(g) -> list[Step]:
    st: dict[str, Any] = {}

    def group_move(g):
        m = g.match
        sel = list(m.selection)
        st["sel"] = sel
        m.order_units(sel, "move", -40, -40)

    def make_army(g):
        m = g.match
        me = _me(g)
        st["army"] = _spawn(g, me, "spearman", -60, -40, 12) + _spawn(g, me, "longbowman", -60, -34, 12) + \
            _spawn(g, me, "knight", -60, -28, 6, spacing=2.4)
        return len(st["army"])

    def showcase(g):
        m = g.match
        me, them = _me(g), _them(g)
        xs = -30.0
        for i, t in enumerate(["peasant", "spearman", "longbowman", "forest_warden", "knight", "loremaster", "trebuchet", "skyhawk_rider"]):
            u = m.spawn_unit(me, t, xs + i * 3.2, -66)
            u.yaw = 180
        for i, t in enumerate(["thrall", "brute", "shade_archer", "dreadhound_rider", "stone_ogre", "pyre_witch", "war_catapult", "carrion_drake"]):
            u = m.spawn_unit(them, t, xs + i * 3.2, -72)
            u.yaw = 180

    return [
        ("wait", 1.5), ("time", 10.0),
        ("call", lambda g: (len(g.match.units), len(g.match.buildings), len(g.match.map.forest.trees), len(g.match.map.mines)),
         "units / buildings / trees / mines"),
        ("check", lambda g: len(_units(g, _me(g))) == 5, "5 starting workers"),
        ("shot", "m1_01_start"),
        ("cam", -76, -82, 30), ("wait", 0.5), ("shot", "m1_02_base_close"),
        ("call", lambda g: g.match.order_units(_units(g, _me(g)), "stop")), ("wait", 0.3),
        ("cam", -82, -76, 46), ("wait", 0.2),
        ("call", lambda g: len(_select_box(g)), "box-selected"),
        ("check", lambda g: len(g.match.selection) == 5 and all(u.is_worker for u in g.match.selection), "box selects the 5 workers"),
        ("call", group_move),
        ("wait", 0.5), ("cam", -58, -60, 46), ("wait", 0.8), ("shot", "m1_03_workers_moving"),
        ("until", lambda g: _all_near(st["sel"], -40, -40, 7), 25, "workers reach (-40,-40) via the ramp"),
        ("check", lambda g: _all_near(st["sel"], -40, -40, 7), "workers walked down the ramp to (-40,-40)"),
        ("call", lambda g: [(round(u.x, 1), round(u.z, 1)) for u in st["sel"]], "positions"),
        # cross the river at the central ford
        ("call", lambda g: g.match.order_units(st["sel"], "move", 30, 30)),
        ("until", lambda g: _all_near(st["sel"], 30, 30, 7), 30, "workers cross the ford"),
        ("check", lambda g: _all_near(st["sel"], 30, 30, 7), "workers crossed the river at the ford"),
        ("cam", 4, 0, 40), ("wait", 0.4), ("shot", "m1_04_ford"),
        # a route that must path around the river through a ford
        ("call", lambda g: g.match.order_units(st["sel"], "move", 60, -78)),
        ("until", lambda g: _all_near(st["sel"], 60, -78, 8), 40, "workers route around to (60,-78)"),
        ("check", lambda g: _all_near(st["sel"], 60, -78, 8), "pathing around the river works"),
        # army formation move
        ("call", make_army, "army size"),
        ("call", lambda g: g.controls.set_selection(st["army"])),
        ("cam", -50, -44, 50), ("wait", 0.5),
        ("call", lambda g: g.match.order_units(st["army"], "move", -10, 20)),
        ("wait", 2.5), ("shot", "m1_05_army_marching"),
        ("until", lambda g: _all_near(st["army"], -10, 20, 14), 30, "army arrives"),
        ("check", lambda g: _all_near(st["army"], -10, 20, 14), "army of 30 arrived in formation"),
        ("cam", -10, 14, 36), ("wait", 0.5), ("shot", "m1_06_army_formation"),
        # camera pan with arrow keys
        ("call", lambda g: st.update(fx=g.match.cam.fx)),
        ("hold", "right arrow", 1.0), ("wait", 1.2),
        ("check", lambda g: g.match.cam.fx > st["fx"] + 10, "arrow keys pan the camera"),
        # models showcase
        ("call", showcase),
        ("cam", -19, -74, 22, 40), ("time", 11.0), ("wait", 1.5), ("shot", "m1_07_models"),
        ("cam", -19, -74, 22, 40), ("time", 22.5), ("wait", 0.5), ("shot", "m1_08_models_night"),
        ("time", 10.0), ("cam", 0, 0, 78), ("wait", 0.5), ("shot", "m1_09_overview_center"),
        ("cam", 76, 76, 50), ("wait", 0.5), ("shot", "m1_10_enemy_base"),
        ("cam", -10, 20, 50), ("wait", 2.0), ("fps",),
        ("quit",),
    ]


def _m1b(g) -> list[Step]:
    st: dict[str, Any] = {}

    def army(g):
        me = _me(g)
        st["army"] = _spawn(g, me, "brute", 0, -60, 18) + _spawn(g, me, "shade_archer", 0, -52, 12)
        g.match.order_units(st["army"], "move", 0, 60)

    return [
        ("wait", 1.5), ("time", 17.0),
        ("shot", "m1b_01_start"),
        ("call", army),
        ("cam", 0, -30, 60), ("wait", 4.0), ("shot", "m1b_02_marching"),
        ("until", lambda g: _all_near(st["army"], 0, 60, 14), 45, "army reaches the enemy plateau"),
        ("check", lambda g: _all_near(st["army"], 0, 60, 14), "army crossed the pass to the north plateau"),
        ("cam", 0, 0, 78), ("wait", 0.5), ("shot", "m1b_03_center"),
        ("call", lambda g: g.match.order_units(st["army"][:10], "move", -76, 0)),
        ("until", lambda g: _all_near(st["army"][:10], -76, 0, 10), 45, "squad takes the west trail"),
        ("check", lambda g: _all_near(st["army"][:10], -76, 0, 10), "west side trail is walkable"),
        ("cam", -70, 0, 50), ("wait", 0.5), ("shot", "m1b_04_west_trail"),
        ("time", 21.0), ("cam", 0, -86, 46), ("wait", 0.8), ("shot", "m1b_05_base_dusk"),
        ("fps",), ("quit",),
    ]


def _m2(g) -> list[Step]:
    st: dict[str, Any] = {}

    def melee(g):
        me, them = _me(g), _them(g)
        st["a"] = _spawn(g, me, "spearman", -10, -20, 10, cols=5)
        st["b"] = _spawn(g, them, "brute", -10, 0, 10, cols=5)
        g.match.order_units(st["a"], "attack_move", -10, 10)
        g.match.order_units(st["b"], "attack_move", -10, -30)
        g.controls.set_selection(st["a"])

    def dmg_table(g):
        m = g.match
        me, them = _me(g), _them(g)
        sp = m.spawn_unit(me, "spearman", 60, -80)
        br = m.spawn_unit(them, "brute", 62, -80)
        lb = m.spawn_unit(me, "longbowman", 64, -80)
        m.env.hour = 12.0
        day = (m.combat.damage_value(sp, br), m.combat.damage_value(lb, br), m.combat.damage_value(br, sp))
        m.env.hour = 23.0
        night = (m.combat.damage_value(sp, br), m.combat.damage_value(lb, br), m.combat.damage_value(br, sp))
        m.env.hour = 12.0
        for u in (sp, br, lb):
            m.kill(u, None)
        st["day"], st["night"] = day, night
        return {"day spear>brute, bow>brute, brute>spear": day, "night": night}

    def ranged(g):
        me, them = _me(g), _them(g)
        st["bows"] = _spawn(g, me, "longbowman", 30, -40, 8, cols=4)
        st["ogres"] = _spawn(g, them, "stone_ogre", 30, -16, 2, cols=2, spacing=3.0)
        g.match.order_units(st["ogres"], "attack_move", 30, -45)

    def siege(g):
        m = g.match
        me, them = _me(g), _them(g)
        st["camp"] = m.spawn_building(them, "war_camp", -60, 20, complete=True)
        st["treb"] = m.spawn_unit(me, "trebuchet", -60, -4)
        st["camp_hp0"] = st["camp"].hp
        m.order_units([st["treb"]], "attack", target=st["camp"])

    def air(g):
        me, them = _me(g), _them(g)
        st["hawks"] = _spawn(g, me, "skyhawk_rider", 60, 0, 4, cols=4, spacing=3)
        st["drakes"] = _spawn(g, them, "carrion_drake", 60, 24, 4, cols=4, spacing=3)
        st["arch"] = _spawn(g, them, "shade_archer", 60, 30, 4, cols=4)
        g.match.order_units(st["hawks"], "attack_move", 60, 30)

    def tower(g):
        m = g.match
        me, them = _me(g), _them(g)
        st["tower"] = m.spawn_building(me, "guard_tower", -30, 50, complete=True)
        st["raiders"] = _spawn(g, them, "dreadhound_rider", -30, 70, 3, cols=3, spacing=2.5)
        m.order_units(st["raiders"], "attack", target=st["tower"])

    def casters(g):
        m = g.match
        me, them = _me(g), _them(g)
        st["lm"] = m.spawn_unit(me, "loremaster", 80, -60)
        st["hurt"] = _spawn(g, me, "spearman", 82, -60, 3, cols=3)
        for u in st["hurt"]:
            u.hp = 60
        st["lm"].mana = 150
        st["pw"] = m.spawn_unit(them, "pyre_witch", 80, -40)
        st["pw"].mana = 150
        st["victims"] = _spawn(g, me, "longbowman", 80, -50, 6, cols=3, spacing=1.2)
        for v in st["victims"]:
            v.command(__import__("core.actor", fromlist=["Order"]).Order("hold"))

    return [
        ("wait", 1.0), ("time", 12.0),
        ("call", dmg_table, "damage"),
        ("check", lambda g: st["day"][0] > st["night"][0] and st["night"][2] > st["day"][2], "day favours Alliance, night favours Host"),
        ("check", lambda g: st["day"][1] < st["day"][0] * 1.0, "pierce does less vs heavy armour"),
        ("call", melee), ("cam", -10, -16, 34), ("wait", 3.5), ("shot", "m2_01_melee_clash"),
        ("until", lambda g: not any(u.alive for u in st["a"]) or not any(u.alive for u in st["b"]), 60, "melee resolved"),
        ("call", lambda g: (sum(u.alive for u in st["a"]), sum(u.alive for u in st["b"])), "survivors spear/brute"),
        ("check", lambda g: not any(u.alive for u in st["a"]) or not any(u.alive for u in st["b"]), "melee fight ends with a winner"),
        ("call", ranged), ("cam", 30, -34, 34), ("wait", 4.0), ("shot", "m2_02_archers_vs_ogres"),
        ("until", lambda g: not any(u.alive for u in st["bows"]) or not any(u.alive for u in st["ogres"]), 60, "ranged fight resolved"),
        ("call", lambda g: (sum(u.alive for u in st["bows"]), sum(u.alive for u in st["ogres"])), "survivors bows/ogres"),
        ("call", siege), ("cam", -60, 4, 40), ("wait", 6.0), ("shot", "m2_03_trebuchet"),
        ("wait", 8.0),
        ("check", lambda g: st["camp"].hp < st["camp_hp0"], "trebuchet damages the war camp"),
        ("call", lambda g: (round(st["camp_hp0"]), round(st["camp"].hp)), "camp hp before/after"),
        ("call", air), ("cam", 60, 14, 40), ("wait", 4.0), ("shot", "m2_04_air_battle"),
        ("until", lambda g: not any(u.alive for u in st["hawks"]) or not any(u.alive for u in st["drakes"] + st["arch"]), 60, "air fight"),
        ("call", lambda g: (sum(u.alive for u in st["hawks"]), sum(u.alive for u in st["drakes"]), sum(u.alive for u in st["arch"])), "hawks/drakes/archers"),
        ("call", tower), ("cam", -30, 56, 36), ("wait", 4.0), ("shot", "m2_05_tower"),
        ("until", lambda g: not st["tower"].alive or not any(u.alive for u in st["raiders"]), 60, "tower fight"),
        ("call", lambda g: (st["tower"].alive, round(st["tower"].hp), sum(u.alive for u in st["raiders"])), "tower alive/hp, raiders"),
        ("call", casters), ("cam", 80, -54, 30), ("wait", 3.0), ("shot", "m2_06_casters"),
        ("check", lambda g: any(u.hp > 60 for u in st["hurt"]), "Loremaster auto-heals wounded spearmen"),
        ("wait", 4.0),
        ("check", lambda g: st["pw"].mana < 150 or not st["pw"].alive, "AI Pyre Witch casts (fireball / frenzy)"),
        ("call", lambda g: (round(st["pw"].mana), [round(v.hp) for v in st["victims"]]), "witch mana, victims hp"),
        ("fps",), ("quit",),
    ]


def _perf(g) -> list[Step]:
    st: dict[str, Any] = {}

    def armies(g):
        me, them = _me(g), _them(g)
        a = _spawn(g, me, "spearman", -30, -30, 60, cols=10) + _spawn(g, me, "longbowman", -30, -45, 50, cols=10) + \
            _spawn(g, me, "knight", -30, -60, 20, cols=10, spacing=2.4)
        b = _spawn(g, them, "brute", 30, 30, 60, cols=10) + _spawn(g, them, "shade_archer", 30, 45, 50, cols=10) + \
            _spawn(g, them, "dreadhound_rider", 30, 60, 20, cols=10, spacing=2.4)
        st["a"], st["b"] = a, b
        g.match.order_units(a, "attack_move", 20, 20)
        g.match.order_units(b, "attack_move", -20, -20)

    return [
        ("wait", 1.0), ("time", 12.0), ("call", armies), ("cam", 0, -6, 60), ("wait", 6.0), ("fps",), ("shot", "perf_01"),
        ("wait", 6.0), ("fps",), ("shot", "perf_02"),
        ("call", lambda g: (len(_units(g, _me(g))), len(_units(g, _them(g)))), "alive a/b"),
        ("quit",),
    ]


CONFIGS: dict[str, dict[str, Any]] = {
    "m1": {"map": "greyfen_crossing", "fog": False},
    "m1b": {"map": "shadowed_pass", "me": "host", "them": "alliance", "fog": False},
    "perf": {"map": "greyfen_crossing", "fog": False},
    "m2": {"map": "greyfen_crossing", "fog": False},
}

SCRIPTS: dict[str, Callable[[Any], list[Step]]] = {
    "m1": _m1,
    "m1b": _m1b,
    "perf": _perf,
    "m2": _m2,
}


def _m3(g) -> list[Step]:
    st: dict[str, Any] = {}

    def start(g):
        m = g.match
        me = _me(g)
        workers = _units(g, me, "peasant")
        st["miners"] = workers[:3]
        st["choppers"] = workers[3:]
        tree = m.economy.find_tree(workers[3], (-100, -96))
        st["tree"] = tree
        m.economy.order_gather(st["choppers"], tree)
        me.gold += 2000
        me.timber += 2000
        st["g0"], st["t0"] = me.gold, me.timber
        return (round(tree.x), round(tree.z)) if tree else None

    def find_site(g, player, btype, near):
        m = g.match
        for r in range(0, 30, 2):
            for a in range(0, 360, 30):
                x = near[0] + math.cos(math.radians(a)) * r
                z = near[1] + math.sin(math.radians(a)) * r
                if m.economy.can_place(player, btype, x, z)[0]:
                    return x, z
        return None

    def build_house(g):
        m = g.match
        me = _me(g)
        w = st["miners"][0]
        st["cap0"] = me.supply_cap
        site = find_site(g, me, "house", (-62, -88))
        return m.economy.order_build(w, "house", *site), site

    def build_barracks(g):
        m = g.match
        me = _me(g)
        site = find_site(g, me, "barracks", (-60, -68))
        return m.economy.order_build(st["miners"][1], "barracks", *site), site

    def rax(g):
        return next((b for b in g.match.buildings if b.type_id == "barracks" and b.owner is _me(g)), None)

    def train(g):
        b = rax(g)
        b.rally = (-50, -50)
        return [b.enqueue_unit("spearman"), b.enqueue_unit("longbowman"), b.enqueue_unit("forest_warden")]

    def host_build(g):
        m = g.match
        them = _them(g)
        them.gold += 1000
        them.timber += 1000
        th = _units(g, them, "thrall")[0]
        st["thrall"] = th
        site = find_site(g, them, "war_camp", (64, 64))
        return m.economy.order_build(th, "war_camp", *site), site

    def camp(g):
        return next((b for b in g.match.buildings if b.type_id == "war_camp" and b.owner is _them(g)), None)

    def upgrade_keep(g):
        keep = next(b for b in g.match.buildings if b.type_id == "keep")
        st["keep"] = keep
        return keep.enqueue_research("castle_upgrade")

    def smith(g):
        m = g.match
        me = _me(g)
        site = find_site(g, me, "blacksmith", (-50, -88))
        b = m.spawn_building(me, "blacksmith", *site, complete=True)
        st["smith"] = b
        sp = m.spawn_unit(me, "spearman", -50, -60)
        st["sp"] = sp
        st["bonus0"] = me.damage_bonus(sp.defn)
        return b.enqueue_research("alliance_weapons_1")

    def chop_out(g):
        t = st["tree"]
        f = g.match.map.forest
        st["tree_cell"] = t.cell
        f.harvest(t, 10000)
        return t.alive, bool(g.match.grid.walk[t.cell])

    def deplete_mine(g):
        mine = g.match.map.mine_near(-94, -62, 10)
        st["mine"] = mine
        mine.gold = 16
        return mine.gold

    def supply_block(g):
        me = _me(g)
        me.supply_used = me.supply_max
        b = rax(g)
        st["n_units"] = len(_units(g, me))
        return b.enqueue_unit("spearman")

    def thrall_free(g):
        t = st["thrall"]
        return camp(g) is not None and (t.order is None or t.order.kind != "build")

    return [
        ("wait", 1.0), ("time", 10.0), ("call", start, "chopping tree"),
        ("cam", -82, -80, 46), ("wait", 6.0), ("shot", "m3_01_gathering"),
        ("wait", 24.0),
        ("call", lambda g: (_me(g).gold - st["g0"], _me(g).timber - st["t0"]), "gold/timber gathered in 30s"),
        ("check", lambda g: _me(g).gold - st["g0"] >= 40, "workers mine gold"),
        ("check", lambda g: _me(g).timber - st["t0"] >= 8, "workers chop timber"),
        ("call", build_house, "house order"),
        ("call", build_barracks, "barracks order"),
        ("wait", 8.0), ("cam", -62, -84, 40), ("shot", "m3_02_construction"),
        ("call", lambda g: [(round(u.x, 1), round(u.z, 1), u.order.kind if u.order else None, u.order.data if u.order else None,
                             u.goal, u.path_pending, len(u.path), u.path_i) for u in st["miners"][:2]], "builders"),
        ("until", lambda g: any(b.type_id == "house" and b.complete for b in g.match.buildings), 60, "house built"),
        ("check", lambda g: _me(g).supply_cap == st["cap0"] + 10, "house adds 10 supply"),
        ("until", lambda g: rax(g) is not None and rax(g).complete, 70, "barracks built"),
        ("check", lambda g: rax(g) is not None and rax(g).complete, "barracks completed by the peasant"),
        ("call", train, "train errors"),
        ("check", lambda g: len(rax(g).queue) == 2, "warden needs a lumber mill (only 2 queued)"),
        ("until", lambda g: len(_units(g, _me(g), "longbowman")) >= 1, 50, "units trained"),
        ("check", lambda g: len(_units(g, _me(g), "spearman")) >= 1 and len(_units(g, _me(g), "longbowman")) >= 1,
         "spearman and longbowman trained"),
        ("call", host_build, "host build order"),
        ("until", lambda g: camp(g) is not None, 30, "camp summoned"), ("wait", 1.0),
        ("check", thrall_free, "thrall summons the war camp and walks away"),
        ("cam", 64, 60, 40), ("wait", 1.0), ("shot", "m3_03_host_summon"),
        ("until", lambda g: camp(g) is not None and camp(g).complete, 60, "war camp raised itself"),
        ("check", lambda g: camp(g) is not None and camp(g).complete, "Host building completes on its own"),
        ("call", upgrade_keep, "keep upgrade"),
        ("until", lambda g: st["keep"].type_id == "castle", 70, "castle upgrade"),
        ("check", lambda g: _me(g).tier == 2, "keep upgraded to castle (tier 2)"),
        ("cam", -76, -82, 46), ("wait", 0.5), ("shot", "m3_04_castle"),
        ("call", smith, "research"),
        ("until", lambda g: "alliance_weapons_1" in _me(g).upgrades, 60, "weapons research"),
        ("check", lambda g: _me(g).damage_bonus(st["sp"].defn) == st["bonus0"] + 1, "Forged Blades I adds +1 damage"),
        ("call", chop_out, "tree alive / cell walkable"),
        ("check", lambda g: not st["tree"].alive and g.match.grid.walk[st["tree_cell"]], "depleted tree is removed and unblocked"),
        ("call", deplete_mine), ("until", lambda g: st["mine"].depleted, 30, "mine depleted"),
        ("wait", 0.5),
        ("check", lambda g: st["mine"].depleted and not st["mine"].alive, "gold mine collapses when empty"),
        ("call", supply_block, "queue while supply-capped"),
        ("wait", 20.0),
        ("check", lambda g: len(_units(g, _me(g))) == st["n_units"], "supply cap blocks training"),
        ("cam", -60, -72, 50), ("wait", 0.5), ("shot", "m3_05_base"),
        ("fps",), ("quit",),
    ]


SCRIPTS["m3"] = _m3
CONFIGS["m3"] = {"map": "greyfen_crossing", "fog": False}


def _ai_report(g) -> str:
    m = g.match
    out = []
    for p in m.players:
        units = [u for u in m.units if u.alive and u.owner is p]
        workers = sum(1 for u in units if u.is_worker)
        blds = [b for b in m.buildings if b.alive and b.owner is p]
        ai = next((a for a in m.ais if a.p is p), None)
        types: dict[str, int] = {}
        for u in units:
            if not u.is_worker:
                types[u.type_id] = types.get(u.type_id, 0) + 1
        out.append(f"{p.faction}: mined {p.stats['gold_mined']}/{p.stats['timber_cut']} g{p.gold} t{p.timber} sup {p.supply_used}/{p.supply_max} w{workers} army{len(units) - workers} "
                   f"bld{len(blds)} step{ai.step if ai else '-'}/{len(ai.order) if ai else '-'} {ai.state if ai else ''} "
                   f"waves{ai.waves_sent if ai else 0} tier{p.tier} ups{len(p.upgrades)} {types}")
    return f"t={int(m.time)}s | " + " || ".join(out)


def _aivai(g) -> list[Step]:
    steps: list[Step] = [("wait", 0.5), ("speed", 6.0)]
    for k in range(1, 31):
        steps += [("until", lambda g, k=k: g.match.time >= k * 60 or g.match.over, 600),
                  ("call", _ai_report, "ai")]
        if k in (4, 8, 12, 16):
            steps += [("call", lambda g: _cam_on_action(g)), ("wait", 0.3), ("shot", f"ai_{k:02d}min")]
        steps += [("call", lambda g: "MATCH OVER" if g.match.over else None, "state")]
    steps += [("call", lambda g: (g.match.over, g.match.winner.faction if g.match.winner else None, int(g.match.time)), "result"),
              ("fps",), ("quit",)]
    return steps


def _cam_on_action(g) -> None:
    m = g.match
    fighting = [u for u in m.units if u.alive and u.target is not None and not u.is_worker]
    if fighting:
        x = sum(u.x for u in fighting) / len(fighting)
        z = sum(u.z for u in fighting) / len(fighting)
    else:
        b = m.buildings[-1] if m.buildings else None
        x, z = (b.x, b.z) if b else (0, 0)
    m.cam.look_at(x, z - 6)
    m.cam.distance = m.cam.target_distance = 58


SCRIPTS["aivai"] = _aivai
CONFIGS["aivai"] = {"map": "greyfen_crossing", "me": "alliance", "them": "host", "me_ai": True, "spectate": True, "fog": True,
                    "ai": True, "diff": "normal"}
SCRIPTS["aivai2"] = _aivai
CONFIGS["aivai2"] = {"map": "shadowed_pass", "me": "host", "them": "alliance", "me_ai": True, "spectate": True, "fog": True,
                     "ai": True, "diff": "hard", "seed": 7}


BAL_MIXES = {
    "t1": {"alliance": {"spearman": 4, "longbowman": 4, "forest_warden": 1},
           "host": {"brute": 5, "shade_archer": 3, "dreadhound_rider": 2}},
    "t2": {"alliance": {"spearman": 3, "longbowman": 3, "knight": 3, "loremaster": 1, "trebuchet": 1, "skyhawk_rider": 1},
           "host": {"brute": 4, "shade_archer": 3, "dreadhound_rider": 3, "stone_ogre": 2, "pyre_witch": 1, "war_catapult": 1, "carrion_drake": 1}},
}


def _value(ud) -> int:
    c = ud["cost"]
    return c.get("gold", 0) + c.get("timber", 0)


def _army_for(faction: str, mix: dict[str, int], budget: int) -> list[str]:
    """Spend ``budget`` (gold+timber) following the mix weights."""
    from core import data as _d
    units = _d.units()
    out: list[str] = []
    counts = {k: 0 for k in mix}
    spent = 0
    while True:
        tid = min(mix, key=lambda k: (counts[k] + 1) / mix[k])
        v = _value(units[tid])
        if spent + v > budget:
            break
        out.append(tid)
        counts[tid] += 1
        spent += v
    return out


def _balance(g) -> list[Step]:
    results: list[tuple] = []
    st: dict[str, Any] = {}

    def setup(g, tier, hour, flip):
        from core import data as _d
        m = g.match
        for u in list(m.units):
            if u.alive:
                m.kill(u, None)
        m.env.hour = hour
        al, ho = m.players[0], m.players[1]
        budget = 1600 if tier == "t1" else 3200
        a_types = _army_for("alliance", BAL_MIXES[tier]["alliance"], budget)
        h_types = _army_for("host", BAL_MIXES[tier]["host"], budget)
        ya, yh = (-14, 14) if not flip else (14, -14)
        a_units, h_units = [], []
        for k, t in enumerate(a_types):
            r, c = divmod(k, 8)
            a_units.append(m.spawn_unit(al, t, -12 + (c - 3.5) * 2.2 + 20, ya - r * 2.2 * (1 if ya < 0 else -1) - 30))
        for k, t in enumerate(h_types):
            r, c = divmod(k, 8)
            h_units.append(m.spawn_unit(ho, t, -12 + (c - 3.5) * 2.2 + 20, yh + r * 2.2 * (1 if yh > 0 else -1) - 30))
        for u in a_units + h_units:
            if u.max_mana:
                u.mana = u.max_mana
        m.order_units(a_units, "attack_move", 8, yh - 30)
        m.order_units(h_units, "attack_move", 8, ya - 30)
        st.update(a=a_units, h=h_units, tier=tier, hour=hour, t0=m.time)

    def record(g):
        from core import data as _d
        units = _d.units()
        av = sum(_value(units[u.type_id]) * u.hp_frac for u in st["a"] if u.alive)
        hv = sum(_value(units[u.type_id]) * u.hp_frac for u in st["h"] if u.alive)
        a0 = sum(_value(units[u.type_id]) for u in st["a"])
        h0 = sum(_value(units[u.type_id]) for u in st["h"])
        res = (st["tier"], "night" if st["hour"] > 19 else "day", f"A {len(st['a'])}u {a0} -> {int(av)}",
               f"H {len(st['h'])}u {h0} -> {int(hv)}", "ALLIANCE" if av > hv else "HOST", round(g.match.time - st["t0"]))
        results.append(res)
        return res

    def done(g):
        return not any(u.alive for u in st["a"]) or not any(u.alive for u in st["h"]) or g.match.time - st["t0"] > 100

    steps: list[Step] = [("wait", 0.5), ("speed", 6.0)]
    for tier in ("t1", "t2"):
        for hour in (12.0, 23.0):
            for flip in (False, True):
                steps += [("call", lambda g, t=tier, h=hour, f=flip: setup(g, t, h, f)), ("wait", 0.2),
                          ("until", done, 200), ("call", record, "battle")]
    steps += [("call", lambda g: sum(1 for r in results if r[4] == "ALLIANCE"), "alliance wins of 8"), ("quit",)]
    return steps


SCRIPTS["balance"] = _balance
CONFIGS["balance"] = {"map": "greyfen_crossing", "fog": False, "seed": 3, "me_ai": True}
SCRIPTS["aivai3"] = _aivai
CONFIGS["aivai3"] = {"map": "greyfen_crossing", "me": "host", "them": "alliance", "me_ai": True, "spectate": True, "fog": True,
                     "ai": True, "diff": "hard", "seed": 11}
SCRIPTS["aivai4"] = _aivai
CONFIGS["aivai4"] = {"map": "shadowed_pass", "me": "alliance", "them": "host", "me_ai": True, "spectate": True, "fog": True,
                     "ai": True, "diff": "normal", "seed": 5}


def _m6(g) -> list[Step]:
    st: dict[str, Any] = {}

    def hidden_enemies(g):
        m = g.match
        en = [u for u in m.units if u.alive and u.owner is not m.human]
        vis = [u for u in en if u.visible]
        return len(en), len(vis)

    def scout(g):
        m = g.match
        me = _me(g)
        st["w"] = _spawn(g, me, "forest_warden", -60, -60, 1)[0]
        m.order_units([st["w"]], "move", 70, 70)
        st["explored0"] = int(m.fog.explored[0].sum())

    return [
        ("wait", 1.0), ("time", 11.0),
        ("cam", -76, -82, 52), ("wait", 0.8), ("shot", "m6_01_fog_base"),
        ("call", hidden_enemies, "enemies total/visible"),
        ("check", lambda g: hidden_enemies(g)[1] == 0, "enemy base is hidden by fog at start"),
        ("check", lambda g: g.match.fog.visible[0][g.match.grid.cell_of(-76, -76) // g.match.grid.w,
                                                   g.match.grid.cell_of(-76, -76) % g.match.grid.w], "own base is visible"),
        ("call", scout), ("speed", 4.0),
        ("until", lambda g: math.hypot(st["w"].x - 70, st["w"].z - 70) < 8 or not st["w"].alive, 60, "scout arrives"),
        ("speed", 1.0),
        ("call", hidden_enemies, "enemies total/visible near their base"),
        ("check", lambda g: hidden_enemies(g)[1] > 0 or not st["w"].alive, "scout reveals enemy units"),
        ("check", lambda g: int(g.match.fog.explored[0].sum()) > st["explored0"] + 300, "exploring grows the explored area"),
        ("cam", 60, 54, 52), ("wait", 0.6), ("shot", "m6_02_scouting_enemy"),
        ("call", lambda g: g.match.order_units([st["w"]], "move", -60, -60) if st["w"].alive else None),
        ("speed", 4.0), ("wait", 6.0), ("speed", 1.0),
        ("call", lambda g: [(b.type_id, b.remembered, b.visible) for b in g.match.buildings if b.owner is _them(g)][:4],
         "remembered enemy buildings"),
        ("check", lambda g: any(b.remembered and not b.visible for b in g.match.buildings if b.owner is _them(g)),
         "seen enemy buildings stay remembered under fog"),
        ("cam", 60, 54, 52), ("wait", 0.6), ("shot", "m6_03_remembered"),
        ("time", 21.5), ("cam", -76, -82, 52), ("wait", 0.8), ("shot", "m6_04_night_fog"),
        ("call", lambda g: (g.match.ais[0].p.faction, len(g.match.ais[0].known)), "AI knowledge (known enemy buildings)"),
        ("fps",), ("quit",),
    ]


SCRIPTS["m6"] = _m6
CONFIGS["m6"] = {"map": "greyfen_crossing", "fog": True, "ai": True, "diff": "normal"}


def _m7(g) -> list[Step]:
    st: dict[str, Any] = {}

    def pick(g, **kw):
        g.menus.cfg.update(kw)
        g.menus._refresh_skirmish()

    def select_worker(g):
        m = g.match
        w = [u for u in m.units if u.alive and u.owner is m.human and u.is_worker][0]
        w.stop()
        g.controls.set_selection([w])
        st["w"] = w
        return w.type_id

    def select_hall(g):
        m = g.match
        h = [b for b in m.buildings if b.owner is m.human and b.town_hall][0]
        g.controls.set_selection([h])
        st["hall"] = h
        return h.type_id

    def win(g):
        m = g.match
        for b in list(m.buildings):
            if b.alive and b.owner is not m.human:
                m.kill(b, None)

    return [
        ("wait", 2.5), ("shot", "m7_01_main_menu"),
        ("check", lambda g: g.state == "menu" and g.menus.current is g.menus.main, "main menu shown"),
        ("call", lambda g: g.menus.show_skirmish()), ("wait", 0.4),
        ("call", lambda g: pick(g, map="shadowed_pass", faction="host", enemy="alliance", difficulty="easy")),
        ("wait", 0.3), ("shot", "m7_02_skirmish_setup"),
        ("call", lambda g: g.menus.start_skirmish()), ("wait", 2.5),
        ("check", lambda g: g.state == "playing" and g.match.human is not None and g.match.human.faction == "host", "skirmish started as Host"),
        ("check", lambda g: g.match.map.id == "shadowed_pass" and g.match.ais and g.match.ais[0].diff == "easy", "map / AI difficulty applied"),
        ("call", lambda g: setattr(g.match.cam, "edge_scroll", False)),
        ("shot", "m7_03_ingame"),
        ("press", "escape"), ("wait", 0.3),
        ("check", lambda g: g.paused and g.menus.current is g.menus.pause, "Esc opens the pause menu"),
        ("shot", "m7_04_pause"),
        ("call", lambda g: g.menus.show_settings(g.menus.show_pause)), ("wait", 0.3), ("shot", "m7_05_settings"),
        ("press", "escape"), ("wait", 0.2),
        ("check", lambda g: g.menus.current is g.menus.pause, "Esc returns from settings"),
        ("call", lambda g: g.menus.show_help(g.menus.show_pause)), ("wait", 0.3), ("shot", "m7_06_help"),
        ("press", "escape"), ("press", "escape"), ("wait", 0.2),
        ("check", lambda g: not g.paused and g.menus.current is None, "resumed"),
        ("call", select_worker, "selected"), ("wait", 0.3),
        ("press", "b"), ("wait", 0.3),
        ("check", lambda g: g.hud.card.menu == "build", "B opens the build menu"),
        ("shot", "m7_07_build_menu"),
        ("press", "w"), ("wait", 0.4),
        ("check", lambda g: g.controls.mode == "build" and g.controls.mode_arg == "warren", "W picks the Warren for placement"),
        ("shot", "m7_08_placement"),
        ("press", "escape"), ("wait", 0.2),
        ("check", lambda g: g.controls.mode is None, "Esc cancels placement"),
        ("press", "escape"), ("wait", 0.2),
        ("call", select_hall, "selected"), ("wait", 0.3),
        ("call", lambda g: st.update(n=len(st["hall"].queue))),
        ("press", "q"), ("wait", 0.3),
        ("check", lambda g: len(st["hall"].queue) == st["n"] + 1, "Q trains a thrall at the Pit"),
        ("shot", "m7_09_training"),
        ("call", lambda g: g.menus.show_pause()), ("call", lambda g: g.menus.surrender()),
        ("wait", 3.5), ("shot", "m7_10_defeat"),
        ("check", lambda g: g.menus.current is g.menus.end and "Defeat" in g.menus.end_title.text, "surrender shows the defeat screen"),
        ("call", lambda g: g.menus.quit_to_main()), ("wait", 1.5),
        ("check", lambda g: g.state == "menu" and g.menus.current is g.menus.main, "back to the main menu"),
        ("call", lambda g: pick(g, map="greyfen_crossing", faction="alliance", enemy="host", difficulty="normal")),
        ("call", lambda g: g.menus.start_skirmish()), ("wait", 2.0),
        ("call", lambda g: setattr(g.match.cam, "edge_scroll", False)),
        ("check", lambda g: g.state == "playing" and g.match.human.faction == "alliance", "second skirmish as Alliance"),
        ("call", win), ("wait", 4.0), ("shot", "m7_11_victory"),
        ("check", lambda g: g.menus.current is g.menus.end and "Victory" in g.menus.end_title.text, "destroying all enemy buildings wins"),
        ("fps",), ("quit",),
    ]


SCRIPTS["m7"] = _m7


def _cur(u):
    """Current order, or the queued one that starts on the next update."""
    return u.order or (u.orders[0] if u.orders else None)


def _input(g) -> list[Step]:
    st: dict[str, Any] = {}

    def setup(g):
        m = g.match
        me, them = _me(g), _them(g)
        st["army"] = _spawn(g, me, "spearman", -40, -40, 4, cols=4)
        st["enemy"] = m.spawn_unit(them, "brute", -40, -20)
        st["enemy"].command(__import__("core.actor", fromlist=["Order"]).Order("hold"))
        st["workers"] = _units(g, me, "peasant")
        for w in st["workers"]:
            w.stop()
        m.cam.look_at(-40, -36)
        m.cam.distance = m.cam.target_distance = 40
        m.cam.apply()

    def pick_unit(g):
        m = g.match
        u = st["army"][0]
        sx, sy = m.cam.project_one(u.x, u.y + u.height * 0.5, u.z)
        return g.controls.pick(sx, sy) is u

    def smart(g, target=None, ground=None, sel=None):
        c = g.controls
        c.set_selection(sel)
        c.pick = lambda *a, **k: target
        c.ground_point = lambda: ground
        c.smart_command(False)
        del c.pick
        del c.ground_point

    def rally(g):
        m = g.match
        hall = next(b for b in m.buildings if b.owner is _me(g) and b.town_hall)
        smart(g, None, (-60.0, -60.0), [hall])
        return hall.rally

    def group(g):
        c = g.controls
        c.set_selection(st["army"])
        held_keys["control"] = 1
        c.input("3")
        held_keys["control"] = 0
        c.set_selection([])
        c.input("3")
        return len(g.match.selection)

    return [
        ("wait", 1.0), ("call", setup), ("wait", 0.5),
        ("check", pick_unit, "clicking on a unit's screen position picks it"),
        ("call", lambda g: smart(g, None, (-30.0, -50.0), st["army"])),
        ("check", lambda g: all(_cur(u) is not None and _cur(u).kind == "move" for u in st["army"]), "right-click ground = move"),
        ("call", lambda g: smart(g, st["enemy"], None, st["army"])),
        ("check", lambda g: all(_cur(u) is not None and _cur(u).kind == "attack" and _cur(u).target is st["enemy"] for u in st["army"]),
         "right-click enemy = attack"),
        ("call", lambda g: smart(g, g.match.map.mine_near(-94, -62, 10), None, st["workers"])),
        ("check", lambda g: all(_cur(w) is not None and _cur(w).kind == "gather" for w in st["workers"]), "right-click mine with workers = gather"),
        ("call", lambda g: smart(g, None, (st["tree"].x, st["tree"].z), st["workers"][:2]) if st.update(
            tree=g.match.economy.find_tree(st["workers"][0], (-100, -96))) is None else None),
        ("check", lambda g: all(_cur(w).kind == "gather" and getattr(_cur(w).target, "is_tree", False) for w in st["workers"][:2]),
         "right-click tree with workers = chop"),
        ("call", rally, "rally"),
        ("check", lambda g: next(b for b in g.match.buildings if b.owner is _me(g) and b.town_hall).rally == (-60.0, -60.0),
         "right-click with a building selected sets the rally point"),
        ("call", group, "group 3 recalled"),
        ("check", lambda g: len(g.match.selection) == 4, "Ctrl+3 then 3 recalls the control group"),
        ("call", lambda g: (g.controls.set_selection(st["army"]), g.controls.input("h")) and None),
        ("check", lambda g: all(_cur(u) is not None and _cur(u).kind == "hold" for u in st["army"]), "H = hold position"),
        ("call", lambda g: g.controls.input("s")),
        ("check", lambda g: all(_cur(u) is None for u in st["army"]), "S = stop"),
        ("call", lambda g: g.controls.input("a")),
        ("check", lambda g: g.controls.mode == "attack", "A enters attack-move targeting"),
        ("call", lambda g: g.controls.cancel_mode()),
        ("quit",),
    ]


SCRIPTS["input"] = _input
CONFIGS["input"] = {"map": "greyfen_crossing", "fog": False}


def _showcase(g) -> list[Step]:
    st: dict[str, Any] = {"shots": 0}

    def look_base(g):
        m = g.match
        me = _me(g)
        hall = next((b for b in m.buildings if b.owner is me and b.town_hall), None)
        if hall is not None:
            m.cam.look_at(hall.x + 6, hall.z - 4)
            m.cam.distance = m.cam.target_distance = 50
        army = [u for u in m.units if u.alive and u.owner is me and not u.is_worker]
        g.controls.set_selection(army[:24])

    def fight_spot(g):
        m = g.match
        fighting = [u for u in m.units if u.alive and not u.is_worker and u.target is not None and u.target.alive
                    and u.dist_to(u.target) < 14]
        if len(fighting) < 8:
            return None
        x = sum(u.x for u in fighting) / len(fighting)
        z = sum(u.z for u in fighting) / len(fighting)
        return x, z

    def look_fight(g):
        p = fight_spot(g)
        if p is None:
            return False
        m = g.match
        m.cam.look_at(p[0], p[1] - 4)
        m.cam.distance = m.cam.target_distance = 42
        mine = [u for u in m.units if u.alive and u.owner is _me(g) and not u.is_worker and math.hypot(u.x - p[0], u.z - p[1]) < 20]
        g.controls.set_selection(mine[:24])
        return True

    return [
        ("wait", 0.5), ("speed", 6.0),
        ("until", lambda g: g.match.time > 400, 400), ("speed", 1.0),
        ("call", look_base), ("time", 11.5), ("wait", 1.0), ("shot", "show_01_base"),
        ("speed", 4.0),
        ("until", lambda g: fight_spot(g) is not None, 400), ("speed", 1.0),
        ("call", look_fight), ("wait", 0.8), ("call", look_fight), ("wait", 0.4), ("shot", "show_02_battle"),
        ("speed", 3.0), ("wait", 2.0), ("speed", 1.0), ("call", look_fight), ("wait", 0.5), ("shot", "show_03_battle"),
        ("call", look_base), ("time", 22.0), ("wait", 1.0), ("shot", "show_04_night"),
        ("quit",),
    ]


SCRIPTS["showcase"] = _showcase
CONFIGS["showcase"] = {"map": "greyfen_crossing", "me": "alliance", "them": "host", "me_ai": True, "fog": True, "ai": True,
                       "diff": "normal", "seed": 4}
SCRIPTS["showcase2"] = _showcase
CONFIGS["showcase2"] = {"map": "shadowed_pass", "me": "host", "them": "alliance", "me_ai": True, "fog": True, "ai": True,
                        "diff": "normal", "seed": 9}
