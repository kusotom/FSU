#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const KEYWORDS = [
  "LOGIN",
  "HEART",
  "HEARTBEAT",
  "REALDATA",
  "RDSREALDATA",
  "ALARM",
  "EVENT",
  "ACK",
  "Register",
  "FSU",
  "XML",
  "SOAP",
];

const DEFAULT_INPUT = path.join(__dirname, "..", "logs", "fsu_raw_packets", "2026-04-28.jsonl");
const inputPath = path.resolve(process.argv[2] || DEFAULT_INPUT);

function fail(message) {
  console.error(message);
  process.exit(1);
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

function table(headers, rows) {
  const escapeCell = (value) => String(value ?? "").replace(/\r?\n/g, "<br>").replace(/\|/g, "\\|");
  return [
    `| ${headers.map(escapeCell).join(" |")} |`,
    `| ${headers.map(() => "---").join(" |")} |`,
    ...rows.map((row) => `| ${row.map(escapeCell).join(" |")} |`),
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

function asciiFromBuffer(buf) {
  let out = "";
  for (const byte of buf) {
    out += byte >= 0x20 && byte <= 0x7e ? String.fromCharCode(byte) : ".";
  }
  return out;
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

function hexDump(buf, width = 16) {
  if (!buf.length) {
    return "(empty)";
  }
  const lines = [];
  for (let offset = 0; offset < buf.length; offset += width) {
    const chunk = buf.subarray(offset, offset + width);
    const hex = [...chunk].map((byte) => byte.toString(16).padStart(2, "0")).join(" ");
    const padded = hex.padEnd(width * 3 - 1, " ");
    lines.push(`${offset.toString(16).padStart(4, "0")}  ${padded}  |${asciiFromBuffer(chunk)}|`);
  }
  return lines.join("\n");
}

function truncateText(value, max = 600) {
  const text = String(value || "");
  if (text.length <= max) {
    return text;
  }
  return `${text.slice(0, max)}... [truncated ${text.length - max} chars]`;
}

function commonPrefix(values) {
  if (!values.length) {
    return "";
  }
  let prefix = values[0] || "";
  for (const value of values.slice(1)) {
    let i = 0;
    while (i < prefix.length && i < value.length && prefix[i] === value[i]) {
      i += 1;
    }
    prefix = prefix.slice(0, i);
    if (!prefix) {
      break;
    }
  }
  return prefix.length % 2 === 0 ? prefix : prefix.slice(0, -1);
}

function maskedFirst8(rawHex) {
  const hex = String(rawHex || "");
  if (hex.length < 16) {
    return hex;
  }
  return `${hex.slice(0, 4)}????${hex.slice(8, 16)}`;
}

function parseDateStem(filePath) {
  const base = path.basename(filePath);
  const match = base.match(/(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : new Date().toISOString().slice(0, 10);
}

function readPackets(filePath) {
  if (!fs.existsSync(filePath)) {
    fail(`input file not found: ${filePath}`);
  }
  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  const packets = [];
  const errors = [];
  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }
    try {
      const packet = JSON.parse(trimmed);
      packet.__line = index + 1;
      packet.__buf = hexToBuffer(packet.rawHex);
      packet.__ascii = asciiFromBuffer(packet.__buf);
      packet.__spans = printableSpans(packet.__buf);
      packets.push(packet);
    } catch (error) {
      errors.push({ line: index + 1, error: error.message });
    }
  });
  return { packets, errors };
}

function createStats(packets) {
  const stats = {
    total: packets.length,
    byProtocol: new Map(),
    byLocalPort: new Map(),
    byRemoteAddress: new Map(),
    protocols: new Map(),
    keywords: new Map(KEYWORDS.map((keyword) => [keyword, 0])),
  };

  for (const packet of packets) {
    const protocol = packet.protocol || "(empty)";
    countMapInc(stats.byProtocol, protocol);
    countMapInc(stats.byLocalPort, packet.localPort);
    countMapInc(stats.byRemoteAddress, packet.remoteAddress);
    if (!stats.protocols.has(protocol)) {
      stats.protocols.set(protocol, {
        packets: [],
        lengthDist: new Map(),
        prefix16: new Map(),
        prefix32: new Map(),
        prefix2Bytes: new Map(),
        prefix4Bytes: new Map(),
        prefix8Bytes: new Map(),
        maskedFirst8: new Map(),
        asciiSpans: new Map(),
        keywords: new Map(KEYWORDS.map((keyword) => [keyword, 0])),
      });
    }
    const perProtocol = stats.protocols.get(protocol);
    perProtocol.packets.push(packet);
    countMapInc(perProtocol.lengthDist, packet.length);
    countMapInc(perProtocol.prefix16, String(packet.rawHex || "").slice(0, 32));
    countMapInc(perProtocol.prefix32, String(packet.rawHex || "").slice(0, 64));
    countMapInc(perProtocol.prefix2Bytes, String(packet.rawHex || "").slice(0, 4));
    countMapInc(perProtocol.prefix4Bytes, String(packet.rawHex || "").slice(0, 8));
    countMapInc(perProtocol.prefix8Bytes, String(packet.rawHex || "").slice(0, 16));
    countMapInc(perProtocol.maskedFirst8, maskedFirst8(packet.rawHex));

    for (const span of packet.__spans) {
      countMapInc(perProtocol.asciiSpans, span.text);
    }

    const haystack = `${packet.rawText || ""}\n${packet.__ascii || ""}`;
    for (const keyword of KEYWORDS) {
      const re = new RegExp(keyword, "i");
      if (re.test(haystack)) {
        countMapInc(stats.keywords, keyword);
        countMapInc(perProtocol.keywords, keyword);
      }
    }
  }

  return stats;
}

function samplePackets(packets) {
  const sortedAsc = [...packets].sort((a, b) => Number(a.length || 0) - Number(b.length || 0) || a.__line - b.__line);
  const sortedDesc = [...packets].sort((a, b) => Number(b.length || 0) - Number(a.length || 0) || a.__line - b.__line);
  const lengthDist = new Map();
  for (const packet of packets) {
    countMapInc(lengthDist, packet.length);
  }
  const [commonLength] = topEntries(lengthDist, 1)[0] || [undefined, 0];
  return {
    shortest: sortedAsc.slice(0, 5),
    longest: sortedDesc.slice(0, 5),
    commonLength,
    commonLengthSamples: packets.filter((packet) => String(packet.length) === String(commonLength)).slice(0, 10),
    recent: packets.slice(-20),
  };
}

function renderPacket(packet, heading) {
  const buf = packet.__buf || hexToBuffer(packet.rawHex);
  const spans = packet.__spans || printableSpans(buf);
  const visibleText = spans.slice(0, 8).map((span) => `${span.start}-${span.end}: ${span.text}`).join("; ") || "(none)";
  return [
    `#### ${heading}`,
    "",
    table(
      ["field", "value"],
      [
        ["line", packet.__line],
        ["receivedAt", packet.receivedAt],
        ["protocol", packet.protocol],
        ["remoteAddress", packet.remoteAddress],
        ["remotePort", packet.remotePort],
        ["localPort", packet.localPort],
        ["length", packet.length],
        ["first4", String(packet.rawHex || "").slice(0, 8)],
        ["first8", String(packet.rawHex || "").slice(0, 16)],
        ["last2", String(packet.rawHex || "").slice(-4)],
        ["last4", String(packet.rawHex || "").slice(-8)],
        ["printable ascii spans", visibleText],
      ],
    ),
    "**rawHex**",
    "",
    "```text",
    packet.rawHex || "",
    "```",
    "",
    "**rawText**",
    "",
    "```text",
    truncateText(packet.rawText || ""),
    "```",
    "",
    "**hex dump**",
    "",
    "```text",
    hexDump(buf),
    "```",
    "",
  ].join("\n");
}

function renderSamples(protocol, packets) {
  const samples = samplePackets(packets);
  const sections = [];
  const groups = [
    ["Shortest 5", samples.shortest],
    ["Longest 5", samples.longest],
    [`Most common length ${samples.commonLength} - first 10`, samples.commonLengthSamples],
    ["Recent 20", samples.recent],
  ];
  for (const [title, items] of groups) {
    sections.push(`### ${protocol} - ${title}`, "");
    items.forEach((packet, index) => {
      sections.push(renderPacket(packet, `${title} #${index + 1}`));
    });
  }
  return sections.join("\n");
}

function renderReport(filePath, packets, errors, stats) {
  const udpPackets = packets.filter((packet) => packet.protocol === "UDP_DSC" || packet.protocol === "UDP_RDS");
  const dateStem = parseDateStem(filePath);
  const lines = [
    `# FSU Raw Packet Analysis - ${dateStem}`,
    "",
    `Input: \`${filePath}\``,
    "",
    "## Overall Statistics",
    "",
    table(
      ["metric", "value"],
      [
        ["total parsed packets", stats.total],
        ["UDP_DSC packets", stats.byProtocol.get("UDP_DSC") || 0],
        ["UDP_RDS packets", stats.byProtocol.get("UDP_RDS") || 0],
        ["other packets", stats.total - udpPackets.length],
        ["parse errors", errors.length],
      ],
    ),
    "### By Protocol",
    "",
    table(["protocol", "count"], topEntries(stats.byProtocol, 50)),
    "### By Local Port",
    "",
    table(["localPort", "count"], topEntries(stats.byLocalPort, 50)),
    "### By Remote Address",
    "",
    table(["remoteAddress", "count"], topEntries(stats.byRemoteAddress, 50)),
    "### Keyword Scan",
    "",
    table(["keyword", "packet count"], topEntries(stats.keywords, KEYWORDS.length)),
  ];

  for (const protocol of ["UDP_DSC", "UDP_RDS"]) {
    const perProtocol = stats.protocols.get(protocol);
    if (!perProtocol) {
      lines.push(`## ${protocol}`, "", "No packets found.", "");
      continue;
    }
    const protocolPackets = perProtocol.packets;
    const prefixes = protocolPackets.map((packet) => String(packet.rawHex || ""));
    const commonHexPrefix = commonPrefix(prefixes);

    lines.push(
      `## ${protocol} Statistics`,
      "",
      table(
        ["metric", "value"],
        [
          ["packet count", protocolPackets.length],
          ["common hex prefix across packets", commonHexPrefix || "(none)"],
          ["common prefix bytes", commonHexPrefix ? commonHexPrefix.match(/../g).join(" ") : "(none)"],
          ["has printable ASCII spans", perProtocol.asciiSpans.size > 0 ? "yes" : "no"],
        ],
      ),
      "### Length Distribution",
      "",
      table(["length", "count"], topEntries(perProtocol.lengthDist, 50)),
      "### RawHex Prefix Distribution - First 16 Bytes",
      "",
      table(["first16BytesHex", "count"], topEntries(perProtocol.prefix16, 20)),
      "### RawHex Prefix Distribution - First 32 Bytes",
      "",
      table(["first32BytesHex", "count"], topEntries(perProtocol.prefix32, 20)),
      "### First 2 Bytes Distribution",
      "",
      table(["first2BytesHex", "count"], topEntries(perProtocol.prefix2Bytes, 20)),
      "### First 4 Bytes Distribution",
      "",
      table(["first4BytesHex", "count"], topEntries(perProtocol.prefix4Bytes, 20)),
      "### First 8 Bytes Distribution",
      "",
      table(["first8BytesHex", "count"], topEntries(perProtocol.prefix8Bytes, 20)),
      "### Masked First 8 Bytes Distribution",
      "",
      "This masks bytes 2-3 as `????` to reduce sequence/counter noise without assigning protocol meaning.",
      "",
      table(["maskedFirst8Hex", "count"], topEntries(perProtocol.maskedFirst8, 20)),
      "### Printable ASCII Spans",
      "",
      table(["ascii", "count"], topEntries(perProtocol.asciiSpans, 30)),
      "### Keyword Scan",
      "",
      table(["keyword", "packet count"], topEntries(perProtocol.keywords, KEYWORDS.length)),
    );
  }

  lines.push(
    "## Samples",
    "",
    renderSamples("UDP_DSC", (stats.protocols.get("UDP_DSC") || { packets: [] }).packets),
    renderSamples("UDP_RDS", (stats.protocols.get("UDP_RDS") || { packets: [] }).packets),
    "## Initial Judgement",
    "",
    "- UDP_DSC and UDP_RDS packets use binary framing; rawHex is the authoritative source.",
    "- The dominant first two bytes are expected to show whether there is a fixed packet header.",
    "- Repeated short packet lengths suggest heartbeat/ACK/control frames, but this report does not assign protocol meaning.",
    "- Printable ASCII spans are treated only as hints for endpoint strings or embedded text.",
    "- No business database write or alarm parsing is performed by this analysis.",
    "",
    "## Next Suggestions",
    "",
    "- Keep collecting raw packets while the FSU is online, especially across reboot and configuration reload.",
    "- Compare repeated length groups and first 16/32-byte prefixes to isolate frame classes.",
    "- Build a parser fixture set from representative rawHex samples before writing any live parser.",
    "- Validate candidate length/checksum fields against many packets before relying on them.",
    "- Only after frame classes are stable should the parser emit normalized telemetry or alarm candidates.",
    "",
  );

  if (errors.length) {
    lines.push(
      "## Parse Errors",
      "",
      table(["line", "error"], errors.slice(0, 50).map((error) => [error.line, error.error])),
    );
  }

  return lines.join("\n");
}

function main() {
  const { packets, errors } = readPackets(inputPath);
  const stats = createStats(packets);
  const dateStem = parseDateStem(inputPath);
  const reportPath = path.join(path.dirname(inputPath), `analysis-${dateStem}.md`);
  const report = renderReport(inputPath, packets, errors, stats);
  fs.writeFileSync(reportPath, report, "utf8");

  const dsc = stats.protocols.get("UDP_DSC") || {
    packets: [],
    lengthDist: new Map(),
    prefix2Bytes: new Map(),
    prefix4Bytes: new Map(),
    prefix8Bytes: new Map(),
    maskedFirst8: new Map(),
    prefix16: new Map(),
    asciiSpans: new Map(),
  };
  const rds = stats.protocols.get("UDP_RDS") || {
    packets: [],
    lengthDist: new Map(),
    prefix2Bytes: new Map(),
    prefix4Bytes: new Map(),
    prefix8Bytes: new Map(),
    maskedFirst8: new Map(),
    prefix16: new Map(),
    asciiSpans: new Map(),
  };
  const summary = {
    inputPath,
    reportPath,
    totalPackets: stats.total,
    udpDscPackets: dsc.packets.length,
    udpRdsPackets: rds.packets.length,
    udpDscCommonLengths: topEntries(dsc.lengthDist, 5),
    udpRdsCommonLengths: topEntries(rds.lengthDist, 5),
    udpDscCommonFirst2Bytes: topEntries(dsc.prefix2Bytes, 5),
    udpRdsCommonFirst2Bytes: topEntries(rds.prefix2Bytes, 5),
    udpDscCommonFirst8Bytes: topEntries(dsc.prefix8Bytes, 5),
    udpRdsCommonFirst8Bytes: topEntries(rds.prefix8Bytes, 5),
    udpDscMaskedFirst8: topEntries(dsc.maskedFirst8, 5),
    udpRdsMaskedFirst8: topEntries(rds.maskedFirst8, 5),
    udpDscCommonPrefixes16: topEntries(dsc.prefix16, 5),
    udpRdsCommonPrefixes16: topEntries(rds.prefix16, 5),
    udpDscHasAscii: dsc.asciiSpans.size > 0,
    udpRdsHasAscii: rds.asciiSpans.size > 0,
    parseErrors: errors.length,
  };
  console.log(JSON.stringify(summary, null, 2));
}

main();
