#!/usr/bin/env node
'use strict';

/**
 * reproduce-d2ff-ack-exact-v12.js
 *
 * OFFLINE ONLY. This script never opens sockets and never sends UDP.
 *
 * v1.1 finding:
 *   Generated normal ACK matches observed checksum, but differs exactly at offsets:
 *     16: 00 -> c1
 *     17: 00 -> 62
 *     19: 00 -> 2d
 *
 * This implies the observed 1F00D2FF checksum is computed before / without these
 * three context bytes, then those context bytes are present in the stored frame.
 *
 * v1.2 candidate model:
 *   1. Start from paired 1180D2FF first 24 bytes.
 *   2. byte4 = 0x1f
 *   3. byte5 = 0x00
 *   4. payloadLength [20..21] = 0
 *   5. checksum field [22..23] = 0
 *   6. For checksum calculation, keep [16]=00, [17]=00, [19]=00.
 *   7. Compute normal checksum bytes[2..23].
 *   8. Store checksum at [22..23].
 *   9. After checksum, apply fixed context overrides:
 *        [16]=0xc1, [17]=0x62, [19]=0x2d
 *  10. Compare exact full 24-byte ACK with observed 1F00D2FF.
 */

const fs = require('fs');
const path = require('path');

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

function bytesFromHex(h) {
  const b = Buffer.alloc(h.length / 2);
  for (let i = 0; i < b.length; i++) b[i] = parseInt(h.slice(i*2, i*2+2), 16);
  return b;
}

function hex(buf) { return Buffer.from(buf).toString('hex'); }
function le16(buf, off) { return buf[off] | (buf[off+1] << 8); }
function putLe16(buf, off, n) { buf[off] = n & 0xff; buf[off+1] = (n >> 8) & 0xff; }
function fmt16(n) { return '0x' + (n & 0xffff).toString(16).padStart(4, '0'); }

function checksumNormal(buf) {
  const tmp = Buffer.from(buf);
  if (tmp.length >= 24) { tmp[22] = 0; tmp[23] = 0; }
  let sum = 0;
  for (let i = 2; i < tmp.length; i++) sum = (sum + tmp[i]) & 0xffff;
  return sum;
}

function findHexCandidates(obj, results = [], pathParts = []) {
  if (obj == null) return results;
  if (typeof obj === 'string') {
    const h = normalizeHex(obj);
    if (h && h.startsWith('6d7e') && h.length >= 48) {
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
  for (const k of keys) if (obj && obj[k]) return String(obj[k]);
  return null;
}

function frameInfo(h, lineNo, ts, sourceField) {
  const b = bytesFromHex(h);
  return {
    lineNo, timestamp: ts, sourceField,
    rawHex: h,
    buf: b,
    totalLength: b.length,
    seqLE: le16(b,2),
    seqBytes: hex(b.slice(2,4)),
    typeBytes: hex(b.slice(4,8)),
    payloadLengthLE: b.length >= 22 ? le16(b,20) : null,
    checksumStoredLE: b.length >= 24 ? le16(b,22) : null,
    checksumStoredHex: b.length >= 24 ? hex(b.slice(22,24)) : null,
  };
}

function buildAckV12(src) {
  const ack = Buffer.from(src.buf.slice(0,24));
  ack[4] = 0x1f;
  ack[5] = 0x00;
  ack[20] = 0x00;
  ack[21] = 0x00;
  ack[22] = 0x00;
  ack[23] = 0x00;

  // Ensure these are zero during checksum calculation.
  ack[16] = 0x00;
  ack[17] = 0x00;
  ack[19] = 0x00;

  const c = checksumNormal(ack);
  putLe16(ack, 22, c);

  // Apply observed fixed context bytes after checksum.
  ack[16] = 0xc1;
  ack[17] = 0x62;
  ack[19] = 0x2d;

  return { ack, checksum: c };
}

function diffBytes(a, b) {
  const out = [];
  for (let i=0; i<Math.max(a.length,b.length); i++) {
    const av = i < a.length ? a[i] : null;
    const bv = i < b.length ? b[i] : null;
    if (av !== bv) out.push({ offset:i, generated:av==null?null:av.toString(16).padStart(2,'0'), observed:bv==null?null:bv.toString(16).padStart(2,'0') });
  }
  return out;
}

function main() {
  const input = argValue('--input') || 'backend/logs/fsu_raw_packets/2026-05-01.jsonl';
  const outJson = argValue('--out-json') || 'backend/logs/fsu_raw_packets/d2ff-ack-exact-reproduction-v12.json';
  const outMd = argValue('--out-md') || 'backend/logs/fsu_raw_packets/d2ff-ack-exact-reproduction-v12.md';
  const sampleLimit = Number(argValue('--sample-limit') || 5);

  if (!fs.existsSync(input)) throw new Error(`input not found: ${input}`);

  const lines = fs.readFileSync(input, 'utf8').split(/\r?\n/);
  const sources = [];
  const observed = [];
  let totalLines=0, parsedLines=0;

  for (let i=0; i<lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    totalLines++;
    let obj;
    try { obj = JSON.parse(line); parsedLines++; } catch { continue; }
    const ts = extractTimestamp(obj);
    const candidates = findHexCandidates(obj).sort((a,b)=>b.score-a.score);
    for (const c of candidates) {
      const b = bytesFromHex(c.hex);
      if (b.length < 24 || hex(b.slice(0,2)) !== '6d7e') continue;
      const t = hex(b.slice(4,8));
      if (b.length === 30 && t === '1180d2ff') {
        sources.push(frameInfo(c.hex, i+1, ts, c.keyPath));
        break;
      }
      if (b.length === 24 && t === '1f00d2ff') {
        observed.push(frameInfo(c.hex, i+1, ts, c.keyPath));
        break;
      }
    }
  }

  const srcBySeq = new Map();
  for (const s of sources) {
    if (!srcBySeq.has(s.seqLE)) srcBySeq.set(s.seqLE, []);
    srcBySeq.get(s.seqLE).push(s);
  }

  let paired=0, exactMatches=0, checksumMatches=0;
  const diffHistogram = {};
  const samples = [];

  for (const obs of observed) {
    const list = srcBySeq.get(obs.seqLE);
    if (!list || !list.length) continue;
    paired++;
    const src = list[list.length - 1];
    const { ack, checksum } = buildAckV12(src);
    const ackHex = hex(ack);
    if (ackHex === obs.rawHex) exactMatches++;
    if (hex(ack.slice(22,24)) === obs.checksumStoredHex) checksumMatches++;
    const diffs = diffBytes(ack, obs.buf);
    diffHistogram[String(diffs.length)] = (diffHistogram[String(diffs.length)] || 0) + 1;

    if (samples.length < sampleLimit) {
      samples.push({
        seqLE: obs.seqLE,
        sourceRds30: {
          lineNo: src.lineNo,
          timestamp: src.timestamp,
          rawHex: src.rawHex,
        },
        generatedAckV12: {
          rawHex: ackHex,
          checksumHex: hex(ack.slice(22,24)),
          checksumValue: fmt16(checksum),
        },
        observedAck24: {
          lineNo: obs.lineNo,
          timestamp: obs.timestamp,
          rawHex: obs.rawHex,
          checksumHex: obs.checksumStoredHex,
        },
        exactMatch: ackHex === obs.rawHex,
        diffs,
      });
    }
  }

  const result = {
    safety: 'offline exact ACK reproduction only; no UDP sent; no ACK sent',
    input,
    model: {
      name: 'd2ff_ack_v12_context_after_checksum',
      description: 'copy RDS30 first 24 bytes; set 1f00; payloadLen=0; zero 16/17/19 for checksum; normal checksum; then set 16=c1,17=62,19=2d',
      fixedOverridesAfterChecksum: { '16': 'c1', '17': '62', '19': '2d' },
    },
    counts: {
      rds30_1180d2ff: sources.length,
      ack24_1f00d2ff: observed.length,
      pairedBySeq: paired,
      exactMatches,
      checksumMatches,
    },
    success: exactMatches === paired && paired > 0,
    diffHistogram,
    samples,
    interpretation: [
      'If success=true, observed 1F00D2FF frames are exactly reproduced by v1.2 model for this log.',
      'The three context bytes appear to be present in frame but excluded/not set during checksum calculation.',
      'This still does not authorize online sending; keep offline unless a separate controlled experiment is approved.'
    ]
  };

  fs.mkdirSync(path.dirname(outJson), { recursive: true });
  fs.writeFileSync(outJson, JSON.stringify(result, null, 2), 'utf8');

  const md = [];
  md.push('# D2FF ACK exact reproduction v1.2');
  md.push('');
  md.push(`Input: \`${input}\``);
  md.push('');
  md.push('Safety: offline only; no UDP sent; no ACK sent.');
  md.push('');
  md.push('## Model');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(result.model, null, 2));
  md.push('```');
  md.push('');
  md.push('## Counts');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(result.counts, null, 2));
  md.push('```');
  md.push('');
  md.push(`Success: **${result.success}**`);
  md.push('');
  md.push('## Diff histogram');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(diffHistogram, null, 2));
  md.push('```');
  md.push('');
  md.push('## Samples');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(samples, null, 2));
  md.push('```');
  fs.writeFileSync(outMd, md.join('\n'), 'utf8');

  console.log(JSON.stringify({
    safety: result.safety,
    model: result.model,
    counts: result.counts,
    success: result.success,
    diffHistogram,
    outJson,
    outMd,
  }, null, 2));
}

try {
  main();
} catch (err) {
  console.error(JSON.stringify({ error: err.message, safety: 'no UDP sent; offline script only' }, null, 2));
  process.exit(1);
}
