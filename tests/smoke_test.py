#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end smoke test for xm-tts-voiceover.

This is deliberately NOT a unit-test suite with mocked network responses. The
whole point of this project is that its default backend rides on an undocumented
Microsoft endpoint that can change or disappear without notice, so the only
meaningful test is one that actually calls the live service. A green run means
"it still works today".

Coverage:

* the CLI surface
* real synthesis through the Edge backend, plus word-aligned subtitles
* batch mode, merge, and combined-subtitle alignment
* the provider layer: the OpenAI-compatible backend is exercised against a local
  mock server (so no API key is needed), and the OS-native backend is exercised
  for real on whichever platform this runs on

The checks come in two tiers:

* **offline** -- the CLI surface, the provider layer against a local mock
  server, and the OS-native backend. Deterministic, and they always gate the
  run.
* **live** -- anything that actually calls Microsoft's endpoint. These are the
  whole point locally, but GitHub's runners sit behind datacenter IPs that the
  endpoint does not reliably serve, so CI sets ``TTS_SMOKE_REQUIRE_LIVE=0`` and
  a live failure degrades to a warning. Real outages are the job of the daily
  health workflow, which is allowed to fail and open an issue.

Run locally:

    python tests/smoke_test.py                    # live checks are mandatory
    TTS_SMOKE_REQUIRE_LIVE=0 python tests/smoke_test.py   # live checks advisory

Exit code 0 = everything passed, 1 = something broke.
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TTS = os.path.join(ROOT, "scripts", "tts.py")
SCRIPTS = os.path.join(ROOT, "scripts")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import mock_azure  # noqa: E402
import mock_openai  # noqa: E402

# Whether a failure of a check that talks to Microsoft's endpoint should fail
# the run. Locally that is what you want; on CI it is not, because the runner's
# datacenter IP may simply be refused by the undocumented endpoint, which says
# nothing about this code.
REQUIRE_LIVE = os.environ.get("TTS_SMOKE_REQUIRE_LIVE", "1").strip().lower() \
    not in ("0", "false", "no", "off")

FAILURES = []
WARNINGS = []
SKIPS = []


def report(name, ok, detail="", live=False):
    """Record one check.

    Pass ``live=True`` for anything that hits the network. When live checks are
    advisory (``TTS_SMOKE_REQUIRE_LIVE=0``) such a failure is printed as
    ``[warn]`` and recorded separately instead of failing the run.
    """
    if ok:
        prefix = "[ok]  "
    elif live and not REQUIRE_LIVE:
        prefix = "[warn]"
    else:
        prefix = "[FAIL]"

    line = "%s %s" % (prefix, name)
    if detail:
        line += "  -> %s" % detail
    print(line, flush=True)

    if not ok:
        if live and not REQUIRE_LIVE:
            WARNINGS.append(name)
        else:
            FAILURES.append(name)


def skip(name, detail=""):
    print("[skip] %s  -> %s" % (name, detail), flush=True)
    SKIPS.append(name)


def run_tts(*args, **kwargs):
    """Run the CLI and return (returncode, stdout, stderr)."""
    env = os.environ.copy()
    env.setdefault("TTS_NO_AUTO_INSTALL", "1")
    env.update(kwargs.pop("env", {}))
    proc = subprocess.run(
        [sys.executable, TTS] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **kwargs
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def tail(text, n=170):
    text = " ".join((text or "").split())
    return text[-n:] if len(text) > n else text


def srt_cues(path):
    """Return [(start_seconds, end_seconds, text)] parsed from an SRT file."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    cues = []
    pattern = (
        r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)\s*\n(.*?)(?=\n\s*\n|\Z)"
    )
    for m in re.finditer(pattern, content, re.S):
        g = [int(x) for x in m.groups()[:8]]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        cues.append((start, end, m.group(9).strip()))
    return cues


def check_cli_surface(tmp):
    code, out, err = run_tts("--version")
    report("--version responds", code == 0 and "xm-tts-voiceover" in out, out.strip() or tail(err))

    code, out, err = run_tts("providers")
    listed = all(name in out for name in ("edge", "openai", "system"))
    report("providers lists every backend", code == 0 and listed, tail(err))

    code, out, err = run_tts("styles")
    report("styles lists voice presets", code == 0 and "女声-温柔" in out, tail(err))

    # Everything above is offline. These two need the voice list, which comes
    # from Microsoft.
    code, out, err = run_tts("voices", "--lang", "zh")
    zh_count = len(re.findall(r"^zh-", out, re.M))
    report(
        "voices --lang zh returns Chinese voices",
        code == 0 and zh_count >= 10,
        "%d 个中文音色" % zh_count,
        live=True,
    )

    code, out, err = run_tts("doctor")
    report("doctor reports a healthy environment",
           code == 0 and "一切就绪" in out, tail(err), live=True)


def check_edge_backend(tmp):
    """The default backend, against the live service. Live."""
    mp3 = os.path.join(tmp, "one.mp3")
    code, out, err = run_tts(
        "say", "--text", "端到端冒烟测试，验证配音功能正常。",
        "--style", "女声-活泼", "--out", mp3, "--srt",
    )
    size = os.path.getsize(mp3) if os.path.exists(mp3) else 0
    report("edge: synthesizes audio", code == 0 and size > 1024, "%d bytes" % size, live=True)

    cues = srt_cues(os.path.splitext(mp3)[0] + ".srt")
    report(
        "edge: --srt emits word-aligned cues",
        len(cues) >= 1 and all(c[1] > c[0] for c in cues),
        "%d 条字幕" % len(cues),
        live=True,
    )


def check_batch(tmp):
    """Batch + merge + combined subtitles, against the live service. Live."""
    import tts

    lines = os.path.join(tmp, "lines.txt")
    with open(lines, "w", encoding="utf-8") as fh:
        fh.write("第一段测试。\n第二段测试。\n")

    outdir = os.path.join(tmp, "batch")
    merged = os.path.join(outdir, "full.mp3")
    gap = 0.5
    code, out, err = run_tts(
        "batch", "--file", lines, "--outdir", outdir,
        "--style", "男声-沉稳", "--srt", "--merge", merged, "--gap", str(gap),
    )
    parts = sorted(glob.glob(os.path.join(outdir, "0*.mp3")))
    report("batch writes one file per segment", code == 0 and len(parts) == 2,
           "%d 段" % len(parts), live=True)

    report("batch --merge produces a merged file",
           os.path.exists(merged) and os.path.getsize(merged) > 1024, live=True)

    all_srt = os.path.join(outdir, "all.srt")
    report("batch --srt produces a combined srt", os.path.exists(all_srt), live=True)

    if not (parts and os.path.exists(merged)):
        return

    d_parts = sum(tts._audio_duration(p) for p in parts)
    d_merged = tts._audio_duration(merged)
    # With ffmpeg the gap is real silence; without it the merge falls back to raw
    # MP3 frame concatenation, which cannot insert silence.
    has_ffmpeg = shutil.which("ffmpeg") is not None
    expected = d_parts + gap if has_ffmpeg else d_parts
    report(
        "merge duration matches %s" % ("ffmpeg path" if has_ffmpeg else "concat fallback"),
        abs(d_merged - expected) < 0.4,
        "实际 %.2fs / 预期 %.2fs%s" % (d_merged, expected, "" if has_ffmpeg else "（无 ffmpeg）"),
        live=True,
    )

    combined = srt_cues(all_srt)
    last_end = combined[-1][1] if combined else 0.0
    report(
        "combined srt stays aligned with merged audio",
        bool(combined) and 0 < last_end <= d_merged and (d_merged - last_end) < 2.5,
        "末条字幕 %.2fs / 音频 %.2fs" % (last_end, d_merged),
        live=True,
    )


def check_openai_backend(tmp):
    """Exercise the HTTP plumbing against a local mock, so no key is required."""
    server, base_url = mock_openai.start()
    common = ["--provider", "openai", "--base-url", base_url, "--api-key", "test-key"]
    try:
        code, out, err = run_tts("voices", *common)
        report("openai: lists voices from the server",
               code == 0 and "mock-voice" in out, tail(err))

        code, out, err = run_tts("styles", *common)
        report("openai: styles shows the OpenAI preset set",
               code == 0 and "nova" in out, tail(err))

        mp3 = os.path.join(tmp, "oai.mp3")
        code, out, err = run_tts("say", *common, "--voice", "mock-voice",
                                 "--text", "hello", "--out", mp3)
        report("openai: synthesizes via /audio/speech",
               code == 0 and os.path.exists(mp3) and os.path.getsize(mp3) > 0,
               "%d bytes" % (os.path.getsize(mp3) if os.path.exists(mp3) else 0))

        code, out, err = run_tts("say", *common, "--voice", "nope",
                                 "--text", "hello", "--out", os.path.join(tmp, "bad.mp3"))
        report("openai: surfaces the server's error message",
               code != 0 and "unknown voice" in err, tail(err))

        code, out, err = run_tts("say", *common, "--voice", "mock-voice",
                                 "--text", "hello", "--srt",
                                 "--out", os.path.join(tmp, "srt.mp3"))
        report("openai: --srt is refused instead of faking timings",
               code != 0 and "--provider edge" in err, tail(err))

        # A key is genuinely required -- this must not silently succeed.
        code, out, err = run_tts("say", "--provider", "openai", "--base-url", base_url,
                                 "--text", "hello", "--out", os.path.join(tmp, "nokey.mp3"),
                                 env={"OPENAI_API_KEY": "", "TTS_API_KEY": ""})
        report("openai: refuses to run without an API key", code != 0, tail(err))
    finally:
        server.shutdown()


def check_azure_backend(tmp):
    """Exercise the Azure REST plumbing against a local mock, so no key is required."""
    server, base_url = mock_azure.start()
    common = ["--provider", "azure", "--azure-key", "test-key", "--azure-endpoint", base_url]
    try:
        code, out, err = run_tts("voices", *common)
        report("azure: lists voices from the server",
               code == 0 and "zh-CN-XiaoxiaoNeural" in out, tail(err))

        code, out, err = run_tts("styles", *common)
        report("azure: styles shows the Chinese preset set",
               code == 0 and "女声-温柔" in out, tail(err))

        mp3 = os.path.join(tmp, "az.mp3")
        code, out, err = run_tts("say", *common, "--voice", "zh-CN-XiaoxiaoNeural",
                                 "--text", "你好", "--out", mp3)
        report("azure: synthesizes via /cognitiveservices/v1",
               code == 0 and os.path.exists(mp3) and os.path.getsize(mp3) > 0,
               "%d bytes" % (os.path.getsize(mp3) if os.path.exists(mp3) else 0))

        code, out, err = run_tts("say", *common, "--voice", "nope",
                                 "--text", "你好", "--out", os.path.join(tmp, "azbad.mp3"))
        report("azure: surfaces the server's error message",
               code != 0 and "unknown voice" in err, tail(err))

        code, out, err = run_tts("say", *common, "--voice", "zh-CN-XiaoxiaoNeural",
                                 "--text", "你好", "--srt",
                                 "--out", os.path.join(tmp, "azsrt.mp3"))
        report("azure: --srt is refused instead of faking timings",
               code != 0 and "--provider edge" in err, tail(err))

        # A key is genuinely required -- this must not silently succeed.
        code, out, err = run_tts("say", "--provider", "azure",
                                 "--azure-endpoint", base_url, "--text", "你好",
                                 "--out", os.path.join(tmp, "aznokey.mp3"),
                                 env={"AZURE_SPEECH_KEY": "", "TTS_API_KEY": ""})
        report("azure: refuses to run without a key", code != 0, tail(err))
    finally:
        server.shutdown()


def check_system_backend(tmp):
    """The OS-native backend, if this platform offers one."""
    code, out, err = run_tts("voices", "--provider", "system")
    if code != 0:
        skip("system: backend available", tail(err))
        return

    report("system: lists OS voices", "VOICE" in out, "")

    mp3 = os.path.join(tmp, "sys.mp3")
    if shutil.which("ffmpeg") is None:
        # The OS engines emit WAV/AIFF; without ffmpeg the backend cannot
        # produce mp3 at all. That is a missing optional dependency, not a
        # code defect, so skip instead of failing the build.
        skip("system: synthesizes offline", "未安装 ffmpeg，system 后端无法转 mp3")
    else:
        code, out, err = run_tts("say", "--provider", "system",
                                 "--text", "offline smoke test", "--out", mp3)
        size = os.path.getsize(mp3) if os.path.exists(mp3) else 0
        report("system: synthesizes offline", code == 0 and size > 1024, "%d bytes" % size)

    code, out, err = run_tts("say", "--provider", "system", "--text", "no subs",
                             "--srt", "--out", os.path.join(tmp, "sys_srt.mp3"))
    report("system: --srt is refused instead of faking timings",
           code != 0 and "--provider edge" in err, tail(err))


def main():
    import tts  # noqa: F401  (validates importability)

    print("xm-tts-voiceover smoke test")
    print("=" * 54)
    if not REQUIRE_LIVE:
        print("联网检查仅警告（TTS_SMOKE_REQUIRE_LIVE=0）—— 接口被限流不挂构建")
        print("=" * 54)

    tmp = tempfile.mkdtemp(prefix="tts-smoke-")
    try:
        check_cli_surface(tmp)
        check_edge_backend(tmp)
        check_batch(tmp)
        check_openai_backend(tmp)
        check_azure_backend(tmp)
        check_system_backend(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 54)
    if FAILURES:
        print("%d 项失败（硬门槛）：" % len(FAILURES))
        for name in FAILURES:
            print("  - %s" % name)
        return 1
    if WARNINGS:
        print("代码检查全部通过；%d 项联网检查未通过（按配置视为警告，不影响退出码）："
              % len(WARNINGS))
        for name in WARNINGS:
            print("  - %s" % name)
        print("如需让联网检查也当硬性门槛，去掉 TTS_SMOKE_REQUIRE_LIVE=0 再跑。")
        return 0
    if SKIPS:
        print("全部通过（跳过 %d 项：%s）" % (len(SKIPS), "、".join(SKIPS)))
        return 0
    print("全部通过 —— 语音服务正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
