"""One skirmish: the map, the players, every unit and building, and the per-frame simulation."""
from __future__ import annotations

import heapq
import itertools
import math
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

import numpy as np
from panda3d.core import NodePath, Vec3

from core import data, shaders
from core.actor import Actor, Order
from core.camera import RTSCamera
from core.events import events
from core.player import Player
from core.textures import radial_texture, ring_texture
from settings import CELL, NIGHT_END, NIGHT_START, START_WORKERS, TEAM_COLORS
from ui.overlays import QuadBatch
from units.unit import GroupPath, Unit
from world.fog import FogOfWar
from world.gamemap import GameMap
from world.pathing import PathService
from world.sky import Environment

if TYPE_CHECKING:
    from core.game import Game


@dataclass
class PlayerConfig:
    faction: str
    is_ai: bool
    difficulty: str = "normal"
    color: tuple[float, float, float] | None = None


@dataclass
class MatchConfig:
    map_id: str = "greyfen_crossing"
    players: list[PlayerConfig] = field(default_factory=lambda: [PlayerConfig("alliance", False), PlayerConfig("host", True)])
    human: int | None = 0            # index of the local player (None = spectate AI vs AI)
    fog: bool = True
    seed: int = 1
    start_units: bool = True
    ai_enabled: bool = True


class Match:
    """Owns and simulates everything in a running skirmish."""

    def __init__(self, game: "Game", config: MatchConfig) -> None:
        self.game = game
        self.base = game.base
        self.config = config
        self.time = 0.0
        self.rng = random.Random(config.seed)
        render = self.base.render
        self.root = render.attachNewNode("match")
        self.map_root = self.root.attachNewNode("map")
        self.unit_root = self.root.attachNewNode("units")
        self.building_root = self.root.attachNewNode("buildings")
        self.fx_root = self.root.attachNewNode("fx")
        self.map = GameMap(self, config.map_id)
        self.terrain = self.map.terrain
        self.grid = self.map.grid
        self.paths = PathService(self.grid)
        self.env = Environment(render, 520.0)
        self.env.hour = float(self.map.defn.get("start_hour", 9.0))
        render.setShader(shaders.world_shader())
        self.fog = FogOfWar(self.grid, len(config.players))
        self.fog.enabled = config.fog                       # AI decisions always respect fog when it is on
        self.fog.display_team = config.human if (config.fog and config.human is not None) else -1
        half = self.terrain.half
        render.setShaderInput("u_fow_tex", self.fog.tex)
        render.setShaderInput("u_fow_rect", (-half, -half, self.terrain.size, self.terrain.size))
        render.setShaderInput("u_fow_on", 1.0 if self.fog.display_team >= 0 else 0.0)
        if self.map.water is not None:
            self.map.water.node.setShaderInput("u_fow_tex", self.fog.tex)
        self.players: list[Player] = []
        factions = [pc.faction for pc in config.players]
        for i, pc in enumerate(config.players):
            if pc.color is not None:
                col = pc.color
            elif len(set(factions)) == len(factions):
                col = TEAM_COLORS[0] if pc.faction == "alliance" else TEAM_COLORS[1]
            else:
                col = TEAM_COLORS[i % len(TEAM_COLORS)]
            self.players.append(Player(i, pc.faction, col, pc.is_ai))
        self.human: Player | None = self.players[config.human] if config.human is not None else None
        self.units: list[Unit] = []
        self.buildings: list[Any] = []
        self.corpses: list[Any] = []
        from combat.combat import CombatSystem
        from combat.effects import EffectsManager
        self.fx = EffectsManager(self)
        self.combat = CombatSystem(self)
        from economy.economy import Economy
        from combat.abilities import Abilities
        self.economy = Economy(self)
        self.abilities = Abilities(self)
        self.map.populate()
        self.cam = RTSCamera(self.base, self.terrain)
        self._sched: list[tuple[float, int, Callable[[], None]]] = []
        self._seq = itertools.count()
        self._fog_t = 0.0
        self._vis_t = 0.0
        self.selection: list[Actor] = []
        self.winner: Player | None = None
        self.over = False
        self.alerts: list[tuple[float, float, float]] = []
        # overlays
        self.shadows = QuadBatch(self.fx_root, 700, radial_texture(64, 0.0, 1.0, (0, 0, 0), power=1.3), "shadows")
        self.shadows.node.setShaderInput("u_emissive", 1.0)
        self.shadows.node.setBin("transparent", 1)
        self.rings = QuadBatch(self.fx_root, 400, ring_texture(128, 0.14), "rings")
        self.rings.node.setShaderInput("u_emissive", 1.0)
        self.rings.node.setBin("transparent", 2)
        from ursina import camera as ucam
        self.bars = QuadBatch(ucam.ui, 1800, None, "bars", flat3d=False)
        self.bars.node.setZ(0.5)
        self.bars.node.setDepthTest(False)
        self.show_all_bars = False
        self.ais: list[Any] = []
        self.ai_enabled = config.ai_enabled
        self.speed = 1.0

    # ================================================================== setup
    def setup(self) -> None:
        """Create starting bases and AI controllers."""
        for i, p in enumerate(self.players):
            info = self.map.start_info(i)
            sx, sz = info["pos"]
            th = p.fdef["town_hall"]
            if self.config.start_units:
                b = self.spawn_building(p, th, sx, sz, complete=True)
                mine = self.map.mine_near(sx, sz, 40)
                # workers spawn between the hall and the mine
                ax, az = (mine.x, mine.z) if mine else (sx + 8, sz)
                for k in range(START_WORKERS):
                    t = (k + 1) / (START_WORKERS + 1)
                    px = sx + (ax - sx) * 0.45 + (k - 2) * 1.4 * (az - sz) / max(1.0, math.hypot(ax - sx, az - sz))
                    pz = sz + (az - sz) * 0.45 - (k - 2) * 1.4 * (ax - sx) / max(1.0, math.hypot(ax - sx, az - sz))
                    u = self.spawn_unit(p, p.fdef["worker"], px, pz)
                    if mine is not None and (p.is_ai or self.human is None or p is self.human):
                        self.economy.order_gather([u], mine, queue=False)
        if self.human is not None:
            sx, sz = self.map.start_info(self.human.id)["pos"]
            self.cam.look_at(sx, sz - 6)
        else:
            self.cam.look_at(0, 0)
        self.update_fog(force=True)

    def start_ai(self) -> None:
        if not self.ai_enabled:
            return
        from ai.ai import AIController
        for i, p in enumerate(self.players):
            if p.is_ai:
                self.ais.append(AIController(self, p, self.config.players[i].difficulty))

    # ================================================================== spawning
    def spawn_unit(self, owner: Player, type_id: str, x: float, z: float, yaw: float = 180.0) -> Unit:
        u = Unit(self, owner, type_id, x, z, yaw)
        self.units.append(u)
        owner.supply_used += u.supply
        events.emit("unit_spawned", unit=u)
        return u

    def spawn_building(self, owner: Player, type_id: str, x: float, z: float, complete: bool = False) -> Any:
        from buildings.building import Building
        b = Building(self, owner, type_id, x, z, complete=complete)
        self.buildings.append(b)
        return b

    # ================================================================== queries
    @property
    def is_night(self) -> bool:
        h = self.env.hour
        return h >= NIGHT_START or h < NIGHT_END

    def actors_near(self, x: float, z: float, r: float) -> list[Actor]:
        out: list[Actor] = []
        r2 = r * r
        for u in self.units:
            if u.alive and (u.x - x) ** 2 + (u.z - z) ** 2 <= r2:
                out.append(u)
        for b in self.buildings:
            rr = r + b.radius
            if b.alive and (b.x - x) ** 2 + (b.z - z) ** 2 <= rr * rr:
                out.append(b)
        return out

    def units_of(self, player: Player) -> list[Unit]:
        return [u for u in self.units if u.alive and u.owner is player]

    def buildings_of(self, player: Player) -> list[Any]:
        return [b for b in self.buildings if b.alive and b.owner is player]

    def is_visible_to(self, actor: Actor, team: int) -> bool:
        if actor.team == team or not self.fog.enabled:
            return True
        if getattr(actor, "hidden", False):
            return False
        return self.fog.is_visible(team, self.grid.cell_of(actor.x, actor.z))

    def crowd_hint(self, unit: Unit) -> int:
        o = unit.order
        return int(o.data.get("n", 1)) if o is not None else 1

    # ================================================================== orders
    def order_units(self, units: list[Unit], kind: str, x: float = 0.0, z: float = 0.0, target: Actor | None = None,
                    queue: bool = False) -> None:
        """Give a group order. Move-like orders spread the group into a formation around (x, z)."""
        units = [u for u in units if u.alive and u.is_unit]
        if not units:
            return
        if kind in ("move", "attack_move", "patrol"):
            slots = self.formation(units, x, z)
            group = GroupPath()
            ground = [u for u in units if not u.flying]
            if ground and len(ground) > 1:
                cx = sum(u.x for u in ground) / len(ground)
                cz = sum(u.z for u in ground) / len(ground)
                lead = min(ground, key=lambda u: (u.x - cx) ** 2 + (u.z - cz) ** 2)

                def done(pts, group=group) -> None:
                    group.pts = pts or [(x, z)]

                self.paths.request(lead.x, lead.z, x, z, done)
            else:
                group.pts = [(x, z)]
            for u, (sx, sz) in zip(units, slots):
                o = Order(kind, sx, sz, data={"group": group if not u.flying else None, "n": len(units)})
                u.command(o, queue)
        elif kind in ("attack", "follow"):
            for u in units:
                if kind == "attack" and (target is None or not u.can_attack(target)):
                    o = Order("move" if target is None else "follow", target.x if target else x, target.z if target else z,
                              target=target, data={"n": len(units)})
                else:
                    o = Order(kind, x, z, target=target, data={"n": len(units)})
                u.command(o, queue)
        elif kind == "hold":
            for u in units:
                u.command(Order("hold"), queue)
        elif kind == "stop":
            for u in units:
                u.stop()

    def formation(self, units: list[Unit], x: float, z: float) -> list[tuple[float, float]]:
        """Target slot for each unit: the group's layout, compressed around (x, z), snapped to walkable cells."""
        n = len(units)
        if n == 1:
            return [(x, z)]
        cx = sum(u.x for u in units) / n
        cz = sum(u.z for u in units) / n
        spacing = max(u.radius for u in units) * 2.3 + 0.3
        max_r = math.sqrt(n) * spacing * 0.75
        offs = [(u.x - cx, u.z - cz) for u in units]
        spread = max(math.hypot(ox, oz) for ox, oz in offs) or 1.0
        out = []
        if spread <= max_r * 1.5:
            k = 1.0 if spread <= max_r else max_r / spread
            for ox, oz in offs:
                out.append((x + ox * k, z + oz * k))
        else:
            # rebuild as a block facing the direction of travel
            dx, dz = x - cx, z - cz
            ln = math.hypot(dx, dz) or 1.0
            fx, fz = dx / ln, dz / ln
            rx, rz = fz, -fx
            cols = max(1, int(math.ceil(math.sqrt(n * 1.6))))
            order = sorted(range(n), key=lambda i: (offs[i][0] * rx + offs[i][1] * rz))
            slots = []
            for k in range(n):
                row, col = divmod(k, cols)
                lat = (col - (cols - 1) / 2) * spacing
                dep = -row * spacing
                slots.append((x + rx * lat + fx * dep, z + rz * lat + fz * dep))
            out = [None] * n  # type: ignore[list-item]
            for slot_i, unit_i in enumerate(order):
                out[unit_i] = slots[slot_i]
        res = []
        g = self.grid
        for (sx, sz), u in zip(out, units):
            if not u.flying and not g.walkable(sx, sz):
                c = g.nearest_walkable(g.cell_of(sx, sz), g.component(g.cell_of(x, z)) if g.walkable(x, z) else None, 8)
                if c is not None:
                    sx, sz = g.center(c)
                else:
                    sx, sz = x, z
            res.append((sx, sz))
        return res

    # ================================================================== events
    def schedule(self, delay: float, fn: Callable[[], None]) -> None:
        heapq.heappush(self._sched, (self.time + delay, next(self._seq), fn))

    def kill(self, actor: Actor, killer: Actor | None) -> None:
        if actor.is_unit:
            u = actor
            u.die()
            u.owner.supply_used -= u.supply
            u.owner.stats["units_lost"] += 1
            self.economy.on_unit_died(u)
            self.corpses.append(u)
            if killer is not None and killer.owner is not None and killer.owner is not u.owner:
                killer.owner.stats["kills"] += 1
            events.emit("sound", name="death", pos=(u.x, u.z))
        elif actor.is_building:
            actor.on_destroyed()
            if killer is not None and killer.owner is not None and killer.owner is not actor.owner:
                killer.owner.stats["kills"] += 1
        if actor in self.selection:
            self.selection.remove(actor)
            actor.selected = False
        events.emit("actor_died", actor=actor, killer=killer)

    def on_damaged(self, victim: Actor, attacker: Actor | None) -> None:
        """Idle units fight back, nearby idle allies join in; the owner gets an alert."""
        if attacker is None or not attacker.alive or attacker.team == victim.team:
            return
        if victim.owner is not None and victim.owner is self.human:
            self.alert(victim.x, victim.z)
        for u in self.units:
            if not u.alive or u.team != victim.team or u.hidden:
                continue
            if (u.x - victim.x) ** 2 + (u.z - victim.z) ** 2 > 100.0 and u is not victim:
                continue
            if u.order is None and u.target is None and u.can_attack(attacker) and not u.is_worker:
                u.target = attacker
                u.anchor = (u.x, u.z)
        events.emit("damaged", victim=victim, attacker=attacker)

    def alert(self, x: float, z: float) -> None:
        if self.alerts and self.time - self.alerts[-1][0] < 6.0 and math.hypot(self.alerts[-1][1] - x, self.alerts[-1][2] - z) < 30:
            return
        self.alerts.append((self.time, x, z))
        events.emit("alert", x=x, z=z)

    def on_mine_depleted(self, mine) -> None:
        self.schedule(0.1, mine.collapse)
        events.emit("mine_depleted", mine=mine)

    def cam_shake(self, actor: Actor, amount: float) -> None:
        if actor.visible and abs(actor.x - self.cam.fx) < 40 and abs(actor.z - self.cam.fz) < 40:
            self.cam.shake(amount, 0.25)

    # ================================================================== fog
    def update_fog(self, force: bool = False) -> None:
        nite = self.is_night
        viewers: list[list[tuple[float, float, float, bool]]] = [[] for _ in self.players]
        night_k = data.combat()["day_night"].get("alliance_night_sight", 1.0)
        for u in self.units:
            if u.alive and not u.hidden:
                s = u.sight * (night_k if (nite and u.owner.faction == "alliance") else 1.0)
                viewers[u.team].append((u.x, u.z, s, u.flying))
        for b in self.buildings:
            if b.alive:
                viewers[b.team].append((b.x, b.z, b.sight if b.complete else 6.0, False))
        self.fog.compute(viewers)

    # ================================================================== simulation
    def update(self, dt: float) -> None:
        dt *= self.speed
        if dt <= 0:
            return
        self.time += dt
        self.paths.update()
        while self._sched and self._sched[0][0] <= self.time:
            _, _, fn = heapq.heappop(self._sched)
            fn()
        self.combat.update(dt)
        for ai in self.ais:
            ai.update(dt)
        for u in self.units:
            if u.alive:
                u.update(dt)
        for b in self.buildings:
            if b.alive:
                b.update(dt)
        self.economy.update(dt)
        self.abilities.update(dt)
        self._separate(dt)
        if any(not b.alive for b in self.buildings):
            self.buildings = [b for b in self.buildings if b.alive]
        self.map.update(dt)
        self._fog_t -= dt
        if self._fog_t <= 0:
            self._fog_t = 0.2
            self.update_fog()
        self._update_corpses(dt)
        self._check_victory()

    def _separate(self, dt: float) -> None:
        ground = [u for u in self.units if u.alive and not u.flying and not u.hidden and not u.work.get("ghost")]
        n = len(ground)
        if n >= 2:
            P = np.empty((n, 2), np.float32)
            P[:, 0] = np.fromiter((u.x for u in ground), np.float32, n)
            P[:, 1] = np.fromiter((u.z for u in ground), np.float32, n)
            R = np.fromiter((u.radius for u in ground), np.float32, n)
            W = np.fromiter((0.15 if (u.order is not None and u.order.kind == "hold") or (u.target is not None and not u.moving)
                             else (1.0 if u.moving else 0.7) for u in ground), np.float32, n)
            D = P[:, None, :] - P[None, :, :]
            dist = np.sqrt((D ** 2).sum(-1))
            np.fill_diagonal(dist, 1e6)
            minD = (R[:, None] + R[None, :]) * 0.92
            ov = minD - dist
            if (ov > 0).any():
                ov = np.clip(ov, 0, None)
                close = dist < 1e-3
                if close.any():
                    jitter = np.random.uniform(-0.05, 0.05, D.shape).astype(np.float32)
                    D = np.where(close[..., None], jitter, D)
                    dist = np.where(close, 0.07, dist)
                share = W[:, None] / (W[:, None] + W[None, :])
                k = min(1.0, dt * 10.0)
                disp = ((D / dist[..., None]) * (ov * share * k)[..., None]).sum(1)
                mag = np.abs(disp).sum(1)
                idx = np.nonzero(mag > 1e-4)[0]
                grid = self.grid
                for i in idx:
                    u = ground[i]
                    nx, nz = u.x + float(disp[i, 0]), u.z + float(disp[i, 1])
                    if grid.walkable(nx, nz):
                        u.x, u.z = nx, nz
                    elif grid.walkable(nx, u.z):
                        u.x = nx
                    elif grid.walkable(u.x, nz):
                        u.z = nz
        flyers = [u for u in self.units if u.alive and u.flying]
        m = len(flyers)
        if m >= 2:
            for i in range(m):
                a = flyers[i]
                for j in range(i + 1, m):
                    b = flyers[j]
                    dx, dz = a.x - b.x, a.z - b.z
                    d = math.hypot(dx, dz)
                    mn = (a.radius + b.radius) * 0.9
                    if d < mn:
                        if d < 1e-3:
                            dx, dz, d = random.uniform(-1, 1), random.uniform(-1, 1), 1.0
                        push = (mn - d) * 0.5 * min(1.0, dt * 6.0) / d
                        a.x += dx * push
                        a.z += dz * push
                        b.x -= dx * push
                        b.z -= dz * push

    def _update_corpses(self, dt: float) -> None:
        keep = []
        for c in self.corpses:
            c.corpse_t += dt
            if c.corpse_t > 3.0 and c.node is not None:
                c.node.setY(c.y - (c.corpse_t - 3.0) * 0.6)
            if c.corpse_t > 5.0:
                c.destroy()
                if c in self.units:
                    self.units.remove(c)
            else:
                keep.append(c)
        self.corpses = keep

    def _check_victory(self) -> None:
        if self.over or self.time < 2.0:
            return
        alive = []
        for p in self.players:
            if p.defeated:
                continue
            if not any(b.alive for b in self.buildings if b.owner is p):
                p.defeated = True
                events.emit("player_defeated", player=p)
            else:
                alive.append(p)
        if len(alive) <= 1:
            self.over = True
            self.winner = alive[0] if alive else None
            events.emit("match_over", winner=self.winner)

    # ================================================================== presentation
    def present(self, dt: float, real_dt: float) -> None:
        """Per-frame visual sync: visibility, node transforms, animation, overlays, effects, lighting."""
        cam = self.cam
        self.env.focus = (cam.fx, cam.fz)
        self.env.update(real_dt * self.speed, self.base.cam.getPos(self.base.render))
        self.fog.update_display(real_dt)
        human_team = self.human.team if self.human is not None else -1
        actors = self.units
        n = len(actors)
        if n:
            pts = np.empty((n, 3), np.float32)
            pts[:, 0] = np.fromiter((u.x for u in actors), np.float32, n)
            pts[:, 1] = np.fromiter((u.y + u.height * 0.5 for u in actors), np.float32, n)
            pts[:, 2] = np.fromiter((u.z for u in actors), np.float32, n)
            ui, front = cam.project(pts)
            from ursina import window
            ax = window.aspect_ratio * 0.5 + 0.12
            onscr = front & (np.abs(ui[:, 0]) < ax) & (np.abs(ui[:, 1]) < 0.62)
        else:
            onscr = np.zeros(0, bool)
        fog_on = self.fog.display_team >= 0
        vb = self.fog.vis_bytes[human_team] if (fog_on and human_team >= 0) else None
        grid = self.grid
        # with big crowds on screen, animate rigs in staggered groups (each at a lower rate)
        n_on = int(onscr.sum()) if n else 0
        stride = 1 if n_on < 90 else 2 if n_on < 200 else 3
        self._frame = getattr(self, "_frame", 0) + 1
        frame = self._frame
        for i, u in enumerate(actors):
            vis = (not u.hidden) and (vb is None or u.team == human_team or vb[grid.cell_of(u.x, u.z)] > 0 or not u.alive and u.visible)
            if vis != u.visible or (u.node is not None and u.node.isHidden() == vis):
                u.visible = vis
                if u.node is not None:
                    if vis:
                        u.node.show()
                    else:
                        u.node.hide()
            u.on_screen = bool(onscr[i]) and vis
            if u.alive:
                u.sync_node()
            if u.on_screen:
                u.anim_dt += dt
                if (i + frame) % stride == 0 or not u.alive:
                    u.animate(u.anim_dt)
                    u.anim_dt = 0.0
            else:
                u._px, u._pz = u.x, u.z
                u.anim_dt = 0.0
        for b in self.buildings:
            b.present(dt, human_team, vb)
        self._draw_overlays()
        q = self.base.cam.getQuat(self.base.render)
        right = q.getRight()
        up = q.getUp()
        self.fx.update(dt, np.array([right.x, right.y, right.z], np.float32), np.array([up.x, up.y, up.z], np.float32))

    def _draw_overlays(self) -> None:
        sh_r, sh_c = [], []
        rg_r, rg_c = [], []
        for u in self.units:
            if not u.on_screen:
                continue
            gy = self.terrain.height(u.x, u.z) if u.flying else u.y
            a = 0.55 if u.alive else 0.55 * max(0.0, 1 - u.corpse_t / 3.0)
            sh_r.append((u.x, gy + 0.06, u.z, u.radius * (1.5 if u.flying else 1.25)))
            sh_c.append((1, 1, 1, a * (0.6 if u.flying else 1.0)))
        for a in self.selection:
            if not a.alive or not a.visible:
                continue
            if a.is_building:
                r = a.footprint * CELL * 0.62
                y = a.y + 0.15
            else:
                r = a.radius * 1.35 + 0.15
                y = (self.terrain.height(a.x, a.z) if a.flying else a.y) + 0.08
            if a.owner is not None and a.owner is self.human:
                col = (0.3, 1.0, 0.35, 0.95)
            elif a.owner is None:
                col = (1.0, 0.9, 0.3, 0.9)
            else:
                col = (1.0, 0.25, 0.2, 0.95)
            rg_r.append((a.x, y, a.z, r))
            rg_c.append(col)
        self.shadows.set(np.asarray(sh_r, np.float32).reshape(-1, 4), np.asarray(sh_c, np.float32).reshape(-1, 4))
        self.rings.set(np.asarray(rg_r, np.float32).reshape(-1, 4), np.asarray(rg_c, np.float32).reshape(-1, 4))
        self._draw_bars()

    def _draw_bars(self) -> None:
        """2D health / mana / progress bars above units and buildings."""
        show_all = self.show_all_bars
        hover = getattr(self.game.controls, "hover", None) if self.game.controls is not None else None
        items = []
        for u in self.units:
            if u.alive and u.on_screen and (show_all or u.selected or u.hp < u.max_hp or u is hover):
                items.append(u)
        for b in self.buildings:
            if b.alive and b.visible and b.node is not None and not b.node.isHidden() and                     (show_all or b.selected or b.hp < b.max_hp or not b.complete or b is hover or b.queue):
                items.append(b)
        if not items:
            self.bars.clear()
            return
        n = len(items)
        pts = np.empty((n, 3), np.float32)
        for i, a in enumerate(items):
            pts[i] = (a.x, a.y + a.height + (0.5 if a.is_unit else 0.4), a.z)
        ui, front = self.cam.project(pts)
        zoom = 48.0 / max(self.cam.distance, 10.0)
        rects, cols = [], []
        for i, a in enumerate(items):
            if not front[i]:
                continue
            x, y = float(ui[i, 0]), float(ui[i, 1])
            if y > 0.455 or y < -0.225:      # keep bars inside the 3D view (not over the HUD)
                continue
            if a.is_unit:
                w = min(0.075, max(0.016, 0.022 * zoom * (0.75 + a.radius * 0.6)))
            else:
                w = min(0.16, max(0.03, 0.012 * zoom * a.footprint * 2.0))
            h = max(0.0035, 0.0052 * zoom ** 0.5)
            x0, x1 = x - w / 2, x + w / 2
            rects.append((x0 - 0.0015, y - 0.0015, x1 + 0.0015, y + h + 0.0015))
            cols.append((0.02, 0.02, 0.02, 0.85))
            f = max(0.0, min(1.0, a.hp_frac))
            if a.owner is not None and self.human is not None and a.owner is not self.human:
                c = (0.95, 0.25 + 0.3 * f, 0.15, 1.0)
            else:
                c = (min(1.0, 2.0 - 2.0 * f), min(1.0, 2.0 * f), 0.1, 1.0)
            rects.append((x0, y, x0 + w * f, y + h))
            cols.append(c)
            yy = y - h - 0.002
            if a.is_unit and a.max_mana > 0 and (a.owner is self.human or self.human is None):
                rects.append((x0 - 0.0015, yy - 0.0015, x1 + 0.0015, yy + h * 0.7 + 0.001))
                cols.append((0.02, 0.02, 0.02, 0.85))
                rects.append((x0, yy, x0 + w * a.mana / a.max_mana, yy + h * 0.7))
                cols.append((0.25, 0.5, 1.0, 1.0))
            elif a.is_building and (not a.complete or a.queue):
                prog = a.build_progress if not a.complete else a.queue[0].frac
                rects.append((x0 - 0.0015, yy - 0.0015, x1 + 0.0015, yy + h * 0.7 + 0.001))
                cols.append((0.02, 0.02, 0.02, 0.85))
                rects.append((x0, yy, x0 + w * prog, yy + h * 0.7))
                cols.append((0.95, 0.85, 0.4, 1.0))
        self.bars.set(np.asarray(rects, np.float32).reshape(-1, 4), np.asarray(cols, np.float32).reshape(-1, 4))

    # ================================================================== teardown
    def destroy(self) -> None:
        self.fx.clear()
        self.bars.destroy()
        for u in self.units:
            u.rig.destroy()
        self.root.removeNode()
        self.env.sky.removeNode()
        render = self.base.render
        render.clearShader()
        events.emit("match_destroyed", match=self)
