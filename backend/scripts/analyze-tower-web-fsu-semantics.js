#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const INPUT_DIR = path.join(ROOT, "backend", "fixtures", "tower_web");
const OUTPUT_DIR = path.join(ROOT, "backend", "logs", "fsu_reverse");
const TODAY = new Date().toISOString().slice(0, 10);

const EXTENSIONS = new Set([".html", ".htm", ".js", ".json", ".xml", ".har", ".txt", ".ini", ".cfg", ".conf", ".properties", ".csv"]);

const KEYWORDS = [
  "FSU", "SC", "B接口", "B 接口", "动环", "动环监控", "监控单元", "监控中心", "上级平台", "北向", "南向",
  "铁塔", "平台", "接口", "协议", "注册", "登录", "心跳", "上报", "实时", "实时数据", "历史数据", "告警",
  "事件", "配置", "服务地址", "服务器地址", "DSC", "Dsc", "DscIp", "DscIP", "DscPort", "RDS", "Rds",
  "RDSIp", "RDSIP", "RDSPort", "RDSHeartBeat", "HeartBeat", "Heartbeat", "SendHeartbeat", "SendRDSHeartbeat",
  "RealData", "SendRealData", "Register", "Login", "Ack", "ACK", "站址", "站点", "机房", "设备", "信号",
  "点位", "采集量", "遥测", "遥信", "遥控", "遥调", "门禁", "水浸", "温度", "湿度", "市电", "电池",
  "空调", "开关电源", "DeviceId", "DeviceID", "SignalId", "SignalID", "FsuId", "FSUID", "SiteId", "SiteID",
  "ChannelNo", "ChannelID", "RoomId", "StationId", "AlarmId", "AlarmLevel", "SignalName", "DeviceName",
  "Value", "Unit", "Status", "7000", "9000", "6000", "6001", "6002", "6003",
];

const PROHIBITED_METHODS = new Set(["POST", "PUT", "DELETE", "PATCH"]);
const PROHIBITED_ENDPOINT_TERMS = [
  "save", "set", "update", "apply", "submit", "restart", "reboot", "delete", "remove", "control",
  "remoteControl", "test", "sync", "upload", "upgrade", "clear", "reset", "issue", "command",
  "config", "modify", "create", "add",
];

const OBJECT_HINTS = [
  ["FSU 编号", /fsu(id|code)?|fsuid|fsu编号|监控单元/i],
  ["站址编号", /site(id|code)?|station(id|code)?|站址|站点/i],
  ["设备编号", /device(id|code)?|设备/i],
  ["信号编号", /signal(id|code)?|点位|信号/i],
  ["遥测点", /遥测|telemetry|yc/i],
  ["遥信点", /遥信|status|yx/i],
  ["遥控点", /遥控|control|yk/i],
  ["遥调点", /遥调|adjust|yt/i],
  ["告警点", /alarm|告警/i],
  ["实时值", /real|实时|value|当前值/i],
  ["单位", /unit|单位/i],
  ["告警等级", /level|等级/i],
  ["告警状态", /alarm.*status|告警状态/i],
];

let sensitiveFieldsRedacted = 0;

const GENERATED_CAPTURE_METADATA = new Set([
  "capture-summary.json",
  "static-resources.json",
  "readonly-get-responses.json",
  "extracted-keywords.json",
  "redaction-report.json",
]);

const COMMON_VENDOR_RESOURCE_HINTS = [
  "jquery",
  "bootstrap",
  "crypto-js",
  "jsencrypt",
  "aes",
];

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function rel(file) {
  return path.relative(ROOT, file).replace(/\\/g, "/");
}

function isPrivateIp(ip) {
  return /^10\./.test(ip) || /^192\.168\./.test(ip) || /^172\.(1[6-9]|2\d|3[0-1])\./.test(ip) || /^127\./.test(ip);
}

function redactSensitive(text) {
  if (text === null || text === undefined) return text;
  let output = String(text);
  const before = output;
  output = output.replace(/(Cookie|Authorization|JSESSIONID|session(?:id)?|token|access_token|refresh_token|password|passwd|pwd|loginName|mobile|phone|手机号|身份证)(["'\s:=]+)([^&\s"',;<>}]+)/gi, (_m, key, sep) => `${key}${sep}[REDACTED]`);
  output = output.replace(/([?&](?:token|session|jsessionid|authorization|loginName|password|mobile|phone)=)[^&#\s]+/gi, "$1[REDACTED]");
  output = output.replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, (ip) => (isPrivateIp(ip) ? ip : "[REDACTED_PUBLIC_IP]"));
  if (output !== before) sensitiveFieldsRedacted += 1;
  return output;
}

function listFiles(dir) {
  if (!fs.existsSync(dir)) return [];
  const files = [];
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, item.name);
    if (item.isDirectory()) files.push(...listFiles(full));
    else if (item.isFile() && EXTENSIONS.has(path.extname(item.name).toLowerCase())) files.push(full);
  }
  return files;
}

function safeRead(file) {
  return redactSensitive(fs.readFileSync(file, "utf8"));
}

function getFileType(file) {
  const ext = path.extname(file).toLowerCase();
  if (ext === ".htm" || ext === ".html") return "html";
  if (ext === ".js") return "js";
  if (ext === ".json") return "json";
  if (ext === ".har") return "har";
  if (ext === ".xml") return "xml";
  return "txt";
}

function shouldScanForKeywordEvidence(file) {
  const base = path.basename(file).toLowerCase();
  if (GENERATED_CAPTURE_METADATA.has(base)) return false;
  if (COMMON_VENDOR_RESOURCE_HINTS.some((hint) => base.includes(hint))) return false;
  return true;
}

function keywordMatches(line, keyword) {
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (/^[A-Za-z0-9_]+$/.test(keyword)) {
    return new RegExp(`(^|[^A-Za-z0-9_])${escaped}([^A-Za-z0-9_]|$)`, "i").test(line);
  }
  return line.toLowerCase().includes(keyword.toLowerCase());
}

function contextForLine(lines, index) {
  const start = Math.max(0, index - 2);
  const end = Math.min(lines.length, index + 3);
  return redactSensitive(lines.slice(start, end).join("\n").replace(/\s+/g, " ").trim()).slice(0, 600);
}

function inferMeaning(text) {
  const value = String(text || "");
  if (/DSC|DscIp|DscPort|注册|登录|服务地址|监控中心|上级平台|心跳/i.test(value)) return "DSC/注册/配置/心跳业务侧证";
  if (/RDS|RDSIp|RDSHeartBeat|RealData|实时数据|遥测|遥信/i.test(value)) return "RDS/实时数据/保活业务侧证";
  if (/告警|事件|遥控|遥调|命令|clear|control/i.test(value)) return "告警/事件/控制业务侧证，仅记录，禁止调用写操作";
  if (/FSU|监控单元|站址|设备|信号|点位/i.test(value)) return "FSU业务对象/设备点位侧证";
  return "关键词上下文";
}

function confidenceFor(text) {
  if (/DSC|RDS|DscIp|RDSIp|RDSHeartBeat/i.test(text)) return "high";
  if (/FSU|实时数据|遥测|遥信|告警|心跳|注册|登录/.test(text)) return "medium";
  return "low";
}

function keywordHits(file, fileType, text, urlPath = "") {
  if (!shouldScanForKeywordEvidence(file)) return [];
  const lines = text.split(/\r?\n/);
  const hits = [];
  lines.forEach((line, idx) => {
    for (const keyword of KEYWORDS) {
      if (keywordMatches(line, keyword)) {
        const nearbyText = contextForLine(lines, idx);
        hits.push({
          keyword,
          sourceFile: rel(file),
          fileType,
          lineNumber: idx + 1,
          urlPath,
          nearbyText,
          inferredMeaning: inferMeaning(nearbyText),
          confidence: confidenceFor(nearbyText),
        });
      }
    }
  });
  return hits;
}

function extractHtml(file, text) {
  const title = (text.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [null, ""])[1].replace(/<[^>]+>/g, "").trim();
  const pageTitle = redactSensitive(title);
  const labels = [...text.matchAll(/<label[^>]*>([\s\S]*?)<\/label>/gi)].map((m) => m[1].replace(/<[^>]+>/g, "").trim()).filter(Boolean);
  const headers = [...text.matchAll(/<th[^>]*>([\s\S]*?)<\/th>/gi)].map((m) => m[1].replace(/<[^>]+>/g, "").trim()).filter(Boolean);
  const buttons = [...text.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/gi)].map((m) => m[1].replace(/<[^>]+>/g, "").trim()).filter(Boolean);
  const inputs = [...text.matchAll(/<(input|select|textarea)\b([^>]*)>/gi)].map((m) => {
    const attrs = {};
    for (const a of m[2].matchAll(/([:\w-]+)\s*=\s*["']([^"']*)["']/g)) attrs[a[1]] = redactSensitive(a[2]);
    return {
      pageTitle,
      urlPath: "",
      formFieldName: attrs.name || attrs.id || "",
      inputName: attrs.name || "",
      inputId: attrs.id || "",
      labelText: labels.find((label) => attrs.id && text.includes(`for="${attrs.id}"`) && text.includes(label)) || "",
      placeholder: attrs.placeholder || "",
      valueExample: attrs.value || "",
      nearbyHelpText: "",
      inferredMeaning: inferMeaning(`${attrs.name || ""} ${attrs.id || ""} ${attrs.placeholder || ""}`),
      relationToFsuDscRds: confidenceFor(`${attrs.name || ""} ${attrs.id || ""}`),
      confidence: confidenceFor(`${attrs.name || ""} ${attrs.id || ""} ${attrs.placeholder || ""}`),
    };
  });
  const forms = [...text.matchAll(/<form\b([^>]*)>/gi)].map((m) => {
    const attrs = {};
    for (const a of m[1].matchAll(/([:\w-]+)\s*=\s*["']([^"']*)["']/g)) attrs[a[1]] = redactSensitive(a[2]);
    return {
      apiEndpoint: attrs.action || "",
      method: String(attrs.method || "GET").toUpperCase(),
      sourceFile: rel(file),
      requestParams: [],
      responseFields: [],
      containsFsuKeyword: /fsu|监控单元/i.test(`${attrs.action || ""} ${labels.join(" ")}`),
      containsDscRdsKeyword: /dsc|rds/i.test(`${attrs.action || ""} ${labels.join(" ")}`),
      containsRealtimeKeyword: /real|实时|遥测|遥信/i.test(labels.join(" ")),
      containsAlarmKeyword: /alarm|告警/i.test(labels.join(" ")),
      readonlyCandidate: !PROHIBITED_METHODS.has(String(attrs.method || "GET").toUpperCase()),
      prohibitedBecause: PROHIBITED_METHODS.has(String(attrs.method || "GET").toUpperCase()) ? "form method is write-capable" : "",
      inferredMeaning: inferMeaning(`${attrs.action || ""} ${labels.join(" ")}`),
    };
  });
  return { pageTitle, labels, headers, buttons, inputs, forms };
}

function extractEndpoints(file, fileType, text) {
  const endpoints = [];
  const endpointRegex = /(?:url|href|action|api|path)?\s*[:=]\s*["'`]([^"'`<> ]+)["'`]|(?:fetch|open)\s*\(\s*["'`]([^"'`]+)["'`]/gi;
  for (const match of text.matchAll(endpointRegex)) {
    const endpoint = redactSensitive(match[1] || match[2] || "");
    if (!endpoint || (!endpoint.startsWith("/") && !/^https?:/i.test(endpoint))) continue;
    const lower = endpoint.toLowerCase();
    const prohibitedTerm = PROHIBITED_ENDPOINT_TERMS.find((term) => lower.includes(term.toLowerCase()));
    endpoints.push({
      apiEndpoint: endpoint,
      method: "UNKNOWN",
      sourceFile: rel(file),
      requestParams: [],
      responseFields: [],
      containsFsuKeyword: /fsu|sc|监控单元/i.test(endpoint),
      containsDscRdsKeyword: /dsc|rds/i.test(endpoint),
      containsRealtimeKeyword: /real|realtime|实时|遥测|遥信/i.test(endpoint),
      containsAlarmKeyword: /alarm|告警/i.test(endpoint),
      readonlyCandidate: !prohibitedTerm,
      prohibitedBecause: prohibitedTerm ? `endpoint contains prohibited term: ${prohibitedTerm}` : "",
      inferredMeaning: inferMeaning(endpoint),
      fileType,
    });
  }
  return endpoints;
}

function extractJsonFields(value, prefix = "", out = []) {
  if (Array.isArray(value)) {
    value.slice(0, 3).forEach((item, idx) => extractJsonFields(item, `${prefix}[${idx}]`, out));
  } else if (value && typeof value === "object") {
    for (const [key, val] of Object.entries(value)) {
      const name = prefix ? `${prefix}.${key}` : key;
      out.push({
        fieldName: redactSensitive(name),
        valueExample: redactSensitive(typeof val === "object" ? JSON.stringify(val).slice(0, 120) : String(val).slice(0, 120)),
      });
      extractJsonFields(val, name, out);
    }
  }
  return out;
}

function analyzeHar(file, text) {
  const results = { hits: [], endpoints: [], fields: [] };
  let har;
  try {
    har = JSON.parse(text);
  } catch (_err) {
    return results;
  }
  const entries = har.log && Array.isArray(har.log.entries) ? har.log.entries : [];
  entries.forEach((entry, idx) => {
    const request = entry.request || {};
    const response = entry.response || {};
    const content = response.content || {};
    const url = redactSensitive(request.url || "");
    const method = String(request.method || "GET").toUpperCase();
    const contentText = redactSensitive(content.text || "");
    const prohibitedTerm = PROHIBITED_ENDPOINT_TERMS.find((term) => url.toLowerCase().includes(term.toLowerCase()));
    results.endpoints.push({
      apiEndpoint: url,
      method,
      sourceFile: rel(file),
      requestParams: (request.queryString || []).map((q) => ({ name: redactSensitive(q.name), value: redactSensitive(q.value) })),
      responseFields: [],
      responseStatus: response.status || null,
      mimeType: content.mimeType || "",
      containsFsuKeyword: /fsu|sc|监控单元/i.test(`${url} ${contentText}`),
      containsDscRdsKeyword: /dsc|rds/i.test(`${url} ${contentText}`),
      containsRealtimeKeyword: /real|realtime|实时|遥测|遥信/i.test(`${url} ${contentText}`),
      containsAlarmKeyword: /alarm|告警/i.test(`${url} ${contentText}`),
      readonlyCandidate: method === "GET" && !prohibitedTerm,
      prohibitedBecause: method !== "GET" ? `method ${method} is not allowed` : prohibitedTerm ? `endpoint contains prohibited term: ${prohibitedTerm}` : "",
      inferredMeaning: inferMeaning(`${url} ${contentText}`),
      harEntryIndex: idx,
    });
    results.hits.push(...keywordHits(file, "har", `${url}\n${contentText}`, url));
    if (/json/i.test(content.mimeType || "")) {
      try {
        results.fields.push(...extractJsonFields(JSON.parse(contentText)).map((field) => ({ ...field, sourceFile: rel(file), sourceEndpoint: url })));
      } catch (_err) {
        // Ignore non-JSON content despite MIME.
      }
    }
  });
  return results;
}

function buildBusinessObjects(fields, pageFields, hits) {
  const rows = [];
  const candidates = [
    ...fields.map((field) => ({ fieldName: field.fieldName, chineseLabel: "", valueExample: field.valueExample, sourcePage: "", sourceEndpoint: field.sourceEndpoint || "" })),
    ...pageFields.map((field) => ({ fieldName: field.formFieldName, chineseLabel: field.labelText, valueExample: field.valueExample, sourcePage: field.pageTitle, sourceEndpoint: "" })),
    ...hits.map((hit) => ({ fieldName: hit.keyword, chineseLabel: hit.keyword, valueExample: "", sourcePage: "", sourceEndpoint: hit.urlPath || "" })),
  ];
  for (const item of candidates) {
    const probe = `${item.fieldName} ${item.chineseLabel} ${item.valueExample}`;
    const found = OBJECT_HINTS.find(([_name, regex]) => regex.test(probe));
    if (!found) continue;
    rows.push({
      objectType: found[0],
      fieldName: item.fieldName,
      chineseLabel: item.chineseLabel,
      valueExample: redactSensitive(item.valueExample),
      sourcePage: item.sourcePage,
      sourceEndpoint: item.sourceEndpoint,
      inferredMeaning: inferMeaning(probe),
      confidence: confidenceFor(probe),
    });
  }
  return dedupe(rows, (row) => `${row.objectType}|${row.fieldName}|${row.sourceEndpoint}`);
}

function dedupe(items, keyFn) {
  const seen = new Set();
  const out = [];
  for (const item of items) {
    const key = keyFn(item);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

function analyze() {
  ensureDir(INPUT_DIR);
  ensureDir(OUTPUT_DIR);

  const files = listFiles(INPUT_DIR);
  const overview = {
    totalFiles: files.length,
    htmlFiles: 0,
    jsFiles: 0,
    jsonFiles: 0,
    xmlFiles: 0,
    harFiles: 0,
    txtFiles: 0,
    skippedFiles: 0,
    sensitiveFieldsRedacted: 0,
  };

  const allHits = [];
  const endpoints = [];
  const pageFields = [];
  const tableRows = [];
  const menuRows = [];
  const jsonFields = [];
  const directDscRds = [];

  for (const file of files) {
    const fileType = getFileType(file);
    overview[`${fileType}Files`] = (overview[`${fileType}Files`] || 0) + 1;
    const text = safeRead(file);
    allHits.push(...keywordHits(file, fileType, text));
    endpoints.push(...extractEndpoints(file, fileType, text));

    if (fileType === "html") {
      const html = extractHtml(file, text);
      pageFields.push(...html.inputs);
      if (html.headers.length) {
        tableRows.push({
          pageTitle: html.pageTitle,
          tableHeaders: html.headers,
          relatedObject: inferMeaning(html.headers.join(" ")),
          inferredMeaning: inferMeaning(html.headers.join(" ")),
          evidence: rel(file),
        });
      }
      for (const textValue of [...html.labels, ...html.buttons].filter(Boolean)) {
        if (/FSU|动环|实时|告警|设备|信号|点位|遥测|遥信|RDS|DSC/i.test(textValue)) {
          menuRows.push({
            menuText: redactSensitive(textValue),
            pagePath: rel(file),
            sourceFile: rel(file),
            relatedToFsu: /FSU|监控单元|动环/i.test(textValue),
            relatedToRealtimeData: /实时|遥测|遥信|RDS/i.test(textValue),
            relatedToAlarm: /告警|事件/i.test(textValue),
            relatedToDeviceSignal: /设备|信号|点位/i.test(textValue),
            evidence: html.pageTitle || rel(file),
          });
        }
      }
      endpoints.push(...html.forms);
    }

    if (fileType === "json") {
      try {
        jsonFields.push(...extractJsonFields(JSON.parse(text)).map((field) => ({ ...field, sourceFile: rel(file), sourceEndpoint: "" })));
      } catch (_err) {
        overview.skippedFiles += 1;
      }
    }

    if (fileType === "har") {
      const har = analyzeHar(file, text);
      allHits.push(...har.hits);
      endpoints.push(...har.endpoints);
      jsonFields.push(...har.fields);
    }
  }

  overview.sensitiveFieldsRedacted = sensitiveFieldsRedacted;

  for (const hit of allHits) {
    if (/\b(?:DSC|DscIp|DscPort|RDS|RDSIp|RDSHeartBeat|RDSPort)\b/i.test(`${hit.keyword} ${hit.nearbyText}`)) {
      directDscRds.push({
        term: hit.keyword,
        chineseLabel: hit.keyword,
        sourceFile: hit.sourceFile,
        pageTitle: "",
        urlPath: hit.urlPath,
        nearbyText: hit.nearbyText,
        inferredMeaning: hit.inferredMeaning,
        confidence: hit.confidence,
      });
    }
  }

  const businessObjects = buildBusinessObjects(jsonFields, pageFields, allHits);
  const hasDirectDscEvidence = directDscRds.some((row) => /DSC|Dsc/i.test(`${row.term} ${row.nearbyText}`));
  const hasDirectRdsEvidence = directDscRds.some((row) => /RDS|Rds/i.test(`${row.term} ${row.nearbyText}`));
  const hasBusinessEvidence = allHits.some((hit) => /FSU|动环|实时数据|遥测|遥信|告警|点位|设备|站址/.test(`${hit.keyword} ${hit.nearbyText}`));

  const conclusion = {
    confirmed: [],
    supportingOnly: [],
    notConfirmed: [
      "ACK 二进制格式未确认。",
      "typeA/opcode 完整枚举未确认。",
      "DSC_CONFIG_209/245 payload 字段未完全确认。",
      "RDS 实时业务帧当前未出现。",
      "铁塔页面业务字段不能直接等价于 FSU 私有 UDP payload offset。",
      "需要继续结合 SiteUnit 逆向和抓包差异分析。",
    ],
  };
  if (hasBusinessEvidence) conclusion.confirmed.push("本地网页资料中出现 FSU/实时数据/告警/设备点位等业务概念。");
  if (hasDirectDscEvidence) conclusion.supportingOnly.push("网页资料直接出现 DSC/Dsc 相关字段，可作为 DSC 命名侧证。");
  if (hasDirectRdsEvidence) conclusion.supportingOnly.push("网页资料直接出现 RDS/Rds 相关字段，可作为 RDS 命名侧证。");
  if (!files.length) conclusion.notConfirmed.push("未发现本地导出的铁塔平台资料文件，因此本次不能提供网页侧证。");

  const report = {
    generatedAt: new Date().toISOString(),
    inputDir: rel(INPUT_DIR),
    safety: {
      readonlyLocalAnalysisOnly: true,
      noPostPutDeletePatch: true,
      noUdpSent: true,
      noAckAdded: true,
      sendOneShotAckNotRun: true,
      gatewayReplyLogicUnchanged: true,
      businessTablesUnchanged: true,
      sensitiveFieldsRedacted: sensitiveFieldsRedacted > 0,
    },
    inputOverview: overview,
    platformMenus: dedupe(menuRows, (row) => `${row.menuText}|${row.sourceFile}`),
    keywordHits: allHits.slice(0, 1000),
    apiEndpoints: dedupe(endpoints, (row) => `${row.method}|${row.apiEndpoint}|${row.sourceFile}`).slice(0, 1000),
    pageFields,
    tableSemantics: tableRows,
    fsuBusinessObjects: businessObjects.slice(0, 1000),
    dscRdsDirectEvidence: dedupe(directDscRds, (row) => `${row.term}|${row.sourceFile}|${row.lineNumber || ""}`).slice(0, 1000),
    directEvidenceSummary: {
      hasDirectDscEvidence,
      hasDirectRdsEvidence,
      hasDscIp: allHits.some((hit) => /DscIp|DscIP/i.test(`${hit.keyword} ${hit.nearbyText}`)),
      hasRdsIp: allHits.some((hit) => /RDSIp|RDSIP/i.test(`${hit.keyword} ${hit.nearbyText}`)),
      hasRdsHeartbeat: allHits.some((hit) => /RDSHeartBeat|SendRDSHeartbeat/i.test(`${hit.keyword} ${hit.nearbyText}`)),
      hasPort7000Evidence: allHits.some((hit) => /\b7000\b/.test(`${hit.keyword} ${hit.nearbyText}`)),
      hasPort9000Evidence: allHits.some((hit) => /\b9000\b/.test(`${hit.keyword} ${hit.nearbyText}`)),
      hasRegisterHeartbeatRealtimeEvidence: allHits.some((hit) => /注册|登录|心跳|实时数据|监控中心|上级平台|服务地址/.test(`${hit.keyword} ${hit.nearbyText}`)),
    },
    packetRelation: {
      currentFrameClasses: [
        "DSC_SHORT_24_TYPE_1F00_D2FF",
        "RDS_SHORT_30_TYPE_1180_D2FF",
        "DSC_CONFIG_209_TYPE_1100_46FF",
        "DSC_CONFIG_245_TYPE_1100_46FF",
      ],
      supportsBusinessConceptsOnly: true,
      rdsRealtimeSupportedByWebConcepts: hasDirectRdsEvidence || allHits.some((hit) => /实时数据|遥测|遥信/.test(`${hit.keyword} ${hit.nearbyText}`)),
      dscRegisterConfigSupportedByWebConcepts: hasDirectDscEvidence || allHits.some((hit) => /注册|登录|配置|监控中心|服务地址/.test(`${hit.keyword} ${hit.nearbyText}`)),
      caveats: [
        "网页资料只能提供业务语义侧证，不能证明二进制 offset。",
        "当前 RDS 只有 30 字节短帧，因此仍不能确认业务 RDS payload 结构。",
      ],
    },
    conclusions: conclusion,
  };

  const jsonPath = path.join(OUTPUT_DIR, `tower-web-fsu-semantics-${TODAY}.json`);
  const mdPath = path.join(OUTPUT_DIR, `tower-web-fsu-semantics-${TODAY}.md`);
  fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2), "utf8");
  fs.writeFileSync(mdPath, renderMarkdown(report), "utf8");
  console.log(JSON.stringify({ jsonPath: rel(jsonPath), mdPath: rel(mdPath), inputOverview: overview, directEvidenceSummary: report.directEvidenceSummary }, null, 2));
}

function renderMarkdown(report) {
  const lines = [];
  lines.push(`# Tower Web FSU Semantics ${TODAY}`);
  lines.push("");
  lines.push("## 安全确认");
  lines.push("- 未修改铁塔平台配置。");
  lines.push("- 未点击保存/提交/下发/测试/重启/清告警/遥控等按钮。");
  lines.push("- 未发起 POST/PUT/DELETE/PATCH 请求。");
  lines.push("- 未发送 UDP。");
  lines.push("- 未新增 ACK。");
  lines.push("- 未运行 send-one-shot-ack.js。");
  lines.push("- 未修改 fsu-gateway 实时回包逻辑。");
  lines.push("- 未写业务主表。");
  lines.push("- 未做 XML/JSON 转换。");
  lines.push("- 已脱敏 Cookie/Token/Authorization/Session/loginName 等敏感信息。");
  lines.push("");
  lines.push("## 输入文件概览");
  lines.push("```json");
  lines.push(JSON.stringify(report.inputOverview, null, 2));
  lines.push("```");
  lines.push("");
  lines.push("## DSC/RDS 直接证据");
  if (!report.dscRdsDirectEvidence.length) lines.push("未在本地资料中发现 DSC/RDS 直接证据。");
  for (const row of report.dscRdsDirectEvidence.slice(0, 50)) {
    lines.push(`- ${row.term} @ ${row.sourceFile}: ${row.nearbyText}`);
  }
  lines.push("");
  lines.push("## FSU 业务对象证据");
  if (!report.fsuBusinessObjects.length) lines.push("未在本地资料中发现 FSU/遥测/遥信/告警/点位业务对象证据。");
  for (const row of report.fsuBusinessObjects.slice(0, 80)) {
    lines.push(`- ${row.objectType}: ${row.fieldName || row.chineseLabel} (${row.inferredMeaning})`);
  }
  lines.push("");
  lines.push("## 接口路径表");
  for (const row of report.apiEndpoints.slice(0, 80)) {
    lines.push(`- ${row.method} ${row.apiEndpoint} readonly=${row.readonlyCandidate} ${row.prohibitedBecause || ""}`);
  }
  lines.push("");
  lines.push("## 与当前 DSC/RDS 抓包的对应关系");
  lines.push("- 平台页面证据只能支持业务层概念，不能证明私有 UDP 二进制 offset。");
  lines.push("- 当前真实设备仍只出现 4 类已知 frameClass，RDS 尚未出现确认业务帧。");
  lines.push("- RDS 与实时数据的关系如由网页命名支持，也仍不能直接确认 payload 结构。");
  lines.push("");
  lines.push("## 未确认内容");
  for (const item of report.conclusions.notConfirmed) lines.push(`- ${item}`);
  return lines.join("\n");
}

analyze();
