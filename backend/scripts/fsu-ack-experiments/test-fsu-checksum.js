#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../../app/modules/fsu_gateway/parser/fsu-frame-parser");
const { CHECKSUM_OFFSET, computeParseDataChecksum } = require("./fsu-checksum");

const DATE_STEM = "2026-04-28";
const DEFAULT_LOG = path.join(process.cwd(), "backend", "logs", "fsu_raw_packets", `${DATE_STEM}.jsonl`);
const TEST_CLASSES = [
  "DSC_CONFIG_209_TYPE_1100_46FF",
  "DSC_CONFIG_245_TYPE_1100_46FF",
  "RDS_SHORT_30_TYPE_1180_D2FF",
  "DSC_SHORT_24_TYPE_1F00_D2FF",
];

function cleanHex(value) {
  return String(value || "").replace(/[^0-9a-f]/gi, "").toLowerCase();
}

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

function collectSamples(logPath, perClass = 20) {
  const samples = new Map(TEST_CLASSES.map((frameClass) => [frameClass, []]));
  for (const line of fs.readFileSync(logPath, "utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    let packet;
    try {
      packet = JSON.parse(line);
    } catch {
      continue;
    }
    if (packet.protocol !== "UDP_DSC" && packet.protocol !== "UDP_RDS") continue;
    const rawHex = cleanHex(packet.rawHex);
    if (!rawHex || rawHex.length % 2 !== 0) continue;
    const parsed = parseFsuFrame(rawHex, { protocol: packet.protocol, includeAscii: false });
    if (!samples.has(parsed.frameClass)) continue;
    const bucket = samples.get(parsed.frameClass);
    if (bucket.length >= perClass) continue;
    bucket.push({ packet, parsed, buffer: Buffer.from(rawHex, "hex") });
    if ([...samples.values()].every((items) => items.length >= perClass)) break;
  }
  return samples;
}

function run(logPath) {
  const samples = collectSamples(logPath, 20);
  const results = [];
  let failures = 0;

  for (const frameClass of TEST_CLASSES) {
    const items = samples.get(frameClass) || [];
    let matched = 0;
    const details = [];
    for (const item of items) {
      const expected = item.buffer.readUInt16LE(CHECKSUM_OFFSET);
      const actual = computeParseDataChecksum(item.buffer);
      const diff = (expected - actual) & 0xffff;
      const ok = expected === actual;
      if (ok) matched += 1;
      details.push({
        receivedAt: item.packet.receivedAt,
        expected,
        expectedHex: `0x${expected.toString(16)}`,
        actual,
        actualHex: `0x${actual.toString(16)}`,
        diff,
        diffHex: `0x${diff.toString(16)}`,
        ok,
      });
    }

    const expectedPass = frameClass !== "DSC_SHORT_24_TYPE_1F00_D2FF";
    const pass = expectedPass ? items.length === 20 && matched === items.length : items.length === 20 && matched === 0;
    if (!pass) failures += 1;
    results.push({
      frameClass,
      sampleCount: items.length,
      matched,
      expectedPass,
      pass,
      note: expectedPass
        ? "ParseData checksum must match all sampled frames."
        : "DSC_SHORT_24 is intentionally marked not applicable to this exact formula.",
      details,
    });
  }

  return { logPath, failures, results };
}

function main() {
  const args = parseArgs(process.argv);
  const logPath = path.resolve(args.log || DEFAULT_LOG);
  const result = run(logPath);
  console.log(JSON.stringify(result, null, 2));
  if (result.failures) process.exit(1);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}


