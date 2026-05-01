#!/usr/bin/env node
'use strict';

/**
 * build-class47-candidates-from-latest-request-offline.js
 *
 * OFFLINE ONLY. This script never opens sockets and never sends UDP.
 *
 * It combines:
 *   1) pick latest 0x46 request frame from JSONL
 *   2) build 0x47 full-frame candidates using that request context
 *
 * Requires:
 *   backend/scripts/build-class47-register-response-frame-candidates-offline.js
 *   already present from v0.6 package.
 */

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function argValue(name) {
  const idx = process.argv.indexOf(name);
  if (idx < 0) return null;
  return process.argv[idx + 1] || null;
}

function runNode(args) {
  const res = spawnSync(process.execPath, args, { encoding: 'utf8' });
  if (res.status !== 0) {
    throw new Error(`command failed: node ${args.join(' ')}\nSTDOUT:\n${res.stdout}\nSTDERR:\n${res.stderr}`);
  }
  return res.stdout;
}

function main() {
  const input = argValue('--input') || 'backend/logs/fsu_raw_packets/2026-05-01.jsonl';
  const payloadHex = argValue('--payload-hex');
  const length = argValue('--length') || '245';
  const typeBytes = argValue('--typeBytes') || '110046ff';
  const out = argValue('--out') || `backend/logs/fsu_raw_packets/class47-candidates-from-latest-${length}-${typeBytes}.json`;

  if (!payloadHex) {
    throw new Error('--payload-hex is required');
  }

  const tempPickOut = out.replace(/\.json$/i, '.pick.json');

  const pickArgs = [
    'backend/scripts/pick-latest-frame-hex.js',
    '--input', input,
    '--typeBytes', typeBytes,
    '--length', String(length),
    '--out', tempPickOut,
  ];

  const pickStdout = runNode(pickArgs);
  const pick = JSON.parse(fs.readFileSync(tempPickOut, 'utf8'));
  if (!pick.found || !pick.latest || !pick.latest.rawHex) {
    throw new Error(`no request frame found for typeBytes=${typeBytes}, length=${length}`);
  }

  const buildArgs = [
    'backend/scripts/build-class47-register-response-frame-candidates-offline.js',
    '--request-hex', pick.latest.rawHex,
    '--payload-hex', payloadHex,
    '--out', out,
  ];

  const buildStdout = runNode(buildArgs);
  const built = JSON.parse(fs.readFileSync(out, 'utf8'));

  const summary = {
    safety: 'offline only; no UDP sent; no ACK sent',
    input,
    selectedRequest: {
      lineNo: pick.latest.lineNo,
      timestamp: pick.latest.timestamp,
      totalLength: pick.latest.totalLength,
      seqLE: pick.latest.seqLE,
      seqBytes: pick.latest.seqBytes,
      typeBytes: pick.latest.typeBytes,
      payloadLengthLE: pick.latest.payloadLengthLE,
      checksumHex: pick.latest.checksumHex,
      sourceField: pick.latest.sourceField,
    },
    output: out,
    pickOutput: tempPickOut,
    candidateSummary: built.candidates.map(c => ({
      name: c.name,
      typeBytes: c.typeBytes,
      totalLength: c.totalLength,
      payloadLength: c.payloadLength,
      seqBytes: c.seqBytes,
      headerContextCopiedFromRequest: c.headerContextCopiedFromRequest,
      checksumStoredHex: c.checksumStoredHex,
      checksumValidUnderNormalModel: c.checksumValidUnderNormalModel,
      frameHexPrefix: c.frameHex.slice(0, 96),
    })),
  };

  const summaryOut = out.replace(/\.json$/i, '.summary.json');
  fs.writeFileSync(summaryOut, JSON.stringify(summary, null, 2), 'utf8');

  console.log(JSON.stringify(summary, null, 2));
}

try {
  main();
} catch (err) {
  console.error(JSON.stringify({ error: err.message, safety: 'no UDP sent; offline script only' }, null, 2));
  process.exit(1);
}
