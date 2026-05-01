#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const TODAY = new Date().toISOString().slice(0, 10);
const SEMANTICS_JSON = path.join(ROOT, "backend", "logs", "fsu_reverse", `tower-web-fsu-semantics-${TODAY}.json`);
const ANNOTATION_FILE = path.join(ROOT, "backend", "app", "modules", "fsu_gateway", "parser", "dsc-rds-annotations.js");
const OUTPUT_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets");

function rel(file) {
  return path.relative(ROOT, file).replace(/\\/g, "/");
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readJson(file) {
  if (!fs.existsSync(file)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function unique(items) {
  return [...new Set(items.filter(Boolean))];
}

function evidenceSnippets(rows, matcher, limit = 12) {
  return rows
    .filter((row) => matcher(`${row.term || ""} ${row.keyword || ""} ${row.nearbyText || ""} ${row.inferredMeaning || ""}`))
    .slice(0, limit)
    .map((row) => ({
      source: row.sourceFile || row.urlPath || "",
      term: row.term || row.keyword || "",
      text: String(row.nearbyText || "").slice(0, 260),
      confidence: row.confidence || "unknown",
    }));
}

function loadAnnotationsFresh() {
  delete require.cache[require.resolve("../app/modules/fsu_gateway/parser/dsc-rds-annotations")];
  return require("../app/modules/fsu_gateway/parser/dsc-rds-annotations");
}

function writeAnnotationFile(updated) {
  const content = `"use strict";

const CHANNEL_ANNOTATIONS = ${JSON.stringify(updated.CHANNEL_ANNOTATIONS, null, 2)};

const FRAME_CLASS_ANNOTATIONS = ${JSON.stringify(updated.FRAME_CLASS_ANNOTATIONS, null, 2)};

const TYPE_A_ANNOTATIONS = ${JSON.stringify(updated.TYPE_A_ANNOTATIONS, null, 2)};

function getFrameClassAnnotation(frameClass) {
  return FRAME_CLASS_ANNOTATIONS[frameClass] || null;
}

function getTypeAAnnotation(typeA) {
  return TYPE_A_ANNOTATIONS[String(typeA || "").toLowerCase()] || null;
}

function getChannelAnnotation(channel) {
  return CHANNEL_ANNOTATIONS[channel] || null;
}

module.exports = {
  CHANNEL_ANNOTATIONS,
  FRAME_CLASS_ANNOTATIONS,
  TYPE_A_ANNOTATIONS,
  getChannelAnnotation,
  getFrameClassAnnotation,
  getTypeAAnnotation,
};
`;
  fs.writeFileSync(ANNOTATION_FILE, content, "utf8");
}

function appendUniqueArray(obj, key, values) {
  const current = Array.isArray(obj[key]) ? obj[key] : [];
  const merged = [...current];
  for (const value of values) {
    const probe = typeof value === "string" ? value : JSON.stringify(value);
    if (!merged.some((item) => (typeof item === "string" ? item : JSON.stringify(item)) === probe)) {
      merged.push(value);
    }
  }
  obj[key] = merged;
}

function updateAnnotations(semantics, annotations) {
  const direct = semantics.dscRdsDirectEvidence || [];
  const hits = semantics.keywordHits || [];
  const objects = semantics.fsuBusinessObjects || [];
  const allEvidenceRows = [...direct, ...hits];

  const dscEvidence = evidenceSnippets(allEvidenceRows, (text) => /DSC|DscIp|DscPort/i.test(text));
  const rdsEvidence = evidenceSnippets(allEvidenceRows, (text) => /RDS|RDSIp|RDSHeartBeat|RDSPort/i.test(text));
  const realtimeEvidence = evidenceSnippets(allEvidenceRows, (text) => /实时|实时数据|遥测|遥信|RealData/i.test(text));
  const registerEvidence = evidenceSnippets(allEvidenceRows, (text) => /注册|登录|心跳|监控中心|上级平台|服务地址/i.test(text));
  const alarmEvidence = evidenceSnippets(allEvidenceRows, (text) => /告警|事件|遥控|遥调|命令/i.test(text));

  const webSummary = {
    generatedAt: semantics.generatedAt,
    sourceReport: rel(SEMANTICS_JSON),
    hasDirectDscEvidence: semantics.directEvidenceSummary?.hasDirectDscEvidence || false,
    hasDirectRdsEvidence: semantics.directEvidenceSummary?.hasDirectRdsEvidence || false,
    hasBusinessEvidence: objects.length > 0 || hits.some((hit) => /FSU|动环|实时|告警|遥测|遥信|点位|设备/.test(`${hit.keyword || ""} ${hit.nearbyText || ""}`)),
    dscEvidence,
    rdsEvidence,
    realtimeEvidence,
    registerEvidence,
    alarmEvidence,
    caveat: "铁塔网页证据只作为业务语义侧证，不能直接等价为 FSU 私有 UDP payload offset 或 typeA/opcode。",
  };

  const updated = JSON.parse(JSON.stringify(annotations));

  if (updated.CHANNEL_ANNOTATIONS?.UDP_DSC) {
    appendUniqueArray(updated.CHANNEL_ANNOTATIONS.UDP_DSC, "evidence", dscEvidence.map((row) => `铁塔网页侧证: ${row.term} ${row.text}`));
    appendUniqueArray(updated.CHANNEL_ANNOTATIONS.UDP_DSC, "sourceHints", dscEvidence.length ? ["tower_web_semantics"] : []);
    updated.CHANNEL_ANNOTATIONS.UDP_DSC.towerWebEvidence = dscEvidence;
  }

  if (updated.CHANNEL_ANNOTATIONS?.UDP_RDS) {
    appendUniqueArray(updated.CHANNEL_ANNOTATIONS.UDP_RDS, "evidence", [...rdsEvidence, ...realtimeEvidence].map((row) => `铁塔网页侧证: ${row.term} ${row.text}`));
    appendUniqueArray(updated.CHANNEL_ANNOTATIONS.UDP_RDS, "sourceHints", rdsEvidence.length || realtimeEvidence.length ? ["tower_web_semantics"] : []);
    updated.CHANNEL_ANNOTATIONS.UDP_RDS.towerWebEvidence = [...rdsEvidence, ...realtimeEvidence];
  }

  for (const frameClass of Object.keys(updated.FRAME_CLASS_ANNOTATIONS || {})) {
    const anno = updated.FRAME_CLASS_ANNOTATIONS[frameClass];
    const related = [];
    if (frameClass.startsWith("DSC_CONFIG")) related.push(...registerEvidence, ...dscEvidence);
    if (frameClass.startsWith("DSC_SHORT")) related.push(...registerEvidence, ...dscEvidence);
    if (frameClass.startsWith("RDS_SHORT")) related.push(...rdsEvidence, ...realtimeEvidence);
    if (alarmEvidence.length) {
      appendUniqueArray(anno, "confidenceNotes", [
        "铁塔网页中的告警/事件/控制类术语仅作为未来业务帧识别侧证，不能强行套到当前 4 类帧。",
      ]);
    }
    appendUniqueArray(anno, "sourceHints", related.length ? ["tower_web_semantics"] : []);
    appendUniqueArray(anno, "confidenceNotes", related.length ? [
      "铁塔网页证据支持相关业务概念，但不确认二进制 typeA/opcode 或 payload offset。",
    ] : [
      "本次本地网页资料未提供该帧类型的直接新增证据。",
    ]);
    anno.towerWebEvidence = related;
  }

  return { updated, webSummary };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push(`# DSC/RDS Tower Web Annotation ${TODAY}`);
  lines.push("");
  lines.push("## 报告摘要");
  lines.push(`- 分析时间: ${report.generatedAt}`);
  lines.push(`- 输入文件目录: ${report.inputDir}`);
  lines.push(`- 扫描文件数量: ${report.scan.totalFiles}`);
  lines.push(`- 是否发现 DSC 直接证据: ${report.summary.hasDirectDscEvidence}`);
  lines.push(`- 是否发现 RDS 直接证据: ${report.summary.hasDirectRdsEvidence}`);
  lines.push(`- 是否发现 FSU/实时数据/告警/点位业务证据: ${report.summary.hasBusinessEvidence}`);
  lines.push(`- 是否有敏感字段脱敏: ${report.safety.sensitiveFieldsRedacted}`);
  lines.push("");
  lines.push("## DSC/RDS 直接证据");
  if (!report.directEvidence.dsc.length && !report.directEvidence.rds.length) {
    lines.push("- 未发现 DSC/RDS 直接字样；铁塔平台本地资料未直接证明 DSC/RDS 命名。");
  }
  for (const item of report.directEvidence.dsc) lines.push(`- DSC: ${item.term} @ ${item.source}: ${item.text}`);
  for (const item of report.directEvidence.rds) lines.push(`- RDS: ${item.term} @ ${item.source}: ${item.text}`);
  lines.push("");
  lines.push("## FSU 业务语义证据");
  if (!report.businessEvidence.length) lines.push("- 未发现本地网页业务字段证据。");
  for (const item of report.businessEvidence.slice(0, 80)) {
    lines.push(`- ${item.objectType}: ${item.fieldName || item.chineseLabel} (${item.inferredMeaning})`);
  }
  lines.push("");
  lines.push("## 当前 4 类 frameClass 注释复核");
  for (const row of report.frameClassReview) {
    lines.push(`- ${row.frameClass}: ${row.chineseName}, confidence=${row.currentConfidence}, webSupport=${row.webSupport}, caveat=${row.caveat}`);
  }
  lines.push("");
  lines.push("## 证据交叉验证表");
  for (const row of report.crossValidation) {
    lines.push(`- ${row.conclusion}: confidence=${row.confidence}; caveat=${row.caveat}`);
  }
  lines.push("");
  lines.push("## 不能确认的内容");
  for (const item of report.notConfirmed) lines.push(`- ${item}`);
  lines.push("");
  lines.push("## 后续建议");
  for (const item of report.nextSteps) lines.push(`- ${item}`);
  lines.push("");
  lines.push("## 安全确认");
  for (const item of report.safetyConfirmations) lines.push(`- ${item}`);
  return lines.join("\n");
}

function main() {
  ensureDir(OUTPUT_DIR);
  const semantics = readJson(SEMANTICS_JSON);
  if (!semantics) {
    throw new Error(`semantic report not found: ${rel(SEMANTICS_JSON)}`);
  }

  const annotations = loadAnnotationsFresh();
  const { updated, webSummary } = updateAnnotations(semantics, annotations);
  writeAnnotationFile(updated);

  const report = {
    generatedAt: new Date().toISOString(),
    inputDir: semantics.inputDir,
    sourceSemanticReport: rel(SEMANTICS_JSON),
    scan: semantics.inputOverview,
    summary: {
      hasDirectDscEvidence: webSummary.hasDirectDscEvidence,
      hasDirectRdsEvidence: webSummary.hasDirectRdsEvidence,
      hasBusinessEvidence: webSummary.hasBusinessEvidence,
      annotationFileUpdated: rel(ANNOTATION_FILE),
    },
    safety: {
      sensitiveFieldsRedacted: semantics.inputOverview.sensitiveFieldsRedacted > 0,
      noUdpSent: true,
      noAckAdded: true,
      sendOneShotAckNotRun: true,
      gatewayReplyLogicUnchanged: true,
      businessTablesUnchanged: true,
    },
    directEvidence: {
      dsc: webSummary.dscEvidence,
      rds: webSummary.rdsEvidence,
      dscIpRdsIpRdsHeartbeat: [...webSummary.dscEvidence, ...webSummary.rdsEvidence].filter((row) => /DscIp|RDSIp|RDSHeartBeat/i.test(`${row.term} ${row.text}`)),
      port7000or9000: [...webSummary.dscEvidence, ...webSummary.rdsEvidence].filter((row) => /7000|9000/.test(`${row.term} ${row.text}`)),
    },
    businessEvidence: semantics.fsuBusinessObjects || [],
    frameClassReview: Object.values(updated.FRAME_CLASS_ANNOTATIONS).map((anno) => ({
      frameClass: anno.frameClass,
      semanticClass: anno.semanticClass,
      chineseName: anno.chineseName,
      currentConfidence: anno.confidence,
      webSupport: anno.towerWebEvidence && anno.towerWebEvidence.length ? "business-side supporting evidence only" : "no direct web evidence in local files",
      caveat: "网页字段不能直接等价为 typeA/opcode 或 payload offset。",
    })),
    crossValidation: [
      {
        conclusion: "UDP_DSC 是主控/注册/配置/心跳相关候选通道。",
        packetEvidence: "UDP_DSC 出现 24/209/245 周期帧，209/245 含 URI。",
        firmwareEvidence: "SiteUnit 存在 LoginToDSC、Register OK、SendHeartbeat、ParseData。",
        webEvidence: webSummary.dscEvidence.length ? "发现 DSC/注册/心跳/服务地址类网页侧证。" : "本地网页资料未直接发现 DSC 证据。",
        confidence: "medium",
        caveat: "仍不能确认 ACK 格式和 typeA 官方语义。",
      },
      {
        conclusion: "UDP_RDS 与实时数据/保活相关。",
        packetEvidence: "UDP_RDS 当前只有 30 字节周期短帧。",
        firmwareEvidence: "SiteUnit 存在 RDS/RealData/SendRDSHeartbeat 相关字符串侧证。",
        webEvidence: webSummary.rdsEvidence.length || webSummary.realtimeEvidence.length ? "发现 RDS/实时数据类网页侧证。" : "本地网页资料未直接发现 RDS/实时数据证据。",
        confidence: "medium",
        caveat: "当前未出现 RDS 业务帧，不能确认 payload 结构。",
      },
      {
        conclusion: "当前 FSU 尚未进入业务数据阶段。",
        packetEvidence: "只出现 4 类已知周期帧，UNKNOWN=0，无新 typeA/length/frameClass。",
        firmwareEvidence: "登录/注册响应路径仍需 ACK 才可能切换阶段。",
        webEvidence: "网页业务字段即使存在，也只说明业务层概念。",
        confidence: "high",
        caveat: "状态判断来自抓包观察，不来自铁塔网页。",
      },
    ],
    notConfirmed: [
      "ACK 格式不能由网页资料确认。",
      "typeA/opcode 不能由网页资料完整确认。",
      "DSC_CONFIG_209/245 每个 payload offset 不能由网页资料直接确认。",
      "RDS 实时业务 payload 当前未出现。",
      "铁塔页面业务字段不能直接等价于 FSU 私有 UDP payload offset。",
    ],
    nextSteps: [
      "继续分析 SiteUnit 中 LoginToDSC、SendHeartbeat、SendRDSHeartbeat、SendRealData、SendEventData、SendCmdData。",
      "继续分析 DSC_CONFIG_209/245 差异。",
      "继续提取铁塔平台点位字段，用于未来 RDS 业务帧出现后的 SignalId/DeviceId 对齐。",
      "不建议当前线上 ACK 实验，除非 ACK 结构有进一步证据。",
    ],
    safetyConfirmations: [
      "未修改铁塔平台配置。",
      "未点击保存/提交/下发/测试/重启/清告警/遥控等按钮。",
      "未发起 POST/PUT/DELETE/PATCH 请求。",
      "未发送 UDP。",
      "未新增 ACK。",
      "未运行 send-one-shot-ack.js。",
      "未修改 fsu-gateway 实时回包逻辑。",
      "未写业务主表。",
      "未做 XML/JSON 转换。",
      "已脱敏 Cookie/Token/Authorization/Session/loginName 等敏感信息。",
    ],
  };

  const jsonPath = path.join(OUTPUT_DIR, `dsc-rds-tower-web-annotation-${TODAY}.json`);
  const mdPath = path.join(OUTPUT_DIR, `dsc-rds-tower-web-annotation-${TODAY}.md`);
  fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2), "utf8");
  fs.writeFileSync(mdPath, renderMarkdown(report), "utf8");

  console.log(JSON.stringify({
    jsonPath: rel(jsonPath),
    mdPath: rel(mdPath),
    annotationFileUpdated: rel(ANNOTATION_FILE),
    hasDirectDscEvidence: report.summary.hasDirectDscEvidence,
    hasDirectRdsEvidence: report.summary.hasDirectRdsEvidence,
    hasBusinessEvidence: report.summary.hasBusinessEvidence,
  }, null, 2));
}

main();
