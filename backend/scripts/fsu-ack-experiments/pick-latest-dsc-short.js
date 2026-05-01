#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../../app/modules/fsu_gateway/parser/fsu-frame-parser");

const DEFAULT_LOG = path.join(__dirname, "..", "..", "logs", "fsu_raw_packets", "2026-04-28.jsonl");
const TARGET_FRAME_CLASS = "DSC_SHORT_24_TYPE_1F00_D2FF";

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) {
      continue;
    }
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

function isLocalTestPacket(packet) {
  const rawText = String(packet.rawText || "").toLowerCase();
  return (
    rawText.includes("hello fsu udp") ||
    packet.remoteAddress === "127.0.0.1" ||
    packet.remoteAddress === "::1"
  );
}

function isTargetPacket(packet, parsed) {
  return (
    packet.protocol === "UDP_DSC" &&
    packet.remoteAddress === "192.168.100.100" &&
    Number(packet.localPort) === 9000 &&
    Number(packet.length) === 24 &&
    parsed.frameClass === TARGET_FRAME_CLASS
  );
}

function remotePortMatches(packet, remotePortFilter) {
  if (!remotePortFilter || remotePortFilter === "any") {
    return true;
  }
  return Number(packet.remotePort) === Number(remotePortFilter);
}

function readLatest(logPath, remotePortFilter) {
  if (!fs.existsSync(logPath)) {
    throw new Error(`log file not found: ${logPath}`);
  }

  const lines = fs.readFileSync(logPath, "utf8").split(/\r?\n/);
  let latest = null;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }

    let packet;
    try {
      packet = JSON.parse(trimmed);
    } catch {
      continue;
    }

    if (isLocalTestPacket(packet)) {
      continue;
    }

    if (
      packet.protocol !== "UDP_DSC" ||
      packet.remoteAddress !== "192.168.100.100" ||
      !remotePortMatches(packet, remotePortFilter) ||
      Number(packet.localPort) !== 9000 ||
      Number(packet.length) !== 24
    ) {
      continue;
    }

    const parsed = parseFsuFrame(packet.rawHex, {
      protocol: packet.protocol,
      includePayloadHex: false,
      includeAscii: false,
    });

    if (!isTargetPacket(packet, parsed)) {
      continue;
    }

    latest = {
      receivedAt: packet.receivedAt,
      protocol: packet.protocol,
      remoteAddress: packet.remoteAddress,
      remotePort: Number(packet.remotePort),
      localPort: Number(packet.localPort),
      length: Number(packet.length),
      rawHex: packet.rawHex,
      seqLE: parsed.seqLE,
      typeA: parsed.typeA,
      frameClass: parsed.frameClass,
    };
  }

  return latest;
}

function main() {
  const args = parseArgs(process.argv);
  const logPath = path.resolve(args.log || DEFAULT_LOG);
  const remotePortFilter = args["remote-port"] || "any";
  const latest = readLatest(logPath, remotePortFilter);

  if (!latest) {
    console.error(`no matching ${TARGET_FRAME_CLASS} packet found in ${logPath}`);
    process.exit(1);
  }

  console.log(JSON.stringify(latest, null, 2));
}

main();


