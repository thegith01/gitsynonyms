/*
 * GitSynonyms flow workspace.
 *
 * n8n-style model: every workflow owns an ordered node chain and its own
 * parameters. Nodes can be inserted, removed, duplicated, disabled and
 * reordered; the page only generates commands and never executes them.
 */
(() => {
  "use strict";

  const FLOW = window.GitSynonymsFlow;
  if (!FLOW) return;

  const WORKSPACE_KEY = "gitsynonyms.flow.workspace.v4";
  const LEGACY_STATE_KEY = "gitsynonyms.flow.v1";
  const LEGACY_CUSTOM_KEY = "gitsynonyms.flow.custom.v1";
  const DEFAULTS = Object.freeze({
    video: "",
    outDir: FLOW.outDirDefault,
    repo: FLOW.repoDefault,
    pythonPath: FLOW.pythonPathDefault,
    title: "",
    eventDate: "",
    sourceUrl: "",
  });
  const KIND_LABELS = Object.freeze({ cloud: "云端", local: "本机" });
  const PLACEHOLDERS =
    /\{(video_id|video_url|repo|out_dir|python_path|title|event_date|source_url)\}/g;

  const els = {
    workflowTabs: document.querySelector("#workflow-tabs"),
    workflowName: document.querySelector("#workflow-name"),
    workflowMeta: document.querySelector("#workflow-meta"),
    newWorkflow: document.querySelector("#new-workflow"),
    duplicateWorkflow: document.querySelector("#duplicate-workflow"),
    deleteWorkflow: document.querySelector("#delete-workflow"),
    openTemplates: document.querySelector("#open-templates"),
    videoInput: document.querySelector("#video-input"),
    videoHint: document.querySelector("#video-hint"),
    outDirInput: document.querySelector("#outdir-input"),
    repoInput: document.querySelector("#repo-input"),
    pythonInput: document.querySelector("#python-input"),
    pythonHint: document.querySelector("#python-hint"),
    resetPython: document.querySelector("#reset-python"),
    titleInput: document.querySelector("#title-input"),
    eventDateInput: document.querySelector("#event-date-input"),
    sourceUrlInput: document.querySelector("#source-url-input"),
    paletteSearch: document.querySelector("#palette-search"),
    insertHint: document.querySelector("#insert-hint"),
    insertHintText: document.querySelector("#insert-hint-text"),
    cancelInsert: document.querySelector("#cancel-insert"),
    paletteGroups: document.querySelector("#palette-groups"),
    newModule: document.querySelector("#new-module"),
    flowCanvas: document.querySelector("#flow-canvas"),
    flowSummary: document.querySelector("#flow-summary"),
    flowWarnings: document.querySelector("#flow-warnings"),
    expandAll: document.querySelector("#expand-all"),
    collapseAll: document.querySelector("#collapse-all"),
    clearNodes: document.querySelector("#clear-nodes"),
    planSummary: document.querySelector("#plan-summary"),
    commandPlan: document.querySelector("#command-plan"),
    copyPlan: document.querySelector("#copy-plan"),
    shareFlow: document.querySelector("#share-flow"),
    exportFlow: document.querySelector("#export-flow"),
    importFlow: document.querySelector("#import-flow"),
    importFile: document.querySelector("#import-file"),
    resetFlow: document.querySelector("#reset-flow"),
    flowStatus: document.querySelector("#flow-status"),
    templatesDialog: document.querySelector("#templates-dialog"),
    closeTemplates: document.querySelector("#close-templates"),
    templateGrid: document.querySelector("#template-grid"),
    moduleDialog: document.querySelector("#module-dialog"),
    moduleForm: document.querySelector("#module-form"),
    editorId: document.querySelector("#editor-id"),
    editorHeading: document.querySelector("#editor-title"),
    editorName: document.querySelector("#editor-name"),
    editorSummary: document.querySelector("#editor-summary"),
    editorGroup: document.querySelector("#editor-group"),
    editorKind: document.querySelector("#editor-kind"),
    editorCommand: document.querySelector("#editor-command"),
    editorNote: document.querySelector("#editor-note"),
    editorRequiresVideo: document.querySelector("#editor-requires-video"),
    editorSetup: document.querySelector("#editor-setup"),
    editorSetupRow: document.querySelector("#editor-setup-row"),
    editorAdd: document.querySelector("#editor-add"),
    editorSave: document.querySelector("#editor-save"),
    editorCancel: document.querySelector("#editor-cancel"),
    editorClose: document.querySelector("#editor-close"),
    editorDelete: document.querySelector("#editor-delete"),
    editorStatus: document.querySelector("#editor-status"),
  };

  let workspace;
  let customModules = [];
  let currentSteps = [];
  let expandedNodes = new Set();
  let insertIndex = null;
  let paletteQuery = "";
  let draggedNodeId = null;
  let dragOverIndex = null;
  let statusTimer = 0;
  let pendingStatus = "";

  /* ------------------------------------------------------------------ */
  /* Small helpers                                                       */
  /* ------------------------------------------------------------------ */

  function stringValue(value) {
    return typeof value === "string" ? value : "";
  }

  function uid(prefix) {
    return `${prefix}-${Date.now().toString(36)}-${Math.random()
      .toString(36)
      .slice(2, 7)}`;
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function psString(value) {
    if (/^\$/.test(value)) {
      return `"${value.replaceAll('"', '`"')}"`;
    }
    return `'${value.replaceAll("'", "''")}'`;
  }

  function pythonSetup(path) {
    return [
      `$py = ${psString(path)}`,
      'if (-not (Test-Path -LiteralPath $py)) { throw "Anaconda Python 未找到: $py" }',
      '& $py -c "import sys; print(sys.executable)"',
    ].join("\n");
  }

  function showStatus(message) {
    els.flowStatus.textContent = message;
    if (statusTimer) window.clearTimeout(statusTimer);
    statusTimer = window.setTimeout(() => {
      els.flowStatus.textContent = "";
    }, 2600);
  }

  function setEditorStatus(message, ok) {
    els.editorStatus.textContent = message;
    els.editorStatus.classList.toggle("is-ok", Boolean(ok));
  }

  function extractVideoId(raw) {
    const value = stringValue(raw).trim();
    if (!value) return "";
    const match = value.match(
      /(?:youtu\.be\/|v=|vi=|shorts\/|embed\/|live\/)([A-Za-z0-9_-]{11})/,
    );
    if (match) return match[1];
    if (/^[A-Za-z0-9_-]{11}$/.test(value)) return value;
    return "";
  }

  function videoUrl(raw, id) {
    const value = stringValue(raw).trim();
    if (/^https?:\/\//i.test(value)) return value;
    if (id) return `https://youtu.be/${id}`;
    return "";
  }

  function openDialog(dialog) {
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }

  function closeDialog(dialog) {
    if (typeof dialog.close === "function" && dialog.open) {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
  }

  /* ------------------------------------------------------------------ */
  /* Custom modules                                                      */
  /* ------------------------------------------------------------------ */

  function makeCustomId() {
    return uid("custom");
  }

  function normalizeCustomModules(raw) {
    if (!Array.isArray(raw)) return [];
    const seen = new Set();
    const result = [];
    for (const item of raw) {
      if (!item || typeof item !== "object") continue;
      const title = stringValue(item.title).trim().slice(0, 80);
      const command = stringValue(item.command).trim().slice(0, 4000);
      if (!title || !command) continue;
      let id = stringValue(item.id);
      if (!/^custom-[a-z0-9-]{3,64}$/i.test(id) || seen.has(id)) {
        id = makeCustomId();
      }
      seen.add(id);
      const group = FLOW.groups.some((entry) => entry.id === item.group)
        ? item.group
        : "produce";
      const kind = item.kind === "local" ? "local" : "cloud";
      result.push({
        id,
        group,
        title,
        summary: stringValue(item.summary).trim().slice(0, 300),
        kind,
        requiresVideo: Boolean(item.requiresVideo),
        setup: kind === "local" ? item.setup !== false : false,
        command,
        note: stringValue(item.note).trim().slice(0, 500),
      });
    }
    return result;
  }

  function mergeCustomModules(incoming) {
    const merged = [...customModules];
    for (const def of incoming) {
      const index = merged.findIndex((item) => item.id === def.id);
      if (index >= 0) merged[index] = def;
      else merged.push(def);
    }
    customModules = merged;
  }

  function fillTemplate(template, ctx) {
    const values = {
      video_id: ctx.id || "<video-id>",
      video_url: ctx.url || "",
      repo: ctx.repo,
      out_dir: ctx.outDir,
      python_path: ctx.pythonPath,
      title: ctx.title,
      event_date: ctx.eventDate,
      source_url: ctx.sourceUrl,
    };
    return template.replace(PLACEHOLDERS, (_, key) => values[key]);
  }

  function customToModule(def) {
    return {
      id: def.id,
      group: def.group,
      title: def.title,
      summary: def.summary || "自定义命令模块；命令与参数由流程工作区编辑。",
      kind: def.kind,
      requiresVideo: def.requiresVideo,
      custom: true,
      def,
      meta: ["自定义"],
      options: [],
      build(ctx) {
        const warnings = [];
        if (def.requiresVideo && !ctx.id) {
          warnings.push(`自定义模块「${def.title}」需要视频 ID。`);
        }
        return {
          kind: def.kind,
          setup: def.kind === "local" && def.setup ? FLOW.pySetup : "",
          code: fillTemplate(def.command, ctx),
          note: def.note,
          warnings,
        };
      },
    };
  }

  function getModule(moduleId) {
    const builtIn = FLOW.modules.find((item) => item.id === moduleId);
    if (builtIn) return builtIn;
    const def = customModules.find((item) => item.id === moduleId);
    return def ? customToModule(def) : null;
  }

  function allModules() {
    return [...FLOW.modules, ...customModules.map(customToModule)];
  }

  function moduleDefaults(module) {
    const options = {};
    for (const option of module.options || []) {
      options[option.key] = option.default;
    }
    return options;
  }

  function sanitizeOption(option, raw) {
    const fallback = option.default;
    if (option.type === "checkbox") return Boolean(raw);
    if (option.type === "select") {
      const allowed = (option.choices || []).some(
        (choice) => choice.value === raw,
      );
      return allowed ? raw : fallback;
    }
    if (option.type === "number") {
      if (raw === "" || raw === undefined || raw === null) return fallback;
      const numeric = Number(raw);
      if (!Number.isFinite(numeric)) return fallback;
      if (option.min !== undefined && numeric < option.min) {
        return String(option.min);
      }
      if (option.max !== undefined && numeric > option.max) {
        return String(option.max);
      }
      return String(numeric);
    }
    return stringValue(raw) || fallback;
  }

  function sanitizeNodeOptions(module, raw) {
    const saved = raw && typeof raw === "object" ? raw : {};
    const options = moduleDefaults(module);
    for (const option of module.options || []) {
      if (Object.prototype.hasOwnProperty.call(saved, option.key)) {
        options[option.key] = sanitizeOption(option, saved[option.key]);
      }
    }
    return options;
  }

  /* ------------------------------------------------------------------ */
  /* Workspace and workflow model                                        */
  /* ------------------------------------------------------------------ */

  function normalizeParams(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    let pythonPath = stringValue(source.pythonPath).trim();
    if (
      (pythonPath.startsWith('"') && pythonPath.endsWith('"')) ||
      (pythonPath.startsWith("'") && pythonPath.endsWith("'"))
    ) {
      pythonPath = pythonPath.slice(1, -1);
    }
    return {
      video: stringValue(source.video),
      outDir: stringValue(source.outDir).trim() || DEFAULTS.outDir,
      repo: stringValue(source.repo).trim() || DEFAULTS.repo,
      pythonPath: pythonPath || DEFAULTS.pythonPath,
      title: stringValue(source.title),
      eventDate: stringValue(source.eventDate),
      sourceUrl: stringValue(source.sourceUrl),
    };
  }

  function makeNode(moduleId, rawOptions, enabled = true) {
    const module = getModule(moduleId);
    if (!module) return null;
    return {
      id: uid("node"),
      moduleId,
      enabled,
      options: sanitizeNodeOptions(module, rawOptions),
    };
  }

  function normalizeNode(raw) {
    if (!raw || typeof raw !== "object") return null;
    const moduleId = stringValue(raw.moduleId);
    const module = getModule(moduleId);
    if (!module) return null;
    const id = /^node-[a-z0-9-]{3,64}$/i.test(stringValue(raw.id))
      ? stringValue(raw.id)
      : uid("node");
    return {
      id,
      moduleId,
      enabled: raw.enabled !== false,
      options: sanitizeNodeOptions(module, raw.options),
    };
  }

  function normalizeWorkflow(raw, index = 0) {
    if (!raw || typeof raw !== "object") return null;
    const name =
      stringValue(raw.name).trim().slice(0, 80) || `流程 ${index + 1}`;
    const sourceNodes = Array.isArray(raw.nodes) ? raw.nodes : [];
    const nodes = sourceNodes.map(normalizeNode).filter(Boolean);
    const id = /^flow-[a-z0-9-]{3,64}$/i.test(stringValue(raw.id))
      ? stringValue(raw.id)
      : uid("flow");
    return {
      id,
      name,
      params: normalizeParams(raw.params || raw),
      nodes,
    };
  }

  function uniqueWorkflowName(base, ignoreId, existingList) {
    let name = stringValue(base).trim().slice(0, 80) || "新流程";
    const existing = Array.isArray(existingList)
      ? existingList
      : workspace
        ? workspace.workflows
        : [];
    const names = new Set(
      existing
        .filter((item) => item.id !== ignoreId)
        .map((item) => item.name),
    );
    if (!names.has(name)) return name;
    let counter = 2;
    while (names.has(`${name} ${counter}`)) counter += 1;
    return `${name} ${counter}`;
  }

  function uniqueWorkflowId(id, existingList) {
    let candidate = id;
    const existing = Array.isArray(existingList)
      ? existingList
      : workspace
        ? workspace.workflows
        : [];
    while (existing.some((item) => item.id === candidate)) {
      candidate = uid("flow");
    }
    return candidate;
  }

  function nodesFromPreset(presetId) {
    const preset =
      FLOW.presets.find((item) => item.id === presetId) || FLOW.presets[0];
    const nodes = [];
    for (const id of FLOW.executionOrder) {
      const setting = preset.modules[id];
      if (!setting || !setting.enabled) continue;
      const node = makeNode(id, setting.options || {}, true);
      if (node) nodes.push(node);
    }
    return nodes;
  }

  function defaultWorkflows() {
    return [
      {
        id: uid("flow"),
        name: "云端全流程",
        params: normalizeParams({}),
        nodes: nodesFromPreset("cloud-full"),
      },
      {
        id: uid("flow"),
        name: "本机字幕 · ASR+MT",
        params: normalizeParams({}),
        nodes: nodesFromPreset("local-asr-mt"),
      },
    ];
  }

  function legacyWorkflow(raw) {
    const savedModules =
      raw.modules && typeof raw.modules === "object" ? raw.modules : {};
    const ids = [...FLOW.executionOrder];
    for (const def of customModules) {
      if (!ids.includes(def.id)) ids.push(def.id);
    }
    const nodes = [];
    for (const id of ids) {
      const saved = savedModules[id];
      if (!saved || !saved.enabled) continue;
      const node = makeNode(id, saved.options || {}, true);
      if (node) nodes.push(node);
    }
    const preset = FLOW.presets.find((item) => item.id === raw.preset);
    const name =
      stringValue(raw.name).trim() || (preset ? preset.title : "导入流程");
    return normalizeWorkflow(
      { id: raw.id, name, params: raw, nodes },
      0,
    );
  }

  function readLegacyCustomModules() {
    try {
      const saved = window.localStorage.getItem(LEGACY_CUSTOM_KEY);
      if (saved) return JSON.parse(saved);
    } catch {
      // Ignore malformed legacy custom modules.
    }
    return [];
  }

  function normalizeWorkspace(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    customModules = normalizeCustomModules(
      Array.isArray(source.customModules)
        ? source.customModules
        : readLegacyCustomModules(),
    );

    let workflows = [];
    if (Array.isArray(source.workflows) && source.workflows.length) {
      workflows = source.workflows
        .map((item, index) => normalizeWorkflow(item, index))
        .filter(Boolean);
    } else if (source.modules && typeof source.modules === "object") {
      const workflow = legacyWorkflow(source);
      if (workflow) workflows.push(workflow);
    }
    if (!workflows.length) workflows = defaultWorkflows();

    const seen = new Set();
    for (const workflow of workflows) {
      if (seen.has(workflow.id)) workflow.id = uid("flow");
      seen.add(workflow.id);
    }

    const activeId = workflows.some((item) => item.id === source.activeId)
      ? source.activeId
      : workflows[0].id;
    return { version: 4, activeId, workflows };
  }

  function readSharedPayload() {
    const params = new URLSearchParams(window.location.search);
    const encoded = params.get("flow");
    if (!encoded) return null;
    window.history.replaceState(null, "", window.location.pathname);
    try {
      let base64 = encoded.replaceAll("-", "+").replaceAll("_", "/");
      while (base64.length % 4) base64 += "=";
      const binary = window.atob(base64);
      const bytes = Uint8Array.from(binary, (character) =>
        character.charCodeAt(0),
      );
      return JSON.parse(new TextDecoder().decode(bytes));
    } catch {
      return null;
    }
  }

  function workflowFromShared(payload, existingList = []) {
    let workflow;
    if (payload.workflow) {
      workflow = normalizeWorkflow(payload.workflow, 0);
    } else if (payload.modules) {
      workflow = legacyWorkflow(payload);
    } else {
      workflow = normalizeWorkflow(payload, 0);
    }
    if (!workflow) return null;
    workflow.id = uniqueWorkflowId(workflow.id, existingList);
    workflow.name = uniqueWorkflowName(
      `${workflow.name}（导入）`,
      null,
      existingList,
    );
    // Imported flows are copies; fresh node ids keep expansion/selection state
    // independent from the workflow the link was generated from.
    workflow.nodes = workflow.nodes.map((node) => ({
      ...node,
      id: uid("node"),
    }));
    return workflow;
  }

  function loadWorkspace() {
    const shared = readSharedPayload();
    let saved = null;
    try {
      const stored = window.localStorage.getItem(WORKSPACE_KEY);
      if (stored) {
        saved = JSON.parse(stored);
      } else {
        const legacy = window.localStorage.getItem(LEGACY_STATE_KEY);
        if (legacy) saved = JSON.parse(legacy);
      }
    } catch {
      // Ignore malformed workspace storage.
    }

    if (!saved && shared) {
      customModules = normalizeCustomModules(shared.customModules || []);
      const workflow = workflowFromShared(shared);
      if (workflow) {
        pendingStatus = "已从分享链接导入流程";
        return { version: 4, activeId: workflow.id, workflows: [workflow] };
      }
      return normalizeWorkspace({});
    }

    const result = normalizeWorkspace(saved || {});
    if (saved && shared) {
      mergeCustomModules(normalizeCustomModules(shared.customModules || []));
      const workflow = workflowFromShared(shared, result.workflows);
      if (workflow) {
        result.workflows.push(workflow);
        result.activeId = workflow.id;
        pendingStatus = "已从分享链接导入新流程";
      }
    }
    return result;
  }

  function saveWorkspace() {
    try {
      window.localStorage.setItem(
        WORKSPACE_KEY,
        JSON.stringify({
          version: 4,
          activeId: workspace.activeId,
          workflows: workspace.workflows,
          customModules,
        }),
      );
    } catch {
      // Private-mode storage failures must not break the workspace.
    }
  }

  function activeWorkflow() {
    return (
      workspace.workflows.find((item) => item.id === workspace.activeId) ||
      workspace.workflows[0]
    );
  }

  function createWorkflow(name, nodes, params) {
    const workflow = {
      id: uid("flow"),
      name: uniqueWorkflowName(name),
      params: normalizeParams(params || activeWorkflow().params),
      nodes: nodes || [],
    };
    workspace.workflows.push(workflow);
    workspace.activeId = workflow.id;
    return workflow;
  }

  /* ------------------------------------------------------------------ */
  /* Context, commands and runbook                                       */
  /* ------------------------------------------------------------------ */

  function buildContext(workflow) {
    const params = workflow.params;
    const id = extractVideoId(params.video);
    const pythonPath = params.pythonPath.trim() || DEFAULTS.pythonPath;
    return {
      workflow,
      params,
      state: params,
      id,
      url: videoUrl(params.video, id),
      repo: params.repo.trim() || DEFAULTS.repo,
      outDir: params.outDir.trim() || DEFAULTS.outDir,
      pythonPath,
      pySetup: pythonSetup(pythonPath),
      title: params.title.trim(),
      eventDate: params.eventDate.trim(),
      sourceUrl: params.sourceUrl.trim(),
    };
  }

  function buildSteps(workflow) {
    const ctx = buildContext(workflow);
    const steps = [];
    workflow.nodes.forEach((node) => {
      if (!node.enabled) return;
      const module = getModule(node.moduleId);
      if (!module) return;
      const opts = { ...moduleDefaults(module), ...node.options };
      let result;
      try {
        result = module.build({ ...ctx, opts });
      } catch (error) {
        result = {
          kind: module.kind,
          code: "",
          note: "",
          warnings: [`生成命令失败：${error.message}`],
        };
      }
      if (!result) return;
      const kind = result.kind || module.kind;
      const useAnaconda = kind === "local" && Boolean(result.setup);
      steps.push({
        node,
        module,
        kind,
        setup: useAnaconda ? ctx.pySetup : "",
        code: result.code || "",
        note: result.note || "",
        warnings: Array.isArray(result.warnings) ? result.warnings : [],
      });
    });
    return { ctx, steps };
  }

  function formatStepCode(step) {
    const parts = [];
    if (step.setup) parts.push(step.setup, "");
    parts.push(step.code);
    if (step.note) parts.push("", `# ${step.note}`);
    return parts.join("\n");
  }

  function buildRunbook() {
    const workflow = activeWorkflow();
    const { ctx, steps } = buildSteps(workflow);
    if (!steps.length) return "";
    const lines = [
      `# GitSynonyms 流程：${workflow.name}`,
      `# 视频: ${ctx.id || "未填写"}`,
      `# 模块: ${steps.map((step) => step.module.title).join(" → ")}`,
      "# 说明: 本页只生成命令，不自动执行；本机步骤统一使用 Anaconda a 环境。",
      "",
    ];
    if (steps.some((step) => step.setup)) {
      lines.push("# ---- Anaconda 环境（本机步骤共用） ----", ctx.pySetup, "");
    }
    steps.forEach((step, index) => {
      lines.push(
        `# ---- ${index + 1}. ${step.module.title} [${KIND_LABELS[step.kind]}] ----`,
      );
      lines.push(step.code);
      if (step.note) lines.push(`# 备注: ${step.note}`);
      for (const warning of step.warnings) lines.push(`# 注意: ${warning}`);
      lines.push("");
    });
    return `${lines.join("\n").trimEnd()}\n`;
  }

  /* ------------------------------------------------------------------ */
  /* Rendering                                                           */
  /* ------------------------------------------------------------------ */

  function countKinds(workflow) {
    let cloud = 0;
    let local = 0;
    let enabled = 0;
    for (const node of workflow.nodes) {
      const module = getModule(node.moduleId);
      if (!module) continue;
      if (node.enabled) enabled += 1;
      if (module.kind === "local") local += 1;
      else cloud += 1;
    }
    return { cloud, local, enabled };
  }

  function renderAll() {
    renderTabs();
    renderWorkflowHeader();
    renderParams();
    renderPalette();
    renderCanvas();
    renderPlan();
    updateInsertHint();
  }

  function renderTabs() {
    els.workflowTabs.innerHTML = "";
    for (const workflow of workspace.workflows) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "workflow-tab";
      button.dataset.workflowId = workflow.id;
      button.setAttribute("role", "tab");
      button.setAttribute(
        "aria-selected",
        workflow.id === workspace.activeId ? "true" : "false",
      );
      if (workflow.id === workspace.activeId) button.classList.add("is-active");

      const name = document.createElement("span");
      name.textContent = workflow.name;
      const { enabled } = countKinds(workflow);
      const count = document.createElement("span");
      count.className = "workflow-tab-count";
      count.textContent = `${enabled}/${workflow.nodes.length}`;
      button.append(name, count);
      els.workflowTabs.append(button);
    }
  }

  function renderWorkflowHeader() {
    const workflow = activeWorkflow();
    if (els.workflowName.value !== workflow.name) {
      els.workflowName.value = workflow.name;
    }
    const { cloud, local, enabled } = countKinds(workflow);
    els.workflowMeta.textContent = `${workflow.nodes.length} 个节点 · 已启用 ${enabled} · 云端 ${cloud} / 本机 ${local} · 自动保存在当前浏览器`;
  }

  function updateVideoHint() {
    const raw = activeWorkflow().params.video.trim();
    const id = extractVideoId(raw);
    els.videoHint.classList.remove("is-warning");
    if (!raw) {
      els.videoHint.textContent = "支持完整 YouTube 链接或 11 位视频 ID。";
      return;
    }
    if (id) {
      els.videoHint.textContent = `已识别视频 ID：${id}`;
      return;
    }
    els.videoHint.textContent =
      "未识别为 YouTube 链接或 11 位 ID；命令会把填写的值原样用于参数。";
    els.videoHint.classList.add("is-warning");
  }

  function updatePythonHint() {
    const path =
      activeWorkflow().params.pythonPath.trim() || DEFAULTS.pythonPath;
    const looksConda = /anaconda|miniconda|conda/i.test(path);
    els.pythonHint.textContent = looksConda
      ? `本机步骤先定义 $py 并检查该解释器；不会回退到系统 python。当前：${path}`
      : `当前路径不像 Anaconda 环境；本机步骤仍会使用它，请确认不是系统 python。当前：${path}`;
    const field = els.pythonInput.closest(".python-field");
    if (field) field.classList.toggle("is-warning", !looksConda);
  }

  function renderParams() {
    const params = activeWorkflow().params;
    els.videoInput.value = params.video;
    els.outDirInput.value = params.outDir;
    els.repoInput.value = params.repo;
    els.pythonInput.value = params.pythonPath;
    els.titleInput.value = params.title;
    els.eventDateInput.value = params.eventDate;
    els.sourceUrlInput.value = params.sourceUrl;
    updateVideoHint();
    updatePythonHint();
  }

  function renderPalette() {
    els.paletteGroups.innerHTML = "";
    const query = paletteQuery.trim().toLowerCase();
    const modules = allModules();
    let matches = 0;

    for (const group of FLOW.groups) {
      const inGroup = modules.filter((module) => module.group === group.id);
      const visible = inGroup.filter((module) => {
        if (!query) return true;
        const haystack = [
          module.title,
          module.summary,
          module.id,
          ...(module.meta || []),
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(query);
      });
      if (!visible.length) continue;
      matches += visible.length;

      const section = document.createElement("section");
      section.className = "palette-group";
      section.dataset.group = group.id;
      const head = document.createElement("div");
      head.className = "palette-group-head";
      const title = document.createElement("h3");
      title.textContent = group.title;
      const count = document.createElement("span");
      count.textContent = `${visible.length} 个`;
      head.append(title, count);

      const list = document.createElement("div");
      list.className = "palette-list";
      for (const module of visible) {
        list.append(createPaletteItem(module));
      }
      section.append(head, list);
      els.paletteGroups.append(section);
    }

    if (!matches) {
      const empty = document.createElement("p");
      empty.className = "palette-empty";
      empty.textContent = query
        ? `没有匹配“${paletteQuery.trim()}”的模块。`
        : "模块库为空。";
      els.paletteGroups.append(empty);
    }
  }

  function createPaletteItem(module) {
    const item = document.createElement("article");
    item.className = "palette-item";
    item.dataset.moduleId = module.id;

    const add = document.createElement("button");
    add.type = "button";
    add.className = "palette-add";
    add.dataset.addModule = module.id;
    add.title = `把「${module.title}」插入当前流程`;

    const titleRow = document.createElement("span");
    titleRow.className = "palette-title-row";
    const title = document.createElement("span");
    title.className = "palette-title";
    title.textContent = module.title;
    const plus = document.createElement("span");
    plus.className = "palette-plus";
    plus.textContent = "＋";
    titleRow.append(title, plus);

    const meta = document.createElement("span");
    meta.className = "palette-meta";
    const kind = document.createElement("span");
    kind.className = `loc-badge ${module.kind}`;
    kind.textContent = KIND_LABELS[module.kind] || module.kind;
    meta.append(kind);
    if (module.custom) {
      const chip = document.createElement("span");
      chip.className = "meta-chip";
      chip.textContent = "自定义";
      meta.append(chip);
    } else if ((module.options || []).length) {
      const chip = document.createElement("span");
      chip.className = "meta-chip";
      chip.textContent = `${module.options.length} 参数`;
      meta.append(chip);
    }

    const summary = document.createElement("span");
    summary.className = "palette-summary";
    summary.textContent = module.summary;
    add.append(titleRow, meta, summary);

    const actions = document.createElement("div");
    actions.className = "palette-actions";
    if (module.custom) {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.dataset.editModule = module.id;
      edit.textContent = "编辑";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "is-danger";
      remove.dataset.deleteModule = module.id;
      remove.textContent = "删除";
      actions.append(edit, remove);
    } else {
      const saveAs = document.createElement("button");
      saveAs.type = "button";
      saveAs.dataset.cloneModule = module.id;
      saveAs.textContent = "另存";
      saveAs.title = "把当前命令另存为可编辑的自定义模块";
      actions.append(saveAs);
    }

    item.append(add, actions);
    return item;
  }

  function updateInsertHint() {
    if (insertIndex === null) {
      els.insertHint.hidden = true;
      els.insertHintText.textContent = "";
      return;
    }
    const length = activeWorkflow().nodes.length;
    insertIndex = Math.max(0, Math.min(insertIndex, length));
    els.insertHint.hidden = false;
    els.insertHintText.textContent =
      insertIndex >= length
        ? "将把模块添加到流程末尾。"
        : `将把模块插入到第 ${insertIndex + 1} 个位置。`;
  }

  function setInsertIndex(index) {
    insertIndex = Number.isFinite(index) ? index : null;
    updateInsertHint();
    els.paletteSearch.focus();
    els.paletteSearch.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function addModule(moduleId) {
    const module = getModule(moduleId);
    if (!module) return;
    const workflow = activeWorkflow();
    const node = makeNode(moduleId);
    if (!node) return;
    const index =
      insertIndex === null
        ? workflow.nodes.length
        : Math.max(0, Math.min(insertIndex, workflow.nodes.length));
    workflow.nodes.splice(index, 0, node);
    expandedNodes.add(node.id);
    insertIndex = null;
    updateInsertHint();

    saveWorkspace();
    renderCanvas();
    renderPlan();
    renderTabs();
    renderWorkflowHeader();
    showStatus(`已添加「${module.title}」`);

    const card = els.flowCanvas.querySelector(
      `[data-node-id="${node.id}"]`,
    );
    if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function renderCanvas() {
    const workflow = activeWorkflow();
    const { cloud, local, enabled } = countKinds(workflow);
    els.flowSummary.textContent = `${workflow.nodes.length} 个节点 · 已启用 ${enabled} · 云端 ${cloud} / 本机 ${local}`;
    els.flowCanvas.innerHTML = "";

    if (!workflow.nodes.length) {
      const empty = document.createElement("div");
      empty.className = "canvas-empty";
      const strong = document.createElement("strong");
      strong.textContent = "这条流程还是空的";
      const text = document.createElement("p");
      text.textContent =
        "从左侧模块库添加节点，或打开“模板”一次加入整套步骤。每个节点都可以单独排序、改参数或跳过。";
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.focusPalette = "true";
      button.textContent = "去添加第一个模块";
      empty.append(strong, text, button);
      els.flowCanvas.append(empty);
      return;
    }

    workflow.nodes.forEach((node, index) => {
      els.flowCanvas.append(createGap(index));
      els.flowCanvas.append(createNodeCard(node, index));
    });
    els.flowCanvas.append(createGap(workflow.nodes.length, true));
  }

  function createGap(index, tail = false) {
    const gap = document.createElement("div");
    gap.className = tail ? "node-gap node-gap--tail" : "node-gap";
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.insertIndex = String(index);
    button.textContent = tail ? "＋ 添加模块" : "＋";
    button.title = tail
      ? "在流程末尾添加模块"
      : `在第 ${index + 1} 个位置插入模块`;
    button.setAttribute("aria-label", button.title);
    gap.append(button);
    return gap;
  }

  function createNodeCard(node, index) {
    const module = getModule(node.moduleId);
    const card = document.createElement("article");
    card.className = "node-card";
    card.dataset.nodeId = node.id;
    card.dataset.group = module ? module.group : "produce";
    if (!node.enabled) card.classList.add("is-disabled");

    const gutter = document.createElement("div");
    gutter.className = "node-gutter";
    const drag = document.createElement("button");
    drag.type = "button";
    drag.className = "node-drag";
    drag.draggable = true;
    drag.dataset.dragHandle = "true";
    drag.textContent = "⠿";
    drag.title = "拖动排序";
    drag.setAttribute("aria-label", "拖动排序");
    const number = document.createElement("span");
    number.className = "node-index";
    number.textContent = String(index + 1);
    gutter.append(drag, number);

    const body = document.createElement("div");
    body.className = "node-body";

    const head = document.createElement("div");
    head.className = "node-head";
    const titleWrap = document.createElement("div");
    titleWrap.className = "node-title-wrap";
    const title = document.createElement("h3");
    title.className = "node-title";
    title.textContent = module ? module.title : node.moduleId;
    titleWrap.append(title);
    const badge = document.createElement("span");
    badge.className = `loc-badge ${module ? module.kind : "cloud"}`;
    badge.textContent = KIND_LABELS[module ? module.kind : "cloud"] || "云端";
    titleWrap.append(badge);
    if (module && module.custom) {
      const chip = document.createElement("span");
      chip.className = "meta-chip";
      chip.textContent = "自定义";
      titleWrap.append(chip);
    }

    const actions = document.createElement("div");
    actions.className = "node-actions";
    const toggle = document.createElement("label");
    toggle.className = "node-toggle";
    toggle.title = node.enabled ? "关闭后跳过该节点" : "重新启用该节点";
    const toggleInput = document.createElement("input");
    toggleInput.type = "checkbox";
    toggleInput.checked = node.enabled;
    toggleInput.dataset.nodeEnabled = node.id;
    const toggleText = document.createElement("span");
    toggleText.textContent = "启用";
    toggle.append(toggleInput, toggleText);

    const options = module ? module.options || [] : [];
    let optionsButton = null;
    if (options.length) {
      optionsButton = document.createElement("button");
      optionsButton.type = "button";
      optionsButton.className = "node-mini";
      optionsButton.dataset.toggleOptions = node.id;
      optionsButton.textContent = `参数 ${options.length}`;
      optionsButton.setAttribute(
        "aria-expanded",
        expandedNodes.has(node.id) ? "true" : "false",
      );
      optionsButton.setAttribute("aria-controls", `options-${node.id}`);
    }

    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "node-mini";
    edit.dataset.editNode = node.id;
    edit.textContent = "编辑";
    edit.hidden = !(module && module.custom);

    const up = document.createElement("button");
    up.type = "button";
    up.className = "node-mini";
    up.dataset.moveUp = node.id;
    up.textContent = "↑";
    up.title = "上移";
    up.disabled = index === 0;

    const down = document.createElement("button");
    down.type = "button";
    down.className = "node-mini";
    down.dataset.moveDown = node.id;
    down.textContent = "↓";
    down.title = "下移";
    down.disabled = index === activeWorkflow().nodes.length - 1;

    const duplicate = document.createElement("button");
    duplicate.type = "button";
    duplicate.className = "node-mini";
    duplicate.dataset.duplicateNode = node.id;
    duplicate.textContent = "⧉";
    duplicate.title = "复制节点";

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "node-mini node-mini--danger";
    remove.dataset.deleteNode = node.id;
    remove.textContent = "×";
    remove.title = "删除节点";

    actions.append(toggle);
    if (optionsButton) actions.append(optionsButton);
    actions.append(edit, up, down, duplicate, remove);

    head.append(titleWrap, actions);

    const summary = document.createElement("p");
    summary.className = "node-summary";
    summary.textContent = module ? module.summary : "模块不存在，无法生成命令。";

    const chips = document.createElement("div");
    chips.className = "node-chips";
    if (module) {
      for (const meta of module.meta || []) {
        const chip = document.createElement("span");
        chip.className = "meta-chip";
        chip.textContent = meta;
        chips.append(chip);
      }
      const merged = { ...moduleDefaults(module), ...node.options };
      for (const text of optionSummary(module, merged).slice(0, 4)) {
        const chip = document.createElement("span");
        chip.className = "meta-chip option-chip";
        chip.textContent = text;
        chips.append(chip);
      }
    }

    body.append(head, summary, chips);

    if (options.length) {
      const optionsBox = document.createElement("div");
      optionsBox.className = "node-options";
      optionsBox.id = `options-${node.id}`;
      optionsBox.hidden = !expandedNodes.has(node.id);
      const merged = { ...moduleDefaults(module), ...node.options };
      for (const option of options) {
        optionsBox.append(createOptionRow(node, module, option, merged));
      }
      body.append(optionsBox);
    }

    const footer = document.createElement("div");
    footer.className = "node-footer";
    const group = FLOW.groups.find((item) => item.id === (module && module.group));
    const groupName = document.createElement("span");
    groupName.textContent = group ? group.title : "未分组";
    const code = document.createElement("code");
    code.textContent = node.moduleId;
    footer.append(groupName, document.createTextNode(" · "), code);

    body.append(footer);
    card.append(gutter, body);
    return card;
  }

  function optionSummary(module, options) {
    const parts = [];
    for (const option of module.options || []) {
      if (option.showWhen && !option.showWhen(options)) continue;
      const value = options[option.key];
      if (option.type === "checkbox") {
        if (value) parts.push(option.label);
        continue;
      }
      const choice = (option.choices || []).find(
        (item) => item.value === value,
      );
      parts.push(`${option.label}: ${choice ? choice.label : value}`);
    }
    return parts;
  }

  function createOptionRow(node, module, option, merged) {
    const row = document.createElement("label");
    row.className =
      option.type === "checkbox"
        ? "option-row option-row--check"
        : "option-row";
    row.dataset.optionRow = option.key;
    if (option.showWhen && !option.showWhen(merged)) row.hidden = true;

    const label = document.createElement("span");
    label.className = "option-label";
    label.textContent = option.label;

    let control;
    if (option.type === "checkbox") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = Boolean(merged[option.key]);
      control.dataset.optionNode = node.id;
      control.dataset.optionKey = option.key;
      row.append(control, label);
    } else {
      if (option.type === "select") {
        control = document.createElement("select");
        for (const choice of option.choices || []) {
          const item = document.createElement("option");
          item.value = choice.value;
          item.textContent = choice.label;
          control.append(item);
        }
        control.value = merged[option.key];
      } else {
        control = document.createElement("input");
        control.type = option.type === "number" ? "number" : "text";
        if (option.type === "number") {
          if (option.min !== undefined) control.min = String(option.min);
          if (option.max !== undefined) control.max = String(option.max);
          if (option.step !== undefined) control.step = String(option.step);
        }
        control.value = merged[option.key];
      }
      control.dataset.optionNode = node.id;
      control.dataset.optionKey = option.key;
      row.append(label, control);
    }

    if (option.hint) {
      const hint = document.createElement("small");
      hint.className = "option-hint";
      hint.textContent = option.hint;
      row.append(hint);
    }
    return row;
  }

  function refreshNodeCard(nodeId) {
    const workflow = activeWorkflow();
    const node = workflow.nodes.find((item) => item.id === nodeId);
    if (!node) return;
    const module = getModule(node.moduleId);
    if (!module) return;
    const card = [...els.flowCanvas.querySelectorAll(".node-card")].find(
      (item) => item.dataset.nodeId === nodeId,
    );
    if (!card) return;
    card.classList.toggle("is-disabled", !node.enabled);
    const toggle = card.querySelector("[data-node-enabled]");
    if (toggle) toggle.checked = node.enabled;
    const merged = { ...moduleDefaults(module), ...node.options };
    for (const row of card.querySelectorAll("[data-option-row]")) {
      const option = (module.options || []).find(
        (item) => item.key === row.dataset.optionRow,
      );
      if (!option) continue;
      row.hidden = Boolean(option.showWhen && !option.showWhen(merged));
    }
    const chips = card.querySelector(".node-chips");
    if (chips) {
      for (const chip of [...chips.querySelectorAll(".option-chip")]) {
        chip.remove();
      }
      for (const text of optionSummary(module, merged).slice(0, 4)) {
        const chip = document.createElement("span");
        chip.className = "meta-chip option-chip";
        chip.textContent = text;
        chips.append(chip);
      }
    }
  }

  /* ------------------------------------------------------------------ */
  /* Command plan and warnings                                           */
  /* ------------------------------------------------------------------ */

  function renderPlan() {
    const workflow = activeWorkflow();
    const { ctx, steps } = buildSteps(workflow);
    currentSteps = steps;
    els.commandPlan.innerHTML = "";

    const localCount = steps.filter((step) => step.kind === "local").length;
    const cloudCount = steps.length - localCount;
    els.planSummary.textContent = steps.length
      ? `${steps.length} 个步骤 · 云端 ${cloudCount} / 本机 ${localCount}`
      : "添加节点后生成对应命令。";

    if (!steps.length) {
      const empty = document.createElement("p");
      empty.className = "plan-empty";
      empty.textContent =
        "当前流程没有启用中的节点。添加模块、打开节点开关，或从模板开始。";
      els.commandPlan.append(empty);
      renderWarnings(steps);
      return;
    }

    if (steps.some((step) => step.setup)) {
      const env = document.createElement("div");
      env.className = "plan-env";
      const envHead = document.createElement("div");
      envHead.className = "plan-env-head";
      const envTitle = document.createElement("p");
      envTitle.className = "plan-env-title";
      envTitle.textContent = "Anaconda 环境（本机步骤共用）";
      const envCopy = document.createElement("button");
      envCopy.type = "button";
      envCopy.className = "ghost-button plan-copy";
      envCopy.dataset.copyEnv = "true";
      envCopy.textContent = "复制环境";
      envHead.append(envTitle, envCopy);
      const pre = document.createElement("pre");
      pre.textContent = ctx.pySetup;
      const note = document.createElement("p");
      note.textContent =
        "所有本机步骤都通过 $py 调用该解释器；不会回退到系统 python。";
      env.append(envHead, pre, note);
      els.commandPlan.append(env);
    }

    steps.forEach((step, index) => {
      const card = document.createElement("article");
      card.className = "plan-step";
      card.dataset.stepIndex = String(index);

      const head = document.createElement("div");
      head.className = "plan-step-head";
      const number = document.createElement("span");
      number.className = "plan-index";
      number.textContent = String(index + 1);
      const heading = document.createElement("div");
      heading.className = "plan-heading";
      const title = document.createElement("h3");
      title.className = "plan-title";
      title.textContent = step.module.title;
      const sub = document.createElement("p");
      sub.className = "plan-sub";
      const badge = document.createElement("span");
      badge.className = `loc-badge ${step.kind}`;
      badge.textContent = KIND_LABELS[step.kind] || step.kind;
      sub.append(badge);
      if (step.setup) {
        const envChip = document.createElement("span");
        envChip.className = "meta-chip option-chip";
        envChip.textContent = "Anaconda";
        sub.append(envChip);
      }
      heading.append(title, sub);
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "ghost-button plan-copy";
      copy.dataset.copyStep = String(index);
      copy.textContent = "复制";
      head.append(number, heading, copy);

      const block = document.createElement("div");
      block.className = "command-block";
      const pre = document.createElement("pre");
      pre.textContent = step.code;
      block.append(pre);

      card.append(head, block);

      if (step.warnings.length) {
        const list = document.createElement("ul");
        list.className = "plan-warnings";
        for (const warning of step.warnings) {
          const item = document.createElement("li");
          item.textContent = warning;
          list.append(item);
        }
        card.append(list);
      }

      if (step.note) {
        const note = document.createElement("p");
        note.className = "plan-note";
        note.textContent = step.note;
        card.append(note);
      }

      els.commandPlan.append(card);
    });

    renderWarnings(steps);
  }

  function renderWarnings(steps) {
    const warnings = [];
    for (const step of steps) {
      for (const warning of step.warnings) {
        warnings.push(`${step.module.title}：${warning}`);
      }
    }
    const workflow = activeWorkflow();
    const hasSetup = steps.some((step) => step.setup);
    const pythonPath =
      workflow.params.pythonPath.trim() || DEFAULTS.pythonPath;
    if (hasSetup && !/anaconda|miniconda|conda/i.test(pythonPath)) {
      warnings.push(
        "本机步骤的解释器路径不像 Anaconda 环境；请确认使用的是 a 环境，而不是系统 python。",
      );
    }
    if (!workflow.nodes.some((node) => node.enabled)) {
      warnings.push("当前流程没有启用中的节点。");
    }

    els.flowWarnings.innerHTML = "";
    els.flowWarnings.classList.toggle("has-warnings", warnings.length > 0);
    if (!warnings.length) {
      const ok = document.createElement("p");
      ok.className = "ok-line";
      ok.textContent = steps.length
        ? "参数完整，可以复制命令。"
        : "添加节点后，这里会显示需要处理的参数。";
      els.flowWarnings.append(ok);
      return;
    }
    const title = document.createElement("p");
    title.className = "warning-title";
    title.textContent = "执行前请确认";
    const list = document.createElement("ul");
    for (const warning of [...new Set(warnings)]) {
      const item = document.createElement("li");
      item.textContent = warning;
      list.append(item);
    }
    els.flowWarnings.append(title, list);
  }

  function updateNodeOption(nodeId, key, rawValue) {
    const workflow = activeWorkflow();
    const node = workflow.nodes.find((item) => item.id === nodeId);
    if (!node) return;
    const module = getModule(node.moduleId);
    if (!module) return;
    const option = (module.options || []).find((item) => item.key === key);
    if (!option) return;
    node.options[key] = sanitizeOption(option, rawValue);

    let rerender = option.type === "select" || option.type === "checkbox";
    if (
      node.moduleId === "localcaptions" &&
      key === "preset" &&
      String(node.options.preset).includes("-mt") &&
      node.options.assMode !== "fused"
    ) {
      node.options.assMode = "fused";
      rerender = true;
    }

    saveWorkspace();
    if (rerender) {
      renderCanvas();
    } else {
      refreshNodeCard(node.id);
    }
    renderPlan();
  }

  function readOptionControl(control) {
    if (control.type === "checkbox") return control.checked;
    return control.value;
  }

  function setNodeEnabled(nodeId, enabled) {
    const node = activeWorkflow().nodes.find((item) => item.id === nodeId);
    if (!node) return;
    node.enabled = Boolean(enabled);
    saveWorkspace();
    refreshNodeCard(node.id);
    renderPlan();
    renderTabs();
    renderWorkflowHeader();
  }

  function moveNode(nodeId, delta) {
    const workflow = activeWorkflow();
    const index = workflow.nodes.findIndex((item) => item.id === nodeId);
    if (index < 0) return;
    const next = index + delta;
    if (next < 0 || next >= workflow.nodes.length) return;
    const [node] = workflow.nodes.splice(index, 1);
    workflow.nodes.splice(next, 0, node);
    saveWorkspace();
    renderCanvas();
    renderPlan();
    renderTabs();
    renderWorkflowHeader();
    showStatus("节点顺序已更新");
  }

  function duplicateNode(nodeId) {
    const workflow = activeWorkflow();
    const index = workflow.nodes.findIndex((item) => item.id === nodeId);
    if (index < 0) return;
    const source = workflow.nodes[index];
    const copy = {
      id: uid("node"),
      moduleId: source.moduleId,
      enabled: source.enabled,
      options: { ...source.options },
    };
    workflow.nodes.splice(index + 1, 0, copy);
    expandedNodes.add(copy.id);
    saveWorkspace();
    renderCanvas();
    renderPlan();
    renderTabs();
    renderWorkflowHeader();
    showStatus("节点已复制");
  }

  function deleteNode(nodeId) {
    const workflow = activeWorkflow();
    const index = workflow.nodes.findIndex((item) => item.id === nodeId);
    if (index < 0) return;
    const module = getModule(workflow.nodes[index].moduleId);
    workflow.nodes.splice(index, 1);
    expandedNodes.delete(nodeId);
    saveWorkspace();
    renderCanvas();
    renderPlan();
    renderTabs();
    renderWorkflowHeader();
    showStatus(module ? `已删除「${module.title}」` : "节点已删除");
  }

  /* ------------------------------------------------------------------ */
  /* Clipboard, sharing and workspace files                              */
  /* ------------------------------------------------------------------ */

  function fallbackCopy(text) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-9999px";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    if (!ok) throw new Error("copy failed");
  }

  async function copyText(text, message) {
    if (!text) {
      showStatus("没有可复制的命令");
      return;
    }
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        fallbackCopy(text);
      }
      showStatus(message);
    } catch {
      try {
        fallbackCopy(text);
        showStatus(message);
      } catch {
        showStatus("复制失败，请手动选择命令");
      }
    }
  }

  function encodeBase64Url(value) {
    const bytes = new TextEncoder().encode(value);
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return window
      .btoa(binary)
      .replaceAll("+", "-")
      .replaceAll("/", "_")
      .replace(/=+$/, "");
  }

  function shareLink() {
    const workflow = activeWorkflow();
    const used = new Set(workflow.nodes.map((node) => node.moduleId));
    const payload = {
      version: 4,
      kind: "workflow",
      workflow,
      customModules: customModules.filter((item) => used.has(item.id)),
    };
    const encoded = encodeBase64Url(JSON.stringify(payload));
    const base = `${window.location.origin}${window.location.pathname}`;
    copyText(`${base}?flow=${encoded}`, "分享链接已复制");
  }

  function exportFlow() {
    const payload = {
      version: 4,
      exportedAt: new Date().toISOString(),
      activeId: workspace.activeId,
      workflows: workspace.workflows,
      customModules,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(blob);
    anchor.download = "gitsynonyms-flows.json";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
    showStatus("工作区 JSON 已导出");
  }

  function importFlowFile(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result));
        if (!parsed || typeof parsed !== "object") {
          throw new Error("invalid payload");
        }
        if (
          !Array.isArray(parsed.workflows) &&
          !parsed.workflow &&
          !parsed.modules
        ) {
          throw new Error("not a workspace");
        }
        if (
          !window.confirm(
            "导入会替换当前工作区（所有流程与自定义模块），继续？",
          )
        ) {
          return;
        }
        let source = parsed;
        if (parsed.workflow) {
          source = {
            workflows: [parsed.workflow],
            customModules: parsed.customModules || [],
          };
        }
        workspace = normalizeWorkspace(source);
        expandedNodes = new Set();
        insertIndex = null;
        renderAll();
        saveWorkspace();
        showStatus("工作区已导入");
      } catch {
        showStatus("导入失败：不是有效的流程 JSON");
      } finally {
        els.importFile.value = "";
      }
    };
    reader.onerror = () => {
      showStatus("导入失败：无法读取文件");
      els.importFile.value = "";
    };
    reader.readAsText(file);
  }

  /* ------------------------------------------------------------------ */
  /* Workflow actions                                                    */
  /* ------------------------------------------------------------------ */

  function switchWorkflow(workflowId) {
    if (workflowId === workspace.activeId) return;
    if (!workspace.workflows.some((item) => item.id === workflowId)) return;
    workspace.activeId = workflowId;
    insertIndex = null;
    renderAll();
    saveWorkspace();
  }

  function newWorkflow() {
    const workflow = createWorkflow("新流程", [], activeWorkflow().params);
    expandedNodes = new Set();
    insertIndex = null;
    renderAll();
    saveWorkspace();
    els.workflowName.focus();
    els.workflowName.select();
    showStatus(`已新建「${workflow.name}」`);
  }

  function duplicateWorkflow() {
    const source = activeWorkflow();
    const copy = {
      id: uid("flow"),
      name: uniqueWorkflowName(`${source.name} 副本`),
      params: { ...source.params },
      nodes: source.nodes.map((node) => ({
        id: uid("node"),
        moduleId: node.moduleId,
        enabled: node.enabled,
        options: { ...node.options },
      })),
    };
    workspace.workflows.push(copy);
    workspace.activeId = copy.id;
    expandedNodes = new Set();
    insertIndex = null;
    renderAll();
    saveWorkspace();
    showStatus(`已复制为「${copy.name}」`);
  }

  function deleteWorkflow() {
    if (workspace.workflows.length <= 1) {
      showStatus("至少保留一条流程");
      return;
    }
    const workflow = activeWorkflow();
    if (!window.confirm(`删除流程「${workflow.name}」？此操作不可撤销。`)) {
      return;
    }
    const index = workspace.workflows.findIndex(
      (item) => item.id === workflow.id,
    );
    workspace.workflows.splice(index, 1);
    workspace.activeId =
      workspace.workflows[Math.max(0, index - 1)].id;
    insertIndex = null;
    renderAll();
    saveWorkspace();
    showStatus("流程已删除");
  }

  function handleWorkflowNameInput() {
    const workflow = activeWorkflow();
    workflow.name = els.workflowName.value.slice(0, 80);
    renderTabs();
    saveWorkspace();
  }

  function handleWorkflowNameChange() {
    const workflow = activeWorkflow();
    workflow.name =
      els.workflowName.value.trim().slice(0, 80) || "未命名流程";
    els.workflowName.value = workflow.name;
    renderTabs();
    renderWorkflowHeader();
    saveWorkspace();
  }

  function resetWorkspace() {
    if (
      !window.confirm(
        "恢复示例工作区？会重建两条示例流程，当前流程节点会被清除；自定义模块会保留。",
      )
    ) {
      return;
    }
    const customs = customModules;
    workspace = normalizeWorkspace({
      workflows: defaultWorkflows(),
      customModules: customs,
    });
    expandedNodes = new Set();
    insertIndex = null;
    renderAll();
    saveWorkspace();
    showStatus("已恢复示例工作区");
  }

  function clearNodes() {
    const workflow = activeWorkflow();
    if (!workflow.nodes.length) return;
    if (
      !window.confirm(
        `清空当前流程的 ${workflow.nodes.length} 个节点？流程名称与参数会保留。`,
      )
    ) {
      return;
    }
    workflow.nodes = [];
    expandedNodes = new Set();
    insertIndex = null;
    renderAll();
    saveWorkspace();
    showStatus("当前流程节点已清空");
  }

  /* ------------------------------------------------------------------ */
  /* Templates                                                           */
  /* ------------------------------------------------------------------ */

  function renderTemplates() {
    els.templateGrid.innerHTML = "";
    for (const preset of FLOW.presets) {
      const card = document.createElement("article");
      card.className = "template-card";
      const head = document.createElement("div");
      head.className = "template-card-head";
      const title = document.createElement("h3");
      title.className = "template-title";
      title.textContent = preset.title;
      const tag = document.createElement("span");
      tag.className = "template-tag";
      tag.textContent = preset.tag || "模板";
      head.append(title, tag);

      const summary = document.createElement("p");
      summary.className = "template-summary";
      summary.textContent = preset.summary;

      const modules = document.createElement("div");
      modules.className = "template-modules";
      for (const id of FLOW.executionOrder) {
        if (!preset.modules[id] || !preset.modules[id].enabled) continue;
        const module = getModule(id);
        if (!module) continue;
        const chip = document.createElement("span");
        chip.className = "template-module";
        chip.textContent = module.title;
        modules.append(chip);
      }

      const actions = document.createElement("div");
      actions.className = "template-actions";
      const create = document.createElement("button");
      create.type = "button";
      create.dataset.templateNew = preset.id;
      create.textContent = "新建流程";
      const replace = document.createElement("button");
      replace.type = "button";
      replace.className = "ghost-button";
      replace.dataset.templateReplace = preset.id;
      replace.textContent = "替换当前";
      actions.append(create, replace);

      card.append(head, summary, modules, actions);
      els.templateGrid.append(card);
    }
  }

  function openTemplates() {
    renderTemplates();
    openDialog(els.templatesDialog);
  }

  function applyTemplateNew(presetId) {
    const preset = FLOW.presets.find((item) => item.id === presetId);
    if (!preset) return;
    const workflow = createWorkflow(
      preset.title,
      nodesFromPreset(presetId),
      activeWorkflow().params,
    );
    expandedNodes = new Set();
    insertIndex = null;
    closeDialog(els.templatesDialog);
    renderAll();
    saveWorkspace();
    showStatus(`已从模板新建「${workflow.name}」`);
  }

  function applyTemplateReplace(presetId) {
    const preset = FLOW.presets.find((item) => item.id === presetId);
    if (!preset) return;
    const workflow = activeWorkflow();
    if (
      workflow.nodes.length &&
      !window.confirm(
        `用模板「${preset.title}」替换当前流程的 ${workflow.nodes.length} 个节点？`,
      )
    ) {
      return;
    }
    workflow.nodes = nodesFromPreset(presetId);
    expandedNodes = new Set();
    insertIndex = null;
    closeDialog(els.templatesDialog);
    renderAll();
    saveWorkspace();
    showStatus(`已替换为「${preset.title}」模板`);
  }

  /* ------------------------------------------------------------------ */
  /* Custom-module editor                                                */
  /* ------------------------------------------------------------------ */

  function populateEditorSelects() {
    els.editorGroup.innerHTML = "";
    for (const group of FLOW.groups) {
      const option = document.createElement("option");
      option.value = group.id;
      option.textContent = group.title;
      els.editorGroup.append(option);
    }
  }

  function updateEditorKind() {
    const local = els.editorKind.value === "local";
    els.editorSetupRow.hidden = !local;
  }

  function openEditor(def, options = {}) {
    const existing = Boolean(
      def && customModules.some((item) => item.id === def.id),
    );
    els.editorId.value = existing ? def.id : "";
    els.editorName.value = def ? def.title : "";
    els.editorSummary.value = def ? def.summary || "" : "";
    els.editorGroup.value = def ? def.group : "produce";
    els.editorKind.value = def ? def.kind : "cloud";
    els.editorCommand.value = def ? def.command : "";
    els.editorNote.value = def ? def.note || "" : "";
    els.editorRequiresVideo.checked = Boolean(def && def.requiresVideo);
    els.editorSetup.checked = def ? def.setup !== false : true;
    els.editorAdd.checked = options.addNow !== undefined
      ? Boolean(options.addNow)
      : !existing;
    els.editorDelete.hidden = !existing;
    els.editorHeading.textContent = existing
      ? "编辑自定义模块"
      : def
        ? "另存为自定义模块"
        : "新建自定义模块";
    setEditorStatus("", false);
    updateEditorKind();
    openDialog(els.moduleDialog);
    window.setTimeout(() => els.editorName.focus(), 0);
  }

  function closeEditor() {
    closeDialog(els.moduleDialog);
    setEditorStatus("", false);
  }

  function readEditor() {
    return {
      title: els.editorName.value.trim().slice(0, 80),
      summary: els.editorSummary.value.trim().slice(0, 300),
      group: els.editorGroup.value,
      kind: els.editorKind.value === "local" ? "local" : "cloud",
      command: els.editorCommand.value.trim().slice(0, 4000),
      note: els.editorNote.value.trim().slice(0, 500),
      requiresVideo: els.editorRequiresVideo.checked,
      setup: els.editorSetup.checked,
      addNow: els.editorAdd.checked,
    };
  }

  function saveEditor(event) {
    if (event) event.preventDefault();
    const data = readEditor();
    if (!data.title) {
      setEditorStatus("请填写模块名称。", false);
      els.editorName.focus();
      return;
    }
    if (!data.command) {
      setEditorStatus("请填写要执行的命令。", false);
      els.editorCommand.focus();
      return;
    }

    const existingId = els.editorId.value;
    const index = customModules.findIndex((item) => item.id === existingId);
    const id = index >= 0 ? existingId : makeCustomId();
    const def = {
      id,
      title: data.title,
      summary: data.summary,
      group: data.group,
      kind: data.kind,
      command: data.command,
      note: data.note,
      requiresVideo: data.requiresVideo,
      setup: data.kind === "local" ? data.setup : false,
    };
    if (index >= 0) customModules[index] = def;
    else customModules.push(def);

    if (data.addNow) {
      const workflow = activeWorkflow();
      const node = makeNode(id);
      if (node) {
        const at =
          insertIndex === null
            ? workflow.nodes.length
            : Math.max(0, Math.min(insertIndex, workflow.nodes.length));
        workflow.nodes.splice(at, 0, node);
        expandedNodes.add(node.id);
        insertIndex = null;
      }
    }

    saveWorkspace();
    renderAll();
    closeEditor();
    showStatus(index >= 0 ? "自定义模块已更新" : "自定义模块已添加");
  }

  function deleteCustomModule(moduleId) {
    const def = customModules.find((item) => item.id === moduleId);
    if (!def) return;
    let used = 0;
    for (const workflow of workspace.workflows) {
      used += workflow.nodes.filter(
        (node) => node.moduleId === moduleId,
      ).length;
    }
    const message = used
      ? `删除自定义模块「${def.title}」？它也会从 ${used} 个流程节点中移除。`
      : `删除自定义模块「${def.title}」？`;
    if (!window.confirm(message)) return;

    customModules = customModules.filter((item) => item.id !== moduleId);
    for (const workflow of workspace.workflows) {
      workflow.nodes = workflow.nodes.filter(
        (node) => node.moduleId !== moduleId,
      );
    }
    if (els.editorId.value === moduleId) closeEditor();
    saveWorkspace();
    renderAll();
    showStatus("自定义模块已删除");
  }

  function cloneModule(moduleId) {
    const module = FLOW.modules.find((item) => item.id === moduleId);
    if (!module) return;
    const existingNode = activeWorkflow().nodes.find(
      (node) => node.moduleId === moduleId,
    );
    const opts = existingNode
      ? { ...moduleDefaults(module), ...existingNode.options }
      : moduleDefaults(module);
    const ctx = buildContext(activeWorkflow());
    const result = module.build({ ...ctx, opts });
    if (!result) return;
    openEditor(
      {
        id: "",
        title: `${module.title}（自定义）`,
        summary: module.summary,
        group: module.group,
        kind: result.kind || module.kind,
        command: result.code,
        note: result.note || "",
        requiresVideo: module.requiresVideo,
        setup: true,
      },
      { addNow: true },
    );
    setEditorStatus("已载入当前命令；保存后加入模块库。", true);
  }

  /* ------------------------------------------------------------------ */
  /* Drag and drop                                                       */
  /* ------------------------------------------------------------------ */

  function clearDropMarkers() {
    for (const element of els.flowCanvas.querySelectorAll(
      ".drag-before, .drag-after, .is-drop-target",
    )) {
      element.classList.remove("drag-before", "drag-after", "is-drop-target");
    }
  }

  function clearDragState() {
    for (const card of els.flowCanvas.querySelectorAll(".node-card")) {
      card.classList.remove("is-dragging");
    }
    clearDropMarkers();
    draggedNodeId = null;
    dragOverIndex = null;
  }

  function handleDragStart(event) {
    const handle = event.target.closest("[data-drag-handle]");
    if (!handle) {
      event.preventDefault();
      return;
    }
    const card = handle.closest(".node-card");
    if (!card) return;
    draggedNodeId = card.dataset.nodeId;
    dragOverIndex = activeWorkflow().nodes.findIndex(
      (node) => node.id === draggedNodeId,
    );
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", draggedNodeId);
    }
    card.classList.add("is-dragging");
  }

  function handleDragOver(event) {
    if (!draggedNodeId) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    clearDropMarkers();
    const workflow = activeWorkflow();
    const card = event.target.closest(".node-card");
    if (card) {
      const rect = card.getBoundingClientRect();
      const after = event.clientY > rect.top + rect.height / 2;
      const index = workflow.nodes.findIndex(
        (node) => node.id === card.dataset.nodeId,
      );
      dragOverIndex = index + (after ? 1 : 0);
      card.classList.add(after ? "drag-after" : "drag-before");
      return;
    }
    const gap = event.target.closest(".node-gap");
    if (gap) {
      const button = gap.querySelector("[data-insert-index]");
      dragOverIndex = button
        ? Number(button.dataset.insertIndex)
        : workflow.nodes.length;
      gap.classList.add("is-drop-target");
      return;
    }
    dragOverIndex = workflow.nodes.length;
  }

  function handleDrop(event) {
    if (!draggedNodeId) return;
    event.preventDefault();
    const workflow = activeWorkflow();
    const from = workflow.nodes.findIndex(
      (node) => node.id === draggedNodeId,
    );
    if (from < 0) {
      clearDragState();
      return;
    }
    let to =
      dragOverIndex === null ? workflow.nodes.length : dragOverIndex;
    const [node] = workflow.nodes.splice(from, 1);
    if (to > from) to -= 1;
    to = Math.max(0, Math.min(to, workflow.nodes.length));
    workflow.nodes.splice(to, 0, node);
    clearDragState();
    saveWorkspace();
    renderCanvas();
    renderPlan();
    renderTabs();
    renderWorkflowHeader();
    showStatus("节点顺序已更新");
  }

  /* ------------------------------------------------------------------ */
  /* Events                                                              */
  /* ------------------------------------------------------------------ */

  function bindEvents() {
    els.workflowTabs.addEventListener("click", (event) => {
      const tab = event.target.closest("[data-workflow-id]");
      if (tab) switchWorkflow(tab.dataset.workflowId);
    });
    els.newWorkflow.addEventListener("click", newWorkflow);
    els.duplicateWorkflow.addEventListener("click", duplicateWorkflow);
    els.deleteWorkflow.addEventListener("click", deleteWorkflow);
    els.workflowName.addEventListener("input", handleWorkflowNameInput);
    els.workflowName.addEventListener("change", handleWorkflowNameChange);

    const paramBindings = [
      [els.videoInput, "video"],
      [els.outDirInput, "outDir"],
      [els.repoInput, "repo"],
      [els.pythonInput, "pythonPath"],
      [els.titleInput, "title"],
      [els.eventDateInput, "eventDate"],
      [els.sourceUrlInput, "sourceUrl"],
    ];
    for (const [element, key] of paramBindings) {
      element.addEventListener("input", () => {
        const workflow = activeWorkflow();
        workflow.params[key] = element.value;
        if (key === "video") updateVideoHint();
        if (key === "pythonPath") updatePythonHint();
        saveWorkspace();
        renderPlan();
      });
    }
    els.resetPython.addEventListener("click", () => {
      const workflow = activeWorkflow();
      workflow.params.pythonPath = DEFAULTS.pythonPath;
      els.pythonInput.value = DEFAULTS.pythonPath;
      updatePythonHint();
      saveWorkspace();
      renderPlan();
      showStatus("已恢复默认 Anaconda 路径");
    });

    els.paletteSearch.addEventListener("input", () => {
      paletteQuery = els.paletteSearch.value;
      renderPalette();
    });
    els.cancelInsert.addEventListener("click", () => {
      insertIndex = null;
      updateInsertHint();
    });
    els.newModule.addEventListener("click", () => openEditor(null));
    els.paletteGroups.addEventListener("click", (event) => {
      const add = event.target.closest("[data-add-module]");
      if (add) {
        addModule(add.dataset.addModule);
        return;
      }
      const cloneButton = event.target.closest("[data-clone-module]");
      if (cloneButton) {
        cloneModule(cloneButton.dataset.cloneModule);
        return;
      }
      const edit = event.target.closest("[data-edit-module]");
      if (edit) {
        const def = customModules.find(
          (item) => item.id === edit.dataset.editModule,
        );
        if (def) openEditor(def);
        return;
      }
      const remove = event.target.closest("[data-delete-module]");
      if (remove) deleteCustomModule(remove.dataset.deleteModule);
    });

    els.flowCanvas.addEventListener("click", (event) => {
      const gap = event.target.closest("[data-insert-index]");
      if (gap) {
        setInsertIndex(Number(gap.dataset.insertIndex));
        return;
      }
      if (event.target.closest("[data-focus-palette]")) {
        els.paletteSearch.focus();
        els.paletteSearch.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
        return;
      }
      const optionsToggle = event.target.closest("[data-toggle-options]");
      if (optionsToggle) {
        const nodeId = optionsToggle.dataset.toggleOptions;
        if (expandedNodes.has(nodeId)) expandedNodes.delete(nodeId);
        else expandedNodes.add(nodeId);
        const box = els.flowCanvas.querySelector(`#options-${nodeId}`);
        if (box) box.hidden = !expandedNodes.has(nodeId);
        optionsToggle.setAttribute(
          "aria-expanded",
          expandedNodes.has(nodeId) ? "true" : "false",
        );
        return;
      }
      const up = event.target.closest("[data-move-up]");
      if (up) {
        moveNode(up.dataset.moveUp, -1);
        return;
      }
      const down = event.target.closest("[data-move-down]");
      if (down) {
        moveNode(down.dataset.moveDown, 1);
        return;
      }
      const duplicate = event.target.closest("[data-duplicate-node]");
      if (duplicate) {
        duplicateNode(duplicate.dataset.duplicateNode);
        return;
      }
      const remove = event.target.closest("[data-delete-node]");
      if (remove) {
        deleteNode(remove.dataset.deleteNode);
        return;
      }
      const edit = event.target.closest("[data-edit-node]");
      if (edit) {
        const node = activeWorkflow().nodes.find(
          (item) => item.id === edit.dataset.editNode,
        );
        if (!node) return;
        const def = customModules.find((item) => item.id === node.moduleId);
        if (def) openEditor(def);
      }
    });

    els.flowCanvas.addEventListener("change", (event) => {
      const enabled = event.target.closest("[data-node-enabled]");
      if (enabled) {
        setNodeEnabled(enabled.dataset.nodeEnabled, enabled.checked);
        return;
      }
      const control = event.target.closest("[data-option-key]");
      if (!control) return;
      if (
        control.tagName === "SELECT" ||
        (control.tagName === "INPUT" && control.type === "checkbox")
      ) {
        updateNodeOption(
          control.dataset.optionNode,
          control.dataset.optionKey,
          readOptionControl(control),
        );
      }
    });

    els.flowCanvas.addEventListener("input", (event) => {
      const control = event.target.closest("[data-option-key]");
      if (!control) return;
      if (control.tagName !== "INPUT") return;
      if (control.type === "checkbox" || control.type === "select") return;
      updateNodeOption(
        control.dataset.optionNode,
        control.dataset.optionKey,
        readOptionControl(control),
      );
    });

    els.flowCanvas.addEventListener("dragstart", handleDragStart);
    els.flowCanvas.addEventListener("dragover", handleDragOver);
    els.flowCanvas.addEventListener("drop", handleDrop);
    els.flowCanvas.addEventListener("dragend", clearDragState);

    els.expandAll.addEventListener("click", () => {
      expandedNodes = new Set(
        activeWorkflow().nodes.map((node) => node.id),
      );
      renderCanvas();
    });
    els.collapseAll.addEventListener("click", () => {
      expandedNodes = new Set();
      renderCanvas();
    });
    els.clearNodes.addEventListener("click", clearNodes);

    els.commandPlan.addEventListener("click", (event) => {
      const copyStep = event.target.closest("[data-copy-step]");
      if (copyStep) {
        const step = currentSteps[Number(copyStep.dataset.copyStep)];
        if (step) copyText(formatStepCode(step), "单步命令已复制");
        return;
      }
      if (event.target.closest("[data-copy-env]")) {
        copyText(
          buildContext(activeWorkflow()).pySetup,
          "Anaconda 环境命令已复制",
        );
      }
    });
    els.copyPlan.addEventListener("click", () => {
      copyText(buildRunbook(), "全部命令已复制");
    });
    els.shareFlow.addEventListener("click", shareLink);
    els.exportFlow.addEventListener("click", exportFlow);
    els.importFlow.addEventListener("click", () => els.importFile.click());
    els.importFile.addEventListener("change", importFlowFile);
    els.resetFlow.addEventListener("click", resetWorkspace);

    els.openTemplates.addEventListener("click", openTemplates);
    els.closeTemplates.addEventListener("click", () =>
      closeDialog(els.templatesDialog),
    );
    els.templateGrid.addEventListener("click", (event) => {
      const create = event.target.closest("[data-template-new]");
      if (create) {
        applyTemplateNew(create.dataset.templateNew);
        return;
      }
      const replace = event.target.closest("[data-template-replace]");
      if (replace) applyTemplateReplace(replace.dataset.templateReplace);
    });

    els.moduleForm.addEventListener("submit", saveEditor);
    els.editorKind.addEventListener("change", updateEditorKind);
    els.editorCancel.addEventListener("click", closeEditor);
    els.editorClose.addEventListener("click", closeEditor);
    els.editorDelete.addEventListener("click", () => {
      if (els.editorId.value) deleteCustomModule(els.editorId.value);
    });

    for (const dialog of [els.templatesDialog, els.moduleDialog]) {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closeDialog(dialog);
      });
    }
  }

  function init() {
    populateEditorSelects();
    updateEditorKind();
    renderAll();
    bindEvents();
    // Persist migrations and share-link imports immediately, otherwise a
    // refresh would drop a workflow that only arrived via ?flow=.
    saveWorkspace();
    if (pendingStatus) showStatus(pendingStatus);
  }

  workspace = loadWorkspace();
  init();
})();





