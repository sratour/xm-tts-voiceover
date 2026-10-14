# -*- coding: utf-8 -*-
"""OS-native speech backend: Windows SAPI, macOS `say`, Linux espeak-ng.

Zero API keys, fully offline -- nothing leaves the machine. The trade-offs are
real: voice quality sits well below the neural options, and none of these
engines expose word timings, so `--srt` is unavailable.

All three engines emit WAV/AIFF rather than mp3, so ffmpeg is required to produce
the format the rest of the pipeline expects. Output is normalised to 24 kHz mono
48 kbps mp3 to match what the Edge backend produces, which keeps `batch --merge`
and the combined-subtitle timeline arithmetic valid across providers.
"""

import os
import platform
import re
import shutil
import subprocess

from .base import Provider, ProviderError, parse_percent, require_ffmpeg

# Words per minute each engine treats as "normal", used to translate the CLI's
# relative percentage into that engine's native rate unit.
_SAY_BASE_WPM = 180
_ESPEAK_BASE_WPM = 175

_PS_SYNTH = (
    "$ErrorActionPreference='Stop';"
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "if($env:TTS_VOICE){$s.SelectVoice($env:TTS_VOICE)};"
    "$s.Rate=[int]$env:TTS_RATE;"
    "$s.SetOutputToWaveFile($env:TTS_WAV);"
    "$s.Speak([IO.File]::ReadAllText($env:TTS_TEXT,[Text.Encoding]::UTF8));"
    "$s.Dispose()"
)

_PS_VOICES = (
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.GetInstalledVoices()|ForEach-Object{"
    "$i=$_.VoiceInfo;"
    "Write-Output ($i.Name+'|'+$i.Gender+'|'+$i.Culture.Name)};"
    "$s.Dispose()"
)


class SystemProvider(Provider):
    name = "system"
    label = "系统自带语音（离线、零 Key、无字幕）"
    supports_srt = False
    needs_api_key = False
    needs_ffmpeg = True
    default_voice = None  # None -> let the OS pick its own default voice
    SETUP_HINT = "无需配置，但需要 ffmpeg 转 mp3"

    def __init__(self, options=None):
        super().__init__(options)
        self.os_name = platform.system()  # 'Windows' | 'Darwin' | 'Linux'
        self.espeak = None
        if self.os_name == "Linux":
            for exe in ("espeak-ng", "espeak"):
                if shutil.which(exe):
                    self.espeak = exe
                    break

    # -------------------------------------------------------------- capability
    def available(self):
        if self.os_name == "Windows":
            shell = shutil.which("powershell") or shutil.which("pwsh")
            if not shell:
                return False, "找不到 powershell"
            return True, "Windows SAPI"
        if self.os_name == "Darwin":
            if not shutil.which("say"):
                return False, "找不到 macOS 的 say 命令"
            return True, "macOS say"
        if self.espeak:
            return True, self.espeak
        return False, "找不到 espeak-ng（Debian/Ubuntu: apt install espeak-ng）"

    # -------------------------------------------------------------------- data
    def list_voices(self, lang=None):
        ok, reason = self.available()
        if not ok:
            raise ProviderError(reason)

        if self.os_name == "Windows":
            voices = self._win_voices()
        elif self.os_name == "Darwin":
            voices = self._darwin_voices()
        else:
            voices = self._linux_voices()

        key = (lang or "").strip().lower()
        if key:
            voices = [v for v in voices if key in (v["id"] + v["locale"]).lower()]
        return voices

    # --------------------------------------------------------------- synthesis
    def synthesize(self, text, voice, rate, volume, pitch, out_path):
        ok, reason = self.available()
        if not ok:
            raise ProviderError(reason)

        percent = parse_percent(rate)
        work = out_path + ".engine"

        if self.os_name == "Windows":
            self._win_speak(text, voice, percent, work + ".wav")
        elif self.os_name == "Darwin":
            self._darwin_speak(text, voice, percent, work + ".aiff")
        else:
            self._linux_speak(text, voice, percent, work + ".wav")

        try:
            self._to_mp3(work + (".aiff" if self.os_name == "Darwin" else ".wav"), out_path)
        finally:
            for candidate in (work + ".wav", work + ".aiff"):
                if os.path.exists(candidate):
                    os.remove(candidate)

        return []  # OS engines expose no word timings

    # ------------------------------------------------------------------ Windows
    def _win_speak(self, text, voice, percent, out_wav):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        text_file = out_wav + ".txt"
        with open(text_file, "w", encoding="utf-8") as fh:
            fh.write(text)

        env = os.environ.copy()
        # Parameters travel through the environment, not the command line, so
        # neither quotes nor the console code page can corrupt the text.
        env["TTS_TEXT"] = text_file
        env["TTS_WAV"] = out_wav
        env["TTS_VOICE"] = voice or ""
        env["TTS_RATE"] = str(_sapi_rate(percent))

        try:
            proc = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", _PS_SYNTH],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
            )
        finally:
            if os.path.exists(text_file):
                os.remove(text_file)

        if proc.returncode != 0:
            raise ProviderError("Windows SAPI 合成失败：%s" % _tail(proc.stderr or proc.stdout))
        if not os.path.exists(out_wav):
            raise ProviderError("Windows SAPI 没有生成音频文件")

    def _win_voices(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        proc = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", _PS_VOICES],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        voices = []
        for line in (proc.stdout or "").splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and parts[0]:
                voices.append({
                    "id": parts[0], "name": parts[0],
                    "gender": parts[1], "locale": parts[2],
                })
        return sorted(voices, key=lambda x: x["id"])

    # -------------------------------------------------------------------- macOS
    def _darwin_speak(self, text, voice, percent, out_aiff):
        text_file = out_aiff + ".txt"
        with open(text_file, "w", encoding="utf-8") as fh:
            fh.write(text)

        cmd = ["say", "-o", out_aiff, "-f", text_file]
        if voice:
            cmd += ["-v", voice]
        cmd += ["-r", str(max(80, int(round(_SAY_BASE_WPM * (1.0 + percent)))))]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
        finally:
            if os.path.exists(text_file):
                os.remove(text_file)

        if proc.returncode != 0:
            raise ProviderError("macOS say 合成失败：%s" % _tail(proc.stderr or proc.stdout))
        if not os.path.exists(out_aiff):
            raise ProviderError("macOS say 没有生成音频文件")

    def _darwin_voices(self):
        proc = subprocess.run(["say", "-v", "?"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        voices = []
        for line in (proc.stdout or "").splitlines():
            match = re.match(r"^(.+?)\s{2,}(\S+)\s+#\s*(.*)$", line)
            if not match:
                continue
            name, locale, note = match.group(1).strip(), match.group(2), match.group(3)
            gender = "Female" if "female" in note.lower() else (
                "Male" if "male" in note.lower() else "")
            voices.append({"id": name, "name": name, "gender": gender, "locale": locale})
        return sorted(voices, key=lambda x: x["id"])

    # -------------------------------------------------------------------- Linux
    def _linux_speak(self, text, voice, percent, out_wav):
        text_file = out_wav + ".txt"
        with open(text_file, "w", encoding="utf-8") as fh:
            fh.write(text)

        cmd = [self.espeak, "-w", out_wav, "-f", text_file]
        if voice:
            cmd += ["-v", voice]
        cmd += ["-s", str(max(80, int(round(_ESPEAK_BASE_WPM * (1.0 + percent)))))]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
        finally:
            if os.path.exists(text_file):
                os.remove(text_file)

        if proc.returncode != 0:
            raise ProviderError("espeak 合成失败：%s" % _tail(proc.stderr or proc.stdout))
        if not os.path.exists(out_wav):
            raise ProviderError("espeak 没有生成音频文件")

    def _linux_voices(self):
        """Best-effort parse of espeak's fixed-width `--voices` table.

        espeak-ng does not offer machine-readable output, so column offsets are
        used first and whitespace splitting is the fallback. If parsing fails the
        list is empty -- any voice name can still be passed straight to --voice.
        """
        proc = subprocess.run([self.espeak, "--voices"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        voices = []
        for line in (proc.stdout or "").splitlines()[1:]:
            if not line.strip():
                continue
            name = line[25:42].strip() if len(line) > 25 else ""
            locale = line[4:14].strip() if len(line) > 4 else ""
            gender = line[15:24].strip() if len(line) > 15 else ""
            if not name:
                parts = line.split()
                if len(parts) < 4:
                    continue
                locale, gender, name = parts[1], parts[2], parts[3]
            voices.append({"id": name, "name": name, "gender": gender, "locale": locale})
        return sorted(voices, key=lambda x: x["id"])

    # ------------------------------------------------------------------ convert
    def _to_mp3(self, src, out_path):
        ffmpeg = require_ffmpeg(self.label)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        proc = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
             "-ar", "24000", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k", out_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0 or not os.path.exists(out_path):
            raise ProviderError("ffmpeg 转 mp3 失败：%s" % _tail(proc.stderr))


def _sapi_rate(percent):
    """Map a relative percentage onto SAPI's integer -10..10 rate scale.

    The mapping is approximate: SAPI documents the range but not the exact
    speed multiplier per step.
    """
    return max(-10, min(10, int(round(percent * 10))))


def _tail(text, limit=300):
    text = " ".join((text or "").split())
    return text[-limit:] if len(text) > limit else text
