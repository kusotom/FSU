#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const DEFAULT_INPUT = path.join(__dirname, "..", "logs", "fsu_raw_packets", "2026-04-28.jsonl");
const SHORT_CLASSES = new Set([
  "DSC_SHORT_24_TYPE_1F00_D2FF",
  "RDS_SHORT_30_TYPE_1180_D2FF",
]);
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

function byteHex(buf, offset) {
  return offset >= 0 && offset < buf.length ? buf[offset].toString(16).padStart(2, "0") : "";
}

function normalizeWithoutSeq(rawHex) {
  const hex = cleanHex(rawHex);
  if (hex.length < 8) {
    return hex;
  }
  return `${hex.slice(0, 4)}${hex.slice(8)}`;
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

function percentile(sortedValues, p) {
  if (!sortedValues.length) {
    return null;
  }
  const index = Math.min(sortedValues.length - 1, Math.max(0, Math.ceil((p / 100) * sortedValues.length) - 1));
  return sortedValues[index];
}

function intervalStats(records) {
  const sorted = [...records].sort((a, b) => a.timeMs - b.timeMs);
  const intervals = [];
  for (let i = 1; i < sorted.length; i += 1) {
    const delta = (sorted[i].timeMs - sorted[i - 1].timeMs) / 1000;
    if (Number.isFinite(delta) && delta >= 0) {
      intervals.push(delta);
    }
  }
  const ordered = [...intervals].sort((a, b) => a - b);
  const sum = intervals.reduce((acc, value) => acc + value, 0);
  return {
    count: intervals.length,
    min: ordered.length ? ordered[0] : null,
    max: ordered.length ? ordered[ordered.length - 1] : null,
    average: intervals.length ? sum / intervals.length : null,
    p50: percentile(ordered, 50),
    p90: percentile(ordered, 90),
    p99: percentile(ordered, 99),
  };
}

function formatSeconds(value) {
  return value === null || value === undefined ? "" : value.toFixed(3);
}

function valueDistribution(values, limit = 20) {
  const counts = new Map();
  for (const value of values) {
    countMapInc(counts, value);
  }
  return topEntries(counts, limit)
    .map(([value, count]) => `${value}:${count}`)
    .join(", ");
}

function byteStats(records) {
  const maxLength = Math.max(0, ...records.map((record) => record.buf.length));
  const sorted = [...records].sort((a, b) => a.timeMs - b.timeMs);
  const rows = [];

  for (let offset = 0; offset < maxLength; offset += 1) {
    const values = new Map();
    for (const record of records) {
      countMapInc(values, byteHex(record.buf, offset) || "(missing)");
    }
    const fixed = values.size === 1 && !values.has("(missing)");
    const fixedValue = fixed ? [...values.keys()][0] : "";
    let seqTransitions = 0;
    let seqLinkedChanges = 0;
    let timeTransitions = 0;
    let timeLinkedChanges = 0;

    for (let i = 1; i < sorted.length; i += 1) {
      const prev = sorted[i - 1];
      const curr = sorted[i];
      const prevValue = byteHex(prev.buf, offset);
      const currValue = byteHex(curr.buf, offset);

      if (prev.seqLE !== curr.seqLE) {
        seqTransitions += 1;
        if (prevValue !== currValue) {
          seqLinkedChanges += 1;
        }
      }
      if (prev.timeMs !== curr.timeMs) {
        timeTransitions += 1;
        if (prevValue !== currValue) {
          timeLinkedChanges += 1;
        }
      }
    }

    rows.push({
      offset,
      fixed,
      fixedValue,
      distinctCount: values.size,
      topValues: topEntries(values, 8).map(([value, count]) => `${value}:${count}`).join(", "),
      changesWithSeqLE:
        !fixed && seqTransitions > 0 ? seqLinkedChanges / seqTransitions >= 0.5 || offset === 2 || offset === 3 : false,
      seqLinkedChangeRate: seqTransitions ? seqLinkedChanges / seqTransitions : 0,
      changesWithTime: !fixed && timeTransitions > 0 ? timeLinkedChanges / timeTransitions >= 0.5 : false,
      timeLinkedChangeRate: timeTransitions ? timeLinkedChanges / timeTransitions : 0,
    });
  }

  return rows;
}

function normalizedGroupSummary(records, limit = 100) {
  const groups = new Map();
  for (const record of records) {
    const key = record.normalizedWithoutSeq;
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key).push(record);
  }

  const repeatedRecordCount = [...groups.values()]
    .filter((items) => items.length > 1)
    .reduce((sum, items) => sum + items.length, 0);

  const topGroups = topEntries(
    [...groups.entries()].reduce((map, [key, items]) => {
      map.set(key, items.length);
      return map;
    }, new Map()),
    limit,
  ).map(([normalizedHex, count]) => {
    const items = groups.get(normalizedHex).sort((a, b) => a.timeMs - b.timeMs);
    return {
      normalizedHex,
      count,
      firstReceivedAt: items[0]?.receivedAt || "",
      lastReceivedAt: items[items.length - 1]?.receivedAt || "",
      intervalStats: intervalStats(items),
      sampleRawHex: items[0]?.rawHex || "",
    };
  });

  return {
    uniqueCount: groups.size,
    repeatedRecordCount,
    groups: topGroups,
  };
}

function groupByKey(records, keyFn, limit = 100) {
  const groups = new Map();
  for (const record of records) {
    const key = keyFn(record);
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key).push(record);
  }

  const repeatedRecordCount = [...groups.values()]
    .filter((items) => items.length > 1)
    .reduce((sum, items) => sum + items.length, 0);

  return {
    uniqueCount: groups.size,
    repeatedRecordCount,
    groups: topEntries(
      [...groups.entries()].reduce((map, [key, items]) => {
        map.set(key, items.length);
        return map;
      }, new Map()),
      limit,
    ).map(([key, count]) => {
      const items = groups.get(key).sort((a, b) => a.timeMs - b.timeMs);
      return {
        key,
        count,
        firstReceivedAt: items[0]?.receivedAt || "",
        lastReceivedAt: items[items.length - 1]?.receivedAt || "",
        intervalStats: intervalStats(items),
      };
    }),
  };
}

function nearestRecord(target, candidates, maxMs) {
  let best = null;
  let bestAbsDelta = Infinity;
  for (const candidate of candidates) {
    const delta = candidate.timeMs - target.timeMs;
    const absDelta = Math.abs(delta);
    if (absDelta <= maxMs && absDelta < bestAbsDelta) {
      best = { record: candidate, deltaMs: delta, absDeltaMs: absDelta };
      bestAbsDelta = absDelta;
    }
  }
  return best;
}

function pairAnalysis(dscRecords, rdsRecords) {
  const maxMs = 1000;
  const secondBuckets = new Map();
  for (const record of [...dscRecords, ...rdsRecords]) {
    const second = new Date(Math.floor(record.timeMs / 1000) * 1000).toISOString();
    if (!secondBuckets.has(second)) {
      secondBuckets.set(second, new Set());
    }
    secondBuckets.get(second).add(record.frameClass);
  }
  const sameSecondCount = [...secondBuckets.values()].filter(
    (classes) => classes.has("DSC_SHORT_24_TYPE_1F00_D2FF") && classes.has("RDS_SHORT_30_TYPE_1180_D2FF"),
  ).length;

  const dscMatches = [];
  const orderCounts = new Map();
  const seqDiffs = new Map();
  const deltas = [];
  for (const dsc of dscRecords) {
    const nearest = nearestRecord(dsc, rdsRecords, maxMs);
    if (!nearest) {
      continue;
    }
    dscMatches.push(nearest);
    deltas.push(nearest.deltaMs / 1000);
    countMapInc(orderCounts, nearest.deltaMs >= 0 ? "DSC before/same RDS" : "RDS before DSC");
    countMapInc(seqDiffs, nearest.record.seqLE - dsc.seqLE);
  }

  const rdsWithDscWithin1s = rdsRecords.filter((rds) => nearestRecord(rds, dscRecords, maxMs)).length;
  return {
    sameSecondBucketCount: sameSecondCount,
    secondsWithAnyShortFrame: secondBuckets.size,
    dscWithRdsWithin1s: dscMatches.length,
    rdsWithDscWithin1s,
    dscCount: dscRecords.length,
    rdsCount: rdsRecords.length,
    orderCounts: countObject(orderCounts),
    seqDiffDistribution: countObject(seqDiffs, 20),
    deltaSecondsDistribution: valueDistribution(deltas.map((value) => value.toFixed(3)), 20),
  };
}

function surroundingRelation(longRecords, dscShortRecords, windowSeconds = 5) {
  const windowMs = windowSeconds * 1000;
  const byClass = {};
  for (const frameClass of CONFIG_CLASSES) {
    const records = longRecords.filter((record) => record.frameClass === frameClass);
    let withShort = 0;
    const beforeCounts = [];
    const afterCounts = [];
    for (const longRecord of records) {
      const before = dscShortRecords.filter(
        (shortRecord) => shortRecord.timeMs < longRecord.timeMs && longRecord.timeMs - shortRecord.timeMs <= windowMs,
      ).length;
      const after = dscShortRecords.filter(
        (shortRecord) => shortRecord.timeMs >= longRecord.timeMs && shortRecord.timeMs - longRecord.timeMs <= windowMs,
      ).length;
      if (before + after > 0) {
        withShort += 1;
      }
      beforeCounts.push(before);
      afterCounts.push(after);
    }
    byClass[frameClass] = {
      longFrameCount: records.length,
      withDscShortWithinWindow: withShort,
      windowSeconds,
      beforeCountDistribution: valueDistribution(beforeCounts),
      afterCountDistribution: valueDistribution(afterCounts),
      repeatIntervalStats: intervalStats(records),
    };
  }
  return byClass;
}

function createRecords(packets) {
  const records = [];
  const byFrameClass = new Map();
  const byTypeA = new Map();
  for (const packet of packets) {
    if (packet.protocol !== "UDP_DSC" && packet.protocol !== "UDP_RDS") {
      continue;
    }
    const parsed = parseFsuFrame(packet.rawHex, { protocol: packet.protocol, includeAscii: true });
    const dscConfig = parsed.dscConfig || null;
    const uriSignature = dscConfig ? [...dscConfig.udpUris, ...dscConfig.ftpUris].join(" | ") : "";
    const buf = hexToBuffer(packet.rawHex);
    const record = {
      receivedAt: packet.receivedAt,
      timeMs: Date.parse(packet.receivedAt),
      protocol: packet.protocol,
      remoteAddress: packet.remoteAddress,
      remotePort: packet.remotePort,
      localPort: packet.localPort,
      rawHex: cleanHex(packet.rawHex),
      normalizedWithoutSeq: normalizeWithoutSeq(packet.rawHex),
      buf,
      frameClass: parsed.frameClass,
      seqLE: parsed.seqLE,
      typeA: parsed.typeA,
      totalLength: parsed.totalLength,
      payloadLengthCandidate: parsed.payloadLengthCandidate,
      bodyHex: parsed.bodyHex,
      bodyTail2: parsed.bodyTail2,
      bodyTail4: parsed.bodyTail4,
      uriSignature,
      dscConfigSummary: dscConfig
        ? {
            udpUris: dscConfig.udpUris,
            ftpUris: dscConfig.ftpUris,
            ipAddresses: dscConfig.ipAddresses,
            ports: dscConfig.ports,
            usesDhcpPlaceholder: dscConfig.usesDhcpPlaceholder,
            usesExplicitIp: dscConfig.usesExplicitIp,
          }
        : null,
      rawSummary: parsed.rawSummary,
    };
    records.push(record);
    countMapInc(byFrameClass, parsed.frameClass);
    countMapInc(byTypeA, parsed.typeA);
  }
  return { records, byFrameClass, byTypeA };
}

function createAnalysis({ inputPath, packets, jsonErrors }) {
  const { records, byFrameClass, byTypeA } = createRecords(packets);
  const dscShort = records.filter((record) => record.frameClass === "DSC_SHORT_24_TYPE_1F00_D2FF");
  const rdsShort = records.filter((record) => record.frameClass === "RDS_SHORT_30_TYPE_1180_D2FF");
  const longConfig = records.filter((record) => CONFIG_CLASSES.has(record.frameClass));
  const dscShortNormalized = normalizedGroupSummary(dscShort);
  const rdsShortNormalized = normalizedGroupSummary(rdsShort);
  const longNormalized = {};
  const longUriSignatures = {};
  for (const frameClass of CONFIG_CLASSES) {
    const classRecords = longConfig.filter((record) => record.frameClass === frameClass);
    longNormalized[frameClass] = normalizedGroupSummary(classRecords);
    longUriSignatures[frameClass] = groupByKey(classRecords, (record) => record.uriSignature || "(none)");
  }

  const longUniqueCounts = Object.fromEntries(
    [...CONFIG_CLASSES].map((frameClass) => [frameClass, longNormalized[frameClass].uniqueCount]),
  );
  const repeatedLongCounts = Object.fromEntries(
    [...CONFIG_CLASSES].map((frameClass) => [frameClass, longNormalized[frameClass].repeatedRecordCount]),
  );
  const repeatedLongUriCounts = Object.fromEntries(
    [...CONFIG_CLASSES].map((frameClass) => [frameClass, longUriSignatures[frameClass].repeatedRecordCount]),
  );
  const hasOnlyKnownProtocolClasses = [...byFrameClass.keys()].every((frameClass) =>
    [
      "DSC_SHORT_24_TYPE_1F00_D2FF",
      "RDS_SHORT_30_TYPE_1180_D2FF",
      "DSC_CONFIG_209_TYPE_1100_46FF",
      "DSC_CONFIG_245_TYPE_1100_46FF",
      "UNKNOWN",
    ].includes(frameClass),
  );

  return {
    generatedAt: new Date().toISOString(),
    inputPath,
    jsonErrors,
    counts: {
      totalPackets: packets.length,
      udpPackets: records.length,
      dscShort24: dscShort.length,
      rdsShort30: rdsShort.length,
      dscConfig209: longConfig.filter((record) => record.frameClass === "DSC_CONFIG_209_TYPE_1100_46FF").length,
      dscConfig245: longConfig.filter((record) => record.frameClass === "DSC_CONFIG_245_TYPE_1100_46FF").length,
      unknown: byFrameClass.get("UNKNOWN") || 0,
    },
    frameClassCounts: countObject(byFrameClass),
    typeACounts: countObject(byTypeA),
    shortFrameStructures: {
      DSC_SHORT_24_TYPE_1F00_D2FF: {
        byteStats: byteStats(dscShort),
        normalizedWithoutSeqUniqueCount: dscShortNormalized.uniqueCount,
        normalizedWithoutSeqRepeatedRecordCount: dscShortNormalized.repeatedRecordCount,
        normalizedWithoutSeqGroups: dscShortNormalized.groups,
        basicallyFixedWithoutSeq: dscShortNormalized.uniqueCount <= 3,
      },
      RDS_SHORT_30_TYPE_1180_D2FF: {
        byteStats: byteStats(rdsShort),
        normalizedWithoutSeqUniqueCount: rdsShortNormalized.uniqueCount,
        normalizedWithoutSeqRepeatedRecordCount: rdsShortNormalized.repeatedRecordCount,
        normalizedWithoutSeqGroups: rdsShortNormalized.groups,
        basicallyFixedWithoutSeq: rdsShortNormalized.uniqueCount <= 3,
      },
    },
    timing: {
      DSC_SHORT_24_TYPE_1F00_D2FF: intervalStats(dscShort),
      RDS_SHORT_30_TYPE_1180_D2FF: intervalStats(rdsShort),
    },
    pairAnalysis: pairAnalysis(dscShort, rdsShort),
    shortLongRelation: surroundingRelation(longConfig, dscShort, 5),
    longRetransmission: {
      normalizedWithoutSeqUniqueCounts: longUniqueCounts,
      repeatedFrameCounts: repeatedLongCounts,
      normalizedWithoutSeqGroups: Object.fromEntries(
        [...CONFIG_CLASSES].map((frameClass) => [frameClass, longNormalized[frameClass].groups]),
      ),
      uriSignatureUniqueCounts: Object.fromEntries(
        [...CONFIG_CLASSES].map((frameClass) => [frameClass, longUriSignatures[frameClass].uniqueCount]),
      ),
      repeatedUriSignatureFrameCounts: repeatedLongUriCounts,
      uriSignatureGroups: Object.fromEntries(
        [...CONFIG_CLASSES].map((frameClass) => [frameClass, longUriSignatures[frameClass].groups]),
      ),
      longRepeatIntervalStats: Object.fromEntries(
        [...CONFIG_CLASSES].map((frameClass) => [
          frameClass,
          intervalStats(longConfig.filter((record) => record.frameClass === frameClass)),
        ]),
      ),
    },
    ackAssessment: {
      suspectedWaitingForAck:
        longConfig.length > 0 &&
        Object.values(repeatedLongUriCounts).some((count) => count > 10) &&
        hasOnlyKnownProtocolClasses,
      evidence: [
        "Long config frames repeat many times while no UDP ACK/reply is implemented in this stage.",
        "Byte-exact long frames are not identical after removing only seqLE, but their URI configuration signatures repeat.",
        "Observed UDP classes remain limited to short periodic/status-like frames and long URI config frames, plus two UNKNOWN text probes.",
        "Long config frames carry stable URI configuration data and recur over time.",
      ],
      caution:
        "This is a conservative transport/protocol-state hypothesis, not a confirmed business meaning. Do not implement ACK until ACK format is reverse engineered.",
    },
  };
}

function renderByteStatsSection(title, structure) {
  return [
    `## ${title}`,
    "",
    table(
      [
        "offset",
        "fixed",
        "fixed value",
        "distinctCount",
        "top values",
        "changesWithSeqLE",
        "seq change rate",
        "changesWithTime",
        "time change rate",
      ],
      structure.byteStats.map((row) => [
        row.offset,
        row.fixed,
        row.fixedValue,
        row.distinctCount,
        row.topValues,
        row.changesWithSeqLE,
        row.seqLinkedChangeRate.toFixed(3),
        row.changesWithTime,
        row.timeLinkedChangeRate.toFixed(3),
      ]),
    ),
    table(
      ["metric", "value"],
      [
        ["normalizedWithoutSeqUniqueCount", structure.normalizedWithoutSeqUniqueCount],
        ["normalizedWithoutSeqRepeatedRecordCount", structure.normalizedWithoutSeqRepeatedRecordCount],
        ["basicallyFixedWithoutSeq", structure.basicallyFixedWithoutSeq],
      ],
    ),
    table(
      ["normalizedHexPrefix", "count", "firstReceivedAt", "lastReceivedAt", "avg repeat interval sec"],
      structure.normalizedWithoutSeqGroups.slice(0, 20).map((group) => [
        group.normalizedHex.slice(0, 96),
        group.count,
        group.firstReceivedAt,
        group.lastReceivedAt,
        formatSeconds(group.intervalStats.average),
      ]),
    ),
  ].join("\n");
}

function renderTimingRows(timing) {
  return Object.entries(timing).map(([frameClass, stats]) => [
    frameClass,
    stats.count,
    formatSeconds(stats.min),
    formatSeconds(stats.max),
    formatSeconds(stats.average),
    formatSeconds(stats.p50),
    formatSeconds(stats.p90),
    formatSeconds(stats.p99),
  ]);
}

function renderMarkdown({ analysis, mdPath, jsonPath }) {
  const lines = [];
  lines.push(`# FSU Short Frame Analysis - ${parseDateStem(analysis.inputPath)}`);
  lines.push("");
  lines.push(`Input: \`${analysis.inputPath}\``);
  lines.push(`Markdown report: \`${mdPath}\``);
  lines.push(`JSON report: \`${jsonPath}\``);
  lines.push(`Generated at: \`${analysis.generatedAt}\``);
  lines.push("");

  lines.push("## 1. Overview");
  lines.push("");
  lines.push(
    table(
      ["metric", "value"],
      [
        ["total packets", analysis.counts.totalPackets],
        ["UDP packets parsed", analysis.counts.udpPackets],
        ["DSC_SHORT_24", analysis.counts.dscShort24],
        ["RDS_SHORT_30", analysis.counts.rdsShort30],
        ["DSC_CONFIG_209", analysis.counts.dscConfig209],
        ["DSC_CONFIG_245", analysis.counts.dscConfig245],
        ["UNKNOWN", analysis.counts.unknown],
        ["invalid JSON lines", analysis.jsonErrors.length],
      ],
    ),
  );
  lines.push(table(["frameClass", "count"], Object.entries(analysis.frameClassCounts)));
  lines.push(table(["typeA", "count"], Object.entries(analysis.typeACounts)));

  lines.push(renderByteStatsSection("2. DSC_SHORT_24 Structure Analysis", analysis.shortFrameStructures.DSC_SHORT_24_TYPE_1F00_D2FF));
  lines.push(renderByteStatsSection("3. RDS_SHORT_30 Structure Analysis", analysis.shortFrameStructures.RDS_SHORT_30_TYPE_1180_D2FF));

  lines.push("## 4. Short Frame Timing Analysis");
  lines.push("");
  lines.push(
    table(
      ["frameClass", "interval count", "min sec", "max sec", "average sec", "p50 sec", "p90 sec", "p99 sec"],
      renderTimingRows(analysis.timing),
    ),
  );

  lines.push("## 5. DSC / RDS Pair Relationship");
  lines.push("");
  lines.push(
    table(
      ["metric", "value"],
      [
        ["same-second buckets with both DSC and RDS", analysis.pairAnalysis.sameSecondBucketCount],
        ["seconds with any short frame", analysis.pairAnalysis.secondsWithAnyShortFrame],
        ["DSC short frames with RDS within 1s", `${analysis.pairAnalysis.dscWithRdsWithin1s}/${analysis.pairAnalysis.dscCount}`],
        ["RDS short frames with DSC within 1s", `${analysis.pairAnalysis.rdsWithDscWithin1s}/${analysis.pairAnalysis.rdsCount}`],
        ["ordering", JSON.stringify(analysis.pairAnalysis.orderCounts)],
        ["seqLE diff distribution", JSON.stringify(analysis.pairAnalysis.seqDiffDistribution)],
        ["delta seconds distribution", analysis.pairAnalysis.deltaSecondsDistribution],
      ],
    ),
  );

  lines.push("## 6. Long Frame Relationship And Repetition");
  lines.push("");
  lines.push(
    table(
      ["frameClass", "long count", "with DSC_SHORT within +/-5s", "before count distribution", "after count distribution", "avg repeat interval sec"],
      Object.entries(analysis.shortLongRelation).map(([frameClass, row]) => [
        frameClass,
        row.longFrameCount,
        row.withDscShortWithinWindow,
        row.beforeCountDistribution,
        row.afterCountDistribution,
        formatSeconds(row.repeatIntervalStats.average),
      ]),
    ),
  );
  lines.push(
    table(
      [
        "frameClass",
        "byte normalized unique count",
        "byte repeated frame count",
        "URI signature unique count",
        "URI signature repeated frame count",
        "interval avg sec",
        "interval p50 sec",
        "interval p90 sec",
      ],
      Object.entries(analysis.longRetransmission.normalizedWithoutSeqUniqueCounts).map(([frameClass, count]) => {
        const timing = analysis.longRetransmission.longRepeatIntervalStats[frameClass];
        return [
          frameClass,
          count,
          analysis.longRetransmission.repeatedFrameCounts[frameClass],
          analysis.longRetransmission.uriSignatureUniqueCounts[frameClass],
          analysis.longRetransmission.repeatedUriSignatureFrameCounts[frameClass],
          formatSeconds(timing.average),
          formatSeconds(timing.p50),
          formatSeconds(timing.p90),
        ];
      }),
    ),
  );
  for (const [frameClass, groups] of Object.entries(analysis.longRetransmission.normalizedWithoutSeqGroups)) {
    lines.push(`### ${frameClass} normalized duplicate groups`);
    lines.push("");
    lines.push(
      table(
        ["normalizedHexPrefix", "count", "firstReceivedAt", "lastReceivedAt", "avg repeat interval sec"],
        groups.slice(0, 20).map((group) => [
          group.normalizedHex.slice(0, 96),
          group.count,
          group.firstReceivedAt,
          group.lastReceivedAt,
          formatSeconds(group.intervalStats.average),
        ]),
      ),
    );
  }
  for (const [frameClass, groups] of Object.entries(analysis.longRetransmission.uriSignatureGroups)) {
    lines.push(`### ${frameClass} URI signature groups`);
    lines.push("");
    lines.push(
      table(
        ["URI signature", "count", "firstReceivedAt", "lastReceivedAt", "avg repeat interval sec"],
        groups.slice(0, 20).map((group) => [
          group.key,
          group.count,
          group.firstReceivedAt,
          group.lastReceivedAt,
          formatSeconds(group.intervalStats.average),
        ]),
      ),
    );
  }

  lines.push("## 7. Is The Device Suspected To Be Waiting For ACK?");
  lines.push("");
  lines.push(
    table(
      ["metric", "value"],
      [
        ["suspectedWaitingForAck", analysis.ackAssessment.suspectedWaitingForAck],
        ["evidence", analysis.ackAssessment.evidence.join("<br>")],
        ["caution", analysis.ackAssessment.caution],
      ],
    ),
  );

  lines.push("## 8. Next Steps");
  lines.push("");
  lines.push("- Reverse engineer ACK format offline from prior generated ack candidates and device behavior; do not send live ACK yet.");
  lines.push("- Re-run this report after a controlled no-ACK capture window to confirm repeat intervals.");
  lines.push("- If ACK research proceeds, keep it behind an explicit disabled-by-default lab flag.");
  lines.push("");

  return `${lines.join("\n")}\n`;
}

function main() {
  const inputPath = path.resolve(process.argv[2] || DEFAULT_INPUT);
  const dateStem = parseDateStem(inputPath);
  const outputDir = path.dirname(inputPath);
  const mdPath = path.join(outputDir, `short-frame-analysis-${dateStem}.md`);
  const jsonPath = path.join(outputDir, `short-frame-analysis-${dateStem}.json`);
  const { packets, errors } = readPackets(inputPath);
  const analysis = createAnalysis({ inputPath, packets, jsonErrors: errors });
  fs.writeFileSync(jsonPath, JSON.stringify(analysis, null, 2), "utf8");
  fs.writeFileSync(mdPath, renderMarkdown({ analysis, mdPath, jsonPath }), "utf8");
  console.log(`markdown: ${mdPath}`);
  console.log(`json: ${jsonPath}`);
  console.log(`DSC_SHORT_24: ${analysis.counts.dscShort24}`);
  console.log(`RDS_SHORT_30: ${analysis.counts.rdsShort30}`);
  console.log(`suspectedWaitingForAck: ${analysis.ackAssessment.suspectedWaitingForAck}`);
}

main();
