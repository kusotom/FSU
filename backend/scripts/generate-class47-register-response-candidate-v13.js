#!/usr/bin/env node
"use strict";

/**
 * Generate the offline v1.3 classByte=0x47 register response candidate report.
 *
 * SAFETY:
 * - Report generation only.
 * - Does not open sockets or send UDP.
 * - Does not add ACK or modify gateway runtime logic.
 */

const fs = require("fs");
const path = require("path");
const annotations = require("../app/modules/fsu_gateway/parser/dsc-rds-annotations");

const ROOT = path.resolve(__dirname, "..", "..");
const RAW_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets");
const DEFAULT_DATE = "2026-05-01";

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === "--date") args.date = argv[++i];
  }
  return args;
}

function readJsonIfExists(rel) {
  const full = path.join(ROOT, rel);
  return fs.existsSync(full) ? JSON.parse(fs.readFileSync(full, "utf8")) : null;
}

function write(rel, content) {
  const full = path.join(ROOT, rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, content, "utf8");
  return full;
}

function confidenceFromConclusion(level) {
  if (!level) return "candidate only";
  return level;
}

function main() {
  const args = parseArgs(process.argv);
  const date = args.date || DEFAULT_DATE;
  const headerContext = readJsonIfExists(`backend/logs/fsu_raw_packets/header-context-8-19-analysis-${date}.json`);
  const seq = readJsonIfExists(`backend/logs/fsu_raw_packets/seq-strategy-analysis-${date}.json`);

  const seqLevel = confidenceFromConclusion(seq?.conclusion?.class47ConclusionLevel);
  const contextLevel = confidenceFromConclusion(headerContext?.recommendation?.confidence);
  const class47Model = annotations.ACK_CONSTRUCTION_MODELS.class47RegisterResponse;

  const result = {
    generatedAt: new Date().toISOString(),
    safety: {
      noUdpSent: true,
      noAckAdded: true,
      sendOneShotAckNotRun: true,
      gatewayReplyLogicUnchanged: true,
      servicePyNotIntegrated: true,
      businessTablesUnchanged: true,
      firmwareUnchanged: true,
      liveExperimentNotPerformed: true,
    },
    sourceReports: {
      headerContext: headerContext ? `backend/logs/fsu_raw_packets/header-context-8-19-analysis-${date}.json` : null,
      seqStrategy: seq ? `backend/logs/fsu_raw_packets/seq-strategy-analysis-${date}.json` : null,
      offlineSummary: `backend/logs/fsu_raw_packets/dsc-rds-offline-reverse-summary-v1.3-${date}.json`,
    },
    request0x46: {
      typeBytes: "110046ff",
      typeByte: "0x11",
      flagByte: "0x00",
      classByte: "0x46",
      tailByte: "0xff",
      frameClasses: {
        DSC_CONFIG_209_TYPE_1100_46FF: {
          meaning: "DHCP placeholder URI variant",
          payloadLength: 185,
          totalLength: 209,
        },
        DSC_CONFIG_245_TYPE_1100_46FF: {
          meaning: "resolved explicit IP URI variant",
          payloadLength: 221,
          totalLength: 245,
        },
      },
      payloadEvidence: [
        "contains FSU/device-side udp:// endpoints",
        "contains FSU/device-side ftp:// endpoint",
        "209/245 length delta is explained by URI address string lengths",
      ],
    },
    response0x47Payload: {
      resultCode: "payload[0], 0=Success, 1=Fail, 2=UnRegister",
      serviceCountLE: "payload[1..2]",
      entries: "payload[3..] repeated fieldId:uint8, valueLength:uint8, valueBytes:ASCII",
      serviceChannelTypes: annotations.SERVICE_CHANNEL_TYPE_ANNOTATIONS,
      requiredMask: "0x3f",
      channelType7: annotations.SERVICE_CHANNEL_TYPE_ANNOTATIONS[7],
    },
    bestOfflineFullFrameCandidate: {
      typeBytes: "110047ff",
      typeByte: "0x11",
      flagByte: "0x00",
      classByte: "0x47",
      tailByte: "0xff",
      ackRequiredFlag: false,
      seqStrategy: "mirror 0x46 request seqLE",
      seqEvidenceLevel: seqLevel,
      headerContext8to19Strategy: "copy 0x46 request bytes[8..19]",
      headerContextEvidenceLevel: contextLevel,
      payloadLength: class47Model.payloadLayout.payloadLengthCandidate,
      payloadLengthHexLE: "ab00",
      totalLength: 195,
      checksum: "normal FSU checksum stored little-endian",
      safeToSend: false,
      ackHex: null,
      doNotSend: true,
    },
    ranking: [
      {
        rank: 1,
        typeBytes: "110047ff",
        reason: "matches 110046ff request family, classByte=0x47 response branch, no ackRequiredFlag",
      },
      {
        rank: 2,
        typeBytes: "118047ff",
        reason: "sets ackRequiredFlag; less suitable because it may request another ACK",
      },
      {
        rank: 3,
        typeBytes: "100047ff",
        reason: "lacks direct raw-log evidence in the current FSU capture",
      },
      {
        rank: 4,
        typeBytes: "1f0047ff",
        reason: "ACK-style typeByte; less likely for long-payload register response",
      },
    ],
    caveats: [
      "This is an offline candidate, not an online-verified protocol fact.",
      "Do not send this candidate.",
      "Do not integrate into service.py or fsu-gateway runtime reply logic.",
      "No real 0x47 frame has been captured.",
      "seqLE and bytes[8..19] strategies are candidates based on available evidence.",
    ],
  };

  const jsonPath = `backend/logs/fsu_raw_packets/class47-register-response-candidate-v1.3-${date}.json`;
  const mdPath = `backend/logs/fsu_raw_packets/class47-register-response-candidate-v1.3-${date}.md`;
  write(jsonPath, `${JSON.stringify(result, null, 2)}\n`);

  const md = [
    `# Class47 Register Response Candidate v1.3 ${date}`,
    "",
    "Safety: offline candidate report only; no UDP sent; no ACK added; gateway runtime reply logic unchanged.",
    "",
    "## 0x46 Request",
    "",
    "- typeBytes: `110046ff`",
    "- 209: DHCP placeholder URI variant",
    "- 245: resolved explicit IP URI variant",
    "- payload contains FSU/device-side UDP/FTP address strings",
    "",
    "## 0x47 Payload",
    "",
    "- resultCode: `payload[0]`, `0=Success`, `1=Fail`, `2=UnRegister`",
    "- serviceCountLE: `payload[1..2]`",
    "- entries: `payload[3..]` repeated `fieldId:uint8, valueLength:uint8, valueBytes:ASCII`",
    "- required mask: `0x3f`",
    "- channelType 7: 实时数据通道",
    "",
    "## Best Offline Full-Frame Candidate",
    "",
    "- typeBytes: `110047ff`",
    `- seq: mirror 0x46 request seqLE (${seqLevel})`,
    `- header[8..19]: copy 0x46 request context (${contextLevel})`,
    "- payloadLength: `171 / 0x00ab`",
    "- totalLength: `195`",
    "- checksum: normal FSU checksum LE",
    "- ackRequiredFlag: `false`",
    "- safeToSend: `false`",
    "- ackHex: `null`",
    "",
    "## Candidate Ranking",
    "",
    "| rank | typeBytes | reason |",
    "| ---: | --- | --- |",
    ...result.ranking.map((item) => `| ${item.rank} | ${item.typeBytes} | ${item.reason} |`),
    "",
    "## Caveats",
    "",
    ...result.caveats.map((item) => `- ${item}`),
    "",
  ].join("\n");
  write(mdPath, md);
  console.log(`Wrote ${path.join(ROOT, mdPath)}`);
  console.log(`Wrote ${path.join(ROOT, jsonPath)}`);
}

main();
