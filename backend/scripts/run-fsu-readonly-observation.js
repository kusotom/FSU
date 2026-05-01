#!/usr/bin/env node
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const { execFileSync } = require("child_process");
const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const RAW_DIR = path.join(PROJECT_ROOT, "backend", "logs", "fsu_raw_packets");
const RAW_LOG_RE = /^\d{4}-\d{2}-\d{2}\.jsonl$/;
const DEVICE_IP = "192.168.100.100";
const KNOWN_FRAME_CLASSES = new Set([
  "DSC_SHORT_24_TYPE_1F00_D2FF",
  "RDS_SHORT_30_TYPE_1180_D2FF",
  "DSC_CONFIG_209_TYPE_1100_46FF",
  "DSC_CONFIG_245_TYPE_1100_46FF",
]);
const KNOWN_TYPE_A = new Set(["1f00d2ff", "1180d2ff", "110046ff"]);
const KNOWN_LENGTHS = new Set([24, 30, 209, 245]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function timestampForFile(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}-${pad(date.getHours())}${pad(
    date.getMinutes()
  )}${pad(date.getSeconds())}`;
}

function rawLogs() {
  if (!fs.existsSync(RAW_DIR)) return [];
  return fs
    .readdirSync(RAW_DIR)
    .filter((name) => RAW_LOG_RE.test(name))
    .sort()
    .map((name) => path.join(RAW_DIR, name));
}

function latestRawLog() {
  const logs = rawLogs();
  if (!logs.length) throw new Error(`No raw packet logs found in ${RAW_DIR}`);
  return logs[logs.length - 1];
}

function dateFromLog(logPath) {
  const match = path.basename(logPath).match(/^(\d{4}-\d{2}-\d{2})\.jsonl$/);
  return match ? match[1] : new Date().toISOString().slice(0, 10);
}

function requestJson(url, options = {}) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: options.timeoutMs || 5000, headers: options.headers || {} }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        let json = null;
        try {
          json = body ? JSON.parse(body) : null;
        } catch {
          json = null;
        }
        resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, statusCode: res.statusCode, json });
      });
    });
    req.on("timeout", () => {
      req.destroy(new Error("timeout"));
    });
    req.on("error", (error) => {
      resolve({ ok: false, statusCode: null, error: error.message });
    });
  });
}

function runNodeScript(scriptRelativePath, args = []) {
  const scriptPath = path.join(PROJECT_ROOT, scriptRelativePath);
  const stdout = execFileSync("node", [scriptPath, ...args], {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    maxBuffer: 50 * 1024 * 1024,
  });
  try {
    return JSON.parse(stdout);
  } catch (error) {
    throw new Error(`Failed to parse JSON output from ${scriptRelativePath}: ${error.message}`);
  }
}

function runNetstat() {
  try {
    return execFileSync("netstat", ["-ano"], { encoding: "utf8", windowsHide: true });
  } catch (error) {
    return error.stdout || "";
  }
}

function udpListening(netstatOutput, port) {
  const pattern = new RegExp(`^\\s*UDP\\s+0\\.0\\.0\\.0:${port}\\s+`, "m");
  const ipv6Pattern = new RegExp(`^\\s*UDP\\s+\\[::\\]:${port}\\s+`, "m");
  return pattern.test(netstatOutput) || ipv6Pattern.test(netstatOutput);
}

function readLatestPackets(logPath, maxLines = 20000) {
  const lines = fs.readFileSync(logPath, "utf8").trim().split(/\r?\n/);
  const selected = lines.slice(Math.max(0, lines.length - maxLines));
  const packets = [];
  selected.forEach((line, index) => {
    if (!line.trim()) return;
    try {
      const row = JSON.parse(line);
      if (row.protocol !== "UDP_DSC" && row.protocol !== "UDP_RDS") return;
      const parsed = parseFsuFrame(row.rawHex, { protocol: row.protocol, includeAscii: true });
      packets.push({ row, parsed, lineFromTailWindow: index + 1 });
    } catch {
      // Keep this script read-only and tolerant of partial writes.
    }
  });
  return packets;
}

function countBy(items, selector) {
  const map = new Map();
  for (const item of items) {
    const key = selector(item);
    const normalized = key === undefined || key === null || key === "" ? "(empty)" : String(key);
    map.set(normalized, (map.get(normalized) || 0) + 1);
  }
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([value, count]) => ({ value, count }));
}

function latestTimes(packets) {
  let latestDscTime = null;
  let latestRdsTime = null;
  for (const { row } of packets) {
    if (row.protocol === "UDP_DSC") latestDscTime = row.receivedAt || latestDscTime;
    if (row.protocol === "UDP_RDS") latestRdsTime = row.receivedAt || latestRdsTime;
  }
  return { latestDscTime, latestRdsTime };
}

function isRealDeviceNewFrame(item) {
  if (item.row.remoteAddress !== DEVICE_IP) return false;
  return (
    item.parsed.frameClass === "UNKNOWN" ||
    !KNOWN_FRAME_CLASSES.has(item.parsed.frameClass) ||
    !KNOWN_TYPE_A.has(item.parsed.typeA) ||
    !KNOWN_LENGTHS.has(item.parsed.totalLength)
  );
}

function isSuspectedBusinessFrame(item) {
  if (item.row.remoteAddress !== DEVICE_IP) return false;
  const asciiBusinessHint = (item.parsed.asciiSpans || []).some((span) => /[A-Za-z]{4,}/.test(span.text));
  return (
    isRealDeviceNewFrame(item) ||
    (item.row.protocol === "UDP_RDS" && item.parsed.totalLength !== 30) ||
    (item.row.protocol === "UDP_DSC" && ![24, 209, 245].includes(item.parsed.totalLength)) ||
    (asciiBusinessHint &&
      item.parsed.frameClass !== "DSC_CONFIG_209_TYPE_1100_46FF" &&
      item.parsed.frameClass !== "DSC_CONFIG_245_TYPE_1100_46FF")
  );
}

function packetSample(item) {
  return {
    receivedAt: item.row.receivedAt,
    protocol: item.row.protocol,
    remoteAddress: item.row.remoteAddress,
    remotePort: item.row.remotePort,
    localPort: item.row.localPort,
    length: item.parsed.totalLength,
    typeA: item.parsed.typeA,
    payloadLengthCandidate: item.parsed.payloadLengthCandidate,
    frameClass: item.parsed.frameClass,
    rawHex: item.row.rawHex,
    asciiSpans: item.parsed.asciiSpans || [],
    annotation: item.parsed.annotation || null,
  };
}

function writeJson(filePath, data) {
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

function writeMarkdown(filePath, result) {
  const lines = [
    `# FSU Readonly Observation Run ${result.runId}`,
    "",
    "Read-only automated inspection. No UDP packets were sent, no ACK was generated, fsu-gateway reply logic was not changed, and business tables were not written.",
    "",
    `- Run at: ${result.runAt}`,
    `- Latest raw log: ${result.latestRawLog}`,
    `- Health OK: ${result.healthOk}`,
    `- UDP DSC 9000 listening: ${result.udpDscListening}`,
    `- UDP RDS 7000 listening: ${result.udpRdsListening}`,
    `- Raw log growing: ${result.rawLogGrowing}`,
    `- Device online: ${result.deviceOnline}`,
    `- Latest DSC: ${result.latestDscTime || ""}`,
    `- Latest RDS: ${result.latestRdsTime || ""}`,
    "",
    "## Reports",
    "",
    `- Daily observation: ${result.reports.dailyObservationReport?.jsonPath || ""}`,
    `- New frame types: ${result.reports.newFrameTypesReport?.jsonPath || ""}`,
    `- Current state: ${result.reports.currentStateReport?.jsonPath || ""}`,
    `- Annotation v0.2: ${result.reports.annotationV02Report?.jsonPath || ""}`,
    "",
    "## Summary",
    "",
    `- UNKNOWN count: ${result.unknownCount}`,
    `- Real device UNKNOWN count: ${result.realDeviceUnknownCount}`,
    `- New typeA count: ${result.newTypeACount}`,
    `- New length count: ${result.newLengthCount}`,
    `- New frameClass count: ${result.newFrameClassCount}`,
    `- Suspected business frames count: ${result.suspectedBusinessFramesCount}`,
    `- Current state: ${result.currentStateJudgment}`,
    "",
    "## FrameClass Distribution",
    "",
    "| frameClass | count |",
    "| --- | ---: |",
    ...result.frameClassDistribution.map((row) => `| ${row.value} | ${row.count} |`),
    "",
    "## Safety",
    "",
    ...Object.entries(result.safety).map(([key, value]) => `- ${key}: ${value}`),
    "",
  ];
  fs.writeFileSync(filePath, `${lines.join("\n")}\n`, "utf8");
}

function writeNewFrameObservation(runId, samples) {
  if (!samples.length) return null;
  const jsonPath = path.join(RAW_DIR, `new-frame-observation-${runId}.json`);
  const mdPath = path.join(RAW_DIR, `new-frame-observation-${runId}.md`);
  const report = {
    generatedAt: new Date().toISOString(),
    safety: {
      noUdpSent: true,
      noAckAdded: true,
      gatewayReplyLogicUnchanged: true,
      businessTablesUnchanged: true,
    },
    samples,
  };
  writeJson(jsonPath, report);
  const lines = [
    `# New Frame Observation ${runId}`,
    "",
    "Read-only sample report. Parser is not modified and no ACK is sent.",
    "",
    "| receivedAt | protocol | remote | localPort | frameClass | typeA | length |",
    "| --- | --- | --- | ---: | --- | --- | ---: |",
    ...samples.map(
      (row) =>
        `| ${row.receivedAt || ""} | ${row.protocol || ""} | ${row.remoteAddress || ""}:${row.remotePort || ""} | ${
          row.localPort || ""
        } | ${row.frameClass || ""} | ${row.typeA || ""} | ${row.length || ""} |`
    ),
    "",
  ];
  fs.writeFileSync(mdPath, `${lines.join("\n")}\n`, "utf8");
  return { jsonPath, mdPath };
}

async function main() {
  const runAtDate = new Date();
  const runId = timestampForFile(runAtDate);
  fs.mkdirSync(RAW_DIR, { recursive: true });

  const logPath = latestRawLog();
  const dateStem = dateFromLog(logPath);
  const sizeBefore = fs.statSync(logPath).size;
  await sleep(5000);
  const sizeAfter = fs.statSync(logPath).size;

  const netstatOutput = runNetstat();
  const health = await requestJson("http://127.0.0.1:8000/health");

  let fsuDebugApi = {
    status: "skipped",
    reason: "FSU_DEBUG_BEARER_TOKEN is not set; admin password is not hardcoded in this readonly scheduler.",
  };
  if (process.env.FSU_DEBUG_BEARER_TOKEN) {
    const response = await requestJson("http://127.0.0.1:8000/api/v1/fsu-debug/raw-packets?max_records=1000&recent_limit=20", {
      timeoutMs: 15000,
      headers: { Authorization: `Bearer ${process.env.FSU_DEBUG_BEARER_TOKEN}` },
    });
    fsuDebugApi = {
      status: response.ok ? "success" : "failed",
      statusCode: response.statusCode,
      reason: response.error || null,
      hasAnnotation: Boolean(response.json?.recentPackets?.some((item) => item.annotation)),
      hasTypeAAnnotation: Boolean(response.json?.recentPackets?.some((item) => item.typeAAnnotation)),
    };
  }

  const dailyOutput = runNodeScript("backend/scripts/generate-fsu-daily-observation-report.js");
  const newFrameOutput = runNodeScript("backend/scripts/detect-fsu-new-frame-types.js");
  const stateOutput = runNodeScript("backend/scripts/infer-current-dsc-rds-state.js", [logPath]);
  const annotationOutput = runNodeScript("backend/scripts/generate-dsc-rds-annotation-v02-report.js", [logPath]);

  const packets = readLatestPackets(logPath);
  const { latestDscTime, latestRdsTime } = latestTimes(packets);
  const frameClassDistribution = countBy(packets, (item) => item.parsed.frameClass);
  const realDeviceNewFrames = packets.filter(isRealDeviceNewFrame);
  const suspectedBusinessFrames = packets.filter(isSuspectedBusinessFrame);
  const unknownCount = packets.filter((item) => item.parsed.frameClass === "UNKNOWN").length;
  const realDeviceUnknownCount = packets.filter((item) => item.row.remoteAddress === DEVICE_IP && item.parsed.frameClass === "UNKNOWN").length;
  const newTypeA = [...new Set(realDeviceNewFrames.map((item) => item.parsed.typeA).filter((typeA) => !KNOWN_TYPE_A.has(typeA)))];
  const newLengths = [
    ...new Set(realDeviceNewFrames.map((item) => item.parsed.totalLength).filter((length) => !KNOWN_LENGTHS.has(length))),
  ];
  const newFrameClasses = [
    ...new Set(realDeviceNewFrames.map((item) => item.parsed.frameClass).filter((frameClass) => !KNOWN_FRAME_CLASSES.has(frameClass))),
  ];

  const stateReport = stateOutput.reportPaths || {};
  const annotationReport = annotationOutput.reportPaths || {};
  const dailyReport =
    (dailyOutput.reports || []).find((item) => String(item.jsonPath || "").includes(`daily-observation-${dateStem}.json`)) || null;
  const newFrameReport = newFrameOutput.reportPaths || null;
  const currentStateJudgment = stateOutput.stateMachine?.currentState?.join(" + ") || stateOutput.deviceStage?.summary || "unknown";
  const deviceOnline = Boolean(latestDscTime || latestRdsTime);
  const newFrameSamples = [...realDeviceNewFrames, ...suspectedBusinessFrames].slice(0, 50).map(packetSample);
  const newFrameObservationReport = writeNewFrameObservation(runId, newFrameSamples);

  const result = {
    runAt: runAtDate.toISOString(),
    runId,
    latestRawLog: logPath,
    healthOk: health.ok,
    healthStatusCode: health.statusCode,
    fsuDebugApiChecked: fsuDebugApi.status,
    fsuDebugApi,
    udpDscListening: udpListening(netstatOutput, 9000),
    udpRdsListening: udpListening(netstatOutput, 7000),
    rawLogSizeBefore: sizeBefore,
    rawLogSizeAfter: sizeAfter,
    rawLogGrowing: sizeAfter > sizeBefore,
    latestDscTime,
    latestRdsTime,
    deviceOnline,
    reports: {
      dailyObservationReport: dailyReport,
      newFrameTypesReport: newFrameReport,
      currentStateReport: stateReport,
      annotationV02Report: annotationReport,
      newFrameObservationReport,
    },
    frameClassDistribution,
    unknownCount,
    realDeviceUnknownCount,
    newTypeACount: newTypeA.length,
    newTypeA,
    newLengthCount: newLengths.length,
    newLengths,
    newFrameClassCount: newFrameClasses.length,
    newFrameClasses,
    suspectedBusinessFramesCount: suspectedBusinessFrames.length,
    suspectedBusinessFrameSamples: suspectedBusinessFrames.slice(0, 20).map(packetSample),
    currentStateJudgment,
    safety: {
      noUdpSent: true,
      sendOneShotAckNotRun: true,
      noAckAdded: true,
      gatewayReplyLogicUnchanged: true,
      businessTablesUnchanged: true,
      rawLogDeleted: false,
      parserConclusionsUnchanged: true,
    },
  };

  const jsonPath = path.join(RAW_DIR, `readonly-observation-run-${runId}.json`);
  const mdPath = path.join(RAW_DIR, `readonly-observation-run-${runId}.md`);
  result.reportPaths = { jsonPath, mdPath };
  writeJson(jsonPath, result);
  writeMarkdown(mdPath, result);
  console.log(JSON.stringify(result, null, 2));
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
}
