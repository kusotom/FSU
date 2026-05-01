#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const RAW_DIR = path.join(__dirname, "..", "logs", "fsu_raw_packets");
const RAW_LOG_RE = /^\d{4}-\d{2}-\d{2}\.jsonl$/;
const KNOWN_LENGTHS = new Set([24, 30, 209, 245]);
const KNOWN_TYPE_A = new Set(["1f00d2ff", "1180d2ff", "110046ff"]);
const KNOWN_FRAME_CLASSES = new Set([
  "DSC_SHORT_24_TYPE_1F00_D2FF",
  "RDS_SHORT_30_TYPE_1180_D2FF",
  "DSC_CONFIG_209_TYPE_1100_46FF",
  "DSC_CONFIG_245_TYPE_1100_46FF",
]);
const CONFIG_FRAME_CLASSES = new Set(["DSC_CONFIG_209_TYPE_1100_46FF", "DSC_CONFIG_245_TYPE_1100_46FF"]);

function inc(map, key) {
  const normalized = key === undefined || key === null || key === "" ? "(empty)" : String(key);
  map.set(normalized, (map.get(normalized) || 0) + 1);
}

function top(map, limit = 100) {
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .slice(0, limit)
    .map(([value, count]) => ({ value, count }));
}

function rawLogs() {
  if (!fs.existsSync(RAW_DIR)) return [];
  return fs
    .readdirSync(RAW_DIR)
    .filter((name) => RAW_LOG_RE.test(name))
    .sort()
    .map((name) => path.join(RAW_DIR, name));
}

function parseTime(value) {
  const ms = Date.parse(value || "");
  return Number.isFinite(ms) ? ms : null;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * p)));
  return sorted[index];
}

function sample(packet, parsed, line) {
  return {
    line,
    receivedAt: packet.receivedAt,
    protocol: packet.protocol,
    remoteAddress: packet.remoteAddress,
    remotePort: packet.remotePort,
    localPort: packet.localPort,
    frameClass: parsed.frameClass,
    typeA: parsed.typeA,
    length: parsed.totalLength,
    payloadLengthCandidate: parsed.payloadLengthCandidate,
    uris: parsed.uris || [],
    rawHex: packet.rawHex,
  };
}

function emptyDay(date, logPath) {
  return {
    date,
    logPath,
    totalPackets: 0,
    protocolCounts: new Map(),
    frameClassCounts: new Map(),
    typeLengthCounts: new Map(),
    remotePortCounts: new Map(),
    dscConfigTimes: [],
    dscShortTimes: [],
    rdsShortTimes: [],
    unknownSamples: [],
    payloadLengthAnomalies: [],
    businessFrameCandidates: [],
    parseErrors: [],
    frameClassesSeen: new Set(),
    typeASeen: new Set(),
    lengthsSeen: new Set(),
  };
}

function scanLog(logPath) {
  const date = path.basename(logPath, ".jsonl");
  const day = emptyDay(date, logPath);
  const lines = fs.readFileSync(logPath, "utf8").split(/\r?\n/);
  lines.forEach((line, index) => {
    if (!line.trim()) return;
    let packet;
    try {
      packet = JSON.parse(line);
    } catch (error) {
      day.parseErrors.push({ line: index + 1, error: error.message });
      return;
    }
    const parsed = parseFsuFrame(packet.rawHex, { protocol: packet.protocol, includeAscii: true });
    day.totalPackets += 1;
    inc(day.protocolCounts, packet.protocol);
    inc(day.frameClassCounts, parsed.frameClass);
    inc(day.typeLengthCounts, `${packet.protocol}|${parsed.typeA}|${parsed.totalLength}`);
    inc(day.remotePortCounts, `${packet.protocol}|${packet.remotePort}`);
    day.frameClassesSeen.add(parsed.frameClass);
    day.typeASeen.add(parsed.typeA);
    day.lengthsSeen.add(String(parsed.totalLength));

    const timeMs = parseTime(packet.receivedAt);
    if (timeMs !== null && CONFIG_FRAME_CLASSES.has(parsed.frameClass)) day.dscConfigTimes.push(timeMs);
    if (timeMs !== null && parsed.frameClass === "DSC_SHORT_24_TYPE_1F00_D2FF") day.dscShortTimes.push(timeMs);
    if (timeMs !== null && parsed.frameClass === "RDS_SHORT_30_TYPE_1180_D2FF") day.rdsShortTimes.push(timeMs);

    if (parsed.frameClass === "UNKNOWN" && day.unknownSamples.length < 50) {
      day.unknownSamples.push(sample(packet, parsed, index + 1));
    }
    if (parsed.payloadLengthCandidate !== null && parsed.payloadLengthCandidate !== parsed.bodyLength) {
      if (day.payloadLengthAnomalies.length < 100) day.payloadLengthAnomalies.push(sample(packet, parsed, index + 1));
    }

    const hasVisibleAscii = (parsed.asciiSpans || []).some((span) => /[A-Za-z]{4,}/.test(span.text));
    const candidate =
      parsed.frameClass === "UNKNOWN" ||
      !KNOWN_LENGTHS.has(parsed.totalLength) ||
      !KNOWN_TYPE_A.has(parsed.typeA) ||
      (hasVisibleAscii && !CONFIG_FRAME_CLASSES.has(parsed.frameClass));
    if (candidate && day.businessFrameCandidates.length < 100) {
      day.businessFrameCandidates.push({
        ...sample(packet, parsed, index + 1),
        candidateReasons: {
          unknown: parsed.frameClass === "UNKNOWN",
          nonStandardLength: !KNOWN_LENGTHS.has(parsed.totalLength),
          newTypeA: !KNOWN_TYPE_A.has(parsed.typeA),
          visibleAscii: hasVisibleAscii,
        },
      });
    }
  });
  return day;
}

function intervals(times) {
  const sorted = [...times].sort((a, b) => a - b);
  const values = [];
  for (let i = 1; i < sorted.length; i += 1) values.push((sorted[i] - sorted[i - 1]) / 1000);
  return {
    count: sorted.length,
    medianSeconds: median(values),
    p10Seconds: percentile(values, 0.1),
    p90Seconds: percentile(values, 0.9),
  };
}

function stage(day) {
  const configCount =
    (day.frameClassCounts.get("DSC_CONFIG_209_TYPE_1100_46FF") || 0) +
    (day.frameClassCounts.get("DSC_CONFIG_245_TYPE_1100_46FF") || 0);
  const businessCount = day.businessFrameCandidates.filter((item) => item.remoteAddress !== "127.0.0.1").length;
  const unknownCount = day.frameClassCounts.get("UNKNOWN") || 0;
  const configPeriod = intervals(day.dscConfigTimes).medianSeconds;
  const repeatingConfig = configCount >= 10 && configPeriod !== null && configPeriod <= 10;
  return {
    stillLoginConfigRepeatStage: repeatingConfig && businessCount === 0,
    businessDataStageSignals: businessCount > 0,
    abnormalSignals: unknownCount > 0 || day.payloadLengthAnomalies.length > 0,
    summary: repeatingConfig
      ? "DSC_CONFIG frames are repeating; no confirmed business-data stage found."
      : "No strong repeating DSC_CONFIG stage signal in this day.",
  };
}

function finalizeDay(day, previousSeen) {
  const report = {
    generatedAt: new Date().toISOString(),
    date: day.date,
    sourceLog: day.logPath,
    safety: {
      readOnly: true,
      udpSendEnabled: false,
      autoAckEnabled: false,
      businessTableWrites: false,
    },
    totalPackets: day.totalPackets,
    protocolCounts: Object.fromEntries(day.protocolCounts),
    frameClassDistribution: top(day.frameClassCounts),
    typeLengthCombinations: top(day.typeLengthCounts, 200),
    remotePortDistribution: top(day.remotePortCounts, 100),
    periods: {
      dscConfig209Or245: intervals(day.dscConfigTimes),
      dscShort24: intervals(day.dscShortTimes),
      rdsShort30: intervals(day.rdsShortTimes),
    },
    unknownCount: day.frameClassCounts.get("UNKNOWN") || 0,
    newFrameClasses: [...day.frameClassesSeen].filter((item) => !previousSeen.frameClasses.has(item)).sort(),
    newTypeA: [...day.typeASeen].filter((item) => !previousSeen.typeA.has(item)).sort(),
    newLengths: [...day.lengthsSeen].filter((item) => !previousSeen.lengths.has(item)).sort(),
    payloadLengthAnomalies: day.payloadLengthAnomalies,
    suspiciousBusinessFrameCandidates: day.businessFrameCandidates,
    unknownSamples: day.unknownSamples,
    deviceStage: stage(day),
    interpretation: [
      "Read-only daily observation report.",
      "Candidate business frames are heuristic and do not confirm protocol semantics.",
      "No UDP packets are sent and no ACK is generated.",
    ],
    parseErrors: day.parseErrors.slice(0, 100),
  };
  return report;
}

function writeReport(report) {
  const jsonPath = path.join(RAW_DIR, `daily-observation-${report.date}.json`);
  const mdPath = path.join(RAW_DIR, `daily-observation-${report.date}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  const lines = [
    `# FSU Daily Observation ${report.date}`,
    "",
    "Read-only report. No UDP packets were sent, no ACK was generated, and no business tables were written.",
    "",
    `Total packets: ${report.totalPackets}`,
    `UNKNOWN: ${report.unknownCount}`,
    `Stage: ${report.deviceStage.summary}`,
    "",
    "## Protocol Counts",
    "",
    "```json",
    JSON.stringify(report.protocolCounts, null, 2),
    "```",
    "",
    "## FrameClass Distribution",
    "",
    "| frameClass | count |",
    "| --- | --- |",
    ...report.frameClassDistribution.map((row) => `| ${row.value} | ${row.count} |`),
    "",
    "## TypeA / Length Combinations",
    "",
    "| combination | count |",
    "| --- | --- |",
    ...report.typeLengthCombinations.map((row) => `| ${row.value} | ${row.count} |`),
    "",
  ];
  fs.writeFileSync(mdPath, `${lines.join("\n")}\n`, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const previousSeen = { frameClasses: new Set(), typeA: new Set(), lengths: new Set() };
  const outputs = [];
  for (const logPath of rawLogs()) {
    const day = scanLog(logPath);
    const report = finalizeDay(day, previousSeen);
    report.reportPaths = writeReport(report);
    outputs.push(report);
    for (const item of day.frameClassesSeen) previousSeen.frameClasses.add(item);
    for (const item of day.typeASeen) previousSeen.typeA.add(item);
    for (const item of day.lengthsSeen) previousSeen.lengths.add(item);
  }
  console.log(JSON.stringify({ generatedAt: new Date().toISOString(), reports: outputs.map((item) => item.reportPaths) }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
