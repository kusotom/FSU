#!/usr/bin/env node
'use strict';

/**
 * pick-latest-frame-hex.js
 *
 * OFFLINE ONLY. This script never opens sockets and never sends UDP.
 *
 * Purpose:
 *   Scan an FSU raw JSONL log and extract the latest full raw frame hex
 *   matching total length and typeBytes at offset [4..7].
 *
 * It is intentionally schema-tolerant:
 *   - recursively searches JSON values for hex strings
 *   - prefers field names containing raw/packet/hex/data
 *   - validates candidate frame starts with 6d7e
 *   - validates byte length and typeBytes
 *
 * Usage:
 *   node backend/scripts/pick-latest-frame-hex.js --input backend/logs/fsu_raw_packets/2026-05-01.jsonl --typeBytes 110046ff --length 245
 *
 * Optional:
 *   --channel UDP_DSC
 *   --out backend/logs/fsu_raw_packets/latest-110046ff-245.json
 */

const fs = require('fs');
const path = require('path');

function usage() {
  console.log(`Usage:
  node backend/scripts/pick-latest-frame-hex.js --input <jsonl> --typeBytes <hex4bytes> --length <bytes> [--channel UDP_DSC] [--out <json>]

Examples:
  node backend/scripts/pick-latest-frame-hex.js --input backend/logs/fsu_raw_packets/2026-05-01.jsonl --typeBytes 110046ff --length 245
  node backend/scripts/pick-latest-frame-hex.js --input backend/logs/fsu_raw_packets/2026-05-01.jsonl --typeBytes 110046ff --length 209
`);
}

function argValue(name) {
  const idx = process.argv.indexOf(name);
  if (idx < 0) return null;
  return process.argv[idx + 1] || null;
}

function normalizeHex(s) {
  if (typeof s !== 'string') return null;
  let h = s.trim();
  if (h.startsWith('0x') || h.startsWith('0X')) h = h.slice(2);
  h = h.replace(/[^0-9a-fA-F]/g, '').toLowerCase();
  if (!h || h.length % 2 !== 0) return null;
  return h;
}

function isLikelyFullFrameHex(h) {
  return h && h.length >= 48 && h.startsWith('6d7e');
}

function bytesFromHex(h) {
  const b = Buffer.alloc(h.length / 2);
  for (let i = 0; i < b.length; i++) b[i] = parseInt(h.slice(i*2, i*2+2), 16);
  return b;
}

function getTypeBytes(buf) {
  if (!buf || buf.length < 8) return null;
  return buf.slice(4, 8).toString('hex').toLowerCase();
}

function findHexCandidates(obj, results = [], pathParts = []) {
  if (obj == null) return results;
  if (typeof obj === 'string') {
    const h = normalizeHex(obj);
    if (isLikelyFullFrameHex(h)) {
      const keyPath = pathParts.join('.');
      const score =
        (/raw/i.test(keyPath) ? 10 : 0) +
        (/packet/i.test(keyPath) ? 8 : 0) +
        (/hex/i.test(keyPath) ? 6 : 0) +
        (/data/i.test(keyPath) ? 3 : 0) +
        (h.length > 100 ? 1 : 0);
      results.push({ hex: h, keyPath, score });
    }
    return results;
  }
  if (Array.isArray(obj)) {
    for (let i = 0; i < obj.length; i++) findHexCandidates(obj[i], results, pathParts.concat(String(i)));
    return results;
  }
  if (typeof obj === 'object') {
    for (const [k, v] of Object.entries(obj)) findHexCandidates(v, results, pathParts.concat(k));
    return results;
  }
  return results;
}

function extractTimestamp(obj) {
  const keys = ['timestamp', 'time', 'ts', 'createdAt', 'receivedAt', 'received_at', 'datetime', 'date'];
  for (const k of keys) {
    if (obj && obj[k]) return String(obj[k]);
  }
  return null;
}

function maybeChannelMatches(obj, wanted) {
  if (!wanted) return true;
  const hay = JSON.stringify(obj).toLowerCase();
  return hay.includes(String(wanted).toLowerCase());
}

function main() {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    usage();
    return;
  }

  const input = argValue('--input');
  const typeBytesWant = normalizeHex(argValue('--typeBytes'));
  const lengthWant = Number(argValue('--length'));
  const channelWant = argValue('--channel');
  const out = argValue('--out');

  if (!input || !typeBytesWant || !lengthWant) {
    usage();
    process.exit(1);
  }
  if (typeBytesWant.length !== 8) {
    throw new Error('--typeBytes must be exactly 4 bytes, e.g. 110046ff');
  }
  if (!fs.existsSync(input)) throw new Error(`input not found: ${input}`);

  const lines = fs.readFileSync(input, 'utf8').split(/\r?\n/);
  let totalLines = 0;
  let parsedLines = 0;
  let matchingFrames = 0;
  let latest = null;

  for (let lineNo = 0; lineNo < lines.length; lineNo++) {
    const line = lines[lineNo].trim();
    if (!line) continue;
    totalLines++;

    let obj;
    try {
      obj = JSON.parse(line);
      parsedLines++;
    } catch {
      continue;
    }

    if (!maybeChannelMatches(obj, channelWant)) continue;

    const candidates = findHexCandidates(obj).sort((a, b) => b.score - a.score);
    for (const c of candidates) {
      const buf = bytesFromHex(c.hex);
      if (buf.length !== lengthWant) continue;
      const typeBytes = getTypeBytes(buf);
      if (typeBytes !== typeBytesWant) continue;

      matchingFrames++;
      latest = {
        lineNo: lineNo + 1,
        timestamp: extractTimestamp(obj),
        sourceField: c.keyPath,
        sourceFieldScore: c.score,
        totalLength: buf.length,
        magicHex: buf.slice(0, 2).toString('hex'),
        seqLE: buf[2] | (buf[3] << 8),
        seqBytes: buf.slice(2, 4).toString('hex'),
        typeBytes,
        typeByte: `0x${buf[4].toString(16).padStart(2, '0')}`,
        flagByte: `0x${buf[5].toString(16).padStart(2, '0')}`,
        classByte: `0x${buf[6].toString(16).padStart(2, '0')}`,
        tailByte: `0x${buf[7].toString(16).padStart(2, '0')}`,
        payloadLengthLE: buf[20] | (buf[21] << 8),
        checksumHex: buf.slice(22, 24).toString('hex'),
        rawHex: c.hex,
      };
      break;
    }
  }

  const result = {
    safety: 'offline extractor only; no UDP sent; no ACK sent',
    input,
    filters: {
      typeBytes: typeBytesWant,
      length: lengthWant,
      channel: channelWant || null,
    },
    totalLines,
    parsedLines,
    matchingFrames,
    found: !!latest,
    latest,
    nextCommandExample: latest
      ? `node backend\\scripts\\build-class47-register-response-frame-candidates-offline.js --request-hex "${latest.rawHex}" --payload-hex <payloadHex>`
      : null,
  };

  if (out) {
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify(result, null, 2), 'utf8');
  }
  console.log(JSON.stringify(result, null, 2));
}

try {
  main();
} catch (err) {
  console.error(JSON.stringify({ error: err.message, safety: 'no UDP sent; offline script only' }, null, 2));
  process.exit(1);
}
