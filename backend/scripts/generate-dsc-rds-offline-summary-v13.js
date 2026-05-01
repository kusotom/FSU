#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const RAW_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets");
const OUT_DATE = "2026-05-01";

function readJson(relativePath) {
  const fullPath = path.join(ROOT, relativePath);
  return JSON.parse(fs.readFileSync(fullPath, "utf8"));
}

function writeFile(relativePath, content) {
  const fullPath = path.join(ROOT, relativePath);
  fs.mkdirSync(path.dirname(fullPath), { recursive: true });
  fs.writeFileSync(fullPath, content, "utf8");
  return fullPath;
}

function statByType(stats, typeBytesSummary) {
  return (stats || []).find((item) => item.typeBytesSummary === typeBytesSummary) || null;
}

function fmtBool(value) {
  return value ? "true" : "false";
}

function main() {
  const checksum = readJson(`backend/logs/fsu_raw_packets/checksum-verification-${OUT_DATE}.json`);
  const d2ff = readJson("backend/logs/fsu_raw_packets/d2ff-ack-exact-reproduction-v12.json");
  const diff = readJson(`backend/logs/fsu_raw_packets/dsc-config-209-245-diff-${OUT_DATE}.json`);
  const annotations = require(path.join(ROOT, "backend", "app", "modules", "fsu_gateway", "parser", "dsc-rds-annotations.js"));

  const checksumStats = {
    rds30: statByType(checksum.stats, "1180d2ff"),
    dsc24: statByType(checksum.stats, "1f00d2ff"),
    dsc209: statByType(checksum.stats, "110046ff") && checksum.stats.filter((item) => item.typeBytesSummary === "110046ff")[0],
    dsc245: checksum.stats.filter((item) => item.typeBytesSummary === "110046ff")[1] || null,
  };

  const uriDelta = {
    udpDhcp: "udp://[dhcp]:6002",
    udpExplicit: "udp://192.168.100.100:6002",
    ftpDhcp: "ftp://root:hello@[dhcp]",
    ftpExplicit: "ftp://root:hello@192.168.100.100",
  };
  uriDelta.udpDelta = uriDelta.udpExplicit.length - uriDelta.udpDhcp.length;
  uriDelta.ftpDelta = uriDelta.ftpExplicit.length - uriDelta.ftpDhcp.length;
  uriDelta.totalExplainedDelta = uriDelta.udpDelta * 3 + uriDelta.ftpDelta;

  const summary = {
    generatedAt: new Date().toISOString(),
    source: {
      userProvidedSummary: "C:\\Users\\测试\\Desktop\\codex_fsu_dsc_rds_offline_summary_v13.md",
      rawLog: diff.input,
      checksumReport: `backend/logs/fsu_raw_packets/checksum-verification-${OUT_DATE}.json`,
      d2ffReport: "backend/logs/fsu_raw_packets/d2ff-ack-exact-reproduction-v12.json",
      dscConfigDiffReport: `backend/logs/fsu_raw_packets/dsc-config-209-245-diff-${OUT_DATE}.json`,
    },
    safety: {
      noUdpSent: true,
      sendOneShotAckNotRun: true,
      noAckAdded: true,
      gatewayReplyLogicUnchanged: true,
      businessTablesUnchanged: true,
      onlineAckStillDisabled: true,
    },
    headerModel: {
      magic: "6d7e",
      seqLE: "offset 2..3",
      typeBytes: {
        typeByte: "offset 4",
        flagByte: "offset 5",
        classByte: "offset 6",
        tailByte: "offset 7",
      },
      ackRequiredFlagCandidate: "flagByte bit7",
      header8to19: "context/session fields, not fully confirmed",
      payloadLengthLE: "offset 20..21 = totalLength - 24",
      checksumLE: "offset 22..23",
      bodyOffset: 24,
      checksumFormula: "uint16 sum(bytes[2..end]) with checksum bytes 22..23 zeroed before calculation",
    },
    checksumStats,
    d2ffExactReproduction: {
      model: d2ff.model,
      counts: d2ff.counts,
      success: d2ff.success,
      diffHistogram: d2ff.diffHistogram,
    },
    dscConfigDiff: {
      counts: diff.counts,
      body209Length: diff.bodyComparison.body209Length,
      body245Length: diff.bodyComparison.body245Length,
      targetDelta: diff.bodyComparison.body245Length - diff.bodyComparison.body209Length,
      uriDelta,
      explainedByUriStringLength: uriDelta.totalExplainedDelta === diff.bodyComparison.body245Length - diff.bodyComparison.body209Length,
      conclusion: "209/245 更像同结构不同 URI 表示形式：209 使用 [dhcp] 占位，245 使用显式 IP。",
    },
    annotations: {
      frameClasses: annotations.FRAME_CLASS_ANNOTATIONS,
      typeA: annotations.TYPE_A_ANNOTATIONS,
      classBytes: annotations.CLASS_BYTE_ANNOTATIONS,
      registerResultCodes: annotations.REGISTER_RESULT_CODE_ANNOTATIONS,
      serviceChannels: annotations.SERVICE_CHANNEL_TYPE_ANNOTATIONS,
      ackConstructionModels: annotations.ACK_CONSTRUCTION_MODELS,
    },
    remainingUnknowns: [
      "0x47 / 110047ff 注册响应候选帧的线上接受行为未确认。",
      "seqLE 是否必须 mirror request 未被固件验收路径强确认。",
      "offset 8..19 的官方字段语义未确认。",
      "RDS 实时业务 payload 当前未出现。",
      "typeA/opcode 完整枚举未确认。",
      "DSC_CONFIG_209/245 payload 每个 offset 的官方字段语义未完全确认。",
    ],
  };

  const md = [
    "# FSU DSC/RDS Offline Reverse Summary v1.3",
    "",
    `Generated at: ${summary.generatedAt}`,
    "",
    "## Safety",
    "",
    "- No UDP sent.",
    "- `send-one-shot-ack.js` was not run.",
    "- No ACK was added.",
    "- fsu-gateway realtime reply logic was not modified.",
    "- Business main tables were not written.",
    "- Online ACK remains disabled.",
    "",
    "## Header Model",
    "",
    "- magic: `6d7e`",
    "- seqLE: offset `2..3`",
    "- type bytes: offsets `4..7` = typeByte / flagByte / classByte / tailByte",
    "- ackRequiredFlag candidate: `flagByte & 0x80`",
    "- offset `8..19`: context/session fields, still unknown",
    "- payloadLengthLE: offset `20..21`, `totalLength - 24`",
    "- checksumLE: offset `22..23`",
    "- bodyOffset: `24`",
    "- checksum formula: uint16 sum of bytes `2..end`, with checksum bytes zeroed before calculation",
    "",
    "## Checksum Verification",
    "",
    `- Parsed packets: ${checksum.parsedLines} / ${checksum.totalLines}`,
    `- RDS 30 \`1180d2ff\`: count ${checksumStats.rds30?.count ?? 0}, validLE ${checksumStats.rds30?.validLE ?? 0}`,
    `- DSC 209 \`110046ff\`: count ${checksumStats.dsc209?.count ?? 0}, validLE ${checksumStats.dsc209?.validLE ?? 0}`,
    `- DSC 245 \`110046ff\`: count ${checksumStats.dsc245?.count ?? 0}, validLE ${checksumStats.dsc245?.validLE ?? 0}`,
    `- DSC 24 \`1f00d2ff\`: general checksum validLE ${checksumStats.dsc24?.validLE ?? 0}; explained by special D2FF reproduction model, not by the general formula directly.`,
    "",
    "## D2FF ACK/Confirm Short Frame Reproduction",
    "",
    `- success: ${fmtBool(d2ff.success)}`,
    `- RDS30 count: ${d2ff.counts.rds30_1180d2ff}`,
    `- DSC24 count: ${d2ff.counts.ack24_1f00d2ff}`,
    `- pairedBySeq: ${d2ff.counts.pairedBySeq}`,
    `- exactMatches: ${d2ff.counts.exactMatches}`,
    `- checksumMatches: ${d2ff.counts.checksumMatches}`,
    `- diffHistogram: \`${JSON.stringify(d2ff.diffHistogram)}\``,
    "",
    "## DSC_CONFIG_209 / DSC_CONFIG_245 Diff",
    "",
    `- 209 count: ${diff.counts.dscConfig209}`,
    `- 245 count: ${diff.counts.dscConfig245}`,
    `- body length delta: ${summary.dscConfigDiff.targetDelta}`,
    `- UDP URI delta: ${uriDelta.udpDelta} bytes × 3`,
    `- FTP URI delta: ${uriDelta.ftpDelta} bytes × 1`,
    `- total explained delta: ${uriDelta.totalExplainedDelta}`,
    `- explained by URI string length: ${fmtBool(summary.dscConfigDiff.explainedByUriStringLength)}`,
    "",
    "Conclusion: 209/245 更像同结构不同 URI 表示形式：209 使用 `[dhcp]` 占位，245 使用显式 IP；不应默认解释为 245 额外尾部字段。",
    "",
    "## v1.3 FrameClass Annotations",
    "",
    "| frameClass | semanticClass | confidence | businessDataConfirmed |",
    "| --- | --- | ---: | --- |",
    ...Object.values(annotations.FRAME_CLASS_ANNOTATIONS).map(
      (item) => `| ${item.frameClass} | ${item.semanticClass} | ${item.confidence} | ${fmtBool(item.businessDataConfirmed)} |`,
    ),
    "",
    "## Class / Register / Service TLV Notes",
    "",
    "- `0x46`: DSC register/config request candidate.",
    "- `0x47`: DSC register/config response candidate; SiteUnit ParseData branches to login status handler.",
    "- `0xd2`: heartbeat/keepalive/ack class candidate.",
    "- register result code: `0=Success`, `1=Fail`, `2=UnRegister`.",
    "- required service fieldIds: `0,5,6,7,8,9`; required mask `0x3f`; values are `udp://host:port` candidates.",
    "",
    "## Offline Class47 Candidate",
    "",
    "- typeA candidate: `110047ff`",
    "- payload layout candidate: resultCode + serviceCount + TLV entries",
    "- status: offline candidate only",
    "- safeToSend: false",
    "- ackHex: null",
    "",
    "## Remaining Unknowns",
    "",
    ...summary.remainingUnknowns.map((item) => `- ${item}`),
    "",
  ].join("\n");

  const jsonPath = `backend/logs/fsu_raw_packets/dsc-rds-offline-reverse-summary-v1.3-${OUT_DATE}.json`;
  const mdPath = `backend/logs/fsu_raw_packets/dsc-rds-offline-reverse-summary-v1.3-${OUT_DATE}.md`;
  writeFile(jsonPath, `${JSON.stringify(summary, null, 2)}\n`);
  writeFile(mdPath, md);
  console.log(`Wrote ${path.join(ROOT, mdPath)}`);
  console.log(`Wrote ${path.join(ROOT, jsonPath)}`);
}

main();
