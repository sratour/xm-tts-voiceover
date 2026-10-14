#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end smoke test for tts-voiceover.

This is deliberately NOT a unit-test suite with mocked responses. The whole
point of this project is that it rides on an undocumented Microsoft endpoint
that can change or disappear without notice, so the only meaningful test is one
that actually calls the live service. A green run means "it still works today".

It covers the CLI surface, real synthesis, subtitle generation, batch mode, and
the merge/silence behaviour -- i.e. every code path a user depends on.

Run locally:

    python tests/smoke_test.py

Exit code 0 = everything passed, 1 = something broke.
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TTS = os.path.join(ROOT, "scripts", "tts.py")
SCRIPTS = os.path.join(ROOT, "scripts")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

FAILURES = []


def report(name, ok, detail=""):
    prefix = "[ok]  " if ok else "[FAIL]"
    line = "%s %s" % (prefix, name)
    if detail:
        line += "  -> %s" % detail
    print(line, flush=True)
    if not ok:
        FAILURES.append(name)


def run_tts(*args):
    """Run the CLI and return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, TTS] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def tail(text, n=160):
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


def main():
    import tts  # noqa: E402  (after sys.path setup; also validates importability)

    print("tts-voiceover smoke test")
    print("=" * 52)

    tmp = tempfile.mkdtemp(prefix="tts-smoke-")
    try:
        # ---------------------------------------------------------- CLI surface
        code, out, err = run_tts("--version")
        report("--version responds", code == 0 and "tts-voiceover" in out, out.strip() or tail(err))

        code, out, err = run_tts("styles")
        report("styles lists voice presets", code == 0 and "女声-温柔" in out, tail(err))

        code, out, err = run_tts("voices", "--lang", "zh")
        zh_count = len(re.findall(r"^zh-", out, re.M))
        report(
            "voices --lang zh returns Chinese voices",
            code == 0 and zh_count >= 10,
            "%d 个中文音色" % zh_count,
        )

        code, out, err = run_tts("doctor")
        report("doctor reports a healthy environment", code == 0 and "一切就绪" in out, tail(err))

        # ------------------------------------------------------ live synthesis
        mp3 = os.path.join(tmp, "one.mp3")
        code, out, err = run_tts(
            "say", "--text", "端到端冒烟测试，验证配音功能正常。",
            "--style", "女声-活泼", "--out", mp3, "--srt",
        )
        size = os.path.getsize(mp3) if os.path.exists(mp3) else 0
        report("say synthesizes audio", code == 0 and size > 1024, "%d bytes" % size)

        cues = srt_cues(os.path.splitext(mp3)[0] + ".srt")
        report(
            "say --srt emits word-aligned cues",
            len(cues) >= 1 and all(c[1] > c[0] for c in cues),
            "%d 条字幕" % len(cues),
        )

        # ------------------------------------------------ batch, merge, timing
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
        report(
            "batch writes one file per segment",
            code == 0 and len(parts) == 2,
            "%d 段" % len(parts),
        )

        report(
            "batch --merge produces a merged file",
            os.path.exists(merged) and os.path.getsize(merged) > 1024,
        )

        all_srt = os.path.join(outdir, "all.srt")
        report("batch --srt produces a combined srt", os.path.exists(all_srt))

        if parts and os.path.exists(merged):
            d_parts = sum(tts._mp3_duration(p) for p in parts)
            d_merged = tts._mp3_duration(merged)
            # With ffmpeg the gap is real silence; without it the merge falls
            # back to raw MP3 frame concatenation, which cannot insert silence.
            has_ffmpeg = shutil.which("ffmpeg") is not None
            expected = d_parts + gap if has_ffmpeg else d_parts
            report(
                "merge duration matches %s" % ("ffmpeg path" if has_ffmpeg else "concat fallback"),
                abs(d_merged - expected) < 0.4,
                "实际 %.2fs / 预期 %.2fs%s" % (d_merged, expected, "" if has_ffmpeg else "（无 ffmpeg）"),
            )

            combined = srt_cues(all_srt)
            last_end = combined[-1][1] if combined else 0.0
            report(
                "combined srt stays aligned with merged audio",
                combined and 0 < last_end <= d_merged and (d_merged - last_end) < 2.5,
                "末条字幕 %.2fs / 音频 %.2fs" % (last_end, d_merged),
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 52)
    if FAILURES:
        print("%d 项失败：" % len(FAILURES))
        for name in FAILURES:
            print("  - %s" % name)
        return 1
    print("全部通过 —— 语音服务正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
