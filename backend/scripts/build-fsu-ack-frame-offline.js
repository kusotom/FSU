#!/usr/bin/env node
/**
 * Offline FSU ACK candidate builder.
 *
 * SAFETY:
 * - Does not open sockets.
 * - Does not send UDP.
 * - Only prints a candidate ACK hex derived from a supplied raw packet hex.
 */
const { buildAckCandidate, normalizeHex } = require("../app/modules/fsu_gateway/parser/fsu-frame-v03-utils");

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === "--hex") args.hex = argv[++i];
    else if (argv[i] === "--json") args.json = true;
  }
  return args;
}

const args = parseArgs(process.argv);
if (!args.hex) {
  console.error("Usage: node backend/scripts/build-fsu-ack-frame-offline.js --hex <rawPacketHex> [--json]");
  process.exit(2);
}

try {
  const hex = normalizeHex(args.hex);
  const result = buildAckCandidate(hex);
  const out = {
    safety: {
      offlineOnly: true,
      udpSent: false,
      socketOpened: false
    },
    original: {
      totalLength: result.original.totalLength,
      typeA: result.original.typeA,
      typeBytesSummary: result.original.typeBytesSummary,
      seqLE: result.original.seqLE,
      ackRequiredFlag: result.original.ackRequiredFlag,
      checksumStoredHex: result.original.checksumStoredHex,
      checksumCalculatedHex: result.original.checksumCalculatedHex,
      checksumValid: result.original.checksumValid
    },
    ack: {
      totalLength: result.ack.totalLength,
      typeA: result.ack.typeA,
      typeBytesSummary: result.ack.typeBytesSummary,
      seqLE: result.ack.seqLE,
      checksumStoredHex: result.ack.checksumStoredHex,
      checksumCalculatedHex: result.ack.checksumCalculatedHex,
      checksumValid: result.ack.checksumValid,
      ackHex: result.ackHex
    }
  };

  if (args.json) {
    console.log(JSON.stringify(out, null, 2));
  } else {
    console.log("offlineOnly: true");
    console.log("udpSent: false");
    console.log(`original.typeA: ${out.original.typeA}`);
    console.log(`original.ackRequiredFlag: ${out.original.ackRequiredFlag}`);
    console.log(`ack.typeA: ${out.ack.typeA}`);
    console.log(`ack.checksumValid: ${out.ack.checksumValid}`);
    console.log(`ackHex: ${out.ack.ackHex}`);
  }
} catch (err) {
  console.error(`ERROR: ${err.message}`);
  process.exit(1);
}
