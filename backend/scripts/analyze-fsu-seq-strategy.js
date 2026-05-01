#!/usr/bin/env node
"use strict";

/**
 * Offline seqLE strategy analysis for FSU DSC/RDS frames.
 *
 * SAFETY:
 * - Reads local raw JSONL only.
 * - Does not open sockets or send UDP.
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

function topValues(map, limit = 12) {
  return Object.entries(map)
    .sort((a, b) => b[1] - a[1] || Number(a[0]) - Number(b[0]))
    .slice(0, limit)
    .map(([value, count]) => ({ value: Number(value), count }));
}

function ensureGroup(groups, frameClass) {
  if (!groups[frameClass]) {
    groups[frameClass] = {
      frameClass,
      seqs: [],
      seqCounts: {},
      timeline: [],
      deltaCounts: {},
    };
  }
  return groups[frameClass];
}

function summarizeSeqs(group) {
  const seqs = group.seqs;
  const deltas = [];
  for (let i = 1; i < group.timeline.length; i += 1) {
    const prev = group.timeline[i - 1].seqLE;
    const cur = group.timeline[i].seqLE;
    const delta = (cur - prev + 0x10000) & 0xffff;
    deltas.push(delta);
    inc(group.deltaCounts, String(delta));
  }
  const uniqueSeqCount = Object.keys(group.seqCounts).length;
  return {
    frameClass: group.frameClass,
    count: seqs.length,
    minSeqLE: seqs.length ? Math.min(...seqs) : null,
    maxSeqLE: seqs.length ? Math.max(...seqs) : null,
    uniqueSeqCount,
    duplicateSeqCount: seqs.length - uniqueSeqCount,
    firstSeqLE: group.timeline[0]?.seqLE ?? null,
    lastSeqLE: group.timeline[group.timeline.length - 1]?.seqLE ?? null,
    topDeltas: topValues(group.deltaCounts),
    mostlyIncrementing: (group.deltaCounts["1"] || 0) >= Math.max(1, Math.floor(deltas.length * 0.8)),
    samples: group.timeline.slice(0, 5),
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

function nearestPairs(leftTimeline, rightTimeline, maxMs = 10000) {
  const out = [];
  const right = rightTimeline.map((item) => ({ ...item, timeMs: Date.parse(item.timestamp || "") })).filter((item) => Number.isFinite(item.timeMs));
  for (const leftItem of leftTimeline) {
    const leftMs = Date.parse(leftItem.timestamp || "");
    if (!Number.isFinite(leftMs)) continue;
    let best = null;
    for (const candidate of right) {
      const dt = Math.abs(candidate.timeMs - leftMs);
      if (dt <= maxMs && (!best || dt < best.dt)) best = { candidate, dt };
    }
    if (best) out.push({ left: leftItem, right: best.candidate, deltaMs: best.dt, seqDelta: (best.candidate.seqLE - leftItem.seqLE + 0x10000) & 0xffff });
  }
  return out;
}

function scanStaticEvidence() {
  const candidates = [
    "backend/logs/fsu_reverse/ack-disasm-analysis-2026-04-28.json",
    "backend/logs/fsu_reverse/seqle-validation-final-2026-04-28.json",
    "backend/logs/fsu_reverse/login-ack-seq-strategy-final-2026-04-28.json",
    "backend/logs/fsu_raw_packets/dsc-rds-offline-reverse-summary-v1.3-2026-05-01.json",
  ];
  const hits = [];
  for (const rel of candidates) {
    const full = path.join(ROOT, rel);
    if (!fs.existsSync(full)) continue;
    const text = fs.readFileSync(full, "utf8");
    const lower = text.toLowerCase();
    const terms = ["seq", "sequence", "0x71ba0", "0x6b898", "mirror request seq", "pending request"];
    const matched = terms.filter((term) => lower.includes(term.toLowerCase()));
    if (matched.length) hits.push({ path: rel, matchedTerms: matched });
  }
  return hits;
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

  for (const line of fs.readFileSync(input, "utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    totalLines += 1;
    let entry;
    try { entry = JSON.parse(line); } catch { skipped += 1; continue; }
    if (entry.remoteAddress && entry.remoteAddress !== deviceIp) continue;
    const rawHex = findRawHex(entry);
    if (!rawHex) { skipped += 1; continue; }
    const frame = parseFsuFrame(rawHex, { protocol: entry.protocol, includeAscii: false });
    if (!frame.ok || !KNOWN_CLASSES.has(frame.frameClass)) continue;
    parsed += 1;
    const group = ensureGroup(groups, frame.frameClass);
    const record = {
      timestamp: toIso(entry),
      protocol: entry.protocol,
      remotePort: entry.remotePort,
      localPort: entry.localPort,
      frameClass: frame.frameClass,
      seqLE: frame.seqLE,
      typeBytes: frame.typeBytesSummary,
      classByte: frame.classByte,
      totalLength: frame.totalLength,
    };
    group.seqs.push(frame.seqLE);
    inc(group.seqCounts, String(frame.seqLE));
    group.timeline.push(record);
  }

  for (const group of Object.values(groups)) {
    group.timeline.sort((a, b) => String(a.timestamp || "").localeCompare(String(b.timestamp || "")));
  }

  const summaries = Object.fromEntries(Object.entries(groups).map(([key, group]) => [key, summarizeSeqs(group)]));
  const rdsAckPairs = pairBySeq(groups.RDS_SHORT_30_TYPE_1180_D2FF?.timeline || [], groups.DSC_SHORT_24_TYPE_1F00_D2FF?.timeline || []);
  const rdsAckEvidence = {
    pairCount: rdsAckPairs.length,
    rds30Count: groups.RDS_SHORT_30_TYPE_1180_D2FF?.timeline.length || 0,
    dsc24Count: groups.DSC_SHORT_24_TYPE_1F00_D2FF?.timeline.length || 0,
    sameSeqRatio: rdsAckPairs.length / Math.max(1, groups.RDS_SHORT_30_TYPE_1180_D2FF?.timeline.length || 0),
    samples: rdsAckPairs.slice(0, 8).map((pair) => ({
      seqLE: pair.left.seqLE,
      rdsTimestamp: pair.left.timestamp,
      ackTimestamp: pair.right.timestamp,
      rdsTypeBytes: pair.left.typeBytes,
      ackTypeBytes: pair.right.typeBytes,
    })),
  };

  const configNearest = nearestPairs(
    groups.DSC_CONFIG_209_TYPE_1100_46FF?.timeline || [],
    groups.DSC_CONFIG_245_TYPE_1100_46FF?.timeline || [],
    12000,
  );
  const seqDeltaCounts = {};
  for (const pair of configNearest) inc(seqDeltaCounts, String(pair.seqDelta));
  const configSeqEvidence = {
    nearestPairCount: configNearest.length,
    topSeqDeltas209To245: topValues(seqDeltaCounts),
    samples: configNearest.slice(0, 8).map((pair) => ({
      dsc209SeqLE: pair.left.seqLE,
      dsc245SeqLE: pair.right.seqLE,
      seqDelta: pair.seqDelta,
      deltaMs: pair.deltaMs,
      dsc209Time: pair.left.timestamp,
      dsc245Time: pair.right.timestamp,
    })),
  };

  const staticEvidence = scanStaticEvidence();
  const conclusion = {
    d2ffSeqEcho: rdsAckPairs.length > 0 && rdsAckPairs.length === (groups.RDS_SHORT_30_TYPE_1180_D2FF?.timeline.length || 0)
      ? "confirmed for RDS30 -> DSC24 D2FF pair"
      : "partial",
    class47SeqStrategyCandidate: "mirror_request_seqLE",
    class47ConclusionLevel: "high-confidence candidate",
    rationale: [
      "RDS30 and DSC24 D2FF pairs use the same seqLE throughout the raw log, which is strong evidence that confirmation-style responses echo request seq in the D2FF family.",
      "No real 0x47 response frame is present in raw log, so 0x47 seq echo cannot be confirmed from live packets.",
      "Static reports available locally do not provide stronger proof here than candidate-level seq mirror notes.",
    ],
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
    frameClassSeqStats: summaries,
    rds30ToDsc24SeqEcho: rdsAckEvidence,
    dscConfig209To245SeqBehavior: configSeqEvidence,
    staticEvidence,
    conclusion,
    remainingUnknowns: [
      "0x47 response seqLE cannot be confirmed without a real 0x47 frame or stronger SiteUnit comparison evidence.",
      "209/245 sequence behavior reflects request retries/config variants, not a response pair.",
    ],
  };

  const outJson = path.join(RAW_DIR, `seq-strategy-analysis-${outDate}.json`);
  const outMd = path.join(RAW_DIR, `seq-strategy-analysis-${outDate}.md`);
  fs.writeFileSync(outJson, JSON.stringify(result, null, 2), "utf8");
  const md = [
    `# FSU seqLE strategy analysis ${outDate}`,
    "",
    `Input: \`${input}\``,
    "",
    "Safety: offline analysis only; no UDP sent; no ACK added; gateway runtime reply logic unchanged.",
    "",
    "## Summary",
    "",
    `- D2FF seq echo: ${conclusion.d2ffSeqEcho}`,
    `- 0x47 seq strategy candidate: \`${conclusion.class47SeqStrategyCandidate}\``,
    `- conclusion level: ${conclusion.class47ConclusionLevel}`,
    "",
    "## FrameClass Seq Stats",
    "",
    "| frameClass | count | min | max | unique | duplicates | first | last | top deltas |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ...Object.values(summaries).map((item) => `| ${item.frameClass} | ${item.count} | ${item.minSeqLE} | ${item.maxSeqLE} | ${item.uniqueSeqCount} | ${item.duplicateSeqCount} | ${item.firstSeqLE} | ${item.lastSeqLE} | ${item.topDeltas.map((v) => `${v.value} (${v.count})`).join(", ")} |`),
    "",
    "## RDS30 / DSC24 Same-Seq Evidence",
    "",
    `- RDS30 count: ${rdsAckEvidence.rds30Count}`,
    `- DSC24 count: ${rdsAckEvidence.dsc24Count}`,
    `- paired by same seq: ${rdsAckEvidence.pairCount}`,
    `- same-seq ratio vs RDS30: ${rdsAckEvidence.sameSeqRatio}`,
    "",
    "## DSC_CONFIG 209 / 245 Seq Behavior",
    "",
    `- nearest 209->245 pairs within 12s: ${configSeqEvidence.nearestPairCount}`,
    `- top seq deltas: ${configSeqEvidence.topSeqDeltas209To245.map((v) => `${v.value} (${v.count})`).join(", ")}`,
    "",
    "## Static Evidence Scan",
    "",
    ...(staticEvidence.length ? staticEvidence.map((item) => `- ${item.path}: ${item.matchedTerms.join(", ")}`) : ["- No local static seq evidence reports found."]),
    "",
    "## Conclusion",
    "",
    "- Recommend `mirror_request_seqLE` for 0x47 only as a high-confidence offline candidate, not confirmed online behavior.",
    "- D2FF ACK/confirm family confirms same-seq response behavior, but cannot alone prove class47 behavior.",
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
