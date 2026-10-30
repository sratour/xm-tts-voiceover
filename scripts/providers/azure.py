# -*- coding: utf-8 -*-
"""Azure AI Speech backend -- the official Microsoft neural voices.

Unlike the free ``edge`` backend, this one is a documented, supported API and
needs a Speech resource: a subscription key plus a region. The trade-off is
that it exposes the full prebuilt voice catalogue (including 48 kHz
high-fidelity models) and is stable, at the cost of a key and per-character
billing beyond the free tier.

Endpoint layout (``POST`` for synthesis, ``GET`` for the voice list)::

    https://<region>.tts.speech.microsoft.com/cognitiveservices/v1
    https://<region>.tts.speech.microsoft.com/cognitiveservices/voices/list

The REST surface returns raw audio only -- no word timings -- so ``--srt`` is
not available here. (Word-boundary events exist, but only through the Speech
SDK, not the REST endpoint.)

Azure China (21Vianet) uses a different host. Point ``--azure-endpoint`` at it::

    https://<region>.tts.speech.azure.cn

Config, highest priority first:

* ``--azure-key`` / ``--azure-region`` / ``--azure-endpoint``
* ``AZURE_SPEECH_KEY`` / ``AZURE_SPEECH_REGION`` / ``AZURE_SPEECH_ENDPOINT``
* ``--api-key`` / ``TTS_API_KEY`` (generic fallback for the key)
"""

import json
import os
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

from .base import Provider, ProviderError

#: 24 kHz mono 48 kbps matches what every other backend emits, so `batch
#: --merge` can stream-copy the parts without re-encoding.
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"

USER_AGENT = "xm-tts-voiceover"

#: Same Chinese aliases as the edge backend -- the short names are identical,
#: so a preset that works on edge also works here.
PRESETS = {
    "女声-温柔": "zh-CN-XiaoxiaoNeural",
    "女声-活泼": "zh-CN-XiaoyiNeural",
    "女声-东北": "zh-CN-liaoning-XiaobeiNeural",
    "女声-陕西": "zh-CN-shaanxi-XiaoniNeural",
    "女声-台湾": "zh-TW-HsiaoChenNeural",
    "女声-粤语": "zh-HK-HiuMaanNeural",
    "男声-沉稳": "zh-CN-YunxiNeural",
    "男声-新闻": "zh-CN-YunyangNeural",
    "男声-少年": "zh-CN-YunjianNeural",
    "男声-粤语": "zh-HK-WanLungNeural",
    "en-female": "en-US-AriaNeural",
    "en-male": "en-US-GuyNeural",
    "ja-female": "ja-JP-NanamiNeural",
    "ja-male": "ja-JP-KeitaNeural",
    "ko-female": "ko-KR-SunHiNeural",
    "多语言-女声": "en-US-AvaMultilingualNeural",
    "多语言-女声2": "en-US-EmmaMultilingualNeural",
    "多语言-男声": "en-US-AndrewMultilingualNeural",
    "多语言-男声2": "en-US-BrianMultilingualNeural",
}


class AzureProvider(Provider):
    name = "azure"
    label = "Azure 语音（官方公开神经音色，需 Key）"
    supports_srt = False
    needs_api_key = True
    needs_ffmpeg = False
    default_voice = "zh-CN-XiaoxiaoNeural"
    PRESETS = PRESETS
    SETUP_HINT = (
        "设置 AZURE_SPEECH_KEY 与 AZURE_SPEECH_REGION"
        "（或用 --azure-key / --azure-region；Azure 中国区再设 --azure-endpoint）"
    )

    def __init__(self, options=None):
        super().__init__(options)
        opts = self.options

        self.key = (
            opts.get("azure_key")
            or os.environ.get("AZURE_SPEECH_KEY")
            or opts.get("api_key")
            or os.environ.get("TTS_API_KEY")
            or ""
        )
        self.region = (
            opts.get("azure_region")
            or os.environ.get("AZURE_SPEECH_REGION")
            or ""
        ).strip()
        self.endpoint = (
            opts.get("azure_endpoint")
            or os.environ.get("AZURE_SPEECH_ENDPOINT")
            or ""
        ).strip().rstrip("/")

        try:
            self.timeout = float(os.environ.get("TTS_TIMEOUT", "60"))
        except ValueError:
            self.timeout = 60.0

    # -------------------------------------------------------------- capability
    def available(self):
        if not self.key:
            return False, "未设置 Azure Key（AZURE_SPEECH_KEY 或 --azure-key）"
        if not self.endpoint and not self.region:
            return False, "未设置 Azure 区域（AZURE_SPEECH_REGION 或 --azure-region）"
        return True, "%s · key 已设置" % self._base()

    def _base(self):
        """Origin of the speech resource, without a trailing slash."""
        if self.endpoint:
            return self.endpoint
        return "https://%s.tts.speech.microsoft.com" % self.region

    # -------------------------------------------------------------------- data
    def list_voices(self, lang=None):
        payload = self._request("GET", "/cognitiveservices/voices/list")
        items = payload if isinstance(payload, list) else []

        key = (lang or "").strip().lower()
        voices = []
        for item in items:
            sid = item.get("ShortName") or ""
            if not sid:
                continue
            locale = item.get("Locale") or ""
            if key and key not in (sid + " " + locale).lower():
                continue
            voices.append({
                "id": sid,
                "name": item.get("DisplayName") or sid,
                "gender": item.get("Gender") or "",
                "locale": locale,
            })
        return sorted(voices, key=lambda x: x["id"])

    # --------------------------------------------------------------- synthesis
    def synthesize(self, text, voice, rate, volume, pitch, out_path):
        voice = voice or self.default_voice
        ssml = _build_ssml(text, voice, rate, volume, pitch)

        audio = self._request(
            "POST",
            "/cognitiveservices/v1",
            body=ssml.encode("utf-8"),
            content_type="application/ssml+xml",
            accept_audio=True,
        )
        if not audio:
            raise ProviderError("Azure 返回了空音频（检查音色名与区域是否匹配）")

        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(audio)
        return []  # REST gives no word timings -> --srt is refused upstream

    # ------------------------------------------------------------------ shared
    def _request(self, method, path, body=None, content_type=None, accept_audio=False):
        url = self._base() + path

        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Ocp-Apim-Subscription-Key", self.key)
        request.add_header("User-Agent", USER_AGENT)
        if content_type:
            request.add_header("Content-Type", content_type)
        if accept_audio:
            request.add_header("X-Microsoft-OutputFormat", OUTPUT_FORMAT)
            request.add_header("Accept", "audio/mpeg")
        else:
            request.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            raise ProviderError(_http_error(exc, path))
        except urllib.error.URLError as exc:
            raise ProviderError("无法连接 %s：%s" % (url, exc.reason))
        except OSError as exc:
            raise ProviderError("网络错误：%s" % exc)

        if accept_audio:
            return data
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return []


def _build_ssml(text, voice, rate, volume, pitch):
    """Wrap text in SSML, applying prosody only when it differs from the default."""
    lang = _locale_of(voice)

    attrs = []
    if rate and str(rate).strip() not in ("", "+0%", "0%"):
        attrs.append("rate='%s'" % escape(str(rate).strip()))
    if volume and str(volume).strip() not in ("", "+0%", "0%"):
        attrs.append("volume='%s'" % escape(str(volume).strip()))
    if pitch and str(pitch).strip() not in ("", "+0Hz", "0Hz"):
        attrs.append("pitch='%s'" % escape(str(pitch).strip()))

    inner = escape(text)
    if attrs:
        inner = "<prosody %s>%s</prosody>" % (" ".join(attrs), inner)

    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
        "xml:lang='%s'>"
        "<voice name='%s'>%s</voice>"
        "</speak>" % (lang, escape(voice), inner)
    )


def _locale_of(voice):
    """'zh-CN-liaoning-XiaobeiNeural' -> 'zh-CN'; fall back to 'en-US'."""
    parts = str(voice or "").split("-")
    if len(parts) >= 2 and parts[0] and parts[1]:
        return "%s-%s" % (parts[0], parts[1])
    return "en-US"


def _http_error(exc, path):
    """Turn an Azure error response into an actionable message."""
    detail = ""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:
        raw = ""
    if raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            detail = raw[:400]
        else:
            if isinstance(parsed, dict):
                error = parsed.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or "")[:400]
                else:
                    detail = str(parsed.get("message") or error or "")[:400]
            else:
                detail = str(parsed)[:400]

    hints = {
        401: "Key 无效，或区域与资源不匹配",
        403: "Key 没有权限（检查资源类型是否为 Speech）",
        429: "超出配额或速率限制",
    }
    hint = hints.get(exc.code, "")
    message = "HTTP %s %s" % (exc.code, path)
    if hint:
        message += "：%s" % hint
    if detail:
        message += "（%s）" % detail
    return message
