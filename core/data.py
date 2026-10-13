"""Loads the editable JSON game data from the /data folder."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from settings import DATA_DIR


@lru_cache(maxsize=None)
def load(name: str) -> Any:
    """Return the parsed contents of ``data/<name>.json`` (cached)."""
    with (DATA_DIR / f"{name}.json").open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = {k: v for k, v in raw.items() if not k.startswith("_")}
    return raw


def factions() -> dict[str, Any]:
    return load("factions")


def units() -> dict[str, Any]:
    return load("units")


def buildings() -> dict[str, Any]:
    return load("buildings")


def upgrades() -> dict[str, Any]:
    return load("upgrades")


def abilities() -> dict[str, Any]:
    return load("abilities")


def maps() -> dict[str, Any]:
    return load("maps")


def combat() -> dict[str, Any]:
    return load("combat")


def ai() -> dict[str, Any]:
    return load("ai")
