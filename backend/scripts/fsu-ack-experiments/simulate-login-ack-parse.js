#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const fs = require("fs");
const path = require("path");
const { computeParseDataChecksum } = require("./fsu-checksum");

const DATE_STEM = "2026-04-28";
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");
const REQUIRED_FLAGS = new Map([
  [0, 0x01],
  [5, 0x02],
  [6, 0x04],
  [7, 0x08],
  [8, 0x10],
  [9, 0x20],
]);

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

function cleanHex(hex) {
  return String(hex || "").replace(/\s+/g, "").toLowerCase();
}

function parseHexBuffer(hex, name = "frame-hex") {
  const normalized = cleanHex(hex);
  if (!normalized || normalized.length % 2 !== 0 || /[^0-9a-f]/.test(normalized)) {
    throw new Error(`invalid ${name}`);
  }
  return Buffer.from(normalized, "hex");
}

function isPrintableAscii(buffer) {
  for (const byte of buffer) {
    if (byte < 0x20 || byte > 0x7e) return false;
  }
  return true;
}

function parseEntries(body, entryCount, warnings) {
  const entries = [];
  let cursor = 3;
  let flags = 0;
  for (let i = 0; i < entryCount; i += 1) {
    if (cursor + 2 > body.length) {
      warnings.push(`entry ${i} header exceeds body length`);
      return { entries, flags, ok: false, cursor };
    }
    const fieldId = body[cursor];
    const valueLength = body[cursor + 1];
    cursor += 2;
    if (cursor + valueLength > body.length) {
      warnings.push(`entry ${i} value exceeds body length`);
      return { entries, flags, ok: false, cursor };
    }
    const valueBytes = body.subarray(cursor, cursor + valueLength);
    cursor += valueLength;
    const valueText = valueBytes.toString("ascii");
    if (REQUIRED_FLAGS.has(fieldId)) flags |= REQUIRED_FLAGS.get(fieldId);
    entries.push({
      index: i,
      fieldId,
      valueLength,
      valueHex: valueBytes.toString("hex"),
      valueText,
      printableAscii: isPrintableAscii(valueBytes),
      udpHostPortLike: /^udp:\/\/[^:]+:\d+$/.test(valueText),
    });
  }
  return { entries, flags, ok: cursor <= body.length, cursor };
}

function simulateLoginAckParse(frame) {
  const warnings = [
    "offline simulation only",
    "does not prove device will accept frame",
    "do not send",
  ];
  const checks = {
    soi: false,
    length: false,
    checksum: false,
    notBusy: false,
    dispatch47: false,
    statusSuccess: false,
    tlvParsed: false,
    requiredFlags: false,
  };
  const parsed = {};

  if (!Buffer.isBuffer(frame)) throw new TypeError("frame must be a Buffer");
  if (frame.length < 24) {
    warnings.push("frame length is below 24");
    return { ok: false, checks, parsed: { totalLength: frame.length }, warnings, doNotSend: true };
  }

  parsed.totalLength = frame.length;
  parsed.seqLE = frame.subarray(2, 4).toString("hex");
  parsed.typeA = frame.subarray(4, 8).toString("hex");
  parsed.offset8to19 = frame.subarray(8, 20).toString("hex");
  parsed.bodyLength = frame.readUInt16LE(20);
  parsed.checksumLE = frame.readUInt16LE(22);

  checks.soi = frame[0] === 0x6d && frame[1] === 0x7e;
  checks.length = parsed.bodyLength === frame.length - 24;
  const computedChecksum = computeParseDataChecksum(frame);
  parsed.computedChecksumLE = computedChecksum;
  checks.checksum = computedChecksum === parsed.checksumLE;
  checks.notBusy = (frame[5] & 0x40) === 0;
  checks.dispatch47 = frame[6] === 0x47;

  const body = frame.subarray(24);
  parsed.bodyHex = body.toString("hex");
  if (body.length < 3) {
    warnings.push("body length is below status+entryCount minimum");
    return { ok: false, checks, parsed, warnings, doNotSend: true };
  }
  parsed.status = body[0];
  parsed.entryCount = body.readUInt16LE(1);
  checks.statusSuccess = parsed.status === 0;
  if (parsed.status === 1) warnings.push("status is Fail path");
  if (parsed.status === 2) warnings.push("status is UnRegister path");

  const tlv = parseEntries(body, parsed.entryCount, warnings);
  parsed.entries = tlv.entries;
  parsed.flags = `0x${tlv.flags.toString(16).padStart(2, "0")}`;
  parsed.cursorEnd = tlv.cursor;
  checks.tlvParsed = tlv.ok && tlv.cursor === body.length;
  checks.requiredFlags = tlv.flags === 0x3f;

  const ok = Object.values(checks).every(Boolean);
  return { ok, checks, parsed, warnings, doNotSend: true, safeToSend: false, ackHex: null };
}

function writeReport(outDir, result) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `offline-login-ack-simulator-${DATE_STEM}.json`);
  const mdPath = path.join(outDir, `offline-login-ack-simulator-${DATE_STEM}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  fs.writeFileSync(
    mdPath,
    [
      "# Offline Login ACK Simulator",
      "",
      `OK: ${result.ok}`,
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
  const frameHex = args["frame-hex"] || args.frameHex || args.hex;
  if (!frameHex) throw new Error("missing --frame-hex");
  const result = simulateLoginAckParse(parseHexBuffer(frameHex));
  if (args["write-report"]) {
    result.reportPaths = writeReport(path.resolve(args["out-dir"] || DEFAULT_OUT_DIR), result);
  }
  console.log(JSON.stringify(result, null, 2));
}

module.exports = { parseHexBuffer, simulateLoginAckParse, writeReport };

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}


