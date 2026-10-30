# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-10-21

### Added

- **`azure` backend** — the official Azure AI Speech REST API. Unlike the free
  `edge` backend this is a documented, supported service: it needs a subscription
  key and a region, and in return exposes the full prebuilt neural catalogue,
  including 48 kHz high-fidelity models. Configure with `--azure-key` /
  `AZURE_SPEECH_KEY`, `--azure-region` / `AZURE_SPEECH_REGION`, and an optional
  `--azure-endpoint` override for Azure China. The `--style` aliases are identical
  to `edge`'s, because the ShortNames are the same.
- `tests/mock_azure.py` — a local Azure-shaped server, so the SSML request,
  subscription-key auth and error propagation are covered without a real key.
- The smoke test gained six Azure checks (27 in total).

### Changed

- `--volume` / `--pitch` now also work on the `azure` backend (through SSML
  `<prosody>`), not just `edge`.

### Notes

- `azure` does not support `--srt`: the REST surface returns audio only, and word
  timings would require the Speech SDK.
- Only **public prebuilt** voices are reachable; a Custom Neural Voice trained by
  another account cannot be called.

## [1.1.1] - 2026-10-15

### Fixed

- **CI failed on every platform because the runners ship no `ffmpeg`.** The
  system-native backend needs ffmpeg to convert the engine's WAV/AIFF output to
  mp3, so `system: synthesizes offline` produced a 0-byte file and the hard gate
  failed — on Ubuntu, macOS and Windows alike. The smoke test now **skips** that
  one check when ffmpeg is absent (a missing optional dependency is not a code
  defect), and CI installs ffmpeg on Linux so at least one job still exercises the
  path end to end.
- The smoke test's live checks (real Edge synthesis, `voices --lang zh`, `doctor`,
  Edge batch/merge) are now advisory under `TTS_SMOKE_REQUIRE_LIVE=0`, which CI
  sets: the undocumented endpoint is occasionally throttled, and a real outage is
  the daily `health.yml` probe's job. Locally they stay mandatory.
- Updated the Testing-and-CI sections of both READMEs to document the two tiers and
  the ffmpeg skip.

## [1.1.0] - 2026-10-14

### Added

- **Pluggable backend layer.** `--provider` (or `$TTS_PROVIDER`) selects the speech
  engine; `edge` remains the default, so existing usage is unaffected.
- **`openai` backend** — any OpenAI-compatible `POST /v1/audio/speech` endpoint.
  One adapter covers OpenAI itself, LocalAI, Fish Speech, Kokoro-FastAPI,
  GPT-SoVITS wrappers and cloud vendors; point `--base-url` at your service.
  Credentials come from `--api-key` / `--base-url` / `--model` or the
  `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `TTS_MODEL` environment variables and are
  never written to disk.
- **`system` backend** — Windows SAPI, macOS `say`, Linux espeak-ng. No key,
  fully offline. Requires ffmpeg, since all three engines emit WAV/AIFF.
- **`providers` command** — lists every backend and whether it is usable.
- **`tests/mock_openai.py`** — a local OpenAI-compatible server, so the HTTP
  plumbing, error propagation and `--srt` refusal are covered by CI without
  needing a real API key.

### Changed

- `--srt` is now refused with an explicit message on backends that report no word
  timings, instead of producing a subtitle file with invented timings.
- Automatic `edge-tts` installation now happens only when the `edge` backend is
  actually used, so `--provider system` never pulls a network dependency.
- `doctor` reports every backend's status, not just Edge's.
- All backends normalise their output to 24 kHz mono 48 kbps mp3, which keeps
  `batch --merge` and the combined-subtitle timeline arithmetic valid across
  providers.
- The smoke test grew from 11 to 21 checks; CI installs `espeak-ng` on Linux so
  the system backend is exercised there too.

## [1.0.0] - 2026-10-14

First public release.

### Added

- `say` — synthesize one block of text to mp3, with optional time-aligned `.srt` export.
- `batch` — synthesize many segments from a `.txt` (one per line) or `.json` input,
  with per-segment voice / rate / volume / pitch overrides.
- `voices` — list available voices, filterable by language.
- `styles` — list built-in Chinese voice aliases.
- `doctor` — environment self-check (Python version, `edge-tts`, `ffmpeg`, service reachability).
- `--merge` with `--gap` — merge segments into one mp3, inserting real silence between them.
- `--proxy` support for restricted networks.
- Combined `all.srt` output whose timeline matches the merged audio exactly.
- `TTS_NO_AUTO_INSTALL` environment variable to disable automatic dependency installation.
- `tests/smoke_test.py` — live end-to-end smoke test covering 11 checks across the CLI,
  real synthesis, subtitles, batch, and merge behaviour.
- GitHub Actions: `ci.yml` runs the smoke test on Ubuntu / Windows / macOS across
  Python 3.9, 3.12 and 3.13; `health.yml` probes the live endpoint daily and files a
  GitHub issue automatically when it breaks.

### Fixed

- Chinese CLI output raised `UnicodeEncodeError` when stdout was piped on Windows,
  because the console code page was used instead of UTF-8. stdout/stderr are now
  explicitly reconfigured to UTF-8.

### Notes

- Subtitles are derived from the engine's real word-boundary events, and the merged
  subtitle timeline advances by each segment's true audio duration — including the
  trailing silence the engine appends — so cues stay aligned with the audio.
- Depends on `edge-tts`, which uses an undocumented Microsoft Edge endpoint. See the
  disclaimer in [README.md](README.md).
