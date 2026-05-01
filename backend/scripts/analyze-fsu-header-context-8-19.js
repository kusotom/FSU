#!/usr/bin/env node
"use strict";

/**
 * Offline analysis of FSU header bytes[8..19].
 *
 * SAFETY:
 * - Reads local raw JSONL only.
 * - Does not open sockets.
 * - Does not send UDP.
 * - Does not add ACK or modify gateway runtime logic.
 */

const fs = require("fs");
const path = require("path");
const { parseFsuFrame, cleanHex } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const ROOT = path.resolve(__dirname, "..", "..");
const RAW_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets");
const KNOWN_CLASSES = new Set([
  "DSC_CONFIG_209_TYPE_1100_46FF",
  "DSC_CONFIG_245_TYPE_1100_46FF",
  "RDS_SHORT_30_TYPE_1180_D2FF",
  "DSC_SHORT_24_TYPE_1F00_D2FF",
]);

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === "--input" || argv[i] === "-i") args.input = argv[++i];
    else if (argv[i] === "--device-ip") args.deviceIp = argv[++i];
  }
  return args;
}

function findLatestRawLog() {
  if (!fs.existsSync(RAW_DIR)) return null;
  return fs.readdirSync(RAW_DIR)
    .filter((name) => /^\d{4}-\d{2}-\d{2}\.jsonl$/.test(name))
    .sort()
    .map((name) => path.join(RAW_DIR, name))
    .pop() || null;
}

function dateFromInput(input) {
  const base = path.basename(input, ".jsonl");
  return /^\d{4}-\d{2}-\d{2}$/.test(base) ? base : new Date().toISOString().slice(0, 10);
}

function findRawHex(entry) {
  return cleanHex(entry.rawHex || entry.hex || entry.raw || entry.payloadHex || "");
}

function toIso(entry) {
  return entry.receivedAt || entry.createdAt || entry.timestamp || null;
}

function inc(map, key) {
  map[key] = (map[key] || 0) + 1;
}

function topValues(map, limit = 8) {
  return Object.entries(map)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([value, count]) => ({ value, count }));
}

function ensureGroup(groups, frameClass) {
  if (!groups[frameClass]) {
    groups[frameClass] = {
      frameClass,
      count: 0,
      firstSeen: null,
      lastSeen: null,
      contexts: {},
      offsets: Array.from({ length: 12 }, (_, index) => ({
        frameOffset: 8 + index,
        values: {},
      })),
      samples: [],
      seqToContexts: {},
      timeline: [],
    };
  }
  return groups[frameClass];
}

function summarizeGroup(group) {
  return {
    frameClass: group.frameClass,
    count: group.count,
    firstSeen: group.firstSeen,
    lastSeen: group.lastSeen,
    uniqueHeaderContextCount: Object.keys(group.contexts).length,
    topHeaderContexts: topValues(group.contexts),
    offsetStability: group.offsets.map((item) => {
      const unique = Object.keys(item.values);
      return {
        frameOffset: item.frameOffset,
        fixed: unique.length === 1,
        uniqueValueCount: unique.length,
        fixedValue: unique.length === 1 ? unique[0] : null,
        topValues: topValues(item.values),
      };
    }),
    samples: group.samples,
  };
}

function compareContextSets(left, right) {
  const leftSet = new Set(Object.keys(left?.contexts || {}));
  const rightSet = new Set(Object.keys(right?.contexts || {}));
  const common = [...leftSet].filter((value) => rightSet.has(value));
  return {
    leftFrameClass: left?.frameClass || null,
    rightFrameClass: right?.frameClass || null,
    leftUniqueCount: leftSet.size,
    rightUniqueCount: rightSet.size,
    commonContexts: common,
    sameContextSet: leftSet.size === rightSet.size && common.length === leftSet.size,
    leftOnly: [...leftSet].filter((value) => !rightSet.has(value)),
    rightOnly: [...rightSet].filter((value) => !leftSet.has(value)),
  };
}

function pairBySeq(leftTimeline, rightTimeline) {
  const rightBySeq = new Map();
  for (const item of rightTimeline) {
    if (!rightBySeq.has(item.seqLE)) rightBySeq.set(item.seqLE, []);
    rightBySeq.get(item.seqLE).push(item);
  }
  const pairs = [];
  for (const left of leftTimeline) {
    const candidates = rightBySeq.get(left.seqLE);
    if (!candidates || !candidates.length) continue;
    pairs.push({ left, right: candidates.shift() });
  }
  return pairs;
}

function comparePairContexts(pairs) {
  const diffOffsets = {};
  let sameContext = 0;
  const samples = [];
  for (const pair of pairs) {
    if (pair.left.headerContextHex === pair.right.headerContextHex) sameContext += 1;
    const leftBuf = Buffer.from(pair.left.headerContextHex, "hex");
    const rightBuf = Buffer.from(pair.right.headerContextHex, "hex");
    const diffs = [];
    for (let i = 0; i < 12; i += 1) {
      if (leftBuf[i] !== rightBuf[i]) {
        const frameOffset = 8 + i;
        inc(diffOffsets, String(frameOffset));
        diffs.push({
          frameOffset,
          left: leftBuf[i].toString(16).padStart(2, "0"),
          right: rightBuf[i].toString(16).padStart(2, "0"),
        });
      }
    }
    if (samples.length < 8 && diffs.length) {
      samples.push({
        seqLE: pair.left.seqLE,
        leftHeaderContextHex: pair.left.headerContextHex,
        rightHeaderContextHex: pair.right.headerContextHex,
        diffs,
      });
    }
  }
  return {
    pairCount: pairs.length,
    sameContext,
    differentContext: pairs.length - sameContext,
    diffOffsets: topValues(diffOffsets, 12),
    samples,
  };
}

function main() {
  const args = parseArgs(process.argv);
  const input = args.input || findLatestRawLog();
  if (!input || !fs.existsSync(input)) {
    console.error("No raw JSONL input found. Use --input backend/logs/fsu_raw_packets/YYYY-MM-DD.jsonl");
    process.exit(2);
  }
  const deviceIp = args.deviceIp || "192.168.100.100";
  const outDate = dateFromInput(input);
  const groups = {};
  let totalLines = 0;
  let parsed = 0;
  let skipped = 0;

  const lines = fs.readFileSync(input, "utf8").split(/\r?\n/);
  for (const line of lines) {
    if (!line.trim()) continue;
    totalLines += 1;
    let entry;
    try { entry = JSON.parse(line); } catch { skipped += 1; continue; }
    if (entry.remoteAddress && entry.remoteAddress !== deviceIp) continue;
    const rawHex = findRawHex(entry);
    if (!rawHex) { skipped += 1; continue; }
    const frame = parseFsuFrame(rawHex, { protocol: entry.protocol, includeAscii: false });
    if (!frame.ok || !KNOWN_CLASSES.has(frame.frameClass) || frame.totalLength < 20) continue;
    const buf = Buffer.from(rawHex, "hex");
    const headerContextHex = buf.subarray(8, 20).toString("hex");
    const group = ensureGroup(groups, frame.frameClass);
    const ts = toIso(entry);
    parsed += 1;
    group.count += 1;
    if (!group.firstSeen || (ts && ts < group.firstSeen)) group.firstSeen = ts;
    if (!group.lastSeen || (ts && ts > group.lastSeen)) group.lastSeen = ts;
    inc(group.contexts, headerContextHex);
    for (let i = 0; i < 12; i += 1) {
      inc(group.offsets[i].values, buf[8 + i].toString(16).padStart(2, "0"));
    }
    const record = {
      timestamp: ts,
      protocol: entry.protocol,
      remoteAddress: entry.remoteAddress,
      remotePort: entry.remotePort,
      localPort: entry.localPort,
      frameClass: frame.frameClass,
      totalLength: frame.totalLength,
      seqLE: frame.seqLE,
      typeBytes: frame.typeBytesSummary,
      typeByte: frame.typeByte,
      flagByte: frame.flagByte,
      classByte: frame.classByte,
      tailByte: frame.tailByte,
      headerContextHex,
      offsets: Object.fromEntries(Array.from({ length: 12 }, (_, i) => [`offset${8 + i}`, buf[8 + i].toString(16).padStart(2, "0")])),
    };
    if (group.samples.length < 5) group.samples.push(record);
    group.timeline.push(record);
  }

  const groupSummaries = Object.fromEntries(Object.entries(groups).map(([key, value]) => [key, summarizeGroup(value)]));
  const configCompare = compareContextSets(groups.DSC_CONFIG_209_TYPE_1100_46FF, groups.DSC_CONFIG_245_TYPE_1100_46FF);
  const rdsAckPairs = pairBySeq(
    groups.RDS_SHORT_30_TYPE_1180_D2FF?.timeline || [],
    groups.DSC_SHORT_24_TYPE_1F00_D2FF?.timeline || [],
  );
  const rdsAckCompare = comparePairContexts(rdsAckPairs);

  const recommendation = {
    class47HeaderContextStrategy: "copy_request_header_context_8_19",
    confidence: configCompare.sameContextSet ? "high-confidence candidate" : "candidate only",
    rationale: [
      "DSC_CONFIG_209 and DSC_CONFIG_245 share the same observed 0x46 header context set, so context is independent of DHCP-vs-explicit-IP URI payload variant.",
      "No live 0x47 frame is available; copying request bytes[8..19] remains a conservative offline strategy.",
      "D2FF RDS30/ACK24 pairs differ at bytes 16,17,19, showing that context bytes can be class/direction-specific for D2FF and should not be generalized blindly to 0x47.",
    ],
    copyByRequestVariant: "copy from the exact selected 0x46 request, whether 209 or 245",
    mustCopyOffsetsCandidate: configCompare.sameContextSet ? Array.from({ length: 12 }, (_, i) => 8 + i) : [],
    fixedOffsetsCandidate: Object.values(groupSummaries).flatMap((group) =>
      group.offsetStability.filter((item) => item.fixed).map((item) => ({ frameClass: group.frameClass, frameOffset: item.frameOffset, value: item.fixedValue })),
    ),
  };

  const result = {
    input,
    generatedAt: new Date().toISOString(),
    safety: {
      noUdpSent: true,
      noAckAdded: true,
      sendOneShotAckNotRun: true,
      gatewayReplyLogicUnchanged: true,
      businessTablesUnchanged: true,
    },
    counts: { totalLines, parsed, skipped },
    groupSummaries,
    config209vs245: configCompare,
    rds30vsDsc24BySeq: rdsAckCompare,
    recommendation,
    remainingUnknowns: [
      "No real 0x47 response frame has been observed.",
      "Official meaning of bytes[8..19] remains unknown.",
      "D2FF offset 16/17/19 behavior cannot be assumed for classByte=0x47.",
    ],
  };

  const outJson = path.join(RAW_DIR, `header-context-8-19-analysis-${outDate}.json`);
  const outMd = path.join(RAW_DIR, `header-context-8-19-analysis-${outDate}.md`);
  fs.writeFileSync(outJson, JSON.stringify(result, null, 2), "utf8");

  const md = [
    `# FSU header context bytes[8..19] analysis ${outDate}`,
    "",
    `Input: \`${input}\``,
    "",
    "Safety: offline analysis only; no UDP sent; no ACK added; gateway runtime reply logic unchanged.",
    "",
    "## Summary",
    "",
    `- Parsed known frames: ${parsed}`,
    `- 0x47 recommendation: \`${recommendation.class47HeaderContextStrategy}\` (${recommendation.confidence})`,
    `- 209/245 same context set: ${configCompare.sameContextSet}`,
    `- RDS30/DSC24 pairs by seq: ${rdsAckCompare.pairCount}`,
    `- RDS30/DSC24 different context pairs: ${rdsAckCompare.differentContext}`,
    "",
    "## By FrameClass",
    "",
    "| frameClass | count | unique contexts | top contexts |",
    "| --- | ---: | ---: | --- |",
    ...Object.values(groupSummaries).map((group) => `| ${group.frameClass} | ${group.count} | ${group.uniqueHeaderContextCount} | ${group.topHeaderContexts.map((v) => `${v.value} (${v.count})`).join("<br>")} |`),
    "",
    "## Offset Stability",
    "",
    ...Object.values(groupSummaries).flatMap((group) => [
      `### ${group.frameClass}`,
      "",
      "| offset | fixed | unique | top values |",
      "| ---: | --- | ---: | --- |",
      ...group.offsetStability.map((item) => `| ${item.frameOffset} | ${item.fixed} | ${item.uniqueValueCount} | ${item.topValues.map((v) => `${v.value} (${v.count})`).join(", ")} |`),
      "",
    ]),
    "## 209 / 245 Compare",
    "",
    `- sameContextSet: ${configCompare.sameContextSet}`,
    `- commonContexts: ${configCompare.commonContexts.join(", ") || "none"}`,
    "",
    "## RDS30 / DSC24 Pair Compare",
    "",
    `- pairCount: ${rdsAckCompare.pairCount}`,
    `- sameContext: ${rdsAckCompare.sameContext}`,
    `- differentContext: ${rdsAckCompare.differentContext}`,
    `- diffOffsets: ${rdsAckCompare.diffOffsets.map((v) => `${v.value} (${v.count})`).join(", ")}`,
    "",
    "## 0x47 Context Strategy",
    "",
    "- Recommended offline strategy: copy bytes[8..19] from the exact selected 0x46 request.",
    "- Evidence level: high-confidence candidate if 209/245 contexts remain identical; not confirmed because no real 0x47 frame has been observed.",
    "",
    "## Remaining Unknowns",
    "",
    ...result.remainingUnknowns.map((item) => `- ${item}`),
    "",
  ].join("\n");
  fs.writeFileSync(outMd, md, "utf8");
  console.log(`Wrote ${outMd}`);
  console.log(`Wrote ${outJson}`);
}

main();
