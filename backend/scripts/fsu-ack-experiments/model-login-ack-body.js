#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

function parseArgs(argv) {
  const args = { entries: [] };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--entry") {
      args.entries.push(argv[i + 1]);
      i += 1;
      continue;
    }
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

function parseIntStrict(value, name) {
  const text = String(value ?? "");
  const parsed = /^0x/i.test(text) ? Number.parseInt(text, 16) : Number.parseInt(text, 10);
  if (!Number.isInteger(parsed)) throw new Error(`invalid ${name}: ${value}`);
  return parsed;
}

function parseEntry(text) {
  const match = String(text).match(/^(\d+|0x[0-9a-f]+)=(.*)$/i);
  if (!match) throw new Error(`invalid --entry ${text}; expected fieldId=value`);
  const fieldId = parseIntStrict(match[1], "fieldId");
  if (fieldId < 0 || fieldId > 255) throw new Error(`fieldId out of range: ${fieldId}`);
  const value = Buffer.from(match[2], "utf8");
  if (value.length > 255) throw new Error(`entry value too long for uint8 length: ${fieldId}`);
  return { fieldId, valueText: match[2], valueHex: value.toString("hex"), valueLength: value.length };
}

function buildBody(status, entries) {
  const body = [status & 0xff, entries.length & 0xff, (entries.length >>> 8) & 0xff];
  for (const entry of entries) {
    body.push(entry.fieldId & 0xff, entry.valueLength & 0xff);
    for (const byte of Buffer.from(entry.valueText, "utf8")) body.push(byte);
  }
  return Buffer.from(body);
}

const REQUIRED_FIELD_IDS = [0, 5, 6, 7, 8, 9];

function entriesFromEndpointMap(endpointMap) {
  return REQUIRED_FIELD_IDS.map((fieldId) => {
    const valueText = endpointMap[fieldId];
    const value = Buffer.from(valueText, "utf8");
    return { fieldId, valueText, valueHex: value.toString("hex"), valueLength: value.length };
  });
}

function buildProfile(name, endpointMap) {
  if (!endpointMap) {
    return {
      name,
      status: "incomplete",
      entryCount: null,
      entries: [],
      bodyHexCandidate: null,
      requiredFlagsSatisfied: false,
      requiredFieldIds: REQUIRED_FIELD_IDS,
      ackHex: null,
      doNotSend: true,
      safeToSend: false,
      warnings: ["endpoint mapping is not closed", "body only; no frame header/type/seq/checksum", "do not send"],
    };
  }
  const entries = entriesFromEndpointMap(endpointMap);
  const body = buildBody(0, entries);
  return {
    name,
    profileName: name,
    status: "candidate",
    entryCount: entries.length,
    entries,
    bodyHexCandidate: body.toString("hex"),
    requiredFlagsSatisfied: true,
    requiredFieldIds: REQUIRED_FIELD_IDS,
    ackHex: null,
    doNotSend: true,
    safeToSend: false,
    warnings: [
      "body only; no frame header/type/seq/checksum",
      "endpoint values are candidates and not live-confirmed",
      "do not send",
    ],
  };
}

function buildCandidateProfiles(platformHost = "192.168.100.123") {
  const all9000 = Object.fromEntries(REQUIRED_FIELD_IDS.map((fieldId) => [fieldId, `udp://${platformHost}:9000`]));
  const all7000 = Object.fromEntries(REQUIRED_FIELD_IDS.map((fieldId) => [fieldId, `udp://${platformHost}:7000`]));
  const recommended = all9000;
  return [
    buildProfile("recommended_profile", recommended),
    buildProfile("all_9000_profile", all9000),
    buildProfile("mixed_9000_7000_profile", {
      0: `udp://${platformHost}:9000`,
      5: `udp://${platformHost}:7000`,
      6: `udp://${platformHost}:7000`,
      7: `udp://${platformHost}:7000`,
      8: `udp://${platformHost}:7000`,
      9: `udp://${platformHost}:7000`,
    }),
    buildProfile("all_7000_profile", all7000),
    buildProfile("unknown_profile", null),
  ];
}

module.exports = {
  buildBody,
  buildCandidateProfiles,
  parseArgs,
  parseEntry,
  parseIntStrict,
  REQUIRED_FIELD_IDS,
};

function main() {
  const args = parseArgs(process.argv);
  const status = parseIntStrict(args.status ?? 0, "status");
  if (status < 0 || status > 255) throw new Error(`status out of range: ${status}`);
  const entries = (args.entries || []).map(parseEntry);
  const requiredFieldIds = REQUIRED_FIELD_IDS;
  const presentFieldIds = new Set(entries.map((entry) => entry.fieldId));
  const missingRequiredFieldIds = requiredFieldIds.filter((fieldId) => !presentFieldIds.has(fieldId));
  const requiredFlagsSatisfied = missingRequiredFieldIds.length === 0;
  const explicitEntryCount = args["entry-count"] !== undefined ? parseIntStrict(args["entry-count"], "entry-count") : null;
  const warnings = [
    "body only; no frame header/type/seq/checksum",
    "field meanings and endpoint values are not fully confirmed",
    "do not send",
  ];
  if (explicitEntryCount !== null && explicitEntryCount !== entries.length) {
    warnings.push(`--entry-count ${explicitEntryCount} differs from provided entries ${entries.length}; output uses provided entries.`);
  }
  if (!requiredFlagsSatisfied) {
    warnings.push(`required fieldIds missing: ${missingRequiredFieldIds.join(",")}`);
  }
  const body = buildBody(status, entries);
  const result = {
    status,
    entryCount: entries.length,
    entries,
    bodyHexCandidate: body.toString("hex"),
    requiredFlagsSatisfied,
    requiredFieldIds,
    missingRequiredFieldIds,
    ackHex: null,
    doNotSend: true,
    warnings,
  };
  if (args.profiles) {
    result.profiles = buildCandidateProfiles(args["platform-host"] || "192.168.100.123");
  }
  console.log(JSON.stringify(result, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}


