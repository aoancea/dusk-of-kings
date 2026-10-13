"""GLSL shaders used by the game (world lighting, sky, water, dust, post-processing, UI)."""
from __future__ import annotations

from panda3d.core import Shader

_VERSION = "#version 140\n"

# ---------------------------------------------------------------------------------
# World: flat-shaded vertex colours, hemispheric ambient + sun + point lights + fog
# ---------------------------------------------------------------------------------
WORLD_VERT = _VERSION + """
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
uniform float osg_FrameTime;
uniform float u_flame;
in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec4 p3d_Color;
in vec2 p3d_MultiTexCoord0;
out vec3 v_wpos;
out vec3 v_normal;
out vec4 v_color;
out vec2 v_uv;
void main() {
    vec4 lp = p3d_Vertex;
    if (u_flame > 0.0) {
        float t = osg_FrameTime;
        float ph = lp.x * 1.7 + lp.z * 1.3;
        lp.x += sin(t * 9.0 + lp.y * 3.0 + ph) * 0.06 * u_flame;
        lp.z += cos(t * 7.5 + lp.y * 2.5 + ph) * 0.06 * u_flame;
        lp.y += sin(t * 11.0 + ph) * 0.05 * u_flame;
    }
    vec4 wp = p3d_ModelMatrix * lp;
    v_wpos = wp.xyz;
    v_normal = mat3(p3d_ModelMatrix) * p3d_Normal;
    v_color = p3d_Color;
    v_uv = p3d_MultiTexCoord0;
    gl_Position = p3d_ModelViewProjectionMatrix * lp;
}
"""

WORLD_FRAG = _VERSION + """
uniform sampler2D p3d_Texture0;
uniform sampler2D u_detail_tex;
uniform vec4 p3d_ColorScale;
uniform vec3 u_sun_dir;
uniform vec3 u_sun_color;
uniform vec3 u_amb_sky;
uniform vec3 u_amb_ground;
uniform vec3 u_fog_color;
uniform vec2 u_fog_range;
uniform vec3 u_cam_pos;
uniform vec4 u_lights_pos[8];
uniform vec4 u_lights_col[8];
uniform int u_num_lights;
uniform float u_emissive;
uniform float u_detail;
uniform float u_rim;
uniform sampler2D u_fow_tex;
uniform vec4 u_fow_rect;
uniform float u_fow_on;
in vec3 v_wpos;
in vec3 v_normal;
in vec4 v_color;
in vec2 v_uv;
out vec4 o_color;
void main() {
    vec4 base = texture(p3d_Texture0, v_uv) * v_color * p3d_ColorScale;
    if (base.a < 0.02) discard;
    vec3 n = normalize(v_normal);
    if (u_detail > 0.0) {
        float d1 = texture(u_detail_tex, v_wpos.xz * 0.23).r;
        float d2 = texture(u_detail_tex, v_wpos.xz * 0.031 + vec2(0.37, 0.71)).r;
        base.rgb *= mix(1.0, 0.80 + 0.26 * d1 + 0.18 * (d2 - 0.5), u_detail);
    }
    float ndl = max(dot(n, u_sun_dir), 0.0);
    float hemi = n.y * 0.5 + 0.5;
    vec3 light = mix(u_amb_ground, u_amb_sky, hemi) + u_sun_color * ndl;
    for (int i = 0; i < u_num_lights; i++) {
        vec3 d = u_lights_pos[i].xyz - v_wpos;
        float dist = length(d);
        float att = clamp(1.0 - dist / u_lights_pos[i].w, 0.0, 1.0);
        att *= att;
        float nd = max(dot(n, d / max(dist, 0.001)), 0.0) * 0.75 + 0.25;
        light += u_lights_col[i].rgb * (u_lights_col[i].a * att * nd);
    }
    vec3 vdir = normalize(u_cam_pos - v_wpos);
    float rim = pow(1.0 - max(dot(n, vdir), 0.0), 3.0) * u_rim;
    vec3 col = base.rgb * mix(light, vec3(1.0), clamp(u_emissive, 0.0, 1.0));
    col += base.rgb * max(u_emissive - 1.0, 0.0);
    col += rim * (u_sun_color * 0.6 + u_amb_sky * 0.6);
    float dist = length(v_wpos - u_cam_pos);
    float fog = clamp((dist - u_fog_range.x) / max(u_fog_range.y - u_fog_range.x, 1.0), 0.0, 1.0);
    col = mix(col, u_fog_color, fog * fog * (3.0 - 2.0 * fog));
    float fv = texture(u_fow_tex, (v_wpos.xz - u_fow_rect.xy) / u_fow_rect.zw).r;
    col *= mix(1.0, fv, u_fow_on);
    o_color = vec4(col, base.a);
}
"""

# ---------------------------------------------------------------------------------
# Sky dome (centred on the camera)
# ---------------------------------------------------------------------------------
SKY_VERT = _VERSION + """
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
out vec3 v_dir;
void main() {
    v_dir = p3d_Vertex.xyz;
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
}
"""

SKY_FRAG = _VERSION + """
uniform vec3 u_sky_zenith;
uniform vec3 u_sky_horizon;
uniform vec3 u_fog_color;
uniform vec3 u_sky_sun;
uniform vec3 u_sun_color;
uniform vec3 u_moon_dir;
uniform float u_night;
uniform float u_underground;
in vec3 v_dir;
out vec4 o_color;
float hash(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
void main() {
    vec3 d = normalize(v_dir);
    float h = d.y;
    vec3 col = mix(u_sky_horizon, u_sky_zenith, pow(clamp(h, 0.0, 1.0), 0.5));
    col = mix(col, u_fog_color, smoothstep(0.12, -0.05, h));
    float sd = max(dot(d, u_sky_sun), 0.0);
    col += u_sun_color * (smoothstep(0.9985, 0.9993, sd) * 4.0 + pow(sd, 10.0) * 0.22 + pow(sd, 90.0) * 0.4);
    float md = max(dot(d, u_moon_dir), 0.0);
    col += vec3(0.85, 0.9, 1.0) * (smoothstep(0.9990, 0.9995, md) * 0.9 + pow(md, 50.0) * 0.07) * u_night;
    vec3 sp = floor(d * 300.0);
    float s = hash(sp);
    float tw = 0.6 + 0.4 * hash(sp + vec3(7.0));
    col += vec3(step(0.9972, s) * u_night * u_night * u_night * smoothstep(0.02, 0.25, h) * tw);
    col = mix(col, vec3(0.02, 0.015, 0.012), u_underground);
    o_color = vec4(col, 1.0);
}
"""

# ---------------------------------------------------------------------------------
# Water (mesh vertices are in world space, node has identity transform)
# ---------------------------------------------------------------------------------
WATER_VERT = _VERSION + """
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
uniform float osg_FrameTime;
in vec4 p3d_Vertex;
out vec3 v_wpos;
out vec3 v_normal;
void main() {
    vec4 wp = p3d_ModelMatrix * p3d_Vertex;
    float t = osg_FrameTime;
    float a1 = wp.x * 0.08 + t * 1.1;
    float a2 = wp.z * 0.11 - t * 0.8 + wp.x * 0.03;
    float a3 = (wp.x + wp.z) * 0.23 + t * 1.9;
    float disp = sin(a1) * 0.16 + sin(a2) * 0.13 + sin(a3) * 0.05;
    float dx = cos(a1) * 0.16 * 0.08 + cos(a2) * 0.13 * 0.03 + cos(a3) * 0.05 * 0.23;
    float dz = cos(a2) * 0.13 * 0.11 + cos(a3) * 0.05 * 0.23;
    v_normal = normalize(vec3(-dx, 1.0, -dz));
    v_wpos = vec3(wp.x, wp.y + disp, wp.z);
    vec4 lp = p3d_Vertex;
    lp.y += disp;
    gl_Position = p3d_ModelViewProjectionMatrix * lp;
}
"""

WATER_FRAG = _VERSION + """
uniform sampler2D u_depth_tex;
uniform vec4 u_depth_rect;
uniform vec3 u_cam_pos;
uniform vec3 u_sun_dir;
uniform vec3 u_sun_color;
uniform vec3 u_amb_sky;
uniform vec3 u_sky_horizon;
uniform vec3 u_fog_color;
uniform vec2 u_fog_range;
uniform float osg_FrameTime;
uniform sampler2D u_fow_tex;
uniform vec4 u_fow_rect;
uniform float u_fow_on;
in vec3 v_wpos;
in vec3 v_normal;
out vec4 o_color;
void main() {
    vec2 uv = (v_wpos.xz - u_depth_rect.xy) / u_depth_rect.zw;
    float depth = texture(u_depth_tex, uv).r * 12.0;
    float t = osg_FrameTime;
    vec3 shallow = vec3(0.22, 0.72, 0.70);
    vec3 deep = vec3(0.03, 0.20, 0.36);
    float dk = clamp(depth / 7.0, 0.0, 1.0);
    vec3 base = mix(shallow, deep, sqrt(dk));
    vec3 n = normalize(v_normal + vec3(sin(v_wpos.z * 0.9 + t * 2.0), 0.0, cos(v_wpos.x * 0.8 - t * 1.7)) * 0.05);
    vec3 v = normalize(u_cam_pos - v_wpos);
    float fres = pow(1.0 - max(dot(n, v), 0.0), 4.0);
    vec3 lightc = u_amb_sky * 0.9 + u_sun_color * (max(dot(n, u_sun_dir), 0.0) * 0.55 + 0.15);
    vec3 col = base * lightc + fres * u_sky_horizon * 0.6;
    vec3 hv = normalize(u_sun_dir + v);
    col += u_sun_color * pow(max(dot(n, hv), 0.0), 220.0) * 1.6;
    float band = 0.5 + 0.5 * sin(depth * 8.0 - t * 2.4);
    float foam = smoothstep(1.1, 0.05, depth) * (0.35 + 0.65 * band);
    col = mix(col, vec3(0.93, 0.92, 0.88) * (u_amb_sky + u_sun_color * 0.8), clamp(foam * 0.75, 0.0, 0.85));
    float alpha = clamp(mix(0.45, 0.93, dk) + foam * 0.4, 0.0, 0.97);
    float dist = length(v_wpos - u_cam_pos);
    float fog = clamp((dist - u_fog_range.x) / max(u_fog_range.y - u_fog_range.x, 1.0), 0.0, 1.0);
    fog = fog * fog * (3.0 - 2.0 * fog);
    col = mix(col, u_fog_color, fog);
    alpha = mix(alpha, 1.0, fog);
    float fv = texture(u_fow_tex, (v_wpos.xz - u_fow_rect.xy) / u_fow_rect.zw).r;
    col *= mix(1.0, fv, u_fow_on);
    o_color = vec4(col, alpha);
}
"""

# ---------------------------------------------------------------------------------
# GPU dust particles that wrap around the camera
# ---------------------------------------------------------------------------------
DUST_VERT = _VERSION + """
uniform mat4 p3d_ModelViewMatrix;
uniform mat4 p3d_ProjectionMatrix;
uniform float osg_FrameTime;
uniform vec3 u_cam_pos;
uniform vec3 u_wind;
uniform float u_box;
in vec4 p3d_Vertex;      // xyz = random seed in [0,1)
in vec2 p3d_MultiTexCoord0;  // quad corner
out vec2 v_uv;
out float v_fade;
void main() {
    vec3 seed = p3d_Vertex.xyz;
    vec3 drift = u_wind * osg_FrameTime + vec3(0.0, sin(osg_FrameTime * 0.7 + seed.x * 40.0) * 0.8, 0.0);
    vec3 rel = fract(seed + (drift - u_cam_pos) / u_box) - 0.5;
    vec3 world = u_cam_pos + rel * u_box;
    world.y = u_cam_pos.y - 6.0 + fract(seed.y + drift.y / 20.0) * 14.0;
    vec4 vpos = p3d_ModelViewMatrix * vec4(world, 1.0);
    float size = 0.03 + seed.z * 0.05;
    vpos.xy += (p3d_MultiTexCoord0 - 0.5) * size;
    v_uv = p3d_MultiTexCoord0;
    float dcam = length(rel * u_box);
    v_fade = (1.0 - smoothstep(0.30, 0.5, length(rel.xz))) * smoothstep(2.0, 6.0, dcam);
    gl_Position = p3d_ProjectionMatrix * vpos;
}
"""

DUST_FRAG = _VERSION + """
uniform vec3 u_dust_color;
uniform float u_dust_alpha;
in vec2 v_uv;
in float v_fade;
out vec4 o_color;
void main() {
    float r = length(v_uv - 0.5) * 2.0;
    float a = (1.0 - smoothstep(0.3, 1.0, r)) * u_dust_alpha * v_fade;
    if (a < 0.01) discard;
    o_color = vec4(u_dust_color, a);
}
"""

# ---------------------------------------------------------------------------------
# Post-processing: heat haze + vignette + mild grading
# ---------------------------------------------------------------------------------
POST_VERT = _VERSION + """
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
in vec2 p3d_MultiTexCoord0;
out vec2 v_uv;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    v_uv = p3d_MultiTexCoord0;
}
"""

POST_FRAG = _VERSION + """
uniform sampler2D tex;
uniform sampler2D dtex;
uniform float osg_FrameTime;
uniform float u_haze;
uniform vec2 u_clip;
uniform float u_flash;
uniform vec3 u_flash_color;
in vec2 v_uv;
out vec4 o_color;
void main() {
    float d = texture(dtex, v_uv).r;
    float ndc = d * 2.0 - 1.0;
    float lin = (2.0 * u_clip.x * u_clip.y) / (u_clip.y + u_clip.x - ndc * (u_clip.y - u_clip.x));
    float k = smoothstep(35.0, 170.0, lin) * u_haze * smoothstep(0.15, 0.6, 1.0 - v_uv.y + 0.3);
    float t = osg_FrameTime;
    vec2 off = vec2(sin(v_uv.y * 190.0 + t * 5.0) * 0.6 + sin(v_uv.y * 67.0 - t * 3.1) * 0.4,
                    cos(v_uv.x * 120.0 + t * 4.0) * 0.5) * 0.0016 * k;
    vec3 col = texture(tex, v_uv + off).rgb;
    vec2 c = v_uv - 0.5;
    float vig = 1.0 - dot(c, c) * 0.55;
    col *= vig;
    col = mix(col, u_flash_color, u_flash);
    o_color = vec4(col, 1.0);
}
"""

# ---------------------------------------------------------------------------------
# UI: circular minimap window into a big map texture
# ---------------------------------------------------------------------------------
MINIMAP_VERT = _VERSION + """
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
in vec2 p3d_MultiTexCoord0;
out vec2 v_uv;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    v_uv = p3d_MultiTexCoord0;
}
"""

MINIMAP_FRAG = _VERSION + """
uniform sampler2D p3d_Texture0;
uniform vec2 u_center;
uniform vec2 u_zoom;
uniform float u_dark;
in vec2 v_uv;
out vec4 o_color;
void main() {
    vec2 p = v_uv - 0.5;
    float r = length(p);
    if (r > 0.5) discard;
    vec2 tuv = u_center + p * u_zoom;
    vec3 c = texture(p3d_Texture0, tuv).rgb;
    if (tuv.x < 0.0 || tuv.x > 1.0 || tuv.y < 0.0 || tuv.y > 1.0) c = vec3(0.05, 0.05, 0.06);
    c *= (1.0 - u_dark);
    float ring = smoothstep(0.455, 0.475, r);
    c = mix(c, vec3(0.42, 0.30, 0.14), ring);
    float edge = smoothstep(0.49, 0.5, r);
    c = mix(c, vec3(0.08, 0.05, 0.02), edge);
    o_color = vec4(c, 1.0);
}
"""

_cache: dict[str, Shader] = {}


def _make(name: str, vert: str, frag: str) -> Shader:
    if name not in _cache:
        _cache[name] = Shader.make(Shader.SL_GLSL, vert, frag)
    return _cache[name]


def world_shader() -> Shader:
    return _make("world", WORLD_VERT, WORLD_FRAG)


def sky_shader() -> Shader:
    return _make("sky", SKY_VERT, SKY_FRAG)


def water_shader() -> Shader:
    return _make("water", WATER_VERT, WATER_FRAG)


def dust_shader() -> Shader:
    return _make("dust", DUST_VERT, DUST_FRAG)


def post_shader() -> Shader:
    return _make("post", POST_VERT, POST_FRAG)


def minimap_shader() -> Shader:
    return _make("minimap", MINIMAP_VERT, MINIMAP_FRAG)
