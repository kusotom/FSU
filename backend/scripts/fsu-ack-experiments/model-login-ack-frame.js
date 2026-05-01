#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const { buildBody, buildCandidateProfiles, parseEntry, parseIntStrict } = require("./model-login-ack-body");
const { writeChecksumLE } = require("./fsu-checksum");

function parseArgs(argv) {
  const args = { endpoints: [] };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--endpoint") {
      args.endpoints.push(argv[i + 1]);
      i += 1;
      continue;
    }
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

function cleanHex(hex) {
  return String(hex || "").replace(/\s+/g, "").toLowerCase();
}

function parseHexBuffer(hex, name) {
  const normalized = cleanHex(hex);
  if (!normalized || normalized.length % 2 !== 0 || /[^0-9a-f]/.test(normalized)) {
    throw new Error(`invalid ${name} hex`);
  }
  return Buffer.from(normalized, "hex");
}

function deriveSeq(request, strategy, fixedValue) {
  if (!request || request.length < 4) return { value: null, hexLE: null, confidence: "none" };
  const requestSeq = request.readUInt16LE(2);
  if (strategy === "mirror") return { value: requestSeq, hexLE: request.subarray(2, 4).toString("hex"), confidence: "candidate" };
  if (strategy === "plus1") {
    const value = (requestSeq + 1) & 0xffff;
    const out = Buffer.alloc(2);
    out.writeUInt16LE(value, 0);
    return { value, hexLE: out.toString("hex"), confidence: "candidate" };
  }
  if (strategy === "fixed") {
    const value = parseIntStrict(fixedValue ?? "0", "fixed-seq") & 0xffff;
    const out = Buffer.alloc(2);
    out.writeUInt16LE(value, 0);
    return { value, hexLE: out.toString("hex"), confidence: "manual candidate" };
  }
  return { value: null, hexLE: null, confidence: "unknown" };
}

function buildFrameCandidate(args) {
  const warnings = [
    "offline model only",
    "do not send",
    "does not call network or send-one-shot-ack",
  ];
  const request = args["request-hex"] ? parseHexBuffer(args["request-hex"], "request-hex") : null;
  const typeAArg = String(args.typea || "unknown").toLowerCase();
  const typeAConfirmed = /^[0-9a-f]{8}$/.test(typeAArg);
  const typeA = typeAConfirmed ? Buffer.from(typeAArg, "hex") : null;
  if (!typeAConfirmed) warnings.push("full typeA is not confirmed; frameHexCandidate remains null");

  let endpointArgs = args.endpoints || [];
  if (args.profile === "recommended_all_9000_offline_candidate" || args.profile === "recommended_all_9000") {
    const profile = buildCandidateProfiles(args["platform-host"] || "192.168.100.123").find((item) => item.name === "recommended_profile");
    endpointArgs = profile.entries.map((entry) => `${entry.fieldId}=${entry.valueText}`);
  }
  const endpoints = endpointArgs.map((text) => parseEntry(text));
  const body = buildBody(0, endpoints);
  const seq = deriveSeq(request, args["seq-strategy"] || "mirror", args["fixed-seq"]);
  const unknown8to19Strategy = args["unknown8to19-strategy"] || "mirror";
  let unknown8to19 = null;
  if (request && request.length >= 20 && unknown8to19Strategy === "mirror") {
    unknown8to19 = request.subarray(8, 20);
  } else if (args["unknown8to19-hex"]) {
    unknown8to19 = parseHexBuffer(args["unknown8to19-hex"], "unknown8to19-hex");
    if (unknown8to19.length !== 12) throw new Error("--unknown8to19-hex must be 12 bytes");
  }

  const canAssemble =
    typeAConfirmed &&
    seq.value !== null &&
    unknown8to19 &&
    unknown8to19.length === 12 &&
    endpoints.length > 0;

  let checksumLE = null;
  let unsafeFrameHex = null;
  if (canAssemble) {
    const frame = Buffer.alloc(24 + body.length);
    frame.writeUInt16BE(0x6d7e, 0);
    frame.writeUInt16LE(seq.value, 2);
    typeA.copy(frame, 4);
    unknown8to19.copy(frame, 8);
    frame.writeUInt16LE(body.length, 20);
    body.copy(frame, 24);
    const checksum = writeChecksumLE(frame);
    checksumLE = frame.subarray(22, 24).toString("hex");
    unsafeFrameHex = frame.toString("hex");
    warnings.push("frameHexCandidate is still suppressed from output by default because typeA/seq/offset8to19 are not independently confirmed for live use");
  }
  const includeIncompleteFrame = Boolean(args["unsafe-include-incomplete-frame"]);

  const result = {
    status: canAssemble ? "candidate" : "incomplete",
    doNotSend: true,
    frame: {
      soi: "6d7e",
      seqLE: seq.hexLE,
      typeA: typeAConfirmed ? typeAArg : "unknown",
      unknown8to19: unknown8to19 ? unknown8to19.toString("hex") : "unknown",
      bodyLengthLE: (() => {
        const b = Buffer.alloc(2);
        b.writeUInt16LE(body.length, 0);
        return b.toString("hex");
      })(),
      checksumLE,
      bodyHex: body.toString("hex"),
      frameHexCandidate: includeIncompleteFrame && unsafeFrameHex ? unsafeFrameHex : null,
      frameHexCandidateForOfflineSimulationOnly: unsafeFrameHex,
    },
    ackHex: null,
    safeToSend: false,
    reason: "typeA/seq/endpoint mapping not fully confirmed",
    internalUnsafeFrameHexComputed: unsafeFrameHex ? "suppressed" : null,
    confidence: {
      typeA: typeAConfirmed ? "caller supplied; not firmware-confirmed by this script" : "unknown",
      seq: seq.confidence,
      unknown8to19: unknown8to19 ? `${unknown8to19Strategy} candidate` : "unknown",
      body: "TLV layout high; endpoint values caller supplied and not live-confirmed",
      checksum: "high for ParseData checksum formula",
    },
    warnings,
  };
  if (includeIncompleteFrame) {
    result.warnings.push("unsafe-include-incomplete-frame was requested; safeToSend remains false and ackHex remains null");
  }
  return result;
}

function main() {
  const args = parseArgs(process.argv);
  const result = buildFrameCandidate(args);
  console.log(JSON.stringify(result, null, 2));
}

module.exports = { buildFrameCandidate };

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}


