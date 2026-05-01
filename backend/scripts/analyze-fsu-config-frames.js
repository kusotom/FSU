#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const DEFAULT_INPUT = path.join(__dirname, "..", "logs", "fsu_raw_packets", "2026-04-28.jsonl");
const CONFIG_CLASSES = new Set([
  "DSC_CONFIG_209_TYPE_1100_46FF",
  "DSC_CONFIG_245_TYPE_1100_46FF",
]);

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

function countObject(map, limit = 1000) {
  return Object.fromEntries(topEntries(map, limit));
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

function hexToBuffer(rawHex) {
  const clean = String(rawHex || "").replace(/[^0-9a-f]/gi, "");
  if (!clean || clean.length % 2 !== 0) {
    return Buffer.alloc(0);
  }
  return Buffer.from(clean, "hex");
}

function byteHex(buf, offset) {
  return offset >= 0 && offset < buf.length ? buf[offset].toString(16).padStart(2, "0") : "";
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

function valueDistribution(values) {
  const map = new Map();
  for (const value of values) {
    countMapInc(map, value);
  }
  return topEntries(map).map(([value, count]) => `${value}:${count}`).join(", ");
}

function uniqueSorted(values) {
  return [...new Set(values)].sort((a, b) => {
    if (typeof a === "number" && typeof b === "number") {
      return a - b;
    }
    return String(a).localeCompare(String(b));
  });
}

function collapseOffsets(offsets) {
  if (!offsets.length) {
    return "(none)";
  }
  const sorted = [...offsets].sort((a, b) => a - b);
  const ranges = [];
  let start = sorted[0];
  let prev = sorted[0];

  for (const offset of sorted.slice(1)) {
    if (offset === prev + 1) {
      prev = offset;
      continue;
    }
    ranges.push(start === prev ? String(start) : `${start}-${prev}`);
    start = offset;
    prev = offset;
  }
  ranges.push(start === prev ? String(start) : `${start}-${prev}`);
  return ranges.join(", ");
}

function byteStats(records, makeBuf) {
  const maxLength = Math.max(0, ...records.map((record) => makeBuf(record).length));
  const rows = [];

  for (let offset = 0; offset < maxLength; offset += 1) {
    const values = new Map();
    let present = 0;
    for (const record of records) {
      const buf = makeBuf(record);
      const value = byteHex(buf, offset);
      if (value) {
        present += 1;
      }
      countMapInc(values, value || "(missing)");
    }
    const nonMissingKeys = [...values.keys()].filter((value) => value !== "(missing)");
    rows.push({
      offset,
      present,
      total: records.length,
      fixed: values.size === 1 && !values.has("(missing)"),
      commonFixed: present === records.length && nonMissingKeys.length === 1,
      valueHex: nonMissingKeys.length === 1 ? nonMissingKeys[0] : "",
      distinctCount: values.size,
      topValues: topEntries(values, 8).map(([value, count]) => `${value}:${count}`).join(", "),
    });
  }

  return rows;
}

function summarizeClass(records, frameClass) {
  const classRecords = records.filter((record) => record.frameClass === frameClass);
  const totalLengths = classRecords.map((record) => record.totalLength);
  const declaredLengths = classRecords.map((record) => record.declaredPayloadLength);
  const uriCounts = classRecords.map((record) => record.udpUris.length + record.ftpUris.length);
  const udpCounts = classRecords.map((record) => record.udpUris.length);
  const ftpCounts = classRecords.map((record) => record.ftpUris.length);
  const firstUriOffsets = classRecords.map((record) => record.stringLayout.firstUriOffset);
  const lastUriOffsets = classRecords.map((record) => record.stringLayout.lastUriOffset);
  const asciiStartOffsets = classRecords.map((record) => record.stringLayout.bodyAsciiStartOffset);
  const asciiEndOffsets = classRecords.map((record) => record.stringLayout.bodyAsciiEndOffset);
  const zeroCounts = classRecords.map((record) => record.zeroTerminatedStrings.length);
  const uriPrefixPatterns = new Map();

  for (const record of classRecords) {
    for (const field of record.uriFields) {
      countMapInc(
        uriPrefixPatterns,
        `${field.scheme}@${field.offsetInFrame}:prefix=${field.preceding2BytesHex}:len=${field.precedingByteDecimal}`,
      );
    }
  }

  return {
    frameClass,
    count: classRecords.length,
    totalLength: valueDistribution(totalLengths),
    declaredPayloadLength: valueDistribution(declaredLengths),
    uriCount: valueDistribution(uriCounts),
    udpUriCount: valueDistribution(udpCounts),
    ftpUriCount: valueDistribution(ftpCounts),
    firstUriOffset: valueDistribution(firstUriOffsets),
    lastUriOffset: valueDistribution(lastUriOffsets),
    bodyAsciiStartOffset: valueDistribution(asciiStartOffsets),
    bodyAsciiEndOffset: valueDistribution(asciiEndOffsets),
    zeroTerminatedStringCount: valueDistribution(zeroCounts),
    uriPrefixPatterns: countObject(uriPrefixPatterns),
  };
}

function configRecord(packet, parsed) {
  const config = parsed.dscConfig;
  return {
    receivedAt: packet.receivedAt,
    remoteAddress: packet.remoteAddress,
    remotePort: packet.remotePort,
    localPort: packet.localPort,
    frameClass: parsed.frameClass,
    seqLE: parsed.seqLE,
    totalLength: parsed.totalLength,
    declaredPayloadLength: parsed.payloadLengthCandidate,
    bodyLength: parsed.bodyLength,
    udpUris: config.udpUris,
    ftpUris: config.ftpUris,
    ipAddresses: config.ipAddresses,
    ports: config.ports,
    usernameCandidates: config.usernameCandidates,
    passwordCandidates: config.passwordCandidates,
    credentialCandidates: config.credentialCandidates,
    usesDhcpPlaceholder: config.usesDhcpPlaceholder,
    usesExplicitIp: config.usesExplicitIp,
    asciiRegions: config.asciiRegions,
    zeroTerminatedStrings: config.zeroTerminatedStrings,
    uriFields: config.uriFields,
    fixedBinaryPrefix: config.fixedBinaryPrefix,
    variableFields: config.variableFields,
    stringLayout: config.stringLayout,
    rawSummary: parsed.rawSummary,
  };
}

function createAnalysis(records, parseErrors) {
  const byFrameClass = new Map();
  const byUri = new Map();
  const byIp = new Map();
  const byPort = new Map();
  const byUsername = new Map();
  const byPassword = new Map();
  const byZeroTerminatedText = new Map();
  const byAsciiRegionLayout = new Map();

  for (const record of records) {
    countMapInc(byFrameClass, record.frameClass);
    for (const uri of [...record.udpUris, ...record.ftpUris]) {
      countMapInc(byUri, uri);
    }
    for (const ip of record.ipAddresses) {
      countMapInc(byIp, ip);
    }
    for (const port of record.ports) {
      countMapInc(byPort, port);
    }
    for (const username of record.usernameCandidates) {
      countMapInc(byUsername, username);
    }
    for (const password of record.passwordCandidates) {
      countMapInc(byPassword, password);
    }
    for (const zString of record.zeroTerminatedStrings) {
      countMapInc(byZeroTerminatedText, `${zString.offsetInFrame}:${zString.text}`);
    }
    for (const region of record.asciiRegions) {
      countMapInc(byAsciiRegionLayout, `${region.offsetInFrame}-${region.offsetEndInFrame}:len=${region.length}`);
    }
  }

  const fullByteRecords = records.map((record) => {
    const source = record.__rawHex ? hexToBuffer(record.__rawHex) : Buffer.alloc(0);
    return { ...record, __buf: source, __body: source.length > 22 ? source.subarray(22) : Buffer.alloc(0) };
  });
  const fullStats = byteStats(fullByteRecords, (record) => record.__buf);
  const bodyStats = byteStats(fullByteRecords, (record) => record.__body);
  const classByteStats = {};

  for (const frameClass of CONFIG_CLASSES) {
    const classRecords = fullByteRecords.filter((record) => record.frameClass === frameClass);
    classByteStats[frameClass] = {
      fixedFrameOffsets: byteStats(classRecords, (record) => record.__buf)
        .filter((row) => row.fixed)
        .map((row) => ({ offset: row.offset, valueHex: row.valueHex })),
      variableFrameOffsets: byteStats(classRecords, (record) => record.__buf)
        .filter((row) => !row.fixed)
        .map((row) => ({ offset: row.offset, topValues: row.topValues })),
      fixedBodyOffsets: byteStats(classRecords, (record) => record.__body)
        .filter((row) => row.fixed)
        .map((row) => ({ offsetInBody: row.offset, offsetInFrame: row.offset + 22, valueHex: row.valueHex })),
      variableBodyOffsets: byteStats(classRecords, (record) => record.__body)
        .filter((row) => !row.fixed)
        .map((row) => ({ offsetInBody: row.offset, offsetInFrame: row.offset + 22, topValues: row.topValues })),
    };
  }

  const comparison = [...CONFIG_CLASSES].map((frameClass) => summarizeClass(records, frameClass));
  const fixedFrameOffsetsAcrossAll = fullStats.filter((row) => row.commonFixed).map((row) => row.offset);
  const variableFrameOffsetsAcrossAll = fullStats.filter((row) => !row.commonFixed).map((row) => row.offset);
  const fixedBodyOffsetsAcrossAll = bodyStats.filter((row) => row.commonFixed).map((row) => row.offset);
  const variableBodyOffsetsAcrossAll = bodyStats.filter((row) => !row.commonFixed).map((row) => row.offset);

  const d209 = records.filter((record) => record.frameClass === "DSC_CONFIG_209_TYPE_1100_46FF");
  const d245 = records.filter((record) => record.frameClass === "DSC_CONFIG_245_TYPE_1100_46FF");

  return {
    generatedAt: new Date().toISOString(),
    counts: {
      totalConfigFrames: records.length,
      dscConfig209: d209.length,
      dscConfig245: d245.length,
      parseErrors: parseErrors.length,
    },
    summaries: {
      frameClass: countObject(byFrameClass),
      uri: countObject(byUri),
      ipAddress: countObject(byIp),
      port: countObject(byPort),
      usernameCandidate: countObject(byUsername),
      passwordCandidate: countObject(byPassword),
      zeroTerminatedText: countObject(byZeroTerminatedText, 50),
      asciiRegionLayout: countObject(byAsciiRegionLayout, 80),
    },
    comparison,
    fixedBinaryFields: {
      commonFixedFrameOffsetsAcrossConfigFrames: fixedFrameOffsetsAcrossAll,
      commonFixedFrameOffsetRangesAcrossConfigFrames: collapseOffsets(fixedFrameOffsetsAcrossAll),
      commonFixedBodyOffsetsAcrossConfigFrames: fixedBodyOffsetsAcrossAll,
      commonFixedBodyOffsetRangesAcrossConfigFrames: collapseOffsets(fixedBodyOffsetsAcrossAll),
      byFrameClass: classByteStats,
    },
    variableFields: {
      variableFrameOffsetsAcrossConfigFrames: variableFrameOffsetsAcrossAll,
      variableFrameOffsetRangesAcrossConfigFrames: collapseOffsets(variableFrameOffsetsAcrossAll),
      variableBodyOffsetsAcrossConfigFrames: variableBodyOffsetsAcrossAll,
      variableBodyOffsetRangesAcrossConfigFrames: collapseOffsets(variableBodyOffsetsAcrossAll),
    },
    differenceAssessment: {
      lengthDelta245Minus209: 36,
      likelyPrimaryCause:
        "Observed URI text length deltas explain the full 36-byte frame length difference: three UDP URIs are 26 vs 17 bytes (+27), one FTP URI is 32 vs 23 bytes (+9).",
      uriCountDifference: "No observed URI count difference; both classes carry three UDP URI strings and one FTP URI string.",
      tailPaddingDifference: "No separate trailing padding was observed after the final FTP URI in representative parsed layouts.",
      otherBinaryDifference:
        "Some non-URI prefix bytes vary across samples/classes; current evidence does not require them to explain the 209/245 length delta.",
    },
    inferredBoundaries: [
      { name: "frame header", offset: "bytes[0..1]", status: "confirmed", evidence: "fixed 6d7e" },
      { name: "sequence", offset: "bytes[2..3]", status: "candidate", evidence: "seqLE monotonically varies" },
      { name: "typeA", offset: "bytes[4..7]", status: "confirmed signature", evidence: "110046ff for both long config classes" },
      { name: "unknown fixed area", offset: "bytes[8..19]", status: "unknown", evidence: "mostly fixed across current samples" },
      {
        name: "declared payload length",
        offset: "bytes[20..21]",
        status: "strong candidate",
        evidence: "little endian value equals totalLength - 24",
      },
      { name: "body", offset: "bytes[22..end]", status: "strong candidate", evidence: "contains config binary and ASCII areas" },
      {
        name: "leading zero-terminated string candidate",
        offset: "body offset 0/1 through 34",
        status: "candidate",
        evidence: "printable ASCII ending with 00 in long config frames",
      },
      {
        name: "URI string area",
        offset: "frame offset 129 through end",
        status: "candidate",
        evidence: "three udp:// strings followed by one ftp:// string; preceding byte equals URI length in observed samples",
      },
    ],
    configFrames: records.map((record) => {
      const { __rawHex, ...publicRecord } = record;
      return publicRecord;
    }),
  };
}

function renderMarkdown({ inputPath, jsonPath, analysis }) {
  const lines = [];
  lines.push(`# FSU DSC Config Frame Analysis - ${parseDateStem(inputPath)}`);
  lines.push("");
  lines.push(`Input: \`${inputPath}\``);
  lines.push(`JSON report: \`${jsonPath}\``);
  lines.push(`Generated at: \`${analysis.generatedAt}\``);
  lines.push("");

  lines.push("## 1. Overview");
  lines.push("");
  lines.push(
    table(
      ["metric", "value"],
      [
        ["total config frames", analysis.counts.totalConfigFrames],
        ["DSC_CONFIG_209", analysis.counts.dscConfig209],
        ["DSC_CONFIG_245", analysis.counts.dscConfig245],
        ["parse errors", analysis.counts.parseErrors],
      ],
    ),
  );

  lines.push("## 2. URI / IP / Port / Credential Candidate Counts");
  lines.push("");
  lines.push(table(["URI", "count"], Object.entries(analysis.summaries.uri)));
  lines.push(table(["IP", "count"], Object.entries(analysis.summaries.ipAddress)));
  lines.push(table(["port", "count"], Object.entries(analysis.summaries.port)));
  lines.push(table(["usernameCandidate", "count"], Object.entries(analysis.summaries.usernameCandidate)));
  lines.push(table(["passwordCandidate", "count"], Object.entries(analysis.summaries.passwordCandidate)));

  lines.push("## 3. 209 / 245 Difference Comparison");
  lines.push("");
  lines.push(
    table(
      [
        "frameClass",
        "totalLength",
        "declaredPayloadLength",
        "uri count",
        "udp uri count",
        "ftp uri count",
        "first uri offset",
        "last uri offset",
        "body ascii start offset",
        "body ascii end offset",
      ],
      analysis.comparison.map((row) => [
        row.frameClass,
        row.totalLength,
        row.declaredPayloadLength,
        row.uriCount,
        row.udpUriCount,
        row.ftpUriCount,
        row.firstUriOffset,
        row.lastUriOffset,
        row.bodyAsciiStartOffset,
        row.bodyAsciiEndOffset,
      ]),
    ),
  );
  lines.push(`Length assessment: ${analysis.differenceAssessment.likelyPrimaryCause}`);
  lines.push(`URI count assessment: ${analysis.differenceAssessment.uriCountDifference}`);
  lines.push(`Tail padding assessment: ${analysis.differenceAssessment.tailPaddingDifference}`);
  lines.push(`Other binary fields: ${analysis.differenceAssessment.otherBinaryDifference}`);
  lines.push("");

  lines.push("## 4. String Offset Layout");
  lines.push("");
  lines.push(table(["layout", "count"], Object.entries(analysis.summaries.asciiRegionLayout)));

  lines.push("## 5. Zero-Terminated String Layout");
  lines.push("");
  lines.push(table(["zeroTerminatedString", "count"], Object.entries(analysis.summaries.zeroTerminatedText)));

  lines.push("## 6. URI Field Prefix Bytes");
  lines.push("");
  for (const row of analysis.comparison) {
    lines.push(`### ${row.frameClass}`);
    lines.push("");
    lines.push(table(["uri prefix pattern", "count"], Object.entries(row.uriPrefixPatterns)));
  }

  lines.push("## 7. Fixed Binary Fields");
  lines.push("");
  lines.push(
    table(
      ["scope", "offset ranges"],
      [
        ["frame offsets fixed across both config classes", analysis.fixedBinaryFields.commonFixedFrameOffsetRangesAcrossConfigFrames],
        ["body offsets fixed across both config classes", analysis.fixedBinaryFields.commonFixedBodyOffsetRangesAcrossConfigFrames],
      ],
    ),
  );
  for (const [frameClass, stats] of Object.entries(analysis.fixedBinaryFields.byFrameClass)) {
    lines.push(`### ${frameClass}`);
    lines.push("");
    lines.push(
      table(
        ["metric", "value"],
        [
          ["fixed frame offset ranges", collapseOffsets(stats.fixedFrameOffsets.map((row) => row.offset))],
          ["variable frame offset ranges", collapseOffsets(stats.variableFrameOffsets.map((row) => row.offset))],
          ["fixed body offset ranges", collapseOffsets(stats.fixedBodyOffsets.map((row) => row.offsetInBody))],
          ["variable body offset ranges", collapseOffsets(stats.variableBodyOffsets.map((row) => row.offsetInBody))],
        ],
      ),
    );
  }

  lines.push("## 8. Variable Fields");
  lines.push("");
  lines.push(
    table(
      ["scope", "offset ranges"],
      [
        ["frame offsets variable/missing across config classes", analysis.variableFields.variableFrameOffsetRangesAcrossConfigFrames],
        ["body offsets variable/missing across config classes", analysis.variableFields.variableBodyOffsetRangesAcrossConfigFrames],
      ],
    ),
  );

  lines.push("## 9. Preliminary Field Boundaries");
  lines.push("");
  lines.push(
    table(
      ["name", "offset", "status", "evidence"],
      analysis.inferredBoundaries.map((row) => [row.name, row.offset, row.status, row.evidence]),
    ),
  );

  lines.push("## 10. Per-Frame Structured URI Fields");
  lines.push("");
  lines.push(
    table(
      [
        "frameClass",
        "seqLE",
        "totalLength",
        "declaredPayloadLength",
        "udpUris",
        "ftpUris",
        "ipAddresses",
        "ports",
        "usernameCandidates",
        "passwordCandidates",
        "usesDhcpPlaceholder",
        "usesExplicitIp",
      ],
      analysis.configFrames.slice(0, 80).map((record) => [
        record.frameClass,
        record.seqLE,
        record.totalLength,
        record.declaredPayloadLength,
        record.udpUris.join("<br>"),
        record.ftpUris.join("<br>"),
        record.ipAddresses.join(", "),
        record.ports.join(", "),
        record.usernameCandidates.join(", "),
        record.passwordCandidates.join(", "),
        record.usesDhcpPlaceholder,
        record.usesExplicitIp,
      ]),
    ),
  );
  lines.push("Only first 80 per-frame rows are shown in Markdown; JSON contains every long config frame.");
  lines.push("");

  lines.push("## 11. Next Steps");
  lines.push("");
  lines.push("- Validate whether URI preceding bytes are length fields across additional captures.");
  lines.push("- Compare the leading ASCII/zero-terminated identifiers across firmware versions or device states.");
  lines.push("- Keep long config parsing optional/read-only until more field meanings are confirmed.");
  lines.push("");

  return `${lines.join("\n")}\n`;
}

function main() {
  const inputPath = path.resolve(process.argv[2] || DEFAULT_INPUT);
  const dateStem = parseDateStem(inputPath);
  const outputDir = path.dirname(inputPath);
  const mdPath = path.join(outputDir, `config-frame-analysis-${dateStem}.md`);
  const jsonPath = path.join(outputDir, `config-frame-analysis-${dateStem}.json`);
  const { packets, errors } = readPackets(inputPath);
  const records = [];

  for (const packet of packets) {
    if (packet.protocol !== "UDP_DSC") {
      continue;
    }
    const parsed = parseFsuFrame(packet.rawHex, {
      protocol: packet.protocol,
      includePayloadHex: false,
      includeAscii: true,
    });
    if (!CONFIG_CLASSES.has(parsed.frameClass)) {
      continue;
    }
    records.push({ ...configRecord(packet, parsed), __rawHex: packet.rawHex });
  }

  const analysis = createAnalysis(records, errors);
  fs.writeFileSync(jsonPath, JSON.stringify(analysis, null, 2), "utf8");
  fs.writeFileSync(mdPath, renderMarkdown({ inputPath, jsonPath, analysis }), "utf8");
  console.log(`markdown: ${mdPath}`);
  console.log(`json: ${jsonPath}`);
  console.log(`DSC_CONFIG_209: ${analysis.counts.dscConfig209}`);
  console.log(`DSC_CONFIG_245: ${analysis.counts.dscConfig245}`);
}

main();
