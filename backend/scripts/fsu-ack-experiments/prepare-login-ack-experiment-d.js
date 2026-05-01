#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const fs = require("fs");
const path = require("path");
const { parseFsuFrame } = require("../../app/modules/fsu_gateway/parser/fsu-frame-parser");
const { buildFrameCandidate } = require("./model-login-ack-frame");
const { simulateLoginAckParse } = require("./simulate-login-ack-parse");
const { selectLatestRawLog } = require("./select-latest-fsu-log");

const DATE_STEM = "2026-04-29";
const OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");
const TARGET_ADDRESS = "192.168.100.100";
const LOCAL_PORT = 9000;
const PLATFORM_HOST = "192.168.100.123";
const LABEL = "EXPERIMENT_D_LOGIN_ACK_CURRENT_DSC_CONFIG_ALL_9000";
const CONFIG_CLASSES = ["DSC_CONFIG_245_TYPE_1100_46FF", "DSC_CONFIG_209_TYPE_1100_46FF"];

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) continue;
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      args[key] = next;
      i += 1;
    } else {
      args[key] = true;
    }
  }
  return args;
}

function readRows(logPath) {
  const rows = [];
  const errors = [];
  fs.readFileSync(logPath, "utf8")
    .split(/\r?\n/)
    .forEach((line, index) => {
      if (!line.trim()) return;
      try {
        rows.push(JSON.parse(line));
      } catch (error) {
        errors.push({ line: index + 1, error: error.message });
      }
    });
  return { rows, errors };
}

function rowBuffer(row) {
  const hex = String(row.rawHex || "").replace(/\s+/g, "").toLowerCase();
  if (!/^[0-9a-f]+$/.test(hex) || hex.length < 48 || hex.length % 2 !== 0) return null;
  return Buffer.from(hex, "hex");
}

function rowTimeMs(row) {
  const ms = Date.parse(row.receivedAt || "");
  return Number.isFinite(ms) ? ms : null;
}

function classify(row, buf) {
  if (row.frameClass) return row.frameClass;
  return parseFsuFrame(buf, { protocol: row.protocol, includeAscii: true }).frameClass;
}

function selectLatestRequest(rows, nowMs, maxAgeSeconds) {
  const candidates = [];
  for (const row of rows) {
    if (row.protocol !== "UDP_DSC" || row.remoteAddress !== TARGET_ADDRESS || Number(row.localPort) !== LOCAL_PORT) {
      continue;
    }
    const buf = rowBuffer(row);
    if (!buf || buf[0] !== 0x6d || buf[1] !== 0x7e) continue;
    const frameClass = classify(row, buf);
    if (!CONFIG_CLASSES.includes(frameClass)) continue;
    const parsed = parseFsuFrame(buf, { protocol: row.protocol, includeAscii: true });
    candidates.push({ row, buf, frameClass, parsed, timeMs: rowTimeMs(row) || 0 });
  }
  const freshCutoff = nowMs - maxAgeSeconds * 1000;
  const freshCandidates = candidates.filter((item) => item.timeMs >= freshCutoff);
  const selectionPool = freshCandidates.length ? freshCandidates : candidates;
  const latest245 = selectionPool
    .filter((item) => item.frameClass === "DSC_CONFIG_245_TYPE_1100_46FF")
    .sort((a, b) => b.timeMs - a.timeMs)[0];
  if (latest245) return latest245;
  const latest209 = selectionPool
    .filter((item) => item.frameClass === "DSC_CONFIG_209_TYPE_1100_46FF")
    .sort((a, b) => b.timeMs - a.timeMs)[0];
  if (latest209) return latest209;
  throw new Error("no fresh DSC_CONFIG_245/209 request candidate found");
}

function inc(map, key) {
  const normalized = key === undefined || key === null || key === "" ? "(empty)" : String(key);
  map[normalized] = (map[normalized] || 0) + 1;
}

function topPort(counts) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1] || Number(a[0]) - Number(b[0]));
  return entries.length ? Number(entries[0][0]) : null;
}

function portDistribution(rows, endMs, seconds = 30) {
  const startMs = endMs - seconds * 1000;
  const result = {
    windowSeconds: seconds,
    start: new Date(startMs).toISOString(),
    end: new Date(endMs).toISOString(),
    udpDscRemotePorts: {},
    udpRdsRemotePorts: {},
    dscConfigRemotePorts: {},
    dscShort24RemotePorts: {},
  };
  for (const row of rows) {
    const ms = rowTimeMs(row);
    if (ms === null || ms < startMs || ms > endMs) continue;
    const buf = rowBuffer(row);
    if (!buf) continue;
    const frameClass = classify(row, buf);
    if (row.protocol === "UDP_DSC") inc(result.udpDscRemotePorts, row.remotePort);
    if (row.protocol === "UDP_RDS") inc(result.udpRdsRemotePorts, row.remotePort);
    if (CONFIG_CLASSES.includes(frameClass)) inc(result.dscConfigRemotePorts, row.remotePort);
    if (frameClass === "DSC_SHORT_24_TYPE_1F00_D2FF") inc(result.dscShort24RemotePorts, row.remotePort);
  }
  result.currentDscConfigRemotePort = topPort(result.dscConfigRemotePorts);
  return result;
}

function uriPorts(parsed) {
  return [...new Set((parsed.dscConfig?.udpUris || []).map((uri) => {
    const match = String(uri).match(/:(\d{1,5})(?:[/?#]|$)/);
    return match ? Number(match[1]) : null;
  }).filter((port) => Number.isInteger(port)))];
}

function commandTemplate(targetHost, targetPort, frameHex) {
  return [
    "node backend\\scripts\\fsu-ack-experiments\\send-one-shot-ack.js",
    `--target-host ${targetHost}`,
    `--target-port ${targetPort}`,
    `--ack-hex ${frameHex}`,
    `--label ${LABEL}`,
    "--yes-i-know-this-is-experimental",
  ].join(" ");
}

function writeReport(result, outDir = OUT_DIR) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `controlled-login-ack-experiment-d-dryrun-${DATE_STEM}.json`);
  const mdPath = path.join(outDir, `controlled-login-ack-experiment-d-dryrun-${DATE_STEM}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  fs.writeFileSync(
    mdPath,
    [
      "# Controlled Login ACK Experiment D Dry Run",
      "",
      "Dry-run only. No ACK was sent and send-one-shot-ack was not run.",
      "",
      "```json",
      JSON.stringify(result, null, 2),
      "```",
      "",
    ].join("\n"),
    "utf8",
  );
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const logSelection = args.log ? { latestRawLog: path.resolve(args.log), reason: "explicit --log" } : selectLatestRawLog();
  const logPath = path.resolve(logSelection.latestRawLog);
  const maxAgeSeconds = Number(args["max-age-seconds"] || 15);
  const { rows, errors } = readRows(logPath);
  const nowMs = Date.now();
  const selected = selectLatestRequest(rows, nowMs, maxAgeSeconds);
  const selectedAtMs = rowTimeMs(selected.row);
  const ageSeconds = selectedAtMs === null ? null : Math.max(0, (nowMs - selectedAtMs) / 1000);
  const freshEnough = ageSeconds !== null && ageSeconds <= maxAgeSeconds;
  const ports = portDistribution(rows, nowMs, 30);
  const portFreshnessOk =
    ports.currentDscConfigRemotePort !== null && Number(ports.currentDscConfigRemotePort) === Number(selected.row.remotePort);

  const frameModel = buildFrameCandidate({
    "request-hex": selected.buf.toString("hex"),
    typea: "110047ff",
    profile: "recommended_all_9000_offline_candidate",
    "seq-strategy": "mirror",
    "unknown8to19-strategy": "mirror",
    "platform-host": args["platform-host"] || PLATFORM_HOST,
    "unsafe-include-incomplete-frame": true,
  });
  const frameHex = frameModel.frame.frameHexCandidateForOfflineSimulationOnly;
  const simulation = frameHex ? simulateLoginAckParse(Buffer.from(frameHex, "hex")) : null;
  const simulationChecksAllTrue = simulation ? Object.values(simulation.checks).every(Boolean) : false;
  const mayPrepareCommand = freshEnough && portFreshnessOk && simulationChecksAllTrue;

  const result = {
    generatedAt: new Date().toISOString(),
    dryRunOnly: true,
    latestRawLog: logPath,
    logSelection,
    jsonParseErrors: errors,
    selectedRequest: {
      receivedAt: selected.row.receivedAt,
      ageSeconds,
      frameClass: selected.frameClass,
      remoteAddress: selected.row.remoteAddress,
      remotePort: selected.row.remotePort,
      localPort: selected.row.localPort,
      seqLE: selected.buf.subarray(2, 4).toString("hex"),
      typeA: selected.buf.subarray(4, 8).toString("hex"),
      offset8to19: selected.buf.subarray(8, 20).toString("hex"),
      rawHex: selected.buf.toString("hex"),
      declaredUriPorts: uriPorts(selected.parsed),
    },
    freshness: {
      maxAgeSeconds,
      freshEnough,
      reason: freshEnough ? "selected DSC_CONFIG is fresh" : "selected DSC_CONFIG is stale",
    },
    currentRemotePortDistribution: ports,
    portFreshness: {
      currentDscConfigRemotePort: ports.currentDscConfigRemotePort,
      selectedRequestRemotePort: selected.row.remotePort,
      portFreshnessOk,
    },
    candidate: {
      typeA: frameModel.frame.typeA,
      seqLE: frameModel.frame.seqLE,
      seqStrategy: "mirror selectedRequest.seqLE",
      offset8to19: frameModel.frame.unknown8to19,
      offset8to19Strategy: "mirror selectedRequest.frame[8..19]",
      bodyProfile: "recommended_profile/all_9000_profile",
      bodyLength: simulation?.parsed?.bodyLength ?? null,
      lengthLE: frameModel.frame.bodyLengthLE,
      checksumLE: frameModel.frame.checksumLE,
      frameHexCandidateForReviewOnly: frameHex,
    },
    simulation,
    targetHost: selected.row.remoteAddress,
    targetPort: selected.row.remotePort,
    manualCommandTemplate: mayPrepareCommand ? commandTemplate(selected.row.remoteAddress, selected.row.remotePort, frameHex) : null,
    commandSuppressedReason: mayPrepareCommand
      ? null
      : "freshness, port freshness, or offline simulation check failed; command template suppressed",
    safeToSend: false,
    doNotSend: true,
    ackHex: null,
    sendOneShotAckRan: false,
    warnings: [
      "dry-run only",
      "do not send",
      "send-one-shot-ack was not run",
      "safeToSend remains false and ackHex remains null",
    ],
  };
  result.reportPaths = writeReport(result, path.resolve(args["out-dir"] || OUT_DIR));
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


