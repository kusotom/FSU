#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { parseFsuFrame, FRAME_CLASS_ANNOTATIONS, TYPE_A_ANNOTATIONS } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const RAW_LOG_RE = /^\d{4}-\d{2}-\d{2}\.jsonl$/;
const DEVICE_IP = "192.168.100.100";
const RAW_DIR = path.join(__dirname, "..", "logs", "fsu_raw_packets");

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

function top(values) {
  const map = new Map();
  for (const value of values) map.set(value, (map.get(value) || 0) + 1);
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .map(([value, count]) => ({ value, count }));
}

function percentile(values, ratio) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * ratio) - 1))];
}

function readPackets(logPath) {
  const packets = [];
  fs.readFileSync(logPath, "utf8")
    .split(/\r?\n/)
    .forEach((line) => {
      if (!line.trim()) return;
      let row;
      try {
        row = JSON.parse(line);
      } catch {
        return;
      }
      if ((row.protocol !== "UDP_DSC" && row.protocol !== "UDP_RDS") || row.remoteAddress !== DEVICE_IP) return;
      const parsed = parseFsuFrame(row.rawHex, { protocol: row.protocol, includeAscii: true });
      packets.push({ row, parsed, time: Date.parse(row.receivedAt) });
    });
  return packets;
}

function periodsFor(packets, frameClass) {
  const times = packets
    .filter((item) => item.parsed.frameClass === frameClass && Number.isFinite(item.time))
    .map((item) => item.time)
    .sort((a, b) => a - b);
  const periods = [];
  for (let i = 1; i < times.length; i += 1) periods.push((times[i] - times[i - 1]) / 1000);
  return {
    count: times.length,
    medianSeconds: percentile(periods, 0.5),
    p90Seconds: percentile(periods, 0.9),
  };
}

function ensureNewPath(basePath) {
  if (!fs.existsSync(basePath)) return basePath;
  const parsed = path.parse(basePath);
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
  return path.join(parsed.dir, `${parsed.name}-${stamp}${parsed.ext}`);
}

function writeReports(result, dateStem) {
  const jsonPath = ensureNewPath(path.join(RAW_DIR, `dsc-rds-annotation-v0.2-${dateStem}.json`));
  const mdPath = ensureNewPath(path.join(RAW_DIR, `dsc-rds-annotation-v0.2-${dateStem}.md`));
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  const lines = [
    "# DSC/RDS Annotation v0.2",
    "",
    "Read-only report. No UDP packets were sent, no ACK was generated, no realtime gateway reply logic was changed, no business tables were written, no raw logs were deleted, and online replies remain disabled.",
    "",
    `Raw log: ${result.rawLog}`,
    `Generated at: ${result.generatedAt}`,
    "",
    "## Current State",
    "",
    `State: ${result.currentState.join(" + ")}`,
    "",
    "ACK_WAIT_INFERRED is an inferred state only; it is not confirmed ACK semantics.",
    "",
    "## FrameClass Annotation Table",
    "",
    "| frameClass | semanticClass | chineseName | confidence | channel | length | typeA | currentPeriod | businessDataConfirmed |",
    "| --- | --- | --- | ---: | --- | ---: | --- | ---: | --- |",
    ...result.frameClassAnnotations.map(
      (row) =>
        `| ${row.frameClass} | ${row.semanticClass} | ${row.chineseName} | ${row.confidence} | ${row.channel} | ${row.totalLength} | ${row.typeA} | ${row.currentPeriod?.medianSeconds ?? ""} | ${row.businessDataConfirmed} |`
    ),
    "",
    "## Not Yet Observed",
    "",
    ...result.notYetObserved.map((item) => `- ${item}`),
    "",
    "## Unknowns",
    "",
    ...result.stillUnknown.map((item) => `- ${item}`),
    "",
  ];
  fs.writeFileSync(mdPath, `${lines.join("\n")}\n`, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const logPath = selectedLog();
  const dateStem = dateFromLog(logPath);
  const packets = readPackets(logPath);
  const knownFrameClasses = [
    "DSC_CONFIG_209_TYPE_1100_46FF",
    "DSC_CONFIG_245_TYPE_1100_46FF",
    "DSC_SHORT_24_TYPE_1F00_D2FF",
    "RDS_SHORT_30_TYPE_1180_D2FF",
  ];
  const frameClassAnnotations = knownFrameClasses.map((frameClass) => ({
    ...FRAME_CLASS_ANNOTATIONS[frameClass],
    currentPeriod: periodsFor(packets, frameClass),
  }));
  const typeAAnnotations = Object.values(TYPE_A_ANNOTATIONS);
  const frameClassSeen = top(packets.map((item) => item.parsed.frameClass));
  const trueUnknown = packets.filter((item) => item.parsed.frameClass === "UNKNOWN");
  const rdsNon30 = packets.filter((item) => item.row.protocol === "UDP_RDS" && item.parsed.totalLength !== 30);
  const dscNonKnown = packets.filter((item) => item.row.protocol === "UDP_DSC" && ![24, 209, 245].includes(item.parsed.totalLength));
  const result = {
    generatedAt: new Date().toISOString(),
    rawLog: logPath,
    safety: {
      udpSent: false,
      ackAdded: false,
      realtimeGatewayReplyLogicChanged: false,
      businessTablesWritten: false,
      rawLogDeleted: false,
      onlineReplyEnabled: false,
    },
    channelAnnotations: [
      {
        protocol: "UDP_DSC",
        annotation: "DSC 主控/调度/登录配置候选通道",
        note: "只读逆向注释，未由厂商协议文档确认。",
      },
      {
        protocol: "UDP_RDS",
        annotation: "RDS 实时数据/保活候选通道",
        note: "只读逆向注释，未由厂商协议文档确认。",
      },
    ],
    frameClassAnnotations,
    typeAAnnotations,
    currentSeenFrameClasses: frameClassSeen,
    currentState: ["DSC_REGISTER_CONFIG_RETRY", "ACK_WAIT_INFERRED", "RDS_HEARTBEAT_ONLY"],
    stateNotes: [
      "未进入 BUSINESS_DATA_ACTIVE。",
      "ACK_WAIT_INFERRED 不是确认 ACK 状态，只是根据重复配置帧和无业务帧推断。",
    ],
    notYetObserved: [
      "RDS_REALDATA",
      "DSC_EVENT",
      "DSC_CMD_ACK",
      "DSC_LOGIN_ACK",
      "CONFIG_ACK",
      "RDS 非 30 字节业务帧",
      "真实设备 UNKNOWN",
    ],
    stillUnknown: [
      "209/245 payload 的全部字段语义",
      "1100_46FF 是否官方注册命令",
      "1F00_D2FF 是否官方心跳或 ACK 等待帧",
      "1180_D2FF 是否官方 RDS 心跳",
      "ACK 应答格式是否被设备线上接受",
      "RDS 实时数据 payload 结构",
      "业务数据帧 typeA / length",
      "端口/通道的官方含义",
    ],
    currentChecks: {
      trueDeviceUnknownCount: trueUnknown.length,
      rdsNon30Count: rdsNon30.length,
      dscNon24_209_245Count: dscNonKnown.length,
      businessDataActive: false,
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
