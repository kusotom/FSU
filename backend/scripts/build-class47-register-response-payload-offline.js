#!/usr/bin/env node
'use strict';

/**
 * Offline payload template builder for FSU/Emerson SiteUnit2 classByte=0x47 register/config response.
 * Safety: builds payload hex only. It does not build a full frame, open sockets, or send UDP.
 */

const REQUIRED_MASK_BY_TYPE = new Map([[0,1],[5,2],[6,4],[7,8],[8,16],[9,32]]);
const RESULT_CODE = { success: 0, fail: 1, unregister: 2 };

function usage() {
  console.error(`Usage:\n  node backend/scripts/build-class47-register-response-payload-offline.js --result success|fail|unregister --entry "0=udp://192.168.100.123:6000" ...\n\nSafety: offline payload only; this script never sends UDP.`);
  process.exit(2);
}

function getArg(name) {
  const idx = process.argv.indexOf(name);
  return idx >= 0 && idx + 1 < process.argv.length ? process.argv[idx + 1] : null;
}

function getAllArgs(name) {
  const vals = [];
  for (let i = 0; i < process.argv.length; i++) {
    if (process.argv[i] === name && i + 1 < process.argv.length) vals.push(process.argv[i + 1]);
  }
  return vals;
}

function parseEntry(s) {
  const eq = s.indexOf('=');
  if (eq <= 0) throw new Error(`invalid --entry '${s}', expected <type>=<uri>`);
  const type = Number.parseInt(s.slice(0, eq), 10);
  const uri = s.slice(eq + 1);
  if (!Number.isInteger(type) || type < 0 || type > 255) throw new Error(`invalid channel type in '${s}'`);
  const uriBuf = Buffer.from(uri, 'ascii');
  if (uriBuf.length > 255) throw new Error(`uri too long for channel ${type}: ${uriBuf.length}`);
  return { type, uri, uriBuf };
}

const resultName = (getArg('--result') || '').toLowerCase();
if (!Object.prototype.hasOwnProperty.call(RESULT_CODE, resultName)) usage();
const entryArgs = getAllArgs('--entry');
if (!entryArgs.length) usage();

try {
  const entries = entryArgs.map(parseEntry);
  let observedMask = 0;
  for (const e of entries) {
    if (REQUIRED_MASK_BY_TYPE.has(e.type)) observedMask |= REQUIRED_MASK_BY_TYPE.get(e.type);
  }

  const payloadParts = [];
  payloadParts.push(Buffer.from([RESULT_CODE[resultName]]));
  const count = Buffer.alloc(2);
  count.writeUInt16LE(entries.length, 0);
  payloadParts.push(count);
  for (const e of entries) {
    payloadParts.push(Buffer.from([e.type, e.uriBuf.length]));
    payloadParts.push(e.uriBuf);
  }
  const payload = Buffer.concat(payloadParts);

  const output = {
    safety: 'OFFLINE PAYLOAD TEMPLATE ONLY. DO NOT SEND. This is not a full UDP frame.',
    result: resultName,
    resultCode: RESULT_CODE[resultName],
    serviceCountCandidate: entries.length,
    entries: entries.map((e, i) => ({ index: i, channelType: e.type, uriLength: e.uriBuf.length, uri: e.uri })),
    observedMask: `0x${observedMask.toString(16).padStart(2, '0')}`,
    requiredMask: '0x3f',
    requiredChannelsComplete: observedMask === 0x3f,
    successConditionCandidateMet: RESULT_CODE[resultName] === 0 && observedMask === 0x3f,
    payloadLength: payload.length,
    payloadHex: payload.toString('hex'),
    warnings: [
      'Payload format is a SiteUnit2-derived candidate: resultCode + uint16LE count + entries(type,len,uri).',
      '0x47 frame header, checksum, and online behavior are still not fully confirmed.',
      'Do not send this payload or wrap it into a live UDP packet without further controlled validation.',
    ],
  };
  console.log(JSON.stringify(output, null, 2));
} catch (err) {
  console.error(`Error: ${err.message}`);
  process.exit(1);
}
