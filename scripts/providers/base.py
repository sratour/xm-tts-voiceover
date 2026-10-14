# -*- coding: utf-8 -*-
"""Backend abstraction: one CLI, several speech providers.

A provider turns text into an audio file. Providers that can report where each
word lands in the audio also return *boundary events*, which is what makes
time-aligned subtitles possible. Providers that cannot must return an empty list
and let the caller refuse `--srt` -- inventing timings would produce subtitles
that silently drift out of sync, which is worse than not producing them.
"""

import shutil

# Boundary offsets are expressed in 100-nanosecond ticks -- the unit used by the
# Edge TTS and Azure word-boundary events. Keeping that unit means the subtitle
# builder works the same regardless of which provider produced the events.
TICKS_PER_SECOND = 10_000_000


class ProviderError(RuntimeError):
    """A provider cannot fulfil the request: bad config, no network, or no capability."""


def parse_percent(value, default=0.0):
    """'+25%' -> 0.25, '-10%' -> -0.10, '' / None -> default."""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text) / 100.0
    except ValueError:
        raise ProviderError("无法解析百分比 %r，示例：+25%%、-10%%" % value)


def parse_hz(value, default=0.0):
    """'+20Hz' -> 20.0, '-15Hz' -> -15.0, '' / None -> default."""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if text.lower().endswith("hz"):
        text = text[:-2]
    try:
        return float(text)
    except ValueError:
        raise ProviderError("无法解析音调 %r，示例：+20Hz、-15Hz" % value)


def require_ffmpeg(provider_label):
    """Providers that emit WAV/AIFF need ffmpeg to reach the mp3 the CLI promises."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ProviderError(
            "%s 后端需要 ffmpeg 把系统音频转成 mp3，但没找到 ffmpeg。\n"
            "装一个 ffmpeg 即可（macOS: brew install ffmpeg；"
            "Debian/Ubuntu: apt install ffmpeg；Windows: winget install ffmpeg），"
            "或改用 --provider edge。" % provider_label
        )
    return ffmpeg


class Provider(object):
    """Base class. Subclasses override everything except `resolve_voice`."""

    name = "base"
    label = "Base"
    #: whether synthesize() can return real word/sentence boundary events
    supports_srt = False
    needs_api_key = False
    needs_ffmpeg = False
    default_voice = None
    #: alias -> voice id, for `--style`
    PRESETS = {}
    #: one-line hint shown by `doctor` / error messages
    SETUP_HINT = ""

    def __init__(self, options=None):
        self.options = options or {}

    # -------------------------------------------------------------- capability
    def available(self):
        """Return (ok, reason). `reason` is shown to the user when ok is False."""
        raise NotImplementedError

    # -------------------------------------------------------------------- data
    def list_voices(self, lang=None):
        """Return a list of {'id', 'name', 'gender', 'locale'} dicts."""
        raise NotImplementedError

    def synthesize(self, text, voice, rate, volume, pitch, out_path):
        """Write audio to `out_path`. Return boundary events (possibly empty)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ shared
    def resolve_voice(self, voice=None, style=None):
        """A `--style` alias wins, then an explicit voice, then the default."""
        if style:
            key = style.strip()
            if key in self.PRESETS:
                return self.PRESETS[key]
            for alias, vid in self.PRESETS.items():
                if alias.lower() == key.lower():
                    return vid
            raise ProviderError(
                "后端 %s 没有音色预设 %r。\n"
                "查看可用预设：tts.py styles --provider %s\n"
                "也可以直接用 --voice 指定音色。" % (self.name, style, self.name)
            )
        if voice:
            return voice.strip()
        return self.default_voice

    def unsupported_features(self, volume, pitch):
        """Names of requested features this provider silently cannot honour."""
        missing = []
        if volume and str(volume).strip() not in ("", "+0%", "0%", "0"):
            missing.append("--volume")
        if pitch and str(pitch).strip() not in ("", "+0Hz", "0Hz", "0"):
            missing.append("--pitch")
        return missing
