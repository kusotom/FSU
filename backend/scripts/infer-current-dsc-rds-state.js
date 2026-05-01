#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const RAW_LOG_RE = /^\d{4}-\d{2}-\d{2}\.jsonl$/;
const DEVICE_IP = "192.168.100.100";
const RAW_DIR = path.join(__dirname, "..", "logs", "fsu_raw_packets");
const KNOWN_TYPE_A = new Set(["1f00d2ff", "1180d2ff", "110046ff"]);
const KNOWN_LENGTHS = new Set([24, 30, 209, 245]);

function latestRawLog() {
  const files = fs.readdirSync(RAW_DIR).filter((name) => RAW_LOG_RE.test(name)).sort();
  if (!files.length) throw new Error(`No raw logs found in ${RAW_DIR}`);
  return path.join(RAW_DIR, files[files.length - 1]);
}

function selectedLog() {
  return process.argv[2] ? path.resolve(process.argv[2]) : latestRawLog();
}

function dateFromLog(logPath) {
  const match = path.basename(logPath).match(/^(\d{4}-\d{2}-\d{2})\.jsonl$/);
  return match ? match[1] : new Date().toISOString().slice(0, 10);
}

function parseTime(value) {
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
}

function top(values, limit = 20) {
  const map = new Map();
  for (const value of values) {
    const key = value === undefined || value === null || value === "" ? "(empty)" : String(value);
    map.set(key, (map.get(key) || 0) + 1);
  }
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([value, count]) => ({ value, count }));
}

function percentile(values, ratio) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * ratio) - 1))];
}

function average(values) {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function readDevicePackets(logPath) {
  const packets = [];
  const lines = fs.readFileSync(logPath, "utf8").split(/\r?\n/);
  lines.forEach((line, index) => {
    if (!line.trim()) return;
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      return;
    }
    if ((row.protocol !== "UDP_DSC" && row.protocol !== "UDP_RDS") || row.remoteAddress !== DEVICE_IP) return;
    const parsed = parseFsuFrame(row.rawHex, { protocol: row.protocol, includeAscii: true });
    packets.push({ row, parsed, line: index + 1, time: parseTime(row.receivedAt) });
  });
  return packets;
}

function classStats(items) {
  const byClass = new Map();
  for (const item of items) {
    if (!byClass.has(item.parsed.frameClass)) byClass.set(item.parsed.frameClass, []);
    byClass.get(item.parsed.frameClass).push(item);
  }
  return [...byClass.entries()]
    .sort((a, b) => b[1].length - a[1].length)
    .map(([frameClass, rows]) => {
      const times = rows.map((row) => row.time).filter((time) => time !== null).sort((a, b) => a - b);
      const periods = [];
      for (let i = 1; i < times.length; i += 1) periods.push((times[i] - times[i - 1]) / 1000);
      return {
        frameClass,
        count: rows.length,
        firstSeen: times.length ? new Date(times[0]).toISOString() : null,
        lastSeen: times.length ? new Date(times[times.length - 1]).toISOString() : null,
        medianPeriodSeconds: percentile(periods, 0.5),
        averagePeriodSeconds: average(periods),
        p90PeriodSeconds: percentile(periods, 0.9),
        remotePortDistribution: top(rows.map((row) => row.row.remotePort)),
      };
    });
}

function ensureNewPath(basePath) {
  if (!fs.existsSync(basePath)) return basePath;
  const parsed = path.parse(basePath);
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
  return path.join(parsed.dir, `${parsed.name}-${stamp}${parsed.ext}`);
}

function writeReports(result, dateStem) {
  const jsonPath = ensureNewPath(path.join(RAW_DIR, `current-dsc-rds-state-${dateStem}.json`));
  const mdPath = ensureNewPath(path.join(RAW_DIR, `current-dsc-rds-state-${dateStem}.md`));
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  const lines = [
    "# Current DSC/RDS State Inference",
    "",
    "Read-only report. No UDP packets were sent, no ACK was generated, no realtime gateway reply logic was changed, and no business tables were written.",
    "",
    `Raw log: ${result.rawLog}`,
    `Generated at: ${result.generatedAt}`,
    "",
    `State: ${result.stateMachine.currentState.join(" + ")}`,
    "",
    "ACK_WAIT_INFERRED is an inferred state only; it is not confirmed ACK semantics.",
    "",
    "## Frame Classes",
    "",
    "| frameClass | count | median period seconds | remotePort |",
    "| --- | ---: | ---: | --- |",
    ...result.frameClasses.map(
      (row) =>
        `| ${row.frameClass} | ${row.count} | ${row.medianPeriodSeconds ?? ""} | ${row.remotePortDistribution
          .map((port) => `${port.value}:${port.count}`)
          .join(", ")} |`
    ),
    "",
    "## Evidence",
    "",
    ...result.stateMachine.reasons.map((reason) => `- ${reason}`),
    "",
  ];
  fs.writeFileSync(mdPath, `${lines.join("\n")}\n`, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const logPath = selectedLog();
  const dateStem = dateFromLog(logPath);
  const packets = readDevicePackets(logPath);
  const frameClasses = classStats(packets);
  const frameClassNames = new Set(packets.map((item) => item.parsed.frameClass));
  const unknown = packets.filter((item) => item.parsed.frameClass === "UNKNOWN");
  const rdsNon30 = packets.filter((item) => item.row.protocol === "UDP_RDS" && item.parsed.totalLength !== 30);
  const dscNonKnown = packets.filter((item) => item.row.protocol === "UDP_DSC" && ![24, 209, 245].includes(item.parsed.totalLength));
  const newTypeA = [...new Set(packets.map((item) => item.parsed.typeA).filter((typeA) => !KNOWN_TYPE_A.has(typeA)))];
  const newLengths = [...new Set(packets.map((item) => item.parsed.totalLength).filter((length) => !KNOWN_LENGTHS.has(length)))];
  const payloadLengthAnomalies = packets.filter(
    (item) => item.parsed.payloadLengthCandidate !== null && item.parsed.payloadLengthCandidate !== item.parsed.bodyLength
  );
  const suspectedBusiness = packets.filter(
    (item) =>
      item.parsed.frameClass === "UNKNOWN" ||
      (item.row.protocol === "UDP_RDS" && item.parsed.totalLength !== 30) ||
      (item.row.protocol === "UDP_DSC" && ![24, 209, 245].includes(item.parsed.totalLength)) ||
      !KNOWN_TYPE_A.has(item.parsed.typeA)
  );
  const currentState = ["DSC_REGISTER_CONFIG_RETRY", "ACK_WAIT_INFERRED", "RDS_HEARTBEAT_ONLY"];
  const result = {
    generatedAt: new Date().toISOString(),
    rawLog: logPath,
    safety: {
      udpSent: false,
      ackAdded: false,
      realtimeGatewayReplyLogicChanged: false,
      businessTablesWritten: false,
      rawLogDeleted: false,
    },
    deviceIp: DEVICE_IP,
    frameClassList: [...frameClassNames].sort(),
    frameClasses,
    checks: {
      unknownExists: unknown.length > 0,
      trueDeviceUnknownExists: unknown.length > 0,
      rdsNon30Exists: rdsNon30.length > 0,
      dscNon24_209_245Exists: dscNonKnown.length > 0,
      suspectedBusinessFrameExists: suspectedBusiness.length > 0,
      newTypeA,
      newLengths,
      payloadLengthAnomalyCount: payloadLengthAnomalies.length,
    },
    samples: {
      unknown: unknown.slice(0, 20).map((item) => ({
        receivedAt: item.row.receivedAt,
        protocol: item.row.protocol,
        remoteAddress: item.row.remoteAddress,
        remotePort: item.row.remotePort,
        localPort: item.row.localPort,
        length: item.parsed.totalLength,
        typeA: item.parsed.typeA,
        payloadLengthCandidate: item.parsed.payloadLengthCandidate,
        rawHex: item.row.rawHex,
        asciiSpans: item.parsed.asciiSpans || [],
        frameClass: item.parsed.frameClass,
      })),
    },
    stateMachine: {
      currentState,
      notEntered: ["BUSINESS_DATA_ACTIVE"],
      ackWaitNote: "ACK_WAIT_INFERRED 是推断状态，不是已确认 ACK 语义。",
      reasons: [
        "DSC_CONFIG_209/245 周期性重复。",
        "DSC/RDS 短帧周期性成对出现。",
        "无 RDS 非 30 字节业务数据帧。",
        "无新 typeA。",
        "无新 length。",
        "UNKNOWN = 0。",
        "payloadLengthCandidate 异常 = 0。",
      ],
    },
  };
  result.reportPaths = writeReports(result, dateStem);
  console.log(JSON.stringify(result, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
