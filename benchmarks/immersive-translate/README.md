# 字幕质量最低基准：Immersive Translate v1.34.4

这份基线回答一个问题：**烧录字幕做到什么程度才算合格？**

答案是「至少不比浏览器里最常用的双语字幕扩展差」。沉浸式翻译（Immersive
Translate）是 Chrome 商店里使用最广的视频双语字幕方案，用户每天拿它当参照
物。所以它被定为模块 2 的**最低线（floor）**，不是追赶目标，也不是上限。

- 基线版本：`1.34.4`（`manifest.json` 声明）
- 扩展 ID：`bpoadfkcbjbfhfodiogcnhhhpibjhbnh`
- CRX SHA-256：`72c0dc8ad563db812df9385b3207b0f85a8d2f071738f13a31a6377e39c0cf5f`
- 机器可读规格：[`baseline.json`](baseline.json)
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
`default_config.json`，以及一次 REA 静态应用图分析
（`ev_8afad77784dc3350625bc01599d2ddd910cc811cc08b8f6054508c3d7a25855f`）。

| 环节 | 行为 |
|---|---|
| 字幕获取 | 劫持页面自己的 XHR/fetch 字幕请求，**不重新下载**；`hookType: "xhr"`、`preTranslation: true` |
| 时间轴 | 监听 `TextTrack` 的 `cuechange`，取 `activeCues` 全量快照；把原生轨道设成 `mode="hidden"`，自己画 |
| 显示单位 | 源 cue：`{text, start: startTime, end: endTime}` |
| 翻译批量 | 每 5 个 cue 一批（`translateGroupCount: 5`），按语速分档 `velocityGroup: [4,4,4]` |
| 双语呈现 | `translationMode: "dual"`、`translationPosition: "bottom"`，字号 100%、白字、`#080808` 75% 底、阴影 |
| 排版 | 由每站点远程规则 `attachRule.injectedCSS` 决定，**扩展本体没有固定字符预算** |
| 静音词 | 默认开启，正则 `\([^)]*\)|\[[^\]]*\]` 过滤 `[music]`、`(applause)` 之类 |

## 它没有做的四件事（也就是我们必须超过的地方）

1. **没有跨 cue 去重。** 每个 `cuechange` 都取当前 `activeCues` 原样渲染。遇到
   YouTube 那种滚动字幕（后一条 cue 重复前一条的尾巴），重复文字会跟着一起上屏。
2. **没有词级时间。** `formatToSubtitleItem` 只产出 cue 的 `start/end`，英文按整块
   替换，不存在卡拉 OK 逐词高亮。
3. **没有排版预算。** 换行、最大行数、溢出处理都交给各站点注入的 CSS；扩展自己
   不测量文本宽度，也不缩字号。
4. **不是离线烧录。** 它是浏览器 overlay，依赖页面、网络与运行时；我们的产物是
   写进画面的 ASS，必须自己保证每个像素可控。

这四条不是「它做得差」，而是两种交付形态的差异。正因为形态不同，**拿它当最低
线是安全的**：凡是它保证的（双语、与源时间轴对齐、不丢文本），我们必须保证；它
不保证的，我们额外保证。

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
