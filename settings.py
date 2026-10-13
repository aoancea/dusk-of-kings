"""Global constants and persistent user settings for Dusk of Kings."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def base_dir() -> Path:
    """Folder that holds writable files (settings, cache)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    """Folder that holds bundled read-only resources (data/*.json)."""
    return Path(getattr(sys, "_MEIPASS", base_dir()))


ROOT = base_dir()
DATA_DIR = resource_dir() / "data"
CACHE_DIR = ROOT / "cache"
SCREENSHOT_DIR = ROOT / "screenshots"
SETTINGS_FILE = ROOT / "settings.json"

GAME_TITLE = "Dusk of Kings"
VERSION = "1.0.0"

# --- Map / grid -------------------------------------------------------------------
CELL = 2.0                  # world units per pathing / fog / terrain cell
SEA_LEVEL = 0.0
WADE_DEPTH = 0.6            # water deeper than this blocks ground units
MAX_WALK_SLOPE = 1.05       # rise/run above which a cell is a cliff
FLY_HEIGHT = 7.0

# --- Time -------------------------------------------------------------------------
DAY_LENGTH_SECONDS = 480.0  # a full day/night cycle (night is about a third of it)
START_HOUR = 9.0
NIGHT_START = 19.5
NIGHT_END = 5.5

# --- Economy ----------------------------------------------------------------------
START_GOLD = 250
START_TIMBER = 150
START_WORKERS = 5
SUPPLY_LIMIT = 100
GOLD_PER_TRIP = 8
TIMBER_PER_TRIP = 8
MINE_TIME = 2.4
CHOP_TIME = 3.6
MAX_MINERS = 5

# --- Colours ----------------------------------------------------------------------
TEAM_COLORS = [(0.20, 0.45, 0.95), (0.88, 0.16, 0.12)]

RESOLUTIONS: list[tuple[int, int]] = [
    (1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160),
]


@dataclass
class UserSettings:
    """Options the player can change from the settings menu."""

    mouse_sensitivity: float = 1.0
    scroll_speed: float = 1.0
    edge_scroll: bool = True
    master_volume: float = 0.8
    sfx_volume: float = 0.9
    ambient_volume: float = 0.6
    resolution: list[int] = field(default_factory=lambda: [1600, 900])
    fullscreen: bool = False
    show_fps: bool = True
    last_map: str = "greyfen_crossing"
    last_faction: str = "alliance"
    last_enemy: str = "host"
    last_difficulty: str = "normal"

    @classmethod
    def load(cls) -> "UserSettings":
        """Load settings from disk, falling back to defaults on any problem."""
        s = cls()
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for key, value in raw.items():
                if hasattr(s, key):
                    setattr(s, key, value)
        except (OSError, ValueError):
            pass
        return s

    def save(self) -> None:
        """Write settings to disk (errors are ignored)."""
        try:
            SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass


user_settings = UserSettings.load()
