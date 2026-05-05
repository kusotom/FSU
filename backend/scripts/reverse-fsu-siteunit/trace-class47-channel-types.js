#!/usr/bin/env node
"use strict";

/**
 * Offline aggregation report for SiteUnit2 classByte=0x47 channelType parsing.
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
const DEFAULT_REQUIRED_FIELDS = path.join(REVERSE_DIR, "required-login-fields-analysis-2026-04-28.json");
const DEFAULT_ENDPOINT_USAGE = path.join(REVERSE_DIR, "endpoint-slot-usage-analysis-2026-04-28.json");
const DEFAULT_CLASS47_ENTRY = path.join(REVERSE_DIR, "siteunit2-class47-payload-entry-analysis-2026-05-01.json");

function pad2(n) {
  return String(n).padStart(2, "0");
}

function dateStamp(date = new Date()) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, ""));
}

function byFieldId(list) {
  const map = new Map();
  for (const item of list || []) map.set(Number(item.fieldId), item);
  return map;
}

function shortHits(hits) {
  return (hits || []).slice(0, 12).map((hit) => ({
    vaHex: hit.vaHex,
    instruction: hit.instruction,
    accessKind: hit.accessKind,
    readWidth: hit.readWidth,
    nearbyStrings: hit.nearbyStrings || [],
    networkCallNearby: hit.networkCallNearby || [],
    participatesInNetworkCall: hit.participatesInNetworkCall === true,
  }));
}

function renderMarkdown(report) {
  return [
    "# SiteUnit2 classByte=0x47 channelType trace",
    "",
    `Generated at: ${report.generatedAt}`,
    "",
    "## Summary",
    "",
    ...report.summary.map((item) => `- ${item}`),
    "",
    "## Channel Table",
    "",
    "| channelType | meaning | writer | raw slot | parsed slot | downstream socket chain | confidence |",
    "| --- | --- | --- | --- | --- | --- | --- |",
    ...report.channels.map((item) => `| ${item.channelType} | ${item.meaningCandidate} | ${item.caseTargetVA} | ${item.rawValueDestination} | ${item.parsedValueDestination} | ${item.downstreamSocketChainRecovered ? "yes" : "no"} | ${item.confidence} |`),
    "",
    "## Detailed Channels",
    "",
    "```json",
    JSON.stringify(report.channels, null, 2),
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
  const required = readJson(DEFAULT_REQUIRED_FIELDS);
  const usage = readJson(DEFAULT_ENDPOINT_USAGE);
  const entry = readJson(DEFAULT_CLASS47_ENTRY);
  const usageById = byFieldId(usage.slotUsage);
  const channels = required.fieldCaseAnalysis
    .filter((item) => [0, 5, 6, 7, 8, 9].includes(Number(item.fieldId)))
    .map((item) => {
      const usageItem = usageById.get(Number(item.fieldId)) || {};
      return {
        channelType: Number(item.fieldId),
        meaningCandidate: item.meaningCandidate,
        flagMask: item.flagMask,
        caseTargetVA: item.caseTargetVA,
        rawValueDestination: item.rawValueDestination,
        parsedValueDestination: item.parsedValueDestination,
        logStringVA: item.logStringVA,
        logString: item.logString,
        parserEvidence: item.evidence || [],
        valueTypeCandidate: item.valueTypeCandidate,
        validation: item.validation,
        storesRawAndParsed: item.storesRawAndParsed,
        usageSummary: {
          usedByFunctions: usageItem.usedByFunctions || [],
          nearbyStrings: usageItem.nearbyStrings || [],
          networkCallEvidence: usageItem.networkCallEvidence || [],
          queueFunctionEvidence: usageItem.queueFunctionEvidence || [],
          downstreamReadsRecovered: usageItem.downstreamReadsRecovered === true,
          recommendedEndpointFromPriorReport: usageItem.recommendedEndpoint || null,
          priorConfidence: usageItem.confidence || null,
          priorReason: usageItem.reason || null,
          sampleFullTextHits: shortHits(usageItem.fullTextHits),
        },
        downstreamSocketChainRecovered: (usageItem.networkCallEvidence || []).length > 0,
        directRunRdsOrSendRealDataEvidence: (usageItem.queueFunctionEvidence || []).length > 0,
        confidence: item.confidence,
      };
    });

  const report = {
    generatedAt: new Date().toISOString(),
    inputs: {
      requiredFields: DEFAULT_REQUIRED_FIELDS,
      endpointUsage: DEFAULT_ENDPOINT_USAGE,
      class47Entry: DEFAULT_CLASS47_ENTRY,
    },
    payloadFormat: entry.payloadFormat,
    requiredMask: entry.requiredMask,
    requiredChannels: entry.requiredChannels,
    summary: [
      "classByte=0x47 body is a TLV-like list: status, serviceCountLE, then channelType/uriLength/uri.",
      "Required Success channelTypes remain 0,5,6,7,8,9 and mask must reach 0x3f.",
      "Each required channel value is parsed as udp://host:port; firmware skips the 6-byte udp:// prefix and stores host/port into per-channel ctx slots.",
      "The previous endpoint-slot scan did not recover a clean downstream socket/sendto consumer chain for the six slots.",
      "No evidence was recovered that a FTP URI entry is required in the 0x47 success TLV.",
      "No evidence was recovered that the TLV entry format includes priority/protocol/reserved bytes beyond channelType,length,uri.",
    ],
    channels,
    conclusions: {
      tlvFormatConfirmed: true,
      requiredMaskConfirmed: "0x3f",
      requiredChannels: [0, 5, 6, 7, 8, 9],
      uriFormat: "udp://host:port",
      downstreamSocketChainRecovered: false,
      ftpUriRequiredEvidence: false,
      extraFieldEvidence: false,
      channel7Rds7000Evidence: "not directly recovered; channel 7 is real-time data by log string, but no closed socket/sendto xref ties it to RDS 7000",
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

  const date = dateStamp();
  const jsonPath = path.join(REVERSE_DIR, `siteunit2-class47-channel-type-trace-${date}.json`);
  const mdPath = path.join(REVERSE_DIR, `siteunit2-class47-channel-type-trace-${date}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  fs.writeFileSync(mdPath, renderMarkdown(report), "utf8");
  console.log(JSON.stringify({ reportMd: mdPath, reportJson: jsonPath, conclusions: report.conclusions }, null, 2));
}

main();
