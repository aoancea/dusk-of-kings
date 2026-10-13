"""The 3 x 4 command card: unit orders, build menus, training, research and abilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from ursina import Entity, color

from core import data
from core.events import events
from ui.icons import ability_icon, simple_icon, upgrade_icon
from ui.portraits import portrait
from ui.widgets import IconSlot, Tooltip

if TYPE_CHECKING:
    from core.game import Game

RED = (1.0, 0.4, 0.35)
GOLD_C = (1.0, 0.85, 0.4)
WHITE = (0.95, 0.92, 0.85)
GREY = (0.7, 0.68, 0.62)


@dataclass
class Command:
    key: str
    name: str
    icon: Any
    action: Callable[[], None]
    tooltip: list[tuple[str, Any]] = field(default_factory=list)
    enabled: bool = True
    active: bool = False


def _cost_line(cost: dict[str, int], supply: int = 0) -> str:
    parts = [f"{cost.get('gold', 0)} gold", f"{cost.get('timber', 0)} timber"]
    if supply:
        parts.append(f"{supply} supply")
    return "Cost: " + ", ".join(parts)


class CommandCard:
    """Builds the command list for the current selection and renders it as 12 icon slots."""

    COLS, ROWS = 4, 3

    def __init__(self, game: "Game", parent: Entity, center: tuple[float, float], size: float = 0.064, gap: float = 0.007) -> None:
        self.game = game
        self.menu: str | None = None    # None | "build"
        self.slots: list[IconSlot] = []
        self.commands: list[Command | None] = [None] * 12
        step = size + gap
        x0 = center[0] - step * (self.COLS - 1) / 2
        y0 = center[1] + step * (self.ROWS - 1) / 2
        for i in range(12):
            r, c = divmod(i, self.COLS)
            slot = IconSlot(parent, (x0 + c * step, y0 - r * step), size, on_click=self._click,
                            on_right_click=self._right_click, tooltip=self._tooltip)
            slot.data = i
            self.slots.append(slot)
        self._refresh_t = 0.0
        self._sig: tuple = ()

    # ------------------------------------------------------------------ building the list
    @property
    def match(self):
        return self.game.match

    def _player(self):
        return self.match.human if self.match else None

    def build_commands(self) -> list[Command | None]:
        m = self.match
        ctl = self.game.controls
        out: list[Command | None] = [None] * 12
        if m is None or ctl is None:
            return out
        p = self._player()
        own = ctl.own_selection()
        if not own:
            return out
        units = [a for a in own if a.is_unit]
        if units:
            if self.menu == "build" and any(u.is_worker for u in units):
                return self._build_menu(p)
            self.menu = None
            mode = ctl.mode
            out[0] = Command("m", "Move", simple_icon("move", (0.15, 0.3, 0.15)), lambda: ctl.begin_mode("move"),
                             [("Move  [M]", GOLD_C), ("Walk to a location, ignoring enemies.", WHITE)], active=mode == "move")
            out[1] = Command("s", "Stop", simple_icon("stop", (0.3, 0.12, 0.1)), lambda: m.order_units(ctl.selected_units(), "stop"),
                             [("Stop  [S]", GOLD_C), ("Cancel all orders.", WHITE)])
            out[2] = Command("h", "Hold Position", simple_icon("hold", (0.2, 0.22, 0.3)),
                             lambda: m.order_units(ctl.selected_units(), "hold"),
                             [("Hold Position  [H]", GOLD_C), ("Stay put and attack enemies in range.", WHITE)])
            if any(u.attack for u in units):
                out[3] = Command("a", "Attack", simple_icon("sword", (0.4, 0.12, 0.08)), lambda: ctl.begin_mode("attack"),
                                 [("Attack  [A]", GOLD_C), ("Attack a target, or attack-move: fight", WHITE),
                                  ("everything met on the way.", WHITE)], active=mode == "attack")
            out[4] = Command("p", "Patrol", simple_icon("patrol", (0.3, 0.25, 0.1)), lambda: ctl.begin_mode("patrol"),
                             [("Patrol  [P]", GOLD_C), ("Walk back and forth, engaging enemies.", WHITE)], active=mode == "patrol")
            workers = [u for u in units if u.is_worker]
            if workers:
                out[5] = Command("g", "Gather", simple_icon("pickaxe", (0.3, 0.25, 0.12)), lambda: ctl.begin_mode("gather"),
                                 [("Gather  [G]", GOLD_C), ("Mine gold from a mine or chop timber from trees.", WHITE)],
                                 active=mode == "gather")
                if any(w.carry > 0 for w in workers):
                    out[6] = Command("r", "Return Cargo", simple_icon("return", (0.3, 0.25, 0.12)),
                                     lambda: m.economy.order_return(ctl.selected_units()),
                                     [("Return Cargo  [R]", GOLD_C), ("Bring carried resources to the nearest drop-off.", WHITE)])
                out[8] = Command("b", "Build", simple_icon("hammer", (0.35, 0.25, 0.1)), self._open_build,
                                 [("Build  [B]", GOLD_C), ("Construct buildings.", WHITE)])
            casters = [u for u in units if u.abilities]
            if casters:
                seen: list[str] = []
                for u in casters:
                    for aid in u.abilities:
                        if aid not in seen:
                            seen.append(aid)
                for k, aid in enumerate(seen[:3]):
                    out[9 + k] = self._ability_cmd(aid, casters)
            return out
        b = own[0]
        if b.is_building:
            return self._building_card(b, p)
        return out

    def _open_build(self) -> None:
        self.menu = "build"
        self._sig = ()

    def _build_menu(self, p) -> list[Command | None]:
        out: list[Command | None] = [None] * 12
        ctl = self.game.controls
        bdefs = data.buildings()
        for i, bid in enumerate(p.fdef["build_menu"][:11]):
            bd = bdefs[bid]
            missing = p.missing_requirements(bd)
            tip = [(f"{bd['name']}  [{bd['hotkey'].upper()}]", GOLD_C), (_cost_line(bd["cost"]), WHITE),
                   (f"Build time: {bd['build_time']}s", GREY), (bd.get("description", ""), WHITE)]
            if missing:
                tip.append(("Requires: " + ", ".join(missing), RED))
            elif not p.can_afford(bd["cost"]):
                tip.append(("Not enough resources", RED))

            def act(bid=bid, missing=missing) -> None:
                if missing:
                    ctl.notify("Requires " + ", ".join(missing))
                    return
                if not p.can_afford(bdefs[bid]["cost"]):
                    ctl.notify("Not enough gold" if p.gold < bdefs[bid]["cost"].get("gold", 0) else "Not enough timber")
                    return
                ctl.begin_mode("build", bid)

            out[i] = Command(bd["hotkey"], bd["name"], portrait("building", bid, p.color), act, tip, enabled=not missing,
                             active=ctl.mode == "build" and ctl.mode_arg == bid)
        out[11] = Command("escape", "Back", simple_icon("back", (0.25, 0.22, 0.2)), self._close_build, [("Back  [Esc]", GOLD_C)])
        return out

    def _close_build(self) -> None:
        self.menu = None
        if self.game.controls is not None and self.game.controls.mode == "build":
            self.game.controls.cancel_mode()
        self._sig = ()

    def _ability_cmd(self, aid: str, casters: list) -> Command:
        a = data.abilities()[aid]
        m = self.match
        ctl = self.game.controls
        ready = any(m.abilities.ready(u, aid) for u in casters)
        tip = [(f"{a['name']}  [{a['hotkey'].upper()}]", GOLD_C), (f"Mana: {a['mana']}   Cooldown: {a['cooldown']}s", WHITE),
               (a.get("description", ""), WHITE)]
        if a.get("autocast"):
            on = any(aid in u.autocast for u in casters)
            tip.append((f"Right-click to toggle autocast ({'on' if on else 'off'})", GREY))

        def act() -> None:
            if a["target"] == "self":
                err = m.abilities.order_cast(ctl.selected_units(), aid)
                if err:
                    ctl.notify(err)
            else:
                ctl.begin_mode("cast", aid)

        cmd = Command(a["hotkey"], a["name"], ability_icon(aid), act, tip, enabled=ready,
                      active=ctl.mode == "cast" and ctl.mode_arg == aid)
        cmd.autocast = aid  # type: ignore[attr-defined]
        return cmd

    def _building_card(self, b, p) -> list[Command | None]:
        out: list[Command | None] = [None] * 12
        if not b.complete:
            out[11] = Command("escape", "Cancel", simple_icon("x", (0.3, 0.1, 0.08)), lambda: b.cancel(),
                              [("Cancel construction  [Esc]", GOLD_C), ("Refunds 75% of the cost.", WHITE)])
            return out
        udefs = data.units()
        slot = 0
        for uid in b.trains():
            ud = udefs[uid]
            missing = p.missing_requirements(ud)
            tip = [(f"Train {ud['name']}  [{ud['hotkey'].upper()}]", GOLD_C),
                   (_cost_line(ud["cost"], ud.get("supply", 1)), WHITE), (f"Time: {ud['build_time']}s", GREY),
                   (ud.get("description", ""), WHITE)]
            if missing:
                tip.append(("Requires: " + ", ".join(missing), RED))

            def act(uid=uid) -> None:
                err = b.enqueue_unit(uid)
                if err:
                    self.game.controls.notify(err)
                else:
                    events.emit("sound", name="click")

            out[slot] = Command(ud["hotkey"], ud["name"], portrait("unit", uid, p.color), act, tip, enabled=not missing)
            slot += 1
        ups = data.upgrades()
        research = list(b.researches())
        th = b.defn.get("upgrades_to")
        if th:
            research.append("castle_upgrade" if p.faction == "alliance" else "stronghold_upgrade")
        shown_keys: set[str] = set()
        for up_id in research:
            u = ups[up_id]
            if up_id in p.upgrades:
                continue
            if u.get("requires_upgrade") and u["requires_upgrade"] not in p.upgrades and u["requires_upgrade"] not in p.researching:
                continue
            if u["hotkey"] in shown_keys:
                continue
            if up_id in p.researching and not any(q.type_id == up_id for q in b.queue):
                continue
            shown_keys.add(u["hotkey"])
            missing = p.missing_requirements(u)
            busy = up_id in p.researching
            tip = [(f"{u['name']}  [{u['hotkey'].upper()}]", GOLD_C), (_cost_line(u["cost"]), WHITE),
                   (f"Time: {u['time']}s", GREY), (u.get("description", ""), WHITE)]
            if missing:
                tip.append(("Requires: " + ", ".join(missing), RED))
            if busy:
                tip.append(("Researching...", GOLD_C))

            def act(up_id=up_id) -> None:
                err = b.enqueue_research(up_id)
                if err:
                    self.game.controls.notify(err)
                else:
                    events.emit("sound", name="click")

            icon = portrait("building", u["town_hall_upgrade"], p.color) if u.get("town_hall_upgrade") else upgrade_icon(up_id)
            pos = slot if slot < 8 else 8
            out[pos] = Command(u["hotkey"], u["name"], icon, act, tip, enabled=not missing and not busy)
            slot += 1
        if b.queue:
            out[11] = Command("escape", "Cancel", simple_icon("x", (0.3, 0.1, 0.08)), lambda: b.cancel(-1),
                              [("Cancel last in queue  [Esc]", GOLD_C), ("Fully refunded.", WHITE)])
        return out

    # ------------------------------------------------------------------ interaction
    def _click(self, slot: IconSlot) -> None:
        cmd = self.commands[slot.data]
        if cmd is not None:
            cmd.action()
            events.emit("sound", name="click")
            self._sig = ()

    def _right_click(self, slot: IconSlot) -> None:
        cmd = self.commands[slot.data]
        aid = getattr(cmd, "autocast", None) if cmd is not None else None
        if aid and data.abilities()[aid].get("autocast"):
            units = [u for u in self.game.controls.selected_units() if aid in u.abilities]
            on = any(aid in u.autocast for u in units)
            for u in units:
                if on:
                    u.autocast.discard(aid)
                else:
                    u.autocast.add(aid)
            events.emit("notice", player=self._player(), text=f"Autocast {'off' if on else 'on'}")
            self._sig = ()

    def _tooltip(self, slot: IconSlot) -> list | None:
        cmd = self.commands[slot.data]
        return cmd.tooltip if cmd is not None else None

    def hotkey(self, key: str) -> bool:
        """Trigger the command bound to ``key``. Returns True if one was found."""
        self.refresh(force=True)
        for cmd in self.commands:
            if cmd is not None and cmd.key == key:
                cmd.action()
                self._sig = ()
                return True
        return False

    def refresh(self, force: bool = False) -> None:
        cmds = self.build_commands()
        p = self._player()
        sig = tuple((c.key, c.name, c.enabled, c.active, id(c.icon)) if c else None for c in cmds)
        sig += (p.gold, p.timber) if p is not None else ()
        if sig == self._sig and not force:
            self.commands = cmds
            return
        self._sig = sig
        self.commands = cmds
        for slot, cmd in zip(self.slots, cmds):
            if cmd is None:
                slot.set_icon(None)
                slot.key_text.text = ""
                slot.set_dim(False)
                slot.color = color.rgba(0.08, 0.07, 0.06, 0.85)
                continue
            slot.set_icon(cmd.icon, border=(1.0, 0.85, 0.3) if cmd.active else None)
            slot.key_text.text = "Esc" if cmd.key == "escape" else cmd.key.upper()
            slot.set_dim(not cmd.enabled)
            slot.color = color.rgba(0.12, 0.1, 0.08, 0.9)
        tt = Tooltip.get()
        if tt.enabled and tt.owner in self.slots:
            lines = self._tooltip(tt.owner)
            if lines:
                tt.show(lines, tt.owner)
            else:
                tt.hide()

    def update(self, dt: float) -> None:
        self._refresh_t -= dt
        if self._refresh_t <= 0:
            self._refresh_t = 0.15
            self.refresh()
