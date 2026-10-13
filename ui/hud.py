"""In-match HUD: resource bar, day/night clock, minimap, selection panel, command card and notices."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ursina import Entity, Text, camera, color, held_keys, window

from core import data
from core.events import events
from settings import NIGHT_END, NIGHT_START
from ui.command_card import CommandCard
from ui.icons import ability_icon, simple_icon
from ui.minimap import Minimap
from ui.portraits import portrait, render_portraits
from ui.widgets import GOLD, PANEL_BORDER, TEXT, Bar, IconSlot, Tooltip, label, quad, rgb

if TYPE_CHECKING:
    from core.game import Game

PANEL_H = 0.26
DIM = color.rgb(0.7, 0.68, 0.62)


class HUD:
    """Created once; attached to each new match."""

    def __init__(self, game: "Game") -> None:
        self.game = game
        self.match = None
        self.root = Entity(parent=camera.ui, enabled=False)
        self.built = False
        self.notices: list[tuple[Text, float]] = []
        self._sel_sig: tuple = ()
        self._t = 0.0
        events.on("notice", self._on_notice)
        events.on("alert", self._on_alert)
        events.on("unit_trained", self._on_trained)
        events.on("building_complete", self._on_built)
        events.on("research_complete", self._on_research)
        events.on("selection_changed", lambda **_: self._force_panel())

    # ================================================================== layout
    def _build(self) -> None:
        ar = window.aspect_ratio
        r = self.root
        L, R = -ar / 2, ar / 2
        bottom = -0.5
        # bottom panel
        self.panel = quad(r, (0, bottom + PANEL_H / 2), (ar, PANEL_H), color.rgba(0.07, 0.055, 0.045, 1.0), z=0.02)
        self.panel.collider = "box"
        quad(r, (0, bottom + PANEL_H + 0.002), (ar, 0.004), PANEL_BORDER, z=0.015)
        # top bar
        self.top = quad(r, (0, 0.5 - 0.018), (ar, 0.036), color.rgba(0.07, 0.055, 0.045, 0.9), z=0.02)
        self.top.collider = "box"
        quad(r, (0, 0.5 - 0.037), (ar, 0.003), PANEL_BORDER, z=0.015)
        x = R - 0.66
        self.gold_icon = Entity(parent=r, model="quad", texture=simple_icon("gold", (0.25, 0.2, 0.08)), scale=0.026,
                                position=(x, 0.482, -0.01))
        self.gold_text = label(r, "0", (x + 0.02, 0.493), 1.0, GOLD)
        self.timber_icon = Entity(parent=r, model="quad", texture=simple_icon("timber", (0.2, 0.15, 0.08)), scale=0.026,
                                  position=(x + 0.15, 0.482, -0.01))
        self.timber_text = label(r, "0", (x + 0.17, 0.493), 1.0, color.rgb(0.85, 0.7, 0.45))
        self.supply_icon = Entity(parent=r, model="quad", texture=simple_icon("supply", (0.2, 0.18, 0.15)), scale=0.026,
                                  position=(x + 0.3, 0.482, -0.01))
        self.supply_text = label(r, "0/0", (x + 0.32, 0.493), 1.0, TEXT)
        self.clock_icon = Entity(parent=r, model="quad", scale=0.026, position=(L + 0.03, 0.482, -0.01))
        self.clock_text = label(r, "", (L + 0.05, 0.493), 0.95, TEXT)
        self.time_text = label(r, "", (0, 0.493), 0.9, DIM, origin=(0, 0.5))
        self.menu_btn = Entity(parent=r, model="quad", scale=(0.13, 0.028), position=(R - 0.075, 0.482, -0.01),
                               color=color.rgba(0.32, 0.18, 0.08, 1), collider="box")
        Text(parent=self.menu_btn, text="Menu (F10)", origin=(0, 0), scale=(7.0, 33.0), color=GOLD, z=-0.01)
        self.menu_btn.on_click = self._open_menu
        # minimap
        mm_size = PANEL_H - 0.03
        self.minimap = Minimap(self.game, r, (L + mm_size / 2 + 0.015, bottom + PANEL_H / 2), mm_size)
        # command card
        self.card = CommandCard(self.game, r, (R - 0.16, bottom + PANEL_H / 2 - 0.005))
        # selection panel
        sx0 = L + mm_size + 0.05
        sx1 = R - 0.33
        self.sel_x0, self.sel_x1 = sx0, sx1
        cy = bottom + PANEL_H / 2
        self.sel_root = Entity(parent=r)
        self.portrait = Entity(parent=self.sel_root, model="quad", scale=0.15, position=(sx0 + 0.08, cy + 0.01, -0.01))
        self.portrait_frame = quad(self.sel_root, (sx0 + 0.08, cy + 0.01), (0.156, 0.156), PANEL_BORDER, z=0.0)
        tx = sx0 + 0.18
        self.name_text = label(self.sel_root, "", (tx, cy + 0.112), 1.35, GOLD)
        self.sub_text = label(self.sel_root, "", (tx, cy + 0.078), 0.85, DIM)
        self.hp_bar = Bar(self.sel_root, (tx, cy + 0.038), (0.3, 0.02), color.rgb(0.25, 0.75, 0.25), text_scale=0.8)
        self.mp_bar = Bar(self.sel_root, (tx, cy + 0.013), (0.3, 0.016), color.rgb(0.25, 0.45, 0.95), text_scale=0.7)
        self.stats_text = label(self.sel_root, "", (tx, cy - 0.006), 0.85, TEXT)
        self.status_text = label(self.sel_root, "", (tx, cy - 0.085), 0.85, color.rgb(0.75, 0.9, 1.0))
        self.prog_bar = Bar(self.sel_root, (tx, cy - 0.06), (0.3, 0.018), color.rgb(0.95, 0.8, 0.35), text_scale=0.75)
        # production queue slots
        self.queue_slots: list[IconSlot] = []
        for i in range(5):
            s = IconSlot(self.sel_root, (tx + 0.36 + i * 0.058, cy + 0.02), 0.052, on_click=self._cancel_queue,
                         tooltip=self._queue_tip)
            s.data = i
            self.queue_slots.append(s)
        self.queue_label = label(self.sel_root, "Training", (tx + 0.335, cy + 0.072), 0.8, DIM)
        # multi-selection grid
        self.multi_slots: list[IconSlot] = []
        cols = max(6, int((sx1 - sx0) / 0.056))
        self.multi_cols = cols
        for i in range(cols * 3):
            rr, cc = divmod(i, cols)
            s = IconSlot(r, (sx0 + 0.03 + cc * 0.056, cy + 0.08 - rr * 0.07), 0.05, on_click=self._multi_click,
                         tooltip=self._multi_tip)
            s.data = i
            s.hp = Entity(parent=s, model="quad", origin=(-0.5, 0), position=(-0.45, -0.56, -0.04), scale=(0.9, 0.09),
                          color=color.green)
            s.enabled = False
            self.multi_slots.append(s)
        self.multi_units: list[Any] = []
        # notices
        self.notice_root = Entity(parent=r, position=(0, -0.2, -0.5))
        # alert banner
        self.banner = label(r, "", (0, 0.43), 1.2, color.rgb(1.0, 0.45, 0.35), origin=(0, 0), z=-0.5)
        self.banner_t = 0.0
        self.built = True

    # ================================================================== match lifecycle
    def attach(self, match) -> None:
        self.match = match
        render_portraits(self.game.base, [p.color for p in match.players])
        if not self.built:
            self._build()
        self.root.enabled = True
        self.minimap.attach(match)
        self.card.menu = None
        self._sel_sig = ()
        self.set_visible(match.human is not None)

    def detach(self) -> None:
        self.match = None
        if self.built:
            self.minimap.detach()
        self.root.enabled = False
        Tooltip.get().hide()
        for t, _ in self.notices:
            t.disable()
        self.notices.clear()

    def set_visible(self, visible: bool) -> None:
        self.root.enabled = visible

    def _open_menu(self) -> None:
        if self.game.menus is not None:
            self.game.menus.show_pause()

    # ================================================================== events
    def _notice(self, text: str, col: Any = (1.0, 0.85, 0.4), life: float = 2.6) -> None:
        if not self.built:
            return
        for t, _ in self.notices:
            t.y += 0.03
        t = label(self.notice_root, text, (0, 0), 1.1, rgb(col), origin=(0, 0))
        self.notices.append((t, life))
        if len(self.notices) > 4:
            old, _ = self.notices.pop(0)
            old.disable()

    def _on_notice(self, player=None, text: str = "", **_) -> None:
        m = self.match
        if m is None or (player is not None and player is not m.human):
            return
        self._notice(text)

    def _on_alert(self, x: float, z: float, **_) -> None:
        if self.match is None or self.match.human is None:
            return
        self.banner.text = "We are under attack!  (Space to view)"
        self.banner_t = 3.5
        events.emit("sound", name="alert")

    def _on_trained(self, unit=None, building=None, **_) -> None:
        if self.match is not None and unit is not None and unit.owner is self.match.human:
            self._notice(f"{unit.name} ready", (0.7, 1.0, 0.7), 2.0)

    def _on_built(self, building=None, **_) -> None:
        if self.match is not None and building is not None and building.owner is self.match.human:
            self._notice(f"{building.name} complete", (0.7, 1.0, 0.7), 2.4)

    def _on_research(self, player=None, upgrade: str = "", **_) -> None:
        if self.match is not None and player is self.match.human:
            self._notice(f"Research complete: {data.upgrades()[upgrade]['name']}", (0.7, 0.9, 1.0), 3.0)

    # ================================================================== input
    def input(self, key: str) -> bool:
        if self.match is None or not self.root.enabled:
            return False
        if key in ("f10",):
            self._open_menu()
            return True
        if self.minimap.input(key):
            return True
        ctl = self.game.controls
        if key in ("left mouse down", "right mouse down") and (self.panel.hovered or self.top.hovered):
            return True
        if key == "escape":
            if ctl is not None and ctl.mode is not None:
                ctl.cancel_mode()
                return True
            if self.card.menu == "build":
                self.card._close_build()
                return True
            if self.card.hotkey("escape"):
                return True
            self._open_menu()
            return True
        if key == "alt":
            self.match.show_all_bars = True
            return True
        if key == "alt up":
            self.match.show_all_bars = False
            return True
        if len(key) == 1 and key.isalpha() and not held_keys["control"]:
            if self.card.hotkey(key):
                return True
        return False

    def _multi_click(self, slot: IconSlot) -> None:
        if slot.data >= len(self.multi_units):
            return
        u = self.multi_units[slot.data]
        ctl = self.game.controls
        if held_keys["shift"]:
            sel = [a for a in self.match.selection if a is not u]
            ctl.set_selection(sel)
        else:
            ctl.set_selection([u])

    def _multi_tip(self, slot: IconSlot) -> list | None:
        if slot.data >= len(self.multi_units):
            return None
        u = self.multi_units[slot.data]
        return [(u.name, (1.0, 0.85, 0.4)), (f"HP {int(u.hp)}/{int(u.max_hp)}", (0.9, 0.9, 0.9))]

    def _cancel_queue(self, slot: IconSlot) -> None:
        b = self._single()
        if b is not None and b.is_building and slot.data < len(b.queue):
            b.cancel(slot.data)

    def _queue_tip(self, slot: IconSlot) -> list | None:
        b = self._single()
        if b is None or not b.is_building or slot.data >= len(b.queue):
            return None
        q = b.queue[slot.data]
        name = data.units()[q.type_id]["name"] if q.kind == "unit" else data.upgrades()[q.type_id]["name"]
        return [(name, (1.0, 0.85, 0.4)), ("Click to cancel (refund)", (0.8, 0.8, 0.8))]

    # ================================================================== update
    def _single(self):
        m = self.match
        if m is None:
            return None
        sel = [a for a in m.selection if a.alive]
        return sel[0] if len(sel) == 1 else None

    def _force_panel(self) -> None:
        self._sel_sig = ()
        if self.built:
            self.card.menu = None
            self.card.refresh(force=True)

    def update(self, dt: float) -> None:
        m = self.match
        if m is None or not self.built or not self.root.enabled:
            return
        p = m.human
        if p is not None:
            self.gold_text.text = str(p.gold)
            self.timber_text.text = str(p.timber)
            used, cap = p.supply_used, p.supply_max
            self.supply_text.text = f"{used}/{cap}"
            self.supply_text.color = color.rgb(1.0, 0.4, 0.3) if used >= cap else TEXT
        h = m.env.hour
        night = h >= NIGHT_START or h < NIGHT_END
        hh, mm = int(h), int((h - int(h)) * 60)
        if night:
            bonus = "Night - Host +15% damage, Alliance sight -25%"
        else:
            bonus = "Day - Alliance +12% damage"
        self.clock_text.text = f"{hh:02d}:{mm:02d}  {bonus}"
        self.clock_icon.texture = simple_icon("moon" if night else "sun", (0.08, 0.1, 0.2) if night else (0.35, 0.28, 0.1))
        t = int(m.time)
        self.time_text.text = f"{t // 60:02d}:{t % 60:02d}"
        # notices fade
        keep = []
        for txt, life in self.notices:
            life -= dt
            if life <= 0:
                txt.disable()
            else:
                txt.alpha = min(1.0, life / 0.6)
                keep.append((txt, life))
        self.notices = keep
        if self.banner_t > 0:
            self.banner_t -= dt
            if self.banner_t <= 0:
                self.banner.text = ""
        self.minimap.update(dt)
        self.card.update(dt)
        self._t -= dt
        if self._t <= 0:
            self._t = 0.1
            self._update_selection()

    def _update_selection(self) -> None:
        m = self.match
        sel = [a for a in m.selection if a.alive]
        if len(sel) != len(m.selection):
            m.selection[:] = sel
        single = sel[0] if len(sel) == 1 else None
        multi = len(sel) > 1
        sig = (len(sel), id(single), single.type_id if single else None)
        layout_changed = sig != self._sel_sig
        self._sel_sig = sig
        show_single = single is not None
        for e in (self.portrait, self.portrait_frame, self.name_text, self.sub_text, self.hp_bar, self.stats_text, self.status_text):
            if e.enabled != show_single:
                e.enabled = show_single
        if not show_single:
            self.mp_bar.enabled = False
            self.prog_bar.enabled = False
            self.queue_label.enabled = False
            for s in self.queue_slots:
                s.enabled = False
        if multi:
            self._show_multi(sel, layout_changed)
        else:
            for s in self.multi_slots:
                if s.enabled:
                    s.enabled = False
            self.multi_units = []
        if single is not None:
            self._show_single(single, layout_changed)

    def _show_multi(self, sel: list, changed: bool) -> None:
        units = sorted(sel, key=lambda a: (not a.is_unit, a.type_id))[: len(self.multi_slots)]
        self.multi_units = units
        for i, s in enumerate(self.multi_slots):
            if i < len(units):
                a = units[i]
                if not s.enabled:
                    s.enabled = True
                kind = "unit" if a.is_unit else "building"
                tex = portrait(kind, a.type_id, a.owner.color) if a.owner is not None else None
                if s.icon.texture != tex or not s.icon.enabled:
                    s.set_icon(tex)
                f = a.hp_frac
                s.hp.scale_x = 0.9 * f
                s.hp.color = color.rgb(min(1, 2 - 2 * f), min(1, 2 * f), 0.1)
            elif s.enabled:
                s.enabled = False

    def _show_single(self, a, changed: bool) -> None:
        m = self.match
        if changed:
            if a.is_mine:
                self.portrait.texture = simple_icon("gold", (0.3, 0.25, 0.1))
            else:
                kind = "unit" if a.is_unit else "building"
                self.portrait.texture = portrait(kind, a.type_id, a.owner.color)
            self.name_text.text = a.name
        owner = a.owner
        if a.is_mine:
            self.sub_text.text = "Neutral"
            self.hp_bar.set(a.gold, a.initial, f"Gold: {a.gold} / {a.initial}")
            self.hp_bar.set_color(color.rgb(0.95, 0.8, 0.25))
            self.stats_text.text = f"Miners inside: {len(a.inside)} / 5"
            self.status_text.text = "Depleted" if a.depleted else ""
            self.mp_bar.enabled = False
            self.prog_bar.enabled = False
            self.queue_label.enabled = False
            for s in self.queue_slots:
                s.enabled = False
            return
        self.sub_text.text = owner.name + ("" if owner is m.human else "  (enemy)")
        self.hp_bar.set(a.hp, a.max_hp, f"{int(a.hp)} / {int(a.max_hp)}")
        f = a.hp_frac
        self.hp_bar.set_color(color.rgb(min(1, 2 - 2 * f) * 0.85, min(1, 2 * f) * 0.75, 0.15))
        if a.is_unit:
            self._unit_info(a)
        else:
            self._building_info(a)

    def _unit_info(self, u) -> None:
        own = u.owner is self.match.human
        att = u.attack
        lines = []
        if att:
            dmg = att["damage"] + u.owner.damage_bonus(u.defn)
            rng = "melee" if u.is_melee else f"{att['range']:g}"
            lines.append(f"Damage {dmg:g} ({att['type']})   Range {rng}   Rate {att['cooldown']:g}s")
        lines.append(f"Armor {u.armor:g} ({u.armor_type})   Speed {u.speed:g}   Sight {u.sight:g}")
        self.stats_text.text = "\n".join(lines)
        if u.max_mana > 0 and own:
            self.mp_bar.enabled = True
            self.mp_bar.set(u.mana, u.max_mana, f"{int(u.mana)} / {int(u.max_mana)}")
        else:
            self.mp_bar.enabled = False
        status = []
        o = u.order
        if o is None:
            status.append("Attacking" if u.target is not None else "Idle")
        else:
            status.append({"move": "Moving", "attack_move": "Attack-moving", "attack": "Attacking", "patrol": "Patrolling",
                           "hold": "Holding position", "follow": "Following", "gather": "Gathering", "return": "Returning cargo",
                           "build": "Constructing", "cast": "Casting"}.get(o.kind, o.kind))
        if u.carry > 0:
            status.append(f"carrying {u.carry} {u.carry_kind}")
        if "slow" in u.buffs:
            status.append("SLOWED")
        if "frenzy" in u.buffs:
            status.append("FRENZY")
        self.status_text.text = ", ".join(status) if own else ""
        self.prog_bar.enabled = False
        self.queue_label.enabled = False
        for s in self.queue_slots:
            s.enabled = False

    def _building_info(self, b) -> None:
        own = b.owner is self.match.human
        lines = [f"Armor {b.armor:g} (fortified)"]
        if b.defn.get("supply"):
            lines[0] += f"   Provides {b.defn['supply']} supply"
        if b.attack:
            lines.append(f"Damage {b.attack['damage'] + b.owner.damage_bonus(b.defn):g} ({b.attack['type']})   Range {b.attack['range']:g}")
        if b.dropoff:
            lines.append("Drop-off: " + ", ".join(b.dropoff))
        self.stats_text.text = "\n".join(lines)
        self.mp_bar.enabled = False
        self.status_text.text = ""
        if not b.complete:
            self.prog_bar.enabled = True
            self.prog_bar.set(b.build_progress, 1.0, f"Constructing {int(b.build_progress * 100)}%")
        elif b.queue and own:
            self.prog_bar.enabled = True
            q = b.queue[0]
            name = data.units()[q.type_id]["name"] if q.kind == "unit" else data.upgrades()[q.type_id]["name"]
            self.prog_bar.set(q.frac, 1.0, f"{name} {int(q.frac * 100)}%")
        else:
            self.prog_bar.enabled = False
        show_q = own and b.complete and bool(b.trains() or b.researches() or b.defn.get("upgrades_to"))
        self.queue_label.enabled = show_q
        for i, s in enumerate(self.queue_slots):
            s.enabled = show_q
            if not show_q:
                continue
            if i < len(b.queue):
                q = b.queue[i]
                if q.kind == "unit":
                    tex = portrait("unit", q.type_id, b.owner.color)
                elif q.kind == "upgrade_hall":
                    tex = portrait("building", data.upgrades()[q.type_id]["town_hall_upgrade"], b.owner.color)
                else:
                    from ui.icons import upgrade_icon
                    tex = upgrade_icon(q.type_id)
                s.set_icon(tex)
                s.set_cooldown(q.time - q.progress if i == 0 else 0.0, q.time)
            else:
                s.set_icon(None)
                s.set_cooldown(0, 1)
