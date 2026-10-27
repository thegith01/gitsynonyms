# 翻译处：英译中字幕翻译引擎研究与排名

> 评分口径 v1.0　数据更新 2026-10-27　及格线 60/100

本页由 `scripts/engine_registry.py markdown` 从 `docs/engines/data/translation.json` 生成；总分由评分表重算，不接受手填。每个分数都必须有可复核链接。

## 评分维度

| 维度 | 权重 | 计分口径 |
|---|---:|---|
| 译文质量 | 35 | FLORES/WMT 的 COMET、spBLEU 与 Intento 错误计数优先；厂商自评按八成折算 |
| 英译中方向强度 | 15 | 中文为母语级目标语言、无需中转英语为满分；中文只是长尾语言减半 |
| 字幕适配 | 15 | 能保持逐条对应、控制行长、按批返回 JSON 为满分；整段自由改写扣分 |
| 成本 | 15 | 按每百万源字符公开价折算；本地模型只计算力 |
| 延迟与吞吐 | 10 | 3000+ 条 cue 的批量翻译耗时与限流风险 |
| 可获得性 | 5 | 仓库已有密钥为满分；需新开户或商务流程按缺口扣分 |
| 可复核性 | 5 | 模型版本可固定、输出可重跑；云端模型随时换版扣分 |

## 排名

| 名次 | 引擎 | 类型 | 总分 | 结论 | 数据性质 | 成本 |
|---:|---|---|---:|---|---|---|
| 1 | `assemblyai-gateway-gemini-2-5-flash-lite` AssemblyAI LLM Gateway（gemini-2.5-flash-lite） | hosted-api | 85 | 可用 | measured | 按 token 计，字幕量级为美元分位 |
| 2 | `google-translation-llm` Google Cloud Translation LLM | hosted-api | 84 | 可用 | measured | $10/M 输入 + $10/M 输出 |
| 3 | `google-cloud-translation-nmt` Google Cloud Translation（NMT） | hosted-api | 84 | 可用 | measured | $20/M 字符 |
| 4 | `gemini-3-1-pro` Google Gemini 3.1 Pro（提示翻译） | hosted-llm | 82 | 可用 | measured | 约 $4.79/M 字符 |
| 5 | `gpt-5-6-terra` OpenAI GPT-5.6 Terra（提示翻译） | hosted-llm | 82 | 可用 | measured | 约 $4.54/M 字符 |
| 6 | `microsoft-translator` Azure AI Translator | hosted-api | 80 | 可用 | estimated | $10/M 字符 |
| 7 | `qwen-mt-open` Qwen-MT / Hunyuan-MT（开源权重） | self-hosted | 79 | 可用 | measured | 免费权重，按算力计 |
| 8 | `deepl-next-gen` DeepL Next Gen | hosted-api | 78 | 可用 | measured | $27.50/M 字符 |
| 9 | `nllb-200-54b` NLLB-200 54.5B（开源权重） | self-hosted | 71 | 可用 | measured | 免费权重，按算力计 |
| 10 | `argos-translate-local` Argos Translate（本地 CTranslate2） | self-hosted | 66 | 可用 | measured | 免费 |

## 选型

- **当前主用**：`assemblyai-gateway-gemini-2-5-flash-lite`
- **达到条件后升级**：`google-translation-llm`, `gpt-5-6-terra`
- **回退**：`argos-translate-local`

主用 AssemblyAI LLM Gateway：同一把已配置的密钥、按 JSON 批返回、逐条对齐，是当前唯一在 3285 条 cue 上验证过的路径。Google Translation LLM 与 GPT-5.6 Terra 质量更高，但都需要新凭据，列为升级项；Google NMT 质量稳定、可复核性最好，适合作为对照基线。Argos 只做无密钥兜底，及格但不达标于质量目标。

## 逐维度得分

| 引擎 | 译文质量 | 英译中方向强度 | 字幕适配 | 成本 | 延迟与吞吐 | 可获得性 | 可复核性 | 总分 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `assemblyai-gateway-gemini-2-5-flash-lite` | 26 | 13 | 15 | 14 | 8 | 5 | 4 | 85 |
| `google-translation-llm` | 32 | 14 | 12 | 12 | 8 | 2 | 4 | 84 |
| `google-cloud-translation-nmt` | 31 | 15 | 11 | 11 | 9 | 2 | 5 | 84 |
| `gemini-3-1-pro` | 34 | 14 | 13 | 9 | 7 | 2 | 3 | 82 |
| `gpt-5-6-terra` | 34 | 14 | 14 | 8 | 7 | 2 | 3 | 82 |
| `microsoft-translator` | 28 | 13 | 11 | 12 | 9 | 2 | 5 | 80 |
| `qwen-mt-open` | 25 | 14 | 12 | 14 | 7 | 3 | 4 | 79 |
| `deepl-next-gen` | 33 | 13 | 12 | 6 | 8 | 2 | 4 | 78 |
| `nllb-200-54b` | 22 | 11 | 12 | 13 | 4 | 4 | 5 | 71 |
| `argos-translate-local` | 12 | 9 | 14 | 15 | 6 | 5 | 5 | 66 |

## 证据

### `assemblyai-gateway-gemini-2-5-flash-lite`

当前唯一已在 runner 上跑通 3285 条 cue 的路径：同一把 ASSEMBLYAI 密钥既能转写也能翻译，按 JSON 数组整批返回，逐条对齐不合并。短板是 flash-lite 属轻量模型，成语与长定语的处理不如旗舰模型；模型名可换，版本不锁定。

- 2026-10-27　LLM Gateway 支持 86 种目标语言，可批处理　<https://www.assemblyai.com/docs/speech-understanding/translation>
- 2026-10-27　Gemini 2.5 Pro 英中 COMET 88.01；flash-lite 低于该上限　<https://www.sota2.com/research/sota/machine-translation-xx-zh-on-flores-plus-latest-test>

### `google-translation-llm`

FLORES 英中方向的头部选手（Gemini 3 Pro COMET 88.13、spBLEU 33.81），中文是核心语言而非长尾。需要 GCP 服务账号；字幕逐条对应要靠提示词约束。

- 2026-10-27　Gemini 3 Pro spBLEU 33.81 / COMET 88.13　<https://www.sota2.com/research/sota/machine-translation-xx-zh-on-flores-plus-latest-test>
- 2026-10-27　Translation LLM $10/M 输入 + $10/M 输出　<https://cloud.google.com/translate/pricing>

### `google-cloud-translation-nmt`

FLORES 英中方向 spBLEU 36.08、COMET 88.24，是传统 NMT 里最强的一档；模型版本稳定、可复核性最好。整段 API 不保证逐条对应，需要按 cue 单发或做后对齐，吞吐成本会上升。

- 2026-10-27　Google Translate spBLEU 36.08 / COMET 88.24，榜首　<https://www.sota2.com/research/sota/machine-translation-xx-zh-on-flores-plus-latest-test>
- 2026-10-27　NMT $20/M 字符，每月 50 万字符免费　<https://cloud.google.com/translate/pricing>

### `gemini-3-1-pro`

与 GPT-5.6 Terra 同档；Intento 在多种语言上把它列为错误最少，FLORES 英中 COMET 88.13。需要 Google AI Studio 或 Vertex 密钥，字幕逐条对应同样依赖提示词。

- 2026-10-27　Gemini 3 Pro COMET 88.13，英中第一梯队　<https://www.sota2.com/research/sota/machine-translation-xx-zh-on-flores-plus-latest-test>
- 2026-10-27　多语言错误计数第一梯队　<https://inten.to/state-of-translation-automation/models/>

### `gpt-5-6-terra`

Intento 2026 在 80 种语言里，最佳 LLM 的错误数中位数只有最佳 MT 引擎的约 1/2.3；英中方向 GPT-4 系在编辑评分上领先 DeepL。字幕场景要靠提示词锁定逐条输出，且模型版本会滚动。

- 2026-10-27　最佳 LLM 错误数中位数约为最佳 MT 引擎的 1/2.3　<https://inten.to/state-of-translation-automation/models/>
- 2026-10-27　EN→ZH 编辑评分 GPT-4 8.1，DeepL 7.5　<https://nllb.com/translation-accuracy-leaderboard/>
- 2026-10-27　GPT-5.6 Terra 实测约 $4.54/M 字符　<https://inten.to/state-of-translation-automation/costs/list-price-on-measured-volume/>

### `microsoft-translator`

价格低、90 种语言、版本稳定；质量处于第二梯队，适合与 LLM 做交叉校验而不是单独定稿。

- 2026-10-27　Microsoft Translator $10/M 字符，90 种语言　<https://inten.to/state-of-translation-automation/costs/list-price-on-measured-volume/>

### `qwen-mt-open`

中文团队训练、中文方向强，权重可固定；FLORES 上低于商用头部（HY-MT1.5-7B spBLEU 23.59），需要 GPU 与自建服务。

- 2026-10-27　HY-MT1.5-7B 英中 spBLEU 23.59 / COMET 86.85　<https://www.sota2.com/research/sota/machine-translation-xx-zh-on-flores-plus-latest-test>

### `deepl-next-gen`

Intento 2026 里在 49 种语言上是最佳 MT 引擎，欧洲语言优势最大；英中方向不如 LLM，价格是全场最高档。适合作为术语一致性要求高的备选。

- 2026-10-27　DeepL Next Gen 在 49 种语言上为最佳 MT 引擎　<https://inten.to/state-of-translation-automation/models/>
- 2026-10-27　$27.50/M 字符，85 种语言　<https://inten.to/state-of-translation-automation/costs/list-price-on-measured-volume/>

### `nllb-200-54b`

200 种语言覆盖最广、完全可离线，但英中质量明显落后（COMET 80.64），且 54B 权重在 runner 上跑不动，只适合做低资源语言的兜底。

- 2026-10-27　NLLB-54.5B spBLEU 20.72 / COMET 80.64　<https://www.sota2.com/research/sota/machine-translation-xx-zh-on-flores-plus-latest-test>

### `argos-translate-local`

零密钥、零费用、逐条对应，3285 条 cue 在 runner 上能跑完；质量是全场最低档，只作为无网络/无密钥时的及格线兜底。此前一次流水线记录里的 84/100 是“可跑通性”评分，口径与本表不同，不具可比性。

- 2026-10-27　本地离线翻译，模型按语言对下载　<https://github.com/argosopentech/argos-translate>
