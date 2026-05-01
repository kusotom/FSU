#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const DEFAULT_FIXTURE_DIR = path.join(__dirname, "..", "fixtures", "fsu");
const DEFAULT_REPORT_PATH = path.join(
  __dirname,
  "..",
  "logs",
  "fsu_raw_packets",
  "frame-analysis-2026-04-28.md",
);

const fixtureDir = path.resolve(process.argv[2] || DEFAULT_FIXTURE_DIR);
const reportPath = path.resolve(process.argv[3] || DEFAULT_REPORT_PATH);

function fail(message) {
  console.error(message);
  process.exit(1);
}

function cleanHex(rawHex) {
  return String(rawHex || "").replace(/[^0-9a-f]/gi, "").toLowerCase();
}

function hexToBuffer(rawHex) {
  const hex = cleanHex(rawHex);
  if (!hex || hex.length % 2 !== 0) {
    return Buffer.alloc(0);
  }
  return Buffer.from(hex, "hex");
}

function escapeCell(value) {
  return String(value ?? "").replace(/\r?\n/g, "<br>").replace(/\|/g, "\\|");
}

function table(headers, rows) {
  return [
    `| ${headers.map(escapeCell).join(" | ")} |`,
    `| ${headers.map(() => "---").join(" | ")} |`,
    ...rows.map((row) => `| ${row.map(escapeCell).join(" | ")} |`),
    "",
  ].join("\n");
}

function countMapInc(map, key, amount = 1) {
  const normalized = key === undefined || key === null || key === "" ? "(empty)" : String(key);
  map.set(normalized, (map.get(normalized) || 0) + amount);
}

function topEntries(map, limit = 20) {
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .slice(0, limit);
}

function topValues(map, limit = 8) {
  return topEntries(map, limit)
    .map(([value, count]) => `${value}:${count}`)
    .join(", ");
}

function printableSpans(buf, minLen = 4) {
  const spans = [];
  let start = -1;
  for (let i = 0; i <= buf.length; i += 1) {
    const byte = i < buf.length ? buf[i] : -1;
    const printable = byte >= 0x20 && byte <= 0x7e;
    if (printable && start < 0) {
      start = i;
    }
    if ((!printable || i === buf.length) && start >= 0) {
      if (i - start >= minLen) {
        spans.push({ start, end: i, text: buf.subarray(start, i).toString("ascii") });
      }
      start = -1;
    }
  }
  return spans;
}

function collapseRanges(offsets) {
  if (!offsets.length) {
    return "(none)";
  }
  const ranges = [];
  let start = offsets[0];
  let prev = offsets[0];
  for (const offset of offsets.slice(1)) {
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

function readUInt16(buf, offset, endian) {
  if (offset < 0 || offset + 1 >= buf.length) {
    return null;
  }
  return endian === "le" ? buf.readUInt16LE(offset) : buf.readUInt16BE(offset);
}

function byteHex(buf, offset) {
  if (offset < 0 || offset >= buf.length) {
    return "--";
  }
  return buf[offset].toString(16).padStart(2, "0");
}

function analyzeBytePositions(records) {
  const maxLength = Math.max(0, ...records.map((record) => record.buf.length));
  const rows = [];
  for (let offset = 0; offset < maxLength; offset += 1) {
    const values = new Map();
    for (const record of records) {
      countMapInc(values, byteHex(record.buf, offset));
    }
    const entries = [...values.keys()];
    const fixed = entries.length === 1;
    rows.push({
      offset,
      fixed,
      valueHex: fixed ? entries[0] : "",
      distinctCount: entries.length,
      topValues: topValues(values),
    });
  }
  return rows;
}

function monotonicSummary(values) {
  const present = values.filter((value) => value !== null);
  if (present.length !== values.length || present.length < 2) {
    return "insufficient";
  }
  const deltas = [];
  let nonDecreasing = true;
  let strictlyIncreasing = true;
  for (let i = 1; i < present.length; i += 1) {
    const delta = present[i] - present[i - 1];
    deltas.push(delta);
    if (delta < 0) {
      nonDecreasing = false;
    }
    if (delta <= 0) {
      strictlyIncreasing = false;
    }
  }
  if (strictlyIncreasing) {
    return "strictly increasing";
  }
  if (nonDecreasing) {
    return "non-decreasing";
  }
  return `not monotonic; deltas=${topEntries(deltas.reduce((m, d) => {
    countMapInc(m, d);
    return m;
  }, new Map()), 5).map(([delta, count]) => `${delta}:${count}`).join(", ")}`;
}

function analyzeCandidateIntegers(records) {
  const specs = [
    { name: "bytes[2..3] little endian", get: (buf) => readUInt16(buf, 2, "le") },
    { name: "bytes[2..3] big endian", get: (buf) => readUInt16(buf, 2, "be") },
    { name: "bytes[4..5] little endian", get: (buf) => readUInt16(buf, 4, "le") },
    { name: "bytes[4..5] big endian", get: (buf) => readUInt16(buf, 4, "be") },
    { name: "last 2 bytes little endian", get: (buf) => readUInt16(buf, buf.length - 2, "le") },
    { name: "last 2 bytes big endian", get: (buf) => readUInt16(buf, buf.length - 2, "be") },
  ];

  return specs.map((spec) => {
    const values = records.map((record) => spec.get(record.buf));
    const present = values.filter((value) => value !== null);
    const distinct = new Map();
    for (const value of values) {
      countMapInc(distinct, value === null ? "(missing)" : value);
    }
    return {
      field: spec.name,
      first: present.length ? present[0] : "",
      last: present.length ? present[present.length - 1] : "",
      min: present.length ? Math.min(...present) : "",
      max: present.length ? Math.max(...present) : "",
      distinctCount: distinct.size,
      monotonic: monotonicSummary(values),
      topValues: topValues(distinct, 8),
    };
  });
}

function asciiFindings(records) {
  const spanCounts = new Map();
  const tokenCounts = new Map();
  const spanRows = [];

  for (const record of records) {
    const payloadBuf = hexToBuffer(record.frame.candidatePayload);
    for (const span of printableSpans(payloadBuf, 4)) {
      countMapInc(spanCounts, span.text);
      spanRows.push({
        sample: record.sampleId,
        offset: span.start + 8,
        text: span.text,
      });
    }

    const printable = [...payloadBuf]
      .map((byte) => (byte >= 0x20 && byte <= 0x7e ? String.fromCharCode(byte) : "."))
      .join("");
    const tokenRegexes = [
      /udp:\/\/[^\s.]+(?:\.[^\s.]+)*/gi,
      /ftp:\/\/[^\s.]+(?:\.[^\s.]+)*/gi,
      /\b\d{1,3}(?:\.\d{1,3}){3}\b/g,
      /:\d{2,5}\b/g,
      /root/gi,
      /hello/gi,
      /dhcp/gi,
    ];
    for (const regex of tokenRegexes) {
      const matches = printable.match(regex) || [];
      for (const match of matches) {
        countMapInc(tokenCounts, match);
      }
    }
  }

  return { spanCounts, tokenCounts, spanRows };
}

function loadFixtures(dir) {
  if (!fs.existsSync(dir)) {
    fail(`fixture dir not found: ${dir}`);
  }
  const files = fs
    .readdirSync(dir)
    .filter((file) => file.endsWith(".json"))
    .sort();

  return files.map((file) => {
    const filePath = path.join(dir, file);
    const samples = JSON.parse(fs.readFileSync(filePath, "utf8"));
    if (!Array.isArray(samples)) {
      fail(`fixture must be an array: ${filePath}`);
    }
    return { file, filePath, samples };
  });
}

function analyzeFixtureGroup(group) {
  const records = group.samples.map((sample, index) => {
    const buf = hexToBuffer(sample.rawHex);
    return {
      sample,
      sampleId: `s${String(index + 1).padStart(2, "0")}`,
      buf,
      frame: parseFsuFrame(buf, { protocol: sample.protocol }),
    };
  });

  const classCounts = new Map();
  const typeCounts = new Map();
  const tail2Counts = new Map();
  const tail4Counts = new Map();
  for (const record of records) {
    countMapInc(classCounts, record.frame.className);
    countMapInc(typeCounts, record.frame.candidateTypeA);
    countMapInc(tail2Counts, record.frame.tail2);
    countMapInc(tail4Counts, record.frame.tail4);
  }

  const byteStats = analyzeBytePositions(records);
  const candidateInts = analyzeCandidateIntegers(records);
  const ascii = asciiFindings(records);
  const variableOffsets = byteStats.filter((row) => !row.fixed).map((row) => row.offset);
  const fixedOffsets = byteStats.filter((row) => row.fixed).map((row) => row.offset);

  return {
    ...group,
    records,
    classCounts,
    typeCounts,
    tail2Counts,
    tail4Counts,
    byteStats,
    candidateInts,
    ascii,
    fixedOffsets,
    variableOffsets,
  };
}

function renderGroup(group) {
  const lines = [];
  const lengths = [...new Set(group.samples.map((sample) => sample.length))].join(", ");
  const protocols = [...new Set(group.samples.map((sample) => sample.protocol))].join(", ");

  lines.push(`## ${group.file}`);
  lines.push("");
  lines.push(
    table(
      ["metric", "value"],
      [
        ["fixture count", group.samples.length],
        ["protocol", protocols],
        ["length", lengths],
        ["fixed offsets", collapseRanges(group.fixedOffsets)],
        ["variable offsets", collapseRanges(group.variableOffsets)],
      ],
    ),
  );

  lines.push("### ClassName Counts");
  lines.push("");
  lines.push(table(["className", "count"], topEntries(group.classCounts).map(([key, count]) => [key, count])));

  lines.push("### Candidate Sequence / Integer Observations");
  lines.push("");
  lines.push(
    table(
      ["field", "first", "last", "min", "max", "distinctCount", "monotonic", "topValues"],
      group.candidateInts.map((row) => [
        row.field,
        row.first,
        row.last,
        row.min,
        row.max,
        row.distinctCount,
        row.monotonic,
        row.topValues,
      ]),
    ),
  );

  lines.push("### Candidate Type And Tail Distribution");
  lines.push("");
  lines.push(table(["candidateTypeA", "count"], topEntries(group.typeCounts).map(([key, count]) => [key, count])));
  lines.push(table(["tail2", "count"], topEntries(group.tail2Counts).map(([key, count]) => [key, count])));
  lines.push(table(["tail4", "count"], topEntries(group.tail4Counts).map(([key, count]) => [key, count])));

  lines.push("### Payload ASCII Findings");
  lines.push("");
  lines.push("Top printable spans:");
  lines.push("");
  lines.push(table(["text", "count"], topEntries(group.ascii.spanCounts, 30).map(([key, count]) => [key, count])));
  lines.push("Token hits:");
  lines.push("");
  lines.push(table(["token", "count"], topEntries(group.ascii.tokenCounts, 30).map(([key, count]) => [key, count])));
  lines.push("Span locations:");
  lines.push("");
  lines.push(
    table(
      ["sample", "offset", "text"],
      group.ascii.spanRows.slice(0, 80).map((row) => [row.sample, row.offset, row.text]),
    ),
  );

  lines.push("### Byte Position Statistics");
  lines.push("");
  lines.push(
    table(
      ["offset", "fixed", "valueHex", "distinctCount", "topValues"],
      group.byteStats.map((row) => [
        row.offset,
        row.fixed ? "true" : "false",
        row.valueHex,
        row.distinctCount,
        row.topValues,
      ]),
    ),
  );

  lines.push("### Per-Sample Byte Difference Matrix");
  lines.push("");
  if (!group.variableOffsets.length) {
    lines.push("(no variable offsets)");
    lines.push("");
  } else {
    const headers = ["offset", ...group.records.map((record) => record.sampleId)];
    const rows = group.variableOffsets.map((offset) => [
      offset,
      ...group.records.map((record) => byteHex(record.buf, offset)),
    ]);
    lines.push(table(headers, rows));
  }

  return lines.join("\n");
}

function main() {
  const groups = loadFixtures(fixtureDir).map(analyzeFixtureGroup);
  const overallClassCounts = new Map();
  for (const group of groups) {
    for (const [className, count] of group.classCounts.entries()) {
      countMapInc(overallClassCounts, className, count);
    }
  }

  const lines = [];
  lines.push("# FSU Offline Frame Fixture Analysis - 2026-04-28");
  lines.push("");
  lines.push(`Fixture dir: \`${fixtureDir}\``);
  lines.push(`Generated at: \`${new Date().toISOString()}\``);
  lines.push("");
  lines.push("## Fixture Counts");
  lines.push("");
  lines.push(
    table(
      ["fixture", "count", "protocol", "length"],
      groups.map((group) => [
        group.file,
        group.samples.length,
        [...new Set(group.samples.map((sample) => sample.protocol))].join(", "),
        [...new Set(group.samples.map((sample) => sample.length))].join(", "),
      ]),
    ),
  );
  lines.push("## Overall ClassName Counts");
  lines.push("");
  lines.push(table(["className", "count"], topEntries(overallClassCounts).map(([key, count]) => [key, count])));
  lines.push("");
  lines.push(groups.map(renderGroup).join("\n"));

  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, `${lines.join("\n")}\n`, "utf8");
  console.log(`report: ${reportPath}`);
}

main();
