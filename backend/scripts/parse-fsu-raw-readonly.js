#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const DEFAULT_INPUT = path.join(__dirname, "..", "logs", "fsu_raw_packets", "2026-04-28.jsonl");

function fail(message) {
  console.error(message);
  process.exit(1);
}

function parseDateStem(filePath) {
  const match = path.basename(filePath).match(/(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : new Date().toISOString().slice(0, 10);
}

function countMapInc(map, key, amount = 1) {
  const normalized = key === undefined || key === null || key === "" ? "(empty)" : String(key);
  map.set(normalized, (map.get(normalized) || 0) + amount);
}

function topEntries(map, limit = 1000) {
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .slice(0, limit);
}

function table(headers, rows) {
  const escapeCell = (value) => String(value ?? "").replace(/\r?\n/g, "<br>").replace(/\|/g, "\\|");
  return [
    `| ${headers.map(escapeCell).join(" | ")} |`,
    `| ${headers.map(() => "---").join(" | ")} |`,
    ...rows.map((row) => `| ${row.map(escapeCell).join(" | ")} |`),
    "",
  ].join("\n");
}

function readPackets(filePath) {
  if (!fs.existsSync(filePath)) {
    fail(`input file not found: ${filePath}`);
  }

  const packets = [];
  const errors = [];
  fs.readFileSync(filePath, "utf8")
    .split(/\r?\n/)
    .forEach((line, index) => {
      const trimmed = line.trim();
      if (!trimmed) {
        return;
      }
      try {
        packets.push(JSON.parse(trimmed));
      } catch (error) {
        errors.push({ line: index + 1, error: error.message });
      }
    });

  return { packets, errors };
}

function renderCountTable(title, headerName, map, limit = 50) {
  return [
    `## ${title}`,
    "",
    table([headerName, "count"], topEntries(map, limit).map(([key, count]) => [key, count])),
  ].join("\n");
}

function renderSummary({ inputPath, jsonlOutputPath, summaryOutputPath, totalInputPackets, jsonErrors, records, stats }) {
  const matchRate =
    stats.payloadLengthCandidateTotal > 0
      ? `${stats.payloadLengthCandidateMatches}/${stats.payloadLengthCandidateTotal} (${(
          (stats.payloadLengthCandidateMatches / stats.payloadLengthCandidateTotal) *
          100
        ).toFixed(2)}%)`
      : "0/0 (0.00%)";

  const lines = [];
  lines.push(`# FSU Readonly Parse Summary - ${parseDateStem(inputPath)}`);
  lines.push("");
  lines.push(`Input: \`${inputPath}\``);
  lines.push(`JSONL output: \`${jsonlOutputPath}\``);
  lines.push(`Generated at: \`${new Date().toISOString()}\``);
  lines.push("");
  lines.push("## Totals");
  lines.push("");
  lines.push(
    table(
      ["metric", "value"],
      [
        ["total packets in input", totalInputPackets],
        ["UDP_DSC / UDP_RDS packets parsed", records.length],
        ["parse ok", stats.parseOk],
        ["invalid JSON lines", jsonErrors.length],
        ["invalid header", stats.invalidHeader],
        ["UNKNOWN", stats.unknown],
        ["seqLE min", stats.seqMin === null ? "" : stats.seqMin],
        ["seqLE max", stats.seqMax === null ? "" : stats.seqMax],
        ["payloadLengthCandidate match rate", matchRate],
      ],
    ),
  );

  lines.push(renderCountTable("FrameClass Counts", "frameClass", stats.byFrameClass));
  lines.push(renderCountTable("TypeA Counts", "typeA", stats.byTypeA));
  lines.push(renderCountTable("URI Summary", "uri", stats.byUri));
  lines.push(renderCountTable("IP Summary", "ipAddress", stats.byIp));
  lines.push(renderCountTable("Port Summary", "port", stats.byPort));

  lines.push("## UNKNOWN Samples");
  lines.push("");
  if (!stats.unknownSamples.length) {
    lines.push("(none)");
    lines.push("");
  } else {
    lines.push(
      table(
        ["receivedAt", "protocol", "length", "typeA", "rawHexPrefix"],
        stats.unknownSamples.map((sample) => [
          sample.receivedAt,
          sample.protocol,
          sample.length,
          sample.typeA,
          sample.rawHexPrefix,
        ]),
      ),
    );
  }

  if (jsonErrors.length) {
    lines.push("## JSON Parse Errors");
    lines.push("");
    lines.push(table(["line", "error"], jsonErrors.slice(0, 20).map((error) => [error.line, error.error])));
  }

  fs.writeFileSync(summaryOutputPath, `${lines.join("\n")}\n`, "utf8");
}

function main() {
  const inputPath = path.resolve(process.argv[2] || DEFAULT_INPUT);
  const dateStem = parseDateStem(inputPath);
  const outputDir = path.dirname(inputPath);
  const jsonlOutputPath = path.join(outputDir, `readonly-parse-${dateStem}.jsonl`);
  const summaryOutputPath = path.join(outputDir, `readonly-parse-summary-${dateStem}.md`);
  const { packets, errors } = readPackets(inputPath);

  const records = [];
  const stats = {
    parseOk: 0,
    invalidHeader: 0,
    unknown: 0,
    seqMin: null,
    seqMax: null,
    payloadLengthCandidateMatches: 0,
    payloadLengthCandidateTotal: 0,
    byFrameClass: new Map(),
    byTypeA: new Map(),
    byUri: new Map(),
    byIp: new Map(),
    byPort: new Map(),
    unknownSamples: [],
  };

  const output = fs.createWriteStream(jsonlOutputPath, { encoding: "utf8" });

  for (const packet of packets) {
    if (packet.protocol !== "UDP_DSC" && packet.protocol !== "UDP_RDS") {
      continue;
    }

    const parsed = parseFsuFrame(packet.rawHex, {
      protocol: packet.protocol,
      includePayloadHex: false,
      includeAscii: true,
    });
    const record = {
      receivedAt: packet.receivedAt,
      protocol: packet.protocol,
      remoteAddress: packet.remoteAddress,
      remotePort: packet.remotePort,
      localPort: packet.localPort,
      length: packet.length,
      parsed,
    };
    records.push(record);
    output.write(`${JSON.stringify(record)}\n`);

    if (parsed.ok) {
      stats.parseOk += 1;
    }
    if (!parsed.validHeader) {
      stats.invalidHeader += 1;
    }
    countMapInc(stats.byFrameClass, parsed.frameClass);
    countMapInc(stats.byTypeA, parsed.typeA);

    if (parsed.seqLE !== null) {
      stats.seqMin = stats.seqMin === null ? parsed.seqLE : Math.min(stats.seqMin, parsed.seqLE);
      stats.seqMax = stats.seqMax === null ? parsed.seqLE : Math.max(stats.seqMax, parsed.seqLE);
    }

    if (parsed.payloadLengthCandidate !== null) {
      stats.payloadLengthCandidateTotal += 1;
      if (parsed.payloadLengthMatchesTotalMinus24) {
        stats.payloadLengthCandidateMatches += 1;
      }
    }

    for (const uri of parsed.uris) {
      countMapInc(stats.byUri, uri);
    }
    for (const ipAddress of parsed.ipAddresses) {
      countMapInc(stats.byIp, ipAddress);
    }
    for (const port of parsed.ports) {
      countMapInc(stats.byPort, port);
    }

    if (parsed.frameClass === "UNKNOWN") {
      stats.unknown += 1;
      if (stats.unknownSamples.length < 10) {
        stats.unknownSamples.push({
          receivedAt: packet.receivedAt,
          protocol: packet.protocol,
          length: packet.length,
          typeA: parsed.typeA,
          rawHexPrefix: String(packet.rawHex || "").slice(0, 120),
        });
      }
    }
  }

  output.end(() => {
    renderSummary({
      inputPath,
      jsonlOutputPath,
      summaryOutputPath,
      totalInputPackets: packets.length,
      jsonErrors: errors,
      records,
      stats,
    });
    console.log(`jsonl: ${jsonlOutputPath}`);
    console.log(`summary: ${summaryOutputPath}`);
  });
}

main();
