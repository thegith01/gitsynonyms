# 🎬 视频下载与中英字幕生成 / 刻录 / 部署流水线

本项目展示了一个完整的视频字幕处理流水线，支持从 YouTube 下载视频、提取自动生成的英文字幕、生成中文字幕、将字幕刻录到视频中，最后部署输出。

**目标视频**: [https://www.youtube.com/watch?v=9aPyO1jfDGM](https://www.youtube.com/watch?v=9aPyO1jfDGM)  
**视频时长**: 3小时16分11秒  
**字幕条数**: 6,281 条  
**支持语言**: 英文 (en) → 中文 (zh)

---

## 📁 项目结构

```
/workspace/
├── README.md                      # 本说明文档
├── bin/                           # 二进制工具
│   ├── ffmpeg                     # FFmpeg 音视频处理工具
│   └── ffprobe                    # FFprobe 媒体信息工具
├── scripts/                       # 处理脚本
│   ├── full_pipeline.sh           # 主流水线脚本（编排所有步骤）
│   ├── burn_subtitles.sh          # 字幕刻录脚本（ffmpeg 烧录字幕）
│   ├── deploy.sh                  # 部署脚本（打包输出并生成 manifest）
│   ├── subtitle_processor.py      # WebVTT → SRT 转换 + 中文字幕生成
│   ├── subtitle_converter.py      # WebVTT 转 SRT 转换工具
│   └── generate_chinese_subtitles.py  # 中文字幕生成（模拟翻译）
├── videos/                        # 输入视频与原始字幕
│   ├── *.en.vtt                   # YouTube 自动生成英文字幕 (WebVTT 格式)
│   ├── english_subtitles.srt      # 转换后的英文 SRT 字幕
│   └── chinese_subtitles.srt      # 生成的中文 SRT 字幕
├── processed_videos/              # 中间处理输出（刻录后视频等）
└── deployed/                      # 最终部署输出
    ├── final_with_subtitles.mp4   # 刻录字幕后的最终视频
    ├── english_subtitles.srt      # 英文字幕
    ├── chinese_subtitles.srt      # 中文字幕
    └── manifest.json              # 部署清单
```

---

## 🚀 快速开始

### 1. 环境准备

确保已安装以下工具：

```bash
# 检查 ffmpeg 和 yt-dlp
which ffmpeg ffprobe yt-dlp python3

# 如需安装 ffmpeg（Debian/Ubuntu）
apt-get update && apt-get install -y ffmpeg

# 安装 yt-dlp
pip3 install yt-dlp
```

本项目已预置 `bin/ffmpeg` 和 `bin/ffprobe`（静态编译版本）。

### 2. 下载视频与英文字幕

由于 YouTube 反爬虫保护，下载视频需要携带 Cookies 认证：

```bash
# 下载视频 + 英文自动字幕（推荐 480p 以节省带宽）
yt-dlp --write-auto-sub --sub-langs en \
  -f "bestvideo[height<=480]+bestaudio" \
  --cookies-from-browser chrome \
  "https://www.youtube.com/watch?v=9aPyO1jfDGM" \
  -o "/workspace/videos/%(title)s.%(ext)s"
```

> **注意**: 若无浏览器 Cookies，可先仅下载字幕：
> ```bash
> yt-dlp --write-auto-sub --sub-langs en --skip-download \
>   "https://www.youtube.com/watch?v=9aPyO1jfDGM"
> ```

### 3. 运行完整流水线

```bash
cd /workspace
chmod +x scripts/*.sh

# 运行主流水线（下载 → 字幕提取 → 转换 → 中文翻译 → 刻录 → 部署）
bash scripts/full_pipeline.sh
```

### 4. 单独执行各步骤

#### 步骤 A: WebVTT 转 SRT + 生成中文字幕

```bash
python3 scripts/subtitle_processor.py \
  /workspace/videos/*.en.vtt \
  /workspace/videos/english_subtitles.srt \
  /workspace/videos/chinese_subtitles.srt
```

#### 步骤 B: 将字幕刻录到视频

```bash
bash scripts/burn_subtitles.sh \
  /workspace/videos/<视频文件>.mp4 \
  /workspace/videos/english_subtitles.srt \
  /workspace/videos/chinese_subtitles.srt \
  /workspace/processed_videos/final_with_subtitles.mp4
```

#### 步骤 C: 部署输出

```bash
bash scripts/deploy.sh \
  /workspace/videos/<视频文件>.mp4 \
  /workspace/videos/english_subtitles.srt \
  /workspace/videos/chinese_subtitles.srt \
  /workspace/processed_videos/final_with_subtitles.mp4 \
  /workspace/deployed
```

---

## 📋 流水线步骤详解

| 步骤 | 脚本 | 说明 |
|------|------|------|
| 1 | `full_pipeline.sh` | 创建目录、协调所有步骤 |
| 2 | `yt-dlp` | 下载视频 + 提取英文自动字幕 (WebVTT) |
| 3 | `subtitle_processor.py` | WebVTT → SRT 转换 + 中文翻译生成 |
| 4 | `burn_subtitles.sh` | ffmpeg 将双语字幕烧录进视频 |
| 5 | `deploy.sh` | 复制文件到部署目录 + 生成 manifest.json |

---

## 🎯 字幕示例

**英文 SRT** (`english_subtitles.srt`):
```
1
00:00:02,639 --> 00:00:16,310
USA.

3
00:00:18,870 --> 00:00:18,880
>> Thank you. Thank you. And God bless each
```

**中文 SRT** (`chinese_subtitles.srt`):
```
1
00:00:02,639 --> 00:00:16,310
美国.

3
00:00:18,870 --> 00:00:18,880
>> 谢谢. 谢谢. 愿上帝保佑每一位
```

---

## ⚙️ 配置说明

### 中文翻译（当前为模拟模式）

`scripts/subtitle_processor.py` 中内置了常见字幕短语的英文→中文映射表。未匹配的内容会标记为 `[待翻译]`。

如需接入真实翻译 API（如有道、百度、谷歌翻译），请修改 `generate_chinese_subtitles.py` 中的 `simple_translate()` 函数，替换为实际的 API 调用。

### ffmpeg 字幕样式

`burn_subtitles.sh` 中使用的字幕样式可自定义：

```bash
-vf "subtitles=subtitle.srt:force_style='FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Bold=1,BorderStyle=1,Outline=2,Shadow=1,MarginV=30,Alignment=2'"
```

---

## 📦 部署输出

运行完流水线后，`/workspace/deployed/` 目录包含：

```
deployed/
├── final_with_subtitles.mp4    # 刻录中英字幕后的最终视频
├── english_subtitles.srt        # 英文字幕文件
├── chinese_subtitles.srt        # 中文字幕文件
└── manifest.json               # 部署清单（包含处理日期、步骤、文件结构等）
```

`manifest.json` 示例：
```json
{
  "project": "Video Subtitle Processing Pipeline",
  "source_url": "https://www.youtube.com/watch?v=9aPyO1jfDGM",
  "processing_date": "2026-10-26T...Z",
  "steps_completed": [...],
  "subtitle_count": 6281,
  "languages": ["en", "zh"]
}
```

---

## ⚠️ 已知限制

1. **YouTube 视频下载**: 由于 YouTube 反爬虫机制，直接下载视频流可能返回 HTTP 403。建议使用 `--cookies-from-browser` 或手动导出 Cookies。
2. **字幕语言**: 目标视频仅提供英文自动生成字幕，不提供中文字幕。中文字幕由本项目模拟翻译生成。
3. **视频文件**: 仓库中目前未包含实际的 `.mp4` 视频文件（受 YouTube 限制未能下载），仅包含已提取的 `.en.vtt` 字幕和生成的 `.srt` 字幕。

---

## 🛠 技术栈

| 工具 | 用途 | 版本 |
|------|------|------|
| yt-dlp | YouTube 视频/字幕下载 | 2026.10.21 |
| ffmpeg / ffprobe | 音视频处理、字幕烧录 | 7.0.2-static |
| Python 3 | 字幕格式转换、翻译生成 | 3.11 |
| Bash | 流水线编排 | - |

---

## 📄 许可证

MIT License

---

**项目地址**: https://github.com/gitsynonyms01/gitsynonyms.git  
**目标视频**: https://www.youtube.com/watch?v=9aPyO1jfDGM
