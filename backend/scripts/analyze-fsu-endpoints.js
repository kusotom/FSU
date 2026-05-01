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

function classifyRemotePort(port) {
  const value = Number(port);
  if (value === 6000) {
    return "6000";
  }
  if (value === 6002) {
    return "6002";
  }
  if (value >= 49152 && value <= 65535) {
    return "random-high-port";
  }
  return "other";
}

function createAnalysis(inputPath, packets, jsonErrors) {
  const protocolEndpointCounts = new Map();
  const protocolRemotePortCounts = new Map();
  const remotePortClassCounts = new Map();
  const uriCounts = new Map();
  const uriPortCounts = new Map();
  const sourceVsUriPortCounts = new Map();
  const sourceVsLocalCounts = new Map();
  const sourcePortByFrameClass = new Map();
  const longFrameExamples = [];

  for (const packet of packets) {
    if (packet.protocol !== "UDP_DSC" && packet.protocol !== "UDP_RDS") {
      continue;
    }
    const protocol = packet.protocol;
    const remotePort = packet.remotePort;
    const localPort = packet.localPort;
    countMapInc(protocolEndpointCounts, `${protocol} ${packet.remoteAddress}:${remotePort} -> local:${localPort}`);
    countMapInc(protocolRemotePortCounts, `${protocol}:${remotePort}`);
    countMapInc(remotePortClassCounts, `${protocol}:${classifyRemotePort(remotePort)}`);
    countMapInc(sourceVsLocalCounts, `${protocol}:source=${remotePort}:local=${localPort}`);

    const parsed = parseFsuFrame(packet.rawHex, { protocol, includeAscii: true });
    countMapInc(sourcePortByFrameClass, `${parsed.frameClass}:source=${remotePort}`);
    const dscConfig = parsed.dscConfig;
    if (!dscConfig) {
      continue;
    }

    const uris = [...dscConfig.udpUris, ...dscConfig.ftpUris];
    for (const uri of uris) {
      countMapInc(uriCounts, uri);
    }
    for (const port of dscConfig.ports) {
      countMapInc(uriPortCounts, port);
      countMapInc(sourceVsUriPortCounts, `${parsed.frameClass}:source=${remotePort}:uri=${port}`);
    }
    if (longFrameExamples.length < 20) {
      longFrameExamples.push({
        receivedAt: packet.receivedAt,
        frameClass: parsed.frameClass,
        remoteAddress: packet.remoteAddress,
        remotePort,
        localPort,
        udpUris: dscConfig.udpUris,
        ftpUris: dscConfig.ftpUris,
        ports: dscConfig.ports,
      });
    }
  }

  const sourceIsDeclaredUdpPort = topEntries(sourceVsUriPortCounts).some(([key, count]) => {
    const match = key.match(/source=(\d+):uri=(\d+)/);
    return match && match[1] === match[2] && count > 0;
  });
  const dscSourcePorts = topEntries(protocolRemotePortCounts)
    .filter(([key]) => key.startsWith("UDP_DSC:"))
    .map(([key]) => Number(key.split(":")[1]));
  const rdsSourcePorts = topEntries(protocolRemotePortCounts)
    .filter(([key]) => key.startsWith("UDP_RDS:"))
    .map(([key]) => Number(key.split(":")[1]));

  return {
    generatedAt: new Date().toISOString(),
    inputPath,
    jsonErrors,
    protocolEndpointCounts: countObject(protocolEndpointCounts),
    protocolRemotePortCounts: countObject(protocolRemotePortCounts),
    remotePortClassCounts: countObject(remotePortClassCounts),
    sourceVsLocalCounts: countObject(sourceVsLocalCounts),
    sourcePortByFrameClass: countObject(sourcePortByFrameClass),
    longFrameUriCounts: countObject(uriCounts),
    longFrameUriPortCounts: countObject(uriPortCounts),
    sourceVsUriPortCounts: countObject(sourceVsUriPortCounts),
    longFrameExamples,
    interpretation: {
      dscSourcePorts,
      rdsSourcePorts,
      sourceIsDeclaredUdpPort,
      likelyReplyTarget:
        sourceIsDeclaredUdpPort || dscSourcePorts.includes(6000) || dscSourcePorts.includes(6002)
          ? "source remotePort observed on inbound packet"
          : "undetermined; source port evidence is weak",
      rationale:
        "For UDP request/response behavior, the immediate reply normally targets the packet source address and source port. The declared URI ports describe service endpoints inside the payload; they must not be assumed to override the datagram source port without firmware or experiment evidence.",
    },
  };
}

function renderMarkdown(analysis, mdPath, jsonPath) {
  const lines = [];
  lines.push(`# FSU Endpoint Analysis - ${parseDateStem(analysis.inputPath)}`);
  lines.push("");
  lines.push(`Input: \`${analysis.inputPath}\``);
  lines.push(`Markdown report: \`${mdPath}\``);
  lines.push(`JSON report: \`${jsonPath}\``);
  lines.push(`Generated at: \`${analysis.generatedAt}\``);
  lines.push("");

  lines.push("## 1. Protocol Endpoint Counts");
  lines.push("");
  lines.push(table(["endpoint", "count"], Object.entries(analysis.protocolEndpointCounts)));

  lines.push("## 2. Remote Port Distribution");
  lines.push("");
  lines.push(table(["protocol:remotePort", "count"], Object.entries(analysis.protocolRemotePortCounts)));
  lines.push(table(["protocol:remotePortClass", "count"], Object.entries(analysis.remotePortClassCounts)));

  lines.push("## 3. Long Frame URI Port Distribution");
  lines.push("");
  lines.push(table(["URI", "count"], Object.entries(analysis.longFrameUriCounts)));
  lines.push(table(["URI port", "count"], Object.entries(analysis.longFrameUriPortCounts)));

  lines.push("## 4. Source Port vs Declared URI Port");
  lines.push("");
  lines.push(table(["frameClass/source/uriPort", "count"], Object.entries(analysis.sourceVsUriPortCounts)));
  lines.push(table(["frameClass/sourcePort", "count"], Object.entries(analysis.sourcePortByFrameClass)));
  lines.push(table(["protocol/source/local", "count"], Object.entries(analysis.sourceVsLocalCounts)));

  lines.push("## 5. Long Frame Examples");
  lines.push("");
  lines.push(
    table(
      ["receivedAt", "frameClass", "remote", "localPort", "udpUris", "ftpUris", "ports"],
      analysis.longFrameExamples.map((row) => [
        row.receivedAt,
        row.frameClass,
        `${row.remoteAddress}:${row.remotePort}`,
        row.localPort,
        row.udpUris.join("<br>"),
        row.ftpUris.join("<br>"),
        row.ports.join(", "),
      ]),
    ),
  );

  lines.push("## 6. Reply Target Assessment");
  lines.push("");
  lines.push(
    table(
      ["metric", "value"],
      [
        ["likelyReplyTarget", analysis.interpretation.likelyReplyTarget],
        ["DSC source ports", analysis.interpretation.dscSourcePorts.join(", ")],
        ["RDS source ports", analysis.interpretation.rdsSourcePorts.join(", ")],
        ["sourceIsDeclaredUdpPort", analysis.interpretation.sourceIsDeclaredUdpPort],
        ["rationale", analysis.interpretation.rationale],
      ],
    ),
  );

  return `${lines.join("\n")}\n`;
}

function main() {
  const inputPath = path.resolve(process.argv[2] || DEFAULT_INPUT);
  const dateStem = parseDateStem(inputPath);
  const outputDir = path.dirname(inputPath);
  const mdPath = path.join(outputDir, `endpoint-analysis-${dateStem}.md`);
  const jsonPath = path.join(outputDir, `endpoint-analysis-${dateStem}.json`);
  const { packets, errors } = readPackets(inputPath);
  const analysis = createAnalysis(inputPath, packets, errors);
  fs.writeFileSync(jsonPath, JSON.stringify(analysis, null, 2), "utf8");
  fs.writeFileSync(mdPath, renderMarkdown(analysis, mdPath, jsonPath), "utf8");
  console.log(`markdown: ${mdPath}`);
  console.log(`json: ${jsonPath}`);
}

main();
