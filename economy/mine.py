"""Gold mines: neutral blocking actors that hold a finite amount of gold."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from core.actor import Actor
from core.meshgen import MeshBuilder, shade
from core.rig import copy_part
from core.util import set_yaw
from settings import MAX_MINERS

if TYPE_CHECKING:
    from core.match import Match

FOOTPRINT = 3
GOLD = (1.0, 0.8, 0.22, 1)


def mine_mesh(seed: int) -> MeshBuilder:
    """A rocky knoll with a timber-framed adit facing +z and gold veins."""
    rng = random.Random(seed)
    mb = MeshBuilder()
    rock = (0.46, 0.42, 0.38, 1)
    for i in range(7):
        a = i / 7 * math.tau + rng.random() * 0.4
        r = 1.6 + rng.random() * 0.8
        mb.sphere((math.cos(a) * r * 0.9, 0.7 + rng.random() * 0.6, math.sin(a) * r - 0.5),
                  (1.5 + rng.random() * 0.6, 1.4 + rng.random() * 0.8, 1.5), shade(rock, 0.85 + rng.random() * 0.3),
                  detail=1, noise=0.25, seed=seed + i)
    mb.sphere((0, 1.9, -0.6), (2.1, 1.8, 1.9), shade(rock, 1.05), detail=1, noise=0.22, seed=seed + 20)
    # adit frame
    wood = (0.45, 0.31, 0.18, 1)
    mb.box((0, 1.0, 1.9), (1.6, 2.0, 0.6), (0.05, 0.04, 0.03, 1))
    for sx in (-1, 1):
        mb.box((sx * 0.95, 1.1, 2.15), (0.24, 2.2, 0.24), wood)
    mb.box((0, 2.25, 2.15), (2.4, 0.28, 0.32), wood)
    mb.box((0, 2.45, 2.15), (1.2, 0.18, 0.2), shade(wood, 0.8))
    # rails and a cart
    for sx in (-0.35, 0.35):
        mb.box((sx, 0.05, 3.2), (0.06, 0.06, 2.6), (0.4, 0.4, 0.42, 1))
    mb.box((0.0, 0.45, 3.6), (0.9, 0.5, 1.1), shade(wood, 0.7), taper=1.15)
    mb.sphere((0.0, 0.75, 3.6), (0.4, 0.2, 0.45), GOLD, detail=0)
    # gold veins
    for i in range(9):
        a = rng.random() * math.tau
        y = 0.6 + rng.random() * 2.2
        mb.box((math.cos(a) * 1.9, y, math.sin(a) * 1.7 - 0.5), (0.3, 0.22, 0.3), GOLD, rot=(rng.random() * 40, rng.random() * 90, 0))
    return mb


class GoldMine(Actor):
    """Neutral source of gold. Up to MAX_MINERS workers can be inside at the same time."""

    is_mine = True

    def __init__(self, match: "Match", x: float, z: float, gold: int, facing: float) -> None:
        defn = {"name": "Gold Mine", "hp": 99999, "armor": 99, "armor_type": "fortified", "radius": 3.0, "sight": 0}
        super().__init__(match, None, "gold_mine", defn, x, z)
        self.gold = gold
        self.initial = gold
        self.inside: list = []
        self.queue: list = []
        self.footprint = FOOTPRINT
        self.yaw = facing
        self.height = 4.0
        grid = match.grid
        self.cell_origin = grid.footprint_origin(x, z, FOOTPRINT)
        grid.block_rect(*self.cell_origin, FOOTPRINT, FOOTPRINT, 1)
        self.node = match.map_root.attachNewNode("gold_mine")
        copy_part(("goldmine", int(abs(x) * 7 + abs(z) * 3) % 5), lambda: mine_mesh(int(abs(x) * 7 + abs(z) * 3) % 5), self.node)
        self.node.setPos(x, self.y - 0.2, z)
        set_yaw(self.node, facing)
        self.depleted = False

    @property
    def entrance(self) -> tuple[float, float]:
        r = math.radians(self.yaw)
        return self.x + math.sin(r) * 3.6, self.z + math.cos(r) * 3.6

    def has_room(self) -> bool:
        return len(self.inside) < MAX_MINERS

    def take(self, amount: int) -> int:
        got = min(amount, self.gold)
        self.gold -= got
        if self.gold <= 0 and not self.depleted:
            self.depleted = True
            self.match.on_mine_depleted(self)
        return got

    def collapse(self) -> None:
        """Remove the depleted mine from the world and unblock its cells."""
        self.alive = False
        self.match.grid.block_rect(*self.cell_origin, FOOTPRINT, FOOTPRINT, -1)
        if self.node is not None:
            self.node.setColorScale(0.45, 0.42, 0.4, 1)
