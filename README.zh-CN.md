# xm-tts-voiceover · 配音 TTS

一个 [Agent Skill](https://code.claude.com/docs/en/skills)：把文字合成为 **mp3 配音**，并自动导出**与音频精确对齐的 SRT 字幕**。

**四种后端，`--provider` 切换**：微软 Edge 神经语音（默认，免费、无需 Key）、**Azure 官方语音**（需 Key，公开神经音色最全）、任意 **OpenAI 兼容**接口、或**操作系统自带**引擎（完全离线）。

[![CI](https://github.com/sratour/xm-tts-voiceover/actions/workflows/ci.yml/badge.svg)](https://github.com/sratour/xm-tts-voiceover/actions/workflows/ci.yml)
[![服务健康](https://github.com/sratour/xm-tts-voiceover/actions/workflows/health.yml/badge.svg)](https://github.com/sratour/xm-tts-voiceover/actions/workflows/health.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md)

---

## ⚠️ 请先读这段免责声明

本 skill 基于 [`edge-tts`](https://github.com/rany2/edge-tts)，它调用的是**微软 Edge 浏览器内置「大声朗读」的接口**。这个接口：

- **不是**微软公开文档化、也未经过微软授权；
- 可能被**随时变更或停用，且不会提前通知**；
- 没有任何可用性或支持承诺。

使用前请接受以下事实：

- 它某天可能失效，而且**本仓库无法修复**。
- **不要**对外宣称这是微软的官方能力。
- **不要**把「永久免费」当作承诺。
- 商业或生产环境请自行评估风险，或改用 Azure 官方语音服务。

本项目只是对第三方服务的封装，不授予你对微软服务的任何权利。

## 能做什么

| 命令 | 用途 |
|---|---|
| `say` | 把一段文本合成为 mp3（可选同时导出 `.srt`） |
| `batch` | 批量合成多段，可合并为一个文件并导出合并字幕 |
| `voices` | 列出可用音色，可按语言过滤 |
| `styles` | 列出当前后端的音色预设别名 |
| `providers` | 列出所有后端及其可用状态 |
| `doctor` | 环境自检，排查装不上的问题 |

## 后端

用 `--provider` 指定，或设置环境变量 `TTS_PROVIDER`。默认 `edge`。

| 后端 | 费用 | 要 Key | 离线 | 字幕 | 覆盖范围 |
|---|---|---|---|---|---|
| `edge`（默认） | 免费 | ❌ | ❌ | ✅ 词级 | 300+ 音色，140+ 语言/地区 |
| `edge` *（默认）* | 免费 | ❌ | ❌ | ✅ 词级 | 300+ 音色、140+ 语言/地区 |
| `azure` | 有免费额度，超出计费 | ✅ | ❌ | ❌ | 微软官方神经音色全量，含 48kHz 高保真 |
| `openai` | 视服务而定 | ✅ | 视服务而定 | ❌ | OpenAI、LocalAI、Fish Speech、Kokoro-FastAPI、GPT-SoVITS、云厂商…… |
| `system` | 免费 | ❌ | **✅** | ❌ | Windows SAPI、macOS `say`、Linux espeak-ng |

```bash
python3 scripts/tts.py providers   # 看这台机器上有哪些能用
```

### `edge` —— 默认后端

无需 Key、无需注册，而且是唯一提供**词级时间戳**的后端 —— 精确对齐的字幕靠它实现。
它也是上面那条免责声明所针对的后端。

### `azure` —— 微软官方语音（需 Key）

和 `edge` 是同一套神经音色，但走**官方文档化 API**：稳定、可商用，代价是要 Key 和区域，
超出免费额度按字符计费（标准神经语音前 12 个月每月 50 万字符免费）。

```bash
export AZURE_SPEECH_KEY=你的Key
export AZURE_SPEECH_REGION=eastasia

python3 scripts/tts.py say --provider azure --voice zh-CN-XiaoxiaoNeural \
  --text "你好" --out out.mp3
python3 scripts/tts.py voices --provider azure --lang zh
```

| 参数 | 环境变量 | 说明 |
|---|---|---|
| `--azure-key` | `AZURE_SPEECH_KEY`（也认 `--api-key` / `TTS_API_KEY`） | 必填 |
| `--azure-region` | `AZURE_SPEECH_REGION` | 必填，如 `eastasia` |
| `--azure-endpoint` | `AZURE_SPEECH_ENDPOINT` | 可选完整端点覆盖；**Azure 中国区**填 `https://<region>.tts.speech.azure.cn` |

音色用 ShortName（`zh-CN-XiaoxiaoNeural` 这类），`--style` 预设别名与 `edge` 完全一致。
输出 24kHz/48kbps mp3，`batch --merge` 可与其他后端混用。**不支持 `--srt`**（REST 只回整段音频）。
只对**公开预置音色**有效——别人训练的 Custom Neural Voice 调不到。

### `openai` —— 接入你自己的服务

`POST /v1/audio/speech` 已经成为 TTS 服务的事实标准接口，所以一个适配器能覆盖一大片。
把 `--base-url` 指向你的服务即可：

```bash
# OpenAI 官方
export OPENAI_API_KEY=sk-...
python3 scripts/tts.py say --provider openai --voice nova --text "Hello" --out out.mp3

# 自建服务（例如 Kokoro-FastAPI）
python3 scripts/tts.py say --provider openai \
  --base-url http://127.0.0.1:8880/v1 --api-key not-needed \
  --voice af_bella --text "Hello" --out out.mp3
```

| 参数 | 环境变量 | 默认值 |
|---|---|---|
| `--api-key` | `OPENAI_API_KEY` / `TTS_API_KEY` | 无（必填） |
| `--base-url` | `OPENAI_BASE_URL` / `TTS_BASE_URL` | `https://api.openai.com/v1` |
| `--model` | `TTS_MODEL` | `tts-1` |

密钥只从参数和环境变量读取，**绝不落盘**。音色名随服务端而异：跑
`voices --provider openai` 看你的服务提供什么（会查 `GET /audio/voices`，
查不到则回退到 OpenAI 官方内置列表）。`--style` 预设只对 OpenAI 官方音色有效。

### `system` —— 完全离线

```bash
python3 scripts/tts.py say --provider system --text "完全离线合成。" --out out.mp3
```

无需 Key、不联网、文件不出本机。代价是真实的：音质明显不如神经语音，
而且**必须有 ffmpeg**，因为三个系统的引擎都只输出 WAV/AIFF。
`--rate` 会换算成各引擎的原生单位（近似映射），`--volume` / `--pitch` 不支持。

### 关于字幕

`--srt` 只在提供词级时间戳的后端上可用 —— 目前只有 `edge`。其他后端返回的是一整块
音频，没有任何位置信息，所以在这里要字幕会**明确报错**，而不是编一条会漂移的时间轴出来。
要做得更好需要强制对齐（用 Whisper 重新识别音频），那是另一个量级的工作。

## 特性

- **四种后端，一套命令。** 默认免费 Edge 语音；想要官方 API 用 Azure，换自己的接口或彻底离线，其他用法都不用改。
- **字幕与音频精确对齐**（edge 后端）：SRT 时间轴取自引擎真实的词边界事件，不是估算。
- **批量 + 逐段指定音色**：有声书对话、多角色脚本可以每句换一个声音。
- **合并带真实停顿**：`--merge` 会在段间插入真正的静音，合并字幕与音频保持同一时间轴。
- **语速 / 音量 / 音调可调**，用相对值（`+25%`、`-10Hz`）。
- **跨平台**：纯 Python + 可选 `ffmpeg`，Windows / macOS / Linux 均可运行。

## 安装

克隆到你的 agent 扫描 skill 的目录。

**WorkBuddy AI**

```bash
git clone https://github.com/sratour/xm-tts-voiceover.git ~/.workbuddy-ai/skills/xm-tts-voiceover
```

Windows 下对应路径为 `%USERPROFILE%\.workbuddy-ai\skills\xm-tts-voiceover`。

**Claude Code**

```bash
git clone https://github.com/sratour/xm-tts-voiceover.git ~/.claude/skills/xm-tts-voiceover
```

**其他 agent** —— 克隆到你所用宿主读取 skill 的目录即可，唯一要求是宿主能解析 `SKILL.md` 的 frontmatter。

装好后**重启一次会话**，新 skill 才会被加载。然后自检环境：

```bash
python3 ~/.workbuddy-ai/skills/xm-tts-voiceover/scripts/tts.py doctor
```

## 用法

正常情况下你不需要敲命令 —— 直接用自然语言跟 agent 说就行（比如「用活泼女声读这段口播」）。想直接调用：

```bash
cd ~/.workbuddy-ai/skills/xm-tts-voiceover

# 单段合成 + 字幕
python3 scripts/tts.py say --text "欢迎收听。" --voice zh-CN-XiaoxiaoNeural --out intro.mp3 --srt

# 从文件读，指定语速
python3 scripts/tts.py say --file script.txt --style 女声-温柔 --rate +10% --out narration.mp3

# 批量：每行一段
python3 scripts/tts.py batch --file lines.txt --outdir audio --srt --merge full.mp3

# 查询
python3 scripts/tts.py voices --lang ja
python3 scripts/tts.py styles
```

### 批量输入格式

纯文本，一行一段；或用 JSON 逐段控制：

```json
[
  { "text": "开场白，男声沉稳。", "style": "男声-沉稳" },
  { "text": "接话，语速快一点。", "voice": "zh-CN-XiaoyiNeural", "rate": "+10%", "out": "reply" }
]
```

### 主要参数

| 参数 | 适用 | 含义 |
|---|---|---|
| `--provider` | 全部 | 后端：`edge` / `azure` / `openai` / `system`（默认 `edge`，也可用 `TTS_PROVIDER`） |
| `--voice` | `say`、`batch` | 音色名，如 `zh-CN-YunxiNeural` / `nova`。**它决定了语言。** |
| `--style` | `say`、`batch` | 友好别名，如 `女声-温柔`、`en-female` |
| `--rate` / `--volume` / `--pitch` | `say`、`batch` | 相对值：`+25%`、`-10%`、`+20Hz`（音量/音调仅 edge 支持） |
| `--api-key` / `--base-url` / `--model` | openai 后端 | 接口凭据与地址，也可走环境变量 |
| `--azure-key` / `--azure-region` / `--azure-endpoint` | azure 后端 | 微软语音 Key、区域、可选端点，也可走 `AZURE_SPEECH_*` |
| `--srt` | `say`、`batch` | 同时导出 `.srt` 字幕（仅 edge 等支持词级时间戳的后端） |
| `--merge` / `--gap` | `batch` | 合并为一个 mp3；段间静音秒数（默认 `0.3`） |
| `--proxy` | edge | HTTP 代理，如 `http://127.0.0.1:7890` |

## 怎么选语言和声音（以 edge 后端为例）

**没有单独的「语言」参数 —— 选哪个音色就用哪种语言。** `--lang` 只存在于 `voices` 上，用来过滤列表。

音色名格式是 `语言-地区-名字-Neural`：

```
zh-CN-XiaoxiaoNeural
└─┬─┘ └──┬───┘ └──┬─┘
  │      │        └── 固定后缀
  │      └── 音色个性
  └── 语言 + 地区   ← 改这里就换了语言
```

两个容易踩的坑：

1. **中英混读必须用多语言音色**（`en-US-AvaMultilingualNeural`、`en-US-AndrewMultilingualNeural` 等）。用 `en-US-AriaNeural` 这类单语音色读中文会返回**空音频** —— 这是服务端行为，不是脚本的 bug。
2. **中文 TTS 默认语速约 2.9 字/秒**，比常见口播节奏（3.5–4 字/秒）慢。定剪之前先测时长再调 `--rate`。参考数据，`zh-CN-XiaoyiNeural` 读 51 字：`+0%` → 13.29s，`+15%` → 11.21s，`+25%` → 10.32s，`+35%` → 9.55s。

完整的中文音色表（14 个）和语言前缀表见 [`SKILL.md`](SKILL.md)。

## 测试与 CI

这里的测试是**真实联网冒烟测试**，不是打桩的单元测试。因为默认后端依赖一个非官方接口，
打桩测试只能证明「桩写得对」，永远发现不了服务本身变了。`tests/smoke_test.py` 跑 27 项断言：

- CLI 各命令与后端注册表
- **真实合成**（edge 后端）+ 词级对齐字幕
- 批量模式、带停顿的合并、合并字幕对齐
- **OpenAI 兼容后端对本地 mock 服务**（`tests/mock_openai.py`）—— HTTP 链路、
  错误透传、`--srt` 拒绝都覆盖到了，**不需要真实 API Key**
- **Azure 后端对本地 mock 服务**（`tests/mock_azure.py`）—— SSML 请求、
  订阅 Key 鉴权、错误透传，**不需要真实 Azure Key**
- **系统自带后端**在测试运行的平台上真实执行

自己跑：

```bash
python tests/smoke_test.py
```

检查分两档。**离线**检查——CLI 各命令、后端注册表、对本地 mock 的 OpenAI 后端、系统自带后端——是硬门槛，任何一项挂了整个测试就挂。**联网**检查——edge 真实合成、`voices --lang zh`、`doctor`、以及走 edge 后端的批量/合并——会真的去打微软的线上接口。它们默认也是必过的，但如果你设 `TTS_SMOKE_REQUIRE_LIVE=0`，联网失败会降级成 `[warn]`，测试仍然以 0 退出。`ci.yml` 设了这个开关：非官方接口偶尔会限流，线上抖一下不算代码缺陷；真正的线上故障由每天跑的 `health.yml` 探针捕获——它会针对线上服务本身开 issue。

系统自带后端还多一个前提：**ffmpeg**。三种系统引擎都输出 WAV/AIFF，后端要靠 ffmpeg 转成 mp3。**没有 ffmpeg 时，冒烟测试会跳过 `system: synthesizes offline` 这一项，而不是判失败**——缺一个可选依赖不算 bug。CI 在 Linux 上装了 ffmpeg，所以至少有一个 job 会端到端跑通这条路径；macOS 和 Windows 的 runner 则跳过。

配套两个 workflow：

| Workflow | 触发 | 作用 |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | push、PR、手动 | 在 Ubuntu（Python 3.9 / 3.12 / 3.13）、Windows、macOS 上跑冒烟测试 |
| [`health.yml`](.github/workflows/health.yml) | 每天 09:00（北京时间）、手动 | 探测线上接口，挂了就**自动开 GitHub Issue**，恢复了自动关闭 |

每日探针是更关键的那个。接口随时可能消失，它把「用户来报障」变成「几小时前已经自动建单」。

## 依赖

- **Python 3.9+**
- **`edge-tts`** —— 仅 `edge` 后端需要。首次使用该后端时自动安装；想自己管理依赖就执行
  `pip install -r requirements.txt` 并设置 `TTS_NO_AUTO_INSTALL=1`。
  **用其他后端不会安装它。**
- **`ffmpeg`** —— 可选，但 `batch --merge`（插入真实停顿）和 `system` 后端（WAV/AIFF 转 mp3）
  需要它。缺失时合并会退化为 MP3 帧拼接。
- `openai` 与 `azure` 后端除标准库外**零依赖**；`azure` 额外需要 Speech 的 Key 和区域。

## 故障排查

先跑自检：

```bash
python3 scripts/tts.py doctor      # 完整环境检查
python3 scripts/tts.py providers   # 只看后端状态
```

| 现象 | 原因 / 处理 |
|---|---|
| `No audio was received`（edge） | 几乎都是单语音色去读另一种语言。改用多语言音色。 |
| `--srt` 被拒绝 | 该后端不提供词级时间戳。改用 `--provider edge`，或去掉 `--srt`。 |
| openai 提示没有 Key | 设置 `OPENAI_API_KEY`，或传 `--api-key`。自建服务通常也要随便填一个值。 |
| openai 返回 HTTP 400 | 服务端拒绝了某个字段。用 `voices --provider openai` 核对 `--voice` 和 `--model`。 |
| azure 提示没有 Key / 区域 | 设置 `AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION`，或传 `--azure-key` / `--azure-region`。 |
| azure 返回 HTTP 401 | Key 无效，或区域与资源不匹配。 |
| azure 返回 HTTP 429 | 超出配额或速率限制，检查 Speech 资源的定价层。 |
| Linux 上 system 后端不可用 | `apt install espeak-ng`。 |
| system 后端提示需要 ffmpeg | 装 ffmpeg —— 系统引擎无法直接输出 mp3。 |
| `edge-tts` 装不上 | 受管或离线环境。手动安装、设 `TTS_NO_AUTO_INSTALL=1`，或改用 `--provider system`。 |
| `.srt` 是空文件 | 仅出现在不支持词边界的旧版 `edge-tts`，升级即可。 |
| 服务不可达 | 企业网络。试 `--proxy http://127.0.0.1:7890`（仅 edge）。 |
| 合并失败 | 缺 `ffmpeg`，装上，或接受帧拼接的降级方案。 |

## 许可证

[MIT](LICENSE)。仅覆盖本仓库代码 —— **不授予**你对微软语音服务的任何权利。
