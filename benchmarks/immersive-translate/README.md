# 中英双语字幕最低（LOWEST）基准：`scheme_local__immersive_lowest` /
# Immersive Translate v1.34.4

这份基线回答一个问题：**烧录字幕做到什么程度才算合格？** 本地中英基准方案为
`scheme_local__immersive_lowest`（沉浸翻译最低 / LOWEST 标准）。

答案是「至少不比浏览器里最常用的双语字幕扩展差」。沉浸式翻译（Immersive
Translate）是 Chrome 商店里使用最广的视频双语字幕方案，用户每天拿它当参照
物。所以它被定为模块 2 的**最低线（floor）**，不是追赶目标，也不是上限。

- 基线版本：`1.34.4`（`manifest.json` 声明）
- 扩展 ID：`bpoadfkcbjbfhfodiogcnhhhpibjhbnh`
- CRX SHA-256：`72c0dc8ad563db812df9385b3207b0f85a8d2f071738f13a31a6377e39c0cf5f`
- 机器可读规格：[`baseline.json`](baseline.json)
- Chrome 运行时观察：[`observed-2026-11-08.json`](observed-2026-11-08.json)
- 验收测试：[`tests/test_subtitle_baseline.py`](../../tests/test_subtitle_baseline.py)

## 为什么仓库里没有 CRX

CRX 是二进制第三方产物，仓库只存代码、字幕、JSON 和小型网页资产。这里保留
的是**可复现的抓取脚本 + 字节级哈希锚点**：

```bash
python scripts/benchmarks/fetch_immersive_translate.py            # 下载到临时目录并校验
python scripts/benchmarks/fetch_immersive_translate.py --verify   # 只校验本地已有副本
python scripts/benchmarks/fetch_immersive_translate.py --refresh-hashes   # 版本升级后重钉哈希
```

脚本会核对 CRX 大小与 SHA-256、拆开 CRX3 头、解包，并逐个核对
`baseline.json` 里记录的 5 个关键文件哈希。任何一项对不上就非零退出——这样
「基线」不会在某次静默的版本更新后漂移。

## 观察到的行为（v1.34.4）

证据来自发布产物本身：`content_main.js`、`video-subtitle/inject.js`、
`default_config.json`，一次 REA 静态应用图分析
（`ev_8afad77784dc3350625bc01599d2ddd910cc811cc08b8f6054508c3d7a25855f`），
以及 2026-11-08 在 Chrome 里对 `e038Q_qaltQ` 的实时采样
（`observed-2026-11-08.json`，150 s / 1186 帧）。

| 环节 | 行为 |
|---|---|
| 字幕获取 | 劫持页面自己的 XHR/fetch 字幕请求，**不重新下载**；`hookType: "xhr"`、`preTranslation: true` |
| 短语来源 | YouTube 的 TTML `p` / json3 事件；`preMergeSubtitles` 先合并滚动短语，再做阅读速度裁剪 |
| 显示单位 | **拼接后的活动短语窗口**，不是单条源 cue；重叠短语首尾相接，重叠部分原样保留（观察到 `that, that`） |
| 译文 | 对当前可见窗口整体翻译，通常晚约 0.5 s 到达；加载时只显示原文或“翻译中”提示 |
| 翻译服务 | 观察到的加载标签是“微软翻译”；`defaultFallbackServices` 仍为 `["bing","google"]` |
| 双语呈现 | `translationMode: "dual"`、`translationPosition: "bottom"`，字号 100%、白字、`#080808` 75% 底、阴影 |
| 排版 | 由每站点远程规则 `attachRule.injectedCSS` 决定，**扩展本体没有固定字符预算** |
| 静音词 | 默认开启，正则 `\([^)]*\)|\[[^\]]*\]` 过滤 `[music]`、`(applause)`、`>>` 之类 |
| 词级高亮 | 扩展 overlay 没有；YouTube 原生播放器可能在自己的字幕 DOM 里加粗当前词 |

## 端到端流程（v1.34.4）

```text
YouTube watch page
  └─ 页面自己的 timedtext 请求（TTML <p> / json3 events）
       └─ 扩展 hook XHR/fetch（hookType: "xhr", preTranslation: true）
            └─ preMergeSubtitles：把当前活动的滚动短语拼成一个可见窗口
                 │  · 重叠短语首尾相接，重叠部分原样保留（会看到 that, that）
                 │  · pCe 按阅读速度裁剪单条短语的显示时长
                 └─ 对整个可见窗口请求翻译（观察到的加载标签：微软翻译；
                    defaultFallbackServices 仍为 bing、google）
                      └─ 目标行通常晚约 0.5 s 到达；加载期间只显示原文或“翻译中”
                           └─ dual overlay：原文 + 译文，bottom，白字，
                              #080808 75% 底、阴影；排版由每站点注入 CSS 决定
```

关键点不是“它用了哪个翻译 API”，而是**显示单位和翻译单位都是当前活动的短语窗口**：
源短语先合并，再整体翻译，最后作为一条 overlay 显示。扩展不重新下载字幕，也不在
本地保存字幕文件；它复用页面已经拿到的 timedtext 响应。

本地 LOWEST 流程按同一顺序重建，但把 overlay 换成可烧录的 ASS：

| 环节 | 扩展 v1.34.4 | 本地 `scheme_local__immersive_lowest` |
|---|---|---|
| 源时间轴 | 页面 timedtext；TTML/json3 | 七格式齐全，`json3` 为主时间轴，其余六种交叉校验 |
| 显示单位 | 活动短语窗口，重叠不去重 | 英文短语按句/从句聚成单元，跨 cue 去重 |
| 翻译单位 | 整个可见窗口 | 整条官方中文 cue 分配给重叠最多的英文单元，不切开中文 |
| 缺中文的英文单元 | 窗口里可能只有原文 | 合并到最近的双语事件，`source_units_skipped = 0` |
| 排版 | 站点 CSS，无固定字符预算 | 中文 ≤28 全角字符/行、英文 ≤60 字符/行；超宽在从句/ cue 边界切分 |
| 词级时间 | overlay 无卡拉 OK | `json3` 的 `tStartMs + tOffsetMs` 驱动英文 `\k` 卡拉 OK |
| 交付 | 浏览器 overlay，依赖页面和网络 | 离线 ASS，两种语言在同一事件里同时出现 |

## 它没有做的四件事（也就是我们必须超过的地方）

1. **没有跨 cue 去重。** 活动的重叠短语直接拼接，捕获到的源窗口里出现
   `exactly that, that we're going to do...`；滚动字幕的尾巴会重复上屏。
2. **没有词级时间。** overlay 只按短语窗口整体显示，英文不存在卡拉 OK 逐词高亮；
   原生播放器的加粗不是扩展产出的 ASS 能力。
3. **没有排版预算。** 换行、最大行数、溢出处理都交给各站点注入的 CSS；扩展自己
   不测量文本宽度，也不缩字号。捕获到 98 字符的源窗口仍按一条显示。
4. **不是离线烧录。** 它是浏览器 overlay，依赖页面、网络与运行时；我们的产物是
   写进画面的 ASS，必须自己保证每个像素可控，且译文不能等到 0.5 s 后才出现。

这四条不是「它做得差」，而是两种交付形态的差异。正因为形态不同，**拿它当最低
线是安全的**：凡是它保证的（源文本不丢、短语锚定源时间轴），我们必须保证；它
不保证的（同时双语、去重、词级时间、固定排版预算、离线可控），我们额外保证。
它也暴露了一个反向要求：新窗口出现后的前约 0.5 s 不能只有原文占屏，我们的 ASS
必须让两种语言在同一事件里同时出现。

## 验收方式

`tests/test_subtitle_baseline.py` 把 `baseline.json` 里的 `requirements` 逐条变成
测试，并额外做一次一致性检查：**每条 requirement 都必须有一个同名测试函数**，
少一条就失败。文档和代码不会各说各话。

其中三条在真实的 3 小时语料上跑（`9aPyO1jfDGM` 归档），其余用合成滚动字幕，
确保失败时能定位到具体规则而不是某个视频。

## 升级基线

```bash
python scripts/benchmarks/fetch_immersive_translate.py --refresh-hashes
```

然后人工复核 `observed` / `baseline_limits`：如果新版本补上了词级时间或去重，
把它从「我们额外保证」移到「必须保证」，而不是放宽测试。基线只允许单向收紧。

运行时行为用 CDP 采样复核：

```bash
node scripts/benchmarks/capture_immersive_translate.mjs 300 90 capture_300.json
node scripts/benchmarks/capture_immersive_translate.mjs 900 60 capture_900.json
```

脚本假设 Chrome 已用 `--remote-debugging-port=9222` 打开、目标页是
`youtube.com/watch`，且沉浸式翻译已启用。捕获文件是临时证据，不提交；把结论
写入 `observed-YYYY-MM-DD.json` 并更新 `baseline.json` 的 `observed` 字段。
