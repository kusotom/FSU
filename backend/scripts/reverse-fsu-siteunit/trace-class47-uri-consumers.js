#!/usr/bin/env node
"use strict";

/**
 * Offline URI consumer trace for SiteUnit2 classByte=0x47 service endpoints.
 *
 * SAFETY:
 * - Static/offline only.
 * - Does not send UDP.
 * - Does not run --execute or send-one-shot-ack.js.
 * - Does not modify fsu-gateway runtime reply logic or service.py.
 * - Does not write business tables.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const REVERSE_DIR = path.join(ROOT, "backend", "logs", "fsu_reverse");
const RAW_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets");
const CHANNEL_TRACE = path.join(REVERSE_DIR, `siteunit2-class47-channel-type-trace-${currentDate()}.json`);
const ENDPOINT_USAGE = path.join(REVERSE_DIR, "endpoint-slot-usage-analysis-2026-04-28.json");
const REQUIRED_FIELDS = path.join(REVERSE_DIR, "required-login-fields-analysis-2026-04-28.json");
const URI_STRATEGY = path.join(RAW_DIR, "class47-payload-uri-strategy-analysis-2026-05-01.json");

function pad2(n) {
  return String(n).padStart(2, "0");
}

function currentDate(date = new Date()) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function readJson(filePath, fallback = null) {
  if (!fs.existsSync(filePath)) return fallback;
  return JSON.parse(fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, ""));
}

function byFieldId(list) {
  const map = new Map();
  for (const item of list || []) map.set(Number(item.fieldId), item);
  return map;
}

function renderMarkdown(report) {
  return [
    "# SiteUnit2 class47 URI consumer trace",
    "",
    `Generated at: ${report.generatedAt}`,
    "",
    "## Summary",
    "",
    ...report.summary.map((item) => `- ${item}`),
    "",
    "## URI Direction Assessment",
    "",
    `- Platform remote endpoint evidence: ${report.directionAssessment.platformRemoteEndpointEvidence}`,
    `- FSU self-address evidence: ${report.directionAssessment.fsuSelfAddressEvidence}`,
    `- Local bind/listen evidence: ${report.directionAssessment.localBindListenEvidence}`,
    `- FTP entry required evidence: ${report.directionAssessment.ftpEntryRequiredEvidence}`,
    "",
    "## Channel Consumers",
    "",
    "```json",
    JSON.stringify(report.channels, null, 2),
    "```",
    "",
    "## Port Semantics",
    "",
    "```json",
    JSON.stringify(report.portSemantics, null, 2),
    "```",
    "",
    "## Safety",
    "",
    "- UDP sent: false",
    "- --execute run: false",
    "- send-one-shot-ack.js run: false",
    "- automatic ACK added: false",
    "- fsu-gateway realtime reply logic modified: false",
    "- service.py integrated: false",
    "- business table written: false",
    "",
  ].join("\n");
}

function main() {
  const channelTrace = readJson(CHANNEL_TRACE, null);
  const endpointUsage = readJson(ENDPOINT_USAGE);
  const requiredFields = readJson(REQUIRED_FIELDS);
  const uriStrategy = readJson(URI_STRATEGY, null);
  const usageById = byFieldId(endpointUsage.slotUsage);
  const requiredById = byFieldId(requiredFields.fieldCaseAnalysis);

  const channels = [0, 5, 6, 7, 8, 9].map((channelType) => {
    const usage = usageById.get(channelType) || {};
    const required = requiredById.get(channelType) || {};
    const channelTraceItem = (channelTrace?.channels || []).find((item) => Number(item.channelType) === channelType) || {};
    return {
      channelType,
      meaningCandidate: required.meaningCandidate || usage.meaningCandidate,
      ctxOffsets: usage.ctxOffsets || [],
      writer: usage.writer || required.caseTargetVA,
      rawValueDestination: required.rawValueDestination,
      parsedValueDestination: required.parsedValueDestination,
      parsedAs: "udp://host:port; host string plus numeric port stored into ctx",
      downstreamConsumersRecovered: usage.downstreamReadsRecovered === true,
      networkCallEvidence: usage.networkCallEvidence || [],
      queueFunctionEvidence: usage.queueFunctionEvidence || [],
      usedByFunctions: usage.usedByFunctions || [],
      nearbyStrings: usage.nearbyStrings || [],
      directRunRdsEvidence: /RunRDS|RDS/.test((usage.nearbyStrings || []).join(" ")),
      directRealDataEvidence: /RealData/.test((usage.nearbyStrings || []).join(" ")),
      priorRecommendedEndpoint: usage.recommendedEndpoint || null,
      priorReason: usage.reason || null,
      currentTraceConclusion: channelTraceItem.downstreamSocketChainRecovered
        ? "has downstream socket chain"
        : "no closed downstream socket/sendto chain recovered",
    };
  });

  const directionAssessment = {
    platformRemoteEndpointEvidence: "medium: 0x47 is a DSC login/register response from platform to FSU and values are parsed into DS service endpoint slots.",
    fsuSelfAddressEvidence: "low: 0x46 contains FSU self-advertised URIs, but 0x47 parser labels returned values as service channels and DS service IP config.",
    localBindListenEvidence: "not recovered: no evidence that class47 URI values are used for local bind/listen.",
    ftpEntryRequiredEvidence: "not recovered: required fields 0/5/6/7/8/9 parse udp://host:port; ftp URI is seen in 0x46 self-advertisement, not as required 0x47 entry.",
  };

  const portSemantics = {
    observedClass46Ports: uriStrategy?.class46UriEvolution?.udpPorts || {},
    class47DryRunUris: uriStrategy?.class47DryRun?.payloadEntries || [],
    currentAssessment: [
      "6005 is currently the FSU self-advertised UDP port in 0x46, not necessarily a platform service port for 0x47 payload.",
      "7000 remains platform RDS listener, but channelType 7 -> 7000 lacks closed SiteUnit2 socket consumer proof.",
      "6000 in the current template lacks direct listener evidence in the provided platform context.",
      "9000 was a previous all-DS endpoint candidate, but v1 template used 6000/7000 and was ignored; neither template is proven online.",
    ],
  };

  const report = {
    generatedAt: new Date().toISOString(),
    inputs: {
      channelTrace: CHANNEL_TRACE,
      endpointUsage: ENDPOINT_USAGE,
      requiredFields: REQUIRED_FIELDS,
      uriStrategy: URI_STRATEGY,
    },
    summary: [
      "0x47 URI values are parsed as endpoint strings, not as local bind/listen configuration.",
      "The static evidence supports platform/service endpoint interpretation more than FSU self-address interpretation, but the exact accepted host/port values remain unconfirmed.",
      "No closed consumer chain proves channelType 7 must use RDS 7000.",
      "No closed consumer chain proves channelType 0/5/6/8/9 can all share one port.",
      "No evidence was recovered that an FTP URI entry is required in the 0x47 TLV.",
      "Do not send another one-shot until channel URI values are better supported.",
    ],
    directionAssessment,
    channels,
    portSemantics,
    conclusions: {
      uriLikelyRemotePlatformServiceAddress: true,
      uriCouldBeFsuSelfAddress: false,
      localBindListenUseRecovered: false,
      channel7Rds7000Confirmed: false,
      sharedPortForOtherChannelsConfirmed: false,
      ftpUriRequired: false,
      timeSyncOrFullConfigEntryRequiredEvidence: false,
    },
    safety: {
      udpSent: false,
      executeRun: false,
      sendOneShotAckRun: false,
      ackAdded: false,
      gatewayReplyLogicModified: false,
      servicePyIntegrated: false,
      businessTableWritten: false,
    },
  };

  const date = currentDate();
  const jsonPath = path.join(REVERSE_DIR, `siteunit2-class47-uri-consumer-trace-${date}.json`);
  const mdPath = path.join(REVERSE_DIR, `siteunit2-class47-uri-consumer-trace-${date}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  fs.writeFileSync(mdPath, renderMarkdown(report), "utf8");
  console.log(JSON.stringify({ reportMd: mdPath, reportJson: jsonPath, conclusions: report.conclusions }, null, 2));
}

main();
