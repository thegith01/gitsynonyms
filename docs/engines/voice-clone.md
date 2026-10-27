# 语音克隆处：零样本声音克隆引擎研究与排名

> 评分口径 v1.0　数据更新 2026-10-27　及格线 60/100

本页由 `scripts/engine_registry.py markdown` 从 `docs/engines/data/voice-clone.json` 生成；总分由评分表重算，不接受手填。每个分数都必须有可复核链接。

## 评分维度

| 维度 | 权重 | 计分口径 |
|---|---:|---|
| 音色相似度 | 30 | 盲听相似度（1–5）或说话人相似度 SS；不同量纲只做同表内相对比较 |
| 中英与跨语种 | 20 | 中文、英语都能克隆且支持跨语种为满分；单语或需重训减半 |
| 自然度与韵律 | 15 | 长句韵律、停顿、情感可控性；盲听自然度优先 |
| 成本 | 10 | 按每千字符或每分钟合成计价；自托管只计算力 |
| 延迟 | 5 | 首包时间与批量合成速度 |
| 授权与合规 | 10 | 强制同意校验、水印、可删除、可本地部署；无同意机制的扣分 |
| 可复核性 | 10 | 权重可下载、版本可固定、可离线复跑为满分；纯黑盒 API 减分 |

## 排名

| 名次 | 引擎 | 类型 | 总分 | 结论 | 数据性质 | 成本 |
|---:|---|---|---:|---|---|---|
| 1 | `cosyvoice-3-open` Fun-CosyVoice 3.0（0.5B，Apache-2.0） | self-hosted | 90 | 可用 | measured | 免费权重，单卡可跑 |
| 2 | `fish-audio-s2-pro` Fish Audio S2 Pro | hosted-api | 88 | 可用 | measured | 中低，按字符计 |
| 3 | `elevenlabs-multilingual-v2` ElevenLabs Multilingual v2 | hosted-api | 81 | 可用 | measured | 按 credit，单价高 |
| 4 | `inworld-tts-2` Inworld TTS-2 | hosted-api | 77 | 可用 | measured | 低 |
| 5 | `cartesia-sonic-3-6` Cartesia Sonic 3.6 | hosted-api | 75 | 可用 | measured | 中 |
| 6 | `minimax-speech-2-6` MiniMax Speech 2.6 | hosted-api | 75 | 可用 | vendor-claimed | 低 |
| 7 | `f5-tts` F5-TTS（开源权重，CC-BY-NC） | self-hosted | 74 | 可用 | measured | 免费权重，需 GPU |
| 8 | `resemble-ai` Resemble AI | hosted-api | 73 | 可用 | vendor-claimed | 高，企业合同 |
| 9 | `xtts-v2` Coqui XTTS v2 | self-hosted | 72 | 可用 | measured | 免费权重，4GB 显存可跑 |
| 10 | `openvoice-v2` OpenVoice v2（MyShell） | self-hosted | 71 | 可用 | vendor-claimed | 免费权重 |

## 选型

- **当前主用**：`cosyvoice-3-open`
- **达到条件后升级**：`fish-audio-s2-pro`
- **回退**：`xtts-v2`

主用 CosyVoice 3：Apache-2.0 代码与权重、中文 SS 78.0 高于人类参考线、9 语言 + 18 方言、可完全离线，配合仓库现有的同意书闸门能形成可审计链路。Fish Audio S2 Pro 盲听相似度更高（4.03），但需要云端密钥与所有权校验，列为升级项；XTTS v2 作为 4GB 显存/无 GPU 环境的兜底。White House 原始素材中的真人声音一律不得克隆：克隆处只服务已书面授权的本人或受聘配音员。

## 逐维度得分

| 引擎 | 音色相似度 | 中英与跨语种 | 自然度与韵律 | 成本 | 延迟 | 授权与合规 | 可复核性 | 总分 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `cosyvoice-3-open` | 23 | 19 | 13 | 10 | 5 | 10 | 10 | 90 |
| `fish-audio-s2-pro` | 28 | 19 | 13 | 7 | 4 | 8 | 9 | 88 |
| `elevenlabs-multilingual-v2` | 26 | 19 | 14 | 4 | 4 | 9 | 5 | 81 |
| `inworld-tts-2` | 24 | 15 | 15 | 8 | 4 | 7 | 4 | 77 |
| `cartesia-sonic-3-6` | 27 | 12 | 12 | 6 | 5 | 8 | 5 | 75 |
| `minimax-speech-2-6` | 24 | 16 | 12 | 8 | 4 | 7 | 4 | 75 |
| `f5-tts` | 21 | 12 | 13 | 10 | 3 | 6 | 9 | 74 |
| `resemble-ai` | 25 | 10 | 12 | 4 | 4 | 10 | 8 | 73 |
| `xtts-v2` | 18 | 13 | 10 | 10 | 4 | 7 | 10 | 72 |
| `openvoice-v2` | 17 | 12 | 9 | 10 | 5 | 8 | 10 | 71 |

## 证据

### `cosyvoice-3-open`

官方评测：中文 SS 78.0 / 英文 SS 71.8（人类参考 75.5 / 73.4），中文相似度高于人类参考线；9 种语言 + 18 种中文方言，零样本跨语种克隆，双流式首包约 150ms。Apache-2.0 代码与权重，可完全离线，是同表里合规与可复核性最好的组合。官方指标与商业厂商的盲听分数量纲不同，只在本表内做相对比较。

- 2026-10-27　test-zh SS 78.0 / test-en SS 71.8；9 语言 + 18 方言；150ms 双流式　<https://github.com/FunAudioLLM/CosyVoice>
- 2026-10-27　Apache-2.0 代码与权重，无需申请即可下载　<https://faun.dev/toolbox/cosyvoice-vs-f5-tts/>

### `fish-audio-s2-pro`

Hume 2026-09 盲听榜相似度第一（4.03/5），83 种语言（S2.1 Pro），10 秒样本即可克隆，Apache-2.0 可自托管。专业克隆要求实时所有权校验，合规流程比纯本地模型重。

- 2026-10-27　Hume 盲听相似度 4.03，11 个模型中第一　<https://www.marktechpost.com/2026/09/21/best-voice-cloning-apis-in-2026-speaker-similarity-consent-checks-and-price-per-1m-characters/>
- 2026-10-27　83 种语言，专业克隆含实时所有权校验　<https://aireiter.com/blog/best-voice-cloning-api-2026>

### `elevenlabs-multilingual-v2`

行业质量基准，70+ 语言，Instant 与 Professional 两档克隆；盲听相似度 3.68 略低于 Fish 与 Cartesia。v3 在相似度榜上反而垫底（2.91），选型时不能默认“越新越好”。价格与版本可控性是其短板。

- 2026-10-27　Multilingual v2 相似度 3.68；Eleven v3 2.91　<https://www.marktechpost.com/2026/09/21/best-voice-cloning-apis-in-2026-speaker-similarity-consent-checks-and-price-per-1m-characters/>
- 2026-10-27　70+ 语言，Instant/Professional 两档克隆　<https://www.veed.io/learn/best-voice-cloning-apis>

### `inworld-tts-2`

盲听音质第一（4.61/5），相似度 3.62；200+ 地区覆盖但高质量语言只有 15 种。适合“音质优先、音色不必完全复刻”的旁白场景。

- 2026-10-27　音频质量 4.61 第一，相似度 3.62　<https://www.marktechpost.com/2026/09/21/best-voice-cloning-apis-in-2026-speaker-similarity-consent-checks-and-price-per-1m-characters/>

### `cartesia-sonic-3-6`

首包 <100ms、3 秒样本即可克隆，盲听相似度 3.70；只有 44 种语言、中文非强项，定位是实时语音代理而非长片中配。

- 2026-10-27　Sonic 3.5 相似度 3.70；3.6-beta 自然度 4.36　<https://www.marktechpost.com/2026/09/21/best-voice-cloning-apis-in-2026-speaker-similarity-consent-checks-and-price-per-1m-characters/>
- 2026-10-27　90ms 首包，3 秒样本，15 种语言（早期版本）　<https://www.veed.io/learn/best-voice-cloning-apis>

### `minimax-speech-2-6`

50+ 语言、10 秒样本、亚洲语言（含普通话）保真度是其主要卖点，价格透明且有免费额度；厂商自评为主，缺独立中文相似度盲测。

- 2026-10-27　50+ 语言、10 秒克隆、按量计价　<https://www.veed.io/learn/best-voice-cloning-apis>

### `f5-tts`

开放权重里自然度最好的之一（中文 SS 74.1 / 英文 64.7），但预训练权重是 CC-BY-NC，商用必须先自训；推理要多次去噪，不适合长片批量。

- 2026-10-27　F5-TTS test-zh SS 74.1 / test-en SS 64.7　<https://github.com/FunAudioLLM/CosyVoice>
- 2026-10-27　预训练权重 CC-BY-NC，商用需自训　<https://faun.dev/toolbox/cosyvoice-vs-f5-tts/>

### `resemble-ai`

合规做得最完整：可验证同意、逐条输出水印、支持本地部署；只有 23 种语言，中文非强项。适合有法务要求的品牌音。

- 2026-10-27　可验证同意 + 逐条水印 + on-prem；23 种语言　<https://aireiter.com/blog/best-voice-cloning-api-2026>

### `xtts-v2`

17 种语言、6 秒样本、跨语种克隆，硬件门槛最低（4GB 显存，可 CPU）；音色相似度与长句韵律落后新一代模型，胜在成熟稳定、可完全离线。

- 2026-10-27　17 种语言、6 秒克隆、24kHz、跨语种　<https://huggingface.co/coqui/XTTS-v2>

### `openvoice-v2`

中英日韩西法多语，音色克隆与风格迁移分离，部署轻；自然度和相似度低于 CosyVoice/F5 一档，适合做低成本原型。

- 2026-10-27　多语种开源克隆，英中日常用场景　<https://presenc.ai/research/best-open-weight-text-to-speech-models-2026>
