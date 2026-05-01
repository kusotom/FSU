#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const path = require("path");

const { parseFsuFrame } = require("../../app/modules/fsu_gateway/parser/fsu-frame-parser");

function cleanHex(value) {
  return String(value || "").replace(/[^0-9a-f]/gi, "").toLowerCase();
}

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) {
      continue;
    }
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

function usage() {
  return [
    "usage:",
    "  node backend/scripts/fsu-ack-experiments/build-ack-candidates.js --raw-hex <hex> --protocol UDP_DSC --remote-address 192.168.100.100 --remote-port 6002 --local-port 9000",
  ].join("\n");
}

function uriHost(uri, fallbackHost) {
  const match = uri.match(/^[a-z]+:\/\/([^:/\]]+|\[[^\]]+\]):(\d+)/i);
  if (!match) {
    return fallbackHost;
  }
  const host = match[1];
  return host === "[dhcp]" ? fallbackHost : host;
}

function uriPort(uri) {
  const match = uri.match(/:(\d{1,5})(?:[/?#]|$)/);
  return match ? Number(match[1]) : null;
}

function candidateBase({ parsed, protocol, warnings }) {
  return {
    targetProtocol: protocol,
    requestFrameClass: parsed.frameClass,
    requestSeqLE: parsed.seqLE,
    requestTypeA: parsed.typeA,
    requestPayloadLengthCandidate: parsed.payloadLengthCandidate,
    warnings,
  };
}

function buildCandidates({ rawHex, protocol, remoteAddress, remotePort, localPort }) {
  const cleaned = cleanHex(rawHex);
  const parsed = parseFsuFrame(cleaned, {
    protocol,
    includePayloadHex: true,
    includeAscii: true,
  });
  const warnings = [
    "experimental candidate only",
    "not confirmed ACK protocol",
    "do not integrate into fsu-gateway",
    "do not send without explicit manual approval and packet capture",
  ];
  const base = candidateBase({ parsed, protocol, warnings });
  const candidates = [];

  if (parsed.frameClass === "DSC_SHORT_24_TYPE_1F00_D2FF") {
    candidates.push({
      candidateName: "CANDIDATE_MIRROR_DSC_SHORT_24_TO_SOURCE",
      ...base,
      targetHost: remoteAddress,
      targetPort: remotePort,
      localPort,
      reason:
        "Mirror the recently received DSC short frame back to the packet source port. High-risk reaction probe only; not a confirmed ACK.",
      ackHex: cleaned,
    });
  }

  if (
    parsed.frameClass === "DSC_CONFIG_209_TYPE_1100_46FF" ||
    parsed.frameClass === "DSC_CONFIG_245_TYPE_1100_46FF"
  ) {
    candidates.push({
      candidateName: "CANDIDATE_MIRROR_DSC_CONFIG_TO_SOURCE",
      ...base,
      targetHost: remoteAddress,
      targetPort: remotePort,
      localPort,
      reason:
        "Mirror the received DSC config long frame to the source port. High-risk network reaction probe only; not a confirmed ACK.",
      ackHex: cleaned,
    });

    candidates.push({
      candidateName: "CANDIDATE_SYNTHETIC_EMPTY_DSC_ACK_NULL",
      ...base,
      targetHost: remoteAddress,
      targetPort: remotePort,
      localPort,
      reason:
        "Placeholder for a future synthetic ACK. ACK type, checksum, and body are not reliable, so ackHex is intentionally null.",
      ackHex: null,
    });
  }

  const dscConfig = parsed.dscConfig;
  if (dscConfig) {
    const seen = new Set();
    for (const uri of dscConfig.udpUris) {
      const port = uriPort(uri);
      if (!port) {
        continue;
      }
      const targetHost = uriHost(uri, remoteAddress);
      const key = `${targetHost}:${port}:${uri}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      candidates.push({
        candidateName: "CANDIDATE_REPLY_TO_DECLARED_URI_PORT",
        ...base,
        targetHost,
        targetPort: port,
        localPort,
        declaredUri: uri,
        reason:
          "Declared URI port candidate only. This does not override source-port reply hypothesis and is not sent by default.",
        ackHex: null,
      });
    }
  }

  return {
    input: {
      rawHexPrefix: cleaned.slice(0, 96),
      protocol,
      remoteAddress,
      remotePort,
      localPort,
    },
    parsedSummary: {
      frameClass: parsed.frameClass,
      seqLE: parsed.seqLE,
      typeA: parsed.typeA,
      payloadLengthCandidate: parsed.payloadLengthCandidate,
      bodyHex: parsed.bodyHex,
      tail2: parsed.bodyTail2,
      tail4: parsed.bodyTail4,
      udpUris: parsed.dscConfig?.udpUris || [],
      ftpUris: parsed.dscConfig?.ftpUris || [],
    },
    candidates,
  };
}

function main() {
  const args = parseArgs(process.argv);
  if (!args["raw-hex"] || !args.protocol || !args["remote-address"] || !args["remote-port"] || !args["local-port"]) {
    console.error(usage());
    process.exit(1);
  }

  const result = buildCandidates({
    rawHex: args["raw-hex"],
    protocol: args.protocol,
    remoteAddress: args["remote-address"],
    remotePort: Number(args["remote-port"]),
    localPort: Number(args["local-port"]),
  });
  console.log(JSON.stringify(result, null, 2));
}

if (require.main === module) {
  main();
}

module.exports = {
  buildCandidates,
};


