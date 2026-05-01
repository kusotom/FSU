#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const fs = require("fs");
const path = require("path");
const { buildFrameCandidate } = require("./model-login-ack-frame");
const { simulateLoginAckParse } = require("./simulate-login-ack-parse");

const DATE_STEM = "2026-04-28";
const DEFAULT_LOG = path.join(process.cwd(), "backend", "logs", "fsu_raw_packets", `${DATE_STEM}.jsonl`);
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

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

function classify(buf, row) {
  const typeA = buf.subarray(4, 8).toString("hex");
  if (row.protocol === "UDP_DSC" && (row.length || buf.length) === 245 && typeA === "110046ff") return "DSC_CONFIG_245_TYPE_1100_46FF";
  if (row.protocol === "UDP_DSC" && (row.length || buf.length) === 209 && typeA === "110046ff") return "DSC_CONFIG_209_TYPE_1100_46FF";
  return null;
}

function latestDscConfig(logPath) {
  let latest = null;
  for (const line of fs.readFileSync(logPath, "utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      continue;
    }
    if (row.protocol !== "UDP_DSC" || row.remoteAddress !== "192.168.100.100") continue;
    const rawHex = String(row.rawHex || "").toLowerCase();
    if (!/^[0-9a-f]+$/.test(rawHex) || rawHex.length < 48) continue;
    const buf = Buffer.from(rawHex, "hex");
    if (buf[0] !== 0x6d || buf[1] !== 0x7e) continue;
    const frameClass = row.frameClass || classify(buf, row);
    if (!frameClass || !/^DSC_CONFIG_(245|209).*1100_46FF$/.test(frameClass)) continue;
    latest = { row, buf, frameClass };
  }
  if (!latest) throw new Error(`no DSC_CONFIG_245/209 request found in ${logPath}`);
  return latest;
}

function writeReport(outDir, result) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `login-ack-offline-candidate-simulation-${DATE_STEM}.json`);
  const mdPath = path.join(outDir, `login-ack-offline-candidate-simulation-${DATE_STEM}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  fs.writeFileSync(
    mdPath,
    [
      "# Login ACK Offline Candidate Simulation",
      "",
      `Simulation OK: ${result.simulation.ok}`,
      `Safe to send: ${result.safeToSend}`,
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
  const logPath = path.resolve(args.log || DEFAULT_LOG);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const latest = latestDscConfig(logPath);
  const frameModel = buildFrameCandidate({
    "request-hex": latest.buf.toString("hex"),
    typea: "110047ff",
    profile: "recommended_all_9000_offline_candidate",
    "seq-strategy": "mirror",
    "unknown8to19-strategy": "mirror",
    "platform-host": args["platform-host"] || "192.168.100.123",
    "unsafe-include-incomplete-frame": true,
  });
  const frameHex = frameModel.frame.frameHexCandidateForOfflineSimulationOnly;
  const simulation = simulateLoginAckParse(Buffer.from(frameHex, "hex"));
  const result = {
    generatedAt: new Date().toISOString(),
    profile: args.profile || "recommended_all_9000",
    requestSummary: {
      receivedAt: latest.row.receivedAt,
      protocol: latest.row.protocol,
      remoteAddress: latest.row.remoteAddress,
      remotePort: latest.row.remotePort,
      localPort: latest.row.localPort,
      frameClass: latest.frameClass,
      length: latest.row.length || latest.buf.length,
      seqLE: latest.buf.subarray(2, 4).toString("hex"),
      typeA: latest.buf.subarray(4, 8).toString("hex"),
      offset8to19: latest.buf.subarray(8, 20).toString("hex"),
    },
    candidateSummary: {
      typeA: frameModel.frame.typeA,
      seqStrategy: "mirror request seqLE",
      seqLE: frameModel.frame.seqLE,
      offset8to19Strategy: "mirror request frame[8..19]",
      offset8to19: frameModel.frame.unknown8to19,
      endpointProfile: "recommended_profile/all_9000_profile",
      bodyLengthLE: frameModel.frame.bodyLengthLE,
      checksumLE: frameModel.frame.checksumLE,
    },
    frameHexCandidateForOfflineSimulationOnly: frameHex,
    simulation,
    doNotSend: true,
    safeToSend: false,
    ackHex: null,
    warnings: [
      "offline candidate only",
      "does not prove device will accept frame",
      "do not send",
    ],
  };
  result.reportPaths = writeReport(outDir, result);
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


