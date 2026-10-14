# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
