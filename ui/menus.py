"""Main menu, skirmish setup, pause menu, settings, how-to-play and the end-of-match summary."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable

from ursina import Entity, Text, application, camera, color, invoke, window

from core import data
from core.events import events
from core.match import MatchConfig, PlayerConfig
from settings import GAME_TITLE, RESOLUTIONS, VERSION, user_settings
from ui.widgets import GOLD, PANEL_BG, PANEL_BORDER, TEXT, label, make_button, quad

if TYPE_CHECKING:
    from core.game import Game

DIM = color.rgb(0.72, 0.68, 0.6)
SEL = color.rgba(0.55, 0.32, 0.1, 1)
UNSEL = color.rgba(0.2, 0.14, 0.09, 1)


class Screen(Entity):
    """A full-screen menu layer with a darkened backdrop."""

    def __init__(self, dim: float = 0.55) -> None:
        super().__init__(parent=camera.ui, z=-20, enabled=False)
        self.backdrop = Entity(parent=self, model="quad", scale=(4, 1.2), color=color.rgba(0, 0, 0, dim), z=0.05,
                               collider="box")

    def panel(self, size: tuple[float, float], pos: tuple[float, float] = (0, 0)) -> Entity:
        root = Entity(parent=self, position=(pos[0], pos[1], 0))
        quad(root, (0, 0), (size[0] + 0.01, size[1] + 0.01), PANEL_BORDER, z=0.02)
        quad(root, (0, 0), size, PANEL_BG, z=0.01)
        return root


class MenuController:
    """Owns every menu screen and the background scene shown behind the main menu."""

    def __init__(self, game: "Game") -> None:
        self.game = game
        self.current: Screen | None = None
        self.cfg = {"map": user_settings.last_map, "faction": user_settings.last_faction,
                    "enemy": user_settings.last_enemy, "difficulty": user_settings.last_difficulty}
        self._orbit = 0.0
        self._build_main()
        self._build_skirmish()
        self._build_pause()
        self._build_settings()
        self._build_help()
        self._build_end()
        self._back_target: Callable[[], None] = self.show_main
        events.on("match_over", self._on_match_over)

    # ================================================================== generic
    def _show(self, screen: Screen | None) -> None:
        if self.current is not None and self.current is not screen:
            self.current.enabled = False
        self.current = screen
        if screen is not None:
            screen.enabled = True

    def close(self) -> None:
        self._show(None)

    def input(self, key: str) -> bool:
        """Menus swallow input while open. Returns True when consumed."""
        if self.current is None:
            if key == "escape" and self.game.state == "playing" and self.game.match is not None and self.game.hud is None:
                self.show_pause()
                return True
            return False
        if key == "escape":
            if self.current is self.pause:
                self.resume()
            elif self.current in (self.settings, self.help):
                self._back_target()
            elif self.current is self.skirmish:
                self.show_main()
            return True
        return True

    def update(self, dt: float) -> None:
        g = self.game
        if self.current is self.main or self.current is self.skirmish:
            m = g.match
            if m is not None and m.human is None and not self._is_real_match():
                self._orbit += dt * 0.04
                m.cam.fx = 70 + math.sin(self._orbit) * 4
                m.cam.fz = 62 + math.cos(self._orbit * 0.7) * 2
                m.cam.distance = m.cam.target_distance = 34.0
                m.cam.pitch_override = 30.0

    def _is_real_match(self) -> bool:
        return getattr(self.game.match, "is_menu_scene", False) is False

    # ================================================================== main menu
    def _build_main(self) -> None:
        s = self.main = Screen(dim=0.25)
        ar = window.aspect_ratio
        quad(s, (-ar / 2 + 0.3, 0), (0.6, 1.0), color.rgba(0.03, 0.02, 0.02, 0.72), z=0.03)
        Text(parent=s, text=GAME_TITLE, position=(-ar / 2 + 0.3, 0.33, -0.01), origin=(0, 0), scale=3.4, color=GOLD)
        Text(parent=s, text="a real-time strategy game of the Twilight Age", position=(-ar / 2 + 0.3, 0.27, -0.01),
             origin=(0, 0), scale=0.95, color=DIM)
        y = 0.12
        for text, fn in (("Skirmish", self.show_skirmish), ("Settings", lambda: self.show_settings(self.show_main)),
                         ("How to Play", lambda: self.show_help(self.show_main)), ("Quit", application.quit)):
            make_button(s, text, (-ar / 2 + 0.3, y), (0.34, 0.06), fn, text_scale=1.2)
            y -= 0.085
        Text(parent=s, text=f"v{VERSION}  -  procedural assets, original world", position=(-ar / 2 + 0.3, -0.45, -0.01),
             origin=(0, 0), scale=0.75, color=DIM)

    def show_main(self) -> None:
        g = self.game
        if g.match is None or self._is_real_match():
            self._start_menu_scene()
        self._show(self.main)
        if g.hud is not None:
            g.hud.set_visible(False)
        events.emit("music", name="theme")

    def _start_menu_scene(self) -> None:
        g = self.game
        cfg = MatchConfig(map_id="greyfen_crossing", players=[PlayerConfig("host", True), PlayerConfig("alliance", True)],
                          human=None, fog=False, ai_enabled=False)
        m = g.start_match(cfg)
        m.is_menu_scene = True
        m.env.hour = 17.3
        m.env.time_scale = 0.0
        al = m.players[1]
        roster = ("knight", "spearman", "spearman", "spearman", "knight", "longbowman", "longbowman", "loremaster",
                  "longbowman", "forest_warden", "spearman", "trebuchet")
        for k, t in enumerate(roster):
            u = m.spawn_unit(al, t, 70 + (k % 6) * 2.6, 64 - (k // 6) * 3.0)
            u.yaw = 180
        g.state = "menu"
        if g.hud is not None:
            g.hud.set_visible(False)

    # ================================================================== skirmish
    def _build_skirmish(self) -> None:
        s = self.skirmish = Screen(dim=0.45)
        p = s.panel((1.24, 0.82))
        label(p, "Skirmish", (0, 0.37), 2.0, GOLD, origin=(0, 0))
        self._opt_buttons: dict[str, list[tuple[str, Any]]] = {}
        maps = data.maps()
        factions = data.factions()
        self._row(p, "Map", "map", [(k, v["name"]) for k, v in maps.items()], 0.27)
        self.map_desc = label(p, "", (-0.56, 0.205), 0.8, DIM)
        self._row(p, "Your faction", "faction", [(k, v["name"]) for k, v in factions.items()], 0.1)
        self.fac_desc = label(p, "", (-0.56, 0.035), 0.8, DIM)
        self._row(p, "Enemy faction", "enemy", [(k, v["name"]) for k, v in factions.items()], -0.07)
        self._row(p, "Difficulty", "difficulty", [("easy", "Easy"), ("normal", "Normal"), ("hard", "Hard")], -0.19)
        self.diff_desc = label(p, "", (-0.56, -0.255), 0.8, DIM)
        make_button(p, "Start Battle", (0.36, -0.35), (0.3, 0.065), self.start_skirmish, col=color.rgba(0.45, 0.25, 0.06, 1),
                    text_scale=1.2)
        make_button(p, "Back", (-0.4, -0.35), (0.2, 0.055), self.show_main)
        self._refresh_skirmish()

    def _row(self, parent: Entity, title: str, key: str, options: list[tuple[str, str]], y: float) -> None:
        label(parent, title, (-0.56, y + 0.012), 1.05, TEXT)
        btns = []
        w = 0.3 if len(options) <= 2 else 0.2
        for i, (val, name) in enumerate(options):
            def pick(val=val, key=key) -> None:
                self.cfg[key] = val
                self._refresh_skirmish()
            b = make_button(parent, name, (-0.18 + i * (w + 0.02) + w / 2, y), (w, 0.05), pick)
            btns.append((val, b))
        self._opt_buttons[key] = btns

    def _refresh_skirmish(self) -> None:
        for key, btns in self._opt_buttons.items():
            for val, b in btns:
                c = SEL if self.cfg[key] == val else UNSEL
                b.color = c
                b.highlight_color = color.rgba(c[0] * 1.4, c[1] * 1.4, c[2] * 1.4, 1)
        self.map_desc.text = data.maps()[self.cfg["map"]]["description"]
        self.fac_desc.text = data.factions()[self.cfg["faction"]]["description"]
        self.diff_desc.text = {"easy": "A relaxed opponent: slow to build and to attack.",
                               "normal": "A capable commander that expands and attacks in waves.",
                               "hard": "An aggressive, efficient opponent with a gathering bonus."}[self.cfg["difficulty"]]

    def show_skirmish(self) -> None:
        self._refresh_skirmish()
        self._show(self.skirmish)

    def start_skirmish(self) -> None:
        if self.game.match is not None:
            self.game.match.cam.pitch_override = None
        c = self.cfg
        user_settings.last_map = c["map"]
        user_settings.last_faction = c["faction"]
        user_settings.last_enemy = c["enemy"]
        user_settings.last_difficulty = c["difficulty"]
        user_settings.save()
        cfg = MatchConfig(map_id=c["map"], players=[PlayerConfig(c["faction"], False), PlayerConfig(c["enemy"], True, c["difficulty"])],
                          human=0, fog=True)
        self.close()
        self.game.start_match(cfg)
        events.emit("music", name=None)

    # ================================================================== pause
    def _build_pause(self) -> None:
        s = self.pause = Screen(dim=0.5)
        p = s.panel((0.46, 0.56))
        label(p, "Paused", (0, 0.22), 1.8, GOLD, origin=(0, 0))
        y = 0.12
        for text, fn in (("Resume", self.resume), ("Settings", lambda: self.show_settings(self.show_pause)),
                         ("How to Play", lambda: self.show_help(self.show_pause)), ("Surrender", self.surrender),
                         ("Quit to Main Menu", self.quit_to_main)):
            make_button(p, text, (0, y), (0.34, 0.055), fn)
            y -= 0.075

    def show_pause(self) -> None:
        g = self.game
        if g.match is None or g.state != "playing":
            return
        g.paused = True
        self._show(self.pause)

    def resume(self) -> None:
        self.game.paused = False
        self.close()

    def surrender(self) -> None:
        m = self.game.match
        if m is not None and m.human is not None and not m.over:
            m.human.defeated = True
            m.over = True
            m.winner = next((p for p in m.players if p is not m.human), None)
            self.game.paused = False
            self.close()
            events.emit("match_over", winner=m.winner)

    def quit_to_main(self) -> None:
        self.game.paused = False
        self.close()
        self.game.end_match()
        self.show_main()

    # ================================================================== settings
    def _build_settings(self) -> None:
        s = self.settings = Screen(dim=0.55)
        p = s.panel((0.8, 0.7))
        label(p, "Settings", (0, 0.3), 1.8, GOLD, origin=(0, 0))
        self._setting_rows: list[Callable[[], None]] = []
        y = 0.2
        for name, attr, step, lo, hi in (("Scroll speed", "scroll_speed", 0.1, 0.3, 3.0), ("Master volume", "master_volume", 0.1, 0.0, 1.0),
                                          ("Effects volume", "sfx_volume", 0.1, 0.0, 1.0), ("Ambience volume", "ambient_volume", 0.1, 0.0, 1.0)):
            self._stepper(p, name, attr, step, lo, hi, y)
            y -= 0.075
        self._toggle(p, "Edge scrolling", "edge_scroll", y)
        y -= 0.075
        self._toggle(p, "Show FPS", "show_fps", y)
        y -= 0.075
        self._toggle(p, "Fullscreen", "fullscreen", y)
        y -= 0.075
        label(p, "Resolution", (-0.34, y + 0.012), 1.0, TEXT)
        self.res_text = label(p, "", (0.12, y + 0.012), 1.0, GOLD, origin=(0, 0.5))
        make_button(p, "-", (-0.02, y), (0.05, 0.045), lambda: self._res(-1))
        make_button(p, "+", (0.26, y), (0.05, 0.045), lambda: self._res(1))
        self._setting_rows.append(lambda: setattr(self.res_text, "text", "x".join(str(v) for v in user_settings.resolution)))
        make_button(p, "Back", (0, -0.3), (0.22, 0.055), lambda: self._back_target())

    def _stepper(self, parent: Entity, name: str, attr: str, step: float, lo: float, hi: float, y: float) -> None:
        label(parent, name, (-0.34, y + 0.012), 1.0, TEXT)
        val = label(parent, "", (0.12, y + 0.012), 1.0, GOLD, origin=(0, 0.5))

        def change(d: float) -> None:
            v = round(min(hi, max(lo, getattr(user_settings, attr) + d)), 2)
            setattr(user_settings, attr, v)
            user_settings.save()
            self._apply_live()
            refresh()

        def refresh() -> None:
            val.text = f"{getattr(user_settings, attr):.1f}"

        make_button(parent, "-", (-0.02, y), (0.05, 0.045), lambda: change(-step))
        make_button(parent, "+", (0.26, y), (0.05, 0.045), lambda: change(step))
        self._setting_rows.append(refresh)

    def _toggle(self, parent: Entity, name: str, attr: str, y: float) -> None:
        label(parent, name, (-0.34, y + 0.012), 1.0, TEXT)
        btn = make_button(parent, "", (0.12, y), (0.18, 0.045), lambda: None)

        def flip() -> None:
            setattr(user_settings, attr, not getattr(user_settings, attr))
            user_settings.save()
            self._apply_live()
            refresh()

        def refresh() -> None:
            btn.text = "On" if getattr(user_settings, attr) else "Off"
            if btn.text_entity:
                btn.text_entity.color = GOLD

        btn.on_click = flip
        self._setting_rows.append(refresh)

    def _res(self, d: int) -> None:
        cur = tuple(user_settings.resolution)
        idx = RESOLUTIONS.index(cur) if cur in RESOLUTIONS else 1
        idx = (idx + d) % len(RESOLUTIONS)
        user_settings.resolution = list(RESOLUTIONS[idx])
        user_settings.save()
        self._apply_live()
        for r in self._setting_rows:
            r()

    def _apply_live(self) -> None:
        g = self.game
        if g.match is not None:
            g.match.cam.scroll_speed = float(user_settings.scroll_speed)
            g.match.cam.edge_scroll = bool(user_settings.edge_scroll)
        if window.fullscreen != bool(user_settings.fullscreen):
            window.fullscreen = bool(user_settings.fullscreen)
        if not window.fullscreen:
            size = tuple(user_settings.resolution)
            if tuple(window.size) != size:
                window.size = size
                window.center_on_screen()
        window.fps_counter.enabled = bool(user_settings.show_fps)

    def show_settings(self, back: Callable[[], None]) -> None:
        self._back_target = back
        for r in self._setting_rows:
            r()
        self._show(self.settings)

    # ================================================================== help
    def _build_help(self) -> None:
        s = self.help = Screen(dim=0.6)
        p = s.panel((1.3, 0.84))
        label(p, "How to Play", (0, 0.38), 1.8, GOLD, origin=(0, 0))
        left = [
            ("Goal", "Destroy every enemy building. Lose all of yours and the battle is lost."),
            ("Economy", "Workers mine gold and chop timber. Right-click a mine or a tree."),
            ("", "Build supply buildings (House / Warren) to raise the unit limit (max 100)."),
            ("Building", "Select a worker, press B, choose a building, click to place it."),
            ("", "Alliance peasants stay to construct. Host thralls summon and walk away."),
            ("Tech", "Upgrade your Keep / Pit to unlock tier 2 units and buildings."),
            ("Day & night", "By day the Alliance deals +12% damage. At night the Host deals"),
            ("", "+15% damage and Alliance units see 25% less far."),
            ("Damage", "Pierce is weak vs heavy armour, siege crushes buildings, magic beats heavy."),
        ]
        right = [
            ("Left click / drag", "Select a unit / box-select units"),
            ("Double click, Ctrl+click", "Select all units of that type on screen"),
            ("Right click", "Move, attack, gather, help construct, set rally point"),
            ("A + click", "Attack-move (fight anything on the way)"),
            ("S / H / P / M", "Stop, hold position, patrol, move"),
            ("Shift + order", "Queue orders"),
            ("Ctrl + 1-9 / 1-9", "Create / recall a control group (twice = centre)"),
            ("Arrows, edges, MMB drag", "Scroll the camera; wheel zooms"),
            ("Space / Backspace", "Jump to last alert / to your town hall"),
            ("Alt", "Show all health bars"),
            ("Esc / F10", "Cancel, back out of menus, pause"),
        ]
        y = 0.3
        for head, txt in left:
            if head:
                label(p, head, (-0.62, y), 0.95, GOLD)
            label(p, txt, (-0.62, y - 0.026), 0.78, TEXT)
            y -= 0.064 if head else 0.04
        y = 0.3
        for head, txt in right:
            label(p, head, (0.04, y), 0.85, GOLD)
            label(p, txt, (0.04, y - 0.024), 0.78, TEXT)
            y -= 0.058
        make_button(p, "Back", (0, -0.37), (0.22, 0.055), lambda: self._back_target())

    def show_help(self, back: Callable[[], None]) -> None:
        self._back_target = back
        self._show(self.help)

    # ================================================================== end screen
    def _build_end(self) -> None:
        s = self.end = Screen(dim=0.55)
        p = s.panel((1.0, 0.72))
        self.end_title = Text(parent=p, text="", position=(0, 0.3, -0.01), origin=(0, 0), scale=3.0, color=GOLD)
        self.end_sub = label(p, "", (0, 0.235), 0.95, DIM, origin=(0, 0))
        self.end_rows: list[tuple[Text, Text, Text]] = []
        self.end_head = (label(p, "", (0.1, 0.17), 1.0, TEXT, origin=(0, 0)), label(p, "", (0.33, 0.17), 1.0, TEXT, origin=(0, 0)))
        y = 0.12
        for _ in range(9):
            self.end_rows.append((label(p, "", (-0.42, y), 0.9, DIM), label(p, "", (0.1, y), 0.9, TEXT, origin=(0, 0.5)),
                                  label(p, "", (0.33, y), 0.9, TEXT, origin=(0, 0.5))))
            y -= 0.042
        make_button(p, "Main Menu", (-0.2, -0.3), (0.26, 0.06), self.quit_to_main)
        make_button(p, "Play Again", (0.2, -0.3), (0.26, 0.06), self._play_again, col=color.rgba(0.45, 0.25, 0.06, 1))

    def _on_match_over(self, winner=None, **_) -> None:
        g = self.game
        m = g.match
        if m is None or m.human is None:
            return
        g.state = "ended"

        def show() -> None:
            if g.match is m:
                self.show_end(m)

        invoke(show, delay=2.5)   # real seconds: the battlefield keeps playing in slow motion meanwhile

    def show_end(self, m) -> None:
        g = self.game
        won = m.winner is m.human
        self.end_title.text = "Victory!" if won else "Defeat"
        self.end_title.color = GOLD if won else color.rgb(0.85, 0.3, 0.25)
        t = int(m.time)
        self.end_sub.text = f"{m.map.name}  -  {t // 60}:{t % 60:02d}"
        a, b = m.players[0], m.players[1]
        self.end_head[0].text = a.fdef["short"] + (" (you)" if a is m.human else "")
        self.end_head[1].text = b.fdef["short"] + (" (you)" if b is m.human else "")
        rows = [("Units trained", "units_trained"), ("Units lost", "units_lost"), ("Enemies destroyed", "kills"),
                ("Buildings built", "buildings_built"), ("Buildings lost", "buildings_lost"), ("Gold mined", "gold_mined"),
                ("Timber cut", "timber_cut"), ("Gold spent", "gold_spent"), ("Upgrades researched", None)]
        for (title, key), (t0, t1, t2) in zip(rows, self.end_rows):
            t0.text = title
            if key is None:
                t1.text, t2.text = str(len(a.upgrades)), str(len(b.upgrades))
            else:
                t1.text, t2.text = str(a.stats[key]), str(b.stats[key])
        if g.hud is not None:
            g.hud.set_visible(False)
        self._show(self.end)
        events.emit("sound", name="victory" if won else "defeat")

    def _play_again(self) -> None:
        self.close()
        self.start_skirmish()
