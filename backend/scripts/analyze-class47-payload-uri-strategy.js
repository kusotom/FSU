#!/usr/bin/env node
"use strict";

/**
 * Read-only URI strategy postmortem after class47 one-shot v2 block.
 *
 * SAFETY:
 * - Does not send UDP.
 * - Does not run --execute.
 * - Does not run send-one-shot-ack.js.
 * - Does not modify fsu-gateway runtime reply logic.
 * - Does not write business tables.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const RAW_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets");
const ONE_SHOT_DIR = path.join(RAW_DIR, "class47-one-shot");
const DEFAULT_URI_EVOLUTION = path.join(RAW_DIR, "class46-uri-evolution-2026-05-01.json");
const DEFAULT_DRY_RUN = path.join(ONE_SHOT_DIR, "class47-one-shot-dry-run-2026-05-01-214458.json");
const DEFAULT_V1_RESULT = path.join(ONE_SHOT_DIR, "class47-one-shot-experiment-result-2026-05-01-212647.json");
const DEFAULT_V2_BLOCKED = path.join(ONE_SHOT_DIR, "class47-one-shot-experiment-v2-declared6002-2026-05-01-214458.json");
const DEFAULT_FINAL_MAP = path.join(RAW_DIR, "final-offline-protocol-map-v1.4-2026-05-01.json");

function pad2(n) {
  return String(n).padStart(2, "0");
}

function stamp(date = new Date()) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}-${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, ""));
}

function parseArgs(argv) {
  const args = {
    uriEvolution: DEFAULT_URI_EVOLUTION,
    dryRun: DEFAULT_DRY_RUN,
    v1Result: DEFAULT_V1_RESULT,
    v2Blocked: DEFAULT_V2_BLOCKED,
    finalMap: DEFAULT_FINAL_MAP,
    outDir: RAW_DIR,
    oneShotOutDir: ONE_SHOT_DIR,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (key === "--uri-evolution") args.uriEvolution = path.resolve(argv[++i]);
    else if (key === "--dry-run") args.dryRun = path.resolve(argv[++i]);
    else if (key === "--v1-result") args.v1Result = path.resolve(argv[++i]);
    else if (key === "--v2-blocked") args.v2Blocked = path.resolve(argv[++i]);
    else if (key === "--final-map") args.finalMap = path.resolve(argv[++i]);
    else if (key === "--out-dir") args.outDir = path.resolve(argv[++i]);
    else if (key === "--one-shot-out-dir") args.oneShotOutDir = path.resolve(argv[++i]);
  }
  return args;
}

function serviceChannelEvidence(finalMap) {
  const channels = finalMap.class47Candidate?.payload?.serviceChannels || {};
  return Object.entries(channels).map(([channelType, info]) => ({
    channelType: Number(channelType),
    chineseName: info.chineseName,
    valueFormat: info.valueFormat,
    requiredMask: info.requiredMask,
    confidence: info.confidence,
    source: "final-offline-protocol-map-v1.4",
  }));
}

function renderStrategyMarkdown(report) {
  return [
    "# class47 payload URI strategy analysis",
    "",
    `Generated at: ${report.generatedAt}`,
    "",
    "## Summary",
    "",
    `- v1 verdict: ${report.v1.verdict}`,
    `- v2 status: ${report.v2.verdict}`,
    `- Current declared UDP ports: ${Object.entries(report.class46UriEvolution.udpPorts).map(([k, v]) => `${k}=${v}`).join(", ") || "none"}`,
    `- Current class47 dry-run target mode: ${report.class47DryRun.targetStrategy.targetMode}`,
    `- Current class47 dry-run resolved target: ${report.class47DryRun.targetStrategy.targetHost}:${report.class47DryRun.targetStrategy.targetPort}`,
    "",
    "## class47 Payload Entries",
    "",
    "```json",
    JSON.stringify(report.class47DryRun.payloadEntries, null, 2),
    "```",
    "",
    "## Firmware / Offline Service Channel Evidence",
    "",
    "```json",
    JSON.stringify(report.staticEvidence.serviceChannels, null, 2),
    "```",
    "",
    "## Candidate URI Strategies",
    "",
    "```json",
    JSON.stringify(report.candidateUriStrategies, null, 2),
    "```",
    "",
    "## Conclusions",
    "",
    ...report.conclusionNotes.map((item) => `- ${item}`),
    "",
    "## Safety",
    "",
    "- UDP sent: false",
    "- --execute run: false",
    "- send-one-shot-ack.js run: false",
    "- automatic ACK added: false",
    "- fsu-gateway reply logic modified: false",
    "- service.py integrated: false",
    "- business table written: false",
    "",
  ].join("\n");
}

function renderPostmortemMarkdown(report) {
  return [
    "# class47 one-shot v2 blocked URI postmortem",
    "",
    `Generated at: ${report.generatedAt}`,
    "",
    "## Summary",
    "",
    `- v1: ${report.v1.summary}`,
    `- v2: ${report.v2.summary}`,
    `- Current actual declared UDP port: ${report.currentDeclaredPort}`,
    "",
    "## Key Findings",
    "",
    ...report.keyFindings.map((item) => `- ${item}`),
    "",
    "## Candidate URI Strategies",
    "",
    "```json",
    JSON.stringify(report.candidateUriStrategies, null, 2),
    "```",
    "",
    "## Recommendation",
    "",
    report.recommendation,
    "",
    "## Safety",
    "",
    "- UDP sent: false",
    "- --execute run: false",
    "- send-one-shot-ack.js run: false",
    "- automatic ACK added: false",
    "- fsu-gateway reply logic modified: false",
    "- service.py integrated: false",
    "- business table written: false",
    "- firmware flashed: false",
    "",
  ].join("\n");
}

function main() {
  const args = parseArgs(process.argv);
  const uriEvolution = readJson(args.uriEvolution);
  const dryRun = readJson(args.dryRun);
  const v1Result = readJson(args.v1Result);
  const v2Blocked = readJson(args.v2Blocked);
  const finalMap = readJson(args.finalMap);
  const generatedAt = new Date().toISOString();

  const udpPorts = uriEvolution.distribution?.udpPorts || {};
  const latestUris = dryRun.targetStrategy?.declaredUdpUris || [];
  const currentDeclaredPort = latestUris[0]?.port || null;
  const serviceChannels = serviceChannelEvidence(finalMap);
  const payloadEntries = dryRun.payload?.entries || [];
  const class47Uris = payloadEntries.map((entry) => ({ channelType: entry.channelType, uri: entry.uri, valueLength: entry.valueLength }));

  const candidateUriStrategies = [
    {
      name: "candidate A",
      description: "Keep the current template values: channel 0/5/6/8/9 use udp://192.168.100.123:6000 and channel 7 uses udp://192.168.100.123:7000.",
      evidence: [
        "Matches the current dry-run implementation.",
        "Uses local platform-facing service addresses rather than FSU self-declared addresses.",
      ],
      risks: [
        "v1 using this payload shape was ignored when sent to source port 6005.",
        "6000 has not been proven as a local listener in the current platform description.",
      ],
      shouldSendNow: false,
    },
    {
      name: "candidate B",
      description: "Keep channel 7 mapped to local RDS listener 7000, but re-model channel 0/5/6/8/9 against actual platform DS/service ports before any future one-shot.",
      evidence: [
        "Offline map labels channelType 7 as real data channel.",
        "Platform RDS listener is 7000.",
      ],
      risks: [
        "No static evidence yet proves which local port each non-7 channel expects.",
        "May still miss required DSC/config/time-sync channels.",
      ],
      shouldSendNow: false,
    },
    {
      name: "candidate C",
      description: "Re-map class47 service URIs from SiteUnit2 channel type usage and current 0x46 URI evolution before constructing another candidate.",
      evidence: [
        "0x46 declared URI has evolved to udp://192.168.100.100:6005, invalidating a fixed 6002 assumption.",
        "v1 ignored suggests payload URI mapping may be a stronger variable than target port.",
      ],
      risks: [
        "Requires more offline static evidence before another live test.",
      ],
      shouldSendNow: false,
    },
  ];

  const strategyReport = {
    generatedAt,
    inputs: {
      uriEvolution: args.uriEvolution,
      dryRun: args.dryRun,
      v1Result: args.v1Result,
      v2Blocked: args.v2Blocked,
      finalMap: args.finalMap,
    },
    v1: {
      verdict: v1Result.preliminaryVerdict,
      sent: v1Result.execute?.sent,
      sendCount: v1Result.execute?.sendCount,
      target: "192.168.100.100:6005",
    },
    v2: {
      verdict: v2Blocked.preliminaryVerdict,
      sent: v2Blocked.sent,
      sendCount: v2Blocked.sendCount,
      reason: v2Blocked.blockedReasons,
    },
    class46UriEvolution: {
      counts: uriEvolution.counts,
      udpPorts,
      udpHosts: uriEvolution.distribution?.udpHosts || {},
      latest209: uriEvolution.latest209,
      latest245: uriEvolution.latest245,
      recent20: uriEvolution.recent20,
    },
    class47DryRun: {
      targetStrategy: dryRun.targetStrategy,
      payloadEntries: class47Uris,
      candidateFrame: {
        typeBytes: dryRun.candidateFrame?.typeBytes,
        totalLength: dryRun.candidateFrame?.totalLength,
        payloadLength: dryRun.candidateFrame?.payloadLength,
        checksumValid: dryRun.candidateFrame?.checksumValid,
        frameHexSha256: dryRun.candidateFrame?.frameHexSha256,
      },
    },
    staticEvidence: {
      serviceChannels,
      notes: [
        "Offline map identifies channelType 7 as real data channel.",
        "Offline map does not prove the online-accepted URI values.",
        "SiteUnit2/static evidence still needs deeper tracing for exact service endpoint semantics.",
      ],
    },
    candidateUriStrategies,
    conclusionNotes: [
      "v1 was sent exactly once to 6005 and was ignored within the 120-second observation window.",
      "v2 declared-6002 was correctly blocked because the current 0x46 payload declares 6005, not 6002.",
      "Do not continue assuming 6002 as a fixed declared port.",
      "The next high-value offline variable is class47 payload URI strategy, not another blind target-port send.",
    ],
    safety: {
      udpSent: false,
      executeRun: false,
      sendOneShotAckRun: false,
      ackAdded: false,
      gatewayReplyLogicModified: false,
      servicePyIntegrated: false,
      businessTableWritten: false,
      firmwareFlashed: false,
    },
  };

  const postmortemReport = {
    generatedAt,
    v1: {
      summary: "110047ff was sent once to 192.168.100.100:6005 and observed as ignored_candidate.",
      report: args.v1Result,
    },
    v2: {
      summary: "declared-6002 was blocked because the latest 0x46 payload declared 6005, not 6002.",
      report: args.v2Blocked,
    },
    currentDeclaredPort,
    keyFindings: [
      "The current 0x46 payload actual declared UDP port is 6005.",
      "The current evidence does not support forcing target port 6002.",
      "Because v1 already targeted 6005 and was ignored, the next likely issue is payload URI/channel strategy or another class47/header requirement.",
      "No additional packet should be sent until URI/channel evidence is improved offline.",
    ],
    candidateUriStrategies,
    recommendation: "Do not send another class47 packet now. First trace SiteUnit2 service channel usage and re-model class47 payload URI values.",
    safety: strategyReport.safety,
  };

  fs.mkdirSync(args.outDir, { recursive: true });
  fs.mkdirSync(args.oneShotOutDir, { recursive: true });
  const date = "2026-05-01";
  const strategyJson = path.join(args.outDir, `class47-payload-uri-strategy-analysis-${date}.json`);
  const strategyMd = path.join(args.outDir, `class47-payload-uri-strategy-analysis-${date}.md`);
  const postBase = path.join(args.oneShotOutDir, `class47-one-shot-v2-blocked-uri-postmortem-${stamp()}`);
  fs.writeFileSync(strategyJson, `${JSON.stringify(strategyReport, null, 2)}\n`, "utf8");
  fs.writeFileSync(strategyMd, renderStrategyMarkdown(strategyReport), "utf8");
  fs.writeFileSync(`${postBase}.json`, `${JSON.stringify(postmortemReport, null, 2)}\n`, "utf8");
  fs.writeFileSync(`${postBase}.md`, renderPostmortemMarkdown(postmortemReport), "utf8");
  console.log(JSON.stringify({
    strategyReportMd: strategyMd,
    strategyReportJson: strategyJson,
    postmortemMd: `${postBase}.md`,
    postmortemJson: `${postBase}.json`,
    currentDeclaredPort,
    safety: strategyReport.safety,
  }, null, 2));
}

main();
