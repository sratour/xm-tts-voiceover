# xm-tts-voiceover

An [Agent Skill](https://code.claude.com/docs/en/skills) that turns text into **mp3 voiceover with time-aligned SRT subtitles** — for AI agents that support the `SKILL.md` convention.

Three pluggable backends: Microsoft Edge neural voices (default — free, no API key), any **OpenAI-compatible** `/v1/audio/speech` endpoint, or your **operating system's** own engine for fully offline use.

[![CI](https://github.com/sratour/xm-tts-voiceover/actions/workflows/ci.yml/badge.svg)](https://github.com/sratour/xm-tts-voiceover/actions/workflows/ci.yml)
[![Service health](https://github.com/sratour/xm-tts-voiceover/actions/workflows/health.yml/badge.svg)](https://github.com/sratour/xm-tts-voiceover/actions/workflows/health.yml)
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
| `styles` | List the active backend's voice aliases |
| `providers` | List every backend and whether it is usable |
| `doctor` | Environment self-check for troubleshooting |

## Backends

Pick one with `--provider`, or set `TTS_PROVIDER`. Default is `edge`.

| Backend | Cost | Key | Offline | Subtitles | Covers |
|---|---|---|---|---|---|
| `edge` *(default)* | Free | — | No | ✅ word-level | 300+ voices, 140+ locales |
| `openai` | Varies | Required | Varies | ❌ | OpenAI, LocalAI, Fish Speech, Kokoro-FastAPI, GPT-SoVITS, cloud vendors, … |
| `system` | Free | — | **Yes** | ❌ | Windows SAPI, macOS `say`, Linux espeak-ng |

```bash
python3 scripts/tts.py providers   # what's available on this machine?
```

### `edge` — the default

No key, no signup, and the only backend that reports word-level timings, which is
what makes precisely aligned subtitles possible. It is also the one with the
disclaimer above attached to it.

### `openai` — bring your own endpoint

`POST /v1/audio/speech` has become the de-facto interface for TTS services, so one
adapter covers a lot of ground. Point `--base-url` at your service and it works:

```bash
# OpenAI itself
export OPENAI_API_KEY=sk-...
python3 scripts/tts.py say --provider openai --voice nova --text "Hello" --out out.mp3

# A self-hosted server (e.g. Kokoro-FastAPI)
python3 scripts/tts.py say --provider openai \
  --base-url http://127.0.0.1:8880/v1 --api-key not-needed \
  --voice af_bella --text "Hello" --out out.mp3
```

| Flag | Environment | Default |
|---|---|---|
| `--api-key` | `OPENAI_API_KEY` / `TTS_API_KEY` | — (required) |
| `--base-url` | `OPENAI_BASE_URL` / `TTS_BASE_URL` | `https://api.openai.com/v1` |
| `--model` | `TTS_MODEL` | `tts-1` |

Keys are read from flags and environment only — never written to disk. Voice names
are server-specific: run `voices --provider openai` to see what yours advertises
(it queries `GET /audio/voices`, falling back to OpenAI's built-in list). The
`--style` aliases only make sense against OpenAI's own voice set.

### `system` — fully offline

```bash
python3 scripts/tts.py say --provider system --text "Fully offline." --out out.mp3
```

No key, no network, nothing leaves the machine. The trade-offs are real: quality
sits well below the neural options, and **ffmpeg is required** because all three
engines emit WAV/AIFF. `--rate` is mapped onto each engine's native unit
(approximately); `--volume` and `--pitch` are not supported.

### About subtitles

`--srt` is only available on backends that report word timings — currently just
`edge`. The others return a single opaque audio blob with no positional data, so
asking for subtitles there fails loudly rather than inventing a timeline that
would drift out of sync. Forced alignment (re-transcribing the audio with Whisper)
would be needed to do better, which is a different order of work.

## Features

- **Three backends, one CLI.** Free Edge voices by default; plug in your own
  endpoint or go fully offline without changing anything else.
- **Time-aligned subtitles** on the Edge backend. SRT cues come from the engine's
  real word-boundary events, not estimates.
- **Batch with per-segment voices.** Give each line its own voice/rate for dialogue
  or multi-character scripts.
- **Merge with real pauses.** `--merge` inserts actual silence between segments and
  keeps the combined SRT on the same timeline.
- **Rate / volume / pitch control** via relative values (`+25%`, `-10Hz`).
- **Portable.** Pure Python + optional `ffmpeg`. Windows, macOS, and Linux.

## Install

Clone into the directory your agent scans for skills.

**WorkBuddy AI**

```bash
git clone https://github.com/sratour/xm-tts-voiceover.git ~/.workbuddy-ai/skills/xm-tts-voiceover
```

On Windows, that path is `%USERPROFILE%\.workbuddy-ai\skills\xm-tts-voiceover`.

**Claude Code**

```bash
git clone https://github.com/sratour/xm-tts-voiceover.git ~/.claude/skills/xm-tts-voiceover
```

**Other agents** — clone into whatever skills directory your host uses. The only requirement is that the host reads `SKILL.md` frontmatter.

Restart the agent session afterwards so the new skill is picked up.

Then verify the environment:

```bash
python3 ~/.workbuddy-ai/skills/xm-tts-voiceover/scripts/tts.py doctor
```

## Usage

The agent invokes the script for you — you normally just ask in natural language
("read this script in a lively female voice"). To call it directly:

```bash
cd ~/.workbuddy-ai/skills/xm-tts-voiceover

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

## Choosing a language and voice (Edge backend)

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

The other backends name their voices differently (`nova` on OpenAI, OS-specific
names on `system`). Run `voices --provider <name>` to see what is available.

Two gotchas worth knowing:

1. **Mixed Chinese + English requires a multilingual voice** (`en-US-AvaMultilingualNeural`, `en-US-AndrewMultilingualNeural`, …). Feeding Chinese text to a single-language voice like `en-US-AriaNeural` returns **empty audio** — a service behavior, not a bug in this script.
2. **Chinese TTS default pace is ~2.9 chars/sec**, slower than typical voiceover pacing (3.5–4). Measure the duration and adjust `--rate` before committing to a cut. For reference, `zh-CN-XiaoyiNeural` on a 51-character passage: `+0%` → 13.29s, `+15%` → 11.21s, `+25%` → 10.32s, `+35%` → 9.55s.

See [`SKILL.md`](SKILL.md) for the full 14-voice Chinese table and language prefix list.

## Testing and CI

The test is a **live smoke test**, not a mocked unit suite. Because the default
backend depends on an undocumented endpoint, a mocked test would only prove that
the mocks match — it could never tell you the service changed. `tests/smoke_test.py`
runs 21 checks end to end:

- the CLI surface and the backend registry
- **real synthesis** through the Edge backend, plus word-aligned subtitles
- batch mode, merge with silence, and combined-SRT alignment
- the **OpenAI-compatible backend against a local mock server** (`tests/mock_openai.py`),
  so the HTTP plumbing, error propagation, and the `--srt` refusal are covered
  without needing a real API key
- the **OS-native backend** for real on whichever platform the test runs on

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
- **`edge-tts`** — only for the `edge` backend. Installed automatically the first
  time that backend runs; to manage it yourself, run `pip install -r requirements.txt`
  and set `TTS_NO_AUTO_INSTALL=1`. Using another backend never installs it.
- **`ffmpeg`** — optional, but needed for `batch --merge` (to insert real silence)
  and for the `system` backend (to convert WAV/AIFF to mp3). Without it, merge falls
  back to raw MP3 frame concatenation.
- The `openai` backend needs nothing beyond the standard library.

## Troubleshooting

Start here:

```bash
python3 scripts/tts.py doctor      # full environment check
python3 scripts/tts.py providers   # just the backend status
```

| Symptom | Cause / fix |
|---|---|
| `No audio was received` (edge) | Almost always a single-language voice reading a different language. Use a multilingual voice. |
| `--srt` refused | That backend reports no word timings. Use `--provider edge`, or drop `--srt`. |
| `openai` says no API key | Set `OPENAI_API_KEY`, or pass `--api-key`. Self-hosted servers still usually require *some* value. |
| `openai` returns HTTP 400 | The server rejected a field. Check `--voice` and `--model` against `voices --provider openai`. |
| `system` backend unavailable on Linux | `apt install espeak-ng`. |
| `system` backend needs ffmpeg | Install ffmpeg — the OS engines cannot write mp3 directly. |
| `edge-tts` won't install | Managed/offline environment. Install manually, set `TTS_NO_AUTO_INSTALL=1`, or switch to `--provider system`. |
| Empty `.srt` file | Only on `edge-tts` builds without word-boundary support; upgrade the package. |
| Service unreachable | Corporate network. Try `--proxy http://127.0.0.1:7890` (edge only). |
| Merge fails | `ffmpeg` missing — install it, or accept the frame-concatenation fallback. |

## License

[MIT](LICENSE). This covers the code in this repository only — it does **not** grant any rights to Microsoft's speech service.
