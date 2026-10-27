# ASR处（语音转写处）

## 隶属

模块2：视频处理部直属，2026-10-27 由总控设立。与翻译处、语音制作司平行。

## 职责边界

当 YouTube 七种字幕格式**确实缺失**时（最高指示 3.7 第 2 款），本处负责：

1. 全网研究语音转写引擎的准确率、语言覆盖、逐词时间戳、成本与合规条款；
2. 按统一口径打分排名，维护 `docs/engines/data/asr.json`；
3. 选定引擎并在云端 runner 上执行转写，产出逐词时间戳；
4. 把引擎、版本、生成时间与分数写入 `ASR.json`，供交付报告引用。

本处**不做**：频道巡检、来源选择、翻译（归翻译处）、字幕排版与刻录（归字幕时间精确刻录司）。

## 评分口径

100 分制，权重与计分规则写在 `docs/engines/data/asr.json` 的 `rubric` 中，由
`scripts/engine_registry.py` 校验权重合计为 100、每个分数落在权重区间内。

| 维度 | 权重 | 关注点 |
|---|---:|---|
| 转写准确率 | 30 | 干净语音与难音频的 WER/CER 分开看 |
| 中英语言覆盖 | 15 | 英语、简体中文都要能直接转写 |
| 逐词时间戳 | 15 | 有原生词级起止时间，才能喂给 ASS |
| 成本 | 15 | 每音频小时公开价 |
| 延迟与吞吐 | 10 | 3 小时素材的端到端等待 |
| 可获得性 | 10 | 仓库是否已有密钥、能否直接调用 |
| 可复核性 | 5 | 模型版本固定、命令可重跑 |

及格线 60 分；低于及格线的引擎不得用于交付。

## 研究来源

- verliapp/stt-benchmark：LibriSpeech 干净集与 Earnings-22 难音频的 WER；
- Openbenchmarks 结构化实体基准：邮件、电话、编号等实体的任务成功率；
- Pipecat 开放 STT 基准：语义 WER 与首包延迟；
- Hugging Face Open ASR Leaderboard：开放权重模型的 WER 与 RTFx；
- koedesk 十二语种基准：中文、日文等方向的独立复测；
- 各家官方定价页（AssemblyAI、Deepgram、Google、ElevenLabs、OpenAI）。

## 当前排名（2026-10-27）

完整表与逐维度得分见 [`docs/engines/asr.md`](../docs/engines/asr.md)。

| 名次 | 引擎 | 总分 | 结论 |
|---:|---|---:|---|
| 1 | AssemblyAI Universal-3.5 Pro | 91 | 主用 |
| 2 | ElevenLabs Scribe v2 | 86 | 升级项 |
| 3 | Whisper large-v3（自托管） | 81 | 无密钥兜底 |
| 4 | Deepgram Nova-3 | 79 | 实时备选 |
| 5 | Speechmatics Linden-1 | 78 | 商务接入 |

选型：**AssemblyAI Universal-3.5 Pro**。理由是仓库已有 `ASSEMBLYAI` 密钥、
$0.21/音频小时、原生逐词时间戳，且已在真实素材上跑通过。没有密钥时回退
faster-whisper，接受更慢的中文质量。

已知条款风险：有公开审计指出 AssemblyAI 的服务条款禁止用其服务做基准测试。
本处的分数一律取自第三方公开基准，不自行调用其 API 跑评测。

## 实现映射

| 环节 | 实现 |
|---|---|
| 托管转写 | `scripts/assemblyai_captions.py`（上传 → 提交 → 轮询 → 写 json3/srt/vtt/ttml + `ASR.json`） |
| 本地兜底 | `scripts/asr_captions.py`（faster-whisper） |
| 流水线接入 | `.github/workflows/auto-pipeline.yml` 的 “ASR fallback when the English track is missing” |
| 排名与校验 | `scripts/engine_registry.py check` / `rank --office asr` |
| 评分离线测试 | `tests/test_engine_registry.py` |

## 复核方式

```bash
python scripts/engine_registry.py check
python scripts/engine_registry.py rank --office asr
python scripts/engine_registry.py markdown --office asr --write
```

排名变化必须同时更新 `updated_at` 与证据的 `observed_at`；没有新证据不得改分。

## 未完成与限制

- 中文转写质量缺少同素材的 A/B 实测，现有结论依赖公开基准；
- `ASR.json` 的分数公式与本节评分表尚未统一（前者是单次转写质量，后者是引擎选型）；
- ElevenLabs Scribe v2 只在文档层评估，尚未在 runner 上跑过。
