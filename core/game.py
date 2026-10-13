"""Application-level game object: owns the current match, the UI layers and the main loop."""
from __future__ import annotations

import time as _time
from typing import Any, Callable

from ursina import Entity, application, camera, held_keys, mouse, time

from core.events import events
from core.match import Match, MatchConfig
from settings import user_settings

MAX_STEP = 1.0 / 30.0


class Game:
    """Holds the running match plus HUD / menus. A single instance lives in ``core.game.game``."""

    def __init__(self, app) -> None:
        self.app = app
        self.base = application.base
        self.settings = user_settings
        self.state = "menu"           # menu | playing | ended
        self.paused = False
        self.match: Match | None = None
        self.controls = None
        self.hud = None
        self.menus = None
        self.audio = None
        self.on_update: list[Callable[[float], None]] = []
        self.frame_times: list[float] = []
        self.sim_ms: list[float] = []
        self.time = 0.0
        self.fast_forward = 1.0
        mouse.traverse_target = None

    # ------------------------------------------------------------------ match lifecycle
    def start_match(self, config: MatchConfig) -> Match:
        self.end_match()
        from ui.controls import Controls
        self.match = Match(self, config)
        self.match.setup()
        self.match.start_ai()
        self.match.cam.edge_scroll = bool(self.settings.edge_scroll)
        self.match.cam.scroll_speed = float(self.settings.scroll_speed)
        self.controls = Controls(self)
        if self.hud is not None:
            self.hud.attach(self.match)
        self.state = "playing"
        self.paused = False
        events.emit("match_started", match=self.match)
        return self.match

    def end_match(self) -> None:
        if self.match is None:
            return
        if self.hud is not None:
            self.hud.detach()
        if self.controls is not None:
            self.controls.destroy()
            self.controls = None
        self.match.destroy()
        self.match = None
        self.state = "menu"

    def average_fps(self) -> float:
        ft = self.frame_times[-240:]
        return len(ft) / sum(ft) if ft and sum(ft) > 0 else 0.0

    def average_sim_ms(self) -> float:
        s = self.sim_ms[-240:]
        return sum(s) / len(s) if s else 0.0

    # ------------------------------------------------------------------ loop
    def input(self, key: str) -> None:
        if self.menus is not None and self.menus.input(key):
            return
        if self.state == "playing" and not self.paused and self.controls is not None:
            if self.hud is not None and self.hud.input(key):
                return
            self.controls.input(key)

    def update(self) -> None:
        dt = min(time.dt, 0.1)
        self.time += dt
        self.frame_times.append(time.dt)
        if len(self.frame_times) > 600:
            del self.frame_times[:300]
        m = self.match
        if m is not None:
            t0 = _time.perf_counter()
            playing = self.state == "playing" and not self.paused
            simulate = self.state in ("playing", "menu", "ended") and not self.paused
            if self.controls is not None and playing:
                self.controls.update(dt)
            m.cam.update(dt, allow_input=playing)
            if simulate and not m.over:
                sim = dt * self.fast_forward
                steps = max(1, int(sim / MAX_STEP + 0.999))
                for _ in range(steps):
                    m.update(sim / steps)
            elif simulate and m.over:
                m.update(dt * 0.25)
            m.present(dt if simulate else 0.0, dt)
            self.sim_ms.append((_time.perf_counter() - t0) * 1000.0)
            if len(self.sim_ms) > 600:
                del self.sim_ms[:300]
        if self.hud is not None:
            self.hud.update(dt)
        if self.menus is not None:
            self.menus.update(dt)
        if self.audio is not None:
            self._ambience()
            self.audio.update(dt)
        for fn in list(self.on_update):
            fn(dt)


    def _ambience(self) -> None:
        m = self.match
        if self.state == "menu" or m is None:
            self.audio.set_ambience({"theme": 1.0})
        elif self.state == "ended" or self.paused:
            self.audio.set_ambience({"amb_wind": 0.2})
        else:
            night = m.is_night
            self.audio.set_ambience({"amb_wind": 0.25 if night else 0.55, "amb_night": 0.7 if night else 0.0})


class GameLoop(Entity):
    """Ursina entity that forwards update/input to the Game object."""

    def __init__(self, game: Game) -> None:
        super().__init__(name="game_loop")
        self.game = game

    def update(self) -> None:
        self.game.update()

    def input(self, key: str) -> None:
        self.game.input(key)


game: Game | None = None
