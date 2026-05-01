#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { parseFsuFrame, BODY_OFFSET, CHECKSUM_OFFSET } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const RAW_LOG_RE = /^\d{4}-\d{2}-\d{2}\.jsonl$/;
const DEVICE_IP = "192.168.100.100";
const RAW_DIR = path.join(__dirname, "..", "logs", "fsu_raw_packets");
const CONFIG_CLASSES = new Set(["DSC_CONFIG_209_TYPE_1100_46FF", "DSC_CONFIG_245_TYPE_1100_46FF"]);
const URI_RE = /\b(?:udp|ftp):\/\/[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]+/g;

function latestRawLog() {
  const files = fs
    .readdirSync(RAW_DIR)
    .filter((name) => RAW_LOG_RE.test(name))
    .sort();
  if (!files.length) throw new Error(`No raw logs found in ${RAW_DIR}`);
  return path.join(RAW_DIR, files[files.length - 1]);
}

function selectedLog() {
  const arg = process.argv[2];
  return arg ? path.resolve(arg) : latestRawLog();
}

function dateFromLog(logPath) {
  const match = path.basename(logPath).match(/^(\d{4}-\d{2}-\d{2})\.jsonl$/);
  return match ? match[1] : new Date().toISOString().slice(0, 10);
}

function readPackets(logPath) {
  const out = [];
  const lines = fs.readFileSync(logPath, "utf8").split(/\r?\n/);
  lines.forEach((line, index) => {
    if (!line.trim()) return;
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      return;
    }
    if (row.protocol !== "UDP_DSC" || row.remoteAddress !== DEVICE_IP) return;
    if (row.remoteAddress === "127.0.0.1" || /hello fsu udp/i.test(row.rawText || "")) return;
    const parsed = parseFsuFrame(row.rawHex, { protocol: row.protocol, includeAscii: true, includePayloadHex: true });
    if (!CONFIG_CLASSES.has(parsed.frameClass)) return;
    out.push({ row, parsed, sourceLine: index + 1, buf: Buffer.from(row.rawHex, "hex") });
  });
  return out;
}

function top(values, limit = 10) {
  const map = new Map();
  for (const value of values) map.set(value, (map.get(value) || 0) + 1);
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .slice(0, limit)
    .map(([value, count]) => ({ value, count }));
}

function fieldVariation(items, maxLength) {
  const rows = [];
  for (let offset = 0; offset < maxLength; offset += 1) {
    const values = items.map((item) => (offset < item.buf.length ? item.buf[offset].toString(16).padStart(2, "0") : "(missing)"));
    const distinct = [...new Set(values)];
    rows.push({
      offset,
      offsetHex: `0x${offset.toString(16)}`,
      fixed: distinct.length === 1,
      fixedValue: distinct.length === 1 ? distinct[0] : null,
      distinctCount: distinct.length,
      topValues: top(values, 5),
    });
  }
  return rows;
}

function asciiSummary(items) {
  const uris = [];
  const ipAddresses = [];
  const ports = [];
  const tokens = { dhcp: 0, root: 0, hello: 0, explicitIp: 0 };
  for (const item of items) {
    for (const uri of item.parsed.uris || []) uris.push(uri);
    for (const ip of item.parsed.ipAddresses || []) {
      ipAddresses.push(ip);
      if (ip === DEVICE_IP) tokens.explicitIp += 1;
    }
    for (const port of item.parsed.ports || []) ports.push(port);
    const text = (item.parsed.asciiSpans || []).map((span) => span.text).join("\n");
    tokens.dhcp += (text.match(/\[dhcp\]/g) || []).length;
    tokens.root += (text.match(/root/g) || []).length;
    tokens.hello += (text.match(/hello/g) || []).length;
  }
  return {
    uris: top(uris, 20),
    ipAddresses: top(ipAddresses, 20),
    ports: top(ports, 20),
    tokens,
  };
}

function uriLengthExplanation() {
  const pairs = [
    ["udp://[dhcp]:6002", "udp://192.168.100.100:6002"],
    ["udp://[dhcp]:6002", "udp://192.168.100.100:6002"],
    ["udp://[dhcp]:6002", "udp://192.168.100.100:6002"],
    ["ftp://root:hello@[dhcp]", "ftp://root:hello@192.168.100.100"],
  ];
  const rows = pairs.map(([dhcp, explicit], index) => ({
    index,
    dhcp,
    explicit,
    dhcpLength: dhcp.length,
    explicitLength: explicit.length,
    delta: explicit.length - dhcp.length,
  }));
  const totalDelta = rows.reduce((sum, row) => sum + row.delta, 0);
  return {
    rows,
    totalDelta,
    targetDelta: 245 - 209,
    explainsLengthDelta: totalDelta === 245 - 209,
    conclusion:
      totalDelta === 245 - 209
        ? "209/245 更像同结构不同 URI 表示形式：209 使用 [dhcp] 占位，245 使用显式 IP。"
        : "URI 字符串长度差异尚不能完全解释 209/245 总长度差异。",
  };
}

function sampleInfo(item) {
  return {
    receivedAt: item.row.receivedAt,
    remotePort: item.row.remotePort,
    sourceLine: item.sourceLine,
    headerHex: item.parsed.headerHex,
    seqLE: item.parsed.seqLE,
    seqBE: item.parsed.seqBE,
    typeA: item.parsed.typeA,
    payloadLengthCandidate: item.parsed.payloadLengthCandidate,
    bodyLength: item.parsed.bodyLength,
    checksumLE: item.parsed.checksumLE,
    bodyOffset: item.parsed.bodyOffset,
    checksumOffset: item.parsed.checksumOffset,
    bodyHexPrefix: item.parsed.bodyHex ? item.parsed.bodyHex.slice(0, 160) : null,
    uris: item.parsed.uris || [],
  };
}

function ensureNewPath(basePath) {
  if (!fs.existsSync(basePath)) return basePath;
  const parsed = path.parse(basePath);
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
  return path.join(parsed.dir, `${parsed.name}-${stamp}${parsed.ext}`);
}

function writeReports(result, dateStem) {
  const jsonPath = ensureNewPath(path.join(RAW_DIR, `dsc-config-209-245-diff-${dateStem}.json`));
  const mdPath = ensureNewPath(path.join(RAW_DIR, `dsc-config-209-245-diff-${dateStem}.md`));
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  const lines = [
    "# DSC_CONFIG 209/245 Difference Analysis",
    "",
    "Read-only report. No UDP packets were sent, no ACK was generated, no realtime gateway reply logic was changed, and no business tables were written.",
    "",
    `Raw log: ${result.rawLog}`,
    `Generated at: ${result.generatedAt}`,
    "",
    "## Counts",
    "",
    `- 209 count: ${result.counts.DSC_CONFIG_209_TYPE_1100_46FF}`,
    `- 245 count: ${result.counts.DSC_CONFIG_245_TYPE_1100_46FF}`,
    "",
    "## URI Length Delta Check",
    "",
    `- Total URI delta: ${result.uriLengthExplanation.totalDelta}`,
    `- Target frame delta: ${result.uriLengthExplanation.targetDelta}`,
    `- Explains length delta: ${result.uriLengthExplanation.explainsLengthDelta}`,
    `- Conclusion: ${result.uriLengthExplanation.conclusion}`,
    "",
    "## Preliminary Judgement",
    "",
    `- 209 DHCP placeholder config: ${result.preliminaryJudgement.dsc209DhcpPlaceholderConfig}`,
    `- 245 explicit IP config: ${result.preliminaryJudgement.dsc245ExplicitIpConfig}`,
    `- Same register/config retry stage: ${result.preliminaryJudgement.sameRegisterConfigRetryStage}`,
    `- Business data frame: ${result.preliminaryJudgement.businessDataFrame}`,
    "",
  ];
  fs.writeFileSync(mdPath, `${lines.join("\n")}\n`, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const logPath = selectedLog();
  const dateStem = dateFromLog(logPath);
  const packets = readPackets(logPath);
  const byClass = {
    DSC_CONFIG_209_TYPE_1100_46FF: packets.filter((item) => item.parsed.frameClass === "DSC_CONFIG_209_TYPE_1100_46FF"),
    DSC_CONFIG_245_TYPE_1100_46FF: packets.filter((item) => item.parsed.frameClass === "DSC_CONFIG_245_TYPE_1100_46FF"),
  };
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
    filters: {
      protocol: "UDP_DSC",
      remoteAddress: DEVICE_IP,
      frameClasses: [...CONFIG_CLASSES],
    },
    counts: Object.fromEntries(Object.entries(byClass).map(([key, value]) => [key, value.length])),
    samples: Object.fromEntries(Object.entries(byClass).map(([key, value]) => [key, value.slice(-3).map(sampleInfo)])),
    asciiUriIpPort: Object.fromEntries(Object.entries(byClass).map(([key, value]) => [key, asciiSummary(value)])),
    variation: Object.fromEntries(
      Object.entries(byClass).map(([key, value]) => [key, fieldVariation(value, key.includes("209") ? 209 : 245)])
    ),
    uriLengthExplanation: uriLengthExplanation(),
    preliminaryJudgement: {
      dsc209DhcpPlaceholderConfig: byClass.DSC_CONFIG_209_TYPE_1100_46FF.length > 0,
      dsc245ExplicitIpConfig: byClass.DSC_CONFIG_245_TYPE_1100_46FF.length > 0,
      sameRegisterConfigRetryStage: byClass.DSC_CONFIG_209_TYPE_1100_46FF.length > 0 && byClass.DSC_CONFIG_245_TYPE_1100_46FF.length > 0,
      businessDataFrame: false,
      notes: [
        "两类帧同属 UDP_DSC 且 typeA=110046ff。",
        "245-209 的 36 字节差异可由 3 个 udp URI 和 1 个 ftp URI 从 [dhcp] 变为 192.168.100.100 的字符串长度差异解释。",
        "不默认假设 245 多出尾部字段。",
        "当前仍不判定为业务数据帧。",
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
