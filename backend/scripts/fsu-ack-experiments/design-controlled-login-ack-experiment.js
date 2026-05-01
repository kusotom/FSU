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

const DATE_STEM = "2026-04-28";
const DEFAULT_LOG = path.join(process.cwd(), "backend", "logs", "fsu_raw_packets", `${DATE_STEM}.jsonl`);
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");
const DEFAULT_ACK_MODEL = path.join(DEFAULT_OUT_DIR, `ack-structure-model-${DATE_STEM}.json`);
const TARGET_ADDRESS = "192.168.100.100";
const LOCAL_PORT = 9000;
const PLATFORM_HOST = "192.168.100.123";
const LABEL = "EXPERIMENT_C_LOGIN_ACK_RECOMMENDED_ALL_9000";
const CONFIG_CLASSES = [
  "DSC_CONFIG_245_TYPE_1100_46FF",
  "DSC_CONFIG_209_TYPE_1100_46FF",
];

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

function readJsonl(logPath) {
  const rows = [];
  const errors = [];
  const text = fs.readFileSync(logPath, "utf8");
  text.split(/\r?\n/).forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    try {
      rows.push(JSON.parse(trimmed));
    } catch (error) {
      errors.push({ line: index + 1, error: error.message });
    }
  });
  return { rows, errors };
}

function rowTimeMs(row) {
  const ms = Date.parse(row.receivedAt || "");
  return Number.isFinite(ms) ? ms : null;
}

function rowBuffer(row) {
  const rawHex = String(row.rawHex || "").replace(/\s+/g, "").toLowerCase();
  if (!/^[0-9a-f]+$/.test(rawHex) || rawHex.length < 48 || rawHex.length % 2 !== 0) return null;
  return Buffer.from(rawHex, "hex");
}

function normalizedFrameClass(row, buf) {
  if (row.frameClass) return row.frameClass;
  const parsed = parseFsuFrame(buf, { protocol: row.protocol, includeAscii: true });
  return parsed.frameClass;
}

function isRealConfigCandidate(row, frameClass) {
  return (
    row.protocol === "UDP_DSC" &&
    row.remoteAddress === TARGET_ADDRESS &&
    Number(row.localPort) === LOCAL_PORT &&
    CONFIG_CLASSES.includes(frameClass)
  );
}

function selectLatestRequest(rows, nowMs = Date.now(), maxAgeSeconds = 15) {
  const candidates = [];
  for (const row of rows) {
    const buf = rowBuffer(row);
    if (!buf || buf[0] !== 0x6d || buf[1] !== 0x7e) continue;
    const frameClass = normalizedFrameClass(row, buf);
    if (!isRealConfigCandidate(row, frameClass)) continue;
    const parsed = parseFsuFrame(buf, { protocol: row.protocol, includeAscii: true });
    candidates.push({ row, buf, parsed, frameClass, timeMs: Date.parse(row.receivedAt || "") });
  }
  const freshCutoff = nowMs - maxAgeSeconds * 1000;
  const freshCandidates = candidates.filter((item) => item.timeMs >= freshCutoff);
  const selectionPool = freshCandidates.length ? freshCandidates : candidates;
  const latest245 = selectionPool
    .filter((item) => item.frameClass === "DSC_CONFIG_245_TYPE_1100_46FF")
    .sort((a, b) => (b.timeMs || 0) - (a.timeMs || 0))[0];
  if (latest245) return latest245;
  const latest209 = selectionPool
    .filter((item) => item.frameClass === "DSC_CONFIG_209_TYPE_1100_46FF")
    .sort((a, b) => (b.timeMs || 0) - (a.timeMs || 0))[0];
  if (latest209) return latest209;
  throw new Error("no matching DSC_CONFIG_245/209 request found");
}

function countInc(map, key) {
  const normalized = key === undefined || key === null || key === "" ? "(empty)" : String(key);
  map[normalized] = (map[normalized] || 0) + 1;
}

function topPort(counts) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1] || Number(a[0]) - Number(b[0]));
  return entries.length ? Number(entries[0][0]) : null;
}

function recentPortDistribution(rows, selectedAtMs, seconds = 30) {
  const start = selectedAtMs - seconds * 1000;
  const end = selectedAtMs;
  const result = {
    windowSeconds: seconds,
    start: new Date(start).toISOString(),
    end: new Date(end).toISOString(),
    udpDscRemotePorts: {},
    udpRdsRemotePorts: {},
    dscConfigRemotePorts: {},
    dscShort24RemotePorts: {},
  };
  for (const row of rows) {
    const ms = rowTimeMs(row);
    if (ms === null || ms < start || ms > end) continue;
    const buf = rowBuffer(row);
    if (!buf) continue;
    const frameClass = normalizedFrameClass(row, buf);
    if (row.protocol === "UDP_DSC") countInc(result.udpDscRemotePorts, row.remotePort);
    if (row.protocol === "UDP_RDS") countInc(result.udpRdsRemotePorts, row.remotePort);
    if (CONFIG_CLASSES.includes(frameClass)) countInc(result.dscConfigRemotePorts, row.remotePort);
    if (frameClass === "DSC_SHORT_24_TYPE_1F00_D2FF") countInc(result.dscShort24RemotePorts, row.remotePort);
  }
  result.currentDscConfigRemotePort = topPort(result.dscConfigRemotePorts);
  return result;
}

function unique(values) {
  return [...new Set(values.filter((value) => value !== undefined && value !== null))];
}

function declaredUriPorts(parsed) {
  const uris = parsed?.dscConfig?.udpUris || [];
  return unique(
    uris
      .map((uri) => {
        const match = String(uri).match(/:(\d{1,5})(?:[/?#]|$)/);
        return match ? Number(match[1]) : null;
      })
      .filter((port) => Number.isInteger(port)),
  );
}

function buildCandidate(request, platformHost) {
  const frameModel = buildFrameCandidate({
    "request-hex": request.buf.toString("hex"),
    typea: "110047ff",
    profile: "recommended_all_9000_offline_candidate",
    "seq-strategy": "mirror",
    "unknown8to19-strategy": "mirror",
    "platform-host": platformHost,
    "unsafe-include-incomplete-frame": true,
  });
  const frameHex = frameModel.frame.frameHexCandidateForOfflineSimulationOnly;
  if (!frameHex) throw new Error("failed to build offline review candidate frame");
  const simulation = simulateLoginAckParse(Buffer.from(frameHex, "hex"));
  return { frameModel, frameHex, simulation };
}

function observationPlan(logPath) {
  return {
    baseline: {
      minimumSeconds: 60,
      commandTemplate:
        `node backend\\scripts\\fsu-ack-experiments\\watch-after-ack.js --log ${logPath} --since "<plannedSentAt>" --seconds 60`,
      note: "Before sending, choose a planned sentAt/marker time and inspect the preceding 60 seconds as baseline; do not send during this stage.",
      metrics: [
        "DSC_CONFIG_209 count",
        "DSC_CONFIG_245 count",
        "DSC_SHORT_24 count",
        "RDS_SHORT_30 count",
        "UNKNOWN count",
        "frameClass distribution",
        "length distribution",
        "typeA distribution",
        "payloadLengthCandidate distribution",
        "remotePort distribution",
        "whether any new frameClass is already present",
      ],
    },
    after: {
      minimumSeconds: 120,
      commandTemplate:
        `node backend\\scripts\\fsu-ack-experiments\\watch-after-ack.js --log ${logPath} --since "<actualSentAt>" --seconds 120`,
      metrics: [
        "whether DSC_CONFIG_209 decreases",
        "whether DSC_CONFIG_245 decreases",
        "after-only frameClass",
        "after-only length",
        "after-only typeA",
        "after-only payloadLengthCandidate",
        "new longer binary frames",
        "new visible ASCII payload",
        "real data / event / alarm-like frames",
        "whether device stops reporting",
        "whether device reboots",
        "whether source port changes",
        "whether RDS behavior changes",
      ],
    },
  };
}

function judgementRules() {
  return {
    successSignals: [
      "DSC_CONFIG_209 / DSC_CONFIG_245 repetition frequency clearly drops or stops",
      "new frameClass / typeA / length appears after the one-shot candidate",
      "real-time data or event-like frames appear",
      "RDS moves from fixed short frames into new data frames",
      "SiteUnit no longer repeats LoginToDSC timeout, if device logs are available",
    ],
    ineffectiveSignals: [
      "120-second before/after statistics remain effectively identical",
      "long config frames continue on the same roughly 6-second cadence",
      "no after-only frameClass / length / typeA appears",
    ],
    abnormalSignals: [
      "device stops reporting",
      "device reboots",
      "source port changes frequently",
      "UNKNOWN frames increase sharply",
      "device enters high-frequency abnormal retransmission",
    ],
    stopConditions: [
      "If any abnormal signal appears, stop immediately and do not send a second candidate.",
      "If the first candidate is ineffective, do not loop or retry automatically.",
      "Any second candidate requires a separate manual review.",
    ],
  };
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

function writeReports(outDir, result) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `controlled-login-ack-experiment-design-${DATE_STEM}.json`);
  const mdPath = path.join(outDir, `controlled-login-ack-experiment-design-${DATE_STEM}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  const md = [
    "# Controlled Login ACK Experiment Design",
    "",
    "This report is design-only. It does not send UDP, does not enable auto ACK, and does not mark the candidate safe to send.",
    "",
    "## Selected Request",
    "",
    "```json",
    JSON.stringify(result.selectedRequest, null, 2),
    "```",
    "",
    "## Candidate ACK Summary",
    "",
    "```json",
    JSON.stringify(result.candidateSummary, null, 2),
    "```",
    "",
    "## frameHexCandidateForReviewOnly",
    "",
    "```text",
    result.frameHexCandidateForReviewOnly,
    "```",
    "",
    "## Offline Simulation",
    "",
    "```json",
    JSON.stringify(result.offlineSimulation, null, 2),
    "```",
    "",
    "## Target Recommendation",
    "",
    "```json",
    JSON.stringify(result.targetRecommendation, null, 2),
    "```",
    "",
    "## Observation Plan",
    "",
    "```json",
    JSON.stringify(result.observationPlan, null, 2),
    "```",
    "",
    "## Judgement And Stop Rules",
    "",
    "```json",
    JSON.stringify(result.judgement, null, 2),
    "```",
    "",
    "## Manual Command Template",
    "",
    "Do not execute this in stage 14 design. It is included only for later human review.",
    "",
    "```powershell",
    result.manualCommandTemplate,
    "```",
    "",
  ].join("\n");
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function updateAckModel(modelPath, designSummary) {
  if (!fs.existsSync(modelPath)) return null;
  const model = JSON.parse(fs.readFileSync(modelPath, "utf8"));
  model.controlledExperimentDesignReady = true;
  model.candidateLabel = LABEL;
  model.candidateStillRequiresHumanApproval = true;
  model.safeToSend = false;
  model.doNotSend = true;
  model.doNotAutoSend = true;
  model.ackHex = null;
  model.controlledExperimentDesign = designSummary;
  fs.writeFileSync(modelPath, `${JSON.stringify(model, null, 2)}\n`, "utf8");
  const mdPath = modelPath.replace(/\.json$/i, ".md");
  if (fs.existsSync(mdPath)) {
    const md = [
      "# ACK Structure Model",
      "",
      "Updated with controlled experiment design readiness. This model remains candidate-only.",
      "",
      "```json",
      JSON.stringify(model, null, 2),
      "```",
      "",
    ].join("\n");
    fs.writeFileSync(mdPath, md, "utf8");
  }
  return modelPath;
}

function main() {
  const args = parseArgs(process.argv);
  const selectedLog = args.log ? { latestRawLog: path.resolve(args.log), reason: "explicit --log" } : selectLatestRawLog();
  const logPath = path.resolve(selectedLog.latestRawLog || DEFAULT_LOG);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const platformHost = args["platform-host"] || PLATFORM_HOST;
  const maxAgeSeconds = Number(args["max-age-seconds"] || 15);
  const { rows, errors } = readJsonl(logPath);
  const selected = selectLatestRequest(rows, Date.now(), maxAgeSeconds);
  const selectedAtMs = rowTimeMs(selected.row);
  const ageSeconds = selectedAtMs === null ? null : Math.max(0, (Date.now() - selectedAtMs) / 1000);
  const freshEnough = ageSeconds !== null && ageSeconds <= maxAgeSeconds;
  const portDistribution = recentPortDistribution(rows, selectedAtMs || Date.now(), 30);
  const portFreshnessOk =
    portDistribution.currentDscConfigRemotePort !== null &&
    Number(selected.row.remotePort) === Number(portDistribution.currentDscConfigRemotePort);
  const candidate = buildCandidate(selected, platformHost);
  const ports = declaredUriPorts(selected.parsed);
  const targetHost = selected.row.remoteAddress;
  const targetPort = selected.row.remotePort;
  const allowCommandTemplate = freshEnough && portFreshnessOk && candidate.simulation.ok;
  const manualCommand = allowCommandTemplate ? commandTemplate(targetHost, targetPort, candidate.frameHex) : null;

  const result = {
    generatedAt: new Date().toISOString(),
    stage: "14-controlled-ack-experiment-design",
    designOnly: true,
    doNotSend: true,
    safeToSend: false,
    ackHex: null,
    label: LABEL,
    sourceLog: logPath,
    logSelection: selectedLog,
    jsonParseErrors: errors,
    selectedRequest: {
      receivedAt: selected.row.receivedAt,
      protocol: selected.row.protocol,
      remoteAddress: selected.row.remoteAddress,
      remotePort: selected.row.remotePort,
      localPort: selected.row.localPort,
      frameClass: selected.frameClass,
      length: selected.row.length || selected.buf.length,
      rawHex: selected.buf.toString("hex"),
      seqLE: selected.buf.subarray(2, 4).toString("hex"),
      typeA: selected.buf.subarray(4, 8).toString("hex"),
      offset8to19: selected.buf.subarray(8, 20).toString("hex"),
      dscConfigUdpUris: selected.parsed?.dscConfig?.udpUris || [],
      declaredUriPorts: ports,
    },
    freshness: {
      maxAgeSeconds,
      ageSeconds,
      freshEnough,
      reason: freshEnough ? "selected DSC_CONFIG is fresh enough" : "selected DSC_CONFIG is stale",
    },
    currentRemotePortDistribution: portDistribution,
    portFreshness: {
      currentDscConfigRemotePort: portDistribution.currentDscConfigRemotePort,
      selectedRequestRemotePort: selected.row.remotePort,
      portFreshnessOk,
    },
    candidateSummary: {
      soi: "6d7e",
      typeA: candidate.frameModel.frame.typeA,
      seqStrategy: "mirror request seqLE",
      seqLE: candidate.frameModel.frame.seqLE,
      offset8to19Strategy: "mirror request frame[8..19]",
      offset8to19: candidate.frameModel.frame.unknown8to19,
      bodyProfile: "recommended_profile/all_9000_profile",
      endpointValues: {
        0: `udp://${platformHost}:9000`,
        5: `udp://${platformHost}:9000`,
        6: `udp://${platformHost}:9000`,
        7: `udp://${platformHost}:9000`,
        8: `udp://${platformHost}:9000`,
        9: `udp://${platformHost}:9000`,
      },
      bodyLengthLE: candidate.frameModel.frame.bodyLengthLE,
      checksumLE: candidate.frameModel.frame.checksumLE,
      frameHexCandidateForReviewOnly: candidate.frameHex,
      ackHex: null,
      safeToSend: false,
      doNotSend: true,
    },
    frameHexCandidateForReviewOnly: candidate.frameHex,
    offlineSimulation: candidate.simulation,
    targetRecommendation: {
      targetHost,
      targetPort,
      recommended: true,
      reason: [
        "UDP request/response should first target the current source address and source port.",
        "The DSC source port has changed across observations, so the design must not hard-code 6002.",
        "This design uses the selected latest DSC_CONFIG request remotePort.",
      ],
      alternatives: {
        declaredUriPorts: ports,
        note: "Declared URI ports are kept for review only; recommended targetPort remains the latest request source remotePort.",
      },
    },
    observationPlan: observationPlan(logPath),
    judgement: judgementRules(),
    manualCommandTemplate: manualCommand,
    warnings: [
      "Do not execute the manual command in this stage.",
      "Do not run send-one-shot-ack in this stage.",
      "This report is not live acceptance proof.",
      "safeToSend remains false and ackHex remains null.",
    ],
  };
  result.reportPaths = writeReports(outDir, result);
  result.ackModelUpdated = updateAckModel(
    path.resolve(args["ack-model"] || DEFAULT_ACK_MODEL),
    {
      reportJson: result.reportPaths.jsonPath,
      reportMd: result.reportPaths.mdPath,
      label: LABEL,
      targetHost,
      targetPort,
      candidateTypeA: result.candidateSummary.typeA,
      candidateSeqStrategy: result.candidateSummary.seqStrategy,
      candidateOffset8to19Strategy: result.candidateSummary.offset8to19Strategy,
      bodyProfile: result.candidateSummary.bodyProfile,
      offlineSimulationOk: result.offlineSimulation.ok,
      candidateStillRequiresHumanApproval: true,
      safeToSend: false,
      doNotAutoSend: true,
      ackHex: null,
    },
  );
  fs.writeFileSync(result.reportPaths.jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
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


