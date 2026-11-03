# 模块2：视频处理部

## 职责边界

模块2处理**已经由上游选定**的视频和字幕。输入至少要能定位源视频、字幕目录、
目标语言和输出目录；模块2不负责频道扫描、视频选择、资源登记或上游巡检。

## 职责单元

### 层级

```text
模块2：视频处理部（部级）
├── 字幕制作司
│   ├── ASR处（语音转写）
│   │   ├── 引擎评测科
│   │   └── 转写执行科
│   └── 翻译处（英译中字幕）
│       ├── 引擎评测科
│       └── 翻译执行科
├── 语音制作司
│   ├── 语音刻录处（TTS 配音与音轨刻录）
│   │   ├── 音色科
│   │   └── 混音科
│   └── 语音克隆处（零样本声音克隆，须书面授权）
│       ├── 授权科
│       └── 克隆科
├── 字幕时间精确刻录司
│   ├── 字幕区判定处
│   │   └── 判定科
│   └── 刻录渲染处
│       ├── 渲染科
│       └── 输出科
└── 质检交接司
    ├── 素材接收处
    │   └── 接收科
    └── 质检交接处
        ├── 质检科
        └── 交接科
```

### 司处职责

| 司 | 处 | 职责 | 实现 |
|---|---|---|---|
| 字幕制作司 | ASR处 | 七格式确实缺失时，全网研究、打分并执行语音转写，产出逐词时间戳 | [`module-2-asr-office.md`](module-2-asr-office.md) |
| 字幕制作司 | 翻译处 | 研究、打分并执行英译中字幕翻译，保证逐条对应 | [`module-2-translation-office.md`](module-2-translation-office.md) |
| 语音制作司 | 语音刻录处 | 用音色库合成配音，按 cue 对齐后混入原声 | [`module-2-voice-production.md`](module-2-voice-production.md) |
| 语音制作司 | 语音克隆处 | 零样本声音克隆；仅限本人或书面授权的配音员 | 同上 |
| 字幕时间精确刻录司 | 字幕区判定处 | 检测片源字幕区是否被横幅遮挡；有遮挡时启用半透明总统蓝背景，干净片源直接显示字幕、不画背景框 | `scripts/video_processing.py` |
| 字幕时间精确刻录司 | 刻录渲染处 | 发现并保留 YouTube 七种字幕格式；以 JSON3 逐词时间为主融合时间轴并生成 ASS；单遍 libass 硬字幕；按需生成 540p 预览与封面；成功后原子替换最终输出 | `scripts/subtitle_timing.py`、`scripts/video_processing.py` |
| 质检交接司 | 素材接收处 | 读取上游选择清单；校验视频与字幕目录、语言对、文件完整性和输出路径 | `scripts/video_processing.py` |
| 质检交接司 | 质检交接处 | 用 ffprobe 校验输入/输出；检查字体与缺字；输出 `BURN.json`、`TIMING.json` 及可复核的处理结果 | `scripts/video_processing.py`、`scripts/subtitle_timing.py` |

科级分工：ASR处、翻译处各设引擎评测科与执行科；语音刻录处设音色科与混音科；
语音克隆处设授权科与克隆科；字幕区判定处设判定科；刻录渲染处设渲染科与输出科；
素材接收处设接收科；质检交接处设质检科与交接科。

四个研究单元（ASR处、翻译处、语音刻录处、语音克隆处）的评分口径、候选排名与选型
结论统一存放在 `docs/engines/`：`asr.md`、`translation.md`、`voice-burn.md`、
`voice-clone.md` 由 `scripts/engine_registry.py` 从 `docs/engines/data/*.json` 生成，
总分按评分表重算。

第三方字幕比较、ASR 模型研究和字幕人体工学由
`scripts/third_party_captions.py`、`scripts/speech_model_research.py`、
`scripts/subtitle_ergonomics.py` 提供支撑能力，归入上述职责单元协作。
根目录旧档案 [`../MODULE2_ORG.md`](../MODULE2_ORG.md) 仅保留为本页入口，
本页是当前模块2架构的唯一详细说明。

## 时间轴精度规则

1. 读取并融合以下七种 YouTube 格式：`vtt`、`srt`、`ttml`、`srv3`、`srv2`、
   `srv1`、`json3`。JSON3 的逐词 `tOffsetMs` 是主要来源；`srv3`/`srv2` 用作逐词
   时间佐证，其余格式补充 cue 边界。保留可用源格式并记录无法解析的来源。
2. 融合时间轴以整数纳秒表示；YouTube 源时间分辨率最高为 1 毫秒，因此纳秒是无损
   的内部计量单位，**不代表源数据含纳秒级观测精度**。不从量化值虚构更细的来源精度。
3. `TIMING.json` 保存纳秒整数时间轴、来源与融合统计。`*.precision.vtt` 以毫秒写出；
   ASS/libass 只接受厘秒时间戳，刻录前按 10 毫秒量化，最大量化误差 5 毫秒，并将误差
   写入时间报告/ASS 信息。因而“优于毫秒”仅适用于内部时间轴表示，不适用于 ASS
   刻录结果；纳秒也不是 YouTube 原始字幕精度。
4. ASS 先对滚动 cue 去重，再按句末标点恢复中英句段并按时间顺序配对；两轨分句数不同
   时只合并相邻句段，不得静默丢字或输出单语 cue。ASS 生成遇到任一语言无有效时间线时
   必须显式失败。逐词高亮仍使用融合后的英文源词时间。双语 ASS 固定使用配置字号
   （默认英文 48、中文 57.6），单行超宽时按逐词/逐字时间切分事件，不得逐事件缩小字号；
   切分必须保留中英文本顺序且每段均有双语内容，无法满足时显式失败。

## 字幕方案等级

- **基准档：沉浸式翻译 v1.34.4**，作为独立行为比较基线，不复制其实现。
- **自研方案1：SRT 重叠结束时间校正**，高于基准档一个方案等级。格式融合时，若当前
  SRT cue 的结束时间晚于下一 cue 的开始时间，则将当前 cue 的结束时间截到下一 cue
  的开始时间；开始时间与文本不变。若截断会令 cue 时长归零或为负，必须显式失败，不得
  静默丢弃字幕。该校正不改变其他格式的时间规则。
- **样例1**：官方英文自动字幕 cue 为 `00:00:00,480–00:00:06,960`、
  `00:00:02,399–00:00:09,599`、`00:00:06,960–00:00:12,080` 等连续滚动区间；
  方案1 将前几条结束时间依次截到 `00:00:02,399`、`00:00:06,960`、
  `00:00:09,599`。官方中文自动翻译轨的首条 cue 为空，解析时跳过；其余 cue 保留文本，
  并按相同规则截断重叠结束时间。生成双语 SRT 时，以校正后的英文 cue 为输出时间轴；
  每条必须有中英两行。若首条英文 cue 与首条有效中文 cue 仅在边界相接，则将该中文 cue
  延用到首条英文 cue，形成样例中的重复译文，不得输出单语 cue。此样例不授权对译文
  文本去重或静默改写。
- 所有自研方案1生成的双语 SRT 都必须遵守上述逐条双语与结束时间截断规则；若无法匹配
  双语 cue 或会留下未配对译文，必须显式失败，不得静默输出部分字幕。
- **方案1 SRT→ASS**：使用 `scripts/scheme1_srt_to_ass.py` 转换；输入每条必须恰有一行中文
  和一行英文，且时间顺序递增、cue 不重叠。样式为中文 Microsoft YaHei（英文字号的
  1.2 倍、金色 `#FFC928`）、英文 Segoe UI 48 px，英文常态暖白 `#F2F1EC`、
  逐词高亮低饱和青色 `#9BCBD1`，使用深色描边且不默认加背景框。每种语言严格单行，
  超宽时缩小字号至安全区内而不换行。独立的右侧闭合标点 cue 必须附到前一条双语 cue，
  并将其结束时间延长至该标点 cue 的结束时间，避免标点单独起行。其余每个 SRT cue 成为
  独立 ASS 显示事件，不合并 cue、不改变起止时间。字体与配色是方案默认值；生成器允许
  替换 ASS 的英文高亮色参数，但不得改变方案1的双语和时间校验。示例：
  `python scripts/scheme1_srt_to_ass.py "D:\MyDownload\a\bilingual_scheme1_Chinese-English.srt"`。
- 等级是方案分类，不等同于已证实的质量胜出；与沉浸式翻译的行为比较仍须按翻译处的
  盲审要求执行并记录结果。

## 字幕区与画面规则

- **检测到横幅遮挡字幕区**：选择不覆盖关键信息的位置，绘制半透明总统蓝
  `#0F1647` 背景框，再显示字幕；透明度须可配置并写入 `BURN.json`。
- **确认是干净片源**：不绘制背景框或遮挡区，只显示字幕。
- **自动检测失败**：采用总统蓝框的保守回退，避免横幅遮挡导致字幕不可读，并在
  `BURN.json` 记录错误和回退来源；不得静默按“干净”处理。用户可显式强制开/关。
- `BURN.json` 应记录检测结论、置信信息、区域坐标、所用样式及渲染参数。
- 自动字幕区判定适用于从七格式字幕目录生成 ASS 的流程；若上游交付的是已排版 ASS，
  当前实现保留其内嵌布局，不会自动重排或补加字幕框。

## 实现与运行边界

- `video_processing.py` 接收已选择的视频/字幕清单，运行 ffprobe 检查，自动判定横幅，
  单遍 libass 刻录，并按选项生成 540p 预览、封面和 `BURN.json`；刻录到临时文件，
  检查输出后通过原子替换发布最终 MP4。
- `local_subtitle_flow.py` 是本地两段式入口：先走 YouTube 七格式（中文轨缺失时机器
  翻译），仅在字幕报告证明英文轨确实缺失时才用 AssemblyAI 逐词转写并翻译；探测
  失败按暂时性故障中止，不得当作“无字幕”直接付费转写。决策、引擎与输出格式写入
  `LOCAL_FLOW.json`。显式维度通过 `--preset` 选择：`local-youtube-official`、
  `local-youtube-mt`、`local-asr-mt`、`local-asr-official`、
  `url-youtube-official`、`url-youtube-mt`、`offline-official`、`offline-mt`；
  `--english-source youtube|asr|auto` 与 `--chinese-source youtube|mt|auto` 是底层
  开关，选择结果写入 `LOCAL_FLOW.json.selection`。可直接复制的 PowerShell 命令见
  `docs/LOCAL_FLOW_MATRIX.md`；`local_subtitle_flow.ps1` 支持 `-List` 逐行复制执行，
  也支持 `-Preset a,b`、`-All -Yes` 批处理，每次调用按行追加到
  `<Directory>\LOCAL_FLOW_COMMANDS.jsonl`（预设、命令、退出码、耗时、是否 dry-run），
  该日志不提交仓库。另有 `manual_local_flow.ps1` 面向人工逐条操作：`-List` 打印
  带注释的命令，`-Step 1,3,5` 单步/多步执行，`-All -Yes` 跑主路径（0-3、5、6、9、10，
  4/7/8 为手工/备选分支），日志写入 `<Directory>\MANUAL_FLOW_COMMANDS.jsonl`。
  另有 `manual_youtube_commands.ps1` 为原样命令清单：每条 yt-dlp/ffmpeg 命令直接写在
  `if ($RunIds -contains N)` 块里，可就地改参数。步骤既可在文件里改 `$Run = @(0)`，
  也可命令行传 `-Run 0`、`-Run 1,3,5`、`-Run 0,1,2,3,5,6,9,10`；`-Url` / `-OutDir`
  同样可在命令行覆盖。
  56 秒通过 yt-dlp 的 `--sleep-subtitles` 传给中文字幕请求，
  英文请求不设置该间隔；它不是流程级等待（可由同名参数覆盖），`--wait` 暂保留为
  兼容别名。本地流程默认不画背景框；启用背景框时，使用独立的框坐标
  `CAPTION_BOX_AREA = (66, 883, 1852, 1022)`，文字安全区仍为
  `CAPTION_AREA = (96, 883, 1824, 1008)`；前者可通过 `--box-x/y/width/height` 覆盖。
  确认源横幅压住字幕区时，须显式传入
  `--box-style solid-color --box-color "#000000" --box-opacity 1`，背景框从视频起始持续
  至片尾；干净片源仍可保持无框。
- `subtitle_timing.py` 发现七种格式、融合 JSON3 优先的逐词时间，调用
  `subtitle_timeline.py` 按完整句段配对后生成 ASS、`TIMING.json` 和毫秒级 precision
  VTT。ASS 输出的 10 毫秒粒度与 5 毫秒最大量化误差是格式/渲染器边界，不得描述为
  亚毫秒精度。
- `subtitle_ergonomics.py` 检查字幕人体工学约束，并由视频处理流程汇总告警/结果。
- `third_party_captions.py` 与 `speech_model_research.py` 是可选比较/研究工具，不是
  刻录主链路的必要依赖。
- 独立模块本身已有实现和离线测试；是否接入具体的上游自动任务，应以对应 workflow
  调用和运行证据为准，不因模块存在就宣称云端端到端自动发布已完成。
- **执行位置**：素材下载、字幕获取、刻录与打包在云端 runner 执行；本地只保存代码、
  配置与登记表（见 `DIRECTIVE.md` 3.6）。
- `download_youtube_bilingual_srt.py` 的中英双语输出使用方案1：英文 cue 作为输出时间轴，
  校正重叠结束时间，并保证每条同时含中英文；无法满足时显式失败。
- **交付语言**：成片与字幕必须中英双语同时具备。缺少任一语种时先补足该语种字幕
  （官方字幕轨优先，其次合规机器翻译），不得以单语成片交付。

## 字幕候选评分（最高指示 3.7 的展开）

每个候选字幕按 100 分制打分，分数与理由写入 `SUBTITLE_SOURCES.json`：

| 维度 | 满分 | 计分口径 |
|---|---|---|
| 语言覆盖 | 40 | 中英双全 40；仅单语 15；缺失 0 |
| 时间轴精度 | 25 | 逐词 `json3`/`srv3` 25；毫秒级 `vtt`/`ttml`/`json3` 18；厘秒 `srt` 10 |
| 来源权威性 | 15 | YouTube 原始轨 15；官方文字稿 12；ASR 或机器翻译 6；第三方转载 5 |
| 覆盖率 | 15 | 字幕覆盖时长 ÷ 视频时长 × 15 |
| 可复核性 | 5 | 有 URL 与抓取时间 5；仅本地文件 3；无法追溯 0 |

- 及格线 60 分；进入刻录的每一语种都必须 ≥ 60 分。
- 优先顺序：YouTube 七格式 → 官方文字稿 → ASR（如 AssemblyAI）→ 机器翻译。
- 机器翻译或 ASR 产物必须标注 `machine-translated` / `asr`、引擎名与生成时间。
- 同一语种存在多个候选时，取分数最高者；分数相同取时间轴精度更高者。

## 案例记录：钦定素材的 720p 例外与字幕取用（2026-10-29）

**素材**：`yt:lJYmGObStag`（FOX 10 Phoenix，President Trump delivers remarks at rally in
Chillicothe, OH，事件日期 2026-10-28）。

**720p 例外**

- 该条在 YouTube 侧最高只发布 720p，无法满足 `DIRECTIVE.md` 3.6 的 1080p 下限。
- 总控于 2026-10-29 批准本次按 720p 刻录，属**一次性例外、下不为例**。
- 例外只作用于本条素材：`download_source_video.py` 的默认 `--min-height` 仍为 1080，
  验收线不放宽；降级须在交付声明（`SOURCE_DECLARATION.json`）与提交说明中显式记录，
  隐瞒降级仍按 P0 处置。
- 本例同时暴露并修复了下载器缺陷：代理分支原先只请求 `formats[0]`（1080p），
  遇到 `Requested format is not available` 就丢弃仍可用的代理；修复后代理同样走
  `1080p → 720p → 任意` 的格式链。

**字幕取用顺序（本例实走路径）**

1. `en-orig` 取 YouTube 原始轨七格式：`json3`、`srv3`、`srv2`、`srv1`、`ttml`、`vtt`、`srt`；
   逐词时间以 `json3` 为准，其余格式交叉校验。
2. `zh-Hans` 取 YouTube 官方默认自动翻译轨，与英文轨一起交给
   `subtitle_timing.build_precise_ass` 生成精确 ASS。
3. 仅当第 1、2 步确实缺失时，才按 3.7 外扩到官方文字稿 / ASR / 机器翻译，并标注
   来源类型、引擎与生成时间。

## 交接验收

处理任务完成时，至少应交付最终 MP4、ASS、`BURN.json`、`TIMING.json` 和质检结果；
使用 caption-directory 模式时，还应交付毫秒级 `*.precision.vtt`。失败时保留明确错误
与失败阶段，不将部分视频作为成功输出；最终文件应在校验通过后原子替换。
