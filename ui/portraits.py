"""Portrait icons rendered from the real procedural models into an offscreen atlas (once per match)."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from panda3d.core import (FrameBufferProperties, GraphicsOutput, GraphicsPipe, NodePath, OrthographicLens,
                          PTA_LVecBase4f, Texture as PTexture, Vec3, WindowProperties)
from PIL import Image, ImageDraw
from ursina import Texture

from core import data, shaders
from core.textures import np_to_texture

CELL_PX = 96
_cache: dict[tuple[str, str, tuple], Texture] = {}


def _frame_bg(img: Image.Image, faction: str | None) -> Image.Image:
    """Put a portrait on a framed gradient background."""
    s = img.size[0]
    y, x = np.mgrid[0:s, 0:s].astype(np.float32)
    k = 1.0 - np.hypot(x - s * 0.5, y - s * 0.38) / s
    base = (0.16, 0.2, 0.3) if faction == "alliance" else (0.28, 0.12, 0.1) if faction == "host" else (0.22, 0.2, 0.16)
    arr = np.stack([base[0] * (0.5 + k), base[1] * (0.5 + k), base[2] * (0.5 + k), np.ones_like(k)], -1)
    bg = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGBA")
    bg.alpha_composite(img)
    d = ImageDraw.Draw(bg)
    d.rectangle([0, 0, s - 1, s - 1], outline=(18, 12, 8, 255), width=3)
    d.rectangle([3, 3, s - 4, s - 4], outline=(255, 235, 190, 45), width=1)
    return bg


def render_portraits(base, colors: list[tuple[float, float, float]]) -> None:
    """Render every unit and building of both factions in each team colour into the cache."""
    from buildings.models import _protos
    from units.models import build_unit_rig
    items: list[tuple[str, str, tuple]] = []
    for uid in data.units():
        for c in colors:
            items.append(("unit", uid, tuple(c)))
    for bid, b in data.buildings().items():
        if b.get("faction") == "neutral":
            continue
        for c in colors:
            items.append(("building", bid, tuple(c)))
    items = [it for it in items if it not in _cache]
    if not items:
        return
    cols = 10
    rows = int(math.ceil(len(items) / cols))
    W, H = cols * CELL_PX, rows * CELL_PX
    fb = FrameBufferProperties()
    fb.setRgbColor(True)
    fb.setAlphaBits(8)
    fb.setDepthBits(24)
    wp = WindowProperties.size(W, H)
    tex = PTexture("portraits")
    buf = base.graphicsEngine.makeOutput(base.pipe, "portraits", -50, fb, wp, GraphicsPipe.BF_refuse_window,
                                         base.win.getGsg(), base.win)
    if buf is None:
        return
    buf.addRenderTexture(tex, GraphicsOutput.RTM_copy_ram)
    buf.setClearColor((0, 0, 0, 0))
    buf.setClearColorActive(True)
    scene = NodePath("portrait_scene")
    cam_np = base.makeCamera(buf)
    cam_np.reparentTo(scene)
    lens = OrthographicLens()
    cell = 1.0
    lens.setFilmSize(cols * cell, rows * cell)
    lens.setNearFar(-50, 50)
    cam_np.node().setLens(lens)
    view_dir = Vec3(-0.45, -0.55, -1.0)
    view_dir.normalize()
    cam_np.setPos(-view_dir * 20)
    cam_np.lookAt(Vec3(0, 0, 0), Vec3.up())
    right = scene.getRelativeVector(cam_np, Vec3.right())
    up = scene.getRelativeVector(cam_np, Vec3.up())
    # world shader inputs
    scene.setShader(shaders.world_shader())
    sun = Vec3(-0.5, 0.8, 0.6)
    sun.normalize()
    scene.setShaderInput("u_sun_dir", sun)
    scene.setShaderInput("u_sun_color", Vec3(1.0, 0.92, 0.8))
    scene.setShaderInput("u_amb_sky", Vec3(0.55, 0.55, 0.62))
    scene.setShaderInput("u_amb_ground", Vec3(0.3, 0.25, 0.22))
    scene.setShaderInput("u_fog_color", Vec3(0, 0, 0))
    scene.setShaderInput("u_fog_range", (1000.0, 2000.0))
    scene.setShaderInput("u_cam_pos", cam_np.getPos(scene))
    scene.setShaderInput("u_lights_pos", PTA_LVecBase4f.emptyArray(8))
    scene.setShaderInput("u_lights_col", PTA_LVecBase4f.emptyArray(8))
    scene.setShaderInput("u_num_lights", 0)
    scene.setShaderInput("u_emissive", 0.0)
    scene.setShaderInput("u_detail", 0.0)
    scene.setShaderInput("u_rim", 0.35)
    scene.setShaderInput("u_flame", 0.0)
    white = np_to_texture(np.full((4, 4, 3), 255, np.uint8), "white", mipmap=False)
    scene.setShaderInput("u_detail_tex", white)
    scene.setShaderInput("u_fow_tex", white)
    scene.setShaderInput("u_fow_rect", (0.0, 0.0, 1.0, 1.0))
    scene.setShaderInput("u_fow_on", 0.0)
    rigs = []
    for k, (kind, tid, col) in enumerate(items):
        r, c = divmod(k, cols)
        holder = scene.attachNewNode("cell")
        if kind == "unit":
            rig = build_unit_rig(data.units()[tid]["model"], col)
            rig.update(0.016, 0.0)
            rig.root.reparentTo(holder)
            rigs.append(rig)
            model = rig.root
        else:
            solid, glow = _protos(tid, col)
            model = holder.attachNewNode("b")
            solid.copyTo(model)
            if glow is not None:
                glow.copyTo(model)
        model.setH(-25 if kind == "unit" else -20)
        lo, hi = model.getTightBounds(scene)
        size = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z, 0.01)
        fill = 0.85 if kind == "unit" else 0.95
        sc = cell * fill / size
        holder.setScale(sc)
        lo, hi = model.getTightBounds(scene)
        centre = (lo + hi) * 0.5
        target = right * ((c - (cols - 1) / 2.0) * cell) + up * (((rows - 1) / 2.0 - r) * cell)
        holder.setPos(holder.getPos(scene) + target - centre)
    for _ in range(3):
        base.graphicsEngine.renderFrame()
    base.graphicsEngine.syncFrame()
    ok = tex.hasRamImage()
    if ok:
        raw = np.frombuffer(tex.getRamImageAs("RGBA"), np.uint8)
        img = raw.reshape(tex.getYSize(), tex.getXSize(), 4)[::-1]
        for k, (kind, tid, col) in enumerate(items):
            r, c = divmod(k, cols)
            sub = img[r * CELL_PX:(r + 1) * CELL_PX, c * CELL_PX:(c + 1) * CELL_PX].copy()
            pil = Image.fromarray(sub, "RGBA")
            fac = (data.units() if kind == "unit" else data.buildings())[tid].get("faction")
            t = Texture(_frame_bg(pil, fac))
            t.filtering = "bilinear"
            _cache[(kind, tid, col)] = t
    for rig in rigs:
        rig.destroy()
    scene.removeNode()
    base.graphicsEngine.removeWindow(buf)


def portrait(kind: str, type_id: str, color: tuple[float, float, float]) -> Texture | None:
    """Cached portrait texture (call ``render_portraits`` first)."""
    return _cache.get((kind, type_id, tuple(color)))
