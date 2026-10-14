# tts-voiceover · 配音 TTS

一个 [Agent Skill](https://code.claude.com/docs/en/skills)：把文字合成为 **mp3 配音**，并自动导出**与音频精确对齐的 SRT 字幕**。

免 API Key、免注册。300+ 神经语音，覆盖 140+ 语言/地区。

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
| `styles` | 列出内置中文音色别名 |
| `doctor` | 环境自检，排查装不上的问题 |

## 特性

- **免费、无需 Key、无需账号**，使用微软 Edge 神经语音。
- **字幕与音频精确对齐**：SRT 时间轴取自引擎真实的词边界事件，不是估算出来的。
- **批量 + 逐段指定音色**：有声书对话、多角色脚本可以每句换一个声音。
- **合并带真实停顿**：`--merge` 会在段间插入真正的静音，合并字幕与音频保持同一时间轴。
- **语速 / 音量 / 音调可调**，用相对值（`+25%`、`-10Hz`）。
- **约 320 个音色、140 种语言/地区**：普通话、粤语、台湾、英语、日语、韩语……还有能在一句话里切换语言的多语言音色。
- **跨平台**：纯 Python + 可选 `ffmpeg`，Windows / macOS / Linux 均可运行。

## 安装

克隆到你的 agent 扫描 skill 的目录。

**WorkBuddy AI**

```bash
git clone https://github.com/<your-username>/tts-voiceover.git ~/.workbuddy-ai/skills/tts-voiceover
```

Windows 下对应路径为 `%USERPROFILE%\.workbuddy-ai\skills\tts-voiceover`。

**Claude Code**

```bash
git clone https://github.com/<your-username>/tts-voiceover.git ~/.claude/skills/tts-voiceover
```

**其他 agent** —— 克隆到你所用宿主读取 skill 的目录即可，唯一要求是宿主能解析 `SKILL.md` 的 frontmatter。

装好后**重启一次会话**，新 skill 才会被加载。然后自检环境：

```bash
python3 ~/.workbuddy-ai/skills/tts-voiceover/scripts/tts.py doctor
```

## 用法

正常情况下你不需要敲命令 —— 直接用自然语言跟 agent 说就行（比如「用活泼女声读这段口播」）。想直接调用：

```bash
cd ~/.workbuddy-ai/skills/tts-voiceover

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
| `--voice` | `say`、`batch` | 音色 `ShortName`，如 `zh-CN-YunxiNeural`。**它决定了语言。** |
| `--style` | `say`、`batch` | 友好别名，如 `女声-温柔`、`en-female`、`多语言-女声` |
| `--rate` / `--volume` / `--pitch` | `say`、`batch` | 相对值：`+25%`、`-10%`、`+20Hz` |
| `--srt` | `say`、`batch` | 同时导出 `.srt` 字幕 |
| `--merge` / `--gap` | `batch` | 合并为一个 mp3；段间静音秒数（默认 `0.3`） |
| `--proxy` | 全部 | HTTP 代理，如 `http://127.0.0.1:7890` |

## 怎么选语言和声音

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

## 依赖

- **Python 3.8+**
- **`edge-tts`** —— 必需。首次运行自动安装；想自己管理依赖就执行 `pip install -r requirements.txt` 并设置 `TTS_NO_AUTO_INSTALL=1`。
- **`ffmpeg`** —— 可选，仅 `batch --merge` 需要。缺失时退化为 MP3 帧拼接。

## 故障排查

先跑自检：

```bash
python3 scripts/tts.py doctor
```

它会报告 Python 版本、`edge-tts` 是否可导入、`ffmpeg` 是否在 `PATH` 中、语音服务是否可达。

| 现象 | 原因 / 处理 |
|---|---|
| `No audio was received` | 几乎都是单语音色去读另一种语言。改用多语言音色。 |
| `edge-tts` 装不上 | 受管或离线环境。手动安装，或设 `TTS_NO_AUTO_INSTALL=1`。 |
| `.srt` 是空文件 | 仅出现在不支持词边界的旧版 `edge-tts`，升级即可。 |
| 服务不可达 | 企业网络。试 `--proxy http://127.0.0.1:7890`。 |
| 合并失败 | 缺 `ffmpeg`，装上，或接受帧拼接的降级方案。 |

## 许可证

[MIT](LICENSE)。仅覆盖本仓库代码 —— **不授予**你对微软语音服务的任何权利。
