"""Dusk of Kings - a real-time strategy game in a high-fantasy world, built with Ursina.

Usage:
    python main.py                                   # main menu
    python main.py --quick alliance host normal      # skip the menus: faction, enemy faction, difficulty
    python main.py --map shadowed_pass --quick host alliance hard
    python main.py --aivsai --speed 4                # watch two computer players fight
    python main.py --autotest m1                     # scripted smoke test (screenshots + checks, then quits)
"""
from __future__ import annotations

import argparse
import sys

from panda3d.core import loadPrcFileData

from settings import GAME_TITLE, user_settings

MENU_TESTS = ("m7", "menu")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=GAME_TITLE)
    ap.add_argument("--autotest", default=None, help="run a scripted smoke test and quit")
    ap.add_argument("--quick", nargs="*", default=None, help="faction enemy difficulty - skip the menus")
    ap.add_argument("--map", default=None, help="greyfen_crossing | shadowed_pass")
    ap.add_argument("--aivsai", action="store_true", help="spectate a computer vs computer match")
    ap.add_argument("--speed", type=float, default=1.0, help="simulation speed multiplier")
    ap.add_argument("--nofog", action="store_true", help="disable fog of war")
    ap.add_argument("--novsync", action="store_true", help="uncapped frame rate")
    ap.add_argument("--size", default=None, help="window size WxH")
    ap.add_argument("--seed", type=int, default=1)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    loadPrcFileData("", "framebuffer-multisample 1\nmultisamples 4\n")
    loadPrcFileData("", "texture-anisotropic-degree 4\n")
    loadPrcFileData("", "window-title " + GAME_TITLE + "\n")
    if args.novsync or args.autotest:
        loadPrcFileData("", "sync-video 0\n")

    from ursina import Ursina

    size = tuple(user_settings.resolution)
    if args.size:
        w, h = args.size.lower().split("x")
        size = (int(w), int(h))
    fullscreen = bool(user_settings.fullscreen) and not args.autotest
    app = Ursina(title=GAME_TITLE, development_mode=False, fullscreen=fullscreen, borderless=False,
                 size=size, vsync=not (args.novsync or args.autotest), show_ursina_splash=False)
    from ursina import window
    if not fullscreen:
        window.center_on_screen()
    window.exit_button.enabled = False
    window.fps_counter.enabled = bool(user_settings.show_fps) and not args.autotest
    window.color = (0.02, 0.02, 0.025, 1)

    import core.game as game_module
    from core.game import Game, GameLoop
    from core.match import MatchConfig, PlayerConfig

    game = Game(app)
    game_module.game = game
    try:
        from core.audio import AudioSystem
        game.audio = AudioSystem(listener=lambda: (game.match.cam.fx, game.match.cam.fz) if game.match else None)
    except Exception as exc:  # pragma: no cover - audio is optional
        print("[audio] disabled:", exc)
    from ui.hud import HUD
    from ui.menus import MenuController
    game.hud = HUD(game)
    game.menus = MenuController(game)
    GameLoop(game)
    game.fast_forward = args.speed

    map_id = args.map or user_settings.last_map
    if args.autotest and not args.autotest.startswith(MENU_TESTS):
        from core.autotest import config_for
        game.start_match(config_for(args.autotest, map_id))
    elif args.aivsai:
        cfg = MatchConfig(map_id=map_id, players=[PlayerConfig("alliance", True, "hard"), PlayerConfig("host", True, "hard")],
                          human=None, fog=False, seed=args.seed)
        game.start_match(cfg)
    elif args.quick is not None:
        q = args.quick
        fac = q[0] if len(q) > 0 and q[0] in ("alliance", "host") else "alliance"
        enemy = q[1] if len(q) > 1 and q[1] in ("alliance", "host") else ("host" if fac == "alliance" else "alliance")
        diff = q[2] if len(q) > 2 and q[2] in ("easy", "normal", "hard") else "normal"
        cfg = MatchConfig(map_id=map_id, players=[PlayerConfig(fac, False), PlayerConfig(enemy, True, diff)],
                          human=0, fog=not args.nofog, seed=args.seed)
        game.start_match(cfg)
    elif game.menus is not None:
        game.menus.show_main()
    else:
        game.start_match(MatchConfig(map_id=map_id))

    if args.autotest:
        from core.autotest import AutoTest
        tester = AutoTest(game, args.autotest)
        game.on_update.append(tester.update)
    app.run(info=False)


if __name__ == "__main__":
    main()
