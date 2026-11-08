/*
 * GitSynonyms flow composer data.
 *
 * Every module is an independent, optional step. A module owns its options and
 * its command builder, so adding a step means adding one object here and the
 * page renders it, validates it and includes it in the generated runbook.
 */
(() => {
  "use strict";

  const REPO_DEFAULT = "gitsynonyms/gitsynonyms";
  const PY_SETUP =
    "$py = Join-Path $env:USERPROFILE 'anaconda3\\envs\\a\\python.exe'";

  function psQuote(value) {
    return `'${String(value).replaceAll("'", "''")}'`;
  }

  function ghValue(value) {
    if (value === true) return "true";
    if (value === false) return "false";
    return String(value);
  }

  function gh(ctx, workflow, inputs = {}) {
    const parts = [
      `gh workflow run ${workflow}`,
      `--repo ${ctx.repo}`,
      "--ref main",
    ];
    for (const [key, value] of Object.entries(inputs)) {
      if (value === undefined || value === null || value === "") continue;
      parts.push(`-f ${psQuote(`${key}=${ghValue(value)}`)}`);
    }
    return parts.join(" ");
  }

  function videoRef(ctx) {
    return ctx.id || "<video-id>";
  }

  function localStep(code, note, warnings = []) {
    return { kind: "local", setup: PY_SETUP, code, note, warnings };
  }

  const GROUPS = [
    {
      id: "observe",
      kicker: "01 / OBSERVE",
      title: "监测与探测",
      summary: "先确认有没有新素材、有没有字幕轨；这些步骤不改动成片。",
    },
    {
      id: "produce",
      kicker: "02 / PRODUCE",
      title: "流水线与字幕",
      summary: "自动全链、本机字幕流程与离线 ASS 重建；按需要只选一个。",
    },
    {
      id: "finish",
      kicker: "03 / FINISH",
      title: "成片与声音",
      summary: "重刻双语 1080p，或从已刻录成片生成中文配音。",
    },
    {
      id: "publish",
      kicker: "04 / PUBLISH",
      title: "发布与治理",
      summary: "备份核对、网页预览、站点重发与发布前校验。",
    },
  ];

  const MODULES = [
    {
      id: "monitor",
      group: "observe",
      title: "白宫频道监测",
      summary:
        "每 5 分钟扫描 White House 的 /videos 与 /streams；发现新片后触发自动流水线。",
      kind: "cloud",
      requiresVideo: false,
      meta: ["5 分钟节律", "自动触发", "可指定单条"],
      options: [
        {
          key: "includeStreams",
          label: "同时扫描 /streams 直播页",
          type: "checkbox",
          default: true,
        },
        {
          key: "forceCheck",
          label: "重处理最近一条（force_check）",
          type: "checkbox",
          default: false,
        },
        {
          key: "onlyThisVideo",
          label: "只处理公共参数中的视频 ID",
          type: "checkbox",
          default: false,
        },
      ],
      build(ctx) {
        const inputs = {
          include_streams: ctx.opts.includeStreams,
          force_check: ctx.opts.forceCheck,
        };
        if (ctx.opts.onlyThisVideo && ctx.id) inputs.video_id = ctx.id;
        const warnings = [];
        if (ctx.opts.onlyThisVideo && !ctx.id) {
          warnings.push("勾选“只处理此视频”后，需要在公共参数中填写视频 ID。");
        }
        return {
          kind: "cloud",
          code: gh(ctx, "monitor-whitehouse.yml", inputs),
          note: "手动启动只跑一次；定时节律仍由 workflow 的 5 分钟 schedule 控制。",
          warnings,
        };
      },
    },
    {
      id: "probe",
      group: "observe",
      title: "字幕探测",
      summary:
        "只列出 YouTube 字幕轨，并尝试下载中英七种格式；用来判断是否需要 ASR。",
      kind: "cloud",
      requiresVideo: true,
      meta: ["只读", "七种格式"],
      options: [],
      build(ctx) {
        return {
          kind: "cloud",
          code: gh(ctx, "caption-probe.yml", { video_id: videoRef(ctx) }),
          note: "探测失败是暂时错误；本机流程会中止，不会直接转付费 ASR。",
          warnings: ctx.id ? [] : ["字幕探测需要视频 ID。"],
        };
      },
    },
    {
      id: "proxy",
      group: "observe",
      title: "代理池重建",
      summary:
        "重建三层公共代理池；直连被 YouTube 拦截时，先刷新 tier 3 再下载。",
      kind: "cloud",
      requiresVideo: false,
      meta: ["按需", "不产生成片"],
      options: [
        {
          key: "tier",
          label: "重建层级",
          type: "select",
          default: "3",
          choices: [
            { value: "3", label: "tier 3 · yt-dlp 实测通过" },
            { value: "2", label: "tier 2 · HTTPS 最快 10,000" },
            { value: "1", label: "tier 1 · 全量收集" },
            { value: "all", label: "all · 三层依次重建" },
          ],
          hint: "tier 3 最贴近真实下载，通常只跑这一层。",
        },
      ],
      build(ctx) {
        return {
          kind: "cloud",
          code: gh(ctx, "proxy-pool.yml", { tier: ctx.opts.tier }),
          note: "代理池存放在 Actions 缓存，不写入 git；仓库里只保留 bootstrap 列表。",
        };
      },
    },
    {
      id: "pipeline",
      group: "produce",
      title: "自动流水线（全链）",
      summary:
        "事件核验 → 素材排序 → 下载 → 七格式字幕 → ASR/翻译兜底 → ASS → 1080p 刻录 → 备份 → 发布。",
      kind: "cloud",
      requiresVideo: true,
      meta: ["推荐", "全自动", "含发布"],
      options: [
        {
          key: "mode",
          label: "流水线阶段",
          type: "select",
          default: "full",
          choices: [
            { value: "probe", label: "probe · 核验 / 排名 / 探测字幕" },
            { value: "test", label: "test · 小样测试" },
            { value: "full", label: "full · 完整处理与发布" },
          ],
          hint: "probe 不下载成片，也不会刻录。",
        },
        {
          key: "minHeight",
          label: "最低源分辨率",
          type: "select",
          default: "1080",
          choices: [
            { value: "1080", label: "1080p（规则下限）" },
            { value: "1440", label: "1440p" },
            { value: "2160", label: "2160p / 4K" },
          ],
          hint: "低于 1080p 属于降级，必须在交付报告中声明。",
        },
        {
          key: "publish",
          label: "完成后发布 Release 与 Pages",
          type: "checkbox",
          default: true,
        },
        {
          key: "forceAsr",
          label: "强制 ASR（跳过 YouTube 字幕）",
          type: "checkbox",
          default: false,
        },
      ],
      build(ctx) {
        const inputs = {
          video_id: videoRef(ctx),
          mode: ctx.opts.mode,
          min_height: ctx.opts.minHeight,
        };
        if (ctx.opts.mode !== "probe") {
          inputs.publish = ctx.opts.publish;
          inputs.force_asr = ctx.opts.forceAsr;
        }
        if (ctx.title) inputs.title = ctx.title;
        if (ctx.eventDate) inputs.event_date = ctx.eventDate;
        if (ctx.sourceUrl) inputs.source_url = ctx.sourceUrl;
        return {
          kind: "cloud",
          code: gh(ctx, "auto-pipeline.yml", inputs),
          note:
            "这条 workflow 已包含下载、字幕、ASS、刻录、Release/page 与 filebin 备份；无需再单独选刻录模块。",
          warnings: ctx.id ? [] : ["自动流水线需要视频 ID。"],
        };
      },
    },
    {
      id: "localcaptions",
      group: "produce",
      title: "本地字幕流程",
      summary:
        "在已下载媒体的目录里运行八种来源组合；只取字幕或音频，不下载视频。",
      kind: "local",
      requiresVideo: false,
      meta: ["8 种预设", "Scheme 1 默认", "本机"],
      options: [
        {
          key: "preset",
          label: "来源组合",
          type: "select",
          default: "local-youtube-official",
          choices: [
            {
              value: "local-youtube-official",
              label: "本地媒体 · 官方英文 + 官方中文",
            },
            {
              value: "local-youtube-mt",
              label: "本地媒体 · 官方英文 + 机器中文",
            },
            {
              value: "local-asr-mt",
              label: "本地媒体 · ASR 英文 + 机器中文",
            },
            {
              value: "local-asr-official",
              label: "本地媒体 · ASR 英文 + 官方中文",
            },
            {
              value: "url-youtube-official",
              label: "仅 URL · 官方英文 + 官方中文",
            },
            {
              value: "url-youtube-mt",
              label: "仅 URL · 官方英文 + 机器中文",
            },
            {
              value: "offline-official",
              label: "离线 · 已有英文 + 已有中文",
            },
            {
              value: "offline-mt",
              label: "离线 · 已有英文 + 机器中文",
            },
          ],
          hint: "带 mt 的预设会把中文替换为机器翻译。",
        },
        {
          key: "assMode",
          label: "ASS 方案",
          type: "select",
          default: "scheme1",
          choices: [
            { value: "scheme1", label: "Scheme 1 · 自研时间轴（默认）" },
            { value: "fused", label: "fused · 七格式句子时间轴" },
            { value: "immersive-lowest", label: "immersive-lowest · 对照基线" },
          ],
          hint: "Scheme 1 需要官方中文；机器翻译只在 fused 路径生效。",
        },
        {
          key: "asrEngine",
          label: "ASR 引擎",
          type: "select",
          default: "auto",
          showWhen: (options) => options.preset.includes("asr"),
          choices: [
            { value: "auto", label: "auto · 有密钥用 AssemblyAI，否则 whisper" },
            { value: "assemblyai", label: "assemblyai · 词级时间" },
            { value: "whisper", label: "whisper · 本地 faster-whisper" },
          ],
        },
        {
          key: "translationEngine",
          label: "机器翻译引擎",
          type: "select",
          default: "auto",
          showWhen: (options) => options.preset.includes("mt"),
          choices: [
            { value: "auto", label: "auto · 有密钥用 AssemblyAI，否则 Argos" },
            { value: "assemblyai", label: "assemblyai · 网关" },
            { value: "argos", label: "argos · 本地" },
            { value: "mymemory", label: "mymemory · 在线" },
          ],
        },
      ],
      build(ctx) {
        const preset = ctx.opts.preset;
        const offline = preset.startsWith("offline");
        const args = ["scripts\\local_subtitle_flow.py"];
        if (offline) {
          args.push("--video-id", psQuote(videoRef(ctx)));
        } else {
          args.push("--url", psQuote(ctx.url || `https://youtu.be/${videoRef(ctx)}`));
        }
        args.push("--directory", psQuote(ctx.outDir));
        args.push("--preset", preset);
        args.push("--ass-mode", ctx.opts.assMode);
        if (preset.includes("asr") && ctx.opts.asrEngine !== "auto") {
          args.push("--asr-engine", ctx.opts.asrEngine);
        }
        if (preset.includes("mt") && ctx.opts.translationEngine !== "auto") {
          args.push("--translation-engine", ctx.opts.translationEngine);
        }

        const warnings = [];
        if (offline && !ctx.id) {
          warnings.push("离线预设需要视频 ID，用来在目录中定位字幕文件。");
        }
        if (!offline && !ctx.id) {
          warnings.push("在线预设需要视频 URL 或 11 位 ID。");
        }
        if (preset.includes("mt") && ctx.opts.assMode !== "fused") {
          warnings.push(
            "机器翻译预设应与 fused 组合；Scheme 1 / immersive-lowest 不会用机器翻译替代官方中文。",
          );
        }

        const schemeNotes = {
          scheme1:
            "Scheme 1 以英文 SRT 为显示时间轴，要求官方自动翻译中文；缺失会失败而不是静默改用机器翻译。",
          fused:
            "fused 使用七格式融合的句子时间轴；只有这条路径允许机器翻译补齐中文。",
          "immersive-lowest":
            "immersive-lowest 是对照基线；要求 en-orig 自动英文与官方自动翻译中文，缺一即失败。",
        };

        return localStep(
          `& $py -X utf8 ${args.join(" ")}`,
          `${schemeNotes[ctx.opts.assMode]} 媒体应已存在于输出目录；本机流程不会下载视频。`,
          warnings,
        );
      },
    },
    {
      id: "ass",
      group: "produce",
      title: "离线 ASS 重建",
      summary:
        "使用目录里已有的七格式字幕重建 ASS，不联网；适合反复调整样式与时间轴。",
      kind: "local",
      requiresVideo: false,
      meta: ["离线", "已有字幕", "本机"],
      options: [
        {
          key: "builder",
          label: "重建方式",
          type: "select",
          default: "scheme1",
          choices: [
            { value: "scheme1", label: "Scheme 1 · 英文 SRT 时间轴" },
            { value: "fused", label: "fused · 七格式融合" },
          ],
          hint: "两种方式都读取同一目录下的官方字幕文件。",
        },
      ],
      build(ctx) {
        const warnings = [];
        let args;
        if (ctx.opts.builder === "scheme1") {
          args = [
            "scripts\\scheme1_local_ass.py",
            "--directory",
            psQuote(ctx.outDir),
            "--video-id",
            psQuote(videoRef(ctx)),
          ];
          if (!ctx.id) warnings.push("Scheme 1 重建需要视频 ID。");
        } else {
          args = [
            "scripts\\local_bilingual_ass.py",
            "--directory",
            psQuote(ctx.outDir),
            "--max-lines",
            "1",
          ];
          if (ctx.id) args.push("--video-id", psQuote(ctx.id));
        }
        return localStep(
          `& $py -X utf8 ${args.join(" ")}`,
          "目录中需要已有十四份字幕文件（每语言七种格式）；本步骤不访问 YouTube。",
          warnings,
        );
      },
    },
    {
      id: "burn",
      group: "finish",
      title: "单条重刻",
      summary:
        "从 filebin 或直链取回源片，补翻译后重刻双语 1080p，并把交付物回传到同一备份。",
      kind: "cloud",
      requiresVideo: true,
      meta: ["1080p", "Release", "可重跑"],
      options: [
        {
          key: "stage",
          label: "刻录阶段",
          type: "select",
          default: "full",
          choices: [
            { value: "full", label: "full · 翻译并刻录" },
            { value: "translate-test", label: "translate-test · 只测翻译" },
          ],
          hint: "translate-test 不下载视频，也不产出成片。",
        },
        {
          key: "crf",
          label: "libx264 CRF",
          type: "number",
          default: "30",
          min: 18,
          max: 40,
          step: 1,
          hint: "越低画质越好、文件越大；默认 30。",
        },
        {
          key: "publish",
          label: "完成后发布 Release 与 Pages",
          type: "checkbox",
          default: true,
        },
      ],
      build(ctx) {
        const inputs = {
          video_id: videoRef(ctx),
          stage: ctx.opts.stage,
          crf: ctx.opts.crf,
        };
        if (ctx.opts.stage === "full") inputs.publish = ctx.opts.publish;
        if (ctx.sourceUrl) inputs.source_url = ctx.sourceUrl;
        if (ctx.title) inputs.title = ctx.title;
        if (ctx.eventDate) inputs.event_date = ctx.eventDate;

        const warnings = [];
        if (!ctx.id) warnings.push("重刻需要视频 ID。");
        if (
          ctx.opts.stage === "full" &&
          !ctx.sourceUrl &&
          ctx.id !== "9aPyO1jfDGM"
        ) {
          warnings.push(
            "source_url 为空时 workflow 会使用默认示例地址（9aPyO1jfDGM），与当前视频不匹配。请在高级参数填写源片直链。",
          );
        }
        return {
          kind: "cloud",
          code: gh(ctx, "module2-burn.yml", inputs),
          note:
            "重刻读取已备份的源片，不会重新监测频道；完成后仍走 Release + Pages + filebin 备份。",
          warnings,
        };
      },
    },
    {
      id: "tts",
      group: "finish",
      title: "语音配音",
      summary:
        "从 Release 读取已刻录成片，按字幕合成中文配音并混音；不修改字幕。",
      kind: "cloud",
      requiresVideo: true,
      meta: ["edge-tts", "非克隆", "需已成片"],
      options: [
        {
          key: "voice",
          label: "配音音色",
          type: "select",
          default: "zh-CN-XiaoxiaoNeural",
          choices: [
            { value: "zh-CN-XiaoxiaoNeural", label: "晓晓 · 女声（默认）" },
            { value: "zh-CN-YunxiNeural", label: "云希 · 男声" },
            { value: "zh-CN-YunyangNeural", label: "云扬 · 男声 · 新闻" },
            { value: "zh-CN-XiaoyiNeural", label: "晓伊 · 女声 · 活泼" },
          ],
        },
        {
          key: "originalGain",
          label: "原声保留比例",
          type: "number",
          default: "0.25",
          min: 0,
          max: 1,
          step: 0.05,
          hint: "0 = 只保留配音；1 = 原声不衰减。",
        },
        {
          key: "rate",
          label: "语速",
          type: "text",
          default: "+0%",
          hint: "例如 +0%、-10%、+15%。",
        },
      ],
      build(ctx) {
        const inputs = {
          video_id: videoRef(ctx),
          voice: ctx.opts.voice,
          original_gain: ctx.opts.originalGain,
          rate: ctx.opts.rate,
        };
        return {
          kind: "cloud",
          code: gh(ctx, "tts-dub.yml", inputs),
          note:
            "读取 Release 里的 Burned_Bilingual_<id>.mp4；请先完成刻录并确保资产已上传。",
          warnings: ctx.id ? [] : ["语音配音需要视频 ID。"],
        };
      },
    },
    {
      id: "backupcheck",
      group: "publish",
      title: "备份核对",
      summary:
        "只读检查 Release 资产是否已存在；filebin 备份在云端运行记录中核对。",
      kind: "cloud",
      requiresVideo: true,
      meta: ["只读", "发布前", "Release"],
      options: [],
      build(ctx) {
        return {
          kind: "cloud",
          code: `gh release view ${psQuote(videoRef(ctx))} --repo ${ctx.repo}`,
          note:
            "发布顺序固定为：先刻录、再备份、最后发布；缺少 Release 或 filebin 任一份都不得发布。",
          warnings: ctx.id ? [] : ["备份核对需要视频 ID（Release tag）。"],
        };
      },
    },
    {
      id: "preview",
      group: "publish",
      title: "网页预览",
      summary:
        "从 Release 成片抽样 720p 预览与海报，并重新生成站点；预览必须小于 40 MB。",
      kind: "cloud",
      requiresVideo: true,
      meta: ["< 40 MB", "自动提交", "需已成片"],
      options: [
        {
          key: "segments",
          label: "抽样段数",
          type: "number",
          default: "3",
          min: 1,
          max: 12,
          step: 1,
        },
        {
          key: "seconds",
          label: "每段秒数",
          type: "number",
          default: "30",
          min: 5,
          max: 120,
          step: 5,
        },
        {
          key: "commit",
          label: "提交预览与重新生成的站点",
          type: "checkbox",
          default: true,
        },
      ],
      build(ctx) {
        const inputs = {
          video_id: videoRef(ctx),
          segments: ctx.opts.segments,
          seconds: ctx.opts.seconds,
          commit: ctx.opts.commit,
        };
        return {
          kind: "cloud",
          code: gh(ctx, "make-preview.yml", inputs),
          note:
            "预览指向 site/media/ 里的小文件；不要把 <video> 直接指向多 GB 的 Release 资产。",
          warnings: ctx.id ? [] : ["网页预览需要视频 ID。"],
        };
      },
    },
    {
      id: "republish",
      group: "publish",
      title: "站点重发",
      summary:
        "只根据已提交的 output/ 档案重建 site/，不触碰媒体；Jekyll 仍是唯一 Pages 出口。",
      kind: "cloud",
      requiresVideo: false,
      meta: ["Jekyll", "无媒体", "可重跑"],
      options: [],
      build(ctx) {
        return {
          kind: "cloud",
          code: gh(ctx, "republish-site.yml"),
          note:
            "本模块只提交重新生成的站点；部署仍由 Jekyll Pages workflow 负责，不调用 deploy-pages。",
        };
      },
    },
    {
      id: "verify",
      group: "publish",
      title: "发布前校验",
      summary:
        "在云端运行 pytest 与资源、巡检、组织、发布登记四项检查；不通过不发布。",
      kind: "cloud",
      requiresVideo: false,
      meta: ["pytest", "四项登记", "云端"],
      options: [],
      build(ctx) {
        return {
          kind: "cloud",
          code: gh(ctx, "infogap.yml", { tests_only: true }),
          note:
            "测试一律在云端 runner 执行；本机不跑测试，确需 Python 时只使用 Anaconda a 环境。",
        };
      },
    },
  ];

  // Execution order is independent of the library grouping. Validation runs
  // before the expensive chain; monitoring/probing are prep; publishing blocks
  // stay at the end.
  const EXECUTION_ORDER = [
    "verify",
    "monitor",
    "probe",
    "proxy",
    "pipeline",
    "localcaptions",
    "ass",
    "burn",
    "tts",
    "backupcheck",
    "preview",
    "republish",
  ];

  const PRESETS = [
    {
      id: "cloud-full",
      title: "云端全流程",
      tag: "推荐",
      summary: "校验 → 自动全链 → 备份核对 → 网页预览",
      modules: {
        verify: { enabled: true },
        pipeline: {
          enabled: true,
          options: {
            mode: "full",
            minHeight: "1080",
            publish: true,
            forceAsr: false,
          },
        },
        backupcheck: { enabled: true },
        preview: { enabled: true },
      },
    },
    {
      id: "cloud-probe",
      title: "单条探测",
      tag: "只读",
      summary: "只核验字幕轨与七格式，不下载成片",
      modules: {
        probe: { enabled: true },
      },
    },
    {
      id: "cloud-monitor",
      title: "监测触发",
      tag: "定时",
      summary: "每 5 分钟发现新片并自动进入流水线",
      modules: {
        monitor: { enabled: true },
      },
    },
    {
      id: "cloud-reburn",
      title: "单条重刻",
      tag: "重跑",
      summary: "已有源片备份时重刻 → 核对 → 预览",
      modules: {
        burn: {
          enabled: true,
          options: { stage: "full", crf: "30", publish: true },
        },
        backupcheck: { enabled: true },
        preview: { enabled: true },
      },
    },
    {
      id: "cloud-publish",
      title: "站点重发",
      tag: "发布",
      summary: "校验 → 只用已提交档案重建并发布站点",
      modules: {
        verify: { enabled: true },
        republish: { enabled: true },
      },
    },
    {
      id: "local-official",
      title: "本机字幕 · 官方",
      tag: "本机",
      summary: "官方英文 + 官方中文 · Scheme 1",
      modules: {
        localcaptions: {
          enabled: true,
          options: {
            preset: "local-youtube-official",
            assMode: "scheme1",
          },
        },
      },
    },
    {
      id: "local-asr-mt",
      title: "本机字幕 · ASR+MT",
      tag: "本机",
      summary: "ASR 英文 + 机器中文 · fused 时间轴",
      modules: {
        localcaptions: {
          enabled: true,
          options: {
            preset: "local-asr-mt",
            assMode: "fused",
            asrEngine: "auto",
            translationEngine: "auto",
          },
        },
      },
    },
  ];

  window.GitSynonymsFlow = Object.freeze({
    groups: GROUPS,
    modules: MODULES,
    presets: PRESETS,
    executionOrder: EXECUTION_ORDER,
    pySetup: PY_SETUP,
    defaultPreset: "cloud-full",
    repoDefault: REPO_DEFAULT,
    outDirDefault: "D:\\MyDownload\\a",
    pythonPathDefault:
      "$env:USERPROFILE\\anaconda3\\envs\\a\\python.exe",
  });
})();
