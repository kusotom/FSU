#!/usr/bin/env node
"use strict";

/**
 * Read-only postmortem for the first class47 one-shot experiment.
 *
 * SAFETY:
 * - Does not send UDP.
 * - Does not run send-one-shot-ack.js.
 * - Does not modify fsu-gateway runtime reply logic.
 * - Does not write business tables.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const DEFAULT_OUT_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets", "class47-one-shot");
const DEFAULT_EXECUTE_JSON = path.join(DEFAULT_OUT_DIR, "class47-one-shot-execute-2026-05-01-212647.json");
const DEFAULT_RESULT_JSON = path.join(DEFAULT_OUT_DIR, "class47-one-shot-experiment-result-2026-05-01-212647.json");

function pad2(n) {
  return String(n).padStart(2, "0");
}

function stamp(date = new Date()) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}-${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, ""));
}

function parseArgs(argv) {
  const args = {
    executeJson: DEFAULT_EXECUTE_JSON,
    resultJson: DEFAULT_RESULT_JSON,
    outDir: DEFAULT_OUT_DIR,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (key === "--execute-json") args.executeJson = path.resolve(argv[++i]);
    else if (key === "--result-json") args.resultJson = path.resolve(argv[++i]);
    else if (key === "--out-dir") args.outDir = path.resolve(argv[++i]);
  }
  return args;
}

function renderMarkdown(report) {
  return [
    "# FSU classByte=0x47 one-shot postmortem v1",
    "",
    `Generated at: ${report.generatedAt}`,
    "",
    "## Summary",
    "",
    `- Verdict: ${report.verdict}`,
    `- Sent exactly once: ${report.sentExactlyOnce}`,
    `- Target: ${report.target.host}:${report.target.port}`,
    `- Target mode used: ${report.target.mode}`,
    "",
    "## Frame Validation",
    "",
    `- typeBytes: ${report.frame.typeBytes}`,
    `- totalLength: ${report.frame.totalLength}`,
    `- payloadLength: ${report.frame.payloadLength}`,
    `- checksumValid: ${report.frame.checksumValid}`,
    `- ackRequiredFlag: ${report.frame.ackRequiredFlag}`,
    `- requiredMask: ${report.payload.requiredMask}`,
    `- observedMask: ${report.payload.observedMask}`,
    "",
    "## Observation",
    "",
    `- 209/245 continued: ${report.observation.config209245Continued}`,
    `- RDS_REALDATA appeared: ${report.observation.rdsRealdataAppeared}`,
    `- New frameClass: ${report.observation.newFrameClass.join(", ") || "none"}`,
    `- New typeBytes: ${report.observation.newTypeBytes.join(", ") || "none"}`,
    `- New length: ${report.observation.newLength.join(", ") || "none"}`,
    `- UNKNOWN increased: ${report.observation.unknownIncreased}`,
    "",
    "## Interpretation",
    "",
    "- The candidate frame shape passed offline validation and was sent exactly once.",
    "- The target was the latest 0x46 source port, 6005.",
    "- The 120-second observation did not show a transition to RDS_REALDATA or BUSINESS_DATA_ACTIVE.",
    "- The most useful next variable is target port strategy: test the FSU-declared UDP endpoint 192.168.100.100:6002 before changing typeBytes or payload structure.",
    "",
    "## Safety Confirmation",
    "",
    "- UDP sent by this postmortem script: false",
    "- send-one-shot-ack.js run: false",
    "- ACK added: false",
    "- fsu-gateway reply logic modified: false",
    "- service.py integrated: false",
    "- business table written: false",
    "",
  ].join("\n");
}

function main() {
  const args = parseArgs(process.argv);
  const execute = readJson(args.executeJson);
  const result = readJson(args.resultJson);
  const report = {
    generatedAt: new Date().toISOString(),
    inputs: {
      executeJson: args.executeJson,
      resultJson: args.resultJson,
    },
    sentExactlyOnce: execute.sent === true && execute.sendCount === 1,
    verdict: result.preliminaryVerdict || "unknown",
    target: {
      mode: execute.targetStrategy?.targetMode || "source-port",
      host: execute.targetStrategy?.targetHost || execute.selectedRequest?.remoteAddress,
      port: execute.targetStrategy?.targetPort || execute.selectedRequest?.remotePort,
      source: execute.targetStrategy?.targetSource || "latest 0x46 source port",
    },
    selectedRequest: execute.selectedRequest,
    frame: {
      typeBytes: execute.candidateFrame?.typeBytes,
      totalLength: execute.candidateFrame?.totalLength,
      payloadLength: execute.candidateFrame?.payloadLength,
      checksumValid: execute.candidateFrame?.checksumValid,
      checksumHex: execute.candidateFrame?.checksumHex,
      ackRequiredFlag: execute.candidateFrame?.ackRequiredFlag,
      frameHexSha256: execute.candidateFrame?.frameHexSha256,
    },
    payload: {
      resultCode: execute.payload?.resultCode,
      serviceCount: execute.payload?.serviceCount,
      requiredMask: execute.payload?.requiredMask,
      observedMask: execute.payload?.observedMask,
    },
    observation: {
      config209245Continued: result.changes?.config209245Continued === true,
      config209245ReducedOrStopped: result.changes?.config209245ReducedOrStopped === true,
      rdsRealdataAppeared: result.changes?.rdsRealdataCandidate === true,
      newFrameClass: result.changes?.newFrameClass || [],
      newTypeBytes: result.changes?.newTypeBytes || [],
      newLength: result.changes?.newLength || [],
      unknownIncreased: result.changes?.unknownIncreased === true,
      abnormalOffline: result.changes?.abnormalOffline === true,
    },
    nextVariable: {
      targetMode: "declared-6002",
      targetHost: "192.168.100.100",
      targetPort: 6002,
      reason: "The previous source-port target 6005 produced no observable transition; 209/245 payload declares udp://192.168.100.100:6002.",
    },
    safety: {
      udpSentByThisScript: false,
      sendOneShotAckRun: false,
      ackAdded: false,
      gatewayReplyLogicModified: false,
      servicePyIntegrated: false,
      businessTableWritten: false,
    },
  };
  fs.mkdirSync(args.outDir, { recursive: true });
  const base = path.join(args.outDir, `class47-one-shot-postmortem-v1-${stamp()}`);
  fs.writeFileSync(`${base}.json`, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  fs.writeFileSync(`${base}.md`, renderMarkdown(report), "utf8");
  console.log(JSON.stringify({ reportMd: `${base}.md`, reportJson: `${base}.json`, verdict: report.verdict, nextVariable: report.nextVariable }, null, 2));
}

main();
