"""GPU rigid skinning: collapse a multi-part :class:`core.rig.Rig` into one mesh driven by bone matrices.

Each animated node of the rig becomes a bone. Part meshes are baked into their bone's local space
and tagged with the bone index (in the texture coordinate), so the whole unit draws in a single call
while the existing rig code keeps animating the (now invisible) bone nodes.
"""
from __future__ import annotations

import numpy as np
from panda3d.core import LMatrix4f, NodePath, PTA_LMatrix4f, Shader

from core import shaders
from core.meshgen import make_geom_node, tri_normals
from core.rig import Rig, part_arrays

MAX_BONES = 16

SKIN_VERT = """#version 140
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
uniform mat4 u_bones[16];
in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec4 p3d_Color;
in vec2 p3d_MultiTexCoord0;
out vec3 v_wpos;
out vec3 v_normal;
out vec4 v_color;
out vec2 v_uv;
void main() {
    mat4 b = u_bones[int(p3d_MultiTexCoord0.x + 0.5)];
    vec4 lp = b * p3d_Vertex;
    vec4 wp = p3d_ModelMatrix * lp;
    v_wpos = wp.xyz;
    v_normal = mat3(p3d_ModelMatrix) * (mat3(b) * p3d_Normal);
    v_color = p3d_Color;
    v_uv = vec2(0.5, 0.5);
    gl_Position = p3d_ModelViewProjectionMatrix * lp;
}
"""

_shader: Shader | None = None
_geom_cache: dict[tuple, NodePath] = {}


def skin_shader() -> Shader:
    global _shader
    if _shader is None:
        _shader = Shader.make(Shader.SL_GLSL, SKIN_VERT, shaders.WORLD_FRAG)
    return _shader


def _mat_np(m: LMatrix4f) -> np.ndarray:
    return np.array([[m.getCell(i, j) for j in range(4)] for i in range(4)], np.float32)


def _collect(root: NodePath) -> tuple[list[NodePath], list[tuple[int, tuple, NodePath]]]:
    """Depth-first: every non-mesh node is a bone; mesh nodes (tagged by ``copy_part``) belong to their parent bone."""
    bones: list[NodePath] = [root]
    parts: list[tuple[int, tuple, NodePath]] = []

    def walk(node: NodePath, bone_idx: int) -> None:
        for child in node.getChildren():
            key = child.getPythonTag("part_key")
            if key is not None:
                parts.append((bone_idx, key, child))
            else:
                bones.append(child)
                walk(child, len(bones) - 1)

    walk(root, 0)
    return bones, parts


class Skin:
    """Single-draw-call stand-in for a rig's part meshes."""

    def __init__(self, rig: Rig, cache_key: tuple) -> None:
        self.rig = rig
        self.root = rig.root
        bones, parts = _collect(self.root)
        if len(bones) > MAX_BONES or not parts or any(k not in part_arrays for _, k, _ in parts):
            raise ValueError("rig cannot be skinned")
        proto = _geom_cache.get(cache_key)
        if proto is None:
            proto = self._build(bones, parts, cache_key)
            _geom_cache[cache_key] = proto
        for _, _, node in parts:
            node.removeNode()
        self.np = proto.copyTo(self.root)
        self.np.setShader(skin_shader())
        self.pta = PTA_LMatrix4f.emptyArray(MAX_BONES)
        self.np.setShaderInput("u_bones", self.pta)
        self.bones = bones
        self.update()

    @staticmethod
    def _build(bones: list[NodePath], parts: list[tuple[int, tuple, NodePath]], cache_key: tuple) -> NodePath:
        tris_l, cols_l, bone_l = [], [], []
        for bone_idx, key, node in parts:
            tris, cols = part_arrays[key]
            m = _mat_np(node.getMat(bones[bone_idx]))   # part transform relative to its bone (row-vector)
            pts = tris.reshape(-1, 3)
            hom = np.concatenate([pts, np.ones((pts.shape[0], 1), np.float32)], axis=1) @ m
            t = hom[:, :3].reshape(-1, 3, 3)
            if np.linalg.det(m[:3, :3]) < 0:
                t = t[:, ::-1, :].copy()
            tris_l.append(t)
            cols_l.append(cols)
            bone_l.append(np.full(t.shape[0], bone_idx, np.float32))
        tris = np.concatenate(tris_l).astype(np.float32)
        cols = np.concatenate(cols_l).astype(np.float32)
        bidx = np.concatenate(bone_l)
        normals = np.repeat(tri_normals(tris), 3, axis=0)
        colors = np.repeat(cols, 3, axis=0)
        uvs = np.zeros((tris.shape[0] * 3, 2), np.float32)
        uvs[:, 0] = np.repeat(bidx, 3)
        return make_geom_node(tris.reshape(-1, 3), normals, colors, uvs=uvs, name=f"skin_{cache_key[0]}")

    def update(self) -> None:
        root = self.root
        pta = self.pta
        for i, b in enumerate(self.bones):
            pta.setElement(i, b.getMat(root))
