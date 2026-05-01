#!/usr/bin/env node
"use strict";

/**
 * Read-only precheck for a possible future classByte=0x47 one-shot experiment.
 *
 * SAFETY:
 * - Does not send UDP.
 * - Does not run send-one-shot-ack.js.
 * - Does not generate ackHex or any sendable frameHex.
 * - Does not add ACK.
 * - Does not modify fsu-gateway runtime reply logic.
 * - Does not write business tables.
 * - Does not execute an online experiment.
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const { execFileSync } = require("child_process");
const { parseFsuFrame, cleanHex } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const ROOT = path.resolve(__dirname, "..", "..");
const RAW_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets");
const DEFAULT_LOG = path.join(RAW_DIR, "2026-05-01.jsonl");
const DEFAULT_OUT_DIR = RAW_DIR;
const DEVICE_IP = "192.168.100.100";
const CRITICAL_FILES = [
  "docs/fsu-class47-one-shot-experiment-plan.md",
  "backend/logs/fsu_raw_packets/final-offline-protocol-map-v1.4-2026-05-01.md",
  "backend/logs/fsu_raw_packets/final-offline-protocol-map-v1.4-2026-05-01.json",
  "backend/app/modules/fsu_gateway/parser/fsu-frame-parser.js",
  "backend/app/modules/fsu_gateway/parser/dsc-rds-annotations.js",
  "backend/scripts/pick-latest-frame-hex.js",
  "backend/scripts/reproduce-d2ff-ack-exact-v12.js",
  "backend/scripts/verify-fsu-checksum.js",
];

const KNOWN_LENGTHS = new Set([24, 30, 209, 245]);
const KNOWN_TYPE_BYTES = new Set(["1f00d2ff", "1180d2ff", "110046ff"]);

function parseArgs(argv) {
  const args = {
    tailLines: 5000,
    growthWaitSeconds: 5,
    healthUrl: "http://127.0.0.1:8000/health",
    outDir: DEFAULT_OUT_DIR,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (key === "--input") args.input = argv[++i];
    else if (key === "--health-url") args.healthUrl = argv[++i];
    else if (key === "--tail-lines") args.tailLines = Number(argv[++i]);
    else if (key === "--growth-wait-seconds") args.growthWaitSeconds = Number(argv[++i]);
    else if (key === "--out-dir") args.outDir = argv[++i];
  }
  return args;
}

function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function relOrAbs(filePath) {
  return path.isAbsolute(filePath) ? filePath : path.join(ROOT, filePath);
}

function findLatestRawLog() {
  if (fs.existsSync(DEFAULT_LOG)) return DEFAULT_LOG;
  if (!fs.existsSync(RAW_DIR)) return null;
  const files = fs.readdirSync(RAW_DIR)
    .filter((name) => /^\d{4}-\d{2}-\d{2}\.jsonl$/.test(name))
    .sort()
    .map((name) => path.join(RAW_DIR, name));
  return files.pop() || null;
}

function ymdFromLog(logPath) {
  const base = path.basename(logPath || "", ".jsonl");
  return /^\d{4}-\d{2}-\d{2}$/.test(base) ? base : new Date().toISOString().slice(0, 10);
}

function timestampForFileName(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function readTailLines(filePath, n) {
  const text = fs.readFileSync(filePath, "utf8");
  const lines = text.split(/\r?\n/).filter(Boolean);
  return lines.slice(Math.max(0, lines.length - n));
}

function findRawHex(entry) {
  return cleanHex(entry.rawHex || entry.hex || entry.raw || entry.payloadHex || "");
}

function getTimestamp(entry) {
  return entry.receivedAt || entry.createdAt || entry.timestamp || null;
}

function hexContextFromRaw(rawHex) {
  const buf = Buffer.from(rawHex, "hex");
  return buf.length >= 20 ? buf.subarray(8, 20).toString("hex") : null;
}

function addReason(reasons, message) {
  if (!reasons.includes(message)) reasons.push(message);
}

function runGitStatus() {
  try {
    const output = execFileSync("git", ["status", "--short"], { cwd: ROOT, encoding: "utf8" });
    const changedFiles = output.split(/\r?\n/).filter(Boolean);
    return { gitClean: changedFiles.length === 0, changedFiles, error: null };
  } catch (error) {
    return { gitClean: false, changedFiles: [], error: error.message };
  }
}

function checkFiles() {
  const files = CRITICAL_FILES.map((rel) => ({ path: rel, exists: fs.existsSync(path.join(ROOT, rel)) }));
  return {
    files,
    missingFiles: files.filter((item) => !item.exists).map((item) => item.path),
    allExist: files.every((item) => item.exists),
  };
}

function requestHealth(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 3000 }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        resolve({
          healthOk: res.statusCode >= 200 && res.statusCode < 300,
          statusCode: res.statusCode,
          responseSnippet: body.slice(0, 300),
          error: null,
        });
      });
    });
    req.on("timeout", () => {
      req.destroy(new Error("health request timed out"));
    });
    req.on("error", (error) => {
      resolve({ healthOk: false, statusCode: null, responseSnippet: "", error: error.message });
    });
  });
}

function checkUdpListening() {
  function normalizeAddress(address) {
    const value = String(address || "").trim();
    return value || "*";
  }

  function endpointMatchesPort(endpoint, port) {
    return Number(endpoint.localPort) === port;
  }

  function parsePowerShellUdpEndpoints(output) {
    return output
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const parts = line.split(/\s+/);
        return {
          localAddress: normalizeAddress(parts[0]),
          localPort: Number(parts[1]),
          pid: parts[2] || null,
          raw: line,
        };
      })
      .filter((item) => Number.isInteger(item.localPort));
  }

  function tryPowerShell() {
    const command = [
      "$ErrorActionPreference='Stop';",
      "Get-NetUDPEndpoint -LocalPort 9000,7000 |",
      "Select-Object LocalAddress,LocalPort,OwningProcess |",
      "ForEach-Object { \"$($_.LocalAddress) $($_.LocalPort) $($_.OwningProcess)\" }",
    ].join(" ");
    const output = execFileSync("powershell.exe", ["-NoProfile", "-Command", command], { encoding: "utf8" });
    const endpoints = parsePowerShellUdpEndpoints(output);
    const dsc = endpoints.filter((item) => endpointMatchesPort(item, 9000));
    const rds = endpoints.filter((item) => endpointMatchesPort(item, 7000));
    return {
      method: "Get-NetUDPEndpoint",
      udpDscListening: dsc.length > 0,
      udpRdsListening: rds.length > 0,
      matchingLines: {
        udpDsc9000: dsc.map((item) => item.raw),
        udpRds7000: rds.map((item) => item.raw),
      },
      pids: {
        udpDsc9000: [...new Set(dsc.map((item) => item.pid).filter(Boolean))],
        udpRds7000: [...new Set(rds.map((item) => item.pid).filter(Boolean))],
      },
      error: null,
    };
  }

  function parseNetstatUdp(output) {
    const listenRegex = /(?:UDP)\s+(\S+):(\d+)\s+\*:\*\s+(\d+)/i;
    const genericRegex = /\s*(?:UDP)?\s+(\S+):(\d+)\s+(?:\*:\*|\S+)\s*(\d+)?\s*$/i;
    return output.split(/\r?\n/).filter(Boolean).map((line) => {
      const trimmed = line.trim();
      const match = trimmed.match(listenRegex) || trimmed.match(genericRegex);
      if (!match) return null;
      return {
        localAddress: normalizeAddress(match[1]),
        localPort: Number(match[2]),
        pid: match[3] || null,
        raw: trimmed,
      };
    }).filter((item) => item && Number.isInteger(item.localPort));
  }

  function tryNetstat(powerShellError = null) {
    const output = execFileSync("netstat", ["-ano", "-p", "udp"], { encoding: "utf8" });
    const endpoints = parseNetstatUdp(output);
    const dsc = endpoints.filter((item) => endpointMatchesPort(item, 9000));
    const rds = endpoints.filter((item) => endpointMatchesPort(item, 7000));
    return {
      method: "netstat -ano -p udp",
      udpDscListening: dsc.length > 0,
      udpRdsListening: rds.length > 0,
      matchingLines: {
        udpDsc9000: dsc.map((item) => item.raw),
        udpRds7000: rds.map((item) => item.raw),
      },
      pids: {
        udpDsc9000: [...new Set(dsc.map((item) => item.pid).filter(Boolean))],
        udpRds7000: [...new Set(rds.map((item) => item.pid).filter(Boolean))],
      },
      error: null,
      fallbackFrom: powerShellError ? { method: "Get-NetUDPEndpoint", error: powerShellError.message } : null,
    };
  }

  try {
    return tryPowerShell();
  } catch (powerShellError) {
    try {
      return tryNetstat(powerShellError);
    } catch (netstatError) {
      return {
        method: "Get-NetUDPEndpoint, fallback netstat",
        udpDscListening: false,
        udpRdsListening: false,
        matchingLines: { udpDsc9000: [], udpRds7000: [] },
        pids: { udpDsc9000: [], udpRds7000: [] },
        error: `Get-NetUDPEndpoint failed: ${powerShellError.message}; netstat failed: ${netstatError.message}`,
      };
    }
  }
}

function describeGitDirty(git) {
  if (git.gitClean) return null;
  const changed = git.changedFiles.map((line) => line.slice(3).trim());
  const onlyPrecheckRelated = changed.length > 0 && changed.every((file) =>
    file === "backend/scripts/precheck-class47-one-shot-readiness.js" ||
    file.startsWith("backend/logs/fsu_raw_packets/class47-one-shot-precheck-"),
  );
  return {
    note: onlyPrecheckRelated
      ? "Git dirty remains a blocker before experiment window; current dirty files appear limited to precheck script/report outputs and can be resolved by committing or cleaning report files."
      : "Git dirty remains a blocker before experiment window; review, commit, or clean changes before any future experiment.",
    onlyPrecheckRelated,
  };
}

function legacyCheckUdpListeningRemoved() {
  try {
    return null;
  } catch (error) {
    return {
      udpDscListening: false,
      udpRdsListening: false,
      matchingLines: { udpDsc9000: [], udpRds7000: [] },
      error: error.message,
    };
  }
}

function summarizeWindow(lines) {
  const parsed = [];
  let parseErrors = 0;
  for (let i = 0; i < lines.length; i += 1) {
    let entry;
    try { entry = JSON.parse(lines[i]); } catch { parseErrors += 1; continue; }
    if (entry.remoteAddress && entry.remoteAddress !== DEVICE_IP) continue;
    const rawHex = findRawHex(entry);
    if (!rawHex) continue;
    const frame = parseFsuFrame(rawHex, { protocol: entry.protocol, includeAscii: false });
    if (!frame.ok) continue;
    parsed.push({
      lineIndexInTail: i,
      timestamp: getTimestamp(entry),
      protocol: entry.protocol,
      remoteAddress: entry.remoteAddress,
      remotePort: entry.remotePort,
      localPort: entry.localPort,
      length: frame.totalLength,
      seqLE: frame.seqLE,
      typeBytes: frame.typeBytesSummary,
      frameClass: frame.frameClass,
      checksumValid: frame.checksumValid,
      checksumValidLE: frame.checksumValidLE,
      checksumValidBE: frame.checksumValidBE,
      payloadLengthMatchesTotalMinus24: frame.payloadLengthMatchesTotalMinus24,
      headerContextHex: hexContextFromRaw(rawHex),
    });
  }
  return { parsed, parseErrors };
}

function inc(obj, key) {
  obj[key] = (obj[key] || 0) + 1;
}

function distribution(items, keyFn) {
  const out = {};
  for (const item of items) inc(out, String(keyFn(item)));
  return out;
}

function latestBy(items, predicate) {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (predicate(items[i])) return items[i];
  }
  return null;
}

function pairRdsDsc24(items) {
  const rds = items.filter((item) => item.length === 30 && item.typeBytes === "1180d2ff");
  const dsc24 = items.filter((item) => item.length === 24 && item.typeBytes === "1f00d2ff");
  const ackBySeq = new Map();
  for (const item of dsc24) {
    if (!ackBySeq.has(item.seqLE)) ackBySeq.set(item.seqLE, []);
    ackBySeq.get(item.seqLE).push(item);
  }
  const pairs = [];
  for (const item of rds) {
    const candidates = ackBySeq.get(item.seqLE);
    if (candidates && candidates.length) pairs.push({ rds: item, ack: candidates.shift() });
  }
  const latestPair = pairs[pairs.length - 1] || null;
  const latestTs = latestPair ? Date.parse(latestPair.ack.timestamp || latestPair.rds.timestamp || "") : NaN;
  return {
    rds30Count: rds.length,
    dsc24Count: dsc24.length,
    pairedCount: pairs.length,
    sameSeqRatio: rds.length ? pairs.length / rds.length : 0,
    latestPairSeqLE: latestPair?.rds.seqLE ?? null,
    latestPairAgeSeconds: Number.isFinite(latestTs) ? Math.max(0, (Date.now() - latestTs) / 1000) : null,
  };
}

function checksumQuick(items) {
  const classes = {
    rds30: items.filter((item) => item.length === 30 && item.typeBytes === "1180d2ff"),
    dsc209: items.filter((item) => item.length === 209 && item.typeBytes === "110046ff"),
    dsc245: items.filter((item) => item.length === 245 && item.typeBytes === "110046ff"),
    dsc24: items.filter((item) => item.length === 24 && item.typeBytes === "1f00d2ff"),
  };
  const rate = (arr) => ({
    count: arr.length,
    validLE: arr.filter((item) => item.checksumValidLE).length,
    validRate: arr.length ? arr.filter((item) => item.checksumValidLE).length / arr.length : null,
  });
  const rates = {
    rds30: rate(classes.rds30),
    dsc209: rate(classes.dsc209),
    dsc245: rate(classes.dsc245),
    dsc24: {
      count: classes.dsc24.length,
      note: "DSC24 is explained by D2FF v1.2 reproduction model, not by normal checksum validation.",
    },
  };
  const critical = ["rds30", "dsc209", "dsc245"].filter((key) => rates[key].count > 0 && rates[key].validRate !== 1);
  return { checksumValidRates: rates, anyInvalidCritical: critical.length > 0, invalidCriticalClasses: critical };
}

function renderMd(result) {
  const lines = [
    "# FSU classByte=0x47 one-shot 实验前只读检查报告",
    "",
    `Generated at: ${result.generatedAt}`,
    "",
    "## 1. 安全边界",
    "",
    "- 只读 precheck。",
    "- 未发送 UDP。",
    "- 未新增 ACK。",
    "- 未运行 `send-one-shot-ack.js`。",
    "- 未写发包脚本。",
    "- 未生成可发送 frameHex。",
    "- 未修改 fsu-gateway 实时回包逻辑。",
    "- 未接入 `service.py`。",
    "- 未写业务主表。",
    "- 未做线上实验。",
    "",
    "## 2. 总体 readiness",
    "",
    `- readiness: \`${result.readiness}\``,
    `- safeToExperiment: \`${result.safeToExperiment}\``,
    "",
    "Reasons:",
    "",
    ...(result.reason.length ? result.reason.map((item) => `- ${item}`) : ["- No blocking reason recorded."]),
    "",
    "## 3. Git 状态",
    "",
    `- gitClean: ${result.checks.git.gitClean}`,
    `- changedFiles: ${result.checks.git.changedFiles.length}`,
    `- note: ${result.checks.gitDirtyExplanation?.note || ""}`,
    "",
    "## 4. 关键文件检查",
    "",
    `- allExist: ${result.checks.files.allExist}`,
    `- missingFiles: ${result.checks.files.missingFiles.join(", ") || "none"}`,
    "",
    "## 5. raw log 检查",
    "",
    `- rawLogPath: \`${result.checks.rawLog.rawLogPath || ""}\``,
    `- rawLogExists: ${result.checks.rawLog.rawLogExists}`,
    `- rawLogSizeBytes: ${result.checks.rawLog.rawLogSizeBytes}`,
    `- rawLogGrowing: ${result.checks.rawLog.rawLogGrowing}`,
    `- growthBytes: ${result.checks.rawLog.growthBytes}`,
    `- parsedTailPackets: ${result.checks.rawLog.parsedTailPackets}`,
    "",
    "## 6. health 检查",
    "",
    `- healthOk: ${result.checks.health.healthOk}`,
    `- statusCode: ${result.checks.health.statusCode}`,
    `- responseSnippet: \`${result.checks.health.responseSnippet || ""}\``,
    "",
    "## 7. UDP 监听检查",
    "",
    `- udpDscListening: ${result.checks.udp.udpDscListening}`,
    `- udpRdsListening: ${result.checks.udp.udpRdsListening}`,
    "",
    "## 8. 最新 0x46 请求检查",
    "",
    `- latest245Found: ${result.checks.latest0x46.latest245Found}`,
    `- latest245Timestamp: ${result.checks.latest0x46.latest245Timestamp || ""}`,
    `- latest245SeqLE: ${result.checks.latest0x46.latest245SeqLE ?? ""}`,
    `- latest245HeaderContextHex: ${result.checks.latest0x46.latest245HeaderContextHex || ""}`,
    `- latest209Found: ${result.checks.latest0x46.latest209Found}`,
    `- latest209Timestamp: ${result.checks.latest0x46.latest209Timestamp || ""}`,
    `- latest209SeqLE: ${result.checks.latest0x46.latest209SeqLE ?? ""}`,
    `- latest209HeaderContextHex: ${result.checks.latest0x46.latest209HeaderContextHex || ""}`,
    "",
    "## 9. RDS30 / DSC24 配对检查",
    "",
    `- rds30Count: ${result.checks.rdsDsc24Pair.rds30Count}`,
    `- dsc24Count: ${result.checks.rdsDsc24Pair.dsc24Count}`,
    `- pairedCount: ${result.checks.rdsDsc24Pair.pairedCount}`,
    `- sameSeqRatio: ${result.checks.rdsDsc24Pair.sameSeqRatio}`,
    `- latestPairSeqLE: ${result.checks.rdsDsc24Pair.latestPairSeqLE ?? ""}`,
    `- latestPairAgeSeconds: ${result.checks.rdsDsc24Pair.latestPairAgeSeconds ?? ""}`,
    "",
    "## 10. frameClass 分布",
    "",
    "```json",
    JSON.stringify(result.checks.frameDistribution, null, 2),
    "```",
    "",
    "## 11. checksum 快速验证",
    "",
    "```json",
    JSON.stringify(result.checks.checksum, null, 2),
    "```",
    "",
    "## 12. 风险与阻塞项",
    "",
    ...(result.blockers.length ? result.blockers.map((item) => `- ${item}`) : ["- No hard blocker recorded."]),
    "",
    "Warnings:",
    "",
    ...(result.warnings.length ? result.warnings.map((item) => `- ${item}`) : ["- No warning recorded."]),
    "",
    "## 13. 下一步建议",
    "",
    `- ${result.nextRecommendation}`,
    "",
    "## 14. 安全确认",
    "",
    `- udpSent: ${result.safety.udpSent}`,
    `- ackAdded: ${result.safety.ackAdded}`,
    `- sendOneShotAckRun: ${result.safety.sendOneShotAckRun}`,
    `- sendableFrameHexGenerated: ${result.safety.sendableFrameHexGenerated}`,
    `- servicePyModified: ${result.safety.servicePyModified}`,
    `- businessTableWritten: ${result.safety.businessTableWritten}`,
    `- onlineExperimentExecuted: ${result.safety.onlineExperimentExecuted}`,
    "",
  ];
  return `${lines.join("\n")}\n`;
}

async function main() {
  const args = parseArgs(process.argv);
  const input = relOrAbs(args.input || findLatestRawLog() || "");
  const outDir = relOrAbs(args.outDir);
  fs.mkdirSync(outDir, { recursive: true });
  const generatedAt = new Date().toISOString();
  const reasons = [];
  const blockers = [];
  const warnings = [];

  const git = runGitStatus();
  const gitDirtyExplanation = describeGitDirty(git);
  if (!git.gitClean) {
    addReason(reasons, "Git 工作区不干净，不能进入实验窗口。");
    blockers.push("Git workspace is not clean.");
  }

  const files = checkFiles();
  if (!files.allExist) {
    addReason(reasons, "关键文件缺失。");
    blockers.push(`Missing critical files: ${files.missingFiles.join(", ")}`);
  }

  let rawLog = {
    rawLogPath: input,
    rawLogExists: false,
    rawLogSizeBytes: 0,
    rawLogLastModified: null,
    rawLogGrowing: false,
    growthBytes: 0,
    tailLinesRequested: args.tailLines,
    parsedTailPackets: 0,
    parseErrors: 0,
  };
  let parsedItems = [];
  if (!input || !fs.existsSync(input)) {
    addReason(reasons, "raw log 不存在。");
    blockers.push("Raw log not found.");
  } else {
    const stat1 = fs.statSync(input);
    sleep(Math.max(0, args.growthWaitSeconds) * 1000);
    const stat2 = fs.statSync(input);
    const tail = readTailLines(input, args.tailLines);
    const summary = summarizeWindow(tail);
    parsedItems = summary.parsed;
    rawLog = {
      rawLogPath: input,
      rawLogExists: true,
      rawLogSizeBytes: stat2.size,
      rawLogLastModified: stat2.mtime.toISOString(),
      rawLogGrowing: stat2.size > stat1.size,
      growthBytes: stat2.size - stat1.size,
      tailLinesRequested: args.tailLines,
      parsedTailPackets: parsedItems.length,
      parseErrors: summary.parseErrors,
    };
    if (!rawLog.rawLogGrowing) {
      addReason(reasons, "raw log 未在检查窗口内增长。");
      blockers.push("Raw log is not growing.");
    }
  }

  const health = await requestHealth(args.healthUrl);
  if (!health.healthOk) {
    addReason(reasons, "后端 /health 检查失败，可能后端未启动。");
    blockers.push("Health check failed.");
  }

  const udp = checkUdpListening();
  if (!udp.udpDscListening) {
    addReason(reasons, "UDP_DSC 9000 未监听。");
    blockers.push("UDP 9000 is not listening.");
  }
  if (!udp.udpRdsListening) {
    addReason(reasons, "UDP_RDS 7000 未监听。");
    blockers.push("UDP 7000 is not listening.");
  }

  const latest245 = latestBy(parsedItems, (item) => item.length === 245 && item.typeBytes === "110046ff");
  const latest209 = latestBy(parsedItems, (item) => item.length === 209 && item.typeBytes === "110046ff");
  const latest0x46 = {
    latest245Found: !!latest245,
    latest245Timestamp: latest245?.timestamp || null,
    latest245SeqLE: latest245?.seqLE ?? null,
    latest245HeaderContextHex: latest245?.headerContextHex || null,
    latest209Found: !!latest209,
    latest209Timestamp: latest209?.timestamp || null,
    latest209SeqLE: latest209?.seqLE ?? null,
    latest209HeaderContextHex: latest209?.headerContextHex || null,
  };
  if (!latest245 && !latest209) {
    addReason(reasons, "最近窗口未找到 209/245 0x46 请求。");
    blockers.push("No 0x46 request found in recent window.");
  } else if (!latest245 || !latest209) {
    warnings.push("Only one of DSC_CONFIG_209 / DSC_CONFIG_245 was found in recent window.");
  }

  const rdsDsc24Pair = pairRdsDsc24(parsedItems);
  if (rdsDsc24Pair.rds30Count < 10 || rdsDsc24Pair.dsc24Count < 10) {
    warnings.push("RDS30 / DSC24 count is low in recent window.");
  }
  if (rdsDsc24Pair.rds30Count > 0 && rdsDsc24Pair.sameSeqRatio < 0.95) {
    addReason(reasons, "RDS30 / DSC24 sameSeqRatio 低于 0.95。");
    blockers.push("RDS30/DSC24 pairing ratio below 0.95.");
  }

  const frameDistribution = {
    totalParsed: parsedItems.length,
    byLength: distribution(parsedItems, (item) => item.length),
    byTypeBytes: distribution(parsedItems, (item) => item.typeBytes),
    byFrameClass: distribution(parsedItems, (item) => item.frameClass),
    unknownCount: parsedItems.filter((item) => item.frameClass === "UNKNOWN").length,
    unexpectedLengthCount: parsedItems.filter((item) => !KNOWN_LENGTHS.has(item.length)).length,
    unexpectedTypeBytes: [...new Set(parsedItems.filter((item) => !KNOWN_TYPE_BYTES.has(item.typeBytes)).map((item) => item.typeBytes))],
  };
  if (frameDistribution.unknownCount > 0) warnings.push("Recent window contains UNKNOWN frames.");
  if (frameDistribution.unexpectedLengthCount > 0) warnings.push("Recent window contains unexpected lengths.");
  if (frameDistribution.unexpectedTypeBytes.length > 0) warnings.push("Recent window contains unexpected typeBytes.");
  if (frameDistribution.unknownCount > 50 || frameDistribution.unexpectedLengthCount > 50) {
    addReason(reasons, "最近窗口出现大量 UNKNOWN 或新长度。");
    blockers.push("Large amount of UNKNOWN or unexpected-length frames.");
  }

  const checksum = checksumQuick(parsedItems);
  if (checksum.anyInvalidCritical) {
    addReason(reasons, "RDS30/209/245 checksum 快速验证异常。");
    blockers.push(`Critical checksum invalid: ${checksum.invalidCriticalClasses.join(", ")}`);
  }

  let readiness = "ready";
  if (blockers.length) readiness = "not_ready";
  else if (warnings.length) readiness = "warning";
  const nextRecommendation =
    readiness === "ready"
      ? "可以进入人工审批是否编写 dry-run one-shot 脚本的讨论，但仍不执行实验。"
      : readiness === "warning"
        ? "先处理 warning 项，再讨论是否进入下一阶段。"
        : "不得进入实验脚本阶段。";

  const result = {
    generatedAt,
    readiness,
    safeToExperiment: false,
    reason: reasons,
    blockers,
    warnings,
    nextRecommendation,
    checks: {
      git,
      gitDirtyExplanation,
      files,
      rawLog,
      health,
      udp,
      latest0x46,
      rdsDsc24Pair,
      frameDistribution,
      checksum,
    },
    safety: {
      udpSent: false,
      ackAdded: false,
      sendOneShotAckRun: false,
      sendableFrameHexGenerated: false,
      servicePyModified: false,
      businessTableWritten: false,
      onlineExperimentExecuted: false,
    },
  };

  const stamp = timestampForFileName(new Date());
  const date = ymdFromLog(input);
  const base = `class47-one-shot-precheck-${date}-${stamp}`;
  const jsonPath = path.join(outDir, `${base}.json`);
  const mdPath = path.join(outDir, `${base}.md`);
  fs.writeFileSync(jsonPath, JSON.stringify(result, null, 2), "utf8");
  fs.writeFileSync(mdPath, renderMd(result), "utf8");
  console.log(JSON.stringify({
    readiness,
    safeToExperiment: false,
    reportMd: mdPath,
    reportJson: jsonPath,
    blockers,
    warnings,
    safety: result.safety,
  }, null, 2));
}

main().catch((error) => {
  console.error(JSON.stringify({
    error: error.message,
    safety: {
      udpSent: false,
      ackAdded: false,
      sendOneShotAckRun: false,
      sendableFrameHexGenerated: false,
      servicePyModified: false,
      businessTableWritten: false,
      onlineExperimentExecuted: false,
    },
  }, null, 2));
  process.exit(1);
});
