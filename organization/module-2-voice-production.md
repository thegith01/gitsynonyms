# 语音制作司

## 隶属

模块2：视频处理部下属，2026-10-27 由总控设立。语音刻录处与语音克隆处均归属本司。

```text
模块2：视频处理部（部级）
└── 语音制作司
    ├── 语音刻录处
    │   ├── 音色科
    │   └── 混音科
    └── 语音克隆处
        ├── 授权科
        └── 克隆科
```

## 为什么是一个司

两处做的是同一件事的两端：把**文字**变成**声音**，再按字幕时间轴刻进视频。

- 共用资产：音色清单、发音词典、采样率与响度标准；
- 共用时间轴：都以字幕 cue 的起止时间作为对齐基准；
- 共用混音链路：原声保留比例、闪避、限幅。

但两者的合规边界完全不同，所以必须分成两个处：刻录处只用**音色库**里的声音，
克隆处才会复刻**特定人**的音色，后者需要书面授权与同意书闸门。

## 语音刻录处

### 职责

把已定稿的中文字幕用音色库合成语音，按 cue 时间轴对齐后混入原声，输出配音版 MP4。
不涉及任何真人音色复刻。

### 评分口径（100 分）

| 维度 | 权重 | 关注点 |
|---|---:|---|
| 中文自然度 | 25 | 普通话韵律、多音字、数字与专名读法 |
| 时间轴贴合 | 20 | 能否按 cue 压缩/拉伸、有无词边界或 SSML 语速控制 |
| 音色与一致性 | 15 | 音色库规模、跨段落一致性、情感标签 |
| 成本 | 15 | 每百万字符 |
| 延迟与吞吐 | 10 | 数千条 cue 的批量合成耗时 |
| 可复核性 | 10 | 接口稳定、版本可固定、可离线 |
| 授权合规 | 5 | 条款允许批量合成与商用 |

当前排名（完整表见 [`docs/engines/voice-burn.md`](../docs/engines/voice-burn.md)）：

| 名次 | 引擎 | 总分 | 结论 |
|---:|---|---:|---|
| 1 | Azure AI Speech（Neural TTS） | 84 | 达到条件后升级 |
| 2 | Fun-CosyVoice 3.0（自托管） | 82 | 离线兜底 |
| 3 | edge-tts | 82 | 当前主用（零密钥） |
| 4 | MiniMax Speech 2.6 | 75 | 备选 |
| 5 | ElevenLabs Flash v2.5 | 73 | 质量优先场景 |

选型说明：`primary` 记的是**当前可部署**的 edge-tts，而不是分数最高的 Azure——
因为 Azure 需要一把尚未配置的密钥。Azure 一旦接入即应替换主用位；CosyVoice 作为
无网络兜底。三者的取舍写在 `docs/engines/data/voice-burn.json` 的 `selection.reason`。

### 实现

| 环节 | 实现 |
|---|---|
| 逐 cue 合成与混音 | `scripts/tts_dub.py`（edge-tts，按 cue 起止与 rate 控制） |
| 工作流 | `.github/workflows/tts-dub.yml`（从 Release 取成片 → 配音 → 回传） |
| 排名与校验 | `scripts/engine_registry.py rank --office voice-burn` |

## 语音克隆处

### 职责

研究并执行**零样本声音克隆**：用一段参考音频复刻音色，合成新的台词。仅服务两类对象：

1. 本人（自我克隆）；
2. 已签署书面授权的受聘配音员。

`scripts/voice_clone_dub.py` 在缺少同意书时直接拒绝运行，并默认在片头加入可听的
“合成语音”提示音。本处不下载、不分发模型权重，只通过 `--backend-command` 调用
本地零样本 TTS 后端。

### 评分口径（100 分）

| 维度 | 权重 | 关注点 |
|---|---:|---|
| 音色相似度 | 30 | 盲听相似度或说话人相似度 SS |
| 中英与跨语种 | 20 | 中文、英语都能克隆且跨语种 |
| 自然度与韵律 | 15 | 长句韵律、停顿、情感 |
| 成本 | 10 | 每千字符或每分钟 |
| 延迟 | 5 | 首包与批量速度 |
| 授权与合规 | 10 | 强制同意校验、水印、可删除、可本地部署 |
| 可复核性 | 10 | 权重可下载、版本可固定、可离线复跑 |

当前排名（完整表见 [`docs/engines/voice-clone.md`](../docs/engines/voice-clone.md)）：

| 名次 | 引擎 | 总分 | 结论 |
|---:|---|---:|---|
| 1 | Fun-CosyVoice 3.0（Apache-2.0） | 90 | 主用 |
| 2 | Fish Audio S2 Pro | 88 | 升级项（盲听相似度第一） |
| 3 | ElevenLabs Multilingual v2 | 81 | 质量基准 |
| 4 | Inworld TTS-2 | 77 | 音质优先 |
| 5 | Cartesia Sonic 3.6 | 75 | 实时场景 |

选型：**CosyVoice 3**。Apache-2.0 代码与权重、中文相似度 78.0 高于人类参考线、
9 语言 + 18 方言、可完全离线，配合同意书闸门能形成可审计链路。Fish Audio S2 Pro
盲听相似度更高（4.03/5），但需要云端密钥与所有权校验，列为升级项。

### 实现

| 环节 | 实现 |
|---|---|
| 同意书闸门与合成 | `scripts/voice_clone_dub.py` |
| 后端占位 | `--backend-command 'python /opt/CosyVoice/api.py --ref {ref} --text {text} --out {out}'` |
| 排名与校验 | `scripts/engine_registry.py rank --office voice-clone` |

## 合规红线（强制）

1. **不得克隆 White House 素材中的任何真人声音**。钦定素材里出现的是公职人员，
   没有书面授权，克隆即违规。
2. 克隆前必须存在同意书 JSON：`speaker_name`、`relationship`、`authorised: true`、
   `evidence`、`valid_until`；字段不全视为未授权。
3. 输出默认带合成语音提示音；关闭提示音需要单独审批并记录。
4. 克隆产物不得标注为“原声”，也不得用于误导性语境。
5. 违反本条按最高指示 3.6 第 4 款处理：隐瞒按 P0，降级按 P1。

## 复核方式

```bash
python scripts/engine_registry.py check
python scripts/engine_registry.py rank --office voice-burn
python scripts/engine_registry.py rank --office voice-clone
python scripts/engine_registry.py markdown --office voice-burn --write
python scripts/engine_registry.py markdown --office voice-clone --write
```

## 未完成与限制

- `tts-dub.yml` 只做到“配音 + 回传 Release”，没有接入主发布链，也不是双语交付的一部分；
- `voice_clone_dub.py` 尚未接入任何 workflow，也没有在 runner 上跑过真实克隆；
- CosyVoice 的部署脚本、显存要求与合成时长尚未在 runner 上实测；
- 语音刻录处与字幕刻录的混音标准（原声比例、响度）还没有写成可执行参数。
