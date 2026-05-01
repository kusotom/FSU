#!/usr/bin/env node
"use strict";

/**
 * class47-one-shot-register-response.js
 *
 * Default mode is DRY-RUN ONLY.
 *
 * SAFETY:
 * - Default run never sends UDP.
 * - Does not run send-one-shot-ack.js.
 * - Does not modify fsu-gateway runtime reply logic.
 * - Does not integrate with service.py.
 * - Does not write business tables.
 * - Does not generate full frame hex unless --show-hex is explicitly provided.
 *
 * Execute mode is implemented only for a future separately approved task and
 * requires multiple explicit confirmation flags. Do not run --execute during
 * ordinary analysis.
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const crypto = require("crypto");
const { execFileSync } = require("child_process");
const {
  calcFsuChecksum,
  findHexCandidate,
  parseFsuFrame,
} = require("../app/modules/fsu_gateway/parser/fsu-frame-v03-utils");

const ROOT = path.resolve(__dirname, "..", "..");
const DEFAULT_INPUT = path.join(ROOT, "backend", "logs", "fsu_raw_packets", "2026-05-01.jsonl");
const DEFAULT_OUT_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets", "class47-one-shot");
const DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/health";
const DEVICE_IP = "192.168.100.100";
const REQUIRED_MASK_BY_TYPE = new Map([[0, 1], [5, 2], [6, 4], [7, 8], [8, 16], [9, 32]]);
const CHANNEL_IDS = [0, 5, 6, 7, 8, 9];
const DEFAULT_URIS = {
  0: "udp://192.168.100.123:6000",
  5: "udp://192.168.100.123:6000",
  6: "udp://192.168.100.123:6000",
  7: "udp://192.168.100.123:7000",
  8: "udp://192.168.100.123:6000",
  9: "udp://192.168.100.123:6000",
};

function parseArgs(argv) {
  const args = {
    input: DEFAULT_INPUT,
    preferLength: 245,
    healthUrl: DEFAULT_HEALTH_URL,
    outDir: DEFAULT_OUT_DIR,
    execute: false,
    executeLatest: false,
    showHex: false,
    understoodUdp: false,
    confirmLatest0x46: false,
    confirmSeq: null,
    confirmTypeBytes: null,
    confirmRequiredMask: null,
    maxRequestAgeMs: 5000,
    channelUris: { ...DEFAULT_URIS },
  };
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (key === "--input") args.input = path.resolve(argv[++i]);
    else if (key === "--prefer-length") args.preferLength = Number(argv[++i]);
    else if (key === "--health-url") args.healthUrl = argv[++i];
    else if (key === "--precheck-json") args.precheckJson = path.resolve(argv[++i]);
    else if (key === "--out-dir") args.outDir = path.resolve(argv[++i]);
    else if (key === "--channel0-uri") args.channelUris[0] = argv[++i];
    else if (key === "--channel5-uri") args.channelUris[5] = argv[++i];
    else if (key === "--channel6-uri") args.channelUris[6] = argv[++i];
    else if (key === "--channel7-uri") args.channelUris[7] = argv[++i];
    else if (key === "--channel8-uri") args.channelUris[8] = argv[++i];
    else if (key === "--channel9-uri") args.channelUris[9] = argv[++i];
    else if (key === "--show-hex") args.showHex = true;
    else if (key === "--execute") args.execute = true;
    else if (key === "--execute-latest") args.executeLatest = true;
    else if (key === "--i-understand-this-sends-one-udp-packet") args.understoodUdp = true;
    else if (key === "--confirm-latest-0x46") args.confirmLatest0x46 = true;
    else if (key === "--confirm-seq") args.confirmSeq = Number(argv[++i]);
    else if (key === "--confirm-typeBytes") args.confirmTypeBytes = String(argv[++i] || "").toLowerCase();
    else if (key === "--confirm-requiredMask") args.confirmRequiredMask = String(argv[++i] || "").toLowerCase();
    else if (key === "--max-request-age-ms") args.maxRequestAgeMs = Number(argv[++i]);
  }
  return args;
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function timestampForFileName(date = new Date()) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}-${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`;
}

function sha256Hex(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function readJsonSafe(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return null;
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null;
  }
}

function findLatestPrecheckJson() {
  const dir = path.join(ROOT, "backend", "logs", "fsu_raw_packets");
  if (!fs.existsSync(dir)) return null;
  const files = fs.readdirSync(dir)
    .filter((name) => /^class47-one-shot-precheck-.*\.json$/.test(name))
    .map((name) => path.join(dir, name))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  return files[0] || null;
}

function requestHealth(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 3000 }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, statusCode: res.statusCode, body: body.slice(0, 300), error: null }));
    });
    req.on("timeout", () => req.destroy(new Error("health request timed out")));
    req.on("error", (error) => resolve({ ok: false, statusCode: null, body: "", error: error.message }));
  });
}

function gitClean() {
  try {
    const output = execFileSync("git", ["status", "--short"], { cwd: ROOT, encoding: "utf8" });
    const changed = output.split(/\r?\n/).filter(Boolean);
    return { clean: changed.length === 0, changed };
  } catch (error) {
    return { clean: false, changed: [], error: error.message };
  }
}

function rawLogGrowing(input, waitMs = 3000) {
  if (!fs.existsSync(input)) return { ok: false, size1: null, size2: null, growthBytes: null };
  const size1 = fs.statSync(input).size;
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, waitMs);
  const size2 = fs.statSync(input).size;
  return { ok: size2 > size1, size1, size2, growthBytes: size2 - size1 };
}

function checkUdpListeningReadOnly() {
  try {
    const command = [
      "$ErrorActionPreference='Stop';",
      "Get-NetUDPEndpoint -LocalPort 9000,7000 |",
      "Select-Object LocalAddress,LocalPort,OwningProcess |",
      "ForEach-Object { \"$($_.LocalAddress) $($_.LocalPort) $($_.OwningProcess)\" }",
    ].join(" ");
    const output = execFileSync("powershell.exe", ["-NoProfile", "-Command", command], { encoding: "utf8" });
    const lines = output.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    return {
      method: "Get-NetUDPEndpoint",
      udp9000: lines.some((line) => /\s9000\s/.test(line)),
      udp7000: lines.some((line) => /\s7000\s/.test(line)),
      matchingLines: lines,
    };
  } catch (error) {
    return { method: "Get-NetUDPEndpoint", udp9000: false, udp7000: false, matchingLines: [], error: error.message };
  }
}

function loadFrames(input) {
  const lines = fs.readFileSync(input, "utf8").split(/\r?\n/);
  const frames = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (!lines[i].trim()) continue;
    let entry;
    try { entry = JSON.parse(lines[i]); } catch { continue; }
    if (entry.remoteAddress && entry.remoteAddress !== DEVICE_IP) continue;
    const rawHex = findHexCandidate(entry);
    if (!rawHex) continue;
    const parsed = parseFsuFrame(rawHex);
    if (!parsed.ok) continue;
    frames.push({
      lineNo: i + 1,
      timestamp: entry.receivedAt || entry.createdAt || entry.timestamp || null,
      remoteAddress: entry.remoteAddress,
      remotePort: entry.remotePort,
      localPort: entry.localPort,
      rawHex,
      buffer: Buffer.from(rawHex, "hex"),
      parsed,
    });
  }
  return frames;
}

function selectLatest0x46(frames, preferLength) {
  const priority = preferLength === 209 ? [209, 245] : [245, 209];
  for (const length of priority) {
    for (let i = frames.length - 1; i >= 0; i -= 1) {
      const frame = frames[i];
      if (frame.parsed.totalLength === length && frame.parsed.typeBytesSummary === "110046ff") return frame;
    }
  }
  return null;
}

function buildPayload(channelUris) {
  const parts = [];
  parts.push(Buffer.from([0x00]));
  const count = Buffer.alloc(2);
  count.writeUInt16LE(CHANNEL_IDS.length, 0);
  parts.push(count);
  const entries = [];
  let observedMask = 0;
  for (const channelType of CHANNEL_IDS) {
    const uri = channelUris[channelType];
    const value = Buffer.from(uri, "ascii");
    if (value.length > 255) throw new Error(`URI too long for channel ${channelType}`);
    parts.push(Buffer.from([channelType, value.length]));
    parts.push(value);
    observedMask |= REQUIRED_MASK_BY_TYPE.get(channelType);
    entries.push({ channelType, uri, valueLength: value.length, maskBit: `0x${REQUIRED_MASK_BY_TYPE.get(channelType).toString(16).padStart(2, "0")}` });
  }
  const payload = Buffer.concat(parts);
  return {
    payload,
    summary: {
      resultCode: 0,
      serviceCount: CHANNEL_IDS.length,
      requiredMask: "0x3f",
      observedMask: `0x${observedMask.toString(16).padStart(2, "0")}`,
      entries,
      uriStrategyNote: "URI strategy remains unvalidated online.",
    },
  };
}

function putLe16(buf, off, value) {
  buf[off] = value & 0xff;
  buf[off + 1] = (value >> 8) & 0xff;
}

function buildFrame(selectedRequest, payload) {
  const totalLength = 24 + payload.length;
  const frame = Buffer.alloc(totalLength, 0);
  frame[0] = 0x6d;
  frame[1] = 0x7e;
  frame[2] = selectedRequest.buffer[2];
  frame[3] = selectedRequest.buffer[3];
  frame[4] = 0x11;
  frame[5] = 0x00;
  frame[6] = 0x47;
  frame[7] = 0xff;
  selectedRequest.buffer.subarray(8, 20).copy(frame, 8);
  putLe16(frame, 20, payload.length);
  payload.copy(frame, 24);
  frame[22] = 0x00;
  frame[23] = 0x00;
  putLe16(frame, 22, calcFsuChecksum(frame));
  return frame;
}

function frameSummary(frame, includeHex) {
  const parsed = parseFsuFrame(frame);
  return {
    typeBytes: parsed.typeBytesSummary,
    totalLength: parsed.totalLength,
    payloadLength: parsed.payloadLengthLE,
    payloadLengthHexLE: frame.subarray(20, 22).toString("hex"),
    checksumLE: parsed.checksumStoredLE,
    checksumHex: parsed.checksumStoredHex,
    checksumValid: parsed.checksumValidLE,
    ackRequiredFlag: parsed.ackRequiredFlag,
    frameHexSha256: sha256Hex(frame),
    frameHexPrefix: frame.subarray(0, 32).toString("hex"),
    fullFrameHexIncluded: includeHex,
    ...(includeHex ? { fullFrameHex: frame.toString("hex") } : {}),
  };
}

function selectedRequestSummary(frame) {
  return {
    lineNo: frame.lineNo,
    timestamp: frame.timestamp,
    length: frame.parsed.totalLength,
    seqLE: frame.parsed.seqLE,
    seqBytes: frame.buffer.subarray(2, 4).toString("hex"),
    typeBytes: frame.parsed.typeBytesSummary,
    headerContextHex: frame.buffer.subarray(8, 20).toString("hex"),
    remoteAddress: frame.remoteAddress,
    remotePort: frame.remotePort,
    localPort: frame.localPort,
  };
}

function parseTimestampMs(timestamp) {
  if (!timestamp) return null;
  const ms = Date.parse(timestamp);
  return Number.isFinite(ms) ? ms : null;
}

function selectedRequestFreshness(frame, now = new Date()) {
  const timestampMs = parseTimestampMs(frame.timestamp);
  if (timestampMs === null) {
    return {
      timestampParseOk: false,
      ageMs: null,
      nowIso: now.toISOString(),
    };
  }
  return {
    timestampParseOk: true,
    ageMs: Math.max(0, now.getTime() - timestampMs),
    nowIso: now.toISOString(),
  };
}

function renderMarkdown(report) {
  return [
    "# FSU classByte=0x47 one-shot dry-run report",
    "",
    `Generated at: ${report.generatedAt}`,
    "",
    "## 1. Safety",
    "",
    "- Dry-run by default.",
    "- No UDP sent.",
    "- No ACK added.",
    "- `send-one-shot-ack.js` was not run.",
    "- fsu-gateway runtime reply logic was not modified.",
    "- `service.py` was not integrated.",
    "- Business tables were not written.",
    "- `110047ff` remains unvalidated online.",
    "",
    "## 2. Mode",
    "",
    `- mode: \`${report.mode}\``,
    `- sent: \`${report.sent}\``,
    `- sendCount: \`${report.sendCount}\``,
    "",
    "## 3. Selected 0x46 request",
    "",
    "```json",
    JSON.stringify(report.selectedRequest, null, 2),
    "```",
    "",
    "## 4. Payload summary",
    "",
    "```json",
    JSON.stringify(report.payload, null, 2),
    "```",
    "",
    "## 5. Candidate frame summary",
    "",
    "```json",
    JSON.stringify(report.candidateFrame, null, 2),
    "```",
    "",
    "## 6. Checksum validation",
    "",
    `- checksumValid: \`${report.candidateFrame.checksumValid}\``,
    `- checksumHex: \`${report.candidateFrame.checksumHex}\``,
    "",
    "## 7. Precheck reference",
    "",
    "```json",
    JSON.stringify(report.precheck, null, 2),
    "```",
    "",
    "## 8. URI strategy",
    "",
    "- URI strategy remains unvalidated online.",
    "- Defaults are candidate values only and do not imply protocol confirmation.",
    "",
    "## 9. Warnings",
    "",
    ...report.warnings.map((item) => `- ${item}`),
    "",
    "## 10. Next step",
    "",
    `- ${report.nextStep}`,
    "",
    "## 11. Safety confirmation",
    "",
    `- udpSent: ${report.safety.udpSent}`,
    `- sendOneShotAckRun: ${report.safety.sendOneShotAckRun}`,
    `- servicePyModified: ${report.safety.servicePyModified}`,
    `- businessTableWritten: ${report.safety.businessTableWritten}`,
    `- onlineExperimentExecuted: ${report.safety.onlineExperimentExecuted}`,
    "",
  ].join("\n");
}

function latestPrecheckSummary(filePath) {
  const doc = readJsonSafe(filePath);
  if (!doc) return { path: filePath, readiness: "unknown", safeToExperiment: false, blockers: ["precheck report not found"], warnings: [] };
  return {
    path: filePath,
    readiness: doc.readiness,
    safeToExperiment: doc.safeToExperiment === true,
    blockers: doc.blockers || [],
    warnings: doc.warnings || [],
  };
}

function validateCandidate(payloadSummary, summary) {
  const errors = [];
  if (summary.typeBytes !== "110047ff") errors.push("candidate typeBytes must be 110047ff");
  if (summary.totalLength !== 195) errors.push("candidate totalLength must be 195");
  if (summary.payloadLength !== 171) errors.push("candidate payloadLength must be 171");
  if (payloadSummary.observedMask !== "0x3f") errors.push("required mask must be 0x3f");
  if (summary.checksumValid !== true) errors.push("candidate checksum must validate");
  if (summary.ackRequiredFlag !== false) errors.push("ackRequiredFlag must be false");
  return errors;
}

function assertExecuteAllowed(args, report, selectedRequest, input) {
  const errors = [];
  if (!args.understoodUdp) errors.push("missing --i-understand-this-sends-one-udp-packet");
  if (args.executeLatest) {
    if (!args.confirmLatest0x46) errors.push("missing --confirm-latest-0x46 for --execute-latest");
    if (!Number.isFinite(args.maxRequestAgeMs) || args.maxRequestAgeMs <= 0) errors.push("--max-request-age-ms must be a positive number");
    const freshness = report.selectedRequestFreshness || {};
    if (!freshness.timestampParseOk) errors.push("latest selected 0x46 request timestamp is not parseable");
    if (freshness.ageMs === null || freshness.ageMs > args.maxRequestAgeMs) {
      errors.push(`latest selected 0x46 request is stale: ageMs=${freshness.ageMs}, maxRequestAgeMs=${args.maxRequestAgeMs}`);
    }
  } else if (args.confirmSeq !== selectedRequest.parsed.seqLE) {
    errors.push("--confirm-seq does not match latest selected 0x46 request seqLE");
  }
  if (args.confirmTypeBytes !== "110047ff") errors.push("--confirm-typeBytes must be 110047ff");
  if (args.confirmRequiredMask !== "0x3f") errors.push("--confirm-requiredMask must be 0x3f");
  if (report.precheck.readiness !== "ready") errors.push("latest precheck readiness is not ready");
  const git = gitClean();
  if (!git.clean) errors.push("Git workspace is not clean");
  const growth = rawLogGrowing(input, 3000);
  if (!growth.ok) errors.push("raw log is not growing");
  const udp = checkUdpListeningReadOnly();
  if (!udp.udp9000 || !udp.udp7000) errors.push("UDP 9000/7000 is not listening");
  if (report.validationErrors.length) errors.push(...report.validationErrors);
  return errors;
}

function writeReport(report, outDir, mode) {
  fs.mkdirSync(outDir, { recursive: true });
  const stamp = timestampForFileName(new Date());
  const prefix = mode === "execute" ? "class47-one-shot-execute" : "class47-one-shot-dry-run";
  const jsonPath = path.join(outDir, `${prefix}-${stamp}.json`);
  const mdPath = path.join(outDir, `${prefix}-${stamp}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  fs.writeFileSync(mdPath, renderMarkdown(report), "utf8");
  return { jsonPath, mdPath };
}

async function main() {
  const args = parseArgs(process.argv);
  fs.mkdirSync(args.outDir, { recursive: true });
  if (!fs.existsSync(args.input)) throw new Error(`input raw log not found: ${args.input}`);

  const frames = loadFrames(args.input);
  const selected = selectLatest0x46(frames, args.preferLength);
  if (!selected) throw new Error("No 0x46 209/245 request found in raw log.");

  const { payload, summary: payloadSummary } = buildPayload(args.channelUris);
  const frame = buildFrame(selected, payload);
  const candidate = frameSummary(frame, args.showHex);
  const precheckPath = args.precheckJson || findLatestPrecheckJson();
  const precheck = latestPrecheckSummary(precheckPath);
  const health = await requestHealth(args.healthUrl);
  const validationErrors = validateCandidate(payloadSummary, candidate);
  const mode = args.execute ? "execute" : "dry-run";
  const freshness = selectedRequestFreshness(selected);

  const report = {
    mode,
    sent: false,
    sendCount: 0,
    generatedAt: new Date().toISOString(),
    selectedAtExecuteTime: Boolean(args.execute && args.executeLatest),
    executeLatest: Boolean(args.executeLatest),
    maxRequestAgeMs: args.maxRequestAgeMs,
    selectedRequest: selectedRequestSummary(selected),
    selectedRequestFreshness: freshness,
    payload: payloadSummary,
    candidateFrame: candidate,
    precheck,
    health,
    readinessReference: precheck,
    validationErrors,
    safety: {
      udpSent: false,
      ackAdded: false,
      sendOneShotAckRun: false,
      sendableFrameHexGenerated: args.showHex,
      servicePyModified: false,
      businessTableWritten: false,
      onlineExperimentExecuted: false,
    },
    warnings: [
      "110047ff is not online-validated.",
      args.showHex
        ? "OFFLINE CANDIDATE ONLY. DO NOT SEND WITHOUT --execute AND HUMAN APPROVAL."
        : "Dry-run only. No UDP sent.",
      "URI strategy remains unvalidated online.",
    ],
    nextStep: "requires explicit human approval and --execute; current run does not authorize or perform an experiment",
  };

  if (!args.execute) {
    const paths = writeReport(report, args.outDir, "dry-run");
    console.log(JSON.stringify({
      mode: report.mode,
      sent: report.sent,
      sendCount: report.sendCount,
      selectedRequest: report.selectedRequest,
      candidateFrame: {
        typeBytes: report.candidateFrame.typeBytes,
        totalLength: report.candidateFrame.totalLength,
        payloadLength: report.candidateFrame.payloadLength,
        checksumValid: report.candidateFrame.checksumValid,
        checksumHex: report.candidateFrame.checksumHex,
        frameHexSha256: report.candidateFrame.frameHexSha256,
        frameHexPrefix: report.candidateFrame.frameHexPrefix,
        fullFrameHexIncluded: report.candidateFrame.fullFrameHexIncluded,
      },
      precheck: report.precheck,
      reportMd: paths.mdPath,
      reportJson: paths.jsonPath,
      safety: report.safety,
    }, null, 2));
    return;
  }

  const executeErrors = assertExecuteAllowed(args, report, selected, args.input);
  if (executeErrors.length) {
    report.mode = "execute";
    report.sent = false;
    report.sendCount = 0;
    report.blocked = true;
    report.blockedReasons = executeErrors;
    const paths = writeReport(report, args.outDir, "execute");
    console.error(JSON.stringify({ sent: false, blockedReasons: executeErrors, reportMd: paths.mdPath, reportJson: paths.jsonPath }, null, 2));
    process.exit(3);
  }

  // The send path is intentionally isolated behind all checks above.
  // Do not execute this branch without a separate explicit human-approved task.
  const dgram = require("dgram");
  const client = dgram.createSocket("udp4");
  const pending = { ...report, pendingSendAt: new Date().toISOString(), pending: true };
  writeReport(pending, args.outDir, "execute");
  await new Promise((resolve, reject) => {
    client.send(frame, selected.remotePort, selected.remoteAddress, (error) => {
      client.close();
      if (error) reject(error);
      else resolve();
    });
  });
  report.sent = true;
  report.sendCount = 1;
  report.safety.udpSent = true;
  report.safety.onlineExperimentExecuted = true;
  const paths = writeReport(report, args.outDir, "execute");
  console.log(JSON.stringify({ sent: true, sendCount: 1, reportMd: paths.mdPath, reportJson: paths.jsonPath }, null, 2));
}

main().catch((error) => {
  console.error(JSON.stringify({
    error: error.message,
    safety: {
      udpSent: false,
      ackAdded: false,
      sendOneShotAckRun: false,
      servicePyModified: false,
      businessTableWritten: false,
      onlineExperimentExecuted: false,
    },
  }, null, 2));
  process.exit(1);
});
