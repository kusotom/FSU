#!/usr/bin/env node
'use strict';

/**
 * build-class47-register-response-frame-candidates-offline.js
 *
 * OFFLINE ONLY. This script never opens a socket and never sends UDP.
 *
 * Purpose:
 *   Build full-frame candidates for DSC classByte=0x47 register/config response
 *   using an already-built 0x47 payload hex.
 *
 * It can optionally copy sequence and header context from a real 0x46 request frame,
 * then replace type bytes and payload.
 *
 * Current frame header model:
 *   [0..1]   magic = 6d 7e
 *   [2..3]   sequence, copied from request or specified
 *   [4]      typeByte candidate
 *   [5]      flagByte candidate
 *   [6]      classByte = 0x47
 *   [7]      tailByte candidate, usually 0xff
 *   [8..19]  copied from request header if --request-hex provided, otherwise zero
 *   [20..21] payloadLength LE
 *   [22..23] checksum LE candidate
 *   [24..]   payload
 *
 * Checksum model:
 *   copy frame
 *   set [22]=0, [23]=0
 *   sum bytes[2..end] as uint16
 *   store LE at [22..23]
 *
 * SAFETY:
 *   This outputs JSON only. Do not send any generated frame.
 */

const fs = require('fs');

function usage() {
  console.log(`Usage:
  node backend/scripts/build-class47-register-response-frame-candidates-offline.js --payload-hex <hex> [options]

Options:
  --payload-hex <hex>       Required. classByte=0x47 payload hex.
  --request-hex <hex>       Optional. A real 0x46 request frame hex; copy seq and bytes[8..19].
  --seq-le <number>         Optional. sequence value as decimal or 0x hex, little-endian.
  --seq-hex <hhhh>          Optional. raw two sequence bytes, e.g. "6b01".
  --out <path>              Optional. write JSON result to path.
  --include-unsafe-note     Include extra warning field.

Examples:
  node backend/scripts/build-class47-register-response-frame-candidates-offline.js --payload-hex 000600...

  node backend/scripts/build-class47-register-response-frame-candidates-offline.js --request-hex <110046ff request hex> --payload-hex <payload hex>
`);
}

function argValue(name) {
  const idx = process.argv.indexOf(name);
  if (idx < 0) return null;
  return process.argv[idx + 1] || null;
}

function normalizeHex(s, label) {
  if (!s) throw new Error(`${label} is required`);
  const h = String(s).replace(/^0x/i, '').replace(/[^0-9a-fA-F]/g, '').toLowerCase();
  if (!h || h.length % 2 !== 0) {
    throw new Error(`${label} must be even-length hex`);
  }
  return h;
}

function bytesFromHex(s, label) {
  const h = normalizeHex(s, label);
  const out = Buffer.alloc(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.slice(i * 2, i * 2 + 2), 16);
  return out;
}

function hexFromBytes(buf) {
  return Buffer.from(buf).toString('hex');
}

function le16(n) {
  return [n & 0xff, (n >> 8) & 0xff];
}

function sum16ForFrame(frame) {
  const tmp = Buffer.from(frame);
  if (tmp.length >= 24) {
    tmp[22] = 0;
    tmp[23] = 0;
  }
  let sum = 0;
  for (let i = 2; i < tmp.length; i++) {
    sum = (sum + tmp[i]) & 0xffff;
  }
  return sum;
}

function putLe16(buf, off, n) {
  buf[off] = n & 0xff;
  buf[off + 1] = (n >> 8) & 0xff;
}

function parseSeqOptions(request) {
  const seqHex = argValue('--seq-hex');
  const seqLe = argValue('--seq-le');
  if (seqHex) {
    const b = bytesFromHex(seqHex, '--seq-hex');
    if (b.length !== 2) throw new Error('--seq-hex must be exactly two bytes');
    return [b[0], b[1], 'seq-hex'];
  }
  if (seqLe) {
    const n = Number(seqLe.startsWith('0x') ? parseInt(seqLe, 16) : parseInt(seqLe, 10));
    if (!Number.isFinite(n) || n < 0 || n > 0xffff) throw new Error('--seq-le must be 0..65535');
    const [a,b] = le16(n);
    return [a, b, 'seq-le'];
  }
  if (request) {
    return [request[2], request[3], 'request-hex'];
  }
  return [0x00, 0x00, 'default-zero'];
}

function candidateFrame({ payload, request, typeBytes }) {
  const totalLength = 24 + payload.length;
  if (totalLength > 0xffff) throw new Error(`frame too long: ${totalLength}`);
  const frame = Buffer.alloc(totalLength, 0);
  frame[0] = 0x6d;
  frame[1] = 0x7e;

  const [s0, s1, seqSource] = parseSeqOptions(request);
  frame[2] = s0;
  frame[3] = s1;

  frame[4] = typeBytes[0];
  frame[5] = typeBytes[1];
  frame[6] = typeBytes[2];
  frame[7] = typeBytes[3];

  if (request && request.length >= 24) {
    // Preserve unknown/session/context header bytes from real 0x46 request.
    for (let i = 8; i <= 19; i++) frame[i] = request[i];
  }

  putLe16(frame, 20, payload.length);
  frame[22] = 0;
  frame[23] = 0;
  payload.copy(frame, 24);

  const checksum = sum16ForFrame(frame);
  putLe16(frame, 22, checksum);

  const verify = sum16ForFrame(frame);
  const storedLE = frame[22] | (frame[23] << 8);
  const storedBE = (frame[22] << 8) | frame[23];

  return {
    typeBytes: hexFromBytes(Buffer.from(typeBytes)),
    typeByte: `0x${typeBytes[0].toString(16).padStart(2, '0')}`,
    flagByte: `0x${typeBytes[1].toString(16).padStart(2, '0')}`,
    classByte: `0x${typeBytes[2].toString(16).padStart(2, '0')}`,
    tailByte: `0x${typeBytes[3].toString(16).padStart(2, '0')}`,
    ackRequiredFlag: (typeBytes[1] & 0x80) !== 0,
    totalLength,
    payloadLength: payload.length,
    payloadLengthHexLE: hexFromBytes(Buffer.from(le16(payload.length))),
    seqBytes: hexFromBytes(Buffer.from([frame[2], frame[3]])),
    seqSource,
    headerContextCopiedFromRequest: !!request,
    checksumStoredHex: hexFromBytes(frame.slice(22, 24)),
    checksumStoredLE: `0x${storedLE.toString(16).padStart(4, '0')}`,
    checksumStoredBE: `0x${storedBE.toString(16).padStart(4, '0')}`,
    checksumCalculatedLE: `0x${verify.toString(16).padStart(4, '0')}`,
    checksumValidUnderNormalModel: storedLE === verify,
    frameHex: hexFromBytes(frame),
  };
}

function main() {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    usage();
    return;
  }

  const payload = bytesFromHex(argValue('--payload-hex'), '--payload-hex');
  let request = null;
  const requestHex = argValue('--request-hex');
  if (requestHex) {
    request = bytesFromHex(requestHex, '--request-hex');
    if (request.length < 24) throw new Error('--request-hex must be at least 24 bytes');
    if (!(request[0] === 0x6d && request[1] === 0x7e)) {
      throw new Error('--request-hex does not start with magic 6d7e');
    }
  }

  const typeCandidates = [
    { name: 'A_110047ff_response_no_ack_candidate', bytes: [0x11, 0x00, 0x47, 0xff], reason: 'Most analogous to 110046ff request, no ackRequiredFlag.' },
    { name: 'B_118047ff_response_ack_required_candidate', bytes: [0x11, 0x80, 0x47, 0xff], reason: 'Same typeByte as request/heartbeat with ackRequiredFlag set.' },
    { name: 'C_1f0047ff_confirm_style_candidate', bytes: [0x1f, 0x00, 0x47, 0xff], reason: 'ACK/confirmation style; probably less likely as full config response.' },
    { name: 'D_100047ff_response_variant_candidate', bytes: [0x10, 0x00, 0x47, 0xff], reason: 'Conservative alternate typeByte observed as possible control variant; unconfirmed.' },
  ];

  const candidates = typeCandidates.map(c => ({
    name: c.name,
    reason: c.reason,
    ...candidateFrame({ payload, request, typeBytes: c.bytes }),
  }));

  const result = {
    safety: 'OFFLINE FULL-FRAME CANDIDATES ONLY. DO NOT SEND. This script never opens a socket and never sends UDP.',
    purpose: 'Generate candidate classByte=0x47 register/config response frames for offline analysis only.',
    payloadLength: payload.length,
    inferredTotalLength: 24 + payload.length,
    payloadPreviewHex: hexFromBytes(payload.slice(0, Math.min(payload.length, 32))),
    requestProvided: !!request,
    requestTypeBytes: request ? hexFromBytes(request.slice(4, 8)) : null,
    requestSeqBytes: request ? hexFromBytes(request.slice(2, 4)) : null,
    candidates,
    caveats: [
      '0x47 header bytes are not fully confirmed.',
      'Generated frames are not proven safe for online use.',
      'Do not send these frames to a live FSU.',
      '1F00_D2FF checksum anomaly is still unresolved.',
      'Use only for parser/checksum/static comparison.'
    ],
  };

  const out = argValue('--out');
  if (out) {
    fs.mkdirSync(require('path').dirname(out), { recursive: true });
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
