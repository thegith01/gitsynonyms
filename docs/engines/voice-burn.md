# 语音刻录处：TTS 配音与音轨刻录引擎研究与排名

> 评分口径 v1.0　数据更新 2026-10-27　及格线 60/100

本页由 `scripts/engine_registry.py markdown` 从 `docs/engines/data/voice-burn.json` 生成；总分由评分表重算，不接受手填。每个分数都必须有可复核链接。

## 评分维度

| 维度 | 权重 | 计分口径 |
|---|---:|---|
| 中文自然度 | 25 | 普通话韵律、多音字、数字与专名读法；以盲听与母语审听为准 |
| 时间轴贴合 | 20 | 能否按 cue 起止压缩/拉伸、提供词边界或 SSML 语速控制；只能整段合成减半 |
| 音色与一致性 | 15 | 音色库规模、跨段落一致性、情感与语速标签 |
| 成本 | 15 | 按每百万字符公开价；自托管只计算力 |
| 延迟与吞吐 | 10 | 3 小时视频、数千条 cue 的批量合成耗时 |
| 可复核性 | 10 | 接口稳定、版本可固定、可离线复跑；非官方接口扣分 |
| 授权合规 | 5 | 服务条款允许批量合成与商用；catalogue voice 不涉及真人克隆 |

## 排名

| 名次 | 引擎 | 类型 | 总分 | 结论 | 数据性质 | 成本 |
|---:|---|---|---:|---|---|---|
| 1 | `azure-ai-speech-neural` Azure AI Speech（Neural TTS） | hosted-api | 84 | 可用 | measured | 约 $15/M 字符（标准神经网络音色） |
| 2 | `cosyvoice-3-dub` Fun-CosyVoice 3.0（自托管配音） | self-hosted | 82 | 可用 | measured | 免费权重，单卡可跑 |
| 3 | `edge-tts` edge-tts（Microsoft Edge 朗读接口） | free-endpoint | 82 | 可用 | measured | 免费 |
| 4 | `minimax-speech-2-6` MiniMax Speech 2.6 | hosted-api | 75 | 可用 | vendor-claimed | 低 |
| 5 | `elevenlabs-flash-v2-5` ElevenLabs Flash v2.5 / Eleven v3 | hosted-api | 73 | 可用 | measured | 按 credit，单价高 |
| 6 | `google-chirp-3-hd` Google Cloud TTS（Chirp 3 HD） | hosted-api | 71 | 可用 | measured | 中高 |
| 7 | `kokoro-82m` Kokoro-82M | self-hosted | 67 | 可用 | measured | 免费权重，CPU 可跑 |
| 8 | `openai-gpt-4o-mini-tts` OpenAI gpt-4o-mini-tts | hosted-api | 65 | 可用 | vendor-claimed | 低 |
| 9 | `playht-play-3-0` PlayHT Play 3.0 | hosted-api | 64 | 可用 | vendor-claimed | 订阅制 |

## 选型

- **当前主用**：`edge-tts`
- **达到条件后升级**：`azure-ai-speech-neural`
- **离线兜底**：`cosyvoice-3-dub`

当前主用 edge-tts，因为它是仓库里已经跑通的零密钥路径（`scripts/tts_dub.py` + `tts-dub.yml`），中文音色自然、按 cue 的 rate 控制够用。长期应升级到 Azure AI Speech：音色同源、有 SLA、SSML 与 word boundary 能直接做时长对齐，只差一把密钥。CosyVoice 作为离线兜底，与克隆处共用权重。OpenAI 与 Kokoro 缺中文能力，PlayHT 价格结构不适合按条计费的成片流程。

## 逐维度得分

| 引擎 | 中文自然度 | 时间轴贴合 | 音色与一致性 | 成本 | 延迟与吞吐 | 可复核性 | 授权合规 | 总分 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `azure-ai-speech-neural` | 23 | 20 | 14 | 8 | 8 | 6 | 5 | 84 |
| `cosyvoice-3-dub` | 23 | 16 | 13 | 10 | 5 | 10 | 5 | 82 |
| `edge-tts` | 22 | 18 | 13 | 15 | 8 | 3 | 3 | 82 |
| `minimax-speech-2-6` | 24 | 15 | 13 | 8 | 7 | 4 | 4 | 75 |
| `elevenlabs-flash-v2-5` | 24 | 14 | 14 | 4 | 9 | 4 | 4 | 73 |
| `google-chirp-3-hd` | 22 | 14 | 13 | 5 | 7 | 5 | 5 | 71 |
| `kokoro-82m` | 14 | 8 | 10 | 15 | 9 | 6 | 5 | 67 |
| `openai-gpt-4o-mini-tts` | 18 | 10 | 12 | 10 | 7 | 4 | 4 | 65 |
| `playht-play-3-0` | 20 | 12 | 12 | 6 | 6 | 4 | 4 | 64 |

## 证据

### `azure-ai-speech-neural`

官方接口，SSML 可控制语速/停顿/音高，并提供 word boundary 事件，可按 cue 做时长对齐；中文神经音色数量与稳定性是商业方案里最好的。与 edge-tts 同源音色，但从非官方接口换成有 SLA 的正规授权。

- 2026-10-27　SSML 语速/停顿控制与 word boundary 事件　<https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech>
- 2026-10-27　神经网络语音按字符计费　<https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/>

### `cosyvoice-3-dub`

与语音克隆处共用一套权重：既能用内置音色，也能用已授权音色；Apache-2.0、可离线、发音可用拼音修补。时长控制要靠外部按 cue 重排，不如 SSML 直接。

- 2026-10-27　拼音/CMU 音素修补发音，150ms 双流式　<https://github.com/FunAudioLLM/CosyVoice>

### `edge-tts`

仓库现有 `tts_dub.py` 与 `tts-dub.yml` 就是这条路径：免费、零密钥、中文音色自然，SSML 的 rate 能对 cue 做粗对齐。风险是它并非公开商用 API，接口随时可能变，条款也不保证批量合成，因此只作为默认可跑方案而不是长期主用。

- 2026-10-27　非官方客户端，音色清单随 Edge 服务变化　<https://github.com/rany2/edge-tts>
- 2026-10-27　仓库自述仅供学习交流，不保证商用授权　<https://github.com/rany2/edge-tts>

### `minimax-speech-2-6`

普通话与粤语保真度是主要卖点，价格低、有免费额度；时间轴控制以语速参数为主，缺逐词边界，长片对齐全靠后处理。

- 2026-10-27　亚洲语言保真度与低价定位　<https://www.veed.io/learn/best-voice-cloning-apis>

### `elevenlabs-flash-v2-5`

自然度与情感标签最强，70+ 语言；但按字符计费在 3 小时成片上成本高，且中文长句的断句需要额外提示。

- 2026-10-27　按 credit 计费，商用需相应套餐　<https://elevenlabs.io/pricing>
- 2026-10-27　Eleven v4 Turbo 盲听 Elo 1335，第一　<https://haass.io/blog/best-tts-for-voice-agents>

### `google-chirp-3-hd`

多语言覆盖广、音质稳定，SSML 支持完整；中文音色的口语感略逊于 Azure/MiniMax，价格偏高。

- 2026-10-27　Chirp 3 HD 按字符计价，高于标准音色　<https://cloud.google.com/text-to-speech/pricing>

### `kokoro-82m`

82M 参数、极低算力、英语质量接近商业档；中文支持弱，只适合英语旁白或草稿试听。

- 2026-10-27　82M 参数，Apache-2.0　<https://huggingface.co/hexgrad/Kokoro-82M>

### `openai-gpt-4o-mini-tts`

可以用自然语言指令控制语气，英文表现好；中文音色与韵律不是强项，且不提供逐词边界，字幕对齐要自己做。

- 2026-10-27　指令式语气控制；无公开词边界接口　<https://platform.openai.com/docs/guides/text-to-speech>

### `playht-play-3-0`

长文旁白与双人对白见长，Creator 套餐可包月不限量；中文不是其主战场。

- 2026-10-27　Creator 套餐包月不限量，长文旁白定位　<https://www.veed.io/learn/best-voice-cloning-apis>
