# -*- coding: utf-8 -*-
"""Microsoft Edge TTS backend -- free, no API key, word-level timing.

This is the default provider. It talks to the "Read Aloud" endpoint inside the
Microsoft Edge browser via the `edge-tts` package. That endpoint is undocumented
and may change or disappear without notice; see the README disclaimer.
"""

import asyncio
import os

from .base import Provider, ProviderError

_BOUNDARY_TYPES = ("WordBoundary", "SentenceBoundary")

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
    # Multilingual voices switch language mid-sentence; use these for scripts
    # that mix Chinese and English.
    "多语言-女声": "en-US-AvaMultilingualNeural",
    "多语言-女声2": "en-US-EmmaMultilingualNeural",
    "多语言-男声": "en-US-AndrewMultilingualNeural",
    "多语言-男声2": "en-US-BrianMultilingualNeural",
}


class EdgeProvider(Provider):
    name = "edge"
    label = "Microsoft Edge TTS（免费、无需 Key、有词级时间戳）"
    supports_srt = True
    needs_api_key = False
    needs_ffmpeg = False
    default_voice = "zh-CN-XiaoxiaoNeural"
    PRESETS = PRESETS
    SETUP_HINT = "无需配置，开箱即用"

    # ------------------------------------------------------------------ module
    @staticmethod
    def _module():
        try:
            import edge_tts
            return edge_tts
        except ImportError:
            pass

        _auto_install()

        try:
            import edge_tts
            return edge_tts
        except ImportError:
            raise ProviderError(
                "缺少依赖 edge-tts。安装：pip install -r requirements.txt"
            )

    def available(self):
        try:
            module = self._module()
        except ProviderError as exc:
            return False, str(exc)
        return True, "edge-tts %s" % getattr(module, "__version__", "?")

    # -------------------------------------------------------------------- data
    def list_voices(self, lang=None):
        module = self._module()
        try:
            raw = asyncio.run(module.list_voices())
        except Exception as exc:
            raise ProviderError("无法获取音色列表：%s: %s" % (type(exc).__name__, exc))

        key = (lang or "").strip().lower()
        voices = []
        for v in raw:
            sid = v.get("ShortName", "")
            if key and key not in sid.lower():
                continue
            voices.append({
                "id": sid,
                "name": sid,
                "gender": v.get("Gender", ""),
                "locale": v.get("Locale", ""),
            })
        return sorted(voices, key=lambda x: x["id"])

    # --------------------------------------------------------------- synthesis
    def synthesize(self, text, voice, rate, volume, pitch, out_path):
        module = self._module()
        proxy = self.options.get("proxy")

        kwargs = {
            "rate": rate or "+0%",
            "volume": volume or "+0%",
            "pitch": pitch or "+0Hz",
        }
        if proxy:
            kwargs["proxy"] = proxy

        try:
            communicate = module.Communicate(text, voice, boundary="WordBoundary", **kwargs)
        except TypeError:
            # edge-tts builds that predate the `boundary` kwarg
            communicate = module.Communicate(text, voice, **kwargs)

        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        boundaries = []
        tmp = out_path + ".part"

        async def _run():
            with open(tmp, "wb") as fh:
                async for chunk in communicate.stream():
                    ctype = chunk.get("type")
                    if ctype == "audio":
                        fh.write(chunk["data"])
                    elif ctype in _BOUNDARY_TYPES:
                        boundaries.append(chunk)

        try:
            asyncio.run(_run())
        except Exception as exc:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise ProviderError(_explain(exc, voice))
        os.replace(tmp, out_path)
        return boundaries

    # ------------------------------------------------------------- validation
    def unsupported_features(self, volume, pitch):
        return []  # Edge supports both


def _auto_install():
    """Install edge-tts on first use, unless the user opted out.

    Scoped to this provider on purpose: running with `--provider system` should
    never pull a network dependency the user did not ask for.
    """
    import subprocess
    import sys

    if os.environ.get("TTS_NO_AUTO_INSTALL"):
        raise ProviderError(
            "缺少依赖 edge-tts，且已设置 TTS_NO_AUTO_INSTALL，跳过自动安装。\n"
            "请手动安装：pip install -r requirements.txt"
        )

    print("首次运行 edge 后端，正在安装依赖 edge-tts ...", file=sys.stderr)
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "edge-tts"]
        )
    except (subprocess.CalledProcessError, OSError):
        raise ProviderError(
            "自动安装 edge-tts 失败。请手动执行：\n"
            "  pip install -r requirements.txt\n"
            "或设置 TTS_NO_AUTO_INSTALL=1 以跳过自动安装并自行管理依赖。"
        )


def _explain(exc, voice):
    name = type(exc).__name__
    if name == "NoAudioReceived":
        return (
            "音色 %s 没有产出音频。最常见的原因是用单语音色读另一种语言"
            "（例如 en-US-AriaNeural 读中文）。请改用多语言音色"
            "（--style 多语言-女声 / 多语言-男声），或换成该语言对应的音色。" % voice
        )
    return "%s: %s" % (name, exc)
