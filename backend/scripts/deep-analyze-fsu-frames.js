#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const DEFAULT_FIXTURE_DIR = path.join(__dirname, "..", "fixtures", "fsu");
const DEFAULT_RAW_LOG_PATH = path.join(__dirname, "..", "logs", "fsu_raw_packets", "2026-04-28.jsonl");
const DEFAULT_REPORT_PATH = path.join(
  __dirname,
  "..",
  "logs",
  "fsu_raw_packets",
  "deep-frame-analysis-2026-04-28.md",
);

const LENGTH_FIELDS = [
  { label: "bytes[4..5] LE", offset: 4, endian: "le" },
  { label: "bytes[4..5] BE", offset: 4, endian: "be" },
  { label: "bytes[6..7] LE", offset: 6, endian: "le" },
  { label: "bytes[6..7] BE", offset: 6, endian: "be" },
  { label: "bytes[8..9] LE", offset: 8, endian: "le" },
  { label: "bytes[8..9] BE", offset: 8, endian: "be" },
  { label: "bytes[20..21] LE", offset: 20, endian: "le" },
  { label: "bytes[20..21] BE", offset: 20, endian: "be" },
  { label: "bytes[22..23] LE", offset: 22, endian: "le" },
  { label: "bytes[22..23] BE", offset: 22, endian: "be" },
];

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

function hexSlice(buf, start, end) {
  if (start >= buf.length) {
    return "";
  }
  return buf.subarray(start, Math.min(end, buf.length)).toString("hex");
}

function byteHex(buf, offset) {
  return offset >= 0 && offset < buf.length ? buf[offset].toString(16).padStart(2, "0") : "";
}

function readUInt16(buf, offset, endian) {
  if (offset < 0 || offset + 1 >= buf.length) {
    return null;
  }
  return endian === "le" ? buf.readUInt16LE(offset) : buf.readUInt16BE(offset);
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
  const normalized = key === null || key === undefined || key === "" ? "(empty)" : String(key);
  map.set(normalized, (map.get(normalized) || 0) + amount);
}

function topEntries(map, limit = 20) {
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .slice(0, limit);
}

function valueSummary(values, limit = 8) {
  const counts = new Map();
  for (const value of values) {
    countMapInc(counts, value === null ? "(missing)" : value);
  }
  return topEntries(counts, limit)
    .map(([value, count]) => `${value}:${count}`)
    .join(", ");
}

function classifyFrame({ protocol, totalLength, typeA }) {
  if (protocol === "UDP_DSC" && totalLength === 24 && typeA === "1f00d2ff") {
    return "DSC_LEN24";
  }
  if (protocol === "UDP_DSC" && totalLength === 209 && typeA === "110046ff") {
    return "DSC_LEN209";
  }
  if (protocol === "UDP_DSC" && totalLength === 245 && typeA === "110046ff") {
    return "DSC_LEN245";
  }
  if (protocol === "UDP_RDS" && totalLength === 30 && typeA === "1180d2ff") {
    return "RDS_LEN30";
  }
  return `${protocol || "UNKNOWN"}_LEN${totalLength}_TYPE_${typeA || "missing"}`;
}

function frameFields(buf) {
  return {
    totalLength: buf.length,
    header: hexSlice(buf, 0, 2),
    seqLE: readUInt16(buf, 2, "le"),
    seqBE: readUInt16(buf, 2, "be"),
    typeA: hexSlice(buf, 4, 8),
    fixedPartHex: hexSlice(buf, 0, 22),
    byte22: byteHex(buf, 22),
    byte23: byteHex(buf, 23),
    payloadFrom8: hexSlice(buf, 8, buf.length),
    payloadFrom22: hexSlice(buf, 22, buf.length),
    tail2: buf.length >= 2 ? hexSlice(buf, buf.length - 2, buf.length) : "",
    tail4: buf.length >= 4 ? hexSlice(buf, buf.length - 4, buf.length) : "",
  };
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
        spans.push({ offsetStart: start, offsetEnd: i - 1, text: buf.subarray(start, i).toString("ascii") });
      }
      start = -1;
    }
  }
  return spans;
}

function visibleAscii(buf) {
  return [...buf]
    .map((byte) => (byte >= 0x20 && byte <= 0x7e ? String.fromCharCode(byte) : "."))
    .join("");
}

function firstPrintableOffset(buf, start = 0) {
  for (let i = start; i < buf.length; i += 1) {
    if (buf[i] >= 0x20 && buf[i] <= 0x7e) {
      return i;
    }
  }
  return -1;
}

function firstUriOffset(buf) {
  const text = buf.toString("latin1");
  const candidates = ["udp://", "ftp://"];
  let best = -1;
  for (const token of candidates) {
    const offset = text.indexOf(token);
    if (offset >= 0 && (best < 0 || offset < best)) {
      best = offset;
    }
  }
  return best;
}

function extractUrisAndNetwork(text) {
  return {
    uris: text.match(/\b(?:udp|ftp):\/\/[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]+/g) || [],
    ips: text.match(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g) || [],
    ports: text.match(/(?::|^)(6000|6002)\b/g)?.map((value) => value.replace(/^:/, "")) || [],
  };
}

function asciiAnalysis(records) {
  const allRows = [];
  const spanKeyCounts = new Map();
  const uriCounts = new Map();
  const uriSequenceCounts = new Map();
  const ipCounts = new Map();
  const portCounts = new Map();
  const offsetCounts = new Map();
  const payloadCOffsets = [];
  const firstUriOffsets = [];

  for (const record of records) {
    const spans = printableSpans(record.buf, 4);
    const recordUris = [];
    for (const span of spans) {
      allRows.push([record.sampleId, span.offsetStart, span.offsetEnd, span.text]);
      countMapInc(spanKeyCounts, `${span.offsetStart}-${span.offsetEnd} ${span.text}`);
      countMapInc(offsetCounts, `${span.offsetStart}-${span.offsetEnd}`);

      const found = extractUrisAndNetwork(span.text);
      for (const uri of found.uris) {
        recordUris.push(uri);
        countMapInc(uriCounts, uri);
      }
      for (const ip of found.ips) {
        countMapInc(ipCounts, ip);
      }
      for (const port of found.ports) {
        countMapInc(portCounts, port);
      }
    }
    countMapInc(uriSequenceCounts, recordUris.length ? recordUris.join(" | ") : "(none)");

    payloadCOffsets.push(firstPrintableOffset(record.buf, 8));
    firstUriOffsets.push(firstUriOffset(record.buf));
  }

  return {
    allRows,
    spanKeyCounts,
    uriCounts,
    uriSequenceCounts,
    ipCounts,
    portCounts,
    offsetCounts,
    payloadCOffsets,
    firstUriOffsets,
  };
}

function lengthCandidateRows(records) {
  const classFixed = new Map();
  for (const spec of LENGTH_FIELDS) {
    const values = records.map((record) => readUInt16(record.buf, spec.offset, spec.endian));
    const present = values.filter((value) => value !== null);
    classFixed.set(spec.label, present.length > 0 && new Set(present).size === 1);
  }

  const rows = [];
  for (const record of records) {
    const payloadLength = Math.max(0, record.buf.length - 22);
    for (const spec of LENGTH_FIELDS) {
      const value = readUInt16(record.buf, spec.offset, spec.endian);
      rows.push([
        record.sampleId,
        spec.label,
        value === null ? "(missing)" : value,
        value === record.buf.length ? "yes" : "no",
        value === record.buf.length - 2 ? "yes" : "no",
        value === record.buf.length - 4 ? "yes" : "no",
        value === record.buf.length - 24 ? "yes" : "no",
        value === payloadLength ? "yes" : "no",
        value === payloadLength - 2 ? "yes" : "no",
        classFixed.get(spec.label) ? "yes" : "no",
      ]);
    }
  }
  return rows;
}

function lengthCandidateSummary(groups) {
  const rows = [];
  for (const group of groups) {
    for (const spec of LENGTH_FIELDS) {
      const values = group.records.map((record) => readUInt16(record.buf, spec.offset, spec.endian));
      const present = values.filter((value) => value !== null);
      const fixed = present.length > 0 && new Set(present).size === 1;
      let total = 0;
      let totalMinus2 = 0;
      let totalMinus4 = 0;
      let totalMinus24 = 0;
      let payload = 0;
      let payloadMinus2 = 0;
      for (const [index, record] of group.records.entries()) {
        const value = values[index];
        const payloadLength = Math.max(0, record.buf.length - 22);
        if (value === record.buf.length) total += 1;
        if (value === record.buf.length - 2) totalMinus2 += 1;
        if (value === record.buf.length - 4) totalMinus4 += 1;
        if (value === record.buf.length - 24) totalMinus24 += 1;
        if (value === payloadLength) payload += 1;
        if (value === payloadLength - 2) payloadMinus2 += 1;
      }
      rows.push([
        group.className,
        spec.label,
        valueSummary(values),
        `${total}/${group.records.length}`,
        `${totalMinus2}/${group.records.length}`,
        `${totalMinus4}/${group.records.length}`,
        `${totalMinus24}/${group.records.length}`,
        `${payload}/${group.records.length}`,
        `${payloadMinus2}/${group.records.length}`,
        fixed ? "yes" : "no",
      ]);
    }
  }
  return rows;
}

function sequenceAnalysis(records) {
  const sorted = [...records].sort((a, b) => String(a.receivedAt).localeCompare(String(b.receivedAt)));
  const seqs = sorted.map((record) => record.fields.seqLE);
  const deltas = [];
  const jumps = [];
  for (let i = 1; i < seqs.length; i += 1) {
    const delta = seqs[i] - seqs[i - 1];
    deltas.push(delta);
    if (delta !== 1) {
      jumps.push(`${sorted[i - 1].sampleId}->${sorted[i].sampleId}:${seqs[i - 1]}->${seqs[i]} (delta ${delta})`);
    }
  }
  return {
    sorted,
    seqs,
    deltas,
    continuousPlusOne: deltas.length > 0 && deltas.every((delta) => delta === 1),
    jumps,
  };
}

function sumBytes(buf) {
  let sum = 0;
  for (const byte of buf) {
    sum += byte;
  }
  return sum;
}

function xorBytes(buf) {
  let out = 0;
  for (const byte of buf) {
    out ^= byte;
  }
  return out;
}

function crc16Modbus(buf) {
  let crc = 0xffff;
  for (const byte of buf) {
    crc ^= byte;
    for (let i = 0; i < 8; i += 1) {
      if (crc & 1) {
        crc = (crc >>> 1) ^ 0xa001;
      } else {
        crc >>>= 1;
      }
    }
  }
  return crc & 0xffff;
}

function crc16CcittFalse(buf) {
  let crc = 0xffff;
  for (const byte of buf) {
    crc ^= byte << 8;
    for (let i = 0; i < 8; i += 1) {
      crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) : crc << 1;
      crc &= 0xffff;
    }
  }
  return crc & 0xffff;
}

function checksumTargets(buf, tailSize) {
  const tail = buf.subarray(buf.length - tailSize);
  const targets = [];
  if (tailSize >= 1) {
    targets.push({ label: `tail${tailSize}.last8`, width: 8, value: tail[tail.length - 1] });
  }
  if (tailSize >= 2) {
    const last2 = tail.subarray(tail.length - 2);
    targets.push({ label: `tail${tailSize}.last2LE`, width: 16, value: last2.readUInt16LE(0) });
    targets.push({ label: `tail${tailSize}.last2BE`, width: 16, value: last2.readUInt16BE(0) });
  }
  if (tailSize >= 4) {
    const first2 = tail.subarray(0, 2);
    targets.push({ label: "tail4.first2LE", width: 16, value: first2.readUInt16LE(0) });
    targets.push({ label: "tail4.first2BE", width: 16, value: first2.readUInt16BE(0) });
    targets.push({ label: "tail4.LE32_low16", width: 16, value: tail.readUInt32LE(0) & 0xffff });
    targets.push({ label: "tail4.BE32_low16", width: 16, value: tail.readUInt32BE(0) & 0xffff });
  }
  return targets;
}

function checksumAnalysis(records) {
  const candidates = new Map();

  for (const record of records) {
    for (const tailSize of [1, 2, 4]) {
      if (record.buf.length <= tailSize) {
        continue;
      }
      const body = record.buf.subarray(0, record.buf.length - tailSize);
      const values = [
        { label: `drop${tailSize}:sum8`, width: 8, value: sumBytes(body) & 0xff },
        { label: `drop${tailSize}:xor8`, width: 8, value: xorBytes(body) & 0xff },
        { label: `drop${tailSize}:sum16`, width: 16, value: sumBytes(body) & 0xffff },
        { label: `drop${tailSize}:crc16_modbus`, width: 16, value: crc16Modbus(body) },
        { label: `drop${tailSize}:crc16_ccitt_false`, width: 16, value: crc16CcittFalse(body) },
      ];
      const targets = checksumTargets(record.buf, tailSize);
      for (const calc of values) {
        for (const target of targets) {
          if (calc.width !== target.width) {
            continue;
          }
          const key = `${calc.label} == ${target.label}`;
          if (!candidates.has(key)) {
            candidates.set(key, { label: key, hits: 0, total: 0, examples: [] });
          }
          const candidate = candidates.get(key);
          candidate.total += 1;
          if (calc.value === target.value) {
            candidate.hits += 1;
            if (candidate.examples.length < 5) {
              candidate.examples.push(`${record.sampleId}:${calc.value.toString(16)}`);
            }
          }
        }
      }
    }
  }

  return [...candidates.values()].sort((a, b) => b.hits / b.total - a.hits / a.total || b.hits - a.hits);
}

function payloadView(buf, start) {
  if (start < 0 || start >= buf.length) {
    return { offset: start, length: 0, hexPrefix: "", ascii: "" };
  }
  const payload = buf.subarray(start);
  return {
    offset: start,
    length: payload.length,
    hexPrefix: payload.subarray(0, 48).toString("hex"),
    ascii: visibleAscii(payload).slice(0, 260),
  };
}

function payloadBoundaryRows(records) {
  const rows = [];
  for (const record of records.slice(0, 8)) {
    const cOffset = firstPrintableOffset(record.buf, 8);
    const views = [
      ["payloadA bytes[8..end]", payloadView(record.buf, 8)],
      ["payloadB bytes[22..end]", payloadView(record.buf, 22)],
      ["payloadC first printable..end", payloadView(record.buf, cOffset)],
      ["first URI..end", payloadView(record.buf, firstUriOffset(record.buf))],
    ];
    for (const [name, view] of views) {
      rows.push([record.sampleId, name, view.offset, view.length, view.hexPrefix, view.ascii]);
    }
  }
  return rows;
}

function loadFixtures(dir) {
  if (!fs.existsSync(dir)) {
    fail(`fixture dir not found: ${dir}`);
  }
  return fs
    .readdirSync(dir)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => {
      const filePath = path.join(dir, file);
      const samples = JSON.parse(fs.readFileSync(filePath, "utf8"));
      if (!Array.isArray(samples)) {
        fail(`fixture must be an array: ${filePath}`);
      }
      return { file, filePath, samples };
    });
}

function makeRecord(sample, sampleId, sourceFile) {
  const buf = hexToBuffer(sample.rawHex);
  const fields = frameFields(buf);
  const className = classifyFrame({
    protocol: sample.protocol,
    totalLength: fields.totalLength,
    typeA: fields.typeA,
  });
  return {
    sourceFile,
    sampleId,
    sample,
    buf,
    fields,
    className,
    protocol: sample.protocol,
    length: sample.length ?? fields.totalLength,
    receivedAt: sample.receivedAt || sample.createdAt || "",
  };
}

function analyzeFixtureFile(group) {
  const records = group.samples.map((sample, index) => makeRecord(sample, `s${String(index + 1).padStart(2, "0")}`, group.file));
  const className = records[0]?.className || group.file.replace(/\.json$/i, "");
  const seq = sequenceAnalysis(records);
  const checksum = checksumAnalysis(records);
  const ascii = asciiAnalysis(records);
  return { ...group, records, className, seq, checksum, ascii };
}

function loadRawLog(rawLogPath) {
  if (!fs.existsSync(rawLogPath)) {
    return [];
  }
  const lines = fs.readFileSync(rawLogPath, "utf8").split(/\r?\n/).filter(Boolean);
  const records = [];
  for (const [index, line] of lines.entries()) {
    try {
      const sample = JSON.parse(line);
      if (sample.protocol === "UDP_DSC" || sample.protocol === "UDP_RDS") {
        records.push(makeRecord(sample, `raw${String(index + 1).padStart(6, "0")}`, path.basename(rawLogPath)));
      }
    } catch {
      // Keep the analysis script tolerant of partial append writes.
    }
  }
  return records;
}

function rawLogSequenceGroups(groups, rawRecords) {
  const rows = [];
  const details = new Map();
  for (const group of groups) {
    const ref = group.records[0];
    if (!ref) {
      continue;
    }
    const matches = rawRecords
      .filter(
        (record) =>
          record.protocol === ref.protocol &&
          record.fields.totalLength === ref.fields.totalLength &&
          record.fields.typeA === ref.fields.typeA,
      )
      .sort((a, b) => String(a.receivedAt).localeCompare(String(b.receivedAt)))
      .slice(-200);
    if (!matches.length) {
      rows.push([group.className, 0, "(none)", "(none)", "no raw-log matches"]);
      continue;
    }
    const seq = sequenceAnalysis(matches);
    rows.push([
      group.className,
      matches.length,
      `${seq.seqs[0]}..${seq.seqs[seq.seqs.length - 1]}`,
      seq.deltas.length ? valueSummary(seq.deltas) : "(none)",
      seq.continuousPlusOne ? "yes" : "no",
    ]);
    details.set(group.className, seq.sorted.map((record) => [record.receivedAt, record.fields.seqLE, record.fields.typeA, record.fields.totalLength]));
  }
  return { rows, details };
}

function renderFieldTable(group) {
  return table(
    [
      "sample",
      "header",
      "seqLE",
      "seqBE",
      "typeA",
      "fixedPartHex bytes[0..21]",
      "byte22",
      "byte23",
      "payloadFrom8",
      "payloadFrom22",
      "tail2",
      "tail4",
    ],
    group.records.slice(0, 20).map((record) => [
      record.sampleId,
      record.fields.header,
      record.fields.seqLE,
      record.fields.seqBE,
      record.fields.typeA,
      record.fields.fixedPartHex,
      record.fields.byte22,
      record.fields.byte23,
      record.fields.payloadFrom8,
      record.fields.payloadFrom22,
      record.fields.tail2,
      record.fields.tail4,
    ]),
  );
}

function renderSequence(group) {
  const seq = group.seq;
  return [
    `### ${group.className}`,
    "",
    table(
      ["metric", "value"],
      [
        ["seqLE list", seq.seqs.join(", ")],
        ["adjacent deltas", seq.deltas.join(", ") || "(none)"],
        ["continuous +1", seq.continuousPlusOne ? "yes" : "no"],
        ["jumps", seq.jumps.length ? seq.jumps.join("; ") : "(none)"],
      ],
    ),
    table(
      ["receivedAt", "sample", "seqLE"],
      seq.sorted.map((record) => [record.receivedAt, record.sampleId, record.fields.seqLE]),
    ),
  ].join("\n");
}

function renderChecksum(group) {
  const rows = group.checksum.slice(0, 20).map((candidate) => [
    candidate.label,
    `${candidate.hits}/${candidate.total}`,
    `${((candidate.hits / candidate.total) * 100).toFixed(1)}%`,
    candidate.examples.join(", ") || "(none)",
  ]);
  const best = group.checksum[0];
  return [
    `### ${group.className}`,
    "",
    table(
      ["metric", "value"],
      [
        ["highest hit candidate", best ? best.label : "(none)"],
        ["highest hit rate", best ? `${best.hits}/${best.total} (${((best.hits / best.total) * 100).toFixed(1)}%)` : "(none)"],
        ["simple checksum conclusion", best && best.hits === best.total ? "full-match candidate observed; still not treated as protocol until broader validation" : "no obvious simple checksum full match found"],
      ],
    ),
    table(["candidate", "hits", "hitRate", "examples"], rows),
  ].join("\n");
}

function renderAsciiSection(group) {
  const ascii = group.ascii;
  return [
    `### ${group.className}`,
    "",
    table(
      ["metric", "value"],
      [
        ["printable span offsets", topEntries(ascii.offsetCounts, 12).map(([value, count]) => `${value}:${count}`).join(", ")],
        ["payloadC first-printable offsets after byte 8", valueSummary(ascii.payloadCOffsets)],
        ["first URI offsets", valueSummary(ascii.firstUriOffsets)],
      ],
    ),
    "URI sequence per sample:",
    "",
    table(["uri sequence", "count"], topEntries(ascii.uriSequenceCounts, 20).map(([value, count]) => [value, count])),
    "URI hits:",
    "",
    table(["uri", "count"], topEntries(ascii.uriCounts, 30).map(([value, count]) => [value, count])),
    "IP hits:",
    "",
    table(["ip", "count"], topEntries(ascii.ipCounts, 30).map(([value, count]) => [value, count])),
    "Port hits:",
    "",
    table(["port", "count"], topEntries(ascii.portCounts, 30).map(([value, count]) => [value, count])),
    "Printable ASCII spans (first 120 rows):",
    "",
    table(["sample", "offsetStart", "offsetEnd", "text"], ascii.allRows.slice(0, 120)),
    "Stable span signatures:",
    "",
    table(["offset/text", "count"], topEntries(ascii.spanKeyCounts, 40).map(([value, count]) => [value, count])),
  ].join("\n");
}

function renderPayloadBoundary(group) {
  const uriOffsets = group.ascii.firstUriOffsets.filter((offset) => offset >= 0);
  const likely = uriOffsets.length ? valueSummary(uriOffsets) : "(no URI offset)";
  return [
    `### ${group.className}`,
    "",
    table(
      ["metric", "value"],
      [
        ["payloadA", "bytes[8..end] includes binary fields before text"],
        ["payloadB", "bytes[22..end] removes fixedPartHex but can still include non-printable bytes before ASCII"],
        ["payloadC", "first printable byte can start inside binary metadata if a binary byte happens to be printable"],
        ["first URI offset", likely],
      ],
    ),
    table(["sample", "view", "offset", "length", "hexPrefix", "asciiPreview"], payloadBoundaryRows(group.records)),
  ].join("\n");
}

function renderReport({ groups, fixtureDir, rawLogPath, rawLog }) {
  const lines = [];
  const generatedAt = new Date().toISOString();
  const rawSeq = rawLogSequenceGroups(groups, rawLog);
  const displayFixtureDir = path.relative(process.cwd(), fixtureDir) || ".";
  const displayRawLogPath = path.relative(process.cwd(), rawLogPath) || rawLogPath;

  lines.push("# FSU Deep Frame Analysis - 2026-04-28");
  lines.push("");
  lines.push(`Generated at: \`${generatedAt}\``);
  lines.push(`Fixture dir: \`${displayFixtureDir}\``);
  lines.push(`Raw log: \`${displayRawLogPath}\``);
  lines.push("");

  lines.push("## 1. Overview");
  lines.push("");
  lines.push(
    table(
      ["class", "fixture", "count", "protocol", "length", "header values", "typeA values", "seqLE range"],
      groups.map((group) => [
        group.className,
        group.file,
        group.records.length,
        valueSummary(group.records.map((record) => record.protocol)),
        valueSummary(group.records.map((record) => record.fields.totalLength)),
        valueSummary(group.records.map((record) => record.fields.header)),
        valueSummary(group.records.map((record) => record.fields.typeA)),
        `${Math.min(...group.records.map((record) => record.fields.seqLE))}..${Math.max(...group.records.map((record) => record.fields.seqLE))}`,
      ]),
    ),
  );

  lines.push("## 2. Four Packet Class Field Tables");
  lines.push("");
  for (const group of groups) {
    lines.push(`### ${group.className}`);
    lines.push("");
    lines.push(renderFieldTable(group));
  }

  lines.push("## 3. Sequence Validation");
  lines.push("");
  lines.push(groups.map(renderSequence).join("\n"));
  lines.push("### Raw Log Recent 200 Same-Class Packets");
  lines.push("");
  lines.push(table(["class", "raw matches used", "seqLE range", "delta distribution", "continuous +1"], rawSeq.rows));
  for (const [className, rows] of rawSeq.details.entries()) {
    lines.push(`#### ${className} raw seqLE / receivedAt`);
    lines.push("");
    lines.push(table(["receivedAt", "seqLE", "typeA", "length"], rows.slice(-80)));
  }

  lines.push("## 4. Length Field Candidates");
  lines.push("");
  lines.push("Summary by class:");
  lines.push("");
  lines.push(
    table(
      [
        "class",
        "field",
        "values",
        "equals totalLength",
        "equals totalLength-2",
        "equals totalLength-4",
        "equals totalLength-24",
        "equals payloadLength bytes[22..end]",
        "equals payloadLength-2",
        "fixed in class",
      ],
      lengthCandidateSummary(groups),
    ),
  );
  for (const group of groups) {
    lines.push(`### ${group.className} per-sample candidates`);
    lines.push("");
    lines.push(
      table(
        [
          "sample",
          "field",
          "value",
          "equals totalLength",
          "equals totalLength-2",
          "equals totalLength-4",
          "equals totalLength-24",
          "equals payloadLength bytes[22..end]",
          "equals payloadLength-2",
          "fixed in class",
        ],
        lengthCandidateRows(group.records).slice(0, 220),
      ),
    );
  }

  lines.push("## 5. Checksum Candidate Hit Rates");
  lines.push("");
  lines.push(groups.map(renderChecksum).join("\n"));

  const dsc209 = groups.find((group) => group.className === "DSC_LEN209");
  const dsc245 = groups.find((group) => group.className === "DSC_LEN245");

  lines.push("## 6. DSC 209 ASCII Extraction");
  lines.push("");
  lines.push(dsc209 ? renderAsciiSection(dsc209) : "(DSC_LEN209 fixture not found)");

  lines.push("## 7. DSC 245 ASCII Extraction");
  lines.push("");
  lines.push(dsc245 ? renderAsciiSection(dsc245) : "(DSC_LEN245 fixture not found)");

  lines.push("## 8. Payload Boundary Comparison");
  lines.push("");
  lines.push(dsc209 ? renderPayloadBoundary(dsc209) : "(DSC_LEN209 fixture not found)");
  lines.push(dsc245 ? renderPayloadBoundary(dsc245) : "(DSC_LEN245 fixture not found)");

  lines.push("## 9. Initial Conclusions");
  lines.push("");
  lines.push("- `bytes[0..1]`, `bytes[2..3]`, and `bytes[4..7]` are reported as field candidates only; no live parser behavior is changed.");
  lines.push("- Length candidate rows are statistical comparisons only. A fixed value inside one class is not treated as proof of a length field.");
  lines.push("- Extra length statistics show `bytes[20..21] LE` equals `totalLength - 24` and `payloadLength(bytes[22..end]) - 2` in all four fixture classes.");
  lines.push("- Checksum candidates are simple checksum experiments against tail bytes. DSC 209/245 tails are also shown in ASCII/payload views because they can be part of text payload.");
  lines.push("- For DSC 209/245, the first URI offset is separated from the first printable-byte offset because binary metadata can contain printable bytes before the actual URI/config text.");
  lines.push("");

  lines.push("## 10. Next Steps");
  lines.push("");
  lines.push("- Use the field tables to pick a read-only parser surface: header, seqLE, typeA, totalLength, and ASCII spans.");
  lines.push("- Keep checksum handling disabled until more packet classes show a consistent full-match checksum candidate.");
  lines.push("- For DSC 209/245, parse ASCII configuration conservatively from stable printable spans and URI offsets, not from tail assumptions.");
  lines.push("- Continue avoiding ACK generation, database writes, and live receive-path changes while parser confidence is being built.");
  lines.push("");

  return `${lines.join("\n")}\n`;
}

function main() {
  const fixtureDir = path.resolve(process.argv[2] || DEFAULT_FIXTURE_DIR);
  const reportPath = path.resolve(process.argv[3] || DEFAULT_REPORT_PATH);
  const rawLogPath = path.resolve(process.argv[4] || DEFAULT_RAW_LOG_PATH);

  const groups = loadFixtures(fixtureDir).map(analyzeFixtureFile);
  const rawLog = loadRawLog(rawLogPath);
  const report = renderReport({ groups, fixtureDir, rawLogPath, rawLog });

  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, report, "utf8");
  console.log(`report: ${reportPath}`);
}

main();
