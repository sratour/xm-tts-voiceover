---
name: xm-tts-voiceover
description: "配音 TTS - 把文字合成为语音配音（mp3），并可自动生成同步字幕。当用户需要配音、语音合成、文字转语音、TTS、朗读、旁白、有声书、短视频配音、多音色批量配音、导出字幕时使用。支持三种后端：微软 Edge TTS（默认，免费、无需 Key、有词级时间戳）、任意 OpenAI 兼容接口（OpenAI / LocalAI / Fish Speech / Kokoro-FastAPI / 云厂商，用 --base-url 接入）、系统自带语音（Windows SAPI / macOS say / Linux espeak，完全离线）。可调语速/音量/音调。"
description_en: "Text-to-speech voiceover that turns text into mp3 narration and time-aligned SRT subtitles. Use for voiceover, TTS, narration, audiobooks, short-video dubbing, batch multi-voice synthesis, or subtitle export. Three pluggable backends: Microsoft Edge neural voices (default; free, no API key, word-level timings), any OpenAI-compatible /v1/audio/speech endpoint, or the OS-native engine for fully offline use."
version: 1.1.1
license: MIT
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - present_files
---

# 配音 TTS

把文字合成为配音音频，并可选导出与音频对齐的字幕。

**三种后端，用 `--provider` 切换：**

| 后端 | 特点 | 字幕 |
|---|---|---|
| `edge`（默认） | 微软 Edge 神经语音。免费、无需 Key、300+ 音色 | ✅ 词级精确 |
| `openai` | 任意 OpenAI 兼容 `/v1/audio/speech` 接口 | ❌ |
| `system` | 系统自带引擎（Windows SAPI / macOS `say` / Linux espeak-ng），完全离线 | ❌ |

> **只有 `edge` 能出字幕。** 另外两个后端只返回整段音频，没有词的位置信息 ——
> 这时传 `--srt` 会明确报错，而不是生成一份时间轴瞎猜的字幕。

## 运行方式

脚本在本 skill 目录下：

```
<SKILL_DIR>/scripts/tts.py
```

用当前环境的 `python` 或 `python3` 调用即可（需 Python 3.9+）：

```bash
python3 "<SKILL_DIR>/scripts/tts.py" <命令> [参数]
```

依赖：

- `edge-tts` —— 仅 `edge` 后端需要（首次使用该后端时自动安装）。
- `ffmpeg` —— 可选。`batch --merge` 需要它插入段间停顿；`system` 后端需要它把 WAV 转成 mp3。

若环境不允许自动装包，先手动 `pip install -r requirements.txt`；
或设置 `TTS_NO_AUTO_INSTALL=1`，脚本会明确报错而不是自动安装。

装完先自检：

```bash
python3 "<SKILL_DIR>/scripts/tts.py" doctor
```

## 命令一览

| 命令 | 用途 |
|---|---|
| `say` | 把一段文本合成为一个 mp3（最常用） |
| `batch` | 批量合成多段配音，可合并 + 导出总字幕 |
| `voices` | 列出可用音色（可按语言过滤） |
| `styles` | 列出当前后端的音色预设别名 |
| `providers` | 列出所有后端及其可用状态 |
| `doctor` | 环境自检，排查装不上的问题 |

## 0. 选后端（providers）

```bash
python3 tts.py providers          # 看每个后端是否可用
python3 tts.py doctor             # 更详细的环境自检
```

切换方式（优先级从高到低）：`--provider` 参数 → 环境变量 `TTS_PROVIDER` → 默认 `edge`。
别名也认：`oai` / `openai-compatible` → openai，`os` / `native` / `sapi` / `say` / `espeak` → system。

### openai：接入任意 OpenAI 兼容接口

一个适配器覆盖 OpenAI 官方、LocalAI、Fish Speech、Kokoro-FastAPI、GPT-SoVITS 封装、
硅基流动、DeepInfra 等。**填 `--base-url` 就能接自己的服务。**

```bash
# 官方 OpenAI
export OPENAI_API_KEY=sk-...
python3 tts.py say --provider openai --voice nova --text "Hello" --out out.mp3

# 自建服务（Kokoro-FastAPI 等）
python3 tts.py say --provider openai \
  --base-url http://127.0.0.1:8880/v1 --api-key not-needed \
  --voice af_bella --text "Hello" --out out.mp3
```

| 参数 | 环境变量 | 默认 |
|---|---|---|
| `--api-key` | `OPENAI_API_KEY` / `TTS_API_KEY` | 无（必填） |
| `--base-url` | `OPENAI_BASE_URL` / `TTS_BASE_URL` | `https://api.openai.com/v1` |
| `--model` | `TTS_MODEL` | `tts-1` |

密钥只从参数和环境变量读取，不落盘。音色名随服务端而异：先跑
`tts.py voices --provider openai` 看服务端提供哪些（会优先查 `GET /audio/voices`，
查不到则回退到 OpenAI 官方内置音色）。`--style` 预设只对 OpenAI 官方音色有效。

### system：完全离线

```bash
python3 tts.py say --provider system --text "完全离线合成。" --out out.mp3
python3 tts.py say --provider system --voice "Microsoft Huihui Desktop" --out out.mp3
```

零 Key、不联网、文件不出本机。代价是音质明显不如神经语音，且**需要 ffmpeg** 转 mp3
（三个系统的引擎都只输出 WAV/AIFF）。`--rate` 会换算成各引擎的原生单位，
映射是近似的；`--volume` / `--pitch` 不支持。

## 1. 单段配音（say）

```bash
# 指定中文音色
python tts.py say --text "大家好，欢迎收听今天的节目。" --voice zh-CN-XiaoxiaoNeural --out intro.mp3

# 用预设别名 + 调语速 + 同时导出字幕
python tts.py say --file script.txt --style 女声-温柔 --rate +10% --out narration.mp3 --srt

# 从 stdin 读文本
echo "这是一段测试" | python tts.py say --out test.mp3
```

参数：

- `--text` / `--file`：文本来源（二选一，都没有则读 stdin）
- `--out`：输出 mp3 路径，默认 `voiceover.mp3`
- `--srt`：额外导出同名 `.srt` 字幕（时间轴来自引擎的 WordBoundary 事件，与音频精确对齐）
- `--voice`：音色 ShortName，如 `zh-CN-YunxiNeural`（决定语言，见第 3 节）
- `--style`：音色预设别名，如 `女声-温柔`（见第 3 节）
- `--rate` / `--volume` / `--pitch`：`+20%` / `-10%` / `+20Hz` 这类相对值
- `--proxy`：需要代理时传入，如 `http://127.0.0.1:7890`

## 2. 批量配音（batch）

输入支持两种格式。

**按行分隔的 txt** —— 每个非空行是一段：

```bash
python tts.py batch --file lines.txt --outdir audio --srt --merge full.mp3
```

**JSON** —— 可对每段单独指定音色/语速：

```json
[
  { "text": "第一段旁白", "style": "男声-沉稳" },
  { "text": "第二段旁白", "voice": "zh-CN-XiaoyiNeural", "rate": "+15%", "out": "part2" }
]
```

```bash
python tts.py batch --file lines.json --outdir audio --srt --merge full.mp3
```

- 输出文件按顺序命名为 `001.mp3`、`002.mp3` …
- `--srt` 会为每段生成单独字幕，并额外输出合并后的 `all.srt`（时间轴已按顺序累加）
- `--merge` 把全部音频合并为一个 mp3（有 ffmpeg 时走 ffmpeg，否则做 MP3 帧拼接）

## 3. 怎么选语言 / 声音（以 edge 后端为例）

**核心规则：没有单独的「语言」参数，选音色就等于选语言。** 音色名自带语言信息，
`--lang` 只是 `voices` 命令用来过滤列表的，不能用在 `say` / `batch` 上。

> 其他后端的音色命名规则不同：`openai` 用 `nova` / `onyx` 这类名字，
> `system` 用操作系统的音色名（如 `Microsoft Huihui Desktop`）。
> 想确认有哪些，跑 `tts.py voices --provider <后端名>`。

音色名格式：`语言-地区-名字-类型`，例如 `zh-CN-XiaoxiaoNeural`

| 段 | 含义 | 例 |
|---|---|---|
| `zh-CN` | 语言-地区，决定用哪国语言朗读 | `en-US` / `ja-JP` / `ko-KR` |
| `Xiaoxiao` | 音色名，决定音色个性 | `Yunxi` / `Aria` |
| `Neural` | 固定后缀，表示神经网络音色 | 一律是 `Neural` |

**换语言 = 换第一段前缀。** 例如把 `zh-CN-YunxiNeural` 换成 `ja-JP-KeitaNeural` 就是日语男声。

### 三条选择路径

1. **用预设别名（最省事）**：`--style 女声-温柔`，中文场景基本够用。
2. **直接指定音色**：`--voice zh-CN-YunyangNeural`，想用没做预设的音色时用。
3. **先查再选**：`python tts.py voices --lang ja` 拿到 ShortName，再传给 `--voice`。

### 全部中文音色（14 个）

| ShortName | 性别 | 地区 | 预设别名 |
|---|---|---|---|
| zh-CN-XiaoxiaoNeural | 女 | 普通话 | 女声-温柔 |
| zh-CN-XiaoyiNeural | 女 | 普通话 | 女声-活泼 |
| zh-CN-YunxiNeural | 男 | 普通话 | 男声-沉稳 |
| zh-CN-YunyangNeural | 男 | 普通话 | 男声-新闻 |
| zh-CN-YunjianNeural | 男 | 普通话 | 男声-少年 |
| zh-CN-YunxiaNeural | 男 | 普通话 | — |
| zh-CN-liaoning-XiaobeiNeural | 女 | 辽宁 | 女声-东北 |
| zh-CN-shaanxi-XiaoniNeural | 女 | 陕西 | 女声-陕西 |
| zh-HK-HiuMaanNeural | 女 | 粤语 | 女声-粤语 |
| zh-HK-HiuGaaiNeural | 女 | 粤语 | — |
| zh-HK-WanLungNeural | 男 | 粤语 | 男声-粤语 |
| zh-TW-HsiaoChenNeural | 女 | 台湾 | 女声-台湾 |
| zh-TW-HsiaoYuNeural | 女 | 台湾 | — |
| zh-TW-YunJheNeural | 男 | 台湾 | — |

### 常用语言前缀

`zh-CN` 普通话 · `zh-HK` 粤语 · `zh-TW` 台湾 · `en-US` / `en-GB` 英语 ·
`ja-JP` 日语 · `ko-KR` 韩语 · `fr-FR` 法语 · `de-DE` 德语 · `es-ES` 西班牙语 ·
`ru-RU` 俄语 · `pt-BR` 葡语 · `it-IT` 意语 · `ar-SA` 阿拉伯语 · `th-TH` 泰语 · `vi-VN` 越南语

共 322 个音色、142 种语言/地区。完整列表：`python tts.py voices`（加 `--lang` 过滤）。

```bash
python tts.py styles             # 中文预设别名
python tts.py voices --lang zh   # 全部中文音色
python tts.py voices --lang ja   # 日语音色
python tts.py voices             # 全部 322 个
```

### 其他语种预设

| 别名 | 音色 |
|---|---|
| en-female | en-US-AriaNeural |
| en-male | en-US-GuyNeural |
| ja-female | ja-JP-NanamiNeural |
| ja-male | ja-JP-KeitaNeural |
| ko-female | ko-KR-SunHiNeural |
| 多语言-女声 | en-US-AvaMultilingualNeural |
| 多语言-女声2 | en-US-EmmaMultilingualNeural |
| 多语言-男声 | en-US-AndrewMultilingualNeural |
| 多语言-男声2 | en-US-BrianMultilingualNeural |

默认音色：`zh-CN-XiaoxiaoNeural`（女声-温柔）。

> **中英混读**必须用「多语言-*」系列：`en-US-AriaNeural` 这类**单语音色读中文会返回空音频**，
> 只有 Multilingual 音色能在一句话里中英自由切换。

> 选音色的建议：纪录片/旁白用「男声-沉稳」或「女声-温柔」；新闻播报用「男声-新闻」；带货/短视频用「女声-活泼」；有声书对话可 `batch` 分角色指定不同音色。

## 长文本

单次合成上限约 1 万字符。更长的内容请拆段后走 `batch`，既避免失败也便于后期剪辑。

## 完成后

合成结束后，用 `present_files` 把生成的 mp3（有字幕时连 `.srt` 一起）呈现给用户，并在回复中说明：
音色、语速、时长/段落数、输出目录的绝对路径。

## 依赖与非官方接口声明

- **`edge` 后端**：需要 `edge-tts`（首次使用该后端时自动安装，可用 `TTS_NO_AUTO_INSTALL=1` 关闭）。
  用其他后端不会安装它。
- **`system` 后端**：需要 ffmpeg（转 mp3），零 Python 依赖。
- **`openai` 后端**：零额外依赖（用标准库发请求），需要你自己的 Key 或自建服务。
- **`batch --merge`**：需要 ffmpeg 插入段间停顿；缺失时退化为 MP3 帧拼接。

> **`edge` 后端依赖的 `edge-tts` 走的是微软 Edge 浏览器「大声朗读」的内部接口，
> 并非微软公开文档化或授权的 API。** 该接口可能被随时变更或停用，导致合成失败；
> 请勿将其视为微软官方能力，也不要把「永久免费」当作承诺。
> 需要正式授权的场景请改用 `--provider openai` 接 Azure/OpenAI 官方服务，或自建。

## 注意

- 输出是标准 mp3，可直接导入剪映 / Premiere / 剪映专业版做视频配音。
- `--srt` 生成的字幕已按音频时间轴对齐，可直接拖进剪辑软件当字幕轨。
- 三个后端都输出 24 kHz 单声道 mp3，所以 `batch --merge` 与字幕时间轴算法跨后端通用。
- `edge` 后端需要能访问微软语音服务；若在企业网络下失败，先跑 `doctor` 自检，
  再尝试 `--proxy`。
