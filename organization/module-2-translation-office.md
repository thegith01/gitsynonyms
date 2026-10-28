# 翻译处（字幕翻译处）

## 隶属

模块2：视频处理部 字幕制作司，2026-10-27 由总控设立。与 ASR处同属字幕制作司；
与语音制作司、字幕时间精确刻录司、质检交接司平行。

## 职责边界

本处负责把英文轨转换为**简体中文字幕**，并使译文与原文逐条对应：

1. 全网研究翻译引擎在英中方向的质量、成本、限流与可复核性；
2. 按统一口径打分排名，维护 `docs/engines/data/translation.json`；
3. 在云端 runner 上执行批量翻译，保持字幕语义单元的顺序与源时间区间；
4. 在产物中标注 `machine-translated`、引擎名与生成时间（最高指示 3.7 第 4 款）。

本处**不做**：语音转写（归 ASR处）、字幕排版与刻录（归字幕时间精确刻录司）、
成片发布。YouTube 自带中文轨存在时不触发翻译。

## 评分口径

| 维度 | 权重 | 关注点 |
|---|---:|---|
| 译文质量 | 35 | FLORES/WMT 的 COMET、spBLEU、Intento 错误计数 |
| 英译中方向强度 | 15 | 中文是核心语言还是长尾语言 |
| 字幕适配 | 15 | 逐条对应、行长可控、批返回结构化结果 |
| 成本 | 15 | 每百万源字符 |
| 延迟与吞吐 | 10 | 3000+ 条 cue 的批量耗时与限流 |
| 可获得性 | 5 | 仓库是否已有密钥 |
| 可复核性 | 5 | 模型版本能否固定 |

及格线 60 分；同一语种多个候选取最高分。

## 研究来源

- SOTA2 FLORES+ 英中榜：Google Translate、Gemini、GPT-5、NLLB 的 spBLEU/COMET；
- Intento《State of Translation Automation 2026》：229 个方案、100 种语言，
  按每千词加权错误数比较 MT 引擎与 LLM；
- NLLB 翻译准确率榜：英中编辑评分；
- Reeve Foundation 多语语料：本地 LLM 与商业 NMT 的离线对比；
- Google Cloud、DeepL、Azure 官方定价页。

关键事实：Intento 2026 的最佳 LLM 译文错误数中位数只有最佳 MT 引擎的约 1/2.3；
但英中方向上 Google NMT 的 spBLEU 仍最高（36.08），LLM 的 COMET 与之接近。

## 当前排名（2026-10-27）

完整表见 [`docs/engines/translation.md`](../docs/engines/translation.md)。

| 名次 | 引擎 | 总分 | 结论 |
|---:|---|---:|---|
| 1 | AssemblyAI LLM Gateway（gemini-2.5-flash-lite） | 85 | 主用 |
| 2 | Google Cloud Translation LLM | 84 | 升级项 |
| 3 | Google Cloud Translation NMT | 84 | 质量基线 |
| 4 | Gemini 3.1 Pro | 82 | 升级项 |
| 5 | GPT-5.6 Terra | 82 | 升级项 |

选型：**AssemblyAI LLM Gateway**。同一把已配置的密钥、按 JSON 批返回、逐条对齐，
是当前唯一在 3285 条 cue 上验证过的路径。Google Translation LLM 与 GPT-5.6 Terra
质量更高但需要新凭据，列为升级项；Argos 只做无密钥兜底（66 分，及格但不达标）。

此前流水线记录里的“Argos 84/100”是**可跑通性**评分，与本表口径不同，不可混用。

## 翻译质量门

1. **滚动 cue 先去重、后翻译**：YouTube 的 JSON3/VTT 可能重复发送上一段已显示文字；先按原始逐词时间构造不重复的单调时间轴，再按可读显示段翻译，禁止把每个滚动窗口独立翻译后再对译文去重；
2. 逐条对应：返回条数必须等于输入语义单元数，否则整批失败并回退；
3. 时间对齐：每个译文显示段沿用组成它的源词时间范围；不得平均重分配已有 JSON3 逐词时间；
4. 行长：中文单行不超过 18 个全角字符，超出在标点处断行；
5. 术语：人名、机构名、法案名使用固定译名表，不交给模型自由发挥；
6. 抽检：每 100 个译文显示段抽 5 个做回译或人工核对，错误率超过 5% 视为本批不合格；
7. 标注：`SUBTITLE_SOURCES.json` 记录引擎、模型、时间、分数、源 cue 数和翻译显示段数。

### 与沉浸式翻译的滚动字幕基线

沉浸式翻译公开扩展版本仅作为可观察行为的对照，不复制其代码，也不把闭源构建的未知行为当作事实。滚动字幕质量门要求：

- 连续滚动窗口中的重叠词只向翻译器提交一次，保留原始时间顺序与 JSON3 词时间；
- 同一可读显示段的词作为上下文整体翻译，输出保持一段对一段及对应源时间范围；
- 有真实停顿、句界或显示长度上限时才拆分；不把持续滚动的半句拆成若干孤立 cue；
- 与 `[沉浸式翻译 v1.34.4](https://github.com/immersive-translate/immersive-translate/releases/tag/v1.34.4)` 做人工盲审时，至少比较漏词/重词、词序与时间、句段连贯性、中文可读性；发现任何维度退化，不得以“格式正确”判合格。

仓库当前单测以合成 cue 固定“无重复词、无丢词、顺序不变、停顿分段、词时间保留”；人工盲审负责覆盖翻译自然度这一无法由结构测试保证的维度。

## 实现映射

| 环节 | 实现 |
|---|---|
| 批量翻译 | `scripts/machine_translate_captions.py --engine assemblyai\|argos\|mymemory` |
| 流水线接入 | `.github/workflows/auto-pipeline.yml` 的 “Machine-translation fallback for the Chinese track” |
| 排名与校验 | `scripts/engine_registry.py check` / `rank --office translation` |
| 评分离线测试 | `tests/test_engine_registry.py` |

## 复核方式

```bash
python scripts/engine_registry.py check
python scripts/engine_registry.py rank --office translation
python scripts/engine_registry.py markdown --office translation --write
```

## 未完成与限制

- `gemini-2.5-flash-lite` 是轻量模型，成语与长定语处理弱于旗舰模型；
- LLM 网关的模型名可能随供应商滚动，版本不可长期锁定；
- 尚未建立固定译名表，人名与机构名仍由模型自行处理；
- 抽检环节目前是人工约定，没有自动化脚本。
