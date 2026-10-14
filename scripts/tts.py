#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配音 TTS - text-to-speech voiceover CLI with pluggable backends.

Default backend is Microsoft Edge TTS: free, no API key, and the only one that
returns word-level timings (which is what makes time-aligned subtitles possible).
Alternatives:

  * ``--provider openai``  any OpenAI-compatible ``/v1/audio/speech`` endpoint --
    OpenAI itself, LocalAI, Fish Speech, Kokoro-FastAPI, cloud vendors, ...
  * ``--provider system``  the OS engine (Windows SAPI / macOS ``say`` /
    Linux espeak-ng): no key, fully offline.

Usage:
  python tts.py doctor
  python tts.py providers
  python tts.py voices [--lang zh] [--provider openai]
  python tts.py styles [--provider openai]
  python tts.py say --text "你好，欢迎收听" --style 女声-温柔 --out out.mp3 --srt
  python tts.py say --text "Hello" --provider openai --voice nova --out out.mp3
  python tts.py say --text "完全离线" --provider system --out out.mp3
  python tts.py batch --file lines.json --outdir ./audio --merge final.mp3
"""

import argparse
import json
import os
import sys

# The CLI prints Chinese text. On Windows, stdout/stderr default to the console
# code page (cp936/cp1252) when piped, which raises UnicodeEncodeError. Force
# UTF-8 so output is identical on every platform and in CI logs.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

# Importing the package from the script's own directory works because Python
# puts the script's folder at the front of sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from providers import ProviderError, get as get_provider  # noqa: E402
from providers import describe_all, names as provider_names  # noqa: E402

__version__ = "1.1.0"

DEFAULT_STYLE = "女声-温柔"


# ---------------------------------------------------------------- subtitles
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
    """Group boundary events into subtitle cues."""
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


def _write_srt(path, cues):
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append("%s --> %s" % (_fmt_ts(start), _fmt_ts(end)))
        lines.append(text.strip())
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------- audio utils
def _audio_duration(path):
    """Duration in seconds. Prefers ffprobe; falls back to a CBR estimate.

    The estimate assumes 48 kbps, which is what both the Edge backend and the
    system backend's ffmpeg conversion produce. An OpenAI-compatible server may
    return a different bitrate, so ffprobe is genuinely preferred there.
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


def _merge_mp3(files, out_path, gap=0.0):
    """Concatenate mp3 files, inserting real silence of `gap` seconds between them.

    The silence is generated at 24 kHz mono 48 kbps to match the backend output,
    so the whole thing is stream-copied with no re-encode.
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
        try:
            subprocess.check_call(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", out_path]
            )
        finally:
            os.remove(listfile)
            if silence and os.path.exists(silence):
                os.remove(silence)
        return

    # fallback: mp3 is frame-based, so a plain byte concat is usually playable
    with open(out_path, "wb") as out:
        for p in seq:
            with open(p, "rb") as src:
                out.write(src.read())


# ---------------------------------------------------------------- provider glue
def _make_provider(args):
    options = {
        "api_key": getattr(args, "api_key", None),
        "base_url": getattr(args, "base_url", None),
        "model": getattr(args, "model", None),
        "proxy": getattr(args, "proxy", None),
    }
    try:
        provider = get_provider(getattr(args, "provider", None), options)
    except ProviderError as exc:
        raise SystemExit(str(exc))

    ok, reason = provider.available()
    if not ok:
        message = "后端 %s 不可用：%s" % (provider.name, reason)
        if provider.SETUP_HINT:
            message += "\n配置提示：%s" % provider.SETUP_HINT
        message += "\n查看全部后端状态：tts.py providers"
        raise SystemExit(message)
    return provider


def _guard_srt(provider, wants_srt):
    if wants_srt and not provider.supports_srt:
        raise SystemExit(
            "后端 %s 无法生成字幕。\n"
            "原因：该接口只返回整段音频，不提供每个词的时间位置，"
            "硬凑时间轴只会得到对不上的字幕。\n"
            "要字幕请改用 --provider edge（它返回词级时间戳），"
            "或去掉 --srt 只输出音频。" % provider.name
        )


def _warn_ignored(provider, volume, pitch):
    missing = provider.unsupported_features(volume, pitch)
    if missing:
        print("提示：后端 %s 不支持 %s，已忽略。" % (provider.name, "、".join(missing)),
              file=sys.stderr)


def _voice_label(voice):
    return voice if voice else "（系统默认）"


def _read_text(args):
    if getattr(args, "file", None):
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    elif getattr(args, "text", None):
        text = args.text
    else:
        text = sys.stdin.read()
    text = text.strip()
    if not text:
        raise SystemExit("文本为空，请用 --text / --file 提供内容，或通过 stdin 传入。")
    return text


# ---------------------------------------------------------------- commands
def cmd_providers(args):
    print("可用后端（--provider 可指定，默认 edge）：")
    print()
    for name, label, ok, reason, needs_ffmpeg in describe_all():
        mark = "[ok]  " if ok else "[--]  "
        default = "  ← 默认" if name == "edge" else ""
        print("%s%-8s %s%s" % (mark, name, label, default))
        print("          %s" % reason)
    print()
    print("切换后端：--provider <名称>，或设置环境变量 TTS_PROVIDER")


def cmd_voices(args):
    provider = _make_provider(args)
    try:
        voices = provider.list_voices(args.lang)
    except ProviderError as exc:
        raise SystemExit("获取音色列表失败：%s" % exc)

    if not voices:
        print("没有匹配的音色。换个 --lang 关键词（如 zh / en / ja），"
              "或用 --voice 直接指定音色名。")
        return

    print("后端: %s" % provider.name)
    print("%-36s %-8s %s" % ("VOICE", "GENDER", "LOCALE"))
    for v in voices:
        print("%-36s %-8s %s" % (v["id"], v.get("gender", ""), v.get("locale", "")))
    print("\n共 %d 个音色" % len(voices))

    if provider.name == "openai" and not getattr(provider, "voices_from_server", True):
        print("（服务端未提供音色列表，以上为 OpenAI 官方内置音色）")


def cmd_styles(args):
    provider = _make_provider(args)
    if not provider.PRESETS:
        print("后端 %s 没有内置音色预设，请直接用 --voice 指定音色。" % provider.name)
        return
    print("后端 %s 的音色预设（--style 可直接用别名）：" % provider.name)
    for alias, vid in provider.PRESETS.items():
        print("  %-12s -> %s" % (alias, vid))
    print("\n也可以直接传 --voice <音色名>；完整列表见 `tts.py voices --provider %s`"
          % provider.name)


def cmd_doctor(args):
    """Environment self-check: helps users diagnose a broken install."""
    import shutil

    print("配音 TTS - 环境自检")
    print("-" * 52)

    problems = []

    v = sys.version_info
    if v >= (3, 9):
        print("[ok]   Python %d.%d.%d" % (v.major, v.minor, v.micro))
    else:
        print("[FAIL] Python %d.%d.%d  —— 需要 3.9 或更高" % (v.major, v.minor, v.micro))
        problems.append("Python 版本过低")
    print("       解释器: %s" % sys.executable)

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg:
        print("[ok]   ffmpeg: %s" % ffmpeg)
        print("[%s]   ffprobe: %s" % ("ok" if ffprobe else "--", ffprobe or "未找到（时长将用估算值）"))
    else:
        print("[--]   ffmpeg 未找到 —— batch --merge 与 system 后端需要它")

    print("-" * 52)
    print("后端状态：")
    for name, label, ok, reason, needs_ffmpeg in describe_all():
        print("  [%s] %-8s %s" % ("ok" if ok else "--", name, label))
        print("           %s" % reason)
        if ok and needs_ffmpeg and not ffmpeg:
            print("           注意：该后端还需要 ffmpeg 才能输出 mp3")

    print("-" * 52)

    # The default backend is the one users hit first, so probe it for real.
    try:
        provider = get_provider(None, {})
        ok, reason = provider.available()
        if not ok:
            print("[FAIL] 默认后端 %s 不可用：%s" % (provider.name, reason))
            problems.append("默认后端不可用")
        else:
            voices = provider.list_voices("zh")
            print("[ok]   默认后端 %s 可用，中文音色 %d 个" % (provider.name, len(voices)))
    except Exception as exc:
        print("[FAIL] 默认后端探测失败: %s: %s" % (type(exc).__name__, exc))
        print("       检查网络；若在企业网络/代理后，试试 --proxy http://127.0.0.1:7890")
        problems.append("默认后端不可达")

    print("-" * 52)
    if problems:
        print("发现问题: %s" % "、".join(problems))
        sys.exit(1)
    print("一切就绪，可以直接用了。")


def cmd_say(args):
    text = _read_text(args)
    provider = _make_provider(args)
    _guard_srt(provider, args.srt)
    _warn_ignored(provider, args.volume, args.pitch)

    voice = provider.resolve_voice(args.voice, args.style)
    out = args.out or "voiceover.mp3"
    if not out.lower().endswith(".mp3"):
        out += ".mp3"

    try:
        boundaries = provider.synthesize(
            text, voice, args.rate, args.volume, args.pitch, out
        )
    except ProviderError as exc:
        raise SystemExit("合成失败：%s" % exc)

    print("后端: %s" % provider.name)
    print("音色: %s" % _voice_label(voice))
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

    provider = _make_provider(args)
    _guard_srt(provider, args.srt)
    _warn_ignored(provider, args.volume, args.pitch)

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
        voice = provider.resolve_voice(it.get("voice") or args.voice,
                                       it.get("style") or args.style)
        rate = it.get("rate") or args.rate
        volume = it.get("volume") or args.volume
        pitch = it.get("pitch") or args.pitch
        name = it.get("out") or ("%0*d.mp3" % (width, i))
        if not str(name).lower().endswith(".mp3"):
            name = str(name) + ".mp3"
        out = os.path.join(outdir, name)

        try:
            boundaries = provider.synthesize(text, voice, rate, volume, pitch, out)
        except ProviderError as exc:
            failed.append((i, text, voice, str(exc)))
            print("[%d/%d] 失败 (%s) %s" % (i, len(items), _voice_label(voice), exc),
                  file=sys.stderr)
            continue

        made.append(out)
        print("[%d/%d] %s  (%s)" % (i, len(items), out, _voice_label(voice)))

        if args.srt:
            cues = _build_cues(boundaries)
            _write_srt(os.path.splitext(out)[0] + ".srt", cues)
            for s, e, t in cues:
                all_cues.append((timeline + s, timeline + e, t))
            # Advance by the segment's real audio length (which includes trailing
            # silence after the last boundary), not by the last cue end -- using
            # the cue end would make the merged SRT drift ahead of the audio.
            timeline += int(_audio_duration(out) * 10_000_000) + gap_ticks

    if args.srt and all_cues:
        merged_srt = os.path.join(outdir, "all.srt")
        _write_srt(merged_srt, all_cues)
        print("合并字幕: %s" % os.path.abspath(merged_srt))

    if args.merge and made:
        merge_path = args.merge if args.merge.lower().endswith(".mp3") else args.merge + ".mp3"
        _merge_mp3(made, merge_path, gap=max(0.0, args.gap))
        print("合并音频: %s" % os.path.abspath(merge_path))

    print("\n完成，成功 %d / 共 %d 段，目录: %s"
          % (len(made), len(items), os.path.abspath(outdir)))
    if failed:
        print("\n失败 %d 段：" % len(failed), file=sys.stderr)
        for i, text, voice, err in failed:
            print("  第 %d 段 [%s] %s" % (i, _voice_label(voice), err), file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------- cli
def add_provider_flags(sp):
    sp.add_argument(
        "--provider",
        help="语音后端：%s（默认取 $TTS_PROVIDER，否则 edge）" % " / ".join(provider_names()),
    )
    sp.add_argument("--api-key",
                    help="API Key；也可用环境变量 OPENAI_API_KEY / TTS_API_KEY")
    sp.add_argument("--base-url",
                    help="OpenAI 兼容接口地址；也可用环境变量 OPENAI_BASE_URL / TTS_BASE_URL")
    sp.add_argument("--model",
                    help="模型名；也可用环境变量 TTS_MODEL")


def add_voice_flags(sp):
    sp.add_argument("--voice", help="音色名，如 zh-CN-YunxiNeural / nova")
    sp.add_argument("--style", help="音色预设别名，如 女声-温柔 / 男声-新闻")
    sp.add_argument("--rate", default="+0%", help="语速，如 +25%% / -10%%")
    sp.add_argument("--volume", default="+0%", help="音量，如 +30%%（仅 edge 支持）")
    sp.add_argument("--pitch", default="+0Hz", help="音调，如 +20Hz（仅 edge 支持）")
    sp.add_argument("--proxy", help="HTTP 代理，如 http://127.0.0.1:7890（仅 edge 支持）")


def build_parser():
    p = argparse.ArgumentParser(
        prog="tts.py",
        description="配音 TTS - 文字转语音配音，支持 Edge TTS / OpenAI 兼容接口 / 系统语音",
    )
    p.add_argument("--version", action="version",
                   version="tts-voiceover %s" % __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("voices", help="列出可用音色")
    v.add_argument("--lang", default="", help="按语言过滤，如 zh / en / ja")
    add_provider_flags(v)
    v.set_defaults(func=cmd_voices)

    s = sub.add_parser("styles", help="列出当前后端的音色预设")
    add_provider_flags(s)
    s.set_defaults(func=cmd_styles)

    pr = sub.add_parser("providers", help="列出所有后端及其可用状态")
    pr.set_defaults(func=cmd_providers)

    d = sub.add_parser("doctor", help="环境自检（排查装不上的问题）")
    d.set_defaults(func=cmd_doctor)

    a = sub.add_parser("say", help="把一段文本合成为 mp3")
    a.add_argument("--text", help="要合成的文本")
    a.add_argument("--file", help="从 txt 文件读取文本")
    a.add_argument("--out", default="voiceover.mp3", help="输出 mp3 路径")
    a.add_argument("--srt", action="store_true",
                   help="同时导出 .srt 字幕（需要 edge 等支持词级时间戳的后端）")
    add_voice_flags(a)
    add_provider_flags(a)
    a.set_defaults(func=cmd_say)

    b = sub.add_parser("batch", help="批量合成（JSON 或按行分隔的 txt）")
    b.add_argument("--file", required=True, help="batch 输入文件")
    b.add_argument("--outdir", default="voiceover", help="输出目录")
    b.add_argument("--srt", action="store_true", help="导出字幕（含合并 all.srt）")
    b.add_argument("--merge", help="把结果合并为一个 mp3")
    b.add_argument("--gap", type=float, default=0.3,
                   help="合并时每段之间插入的静音秒数，默认 0.3")
    add_voice_flags(b)
    add_provider_flags(b)
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
