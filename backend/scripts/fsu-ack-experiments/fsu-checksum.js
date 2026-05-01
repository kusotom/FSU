#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const CHECKSUM_OFFSET = 22;
const MIN_FRAME_LENGTH = 24;

function assertFrameBuffer(buffer) {
  if (!Buffer.isBuffer(buffer)) {
    throw new TypeError("buffer must be a Buffer");
  }
  if (buffer.length < MIN_FRAME_LENGTH) {
    throw new RangeError(`buffer must be at least ${MIN_FRAME_LENGTH} bytes`);
  }
}

function computeParseDataChecksum(buffer) {
  assertFrameBuffer(buffer);
  const copy = Buffer.from(buffer);
  copy[CHECKSUM_OFFSET] = 0;
  copy[CHECKSUM_OFFSET + 1] = 0;

  let sum = 0;
  for (let offset = 2; offset < copy.length; offset += 1) {
    sum = (sum + copy[offset]) & 0xffff;
  }
  return sum;
}

function writeChecksumLE(buffer) {
  assertFrameBuffer(buffer);
  const checksum = computeParseDataChecksum(buffer);
  buffer.writeUInt16LE(checksum, CHECKSUM_OFFSET);
  return checksum;
}

module.exports = {
  CHECKSUM_OFFSET,
  MIN_FRAME_LENGTH,
  computeParseDataChecksum,
  writeChecksumLE,
};

if (require.main === module) {
  console.log("This module exports computeParseDataChecksum(buffer) and writeChecksumLE(buffer).");
}


