"""Reusable UI building blocks on top of Ursina (panels, bars, icon slots, tooltips, buttons)."""
from __future__ import annotations

from typing import Any, Callable

from panda3d.core import Point2, Point3
from ursina import Button, Entity, Text, camera, color, mouse, window

PANEL_BG = color.rgba(0.07, 0.055, 0.045, 0.92)
PANEL_BORDER = color.rgba(0.62, 0.47, 0.24, 1)
PANEL_INNER = color.rgba(0.13, 0.10, 0.08, 1)
GOLD = color.rgb(1.0, 0.82, 0.38)
TEXT = color.rgb(0.95, 0.92, 0.85)
DIM = color.rgb(0.62, 0.6, 0.55)
FONT_SCALE = 1.0


def rgb(c: Any, a: float = 1.0) -> color.Color:
    return color.rgba(float(c[0]), float(c[1]), float(c[2]), a if len(c) < 4 else float(c[3]))


def tag(c: Any) -> str:
    """Text colour tag for inline colouring: '<rgb(r,g,b)>'."""
    return f"<rgb({c[0]:.3f},{c[1]:.3f},{c[2]:.3f})>"


def quad(parent: Entity, pos: tuple, scale: tuple, col: color.Color, z: float = 0.0, **kw: Any) -> Entity:
    return Entity(parent=parent, model="quad", position=(pos[0], pos[1], z), scale=scale, color=col,
                  add_to_scene_entities=False, **kw)


def label(parent: Entity, text: str, pos: tuple, scale: float = 1.0, col: color.Color = TEXT,
          origin: tuple = (-0.5, 0.5), z: float = -0.01, **kw: Any) -> Text:
    return Text(parent=parent, text=text, position=(pos[0], pos[1], z), scale=scale * FONT_SCALE, color=col,
                origin=origin, **kw)


class Panel(Entity):
    """Bordered window with an optional title and close button. Blocks mouse clicks."""

    def __init__(self, parent: Entity | None = None, position: tuple = (0, 0), size: tuple = (0.5, 0.5),
                 title: str = "", on_close: Callable[[], None] | None = None, z: float = 0.0, **kw: Any) -> None:
        super().__init__(parent=parent or camera.ui, position=(position[0], position[1], z), **kw)
        w, h = size
        self.size = size
        self.border = quad(self, (0, 0), (w + 0.008, h + 0.008), PANEL_BORDER, z=0.002)
        self.bg = Entity(parent=self, model="quad", scale=(w, h), color=PANEL_BG, collider="box", z=0.001)
        self.title_text = None
        if title:
            self.title_bar = quad(self, (0, h / 2 - 0.022), (w - 0.01, 0.036), PANEL_INNER, z=0.0)
            self.title_text = label(self, title, (0, h / 2 - 0.022), 1.1, GOLD, origin=(0, 0))
        if on_close:
            self.close_btn = Button(parent=self, text="x", scale=(0.03, 0.03), position=(w / 2 - 0.022, h / 2 - 0.022, -0.02),
                                    color=color.rgba(0.35, 0.1, 0.08, 1), highlight_color=color.rgba(0.6, 0.15, 0.1, 1),
                                    on_click=on_close)
            self.close_btn.text_entity.scale = 18

    @property
    def top(self) -> float:
        return self.size[1] / 2

    @property
    def left(self) -> float:
        return -self.size[0] / 2


class Bar(Entity):
    """Horizontal fill bar with optional centred text."""

    def __init__(self, parent: Entity, position: tuple, size: tuple, fill: color.Color,
                 bg: color.Color = color.rgba(0.05, 0.05, 0.05, 0.9), text_scale: float = 0.75,
                 show_text: bool = True, z: float = -0.005) -> None:
        super().__init__(parent=parent, position=(position[0], position[1], z), add_to_scene_entities=False)
        w, h = size
        self.w = w
        self.frame = quad(self, (w / 2, 0), (w + 0.004, h + 0.004), color.rgba(0, 0, 0, 0.9), z=0.002)
        self.bg = quad(self, (w / 2, 0), (w, h), bg, z=0.001)
        self.fill = Entity(parent=self, model="quad", origin=(-0.5, 0), scale=(w, h), color=fill, z=0.0,
                           add_to_scene_entities=False)
        self.shine = Entity(parent=self.fill, model="quad", origin=(-0.5, 0), scale=(1, 0.35), y=0.2,
                            color=color.rgba(1, 1, 1, 0.12), z=-0.0005, add_to_scene_entities=False)
        self.text = label(self, "", (w / 2, 0), text_scale, TEXT, origin=(0, 0), z=-0.003) if show_text else None
        self._last = (-1.0, -1.0, "")

    def set(self, value: float, maximum: float, text: str | None = None) -> None:
        frac = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
        key = (round(frac, 4), maximum, text or "")
        if key == self._last:
            return
        self._last = key
        self.fill.scale_x = max(0.0001, self.w * frac)
        vis = frac > 0.0005
        if self.fill.visible != vis:
            self.fill.visible = vis
        if self.text is not None:
            self.text.text = text if text is not None else f"{int(value)} / {int(maximum)}"

    def set_color(self, c: color.Color) -> None:
        self.fill.color = c


class Tooltip(Entity):
    """Follows the mouse, showing coloured lines of text."""

    _instance: "Tooltip | None" = None

    def __init__(self) -> None:
        super().__init__(parent=camera.ui, z=-5, enabled=False)
        self.bg = quad(self, (0, 0), (0.1, 0.1), color.rgba(0.04, 0.035, 0.03, 0.95), z=0.01)
        self.border = quad(self, (0, 0), (0.1, 0.1), color.rgba(0.5, 0.42, 0.3, 1), z=0.02)
        self.lines: list[Text] = []
        self.owner = None
        Tooltip._instance = self

    @classmethod
    def get(cls) -> "Tooltip":
        if cls._instance is None:
            cls()
        return cls._instance  # type: ignore[return-value]

    def show(self, lines: list[tuple[str, Any]], owner: Any = None) -> None:
        self.owner = owner
        for t in self.lines:
            t.enabled = False
        y = 0.0
        width = 0.12
        lh = 0.024
        for i, (txt, col) in enumerate(lines):
            if i >= len(self.lines):
                self.lines.append(label(self, "", (0, 0), 0.8, TEXT, z=-0.01))
            t = self.lines[i]
            t.enabled = True
            t.text = txt or " "
            t.scale = 1.0 if i == 0 else 0.8
            t.color = rgb(col)
            t.position = (0.012, -0.012 + y, -0.01)
            if txt:
                width = max(width, t.width * t.scale_x + 0.024)
            y -= lh if i else lh * 1.2
        h = -y + 0.014
        self.bg.scale = (width, h)
        self.bg.position = (width / 2, -h / 2, 0.01)
        self.border.scale = (width + 0.004, h + 0.004)
        self.border.position = (width / 2, -h / 2, 0.02)
        self._w, self._h = width, h
        self.enabled = True
        self.follow()

    def follow(self) -> None:
        x, y = mouse.x + 0.02, mouse.y - 0.02
        ar = window.aspect_ratio
        if x + self._w > ar / 2 - 0.01:
            x = mouse.x - self._w - 0.02
        if y - self._h < -0.49:
            y = -0.49 + self._h
        self.position = (x, y, -5)

    def hide(self, owner: Any = None) -> None:
        if owner is None or owner is self.owner:
            self.enabled = False
            self.owner = None

    def update(self) -> None:
        if self.enabled:
            self.follow()


class IconSlot(Entity):
    """Clickable square with icon, stack count, border colour and cooldown shade."""

    def __init__(self, parent: Entity, position: tuple, size: float = 0.06,
                 on_click: Callable[["IconSlot"], None] | None = None,
                 on_right_click: Callable[["IconSlot"], None] | None = None,
                 tooltip: Callable[["IconSlot"], list | None] | None = None, key_label: str = "",
                 empty_color: color.Color = color.rgba(0.12, 0.1, 0.08, 0.9)) -> None:
        super().__init__(parent=parent, model="quad", position=(position[0], position[1], -0.01), scale=size,
                         color=empty_color, collider="box")
        self.size = size
        self.on_click_fn = on_click
        self.on_right_fn = on_right_click
        self.tooltip_fn = tooltip
        self.data: Any = None
        self.border = Entity(parent=self, model="quad", scale=1.08, color=color.rgba(0.35, 0.28, 0.18, 1), z=0.01,
                             add_to_scene_entities=False)
        self.icon = Entity(parent=self, model="quad", scale=0.9, z=-0.01, enabled=False, add_to_scene_entities=False)
        self.shade = Entity(parent=self, model="quad", origin=(0, -0.5), scale=(0.9, 0), y=-0.45,
                            color=color.rgba(0, 0, 0, 0.62), z=-0.02, add_to_scene_entities=False)
        k = 1.0 / size
        self.count_text = Text(parent=self, text="", origin=(0.5, -0.5), position=(0.45, -0.45, -0.03),
                               scale=0.6 * k, color=color.white)
        self.key_text = Text(parent=self, text=key_label, origin=(-0.5, 0.5), position=(-0.44, 0.46, -0.03),
                             scale=0.55 * k, color=color.rgb(0.9, 0.9, 0.9))
        self.cd_text = Text(parent=self, text="", origin=(0, 0), position=(0, 0, -0.035), scale=0.85 * k,
                            color=color.rgb(1, 0.95, 0.6))
        self.dim = Entity(parent=self, model="quad", scale=0.9, color=color.rgba(0, 0, 0, 0.55), z=-0.025,
                          enabled=False, add_to_scene_entities=False)
        self._cd_last = ""

    def set_icon(self, tex: Any, border: Any = None, count: int = 0) -> None:
        if tex is None:
            self.icon.enabled = False
        else:
            self.icon.enabled = True
            self.icon.texture = tex
        self.border.color = rgb(border) if border is not None else color.rgba(0.35, 0.28, 0.18, 1)
        self.count_text.text = str(count) if count > 1 else ""

    def set_cooldown(self, remaining: float, total: float) -> None:
        frac = 0.0 if total <= 0 else max(0.0, min(1.0, remaining / total))
        self.shade.scale_y = 0.9 * frac
        txt = ""
        if remaining > 1.5:
            txt = f"{int(remaining + 0.99)}" if remaining < 60 else f"{int(remaining // 60 + 1)}m"
        if txt != self._cd_last:
            self._cd_last = txt
            self.cd_text.text = txt

    def set_dim(self, dim: bool) -> None:
        if self.dim.enabled != dim:
            self.dim.enabled = dim

    def input(self, key: str) -> None:
        if not self.hovered:
            return
        if key == "left mouse down" and self.on_click_fn:
            self.on_click_fn(self)
        elif key == "right mouse down" and self.on_right_fn:
            self.on_right_fn(self)

    def update(self) -> None:
        tt = Tooltip.get()
        if self.hovered and self.tooltip_fn:
            lines = self.tooltip_fn(self)
            if lines:
                if tt.owner is not self or not tt.enabled:
                    tt.show(lines, self)
            else:
                tt.hide(self)
        elif tt.owner is self:
            tt.hide(self)

    def on_disable(self) -> None:
        if Tooltip._instance is not None and Tooltip._instance.owner is self:
            Tooltip._instance.hide(self)


def make_button(parent: Entity, text: str, position: tuple, size: tuple, on_click: Callable[[], None],
                col: color.Color = color.rgba(0.32, 0.18, 0.08, 1), text_scale: float = 1.0) -> Button:
    b = Button(parent=parent, text=text, position=(position[0], position[1], -0.02), scale=size, color=col,
               highlight_color=color.rgba(col[0] * 1.5, col[1] * 1.5, col[2] * 1.5, 1),
               pressed_color=color.rgba(col[0] * 0.7, col[1] * 0.7, col[2] * 0.7, 1), on_click=on_click)
    if b.text_entity:
        b.text_entity.scale *= text_scale
        b.text_entity.color = GOLD
    return b


def world_to_ui(base, pos: Point3) -> tuple[float, float] | None:
    """Project a world position to Ursina UI coordinates, or None if behind the camera."""
    p = base.cam.getRelativePoint(base.render, pos)
    if p.z <= 0.1:
        return None
    p2 = Point2()
    if not base.camLens.project(p, p2):
        if abs(p2.x) > 1.3 or abs(p2.y) > 1.3:
            return None
    return p2.x * window.aspect_ratio / 2, p2.y / 2
