#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const RAW_LOG_RE = /^\d{4}-\d{2}-\d{2}\.jsonl$/;
const KNOWN_LENGTHS = new Set([24, 30, 209, 245]);
const KNOWN_TYPE_A = new Set(["1f00d2ff", "1180d2ff", "110046ff"]);
const KNOWN_CONFIG_CLASSES = new Set(["DSC_CONFIG_209_TYPE_1100_46FF", "DSC_CONFIG_245_TYPE_1100_46FF"]);
const RAW_DIR = path.join(__dirname, "..", "logs", "fsu_raw_packets");

function countInc(map, key) {
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

function sample(packet, parsed, sourceFile, line) {
  return {
    sourceFile,
    line,
    receivedAt: packet.receivedAt,
    protocol: packet.protocol,
    remoteAddress: packet.remoteAddress,
    remotePort: packet.remotePort,
    localPort: packet.localPort,
    frameClass: parsed.frameClass,
    typeA: parsed.typeA,
    length: parsed.totalLength,
    seqLE: parsed.seqLE,
    seqLEHex: Buffer.from(packet.rawHex.slice(4, 8), "hex").toString("hex"),
    payloadLengthCandidate: parsed.payloadLengthCandidate,
    uris: parsed.uris || [],
    asciiSpans: (parsed.asciiSpans || []).slice(0, 5),
    rawHex: packet.rawHex,
  };
}

function scan() {
  const frameClassCounts = new Map();
  const typeACounts = new Map();
  const lengthCounts = new Map();
  const comboCounts = new Map();
  const uriCounts = new Map();
  const unknownSamples = [];
  const nonStandardLengthFrames = [];
  const asciiNewFrames = [];
  const payloadLengthAnomalies = [];
  const businessFrameCandidates = [];
  const parseErrors = [];
  let totalPackets = 0;

  for (const logPath of rawLogs()) {
    const sourceFile = path.basename(logPath);
    const lines = fs.readFileSync(logPath, "utf8").split(/\r?\n/);
    lines.forEach((line, index) => {
      if (!line.trim()) return;
      let packet;
      try {
        packet = JSON.parse(line);
      } catch (error) {
        parseErrors.push({ sourceFile, line: index + 1, error: error.message });
        return;
      }
      if (packet.protocol !== "UDP_DSC" && packet.protocol !== "UDP_RDS") return;
      const parsed = parseFsuFrame(packet.rawHex, {
        protocol: packet.protocol,
        includeAscii: true,
      });
      totalPackets += 1;
      countInc(frameClassCounts, parsed.frameClass);
      countInc(typeACounts, parsed.typeA);
      countInc(lengthCounts, parsed.totalLength);
      countInc(comboCounts, `${packet.protocol}|${parsed.frameClass}|${parsed.typeA}|${parsed.totalLength}`);
      for (const uri of parsed.uris || []) countInc(uriCounts, uri);

      const item = sample(packet, parsed, sourceFile, index + 1);
      const isUnknown = parsed.frameClass === "UNKNOWN";
      const nonStandardLength = !KNOWN_LENGTHS.has(parsed.totalLength);
      const newTypeA = !KNOWN_TYPE_A.has(parsed.typeA);
      const visibleAscii = (parsed.asciiSpans || []).some((span) => /[A-Za-z]{4,}/.test(span.text));
      const payloadLengthAnomaly = parsed.payloadLengthCandidate !== null && parsed.payloadLengthCandidate !== parsed.bodyLength;

      if (isUnknown && unknownSamples.length < 100) unknownSamples.push(item);
      if (nonStandardLength && nonStandardLengthFrames.length < 200) nonStandardLengthFrames.push(item);
      if (visibleAscii && (isUnknown || nonStandardLength || newTypeA) && asciiNewFrames.length < 200) {
        asciiNewFrames.push(item);
      }
      if (payloadLengthAnomaly && payloadLengthAnomalies.length < 200) payloadLengthAnomalies.push(item);
      if (
        (isUnknown || nonStandardLength || newTypeA || (visibleAscii && !KNOWN_CONFIG_CLASSES.has(parsed.frameClass))) &&
        businessFrameCandidates.length < 300
      ) {
        businessFrameCandidates.push({
          ...item,
          candidateReasons: {
            isUnknown,
            nonStandardLength,
            newTypeA,
            visibleAscii,
            payloadLengthAnomaly,
          },
        });
      }
    });
  }

  return {
    generatedAt: new Date().toISOString(),
    safety: {
      readOnly: true,
      udpSendEnabled: false,
      autoAckEnabled: false,
      businessTableWrites: false,
    },
    rawLogDir: RAW_DIR,
    rawLogs: rawLogs(),
    totalPackets,
    parseErrors: parseErrors.slice(0, 100),
    summary: {
      frameClass: top(frameClassCounts),
      typeA: top(typeACounts),
      length: top(lengthCounts),
      frameClassTypeALength: top(comboCounts, 200),
      uri: top(uriCounts, 100),
    },
    unknownSamples,
    nonStandardLengthFrames,
    asciiNewFrames,
    payloadLengthAnomalies,
    businessFrameCandidates,
    interpretation: [
      "This report is offline and read-only.",
      "Candidate business frames are heuristic; protocol semantics are not confirmed.",
      "No ACK or UDP response is generated by this script.",
    ],
  };
}

function writeReport(result) {
  const dateStem = new Date().toISOString().slice(0, 10);
  fs.mkdirSync(RAW_DIR, { recursive: true });
  const jsonPath = path.join(RAW_DIR, `new-frame-types-${dateStem}.json`);
  const mdPath = path.join(RAW_DIR, `new-frame-types-${dateStem}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  const lines = [
    "# FSU New Frame Type Detection",
    "",
    "Read-only offline report. No UDP packets were sent, no ACK was generated, and no business tables were written.",
    "",
    `Generated at: ${result.generatedAt}`,
    `Total packets: ${result.totalPackets}`,
    "",
    "## FrameClass / TypeA / Length combinations",
    "",
    "| Combination | Count |",
    "| --- | --- |",
    ...result.summary.frameClassTypeALength.map((row) => `| ${row.value} | ${row.count} |`),
    "",
    "## Candidate business frames",
    "",
    "| Time | Protocol | Remote | frameClass | typeA | length | Reasons |",
    "| --- | --- | --- | --- | --- | --- | --- |",
    ...result.businessFrameCandidates.slice(0, 100).map((row) => {
      const reasons = Object.entries(row.candidateReasons)
        .filter(([, enabled]) => enabled)
        .map(([key]) => key)
        .join(", ");
      return `| ${row.receivedAt || ""} | ${row.protocol || ""} | ${row.remoteAddress || ""}:${row.remotePort || ""} | ${row.frameClass} | ${row.typeA} | ${row.length} | ${reasons} |`;
    }),
    "",
  ];
  fs.writeFileSync(mdPath, `${lines.join("\n")}\n`, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const result = scan();
  result.reportPaths = writeReport(result);
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
