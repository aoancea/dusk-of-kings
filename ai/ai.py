"""Computer opponent: build orders, economy, supply, expansions, tech, scouting, defence and attack waves.

The AI only reacts to what its team can see (fog of war) plus remembered enemy buildings,
and knows the enemy start location (as every player of a two-player map would).
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from core import data
from core.actor import Order
from settings import CELL

if TYPE_CHECKING:
    from core.match import Match
    from core.player import Player


class AIController:
    """Drives one AI player."""

    def __init__(self, match: "Match", player: "Player", difficulty: str = "normal") -> None:
        self.m = match
        self.p = player
        self.diff = difficulty
        cfg = data.ai()
        self.cfg: dict[str, Any] = cfg["difficulty"][difficulty]
        self.order: list[dict[str, Any]] = [dict(s) for s in cfg["build_orders"][player.faction]]
        self.step = 0
        self.mix: dict[str, float] = cfg["army"][player.faction]
        self.rng = random.Random(match.config.seed * 31 + player.id)
        player.gather_mult = float(self.cfg["gather_bonus"])
        self.think_t = 1.0 + self.rng.random()
        self.worker_target = 8
        self.known: dict[int, tuple[str, float, float]] = {}   # enemy building id -> (type, x, z)
        self.enemy_start = self._enemy_start()
        self.start = tuple(match.map.start_info(player.id)["pos"])
        self.hunt: list[tuple[float, float]] = []
        self.state = "build"
        self.wave: list[Any] = []
        self.wave_target: tuple[float, float] | None = None
        self.next_attack = float(self.cfg["first_attack"])
        self.waves_sent = 0
        self.scout = None
        self.scouted = not self.cfg.get("scout", False)
        self.expansions = 0
        self.defending = False
        self.rally = self._rally_point()

    # ================================================================== helpers
    @property
    def home(self) -> tuple[float, float]:
        halls = [h for h in self.halls() if h.complete] or self.halls()
        if halls:
            h = min(halls, key=lambda h: math.hypot(h.x - self.start[0], h.z - self.start[1]))
            return h.x, h.z
        blds = self.buildings()
        return (blds[0].x, blds[0].z) if blds else self.start

    def _enemy_start(self) -> tuple[float, float]:
        for i, pl in enumerate(self.m.players):
            if pl.team != self.p.team:
                return tuple(self.m.map.start_info(i)["pos"])  # type: ignore[return-value]
        return (0.0, 0.0)

    def _rally_point(self) -> tuple[float, float]:
        hx, hz = self.home
        ex, ez = self.enemy_start
        d = math.hypot(ex - hx, ez - hz) or 1.0
        x, z = hx + (ex - hx) / d * 18, hz + (ez - hz) / d * 18
        g = self.m.grid
        c = g.nearest_walkable(g.cell_of(x, z), max_r=10)
        return g.center(c) if c is not None else (hx, hz)

    def units(self) -> list[Any]:
        return [u for u in self.m.units if u.alive and u.owner is self.p]

    def workers(self) -> list[Any]:
        return [u for u in self.units() if u.is_worker]

    def army(self) -> list[Any]:
        return [u for u in self.units() if not u.is_worker]

    def buildings(self, btype: str | None = None, complete: bool | None = None) -> list[Any]:
        return [b for b in self.m.buildings if b.alive and b.owner is self.p and (btype is None or b.type_id == btype)
                and (complete is None or b.complete == complete)]

    def halls(self) -> list[Any]:
        return [b for b in self.buildings() if b.town_hall]

    def count_type(self, tid: str) -> int:
        """Units of a type alive or queued."""
        n = sum(1 for u in self.units() if u.type_id == tid)
        for b in self.buildings(complete=True):
            n += sum(1 for q in b.queue if q.type_id == tid)
        return n

    def pending_building(self, btype: str) -> bool:
        if any(b.type_id == btype and not b.complete for b in self.buildings()):
            return True
        return any(u.order is not None and u.order.kind == "build" and u.order.data.get("type") == btype
                   and u.order.data.get("site") is None for u in self.workers())

    # ================================================================== main loop
    def update(self, dt: float) -> None:
        if self.p.defeated:
            return
        self.think_t -= dt
        if self.think_t > 0:
            return
        self.think_t = float(self.cfg["think"])
        self._observe()
        self._economy()
        self._supply()
        if len(self.army()) < self.min_army():
            self._production()      # a small army gets first claim on resources
            self._build_order()
        else:
            self._build_order()
            self._production()
        self._finish_sites()
        self._rebuild()
        self._expand()
        self._scout()
        self._defend()
        self._attack()

    # ================================================================== perception
    def _observe(self) -> None:
        m = self.m
        fog = m.fog
        team = self.p.team
        for b in m.buildings:
            if not b.alive or b.team == team or b.team < 0:
                continue
            if fog.is_visible(team, m.grid.cell_of(b.x, b.z)) or not fog.enabled:
                self.known[b.id] = (b.type_id, b.x, b.z)
        alive_ids = {b.id for b in m.buildings if b.alive}
        for bid in list(self.known):
            if bid not in alive_ids:
                _, x, z = self.known[bid]
                # forget destroyed buildings once we see the spot again
                if fog.is_visible(team, m.grid.cell_of(x, z)) or not fog.enabled:
                    del self.known[bid]

    def visible_enemies_near(self, x: float, z: float, r: float) -> list[Any]:
        m = self.m
        out = []
        for u in m.units:
            if u.alive and u.team != self.p.team and u.team >= 0 and not u.hidden and (u.x - x) ** 2 + (u.z - z) ** 2 < r * r:
                if m.is_visible_to(u, self.p.team):
                    out.append(u)
        return out

    # ================================================================== economy
    def _economy(self) -> None:
        m = self.m
        minutes = m.time / 60.0
        cap = int(self.cfg["max_workers"])
        target = min(cap, max(self.worker_target, int(9 + minutes * 2.2)))
        n_workers = self.count_type(self.p.fdef["worker"])
        if n_workers < target:
            for h in self.halls():
                if h.complete and not h.queue and not h.is_upgrading and self.p.has_supply(1):
                    if self.p.can_afford(data.units()[self.p.fdef["worker"]]["cost"]):
                        h.enqueue_unit(self.p.fdef["worker"])
                        n_workers += 1
                        if n_workers >= target:
                            break
        workers = self.workers()
        idle = [w for w in workers if w.order is None and not w.orders and w is not self.scout]
        if not idle:
            self._rebalance(workers)
            return
        timber_workers = [w for w in workers if w.order is not None and w.order.kind == "gather" and getattr(w.order.target, "is_tree", False)]
        want_timber = self.want_timber(len(workers))
        for w in idle:
            if len(timber_workers) < want_timber:
                tree = m.economy.find_tree(w, self._timber_spot(w))
                if tree is not None:
                    m.economy.order_gather([w], tree)
                    timber_workers.append(w)
                    continue
            mine = self._best_mine(w)
            if mine is not None:
                m.economy.order_gather([w], mine)
            else:
                tree = m.economy.find_tree(w, (w.x, w.z), max_dist=80)
                if tree is not None:
                    m.economy.order_gather([w], tree)

    def want_timber(self, n_workers: int) -> int:
        t = self.p.timber
        if self.p.gold > t * 3 + 250:
            return max(3, int(round(n_workers * 0.45)))
        if t > 700:
            frac = 0.1
        elif t > 350:
            frac = 0.2
        elif t > 150:
            frac = 0.28
        else:
            frac = 0.38
        return max(2, int(round(n_workers * frac)))

    def min_army(self) -> int:
        """Army size the AI keeps before spending on its build order (grows with time)."""
        k = {"easy": 0.8, "normal": 1.4, "hard": 1.9}.get(self.diff, 1.4)
        return int(2 + (self.m.time / 60.0) * k)

    def _timber_spot(self, w) -> tuple[float, float]:
        drops = [b for b in self.buildings(complete=True) if "timber" in b.dropoff]
        if drops:
            b = min(drops, key=lambda b: (b.x - w.x) ** 2 + (b.z - w.z) ** 2)
            return b.x, b.z
        return w.x, w.z

    def _best_mine(self, w) -> Any:
        best, score = None, 1e9
        for h in self.halls():
            if not h.complete:
                continue
            mine = self.m.map.mine_near(h.x, h.z, 30)
            if mine is None:
                continue
            miners = sum(1 for u in self.workers() if u.order is not None and u.order.kind == "gather" and u.order.target is mine)
            if miners >= 9:
                continue
            s = miners * 6 + math.hypot(mine.x - w.x, mine.z - w.z) * 0.1
            if s < score:
                best, score = mine, s
        if best is None:
            # long-distance mining from the closest mine that still has gold
            halls = [h for h in self.halls() if h.complete]
            for mine in self.m.map.mines:
                if not mine.alive or mine.depleted or not halls:
                    continue
                d = min(math.hypot(mine.x - h.x, mine.z - h.z) for h in halls)
                miners = sum(1 for u in self.workers() if u.order is not None and u.order.kind == "gather" and u.order.target is mine)
                if d < 70 and miners < 10 and d + miners * 3 < score:
                    best, score = mine, d + miners * 3
        return best

    def _rebalance(self, workers: list[Any]) -> None:
        """Move one worker from gold to timber (or back) when stockpiles are lopsided."""
        p = self.p
        gold = [w for w in workers if w.order is not None and w.order.kind == "gather" and getattr(w.order.target, "is_mine", False)]
        wood = [w for w in workers if w.order is not None and w.order.kind == "gather" and getattr(w.order.target, "is_tree", False)]
        want = self.want_timber(len(workers))
        if len(wood) < want - 1 and len(gold) > 4:
            w = gold[-1]
            tree = self.m.economy.find_tree(w, self._timber_spot(w))
            if tree is not None and w.carry == 0:
                self.m.economy.order_gather([w], tree)
        elif len(wood) > want + 1:
            w = wood[-1]
            mine = self._best_mine(w)
            if mine is not None and w.carry == 0:
                self.m.economy.order_gather([w], mine)

    # ================================================================== construction
    def _builder(self, near: tuple[float, float]) -> Any:
        cands = [w for w in self.workers() if w is not self.scout and w.carry == 0 and
                 (w.order is None or w.order.kind == "gather") and not w.hidden]
        if not cands:
            cands = [w for w in self.workers() if w is not self.scout and (w.order is None or w.order.kind == "gather") and not w.hidden]
        if not cands:
            return None
        return min(cands, key=lambda w: (w.x - near[0]) ** 2 + (w.z - near[1]) ** 2)

    def find_spot(self, btype: str, near: tuple[float, float] | None = None) -> tuple[float, float] | None:
        m = self.m
        g = m.grid
        bdef = data.buildings()[btype]
        size = int(bdef["footprint"])
        hx, hz = near or self.home
        mine = m.map.mine_near(hx, hz, 30)
        tower = btype in ("guard_tower", "watch_spire")
        r0 = 6 if tower else 9
        for r in range(r0, 40, 2):
            steps = max(8, int(r * 1.2))
            off = self.rng.random() * math.tau
            for k in range(steps):
                a = off + k / steps * math.tau
                x, z = hx + math.cos(a) * r, hz + math.sin(a) * r
                ok, _ = m.economy.can_place(self.p, btype, x, z)
                if not ok:
                    continue
                cx, cz = g.snap_footprint(x, z, size)
                i0, j0 = g.footprint_origin(cx, cz, size)
                # keep a one-cell lane around buildings so units never get boxed in
                if (g.dyn[max(j0 - 1, 0):j0 + size + 1, max(i0 - 1, 0):i0 + size + 1] > 0).any():
                    continue
                if mine is not None and not tower:
                    # stay out of the mining lane between hall and mine
                    if self._seg_dist(cx, cz, (hx, hz), (mine.x, mine.z)) < size * CELL * 0.5 + 4.5:
                        continue
                    if math.hypot(cx - mine.x, cz - mine.z) < 9:
                        continue
                if tower and mine is not None and math.hypot(cx - mine.x, cz - mine.z) > 16:
                    continue
                return cx, cz
        return None

    @staticmethod
    def _seg_dist(px: float, pz: float, a: tuple[float, float], b: tuple[float, float]) -> float:
        ax, az = a
        bx, bz = b
        dx, dz = bx - ax, bz - az
        ll = dx * dx + dz * dz
        t = 0.0 if ll < 1e-6 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / ll))
        return math.hypot(px - (ax + dx * t), pz - (az + dz * t))

    def build(self, btype: str, near: tuple[float, float] | None = None) -> bool:
        bdef = data.buildings()[btype]
        if not self.p.can_afford(bdef["cost"]) or self.p.missing_requirements(bdef):
            return False
        spot = self.find_spot(btype, near)
        if spot is None:
            return False
        w = self._builder(spot)
        if w is None:
            return False
        last = w.order.target if (w.order is not None and w.order.kind == "gather") else None
        err = self.m.economy.order_build(w, btype, *spot)
        if err:
            return False
        if last is not None:
            w.orders.append(Order("gather", last.x, last.z, target=last))
        return True

    def _supply(self) -> None:
        p = self.p
        sb = p.fdef["supply_building"]
        headroom = p.supply_cap - p.supply_used
        rate = len([b for b in self.buildings(complete=True) if b.trains()])
        need = 3 + rate * 2
        if p.supply_cap >= 100 + 10:
            return
        pending = sum(1 for b in self.buildings(sb) if not b.complete) + sum(
            1 for u in self.workers() if u.order is not None and u.order.kind == "build" and u.order.data.get("type") == sb
            and u.order.data.get("site") is None)
        if headroom < need and pending < (2 if rate >= 3 else 1):
            self.build(sb)

    # ================================================================== build order
    def home_gold(self) -> int:
        """Gold left in the mines next to our town halls."""
        total = 0
        for mine in self.m.map.mines:
            if mine.alive and not mine.depleted and any(math.hypot(mine.x - h.x, mine.z - h.z) < 30 for h in self.halls()):
                total += mine.gold
        return total

    def want_expand(self) -> bool:
        if self.expansions >= 3 or self.pending_building(self.p.fdef["town_hall"]):
            return False
        if self.home_gold() < 2500:
            return True
        return self.m.time >= float(self.cfg["expand_at"]) * (1 + self.expansions * 0.9)

    def _reserve(self) -> dict[str, int]:
        if self.want_expand() and len(self.army()) >= self.min_army() // 2:
            return dict(data.buildings()[self.p.fdef["town_hall"]]["cost"])
        if self.step >= len(self.order):
            return {"gold": 0, "timber": 0}
        s = self.order[self.step]
        if "build" in s:
            return dict(data.buildings()[s["build"]]["cost"])
        if "research" in s:
            return dict(data.upgrades()[s["research"]]["cost"])
        if "upgrade_town_hall" in s:
            key = "castle_upgrade" if self.p.faction == "alliance" else "stronghold_upgrade"
            return dict(data.upgrades()[key]["cost"])
        return {"gold": 0, "timber": 0}

    def _build_order(self) -> None:
        guard = 0
        while self.step < len(self.order) and guard < 4:
            guard += 1
            s = self.order[self.step]
            if "workers" in s:
                self.worker_target = int(s["workers"])
                if self.count_type(self.p.fdef["worker"]) >= min(self.worker_target, int(self.cfg["max_workers"])) - 1:
                    self.step += 1
                    continue
                return
            if "build" in s:
                bt = s["build"]
                if s.get("_ordered"):
                    if self.pending_building(bt) or any(b.type_id == bt for b in self.buildings()):
                        self.step += 1
                        continue
                    s["_ordered"] = False   # builder died or the site was blocked: retry
                if self.p.missing_requirements(data.buildings()[bt]):
                    return
                if self.build(bt):
                    s["_ordered"] = True
                return
            if "train" in s:
                tid = s["train"]
                if self.count_type(tid) >= s.get("count", 1):
                    self.step += 1
                    continue
                if not self._train(tid):
                    return
                continue
            if "research" in s:
                up = s["research"]
                if up in self.p.upgrades or up in self.p.researching:
                    self.step += 1
                    continue
                u = data.upgrades()[up]
                if self.p.missing_requirements(u):
                    if u.get("tier", 1) >= 2 and self.p.tier < 2:
                        return
                    self.step += 1   # skip impossible step
                    continue
                for b in self.buildings(complete=True):
                    if up in b.researches() and len(b.queue) < 2:
                        if b.enqueue_research(up) is None:
                            self.step += 1
                        break
                return
            if "upgrade_town_hall" in s:
                key = "castle_upgrade" if self.p.faction == "alliance" else "stronghold_upgrade"
                if self.p.tier >= 2 or key in self.p.researching:
                    self.step += 1
                    continue
                for h in self.halls():
                    if h.complete and h.defn.get("upgrades_to"):
                        if len(h.queue) < 2 and h.enqueue_research(key) is None:
                            self.step += 1
                        break
                return
            self.step += 1

    def _train(self, tid: str) -> bool:
        ud = data.units()[tid]
        if self.p.missing_requirements(ud) or not self.p.has_supply(int(ud.get("supply", 1))):
            return False
        for b in sorted(self.buildings(complete=True), key=lambda b: len(b.queue)):
            if tid in b.trains() and len(b.queue) < 3 and not b.is_upgrading:
                if b.enqueue_unit(tid) is None:
                    if b.rally is None:
                        b.rally = self.rally
                    return True
                return False
        return False

    # ================================================================== army production
    def _finish_sites(self) -> None:
        """Send a worker to any unfinished building that has nobody constructing it (Alliance)."""
        for b in self.buildings(complete=False):
            if b.self_building:
                continue
            busy = any(u.order is not None and u.order.kind == "build" and u.order.data.get("site") is b for u in self.workers())
            if not busy:
                w = self._builder((b.x, b.z))
                if w is not None:
                    last = w.order.target if (w.order is not None and w.order.kind == "gather") else None
                    self.m.economy.order_construct([w], b)
                    if last is not None:
                        w.orders.append(Order("gather", last.x, last.z, target=last))

    def _rebuild(self) -> None:
        """Replace destroyed town halls, production and tech buildings once the build order is done."""
        p = self.p
        th = p.fdef["town_hall"]
        if not self.halls():
            if not self.pending_building(th) and p.can_afford(data.buildings()[th]["cost"]):
                spot = self._hall_spot()
                if spot is not None:
                    w = self._builder(spot)
                    if w is not None:
                        self.m.economy.order_build(w, th, *spot)
            return
        if self.step < len(self.order):
            return
        wanted: dict[str, int] = {}
        for st in self.order:
            if "build" in st and st["build"] != p.fdef["supply_building"]:
                wanted[st["build"]] = wanted.get(st["build"], 0) + 1
        for bt, n in wanted.items():
            have = sum(1 for b in self.buildings() if b.type_id == bt or data.buildings()[b.type_id].get("upgrade_of") == bt)
            if have < min(n, 2) and not self.pending_building(bt):
                if self.build(bt):
                    return

    def _hall_spot(self) -> tuple[float, float] | None:
        """A legal town-hall site next to the nearest unclaimed gold mine."""
        taken = [(b.x, b.z) for b in self.m.buildings if b.alive and b.town_hall]
        ref = self.home
        mines = sorted((mi for mi in self.m.map.mines if mi.alive and not mi.depleted and
                        not any(math.hypot(mi.x - x, mi.z - z) < 30 for x, z in taken)),
                       key=lambda mi: math.hypot(mi.x - ref[0], mi.z - ref[1]))
        for mine in mines:
            if self.visible_enemies_near(mine.x, mine.z, 18):
                continue
            ex, ez = mine.entrance
            dx, dz = ex - mine.x, ez - mine.z
            ln = math.hypot(dx, dz) or 1.0
            tx, tz = mine.x + dx / ln * 12.5, mine.z + dz / ln * 12.5
            for r in range(0, 10, 2):
                for k in range(8):
                    a = k / 8 * math.tau
                    x, z = tx + math.cos(a) * r, tz + math.sin(a) * r
                    if self.m.economy.can_place(self.p, self.p.fdef["town_hall"], x, z)[0]:
                        return x, z
        return None

    def _production(self) -> None:
        p = self.p
        army = self.army()
        reserve = self._reserve() if len(army) >= self.min_army() else {"gold": 0, "timber": 0}
        counts: dict[str, int] = {}
        for u in army:
            counts[u.type_id] = counts.get(u.type_id, 0) + 1
        for b in self.buildings(complete=True):
            for q in b.queue:
                if q.kind == "unit":
                    counts[q.type_id] = counts.get(q.type_id, 0) + 1
        total = sum(counts.values()) + 1
        options = []
        for tid, weight in self.mix.items():
            ud = data.units()[tid]
            if p.missing_requirements(ud):
                continue
            share = counts.get(tid, 0) / total
            options.append((share / weight, tid))
        options.sort()
        for _, tid in options:
            ud = data.units()[tid]
            cost = ud["cost"]
            if p.gold - cost.get("gold", 0) < reserve.get("gold", 0) or p.timber - cost.get("timber", 0) < reserve.get("timber", 0):
                continue
            if not p.has_supply(int(ud.get("supply", 1))):
                return
            if self._train(tid):
                return
        # extra production buildings when floating resources
        prod = "barracks" if p.faction == "alliance" else "war_camp"
        n_prod = len(self.buildings(prod))
        limit = min(4, 1 + int(self.m.time / 180))
        if p.gold > 450 + 150 * n_prod and n_prod < limit and p.supply_used < 90 and self.step >= 4:
            if not self.pending_building(prod):
                self.build(prod)

    # ================================================================== expansion
    def _expand(self) -> None:
        if not self.want_expand():
            return
        th = self.p.fdef["town_hall"]
        bdef = data.buildings()[th]
        if not self.p.can_afford(bdef["cost"]):
            return
        spot = self._hall_spot()
        if spot is None:
            return
        w = self._builder(spot)
        if w is not None and self.m.economy.order_build(w, th, *spot) is None:
            self.expansions += 1

    # ================================================================== scouting
    def _scout(self) -> None:
        if self.scouted or self.m.time < 100:
            return
        if self.scout is None:
            ws = [w for w in self.workers() if w.carry == 0 and not w.hidden and (w.order is None or w.order.kind == "gather")]
            if len(ws) < 6:
                return
            self.scout = ws[-1]
            ex, ez = self.enemy_start
            self.m.order_units([self.scout], "move", ex, ez)
            return
        s = self.scout
        if not s.alive:
            self.scouted = True
            self.scout = None
            return
        ex, ez = self.enemy_start
        if math.hypot(s.x - ex, s.z - ez) < 14 or s.order is None:
            self.scouted = True
            s.stop()
            self.scout = None   # goes back to work via the idle-worker logic

    # ================================================================== defence
    def _defend(self) -> None:
        threats = []
        for b in self.buildings():
            threats += self.visible_enemies_near(b.x, b.z, 22)
        for w in self.workers():
            if w.last_attacker is not None and self.m.time - w.last_hit_time < 3 and w.last_attacker.alive:
                threats.append(w.last_attacker)
        threats = [t for t in threats if not t.is_worker or t.attack]
        if not threats:
            if self.defending:
                self.defending = False
                home = [u for u in self.army() if u not in self.wave]
                self.m.order_units(home, "move", *self.rally)
            return
        self.defending = True
        tx = sum(t.x for t in threats) / len(threats)
        tz = sum(t.z for t in threats) / len(threats)
        defenders = [u for u in self.army() if u not in self.wave or len(threats) > 6]
        if defenders:
            busy = [u for u in defenders if u.target is not None and u.target.alive and u.dist_to(u.target) < 15]
            free = [u for u in defenders if u not in busy]
            if free:
                self.m.order_units(free, "attack_move", tx, tz)
            if len(threats) > 6:
                self.wave = [u for u in self.wave if u not in defenders]
        # desperate: workers fight when the base is overrun early
        if len(self.army()) < 2 and len(threats) >= 2:
            near = [w for w in self.workers() if math.hypot(w.x - tx, w.z - tz) < 20 and not w.hidden]
            self.m.order_units(near[:6], "attack_move", tx, tz)

    # ================================================================== attack waves
    def _attack(self) -> None:
        m = self.m
        self.wave = [u for u in self.wave if u.alive]
        if self.state == "attack":
            if len(self.wave) < max(3, int(self.cfg["attack_size"]) // 4):
                self.state = "build"
                self.next_attack = m.time + float(self.cfg["attack_interval"]) * 0.6
                if self.wave:
                    m.order_units(self.wave, "move", *self.rally)
                self.wave = []
                return
            tgt = self._attack_target()
            if tgt != self.wave_target:
                self.wave_target = tgt
                m.order_units(self.wave, "attack_move", *tgt)
            else:
                idle = [u for u in self.wave if u.order is None and u.target is None]
                if idle:
                    m.order_units(idle, "attack_move", *tgt)
            return
        if self.defending:
            return
        army = [u for u in self.army() if u.order is None or u.order.kind in ("move", "attack_move")]
        size = int(self.cfg["attack_size"]) + self.waves_sent * 4
        if m.time >= self.next_attack and len(army) >= size or len(army) >= 40:
            self.state = "attack"
            self.waves_sent += 1
            self.wave = army
            self.wave_target = self._attack_target()
            m.order_units(self.wave, "attack_move", *self.wave_target)
            self.next_attack = m.time + float(self.cfg["attack_interval"])
        else:
            stray = [u for u in army if u.order is None and math.hypot(u.x - self.rally[0], u.z - self.rally[1]) > 14
                     and u.target is None]
            if stray:
                m.order_units(stray, "move", *self.rally)

    def _attack_target(self) -> tuple[float, float]:
        if self.known:
            cx = sum(u.x for u in self.wave) / max(1, len(self.wave))
            cz = sum(u.z for u in self.wave) / max(1, len(self.wave))
            # prefer production and town halls, then whatever is closest
            def score(item):
                tid, x, z = item
                d = math.hypot(x - cx, z - cz)
                bd = data.buildings()[tid]
                if bd.get("attack"):
                    d -= 6
                return d
            tid, x, z = min(self.known.values(), key=score)
            self.hunt = []
            return x, z
        if not self.hunt:
            ex, ez = self.enemy_start
            spots = [(mi.x, mi.z) for mi in self.m.map.mines] + [tuple(s["pos"]) for s in self.m.map.starts]
            self.hunt = sorted(spots, key=lambda q: math.hypot(q[0] - ex, q[1] - ez))
        # advance to the next search spot once the wave has reached the current one
        if self.wave:
            cx = sum(u.x for u in self.wave) / len(self.wave)
            cz = sum(u.z for u in self.wave) / len(self.wave)
            while len(self.hunt) > 1 and math.hypot(self.hunt[0][0] - cx, self.hunt[0][1] - cz) < 14:
                self.hunt.pop(0)
        return self.hunt[0]
