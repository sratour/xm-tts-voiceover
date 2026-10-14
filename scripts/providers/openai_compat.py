# -*- coding: utf-8 -*-
"""OpenAI-compatible `/v1/audio/speech` backend.

One adapter covers a lot of ground, because `POST /v1/audio/speech` has become
the de-facto interface for TTS services:

* OpenAI itself
* self-hosted: LocalAI, Fish Speech, Kokoro-FastAPI, openedai-speech, GPT-SoVITS wrappers
* cloud vendors exposing an OpenAI-compatible surface

Point `--base-url` at any of them and it works. Configuration is read from flags
first, then environment variables, so keys never have to be written into a file.

Note: this endpoint returns raw audio only -- no word timings -- so `--srt` is
not available here.
"""

import json
import os
import urllib.error
import urllib.request

from .base import Provider, ProviderError, parse_percent

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "tts-1"

# Voices shipped by OpenAI's own API. Self-hosted servers normally advertise
# their own list via GET /audio/voices, which takes precedence when available.
OPENAI_VOICES = [
    ("alloy", "neutral"),
    ("ash", "male"),
    ("ballad", "male"),
    ("coral", "female"),
    ("echo", "male"),
    ("fable", "neutral"),
    ("nova", "female"),
    ("onyx", "male"),
    ("sage", "female"),
    ("shimmer", "female"),
    ("verse", "male"),
]

# These aliases only make sense against OpenAI's own voice set. Self-hosted
# servers name voices differently -- use --voice there.
PRESETS = {
    "女声-温柔": "nova",
    "女声-活泼": "coral",
    "男声-沉稳": "onyx",
    "男声-新闻": "echo",
    "男声-少年": "ash",
    "en-female": "nova",
    "en-male": "onyx",
}


class OpenAICompatProvider(Provider):
    name = "openai"
    label = "OpenAI 兼容接口"
    supports_srt = False
    needs_api_key = True
    needs_ffmpeg = False
    default_voice = "alloy"
    PRESETS = PRESETS
    SETUP_HINT = "设置 OPENAI_API_KEY（可选 OPENAI_BASE_URL / TTS_MODEL）"

    def __init__(self, options=None):
        super().__init__(options)
        opts = self.options

        self.base_url = (
            opts.get("base_url")
            or os.environ.get("TTS_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")

        self.api_key = (
            opts.get("api_key")
            or os.environ.get("TTS_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )

        self.model = (
            opts.get("model")
            or os.environ.get("TTS_MODEL")
            or os.environ.get("OPENAI_TTS_MODEL")
            or DEFAULT_MODEL
        )

        try:
            self.timeout = float(os.environ.get("TTS_TIMEOUT", "60"))
        except ValueError:
            self.timeout = 60.0

        #: False when /audio/voices was unreachable and we fell back to OpenAI's list
        self.voices_from_server = False

    # -------------------------------------------------------------- capability
    def available(self):
        if not self.base_url:
            return False, "未设置 Base URL"
        if not self.api_key:
            return False, "未设置 API Key（OPENAI_API_KEY 或 --api-key）"
        return True, "%s · model=%s" % (self.base_url, self.model)

    # -------------------------------------------------------------------- data
    def list_voices(self, lang=None):
        for path in ("/audio/voices", "/voices"):
            try:
                payload = self._request("GET", path)
            except ProviderError:
                continue
            voices = _extract_voices(payload)
            if voices:
                self.voices_from_server = True
                key = (lang or "").strip().lower()
                if key:
                    voices = [v for v in voices if key in (v["id"] + v["locale"]).lower()]
                return sorted(voices, key=lambda x: x["id"])

        self.voices_from_server = False
        return [
            {"id": vid, "name": vid, "gender": gender, "locale": ""}
            for vid, gender in OPENAI_VOICES
        ]

    # --------------------------------------------------------------- synthesis
    def synthesize(self, text, voice, rate, volume, pitch, out_path):
        speed = 1.0 + parse_percent(rate)
        # OpenAI documents 0.25 - 4.0; clamp so a typo cannot 400 the request.
        speed = max(0.25, min(4.0, speed))

        payload = {
            "model": self.model,
            "input": text,
            "voice": voice or self.default_voice,
            "response_format": "mp3",
        }
        # Only send `speed` when it differs from the default: some self-hosted
        # servers reject fields they do not implement.
        if abs(speed - 1.0) > 1e-6:
            payload["speed"] = round(speed, 3)

        audio = self._request("POST", "/audio/speech", payload, binary=True)
        if not audio:
            raise ProviderError("接口返回了空音频（检查 voice / model 是否被服务端接受）")

        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(audio)
        return []  # no timing data -> --srt is refused upstream

    # ------------------------------------------------------------------ shared
    def _request(self, method, path, payload=None, binary=False):
        url = self.base_url + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None

        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "*/*")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.api_key:
            request.add_header("Authorization", "Bearer " + self.api_key)

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise ProviderError("HTTP %s %s：%s" % (exc.code, path, _http_detail(exc)))
        except urllib.error.URLError as exc:
            raise ProviderError("无法连接 %s：%s" % (url, exc.reason))
        except OSError as exc:
            raise ProviderError("网络错误：%s" % exc)

        if binary:
            return body
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}


def _http_detail(exc):
    """Pull the most useful message out of an error body."""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:
        return ""
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw[:400]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:400]
        if parsed.get("message"):
            return str(parsed["message"])[:400]
    return raw[:400]


def _extract_voices(payload):
    """Accept the several shapes OpenAI-compatible servers use for voice lists."""
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("data") or payload.get("voices") or []
    else:
        return []

    voices = []
    for item in items:
        if isinstance(item, str):
            voices.append({"id": item, "name": item, "gender": "", "locale": ""})
        elif isinstance(item, dict):
            vid = item.get("id") or item.get("name") or item.get("voice")
            if not vid:
                continue
            voices.append({
                "id": str(vid),
                "name": str(item.get("name") or vid),
                "gender": str(item.get("gender") or ""),
                "locale": str(item.get("locale") or item.get("language") or ""),
            })
    return voices
