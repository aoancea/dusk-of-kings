"""Procedurally synthesised sound effects and ambience (numpy -> WAV cache -> Panda3D audio)."""
from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Callable

import numpy as np
from panda3d.core import AudioSound, Filename

from core.events import events
from settings import CACHE_DIR, user_settings

SR = 22050
AUDIO_VERSION = 4


def _t(dur: float) -> np.ndarray:
    return np.arange(int(SR * dur), dtype=np.float32) / SR


def _env(n: int, attack: float = 0.005, decay: float = 0.2, curve: float = 3.0) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    d = np.exp(-np.maximum(t - attack, 0) / max(decay, 1e-4) * curve / 3.0)
    return a * d


def _noise(n: int, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-1, 1, n).astype(np.float32)


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    """One-pole low-pass filter (vectorised via cumulative trick for constant cutoff)."""
    rc = 1.0 / (2 * math.pi * max(cutoff, 10.0))
    alpha = (1.0 / SR) / (rc + 1.0 / SR)
    y = np.empty_like(x)
    acc = 0.0
    a = float(alpha)
    for i in range(len(x)):
        acc += a * (float(x[i]) - acc)
        y[i] = acc
    return y


def _lp_fast(x: np.ndarray, k: int) -> np.ndarray:
    """Cheap low-pass: moving average of width k."""
    if k <= 1:
        return x
    c = np.cumsum(np.concatenate([[0.0], x.astype(np.float64)]))
    y = (c[k:] - c[:-k]) / k
    return np.concatenate([y, np.full(k - 1, y[-1] if len(y) else 0.0)]).astype(np.float32)


def _sine(freq: np.ndarray | float, dur: float) -> np.ndarray:
    t = _t(dur)
    if np.isscalar(freq):
        return np.sin(2 * np.pi * float(freq) * t).astype(np.float32)
    phase = np.cumsum(np.asarray(freq, np.float32)) / SR
    return np.sin(2 * np.pi * phase).astype(np.float32)


def _pluck(freq: float, dur: float, decay: float = 0.996) -> np.ndarray:
    n = int(SR * dur)
    period = int(SR / freq)
    buf = np.random.default_rng(3).uniform(-1, 1, period).astype(np.float32)
    out = np.empty(n, np.float32)
    for i in range(n):
        j = i % period
        v = buf[j]
        out[i] = v
        buf[j] = decay * 0.5 * (v + buf[(j + 1) % period])
    return out


def _note(freq: float, dur: float, harmonics: tuple = (1.0, 0.5, 0.25), decay: float = 0.5) -> np.ndarray:
    t = _t(dur)
    s = np.zeros_like(t)
    for i, a in enumerate(harmonics):
        s += a * np.sin(2 * np.pi * freq * (i + 1) * t)
    return (s * _env(len(t), 0.01, decay)).astype(np.float32)


def _mix(*parts: np.ndarray) -> np.ndarray:
    n = max(len(p) for p in parts)
    out = np.zeros(n, np.float32)
    for p in parts:
        out[: len(p)] += p
    return out


def _seq(notes: list[tuple[float, float, float]], total: float, **kw) -> np.ndarray:
    out = np.zeros(int(SR * total), np.float32)
    for start, freq, dur in notes:
        s = _note(freq, dur, **kw)
        i = int(start * SR)
        out[i:i + len(s)] += s[: max(0, len(out) - i)]
    return out


# --------------------------------------------------------------------------- recipes
def s_hit() -> np.ndarray:
    n = int(SR * 0.16)
    thump = _sine(np.linspace(160, 60, n), 0.16) * _env(n, 0.002, 0.08)
    crunch = _lp_fast(_noise(n, 1), 6) * _env(n, 0.001, 0.05)
    return _mix(thump * 0.9, crunch * 0.6)


def s_swing() -> np.ndarray:
    n = int(SR * 0.22)
    nz = _noise(n, 2)
    sweep = np.concatenate([_lp_fast(nz[: n // 2], 10), _lp_fast(nz[n // 2:], 4)])
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    return sweep * env * 0.5


def s_bow() -> np.ndarray:
    tw = _pluck(220, 0.35, 0.99) * _env(int(SR * 0.35), 0.001, 0.2)
    return _mix(tw * 0.6, s_swing()[: int(SR * 0.2)] * 0.5)


def s_fire() -> np.ndarray:
    n = int(SR * 0.6)
    whoosh = _lp_fast(_noise(n, 6), 12) * np.sin(np.linspace(0, np.pi, n)) * 1.4
    crack = _noise(n, 7) * (np.random.default_rng(8).random(n) > 0.97) * _env(n, 0.01, 0.4) * 0.5
    return _mix(whoosh, crack)


def s_heal() -> np.ndarray:
    return _seq([(0, 523, 0.6), (0.1, 659, 0.6), (0.2, 784, 0.6), (0.3, 1046, 0.7)], 1.1,
                harmonics=(1.0, 0.3, 0.1), decay=0.35) * 0.35


def s_click() -> np.ndarray:
    n = int(SR * 0.05)
    return _sine(1200, 0.05) * _env(n, 0.001, 0.015) * 0.25


def s_error() -> np.ndarray:
    n = int(SR * 0.18)
    return (np.sign(_sine(130, 0.18)) * 0.15 + _sine(97, 0.18) * 0.2) * _env(n, 0.005, 0.12)


def s_death() -> np.ndarray:
    n = int(SR * 1.2)
    return _sine(np.linspace(220, 80, n), 1.2) * _env(n, 0.02, 0.8) * 0.35


def s_roar() -> np.ndarray:
    n = int(SR * 0.9)
    t = _t(0.9)
    saw = ((t * 95 + 0.3 * np.sin(t * 30)) % 1.0 - 0.5) * 2
    growl = _lp_fast(saw.astype(np.float32) + _noise(n, 13) * 0.5, 6) * np.sin(np.linspace(0, np.pi, n)) ** 0.5
    return growl * 0.45


def s_summon() -> np.ndarray:
    n = int(SR * 0.7)
    rise = _sine(np.linspace(200, 900, n), 0.7) * np.sin(np.linspace(0, np.pi, n)) * 0.25
    return _mix(rise, _lp_fast(_noise(n, 14), 10) * np.sin(np.linspace(0, np.pi, n)) * 0.6)


def s_cast() -> np.ndarray:
    n = int(SR * 0.35)
    return _sine(np.linspace(300, 520, n), 0.35) * np.sin(np.linspace(0, np.pi, n)) * 0.18


def s_grunt() -> np.ndarray:
    n = int(SR * 0.3)
    t = _t(0.3)
    saw = (((t * 70) % 1.0) - 0.5).astype(np.float32)
    return _lp_fast(saw + _noise(n, 15) * 0.4, 8) * _env(n, 0.01, 0.2) * 0.8


def s_charge() -> np.ndarray:
    return _mix(s_swing() * 1.2, s_grunt()[: int(SR * 0.2)] * 0.6)


def _horn(freq: float, dur: float, vib: float = 4.0) -> np.ndarray:
    """Brassy horn tone (harmonics, slow attack, vibrato)."""
    t = _t(dur)
    f = freq * (1.0 + 0.006 * np.sin(2 * np.pi * vib * t))
    ph = np.cumsum(f) / SR
    s = np.zeros_like(t)
    for k, a in enumerate((1.0, 0.7, 0.45, 0.3, 0.18, 0.1)):
        s += a * np.sin(2 * np.pi * ph * (k + 1))
    env = np.clip(t / 0.08, 0, 1) * np.clip((dur - t) / 0.25, 0, 1)
    return (np.tanh(s * 0.8) * env * 0.35).astype(np.float32)


def s_ack() -> np.ndarray:
    second = np.concatenate([np.zeros(int(SR * 0.07), np.float32), _note(523, 0.14, (1.0, 0.4, 0.2), 0.1) * 0.35])
    return _mix(_note(392, 0.12, (1.0, 0.4, 0.2), 0.08) * 0.35, second)


def s_select() -> np.ndarray:
    return _note(660, 0.09, (1.0, 0.3), 0.05) * 0.25


def s_alert() -> np.ndarray:
    return _mix(_horn(110, 1.4), np.concatenate([np.zeros(int(SR * 0.5), np.float32), _horn(146.8, 1.2) * 0.8]))


def s_build() -> np.ndarray:
    out = np.zeros(int(SR * 0.6), np.float32)
    for k in range(3):
        n = int(SR * 0.08)
        knock = (_sine(np.linspace(900, 500, n), 0.08) * 0.4 + _lp_fast(_noise(n, 30 + k), 3) * 0.5) * _env(n, 0.001, 0.03)
        i = int(k * 0.18 * SR)
        out[i:i + n] += knock
    return out


def s_chop() -> np.ndarray:
    n = int(SR * 0.18)
    thunk = _sine(np.linspace(260, 140, n), 0.18) * _env(n, 0.001, 0.07) * 0.7
    crack = _lp_fast(_noise(n, 33), 4) * _env(n, 0.001, 0.025) * 0.6
    return _mix(thunk, crack)


def s_explosion() -> np.ndarray:
    n = int(SR * 1.1)
    boom = _sine(np.linspace(90, 28, n), 1.1) * _env(n, 0.003, 0.45) * 0.9
    roar = _lp_fast(_noise(n, 34), 12) * _env(n, 0.005, 0.5) * 2.2
    return _mix(boom, roar)


def s_collapse() -> np.ndarray:
    n = int(SR * 1.8)
    rumble = _lp_fast(_noise(n, 35), 40) * _env(n, 0.05, 1.2) * 6.0
    debris = np.zeros(n, np.float32)
    rng = np.random.default_rng(36)
    for _ in range(14):
        i = int(rng.integers(0, n - SR // 6))
        m = int(SR * 0.06)
        debris[i:i + m] += _lp_fast(_noise(m, int(rng.integers(0, 999))), 3) * _env(m, 0.001, 0.03) * 0.5
    return _mix(rumble * 0.7, debris, s_explosion()[:n] * 0.5)


def s_throw() -> np.ndarray:
    n = int(SR * 0.5)
    creak = _sine(np.linspace(140, 90, n), 0.5) * _env(n, 0.02, 0.2) * 0.25
    return _mix(creak, s_swing() * 1.3)


def s_victory() -> np.ndarray:
    notes = [(0.0, 261.6, 0.5), (0.25, 329.6, 0.5), (0.5, 392.0, 0.5), (0.8, 523.3, 1.6), (0.8, 392.0, 1.6), (0.8, 659.3, 1.6)]
    return _mix(_seq(notes, 2.8, harmonics=(1.0, 0.6, 0.35, 0.2), decay=0.9) * 0.4, _horn(130.8, 2.4) * 0.5)


def s_defeat() -> np.ndarray:
    notes = [(0.0, 392.0, 0.8), (0.6, 349.2, 0.8), (1.2, 311.1, 0.9), (1.9, 261.6, 1.8), (1.9, 155.6, 1.8)]
    return _seq(notes, 4.0, harmonics=(1.0, 0.5, 0.3), decay=1.0) * 0.4


def s_coin() -> np.ndarray:
    second = np.concatenate([np.zeros(int(SR * 0.05), np.float32), _note(2093, 0.15, (1.0, 0.3), 0.06) * 0.2])
    return _mix(_note(1568, 0.12, (1.0, 0.3), 0.05) * 0.2, second)


def _loop(x: np.ndarray, fade: float = 0.5) -> np.ndarray:
    """Make a seamless loop by cross-fading the tail into the head."""
    f = int(SR * fade)
    head, body, tail = x[:f], x[f:-f], x[-f:]
    w = np.linspace(0, 1, f, dtype=np.float32)
    joined = tail * (1 - w) + head * w
    return np.concatenate([body, joined])


def s_wind() -> np.ndarray:
    n = int(SR * 9.0)
    t = _t(9.0)
    base = _lp_fast(_noise(n, 16), 40) * 6.0
    gust = 0.55 + 0.45 * np.sin(t * 2 * np.pi / 4.5) * np.sin(t * 2 * np.pi / 9.0 + 1.0)
    whistle = _lp_fast(_noise(n, 17), 3) * 0.08 * (0.5 + 0.5 * np.sin(t * 1.4))
    return _loop((base * gust + whistle) * 0.5, 1.0)


def s_night() -> np.ndarray:
    n = int(SR * 8.0)
    out = np.zeros(n, np.float32)
    rng = np.random.default_rng(22)
    for _ in range(26):
        i = rng.integers(0, n - SR // 3)
        f = rng.uniform(3800, 4600)
        chirp = np.concatenate([_note(f, 0.05, (1.0,), 0.02), np.zeros(int(SR * 0.03), np.float32)] * 3) * 0.08
        out[i:i + len(chirp)] += chirp[: n - i]
    return _loop(out + _lp_fast(_noise(n, 23), 40) * 0.6, 0.8)


def s_theme() -> np.ndarray:
    """Menu theme: low strings pad in D minor with distant horn calls."""
    total = 32.0
    n = int(SR * total)
    out = np.zeros(n, np.float32)
    chords = [(146.8, 174.6, 220.0), (116.5, 146.8, 174.6), (130.8, 164.8, 196.0), (110.0, 138.6, 164.8)]
    seg = total / len(chords)
    for ci, ch in enumerate(chords):
        t = _t(seg + 2.0)
        env = np.clip(t / 2.5, 0, 1) * np.clip((seg + 2.0 - t) / 2.5, 0, 1)
        s = np.zeros_like(t)
        for f in ch:
            for det in (0.997, 1.0, 1.003):
                s += np.sin(2 * np.pi * f * det * t) * 0.12
            s += np.sin(2 * np.pi * f * 0.5 * t) * 0.08
        s *= env * (0.85 + 0.15 * np.sin(t * 0.9))
        i = int(ci * seg * SR)
        m = min(len(s), n - i)
        out[i:i + m] += s[:m]
    for t0, f in ((3.0, 293.7), (11.0, 349.2), (19.0, 293.7), (27.0, 261.6)):
        h = _horn(f, 2.6, 3.0) * 0.45
        i = int(t0 * SR)
        out[i:i + len(h)] += h[: n - i]
    drum = np.zeros(n, np.float32)
    for k in range(int(total / 2.0)):
        i = int(k * 2.0 * SR)
        b = _sine(np.linspace(65, 38, int(SR * 0.5)), 0.5) * _env(int(SR * 0.5), 0.002, 0.25) * (0.55 if k % 2 == 0 else 0.3)
        drum[i:i + len(b)] += b[: n - i]
    return _loop((out * 0.5 + drum * 0.45).astype(np.float32), 2.0)


RECIPES: dict[str, Callable[[], np.ndarray]] = {
    "hit": s_hit, "swing": s_swing, "bow": s_bow, "fire": s_fire, "heal": s_heal, "click": s_click, "error": s_error,
    "death": s_death, "roar": s_roar, "summon": s_summon, "cast": s_cast, "grunt": s_grunt,
    "ack": s_ack, "ack_attack": s_charge, "select": s_select, "alert": s_alert, "build": s_build, "chop": s_chop,
    "explosion": s_explosion, "collapse": s_collapse, "throw": s_throw, "victory": s_victory, "defeat": s_defeat,
    "coin": s_coin,
    "amb_wind": s_wind, "amb_night": s_night, "theme": s_theme,
}


def _write_wav(path: Path, x: np.ndarray) -> None:
    peak = float(np.max(np.abs(x))) if len(x) else 1.0
    if peak > 0.98:
        x = x / peak * 0.98
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


class AudioSystem:
    """Generates (once), caches and plays all game sounds."""

    POOL = 4
    HEAR = 75.0          # sounds further than this from the camera focus are silent

    def __init__(self, listener: Callable[[], tuple[float, float] | None] | None = None) -> None:
        from ursina.audio import _audio_manager
        self.mgr = _audio_manager
        self.listener = listener
        self.dir = CACHE_DIR / f"sounds_v{AUDIO_VERSION}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sounds: dict[str, list[AudioSound]] = {}
        self._rr: dict[str, int] = {}
        self._last: dict[str, float] = {}
        self._clock = 0.0
        self.loops: dict[str, AudioSound] = {}
        self.loop_vol: dict[str, float] = {}
        self.loop_target: dict[str, float] = {}
        for name, fn in RECIPES.items():
            path = self.dir / f"{name}.wav"
            if not path.exists():
                _write_wav(path, fn())
            if name.startswith("amb_") or name == "theme":
                snd = self.mgr.getSound(Filename.fromOsSpecific(str(path)))
                snd.setLoop(True)
                snd.setVolume(0.0)
                self.loops[name] = snd
                self.loop_vol[name] = 0.0
                self.loop_target[name] = 0.0
            else:
                self.sounds[name] = [self.mgr.getSound(Filename.fromOsSpecific(str(path))) for _ in range(self.POOL)]
        events.on("sound", self._on_sound)

    def _on_sound(self, name: str, volume: float = 1.0, pos: tuple[float, float] | None = None, **_: object) -> None:
        if pos is not None and self.listener is not None:
            lp = self.listener()
            if lp is not None:
                d = math.hypot(pos[0] - lp[0], pos[1] - lp[1])
                if d > self.HEAR:
                    return
                volume *= max(0.15, 1.0 - d / self.HEAR) ** 1.5
        gap = 0.09 if name in ("hit", "bow", "swing", "chop", "death") else 0.05
        if self._clock - self._last.get(name, -1.0) < gap:
            return
        self._last[name] = self._clock
        self.play(name, volume, pitch=0.93 + 0.14 * ((self._rr.get(name, 0) * 37) % 10) / 10.0)

    def play(self, name: str, volume: float = 1.0, pitch: float = 1.0) -> None:
        pool = self.sounds.get(name)
        if not pool:
            return
        i = self._rr.get(name, 0)
        self._rr[name] = (i + 1) % len(pool)
        s = pool[i]
        s.setVolume(max(0.0, min(1.0, volume * user_settings.master_volume * user_settings.sfx_volume)))
        s.setPlayRate(pitch)
        s.play()

    def set_ambience(self, levels: dict[str, float]) -> None:
        """Target volume per looping track (0..1); they fade smoothly."""
        for name in self.loops:
            self.loop_target[name] = levels.get(name, 0.0)

    def update(self, dt: float) -> None:
        self._clock += dt
        for name, snd in self.loops.items():
            cur = self.loop_vol[name]
            tgt = self.loop_target[name]
            if abs(cur - tgt) > 0.001:
                cur += (tgt - cur) * min(1.0, dt * 1.2)
                self.loop_vol[name] = cur
            vol_group = user_settings.ambient_volume if name != "theme" else 0.85
            v = cur * user_settings.master_volume * vol_group
            snd.setVolume(v)
            playing = snd.status() == AudioSound.PLAYING
            if v > 0.002 and not playing:
                snd.play()
            elif v <= 0.002 and playing:
                snd.stop()
