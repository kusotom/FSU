#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../../app/modules/fsu_gateway/parser/fsu-frame-parser");

const DATE_STEM = "2026-04-28";
const DEFAULT_LOG = path.join(process.cwd(), "backend", "logs", "fsu_raw_packets", `${DATE_STEM}.jsonl`);
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");
const CHECKSUM_OFFSET = 22;

const SAMPLE_HEX = {
  sampleA: "6d7e1a001f00d2ff00000000c162002dc162002d00005a03",
  sampleB: "6d7ee2201f00d2ff00000000c162002dc162002d00004204",
};

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

function cleanHex(value) {
  return String(value || "").replace(/[^0-9a-f]/gi, "").toLowerCase();
}

function sumBytes(buf, start, endExclusive, options = {}) {
  const safeStart = Math.max(0, start);
  const safeEnd = Math.min(buf.length, Math.max(safeStart, endExclusive));
  let sum = 0;
  for (let i = safeStart; i < safeEnd; i += 1) {
    if (options.excludeChecksum && i >= CHECKSUM_OFFSET && i < CHECKSUM_OFFSET + 2) continue;
    sum = (sum + buf[i]) & 0xffff;
  }
  return sum;
}

function sumWords(buf, start, endian) {
  let sum = 0;
  for (let i = start; i + 1 < buf.length; i += 2) {
    const word = endian === "le" ? buf.readUInt16LE(i) : buf.readUInt16BE(i);
    sum = (sum + word) & 0xffff;
  }
  return sum;
}

function readU16(buf, offset, endian = "le") {
  if (offset < 0 || offset + 1 >= buf.length) return null;
  return endian === "le" ? buf.readUInt16LE(offset) : buf.readUInt16BE(offset);
}

function parsePackets(logPath) {
  const packets = [];
  const errors = [];
  fs.readFileSync(logPath, "utf8")
    .split(/\r?\n/)
    .forEach((line, index) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      try {
        const packet = JSON.parse(trimmed);
        if (packet.protocol !== "UDP_DSC" && packet.protocol !== "UDP_RDS") return;
        const hex = cleanHex(packet.rawHex);
        if (!hex || hex.length % 2 !== 0) return;
        const buf = Buffer.from(hex, "hex");
        if (buf.length < 24) return;
        const parsed = parseFsuFrame(hex, { protocol: packet.protocol, includeAscii: false });
        packets.push({ packet, parsed, buf, rawHex: hex });
      } catch (error) {
        errors.push({ line: index + 1, error: error.message });
      }
    });
  return { packets, errors };
}

function algorithmValues(buf) {
  const lengthLE = readU16(buf, 20, "le");
  const declaredTotalLen = lengthLE === null ? null : lengthLE + 24;
  const dataEnd = lengthLE === null ? null : 22 + lengthLE;
  const zeroed = Buffer.from(buf);
  if (zeroed.length >= CHECKSUM_OFFSET + 2) {
    zeroed[CHECKSUM_OFFSET] = 0;
    zeroed[CHECKSUM_OFFSET + 1] = 0;
  }

  const candidates = {
    sum8_bytes_2_to_checksum_minus1: sumBytes(buf, 2, CHECKSUM_OFFSET) & 0xff,
    sum16_bytes_2_to_checksum_minus1: sumBytes(buf, 2, CHECKSUM_OFFSET),
    sum16_bytes_2_to_end: sumBytes(buf, 2, buf.length),
    sum16_bytes_0_to_checksum_minus1: sumBytes(buf, 0, CHECKSUM_OFFSET),
    sum16_bytes_0_to_end: sumBytes(buf, 0, buf.length),
    word_sum16_le_from_2: sumWords(buf, 2, "le"),
    word_sum16_be_from_2: sumWords(buf, 2, "be"),
    word_sum16_le_from_0: sumWords(buf, 0, "le"),
    word_sum16_be_from_0: sumWords(buf, 0, "be"),
    declared_sum16_bytes_2_to_21: sumBytes(buf, 2, 22),
    declared_sum16_bytes_2_to_dataEnd_minus1: dataEnd === null ? null : sumBytes(buf, 2, dataEnd),
    declared_sum16_bytes_2_to_dataEnd_plus1: dataEnd === null ? null : sumBytes(buf, 2, dataEnd + 2),
    declared_sum16_excluding_checksum_2_to_end: sumBytes(buf, 2, buf.length, { excludeChecksum: true }),
    parseData_sum16_zero_checksum_2_to_totalLen_minus1: sumBytes(zeroed, 2, buf.length),
  };

  return { lengthLE, declaredTotalLen, dataEnd, candidates };
}

function matchKinds(candidateLE, value) {
  if (value === null || value === undefined) return {};
  const v = value & 0xffff;
  return {
    eq: candidateLE === v,
    onesComplement: candidateLE === ((0xffff - v) & 0xffff),
    twosComplement: candidateLE === ((0x10000 - v) & 0xffff),
    sumPlusCandidateFFFF: ((v + candidateLE) & 0xffff) === 0xffff,
    sumPlusCandidate0000: ((v + candidateLE) & 0xffff) === 0,
    diff: (candidateLE - v) & 0xffff,
  };
}

function inc(map, key, amount = 1) {
  const normalized = key === undefined || key === null || key === "" ? "(empty)" : String(key);
  map.set(normalized, (map.get(normalized) || 0) + amount);
}

function summarize(packets) {
  const algorithms = new Map();
  const byFrameClass = new Map();
  const diffs = new Map();

  for (const item of packets) {
    const candidateLE = readU16(item.buf, CHECKSUM_OFFSET, "le");
    const candidateBE = readU16(item.buf, CHECKSUM_OFFSET, "be");
    const frameClass = item.parsed.frameClass || "UNKNOWN";
    const { candidates } = algorithmValues(item.buf);

    for (const [name, value] of Object.entries(candidates)) {
      if (!algorithms.has(name)) {
        algorithms.set(name, { total: 0, eqLE: 0, eqBE: 0, onesComplement: 0, twosComplement: 0, plusFFFF: 0, plus0000: 0 });
      }
      const row = algorithms.get(name);
      const m = matchKinds(candidateLE, value);
      row.total += 1;
      if (candidateLE === (value & 0xffff)) row.eqLE += 1;
      if (candidateBE === (value & 0xffff)) row.eqBE += 1;
      if (m.onesComplement) row.onesComplement += 1;
      if (m.twosComplement) row.twosComplement += 1;
      if (m.sumPlusCandidateFFFF) row.plusFFFF += 1;
      if (m.sumPlusCandidate0000) row.plus0000 += 1;

      const classKey = `${frameClass}::${name}`;
      if (!byFrameClass.has(classKey)) {
        byFrameClass.set(classKey, { frameClass, algorithm: name, total: 0, eqLE: 0, eqBE: 0 });
      }
      const classRow = byFrameClass.get(classKey);
      classRow.total += 1;
      if (candidateLE === (value & 0xffff)) classRow.eqLE += 1;
      if (candidateBE === (value & 0xffff)) classRow.eqBE += 1;

      const diffKey = `${name}::${m.diff}`;
      inc(diffs, diffKey);
    }
  }

  const algorithmRows = [...algorithms.entries()].map(([algorithm, row]) => ({
    algorithm,
    ...row,
    eqLERate: row.total ? row.eqLE / row.total : 0,
    eqBERate: row.total ? row.eqBE / row.total : 0,
    onesComplementRate: row.total ? row.onesComplement / row.total : 0,
    twosComplementRate: row.total ? row.twosComplement / row.total : 0,
    plusFFFFRate: row.total ? row.plusFFFF / row.total : 0,
    plus0000Rate: row.total ? row.plus0000 / row.total : 0,
  })).sort((a, b) => b.eqLERate - a.eqLERate || b.eqLE - a.eqLE || a.algorithm.localeCompare(b.algorithm));

  const frameRows = [...byFrameClass.values()].map((row) => ({
    ...row,
    eqLERate: row.total ? row.eqLE / row.total : 0,
    eqBERate: row.total ? row.eqBE / row.total : 0,
  })).sort((a, b) => a.frameClass.localeCompare(b.frameClass) || b.eqLERate - a.eqLERate);

  const topConstantDifferences = {};
  for (const row of algorithmRows) {
    const prefix = `${row.algorithm}::`;
    topConstantDifferences[row.algorithm] = [...diffs.entries()]
      .filter(([key]) => key.startsWith(prefix))
      .map(([key, count]) => ({ diff: Number(key.slice(prefix.length)), diffHex: `0x${Number(key.slice(prefix.length)).toString(16)}`, count }))
      .sort((a, b) => b.count - a.count || a.diff - b.diff)
      .slice(0, 10);
  }

  return { algorithmRows, frameRows, topConstantDifferences };
}

function describeSample(name, rawHex) {
  const buf = Buffer.from(cleanHex(rawHex), "hex");
  const fields = {
    soi: buf.subarray(0, 2).toString("hex"),
    seqLE: readU16(buf, 2, "le"),
    typeA: buf.subarray(4, 8).toString("hex"),
    lengthLE: readU16(buf, 20, "le"),
    checksumCandidateLE: readU16(buf, CHECKSUM_OFFSET, "le"),
    checksumCandidateBE: readU16(buf, CHECKSUM_OFFSET, "be"),
    totalLength: buf.length,
  };
  const { candidates } = algorithmValues(buf);
  const table = [...buf.entries()].map(([offset, byte]) => ({
    offset,
    offsetHex: `0x${offset.toString(16).padStart(2, "0")}`,
    byteHex: byte.toString(16).padStart(2, "0"),
    role:
      offset < 2
        ? "SOI"
        : offset < 4
          ? "seqLE"
          : offset < 8
            ? "typeA"
            : offset >= 20 && offset < 22
              ? "lengthLE"
              : offset >= 22 && offset < 24
                ? "checksumCandidate"
                : "",
  }));
  const computed = Object.fromEntries(
    Object.entries(candidates).map(([algorithm, value]) => [
      algorithm,
      {
        value,
        valueHex: `0x${(value & 0xffff).toString(16)}`,
        diffFromCandidateLE: (fields.checksumCandidateLE - value) & 0xffff,
        matchesCandidateLE: fields.checksumCandidateLE === (value & 0xffff),
      },
    ]),
  );
  return { name, rawHex: cleanHex(rawHex), fields, offsetTable: table, computed };
}

function markdownTable(rows, columns) {
  const header = `| ${columns.map((column) => column.title).join(" | ")} |`;
  const divider = `| ${columns.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => `| ${columns.map((column) => String(column.value(row) ?? "").replace(/\|/g, "\\|")).join(" | ")} |`);
  return [header, divider, ...body].join("\n");
}

function pct(value) {
  return `${(value * 100).toFixed(2)}%`;
}

function writeReports(outDir, result) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `checksum-verify-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const md = [
    "# FSU Checksum Verification",
    "",
    `Generated: ${result.generatedAt}`,
    `Raw log: ${result.logPath}`,
    `Packets tested: ${result.packetCount}`,
    `JSON parse errors: ${result.jsonParseErrors.length}`,
    "",
    "## Algorithm Hit Rates",
    "",
    markdownTable(result.summary.algorithmRows, [
      { title: "Algorithm", value: (row) => row.algorithm },
      { title: "Total", value: (row) => row.total },
      { title: "eq LE", value: (row) => `${row.eqLE} (${pct(row.eqLERate)})` },
      { title: "eq BE", value: (row) => `${row.eqBE} (${pct(row.eqBERate)})` },
      { title: "1s comp", value: (row) => `${row.onesComplement} (${pct(row.onesComplementRate)})` },
      { title: "2s comp", value: (row) => `${row.twosComplement} (${pct(row.twosComplementRate)})` },
      { title: "sum+candidate=FFFF", value: (row) => `${row.plusFFFF} (${pct(row.plusFFFFRate)})` },
      { title: "sum+candidate=0000", value: (row) => `${row.plus0000} (${pct(row.plus0000Rate)})` },
    ]),
    "",
    "## Frame-Class Hit Rates",
    "",
    markdownTable(result.summary.frameRows, [
      { title: "Frame Class", value: (row) => row.frameClass },
      { title: "Algorithm", value: (row) => row.algorithm },
      { title: "Total", value: (row) => row.total },
      { title: "eq LE", value: (row) => `${row.eqLE} (${pct(row.eqLERate)})` },
      { title: "eq BE", value: (row) => `${row.eqBE} (${pct(row.eqBERate)})` },
    ]),
    "",
    "## Top Constant Differences",
    "",
    ...Object.entries(result.summary.topConstantDifferences).flatMap(([algorithm, diffs]) => [
      `### ${algorithm}`,
      "",
      markdownTable(diffs, [
        { title: "Diff", value: (row) => row.diffHex },
        { title: "Count", value: (row) => row.count },
      ]),
      "",
    ]),
    "## Sample Detail",
    "",
    ...result.samples.flatMap((sample) => [
      `### ${sample.name}`,
      "",
      `Raw: \`${sample.rawHex}\``,
      "",
      markdownTable(Object.entries(sample.fields).map(([key, value]) => ({ key, value })), [
        { title: "Field", value: (row) => row.key },
        { title: "Value", value: (row) => row.value },
      ]),
      "",
      "Offset table:",
      "",
      markdownTable(sample.offsetTable, [
        { title: "Offset", value: (row) => row.offsetHex },
        { title: "Byte", value: (row) => row.byteHex },
        { title: "Role", value: (row) => row.role },
      ]),
      "",
      "Computed values:",
      "",
      markdownTable(Object.entries(sample.computed).map(([algorithm, item]) => ({ algorithm, ...item })), [
        { title: "Algorithm", value: (row) => row.algorithm },
        { title: "Value", value: (row) => row.valueHex },
        { title: "Diff from candidate LE", value: (row) => `0x${row.diffFromCandidateLE.toString(16)}` },
        { title: "Match", value: (row) => row.matchesCandidateLE },
      ]),
      "",
    ]),
    "## Conclusion",
    "",
    `Checksum field offset assessment: ${result.checksumFieldOffset22Assessment}`,
    "",
    result.conclusion,
    "",
  ].join("\n");
  const mdPath = path.join(outDir, `checksum-verify-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const logPath = path.resolve(args.log || DEFAULT_LOG);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  if (!fs.existsSync(logPath)) throw new Error(`raw log not found: ${logPath}`);

  const { packets, errors } = parsePackets(logPath);
  const summary = summarize(packets);
  const best = summary.algorithmRows[0];
  const parseDataRow = summary.algorithmRows.find(
    (row) => row.algorithm === "parseData_sum16_zero_checksum_2_to_totalLen_minus1",
  );
  const frameClasses = [...new Set(packets.map((item) => item.parsed.frameClass || "UNKNOWN"))];
  const bestFrameRows = summary.frameRows.filter((row) => row.algorithm === best.algorithm);
  const parseDataFrameRows = summary.frameRows.filter(
    (row) => row.algorithm === "parseData_sum16_zero_checksum_2_to_totalLen_minus1",
  );
  const allFramesHitBest = bestFrameRows.every((row) => row.eqLE === row.total);
  const shortFramesHit = bestFrameRows
    .filter((row) => /SHORT/.test(row.frameClass))
    .every((row) => row.eqLE === row.total);
  const longFramesHit = bestFrameRows
    .filter((row) => /CONFIG/.test(row.frameClass))
    .every((row) => row.eqLE === row.total);
  const dscShortParseDataRow = parseDataFrameRows.find((row) => row.frameClass === "DSC_SHORT_24_TYPE_1F00_D2FF");
  const nonDscShortParseDataRows = parseDataFrameRows.filter((row) => row.frameClass !== "DSC_SHORT_24_TYPE_1F00_D2FF");
  const nonDscShortAllHit = nonDscShortParseDataRows.every((row) => row.eqLE === row.total);
  const parseDataDiffs = summary.topConstantDifferences.parseData_sum16_zero_checksum_2_to_totalLen_minus1 || [];
  const dscShortFixedDiff = parseDataDiffs.find((row) => row.diff === 0xfeb0);

  const samples = Object.entries(SAMPLE_HEX).map(([name, hex]) => describeSample(name, hex));
  const result = {
    generatedAt: new Date().toISOString(),
    logPath,
    packetCount: packets.length,
    jsonParseErrors: errors,
    frameClasses,
    summary,
    samples,
    bestAlgorithm: best,
    parseDataAlgorithm: parseDataRow,
    allFramesHitBest,
    shortFramesHit,
    longFramesHit,
    parseDataFrameRows,
    nonDscShortAllHit,
    dscShortFixedDiff,
    checksumFieldLikelyOffset22:
      nonDscShortAllHit &&
      dscShortParseDataRow &&
      dscShortParseDataRow.total > 0 &&
      dscShortFixedDiff &&
      dscShortFixedDiff.count === dscShortParseDataRow.total,
    checksumFieldOffset22Assessment:
      nonDscShortAllHit &&
      dscShortFixedDiff &&
      dscShortParseDataRow &&
      dscShortFixedDiff.count === dscShortParseDataRow.total
        ? "offset 22..23 is strongly supported as the checksum field across observed classes, but DSC_SHORT_24 uses a fixed -0x150 adjustment relative to the ParseData additive formula."
        : "offset 22..23 is not fully proven for all observed classes by this script.",
    conclusion:
      nonDscShortAllHit && dscShortFixedDiff && dscShortParseDataRow && dscShortFixedDiff.count === dscShortParseDataRow.total
        ? `ParseData additive formula matched every non-DSC_SHORT packet (${nonDscShortParseDataRows.map((row) => `${row.frameClass} ${row.eqLE}/${row.total}`).join(", ")}). DSC_SHORT_24 did not match directly, but all ${dscShortParseDataRow.total} DSC_SHORT_24 samples have fixed diff 0xfeb0, i.e. candidateLE = parseDataSum - 0x150. Treat checksum offset 22..23 as strongly supported, but checksum formula as frame-class dependent until the DSC_SHORT generator is reversed.`
        : `No formula matched all packets. Best formula ${best ? best.algorithm : "none"} matched ${best ? `${best.eqLE}/${best.total}` : "0/0"} packets; checksum offset/range needs more reverse analysis.`,
  };
  const paths = writeReports(outDir, result);
  console.log(JSON.stringify({ ...paths, packetCount: packets.length, bestAlgorithm: result.bestAlgorithm, checksumFieldLikelyOffset22: result.checksumFieldLikelyOffset22 }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
