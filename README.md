# gitsynonyms

视频字幕获取、中英双语生成、ASS 烧录、GitHub Pages 发布流水线。

## 目标视频

- **URL**: https://www.youtube.com/watch?v=9aPyO1jfDGM
- **标题**: LIVE: President Trump rallies in Michigan ahead of state's November Election
- **时长**: 3 小时 16 分 11 秒 (11771 秒)
- **字幕条数**: 6,281 条 (英文自动生成)
- **中文**: 模拟翻译生成 (YouTube 未提供官方中文轨道)

---

## 快速开始

### 1. 环境准备

```bash
# 检查工具
which ffmpeg ffprobe yt-dlp python3

# 安装 ffmpeg (Debian/Ubuntu)
apt-get update && apt-get install -y ffmpeg

# 安装 yt-dlp
pip3 install yt-dlp
```

本仓库已预置 `bin/ffmpeg` 和 `bin/ffprobe`（静态编译版本）。

### 2. 下载视频与英文字幕

YouTube 有反爬虫保护，下载视频流需要携带 Cookies：

```bash
# 下载视频 + 英文自动字幕 (推荐 480p 节省带宽)
yt-dlp --write-auto-sub --sub-langs en \
  -f "bestvideo[height<=480]+bestaudio" \
  --cookies-from-browser chrome \
  "https://www.youtube.com/watch?v=9aPyO1jfDGM" \
  -o "/workspace/videos/%(title)s.%(ext)s"

# 如只下载字幕，不下载视频
yt-dlp --write-auto-sub --sub-langs en --skip-download \
  "https://www.youtube.com/watch?v=9aPyO1jfDGM"
```

### 3. 运行完整流水线

```bash
cd /workspace
chmod +x scripts/*.sh

# 主流水线：下载 -> 字幕提取 -> WebVTT转SRT -> 中文翻译 -> ASS烧录 -> 部署
bash scripts/full_pipeline.sh
```

### 4. 单步执行

**步骤 A: WebVTT 转 SRT + 生成中文字幕**
```bash
python3 scripts/subtitle_processor.py \
  /workspace/videos/*.en.vtt \
  /workspace/videos/english_subtitles.srt \
  /workspace/videos/chinese_subtitles.srt
```

**步骤 B: 将字幕烧录到视频 (ffmpeg)**
```bash
bash scripts/burn_subtitles.sh \
  /workspace/videos/<视频文件>.mp4 \
  /workspace/videos/english_subtitles.srt \
  /workspace/videos/chinese_subtitles.srt \
  /workspace/processed_videos/final_with_subtitles.mp4
```

**步骤 C: 部署输出**
```bash
bash scripts/deploy.sh \
  /workspace/videos/<视频文件>.mp4 \
  /workspace/videos/english_subtitles.srt \
  /workspace/videos/chinese_subtitles.srt \
  /workspace/processed_videos/final_with_subtitles.mp4 \
  /workspace/deployed
```

---

## 项目结构

```
/workspace/
├── README.md                       # 本说明文档
├── bin/                            # 二进制工具
│   ├── ffmpeg                      # FFmpeg 音视频处理
│   └── ffprobe                     # FFprobe 媒体信息
├── scripts/                        # 处理脚本
│   ├── full_pipeline.sh            # 主流水线编排
│   ├── burn_subtitles.sh           # ffmpeg 字幕烧录
│   ├── deploy.sh                   # 部署输出 + 生成 manifest.json
│   ├── subtitle_processor.py       # WebVTT -> SRT 转换 + 中文翻译
│   ├── subtitle_converter.py       # WebVTT 转 SRT 工具
│   ├── generate_chinese_subtitles.py  # 中文字幕生成 (模拟翻译)
│   ├── download_youtube_bilingual_srt.py  # 双语字幕下载 + ASS 生成 + 烧录
│   ├── generate_video_pages.py     # GitHub Pages 静态网页生成
│   └── monitoring/                 # 白宫视频监测 (acquisition, multi_source, ...)
├── videos/                         # 输入视频与原始字幕
│   ├── *.en.vtt                    # YouTube 自动生成英文字幕 (WebVTT)
│   ├── english_subtitles.srt       # 转换后的英文 SRT
│   └── chinese_subtitles.srt       # 生成的中文 SRT
├── output/                         # 监测与归档输出 (按日期/事件/视频ID 分目录)
├── site/                           # GitHub Pages 静态网站源码
├── deployed/                       # 最终部署输出
│   ├── final_with_subtitles.mp4
│   ├── english_subtitles.srt
│   ├── chinese_subtitles.srt
│   └── manifest.json
├── .github/workflows/              # GitHub Actions 工作流
│   ├── deploy-pages.yml            # Pages 自动部署
│   ├── monitor-whitehouse.yml      # 白宫视频监测 + 烧录 + 发布
│   ├── infogap.yml                 # 信息差报告
│   └── jekyll-gh-pages.yml         # Jekyll 部署
└── .github/workflows-deploy/       # 工作流模板备份
```

---

## 字幕示例

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

## GitHub Pages 发布

仓库已启用 GitHub Actions 工作流 `.github/workflows/deploy-pages.yml`，推送 `site/` 目录变更会自动部署。

**部署地址**: `https://gitsynonyms01.github.io/gitsynonyms/`

> **注意**：GitHub 项目 Pages 部署在子目录 `/gitsynonyms/` 下。网页内所有资源引用必须使用**相对路径**（如 `styles.css`、`latest.html`），不要使用绝对路径（`/styles.css`），否则会 404，导致页面看起来是"空"的。

---

## 技术栈

| 工具 | 用途 | 版本 |
|------|------|------|
| yt-dlp | YouTube 视频/字幕下载 | 2026.10.21 |
| ffmpeg / ffprobe | 音视频处理、ASS 字幕烧录 | 7.0.2-static |
| Python 3 | 字幕格式转换、翻译生成、Pages 网页生成 | 3.11 |
| Bash | 流水线编排 | - |

---

## 已知限制

1. **YouTube 视频下载**: 直接下载视频流可能返回 HTTP 403。建议使用 `--cookies-from-browser` 或手动导出 Cookies。
2. **中文字幕**: 目标视频仅提供英文自动生成字幕，不提供中文字幕。中文由本项目模拟翻译生成，未匹配内容标记为 `[待翻译]`。
3. **视频文件**: 受 YouTube 限制，仓库中可能不包含实际 `.mp4` 视频文件，仅包含已提取的字幕。

---

## 许可证

MIT License

---

**项目地址**: https://github.com/gitsynonyms01/gitsynonyms.git  
**目标视频**: https://www.youtube.com/watch?v=9aPyO1jfDGM
