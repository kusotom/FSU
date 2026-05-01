#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const DEFAULT_INPUT = path.join(__dirname, "..", "logs", "fsu_raw_packets", "2026-04-28.jsonl");
const DEFAULT_OUTPUT_DIR = path.join(__dirname, "..", "fixtures", "fsu");

const inputPath = path.resolve(process.argv[2] || DEFAULT_INPUT);
const outputDir = path.resolve(process.argv[3] || DEFAULT_OUTPUT_DIR);

const TARGETS = [
  { key: "udp_dsc_len24", protocol: "UDP_DSC", length: 24, limit: 20, file: "udp_dsc_len24.json" },
  { key: "udp_dsc_len209", protocol: "UDP_DSC", length: 209, limit: 20, file: "udp_dsc_len209.json" },
  { key: "udp_dsc_len245", protocol: "UDP_DSC", length: 245, limit: 20, file: "udp_dsc_len245.json" },
  { key: "udp_rds_len30", protocol: "UDP_RDS", length: 30, limit: 20, file: "udp_rds_len30.json" },
];

function fail(message) {
  console.error(message);
  process.exit(1);
}

function isSelfTestPacket(packet) {
  return /hello fsu udp/i.test(String(packet.rawText || ""));
}

function toFixture(packet) {
  return {
    protocol: packet.protocol,
    remoteAddress: packet.remoteAddress,
    remotePort: packet.remotePort,
    localPort: packet.localPort,
    length: packet.length,
    rawHex: packet.rawHex,
    rawText: packet.rawText,
    receivedAt: packet.receivedAt,
  };
}

function readPackets(filePath) {
  if (!fs.existsSync(filePath)) {
    fail(`input file not found: ${filePath}`);
  }
  return fs
    .readFileSync(filePath, "utf8")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line, index) => {
      try {
        return JSON.parse(line);
      } catch (error) {
        fail(`invalid JSON at line ${index + 1}: ${error.message}`);
      }
      return null;
    });
}

function main() {
  const packets = readPackets(inputPath);
  const buckets = new Map(TARGETS.map((target) => [target.key, []]));

  for (const packet of packets) {
    if (isSelfTestPacket(packet)) {
      continue;
    }
    for (const target of TARGETS) {
      const bucket = buckets.get(target.key);
      if (
        bucket.length < target.limit &&
        packet.protocol === target.protocol &&
        Number(packet.length) === target.length
      ) {
        bucket.push(toFixture(packet));
      }
    }
    if (TARGETS.every((target) => buckets.get(target.key).length >= target.limit)) {
      break;
    }
  }

  fs.mkdirSync(outputDir, { recursive: true });

  const summary = [];
  for (const target of TARGETS) {
    const fixtures = buckets.get(target.key);
    const outputPath = path.join(outputDir, target.file);
    fs.writeFileSync(outputPath, `${JSON.stringify(fixtures, null, 2)}\n`, "utf8");
    summary.push({ file: outputPath, count: fixtures.length, expected: target.limit });
  }

  console.log(`input: ${inputPath}`);
  for (const item of summary) {
    console.log(`${item.file}: ${item.count}/${item.expected}`);
  }
}

main();
