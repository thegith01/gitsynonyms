# ASR处：语音转写引擎研究与排名

> 评分口径 v1.0　数据更新 2026-10-27　及格线 60/100

本页由 `scripts/engine_registry.py markdown` 从 `docs/engines/data/asr.json` 生成；总分由评分表重算，不接受手填。每个分数都必须有可复核链接。

## 评分维度

| 维度 | 权重 | 计分口径 |
|---|---:|---|
| 转写准确率 | 30 | 以公开独立基准的 WER/CER 为准；干净语音与难音频分别看，不采信单一营销数字 |
| 中英语言覆盖 | 15 | 同时支持英语与简体中文为满分；仅英语或需二次翻译按比例扣分 |
| 逐词时间戳 | 15 | 原生逐词起止时间为满分；句级时间戳减半；无时间戳不得分 |
| 成本 | 15 | 按每音频小时公开价折算；自托管只计算力，不计许可证费 |
| 延迟与吞吐 | 10 | 批量转写 3 小时素材的端到端等待时间与并发能力 |
| 可获得性 | 10 | 仓库已有密钥/可直接调用为满分；需新开户或审批按缺口扣分 |
| 可复核性 | 5 | 有版本化模型、公开文档与可重跑命令；仅云端黑盒且条款禁止基准测试的扣分 |

## 排名

| 名次 | 引擎 | 类型 | 总分 | 结论 | 数据性质 | 成本 |
|---:|---|---|---:|---|---|---|
| 1 | `assemblyai-universal-3-5-pro` AssemblyAI Universal-3.5 Pro | hosted-api | 91 | 可用 | measured | $0.21/音频小时 |
| 2 | `elevenlabs-scribe-v2` ElevenLabs Scribe v2 | hosted-api | 86 | 可用 | measured | $0.22/音频小时 |
| 3 | `whisper-large-v3-selfhost` OpenAI Whisper large-v3（faster-whisper 自托管） | self-hosted | 81 | 可用 | measured | 免费权重，按算力计 |
| 4 | `deepgram-nova-3` Deepgram Nova-3 | hosted-api | 79 | 可用 | measured | $0.26–0.31/音频小时 |
| 5 | `speechmatics-linden-1` Speechmatics Linden-1 | hosted-api | 78 | 可用 | measured | 按合同 |
| 6 | `groq-whisper-large-v3-turbo` Groq Whisper large-v3-turbo | hosted-api | 77 | 可用 | estimated | 低 |
| 7 | `google-chirp-3` Google Cloud Speech-to-Text V2（Chirp 3） | hosted-api | 76 | 可用 | measured | $0.48/音频小时（标准识别） |
| 8 | `nvidia-parakeet-tdt-0-6b-v3` NVIDIA Parakeet TDT 0.6B v3 | self-hosted | 76 | 可用 | measured | 免费权重，按算力计 |
| 9 | `openai-gpt-4o-transcribe` OpenAI gpt-4o-transcribe | hosted-api | 69 | 可用 | measured | $0.36/音频小时 |

## 选型

- **当前主用**：`assemblyai-universal-3-5-pro`
- **达到条件后升级**：`elevenlabs-scribe-v2`
- **回退**：`whisper-large-v3-selfhost`

主用 AssemblyAI：仓库已有密钥、$0.21/hr、原生逐词时间戳，能直接喂给字幕时间轴。没有任何密钥时回退到 faster-whisper（99 语言、可离线），接受更慢的中文质量。Scribe v2 在结构化实体任务上更稳，等 ELEVENLABS 密钥到位后作为升级项；Deepgram 的公开 WER 分歧过大，只保留为实时场景备选。

## 逐维度得分

| 引擎 | 转写准确率 | 中英语言覆盖 | 逐词时间戳 | 成本 | 延迟与吞吐 | 可获得性 | 可复核性 | 总分 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `assemblyai-universal-3-5-pro` | 28 | 12 | 15 | 14 | 8 | 10 | 4 | 91 |
| `elevenlabs-scribe-v2` | 27 | 15 | 15 | 13 | 8 | 4 | 4 | 86 |
| `whisper-large-v3-selfhost` | 23 | 15 | 13 | 15 | 4 | 6 | 5 | 81 |
| `deepgram-nova-3` | 22 | 13 | 15 | 12 | 10 | 3 | 4 | 79 |
| `speechmatics-linden-1` | 26 | 14 | 14 | 9 | 8 | 3 | 4 | 78 |
| `groq-whisper-large-v3-turbo` | 22 | 15 | 11 | 13 | 10 | 2 | 4 | 77 |
| `google-chirp-3` | 24 | 15 | 13 | 9 | 8 | 3 | 4 | 76 |
| `nvidia-parakeet-tdt-0-6b-v3` | 20 | 6 | 14 | 15 | 10 | 6 | 5 | 76 |
| `openai-gpt-4o-transcribe` | 25 | 13 | 6 | 11 | 8 | 3 | 3 | 69 |

## 证据

### `assemblyai-universal-3-5-pro`

仓库已配置 ASSEMBLYAI 密钥，是当前唯一能直接跑通的主用引擎。独立基准：干净语音 WER 1.55%，难音频 WER 10.43%；结构化实体基准 WER 3.9% 但任务成功率中游，说明标点与实体格式仍需后处理。Universal-3.5 Pro 官方覆盖 18 种语言，中文可用但不如 99 语言的 Universal-2 宽。

- 2026-10-27　LibriSpeech 干净 1.55% / Earnings-22 难音频 10.43%　<https://github.com/verliapp/stt-benchmark>
- 2026-10-27　17 家系统中 WER 3.9%，任务成功率 50.3%　<https://openbenchmarks.com/structured-speech-to-text-benchmark>
- 2026-10-27　预录 $0.21/hr；逐词时间戳与置信度随转写返回　<https://www.assemblyai.com/pricing/>

### `elevenlabs-scribe-v2`

语言覆盖与逐词时间戳都强，结构化实体任务成功率 68.0%，明显高于 AssemblyAI 的 50.3%。仓库尚无 ELEVENLABS 密钥，接入前需要新增凭据。

- 2026-10-27　干净 1.99% / 难音频 15.44%　<https://github.com/verliapp/stt-benchmark>
- 2026-10-27　任务成功率 68.0%，WER 6.8%　<https://openbenchmarks.com/structured-speech-to-text-benchmark>
- 2026-10-27　Scribe v2 预录 $0.22/hr，含逐词时间戳　<https://infro.io/blog/speech-apis-compared-2026>

### `whisper-large-v3-selfhost`

99 种语言、权重公开、可离线，是没有任何密钥时的唯一可靠兜底；中文质量低于商业引擎，CPU 上 3 小时素材会非常慢，需要 GPU。

- 2026-10-27　开放 ASR 榜，Whisper large-v3 为对照基线　<https://huggingface.co/spaces/hf-audio/open_asr_leaderboard>
- 2026-10-27　任务成功率 53.3%，WER 5.9%　<https://openbenchmarks.com/structured-speech-to-text-benchmark>

### `deepgram-nova-3`

流式延迟最低、结构化实体任务成功率最高（71.0%），但公开 WER 分歧极大：干净语音 2.50%，部分独立测试给出 25% 级别的难音频结果。只适合作为实时场景备选，不适合作为 3 小时成片转写的主用。

- 2026-10-27　任务成功率 71.0%，WER 8.2%　<https://openbenchmarks.com/structured-speech-to-text-benchmark>
- 2026-10-27　Nova-3 平均 WER 25.3%，延迟最低　<https://gradium.ai/content/stt-api-benchmark-2026-latency-accuracy>

### `speechmatics-linden-1`

Pipecat 独立测试中语义 WER 0.96%，55+ 语言，逐词时间戳齐全；公开价不透明，接入需要商务流程。

- 2026-10-27　linden-1 池化语义 WER 0.96%，TTFS 中位 369ms　<https://github.com/pipecat-ai/stt-benchmark/>

### `groq-whisper-large-v3-turbo`

把 Whisper 权重跑在 LPU 上，速度极快、价格低，但仍是 Whisper 家族的中文上限，且需要 Groq 密钥。

- 2026-10-27　以 Whisper large-v3 的 WER 作为质量上限参考　<https://huggingface.co/spaces/hf-audio/open_asr_leaderboard>

### `google-chirp-3`

125 种语言，结构化实体任务成功率 58.0%。成本是 AssemblyAI 的两倍多，需要 GCP 服务账号。

- 2026-10-27　任务成功率 58.0%，WER 5.8%　<https://openbenchmarks.com/structured-speech-to-text-benchmark>
- 2026-10-27　Google Cloud 约 $0.48/hr 批量价　<https://www.assemblyai.com/blog/speech-to-text-api-pricing>

### `nvidia-parakeet-tdt-0-6b-v3`

RTFx 极高、显存需求小，但以英语为主，中文和多语场景不合格；适合做英语初稿的快速批处理。

- 2026-10-27　结构化实体任务成功率 39.3%，WER 11.4%　<https://openbenchmarks.com/structured-speech-to-text-benchmark>
- 2026-10-27　开放 ASR 榜 RTFx 与 WER 对照　<https://huggingface.co/spaces/hf-audio/open_asr_leaderboard>

### `openai-gpt-4o-transcribe`

干净语音最低 WER（1.47%），但难音频 18.55% 是前列引擎里最差的；逐词时间戳只在 whisper-1 上有文档，做逐词 ASS 会被这一条卡住。

- 2026-10-27　干净 1.47% / 难音频 18.55%　<https://github.com/verliapp/stt-benchmark>
- 2026-10-27　逐词时间戳仅 whisper-1 有文档；$0.36/hr　<https://www.cometapi.com/best-speech-to-text-apis/>
