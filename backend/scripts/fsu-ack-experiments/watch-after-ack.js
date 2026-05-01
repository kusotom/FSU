#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../../app/modules/fsu_gateway/parser/fsu-frame-parser");
const { RAW_LOG_RE, DEFAULT_DIR: DEFAULT_RAW_LOG_DIR, listRawLogs } = require("./select-latest-fsu-log");

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

function usage() {
  return [
    "usage:",
    "  node backend/scripts/fsu-ack-experiments/watch-after-ack.js --log backend/logs/fsu_raw_packets/2026-04-28.jsonl --since \"2026-04-28T09:00:00.000Z\" --seconds 60",
  ].join("\n");
}

function countMapInc(map, key, amount = 1) {
  const normalized = key === undefined || key === null || key === "" ? "(empty)" : String(key);
  map.set(normalized, (map.get(normalized) || 0) + amount);
}

function countObject(map) {
  return Object.fromEntries(
    [...map.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]))),
  );
}

function dateStemFromMs(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

function resolveLogPaths(logArg, sinceMs, seconds) {
  if (logArg !== "auto") {
    return String(logArg)
      .split(",")
      .map((item) => path.resolve(item.trim()))
      .filter(Boolean);
  }
  const endMs = sinceMs + seconds * 1000;
  const startDate = dateStemFromMs(sinceMs);
  const endDate = dateStemFromMs(endMs);
  return listRawLogs(DEFAULT_RAW_LOG_DIR)
    .filter((item) => RAW_LOG_RE.test(item.name) && item.date >= startDate && item.date <= endDate)
    .map((item) => item.path)
    .sort();
}

function readPackets(logPaths) {
  const packets = [];
  const errors = [];
  for (const logPath of logPaths) {
    if (!fs.existsSync(logPath)) {
      throw new Error(`log not found: ${logPath}`);
    }
    fs.readFileSync(logPath, "utf8")
      .split(/\r?\n/)
      .forEach((line, index) => {
        const trimmed = line.trim();
        if (!trimmed) {
          return;
        }
        try {
          packets.push(JSON.parse(trimmed));
        } catch (error) {
          errors.push({ file: logPath, line: index + 1, error: error.message });
        }
      });
  }
  return { packets, errors };
}

function hasVisibleAscii(parsed) {
  return (parsed.asciiSpans || []).some((span) => /[A-Za-z]{4,}/.test(span.text));
}

function summarize(records) {
  const frameClassCounts = new Map();
  const typeACounts = new Map();
  const lengthCounts = new Map();
  const payloadLengthCounts = new Map();
  const remotePortCounts = new Map();
  const udpDscRemotePortCounts = new Map();
  const udpRdsRemotePortCounts = new Map();
  const dscConfigRemotePortCounts = new Map();
  const asciiFrameClasses = new Map();
  const protocols = new Map();
  let dscConfigCount = 0;
  let unknownCount = 0;

  for (const record of records) {
    countMapInc(protocols, record.protocol);
    countMapInc(remotePortCounts, record.remotePort);
    if (record.protocol === "UDP_DSC") countMapInc(udpDscRemotePortCounts, record.remotePort);
    if (record.protocol === "UDP_RDS") countMapInc(udpRdsRemotePortCounts, record.remotePort);
    countMapInc(frameClassCounts, record.parsed.frameClass);
    countMapInc(typeACounts, record.parsed.typeA);
    countMapInc(lengthCounts, record.parsed.totalLength);
    countMapInc(payloadLengthCounts, record.parsed.payloadLengthCandidate);
    if (
      record.parsed.frameClass === "DSC_CONFIG_209_TYPE_1100_46FF" ||
      record.parsed.frameClass === "DSC_CONFIG_245_TYPE_1100_46FF"
    ) {
      dscConfigCount += 1;
      countMapInc(dscConfigRemotePortCounts, record.remotePort);
    }
    if (record.parsed.frameClass === "UNKNOWN") {
      unknownCount += 1;
    }
    if (hasVisibleAscii(record.parsed)) {
      countMapInc(asciiFrameClasses, record.parsed.frameClass);
    }
  }

  return {
    total: records.length,
    protocols: countObject(protocols),
    frameClassCounts: countObject(frameClassCounts),
    typeACounts: countObject(typeACounts),
    lengthCounts: countObject(lengthCounts),
    payloadLengthCandidateCounts: countObject(payloadLengthCounts),
    remotePortCounts: countObject(remotePortCounts),
    udpDscRemotePortCounts: countObject(udpDscRemotePortCounts),
    udpRdsRemotePortCounts: countObject(udpRdsRemotePortCounts),
    dscConfigRemotePortCounts: countObject(dscConfigRemotePortCounts),
    dscConfig209Or245Count: dscConfigCount,
    unknownCount,
    asciiFrameClassCounts: countObject(asciiFrameClasses),
  };
}

function setDifference(afterObject, beforeObject) {
  return Object.keys(afterObject).filter((key) => !(key in beforeObject));
}

function main() {
  const args = parseArgs(process.argv);
  if (!args.log || !args.since || !args.seconds) {
    console.error(usage());
    process.exit(1);
  }

  const sinceMs = Date.parse(args.since);
  const seconds = Number(args.seconds);
  if (!Number.isFinite(sinceMs) || !Number.isFinite(seconds) || seconds <= 0) {
    console.error("--since must be ISO time and --seconds must be positive");
    process.exit(1);
  }

  const logPaths = resolveLogPaths(args.log, sinceMs, seconds);
  const { packets, errors } = readPackets(logPaths);
  const beforeStart = sinceMs - seconds * 1000;
  const beforeEnd = sinceMs;
  const afterStart = sinceMs;
  const afterEnd = sinceMs + seconds * 1000;
  const parsedRecords = [];

  for (const packet of packets) {
    if (packet.protocol !== "UDP_DSC" && packet.protocol !== "UDP_RDS") {
      continue;
    }
    const timeMs = Date.parse(packet.receivedAt);
    if (!Number.isFinite(timeMs) || timeMs < beforeStart || timeMs > afterEnd) {
      continue;
    }
    parsedRecords.push({
      receivedAt: packet.receivedAt,
      timeMs,
      protocol: packet.protocol,
      remoteAddress: packet.remoteAddress,
      remotePort: packet.remotePort,
      localPort: packet.localPort,
      parsed: parseFsuFrame(packet.rawHex, {
        protocol: packet.protocol,
        includeAscii: true,
      }),
    });
  }

  const beforeRecords = parsedRecords.filter((record) => record.timeMs >= beforeStart && record.timeMs < beforeEnd);
  const afterRecords = parsedRecords.filter((record) => record.timeMs >= afterStart && record.timeMs <= afterEnd);
  const before = summarize(beforeRecords);
  const after = summarize(afterRecords);
  const result = {
    logPath: args.log,
    logPaths,
    since: new Date(sinceMs).toISOString(),
    seconds,
    jsonParseErrors: errors,
    beforeWindow: {
      start: new Date(beforeStart).toISOString(),
      end: new Date(beforeEnd).toISOString(),
      summary: before,
    },
    afterWindow: {
      start: new Date(afterStart).toISOString(),
      end: new Date(afterEnd).toISOString(),
      summary: after,
    },
    judgement: {
      longConfigReduced: after.dscConfig209Or245Count < before.dscConfig209Or245Count,
      newFrameClasses: setDifference(after.frameClassCounts, before.frameClassCounts),
      newLengths: setDifference(after.lengthCounts, before.lengthCounts),
      newTypeA: setDifference(after.typeACounts, before.typeACounts),
      newPayloadLengthCandidates: setDifference(
        after.payloadLengthCandidateCounts,
        before.payloadLengthCandidateCounts,
      ),
      newRemotePorts: setDifference(after.remotePortCounts, before.remotePortCounts),
      afterOnlyFrameClasses: setDifference(after.frameClassCounts, before.frameClassCounts),
      afterOnlyTypeA: setDifference(after.typeACounts, before.typeACounts),
      afterOnlyLengths: setDifference(after.lengthCounts, before.lengthCounts),
      obviousAsciiFrameClassesAfter: after.asciiFrameClassCounts,
    },
  };

  console.log(JSON.stringify(result, null, 2));
}

main();


