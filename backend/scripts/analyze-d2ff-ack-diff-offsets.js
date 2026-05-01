#!/usr/bin/env node
'use strict';

/**
 * analyze-d2ff-ack-diff-offsets.js
 *
 * OFFLINE ONLY. This script never opens sockets and never sends UDP.
 *
 * Purpose:
 *   v1.0 showed:
 *     - generated ACK model with normal checksum has checksumMatchesOnly=100%
 *     - but exactMatches=0 and byteDiff=3
 *
 * This script identifies exactly which byte offsets differ between:
 *   generated ACK candidate:
 *     copy paired 1180D2FF first 24 bytes
 *     set [4]=1f, [5]=00, [20..21]=0
 *     checksum = normal checksum of generated candidate
 *
 * and observed 1F00D2FF 24-byte frame.
 *
 * Output:
 *   - diff offset histogram
 *   - generated/observed values at each diff offset
 *   - constant transform candidates
 *   - sample pairs
 *
 * Usage:
 *   node backend/scripts/analyze-d2ff-ack-diff-offsets.js --input backend/logs/fsu_raw_packets/2026-05-01.jsonl
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
function fmt2(n) { return n == null ? null : n.toString(16).padStart(2, '0'); }
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
    checksumNormal: b.length >= 24 ? checksumNormal(b) : null,
  };
}

function buildNormalAck(src) {
  const ack = Buffer.from(src.buf.slice(0,24));
  ack[4] = 0x1f;
  ack[5] = 0x00;
  ack[20] = 0x00;
  ack[21] = 0x00;
  ack[22] = 0x00;
  ack[23] = 0x00;
  const c = checksumNormal(ack);
  putLe16(ack, 22, c);
  return ack;
}

function inc(map, key, n=1) { map[key] = (map[key] || 0) + n; }
function topMap(map, limit=20) {
  return Object.entries(map).sort((a,b)=>b[1]-a[1] || a[0].localeCompare(b[0])).slice(0, limit).map(([value,count])=>({value,count}));
}

function main() {
  const input = argValue('--input') || 'backend/logs/fsu_raw_packets/2026-05-01.jsonl';
  const outJson = argValue('--out-json') || 'backend/logs/fsu_raw_packets/d2ff-ack-diff-offset-analysis.json';
  const outMd = argValue('--out-md') || 'backend/logs/fsu_raw_packets/d2ff-ack-diff-offset-analysis.md';
  const sampleLimit = Number(argValue('--sample-limit') || 10);

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

  const diffOffsetCounts = {};
  const diffValueCounts = {};
  const offsetGeneratedValues = {};
  const offsetObservedValues = {};
  const offsetTransforms = {};
  const diffCountHistogram = {};
  const generatedExactIfOverride = {};
  const samples = [];

  let paired = 0;
  let checksumMatches = 0;
  let exactNormal = 0;

  for (const obs of observed) {
    const list = srcBySeq.get(obs.seqLE);
    if (!list || !list.length) continue;
    paired++;
    const src = list[list.length - 1];
    const gen = buildNormalAck(src);
    const genHex = hex(gen);
    if (obs.checksumStoredHex === hex(gen.slice(22,24))) checksumMatches++;
    if (genHex === obs.rawHex) exactNormal++;

    const diffs = [];
    for (let off=0; off<Math.max(gen.length, obs.buf.length); off++) {
      const g = off < gen.length ? gen[off] : null;
      const o = off < obs.buf.length ? obs.buf[off] : null;
      if (g !== o) {
        diffs.push({ offset:off, generated:g, observed:o });
        inc(diffOffsetCounts, String(off));
        inc(diffValueCounts, `${off}:${fmt2(g)}->${fmt2(o)}`);
        inc(offsetGeneratedValues[off] || (offsetGeneratedValues[off]={}), fmt2(g));
        inc(offsetObservedValues[off] || (offsetObservedValues[off]={}), fmt2(o));
        const delta = (o - g) & 0xff;
        const xor = (o ^ g) & 0xff;
        inc(offsetTransforms[off] || (offsetTransforms[off]={}), `delta=${fmt2(delta)},xor=${fmt2(xor)}`);
      }
    }
    inc(diffCountHistogram, String(diffs.length));

    if (samples.length < sampleLimit) {
      samples.push({
        seqLE: obs.seqLE,
        sourceRds30: {
          lineNo: src.lineNo, timestamp: src.timestamp,
          rawHex: src.rawHex,
          header0_23: hex(src.buf.slice(0,24)),
        },
        generatedAckNormal: {
          rawHex: genHex,
          header0_23: hex(gen.slice(0,24)),
          checksumHex: hex(gen.slice(22,24)),
        },
        observedAck24: {
          lineNo: obs.lineNo, timestamp: obs.timestamp,
          rawHex: obs.rawHex,
          header0_23: hex(obs.buf.slice(0,24)),
          checksumHex: obs.checksumStoredHex,
        },
        diffs: diffs.map(d => ({ offset:d.offset, generated:fmt2(d.generated), observed:fmt2(d.observed) })),
      });
    }
  }

  // Derive a simple override candidate if every pair differs at stable offsets with one observed value per offset.
  const stableOverrides = {};
  for (const [off, values] of Object.entries(offsetObservedValues)) {
    const top = Object.entries(values).sort((a,b)=>b[1]-a[1]);
    if (top.length === 1 && top[0][1] === paired) {
      stableOverrides[off] = top[0][0];
    }
  }

  const result = {
    safety: 'offline ACK diff-offset analysis only; no UDP sent; no ACK sent',
    input,
    totalLines,
    parsedLines,
    counts: {
      rds30_1180d2ff: sources.length,
      ack24_1f00d2ff: observed.length,
      pairedBySeq: paired,
      checksumMatchesUnderNormalGeneratedModel: checksumMatches,
      exactMatchesUnderNormalGeneratedModel: exactNormal,
    },
    diffCountHistogram,
    diffOffsetCounts: topMap(diffOffsetCounts, 30),
    diffValueCounts: topMap(diffValueCounts, 50),
    offsetGeneratedValues,
    offsetObservedValues,
    offsetTransforms,
    stableOverrides,
    interpretation: [
      'If checksum matches but exact match fails with stable diff offsets, ACK checksum model is correct but header transformation is incomplete.',
      'Stable observed values at offsets can become candidate header overwrite rules.',
      'Do not send generated ACKs online.'
    ],
    samples,
  };

  fs.mkdirSync(path.dirname(outJson), { recursive: true });
  fs.writeFileSync(outJson, JSON.stringify(result, null, 2), 'utf8');

  const md = [];
  md.push('# D2FF ACK diff offset analysis');
  md.push('');
  md.push(`Input: \`${input}\``);
  md.push('');
  md.push('Safety: offline only; no UDP sent; no ACK sent.');
  md.push('');
  md.push('## Counts');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(result.counts, null, 2));
  md.push('```');
  md.push('');
  md.push('## Diff count histogram');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(diffCountHistogram, null, 2));
  md.push('```');
  md.push('');
  md.push('## Diff offsets');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(result.diffOffsetCounts, null, 2));
  md.push('```');
  md.push('');
  md.push('## Diff values');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(result.diffValueCounts, null, 2));
  md.push('```');
  md.push('');
  md.push('## Stable overrides');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(stableOverrides, null, 2));
  md.push('```');
  md.push('');
  md.push('## Samples');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(samples.slice(0,3), null, 2));
  md.push('```');
  fs.writeFileSync(outMd, md.join('\n'), 'utf8');

  console.log(JSON.stringify({
    safety: result.safety,
    input,
    counts: result.counts,
    diffCountHistogram,
    diffOffsetCounts: result.diffOffsetCounts,
    diffValueCounts: result.diffValueCounts.slice(0, 20),
    stableOverrides,
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
