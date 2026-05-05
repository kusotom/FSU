#!/usr/bin/env node
"use strict";

/**
 * Read-only classByte=0x46 URI evolution analysis.
 *
 * SAFETY:
 * - Does not send UDP.
 * - Does not run send-one-shot-ack.js.
 * - Does not modify fsu-gateway runtime reply logic.
 * - Does not write business tables.
 */

const fs = require("fs");
const path = require("path");
const {
  findHexCandidate,
  parseFsuFrame,
} = require("../app/modules/fsu_gateway/parser/fsu-frame-v03-utils");

const ROOT = path.resolve(__dirname, "..", "..");
const DEFAULT_INPUT = path.join(ROOT, "backend", "logs", "fsu_raw_packets", "2026-05-01.jsonl");
const DEFAULT_OUT_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets");
const DEVICE_IP = "192.168.100.100";

function parseArgs(argv) {
  const args = { input: DEFAULT_INPUT, outDir: DEFAULT_OUT_DIR };
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (key === "--input") args.input = path.resolve(argv[++i]);
    else if (key === "--out-dir") args.outDir = path.resolve(argv[++i]);
  }
  return args;
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function logDate(input) {
  const match = /(\d{4}-\d{2}-\d{2})\.jsonl$/i.exec(input);
  if (match) return match[1];
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function inc(map, key) {
  map[key] = (map[key] || 0) + 1;
}

function addRange(map, key, timestamp) {
  if (!key) return;
  if (!map[key]) map[key] = { count: 0, firstSeen: timestamp, lastSeen: timestamp };
  map[key].count += 1;
  if (timestamp && (!map[key].firstSeen || timestamp < map[key].firstSeen)) map[key].firstSeen = timestamp;
  if (timestamp && (!map[key].lastSeen || timestamp > map[key].lastSeen)) map[key].lastSeen = timestamp;
}

function extractUris(buffer) {
  const ascii = buffer.toString("latin1");
  const out = { udp: [], ftp: [] };
  const patterns = {
    udp: /udp:\/\/(?:\[[^\]]+\]|[A-Za-z0-9_.-]+):\d+/g,
    ftp: /ftp:\/\/[^\s\x00]+/g,
  };
  for (const [kind, regex] of Object.entries(patterns)) {
    let match;
    while ((match = regex.exec(ascii)) !== null) {
      const uri = match[0].replace(/[^\x20-\x7e].*$/, "");
      const parsedUdp = /^udp:\/\/(.+):(\d+)$/.exec(uri);
      out[kind].push({
        uri,
        host: parsedUdp ? parsedUdp[1].replace(/^\[|\]$/g, "") : null,
        port: parsedUdp ? Number(parsedUdp[2]) : null,
        offset: match.index,
      });
    }
  }
  return out;
}

function frameClassFor(parsed) {
  if (parsed.typeBytesSummary === "110046ff" && parsed.totalLength === 209) return "DSC_CONFIG_209_TYPE_1100_46FF";
  if (parsed.typeBytesSummary === "110046ff" && parsed.totalLength === 245) return "DSC_CONFIG_245_TYPE_1100_46FF";
  return "OTHER";
}

function renderMarkdown(report) {
  const lines = [
    "# DSC classByte=0x46 URI evolution analysis",
    "",
    `Generated at: ${report.generatedAt}`,
    `Input: ${report.input}`,
    "",
    "## Summary",
    "",
    `- 209 count: ${report.counts.length209}`,
    `- 245 count: ${report.counts.length245}`,
    `- UDP URI ports: ${Object.entries(report.distribution.udpPorts).map(([k, v]) => `${k}=${v}`).join(", ") || "none"}`,
    `- UDP URI hosts: ${Object.entries(report.distribution.udpHosts).map(([k, v]) => `${k}=${v}`).join(", ") || "none"}`,
    `- Three UDP URIs identical in all sampled 0x46 frames: ${report.conclusions.threeUdpUrisAlwaysIdentical}`,
    `- 209/245 latest URI sets equal: ${report.conclusions.latest209245UriSetEqual}`,
    `- 6002 observed: ${report.conclusions.port6002Observed}`,
    `- 6005 observed: ${report.conclusions.port6005Observed}`,
    "",
    "## URI Time Ranges",
    "",
    "```json",
    JSON.stringify(report.uriRanges, null, 2),
    "```",
    "",
    "## Recent 20 classByte=0x46 Frames",
    "",
    "```json",
    JSON.stringify(report.recent20, null, 2),
    "```",
    "",
    "## Conclusions",
    "",
    ...report.conclusionNotes.map((item) => `- ${item}`),
    "",
    "## Safety",
    "",
    "- UDP sent: false",
    "- ACK added: false",
    "- send-one-shot-ack.js run: false",
    "- fsu-gateway reply logic modified: false",
    "- business table written: false",
    "",
  ];
  return lines.join("\n");
}

function main() {
  const args = parseArgs(process.argv);
  const lines = fs.readFileSync(args.input, "utf8").split(/\r?\n/);
  const frames = [];
  const distribution = {
    byFrameClass: {},
    udpHosts: {},
    udpPorts: {},
    ftpHosts: {},
    uriCounts: {},
  };
  const uriRanges = {};
  let length209 = 0;
  let length245 = 0;

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.trim()) continue;
    let entry;
    try { entry = JSON.parse(line); } catch { continue; }
    if (entry.remoteAddress !== DEVICE_IP || entry.protocol !== "UDP_DSC") continue;
    const rawHex = findHexCandidate(entry);
    if (!rawHex) continue;
    const buffer = Buffer.from(rawHex, "hex");
    const parsed = parseFsuFrame(buffer);
    if (!parsed.ok || parsed.typeBytesSummary !== "110046ff") continue;
    if (![209, 245].includes(parsed.totalLength)) continue;
    const frameClass = frameClassFor(parsed);
    if (parsed.totalLength === 209) length209 += 1;
    if (parsed.totalLength === 245) length245 += 1;
    inc(distribution.byFrameClass, frameClass);
    const uris = extractUris(buffer);
    for (const item of uris.udp) {
      inc(distribution.udpHosts, item.host || "unknown");
      inc(distribution.udpPorts, String(item.port));
      inc(distribution.uriCounts, item.uri);
      addRange(uriRanges, item.uri, entry.receivedAt);
    }
    for (const item of uris.ftp) {
      const hostMatch = /@([^\/:]+)/.exec(item.uri);
      inc(distribution.ftpHosts, hostMatch ? hostMatch[1].replace(/^\[|\]$/g, "") : "unknown");
      inc(distribution.uriCounts, item.uri);
      addRange(uriRanges, item.uri, entry.receivedAt);
    }
    frames.push({
      lineNo: i + 1,
      receivedAt: entry.receivedAt,
      frameClass,
      length: parsed.totalLength,
      seqLE: parsed.seqLE,
      remotePort: entry.remotePort,
      udpUris: uris.udp.map((item) => item.uri),
      ftpUris: uris.ftp.map((item) => item.uri),
      threeUdpUrisIdentical: uris.udp.length === 3 && new Set(uris.udp.map((item) => item.uri)).size === 1,
    });
  }

  const latest209 = [...frames].reverse().find((item) => item.length === 209) || null;
  const latest245 = [...frames].reverse().find((item) => item.length === 245) || null;
  const latest209Set = latest209 ? JSON.stringify([...latest209.udpUris, ...latest209.ftpUris].sort()) : null;
  const latest245Set = latest245 ? JSON.stringify([...latest245.udpUris, ...latest245.ftpUris].sort()) : null;
  const ports = Object.keys(distribution.udpPorts);
  const report = {
    generatedAt: new Date().toISOString(),
    input: args.input,
    counts: { length209, length245, total0x46: frames.length },
    distribution,
    uriRanges,
    recent20: frames.slice(-20),
    latest209,
    latest245,
    conclusions: {
      port6002Observed: ports.includes("6002"),
      port6005Observed: ports.includes("6005"),
      threeUdpUrisAlwaysIdentical: frames.length > 0 && frames.every((item) => item.threeUdpUrisIdentical),
      latest209245UriSetEqual: latest209Set !== null && latest209Set === latest245Set,
    },
    conclusionNotes: [
      ports.includes("6005")
        ? "The current 0x46 payload evidence includes declared UDP port 6005."
        : "No 6005 UDP URI was found in the scanned 0x46 payloads.",
      ports.includes("6002")
        ? "Historical 0x46 payload evidence includes declared UDP port 6002."
        : "No 6002 UDP URI was found in the scanned 0x46 payloads.",
      "The declared UDP URI should be treated as evolving field evidence rather than a fixed constant.",
      "This report does not justify any additional packet send.",
    ],
    safety: {
      udpSent: false,
      ackAdded: false,
      sendOneShotAckRun: false,
      gatewayReplyLogicModified: false,
      businessTableWritten: false,
    },
  };

  fs.mkdirSync(args.outDir, { recursive: true });
  const date = logDate(args.input);
  const jsonPath = path.join(args.outDir, `class46-uri-evolution-${date}.json`);
  const mdPath = path.join(args.outDir, `class46-uri-evolution-${date}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  fs.writeFileSync(mdPath, renderMarkdown(report), "utf8");
  console.log(JSON.stringify({ reportMd: mdPath, reportJson: jsonPath, counts: report.counts, conclusions: report.conclusions }, null, 2));
}

main();
