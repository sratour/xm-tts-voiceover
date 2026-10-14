#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配音 TTS - text-to-speech voiceover CLI built on Microsoft Edge TTS.

Free, no API key. Supports Chinese / English / Japanese and many more
languages, multiple neural voices, rate / volume / pitch tuning, batch
generation and automatic SRT subtitle export.

Usage:
  python tts.py doctor
  python tts.py voices [--lang zh]
  python tts.py say --text "你好，欢迎收听" --voice zh-CN-XiaoxiaoNeural --out out.mp3 [--srt]
  python tts.py say --file script.txt --style 女声-温柔 --out out.mp3 --srt
  python tts.py batch --file lines.json --outdir ./audio [--merge final.mp3]
  python tts.py styles
"""

import argparse
import asyncio
import json
import os
import sys

__version__ = "1.0.0"

# The CLI prints Chinese text. On Windows, stdout/stderr default to the console
# code page (cp936/cp1252) when piped, which raises UnicodeEncodeError. Force
# UTF-8 so output is identical on every platform and in CI logs.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

# ---------------------------------------------------------------- dependencies
def _ensure_deps():
    try:
        import edge_tts  # noqa: F401
        return
    except ImportError:
        pass

    if os.environ.get("TTS_NO_AUTO_INSTALL"):
        raise SystemExit(
            "缺少依赖 edge-tts，且已设置 TTS_NO_AUTO_INSTALL，跳过自动安装。\n"
            "请手动安装：pip install -r requirements.txt"
        )

    import subprocess

    print("首次运行，正在安装依赖 edge-tts ...", file=sys.stderr)
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "edge-tts"]
        )
    except (subprocess.CalledProcessError, OSError):
        raise SystemExit(
            "自动安装 edge-tts 失败。请手动执行：\n"
            "  pip install -r requirements.txt\n"
            "或设置 TTS_NO_AUTO_INSTALL=1 以跳过自动安装并自行管理依赖。"
        )


_ensure_deps()

import edge_tts  # noqa: E402

# ---------------------------------------------------------------- presets
# Friendly aliases -> concrete Edge neural voices.
STYLE_PRESETS = {
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
    # multilingual voices: handle Chinese + English (and more) in one pass,
    # use these for mixed-language scripts
    "多语言-女声": "en-US-AvaMultilingualNeural",
    "多语言-女声2": "en-US-EmmaMultilingualNeural",
    "多语言-男声": "en-US-AndrewMultilingualNeural",
    "多语言-男声2": "en-US-BrianMultilingualNeural",
}

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_STYLE = "女声-温柔"


def resolve_voice(voice=None, style=None):
    """style alias wins, then explicit voice, then default."""
    if style:
        key = style.strip()
        if key in STYLE_PRESETS:
            return STYLE_PRESETS[key]
        # allow case-insensitive lookup for the latin aliases
        for k, v in STYLE_PRESETS.items():
            if k.lower() == key.lower():
                return v
        raise SystemExit(
            "未知音色预设: %s\n可用预设见 `python tts.py styles`" % style
        )
    if voice:
        return voice.strip()
    return DEFAULT_VOICE


# ---------------------------------------------------------------- helpers
def _fmt_ts(ticks):
    """100-nanosecond ticks -> SRT timestamp HH:MM:SS,mmm"""
    ms = int(ticks / 10000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


_BREAK_CHARS = "，。！？；：、,.!?;:…—\n"
_MAX_CUE_CHARS = 18


def _build_cues(boundaries):
    """Group WordBoundary events into subtitle cues."""
    cues = []
    buf_text, buf_start, buf_end = "", None, None
    prev_end = None
    for b in boundaries:
        text = b["text"]
        start = b["offset"]
        end = b["offset"] + b["duration"]
        gap = (start - prev_end) if prev_end is not None else 0
        if buf_text and (gap > 5_000_000 or len(buf_text) + len(text) > _MAX_CUE_CHARS):
            cues.append((buf_start, buf_end, buf_text))
            buf_text, buf_start, buf_end = "", None, None
        if buf_start is None:
            buf_start = start
        buf_text += text
        buf_end = end
        prev_end = end
        if text and text[-1] in _BREAK_CHARS:
            cues.append((buf_start, buf_end, buf_text))
            buf_text, buf_start, buf_end = "", None, None
    if buf_text:
        cues.append((buf_start, buf_end, buf_text))
    return cues


def _mp3_duration(path):
    """Duration of an mp3 in seconds.

    Edge TTS writes CBR 48 kbps mp3, so byte size alone is accurate; ffprobe is
    used when present for extra safety.
    """
    import shutil
    import subprocess

    probe = shutil.which("ffprobe")
    if probe:
        try:
            out = subprocess.check_output(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path],
                text=True,
            ).strip()
            if out:
                return float(out)
        except Exception:
            pass
    return os.path.getsize(path) * 8.0 / 48000.0


def _write_srt(path, cues):
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append("%s --> %s" % (_fmt_ts(start), _fmt_ts(end)))
        lines.append(text.strip())
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


_BOUNDARY_TYPES = ("WordBoundary", "SentenceBoundary")


class SynthError(RuntimeError):
    """Raised when one synthesis request fails."""


async def _synth(text, voice, rate, volume, pitch, out_path, proxy=None, word_level=True):
    """Synthesize one text block. Returns list of boundary events (word level by default)."""
    kwargs = {"rate": rate, "volume": volume, "pitch": pitch}
    if proxy:
        kwargs["proxy"] = proxy
    try:
        communicate = edge_tts.Communicate(
            text, voice, boundary="WordBoundary" if word_level else "SentenceBoundary", **kwargs
        )
    except TypeError:
        # older edge-tts without the `boundary` kwarg
        communicate = edge_tts.Communicate(text, voice, **kwargs)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    boundaries = []
    tmp = out_path + ".part"
    try:
        with open(tmp, "wb") as f:
            async for chunk in communicate.stream():
                ctype = chunk.get("type")
                if ctype == "audio":
                    f.write(chunk["data"])
                elif ctype in _BOUNDARY_TYPES:
                    boundaries.append(chunk)
    except Exception as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        name = type(exc).__name__
        if name == "NoAudioReceived":
            raise SynthError(
                "音色 %s 没有产出音频。常见原因：用单语音色读另一种语言"
                "（例如 en-US-AriaNeural 读中文）。请换成多语言音色"
                "（--style 多语言-女声 / 多语言-男声）或改用对应语言的音色。" % voice
            )
        raise SynthError("%s: %s" % (name, exc))
    os.replace(tmp, out_path)
    return boundaries


# ---------------------------------------------------------------- commands
def cmd_voices(args):
    async def _run():
        return await edge_tts.list_voices()

    voices = asyncio.run(_run())
    key = (args.lang or "").strip().lower()
    rows = []
    for v in voices:
        if key and key not in v["ShortName"].lower():
            continue
        rows.append((v["ShortName"], v["Gender"], v.get("Locale", "")))
    rows.sort()
    if not rows:
        print("没有匹配的音色，请换个 --lang 关键词，例如 zh / en / ja")
        return
    print("%-34s %-8s %s" % ("VOICE", "GENDER", "LOCALE"))
    for name, gender, locale in rows:
        print("%-34s %-8s %s" % (name, gender, locale))
    print("\n共 %d 个音色" % len(rows))


def cmd_styles(args):
    print("音色预设（--style 可直接用中文别名）：")
    for k, v in STYLE_PRESETS.items():
        print("  %-12s -> %s" % (k, v))
    print("\n也可以直接传 --voice <ShortName>，完整列表见 `python tts.py voices`")


def cmd_doctor(args):
    """Environment self-check: helps users diagnose a broken install."""
    import shutil

    print("配音 TTS - 环境自检")
    print("-" * 46)

    problems = []

    v = sys.version_info
    if v >= (3, 9):
        print("[ok]   Python %d.%d.%d" % (v.major, v.minor, v.micro))
    else:
        print("[FAIL] Python %d.%d.%d  —— 需要 3.9 或更高" % (v.major, v.minor, v.micro))
        problems.append("Python 版本过低")
    print("       解释器: %s" % sys.executable)

    print("[ok]   edge-tts %s" % getattr(edge_tts, "__version__", "?"))

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        print("[ok]   ffmpeg: %s" % ffmpeg)
    else:
        print("[--]   ffmpeg 未找到 —— 可选，仅 batch --merge 需要")

    print("-" * 46)

    try:
        voices = asyncio.run(edge_tts.list_voices())
        zh = sum(1 for x in voices if x["ShortName"].startswith("zh-"))
        print("[ok]   语音服务可达，共 %d 个音色（其中中文 %d 个）" % (len(voices), zh))
    except Exception as exc:
        print("[FAIL] 无法连接语音服务: %s: %s" % (type(exc).__name__, exc))
        print("       检查网络；若在企业网络/代理后，试试 --proxy http://127.0.0.1:7890")
        problems.append("语音服务不可达")

    print("-" * 46)
    if problems:
        print("发现问题: %s" % "、".join(problems))
        sys.exit(1)
    print("一切就绪，可以直接用了。")


def cmd_say(args):
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    text = text.strip()
    if not text:
        raise SystemExit("文本为空，请用 --text / --file 提供内容")

    voice = resolve_voice(args.voice, args.style)
    out = args.out or "voiceover.mp3"
    if not out.lower().endswith(".mp3"):
        out += ".mp3"

    try:
        boundaries = asyncio.run(
            _synth(text, voice, args.rate, args.volume, args.pitch, out, args.proxy)
        )
    except SynthError as exc:
        raise SystemExit("合成失败：%s" % exc)
    print("音色: %s" % voice)
    print("输出: %s" % os.path.abspath(out))
    print("字数: %d" % len(text))

    if args.srt:
        srt_path = os.path.splitext(out)[0] + ".srt"
        _write_srt(srt_path, _build_cues(boundaries))
        print("字幕: %s" % os.path.abspath(srt_path))


def _load_batch(path):
    """Return list of dicts: {text, voice?, style?, rate?, out?}"""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    stripped = raw.lstrip()
    if path.lower().endswith(".json") or stripped[:1] in "[{":
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("segments") or data.get("lines") or []
        items = []
        for i, it in enumerate(data):
            if isinstance(it, str):
                items.append({"text": it})
            elif isinstance(it, dict):
                items.append(it)
            else:
                raise SystemExit("batch 第 %d 项格式不支持" % (i + 1))
        return items

    # plain text: one non-empty line == one segment
    return [{"text": ln.strip()} for ln in raw.splitlines() if ln.strip()]


def cmd_batch(args):
    items = _load_batch(args.file)
    if not items:
        raise SystemExit("batch 文件里没有可合成的内容")

    outdir = args.outdir or "voiceover"
    os.makedirs(outdir, exist_ok=True)
    width = max(3, len(str(len(items))))

    made = []
    failed = []
    all_cues = []
    timeline = 0  # ticks, for a merged subtitle file
    gap_ticks = int(max(0.0, args.gap) * 10_000_000)
    for i, it in enumerate(items, 1):
        text = str(it.get("text", "")).strip()
        if not text:
            continue
        voice = resolve_voice(it.get("voice") or args.voice, it.get("style") or args.style)
        rate = it.get("rate") or args.rate
        volume = it.get("volume") or args.volume
        pitch = it.get("pitch") or args.pitch
        name = it.get("out") or ("%0*d.mp3" % (width, i))
        if not str(name).lower().endswith(".mp3"):
            name = str(name) + ".mp3"
        out = os.path.join(outdir, name)

        try:
            boundaries = asyncio.run(
                _synth(text, voice, rate, volume, pitch, out, args.proxy)
            )
        except SynthError as exc:
            failed.append((i, text, voice, str(exc)))
            print("[%d/%d] 失败 (%s) %s" % (i, len(items), voice, exc), file=sys.stderr)
            continue

        made.append(out)
        print("[%d/%d] %s  (%s)" % (i, len(items), out, voice))

        cues = _build_cues(boundaries)
        if args.srt:
            _write_srt(os.path.splitext(out)[0] + ".srt", cues)
        for s, e, t in cues:
            all_cues.append((timeline + s, timeline + e, t))
        # Advance by the segment's real audio length (which includes trailing
        # silence after the last word boundary), not by the last cue end — using
        # the cue end would make the merged SRT drift ahead of the merged audio.
        timeline += int(_mp3_duration(out) * 10_000_000) + gap_ticks

    if args.srt and all_cues:
        merged_srt = os.path.join(outdir, "all.srt")
        _write_srt(merged_srt, all_cues)
        print("合并字幕: %s" % os.path.abspath(merged_srt))

    if args.merge and made:
        merge_path = args.merge if args.merge.lower().endswith(".mp3") else args.merge + ".mp3"
        _merge_mp3(made, merge_path, gap=max(0.0, args.gap))
        print("合并音频: %s" % os.path.abspath(merge_path))

    print("\n完成，成功 %d / 共 %d 段，目录: %s" % (len(made), len(items), os.path.abspath(outdir)))
    if failed:
        print("\n失败 %d 段：" % len(failed), file=sys.stderr)
        for i, text, voice, err in failed:
            print("  第 %d 段 [%s] %s" % (i, voice, err), file=sys.stderr)
        sys.exit(1)


def _merge_mp3(files, out_path, gap=0.0):
    """Concatenate MP3 files, inserting real silence of `gap` seconds between them.

    Edge TTS emits 24 kHz mono 48 kbps mp3, so the silence is generated with
    matching parameters and the whole thing is stream-copied (no re-encode).
    """
    import shutil
    import subprocess

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")

    silence = None
    if ffmpeg and gap > 0 and len(files) > 1:
        silence = out_path + ".gap.mp3"
        subprocess.check_call(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", "%.3f" % gap, "-c:a", "libmp3lame", "-b:a", "48k",
             "-ar", "24000", "-ac", "1", silence]
        )

    seq = []
    for i, p in enumerate(files):
        if i and silence:
            seq.append(silence)
        seq.append(p)

    if ffmpeg:
        listfile = out_path + ".list.txt"
        with open(listfile, "w", encoding="utf-8") as f:
            for p in seq:
                f.write("file '%s'\n" % os.path.abspath(p).replace("\\", "/").replace("'", "'\\''"))
        subprocess.check_call(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", out_path]
        )
        os.remove(listfile)
        if silence and os.path.exists(silence):
            os.remove(silence)
        return
    # fallback: MP3 is frame-based, so a plain byte concat is usually playable
    with open(out_path, "wb") as out:
        for p in seq:
            with open(p, "rb") as src:
                out.write(src.read())


# ---------------------------------------------------------------- cli
def build_parser():
    p = argparse.ArgumentParser(
        prog="tts.py",
        description="配音 TTS - 基于 Edge TTS 的免费语音合成（无需 API Key）",
    )
    p.add_argument("--version", action="version",
                   version="tts-voiceover %s" % __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("voices", help="列出可用音色")
    v.add_argument("--lang", default="", help="按语言过滤，如 zh / en / ja")
    v.set_defaults(func=cmd_voices)

    s = sub.add_parser("styles", help="列出中文音色预设")
    s.set_defaults(func=cmd_styles)

    d = sub.add_parser("doctor", help="环境自检（排查装不上的问题）")
    d.set_defaults(func=cmd_doctor)

    def add_common(sp):
        sp.add_argument("--voice", help="音色 ShortName，如 zh-CN-YunxiNeural")
        sp.add_argument("--style", help="音色预设别名，如 女声-温柔 / 男声-新闻")
        sp.add_argument("--rate", default="+0%", help="语速，如 +20%% / -10%%")
        sp.add_argument("--volume", default="+0%", help="音量，如 +30%%")
        sp.add_argument("--pitch", default="+0Hz", help="音调，如 +20Hz / -15Hz")
        sp.add_argument("--proxy", help="HTTP 代理，如 http://127.0.0.1:7890")

    a = sub.add_parser("say", help="把一段文本合成为 mp3")
    a.add_argument("--text", help="要合成的文本")
    a.add_argument("--file", help="从 txt 文件读取文本")
    a.add_argument("--out", default="voiceover.mp3", help="输出 mp3 路径")
    a.add_argument("--srt", action="store_true", help="同时导出 .srt 字幕")
    add_common(a)
    a.set_defaults(func=cmd_say)

    b = sub.add_parser("batch", help="批量合成（JSON 或按行分隔的 txt）")
    b.add_argument("--file", required=True, help="batch 输入文件")
    b.add_argument("--outdir", default="voiceover", help="输出目录")
    b.add_argument("--srt", action="store_true", help="导出字幕（含合并 all.srt）")
    b.add_argument("--merge", help="把结果合并为一个 mp3")
    b.add_argument("--gap", type=float, default=0.3,
                   help="合并时每段之间插入的静音秒数，默认 0.3")
    add_common(b)
    b.set_defaults(func=cmd_batch)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
