# tts-voiceover

An [Agent Skill](https://code.claude.com/docs/en/skills) that turns text into **mp3 voiceover with time-aligned SRT subtitles** — for AI agents that support the `SKILL.md` convention.

No API key. No signup. 300+ neural voices across 140+ locales.

[![CI](https://github.com/<your-username>/tts-voiceover/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-username>/tts-voiceover/actions/workflows/ci.yml)
[![Service health](https://github.com/<your-username>/tts-voiceover/actions/workflows/health.yml/badge.svg)](https://github.com/<your-username>/tts-voiceover/actions/workflows/health.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[中文说明](README.zh-CN.md)

---

## ⚠️ Disclaimer — read this first

This skill is built on [`edge-tts`](https://github.com/rany2/edge-tts), which talks to the **"Read Aloud" endpoint inside the Microsoft Edge browser**. That endpoint is:

- **not** a documented, public, or licensed Microsoft API;
- subject to change or shutdown **at any time, without notice**;
- not covered by any uptime or support commitment.

Consequences you should accept before using this:

- Synthesis may break one day and **no one can fix it** from this repo.
- Do **not** describe this as an official Microsoft capability.
- Do **not** treat "free forever" as a promise.
- For commercial or production use, evaluate the risk yourself, or switch to the
  official Azure Speech service.

This project is a convenience wrapper. It grants you no rights over Microsoft's service.

## What it does

| Command | Purpose |
|---|---|
| `say` | Synthesize one block of text into an mp3 (optionally with `.srt`) |
| `batch` | Synthesize many segments, optionally merging them and exporting one combined `.srt` |
| `voices` | List available voices, filterable by language |
| `styles` | List built-in Chinese voice aliases |
| `doctor` | Environment self-check for troubleshooting |

## Features

- **Free, no API key, no account.** Uses Microsoft Edge neural voices.
- **Time-aligned subtitles.** SRT cues come from the engine's real word-boundary events, not estimated — they stay in sync with the audio.
- **Batch with per-segment voices.** Give each line its own voice/rate for dialogue or multi-character scripts.
- **Merge with real pauses.** `--merge` inserts actual silence between segments and keeps the combined SRT on the same timeline.
- **Rate / volume / pitch control** via relative values (`+25%`, `-10Hz`).
- **~320 voices, ~140 locales.** Mandarin, Cantonese, Taiwanese, English, Japanese, Korean, and many more — plus multilingual voices that switch language mid-sentence.
- **Portable.** Pure Python + optional `ffmpeg`. Runs on Windows, macOS, and Linux.

## Install

Clone into the directory your agent scans for skills.

**WorkBuddy AI**

```bash
git clone https://github.com/<your-username>/tts-voiceover.git ~/.workbuddy-ai/skills/tts-voiceover
```

On Windows, that path is `%USERPROFILE%\.workbuddy-ai\skills\tts-voiceover`.

**Claude Code**

```bash
git clone https://github.com/<your-username>/tts-voiceover.git ~/.claude/skills/tts-voiceover
```

**Other agents** — clone into whatever skills directory your host uses. The only requirement is that the host reads `SKILL.md` frontmatter.

Restart the agent session afterwards so the new skill is picked up.

Then verify the environment:

```bash
python3 ~/.workbuddy-ai/skills/tts-voiceover/scripts/tts.py doctor
```

## Usage

The agent invokes the script for you — you normally just ask in natural language
("read this script in a lively female voice"). To call it directly:

```bash
cd ~/.workbuddy-ai/skills/tts-voiceover

# one-shot synthesis, with subtitles
python3 scripts/tts.py say --text "Welcome aboard." --voice en-US-AriaNeural --out intro.mp3 --srt

# from a file, at a chosen pace
python3 scripts/tts.py say --file script.txt --style 女声-温柔 --rate +10% --out narration.mp3

# batch: one segment per line
python3 scripts/tts.py batch --file lines.txt --outdir audio --srt --merge full.mp3

# explore
python3 scripts/tts.py voices --lang ja
python3 scripts/tts.py styles
```

### Batch input

A plain text file, one segment per line, **or** JSON for per-segment control:

```json
[
  { "text": "Opening line, steady male voice.", "style": "男声-沉稳" },
  { "text": "Replying line, faster.", "voice": "zh-CN-XiaoyiNeural", "rate": "+10%", "out": "reply" }
]
```

### Key options

| Option | Applies to | Meaning |
|---|---|---|
| `--voice` | `say`, `batch` | Voice `ShortName`, e.g. `zh-CN-YunxiNeural`. **Determines the language.** |
| `--style` | `say`, `batch` | Friendly alias, e.g. `女声-温柔`, `en-female`, `多语言-女声` |
| `--rate` / `--volume` / `--pitch` | `say`, `batch` | Relative values: `+25%`, `-10%`, `+20Hz` |
| `--srt` | `say`, `batch` | Also write `.srt` subtitles |
| `--merge` / `--gap` | `batch` | Merge into one mp3; seconds of silence between segments (default `0.3`) |
| `--proxy` | all | HTTP proxy, e.g. `http://127.0.0.1:7890` |

## Choosing a language and voice

**There is no separate "language" parameter — the voice you pick decides the language.**
`--lang` exists only on `voices`, to filter the list.

A voice name is `language-region-Name-Neural`:

```
zh-CN-XiaoxiaoNeural
└─┬─┘ └──┬───┘ └──┬─┘
  │      │        └── fixed suffix
  │      └── voice personality
  └── language + region  ← change this to change language
```

Two gotchas worth knowing:

1. **Mixed Chinese + English requires a multilingual voice** (`en-US-AvaMultilingualNeural`, `en-US-AndrewMultilingualNeural`, …). Feeding Chinese text to a single-language voice like `en-US-AriaNeural` returns **empty audio** — a service behavior, not a bug in this script.
2. **Chinese TTS default pace is ~2.9 chars/sec**, slower than typical voiceover pacing (3.5–4). Measure the duration and adjust `--rate` before committing to a cut. For reference, `zh-CN-XiaoyiNeural` on a 51-character passage: `+0%` → 13.29s, `+15%` → 11.21s, `+25%` → 10.32s, `+35%` → 9.55s.

See [`SKILL.md`](SKILL.md) for the full 14-voice Chinese table and language prefix list.

## Testing and CI

The test is a **live smoke test**, not a mocked unit suite. Because this project
depends on an undocumented endpoint, a mocked test would only prove that the mocks
match — it could never tell you the service changed. `tests/smoke_test.py` calls the
real service and checks 11 things end to end: the CLI surface, actual audio output,
word-aligned subtitles, batch mode, the merge/silence behaviour, and that the combined
subtitle timeline still matches the merged audio.

Run it yourself:

```bash
python tests/smoke_test.py
```

Two workflows back this up:

| Workflow | Trigger | What it does |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | push, PR, manual | Runs the smoke test on Ubuntu (Python 3.9 / 3.12 / 3.13), Windows, and macOS |
| [`health.yml`](.github/workflows/health.yml) | daily at 09:00 CST, manual | Probes the live endpoint; **opens a GitHub issue automatically** if it breaks, and closes it again once the service recovers |

The daily probe is the important one. Since the endpoint can vanish without warning,
this turns "a user reports it's broken" into "an issue was filed hours earlier".

## Requirements

- **Python 3.9+**
- **`edge-tts`** — required. Installed automatically on first run; to manage it yourself, run `pip install -r requirements.txt` and set `TTS_NO_AUTO_INSTALL=1`.
- **`ffmpeg`** — optional, only for `batch --merge`. Without it the merge falls back to raw MP3 frame concatenation.

## Troubleshooting

Start here:

```bash
python3 scripts/tts.py doctor
```

It reports your Python version, whether `edge-tts` is importable, whether `ffmpeg` is on `PATH`, and whether the speech service is reachable.

| Symptom | Cause / fix |
|---|---|
| `No audio was received` | Almost always a single-language voice reading a different language. Use a multilingual voice. |
| `edge-tts` won't install | Managed/offline environment. Install manually, or set `TTS_NO_AUTO_INSTALL=1`. |
| Empty `.srt` file | Only happens on `edge-tts` builds without word-boundary support; upgrade the package. |
| Service unreachable | Corporate network. Try `--proxy http://127.0.0.1:7890`. |
| Merge fails | `ffmpeg` missing — install it, or accept the frame-concatenation fallback. |

## License

[MIT](LICENSE). This covers the code in this repository only — it does **not** grant any rights to Microsoft's speech service.
