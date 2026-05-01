#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

function cleanHex(rawHex) {
  return String(rawHex || "").replace(/[^0-9a-f]/gi, "").toLowerCase();
}

function readInput(arg) {
  if (!arg) {
    return null;
  }
  if (fs.existsSync(arg)) {
    const text = fs.readFileSync(arg, "utf8").trim();
    if (!text) {
      return null;
    }
    const firstLine = text.split(/\r?\n/).find(Boolean);
    try {
      const json = JSON.parse(firstLine);
      return json.rawHex || json.parsed?.rawHex || json.parsed?.rawSummary?.rawHex || json.ackHex || firstLine;
    } catch {
      return firstLine;
    }
  }
  return arg;
}

function inferDeclaredUriPorts(parsed) {
  if (!parsed.dscConfig) {
    return [];
  }
  return [...new Set(parsed.dscConfig.ports)];
}

function buildCandidates({ rawHex, protocol, remoteAddress, remotePort }) {
  const parsed = parseFsuFrame(rawHex, { protocol, includeAscii: true });
  const declaredPorts = inferDeclaredUriPorts(parsed);
  const warnings = [
    "offline research only",
    "do not send these candidates without a controlled experiment plan",
    "ACK type/body/checksum are not confirmed",
  ];

  const base = {
    targetProtocol: protocol || parsed.protocol || "",
    targetHost: remoteAddress || null,
    requestSeqLE: parsed.seqLE,
    requestTypeA: parsed.typeA,
    warnings,
  };

  const candidates = [
    {
      candidateName: "mirror-seq empty-body candidate",
      ...base,
      targetPort: remotePort || null,
      reason:
        "Would mirror request sequence with zero payload if ACK type/checksum were known; currently insufficient evidence.",
      ackHex: null,
    },
    {
      candidateName: "mirror-seq short-body candidate",
      ...base,
      targetPort: remotePort || null,
      reason:
        "Would include a minimal status body if firmware confirms an ACK body schema; currently insufficient evidence.",
      ackHex: null,
    },
    {
      candidateName: "reply-to-source-port candidate",
      ...base,
      targetPort: remotePort || null,
      reason:
        "UDP replies normally target the datagram source port, but ACK command/checksum are not confirmed.",
      ackHex: null,
    },
  ];

  for (const port of declaredPorts) {
    candidates.push({
      candidateName: "reply-to-declared-uri-port candidate",
      ...base,
      targetPort: port,
      reason:
        "Declared URI port is present in the config payload; use only as a research target until endpoint behavior is confirmed.",
      ackHex: null,
    });
  }

  return {
    inputSummary: {
      frameClass: parsed.frameClass,
      seqLE: parsed.seqLE,
      typeA: parsed.typeA,
      payloadLengthCandidate: parsed.payloadLengthCandidate,
      declaredUriPorts: declaredPorts,
      rawHexPrefix: cleanHex(rawHex).slice(0, 64),
    },
    candidates,
  };
}

function main() {
  const rawInput = readInput(process.argv[2]);
  if (!rawInput) {
    console.error("usage: node backend/scripts/build-fsu-ack-candidates.js <rawHex|jsonl-file> [protocol] [remoteAddress] [remotePort]");
    process.exit(1);
  }

  const result = buildCandidates({
    rawHex: rawInput,
    protocol: process.argv[3] || "UDP_DSC",
    remoteAddress: process.argv[4] || null,
    remotePort: process.argv[5] ? Number(process.argv[5]) : null,
  });
  console.log(JSON.stringify(result, null, 2));
}

main();
