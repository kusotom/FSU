#!/usr/bin/env node
'use strict';

/**
 * reproduce-d2ff-ack-offline.js
 *
 * OFFLINE ONLY. This script never opens sockets and never sends UDP.
 *
 * Purpose:
 *   Verify whether the observed 24-byte 1F00D2FF ACK/confirm frames can be
 *   reproduced from paired 30-byte 1180D2FF frames.
 *
 * Current candidate model:
 *   input:  RDS/heartbeat frame 6d7e .... 11 80 d2 ff .... payloadLen=6
 *   output: 24-byte ACK candidate:
 *     - copy input first 24 bytes
 *     - byte4 = 0x1f
 *     - byte5 = 0x00
 *     - byte6/byte7 preserved
 *     - payloadLen = 0
 *     - checksum field = checksumNormal(candidate24) - 0x0150
 *
 * The script also tests alternate checksum models:
 *   - normal checksum
 *   - normal - 0x0150
 *   - normal + 0xfeb0
 *   - reuse source stored checksum
 *   - reuse source calculated checksum
 *
 * It pairs frames by seqLE and compares generated ACK candidates against
 * observed 1F00D2FF frames byte-for-byte.
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
function be16(buf, off) { return (buf[off] << 8) | buf[off+1]; }
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
    checksumStoredBE: b.length >= 24 ? be16(b,22) : null,
    checksumStoredHex: b.length >= 24 ? hex(b.slice(22,24)) : null,
    checksumNormal: b.length >= 24 ? checksumNormal(b) : null,
  };
}

function buildBaseAckFromSource(src) {
  const inb = src.buf;
  if (inb.length < 24) throw new Error('source too short');
  const ack = Buffer.from(inb.slice(0, 24));
  ack[4] = 0x1f;
  ack[5] = 0x00;
  // Preserve ack[6], ack[7], seq and header context.
  ack[20] = 0x00;
  ack[21] = 0x00;
  ack[22] = 0x00;
  ack[23] = 0x00;
  return ack;
}

function buildModels(src) {
  const base = buildBaseAckFromSource(src);
  const normal = checksumNormal(base);
  const sourceStored = src.checksumStoredLE;
  const sourceCalc = src.checksumNormal;
  const models = [];

  function add(name, checksum) {
    const b = Buffer.from(base);
    putLe16(b, 22, checksum & 0xffff);
    models.push({
      model: name,
      checksumLE: checksum & 0xffff,
      checksumHex: hex(b.slice(22,24)),
      normalChecksumForCandidate: normal,
      ackHex: hex(b),
    });
  }

  add('normal', normal);
  add('normal_minus_0x0150', (normal - 0x0150) & 0xffff);
  add('normal_plus_0xfeb0', (normal + 0xfeb0) & 0xffff);
  add('source_stored_checksum', sourceStored);
  add('source_calculated_checksum', sourceCalc);
  add('source_stored_minus_payload_sum_candidate', (sourceStored - 0x0150) & 0xffff);

  return models;
}

function hammingByteDiff(aHex, bHex) {
  const a = bytesFromHex(aHex);
  const b = bytesFromHex(bHex);
  const max = Math.max(a.length, b.length);
  let diff = 0;
  const offsets = [];
  for (let i=0; i<max; i++) {
    const av = i < a.length ? a[i] : null;
    const bv = i < b.length ? b[i] : null;
    if (av !== bv) {
      diff++;
      if (offsets.length < 20) offsets.push({ offset:i, generated: av == null ? null : av.toString(16).padStart(2,'0'), observed: bv == null ? null : bv.toString(16).padStart(2,'0') });
    }
  }
  return { diff, offsets };
}

function main() {
  const input = argValue('--input') || 'backend/logs/fsu_raw_packets/2026-05-01.jsonl';
  const outJson = argValue('--out-json') || 'backend/logs/fsu_raw_packets/d2ff-ack-reproduction-analysis.json';
  const outMd = argValue('--out-md') || 'backend/logs/fsu_raw_packets/d2ff-ack-reproduction-analysis.md';
  const sampleLimit = Number(argValue('--sample-limit') || 10);

  if (!fs.existsSync(input)) throw new Error(`input not found: ${input}`);

  const lines = fs.readFileSync(input, 'utf8').split(/\r?\n/);
  const sources = [];
  const observedAcks = [];
  let totalLines = 0, parsedLines = 0;

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
      const typeBytes = hex(b.slice(4,8));
      if (b.length === 30 && typeBytes === '1180d2ff') {
        sources.push(frameInfo(c.hex, i+1, ts, c.keyPath));
        break;
      }
      if (b.length === 24 && typeBytes === '1f00d2ff') {
        observedAcks.push(frameInfo(c.hex, i+1, ts, c.keyPath));
        break;
      }
    }
  }

  const srcBySeq = new Map();
  for (const f of sources) {
    if (!srcBySeq.has(f.seqLE)) srcBySeq.set(f.seqLE, []);
    srcBySeq.get(f.seqLE).push(f);
  }

  const modelStats = {};
  const samples = [];
  let paired = 0;

  for (const ack of observedAcks) {
    const list = srcBySeq.get(ack.seqLE);
    if (!list || !list.length) continue;
    paired++;
    const src = list[list.length - 1];
    const models = buildModels(src);

    for (const m of models) {
      if (!modelStats[m.model]) {
        modelStats[m.model] = {
          exactMatches: 0,
          checksumMatchesOnly: 0,
          minByteDiff: Infinity,
          maxByteDiff: 0,
          diffHistogram: {},
        };
      }
      const st = modelStats[m.model];
      const cmp = hammingByteDiff(m.ackHex, ack.rawHex);
      if (m.ackHex === ack.rawHex) st.exactMatches++;
      if (m.checksumHex === ack.checksumStoredHex) st.checksumMatchesOnly++;
      st.minByteDiff = Math.min(st.minByteDiff, cmp.diff);
      st.maxByteDiff = Math.max(st.maxByteDiff, cmp.diff);
      st.diffHistogram[String(cmp.diff)] = (st.diffHistogram[String(cmp.diff)] || 0) + 1;
    }

    if (samples.length < sampleLimit) {
      const modelDetails = models.map(m => {
        const cmp = hammingByteDiff(m.ackHex, ack.rawHex);
        return {
          model: m.model,
          checksumHex: m.checksumHex,
          exactMatch: m.ackHex === ack.rawHex,
          byteDiff: cmp.diff,
          firstDiffs: cmp.offsets,
          generatedAckHex: m.ackHex,
        };
      });
      samples.push({
        seqLE: ack.seqLE,
        sourceRds30: {
          lineNo: src.lineNo,
          timestamp: src.timestamp,
          rawHex: src.rawHex,
          checksumStoredHex: src.checksumStoredHex,
          checksumNormal: fmt16(src.checksumNormal),
        },
        observedAck24: {
          lineNo: ack.lineNo,
          timestamp: ack.timestamp,
          rawHex: ack.rawHex,
          checksumStoredHex: ack.checksumStoredHex,
          checksumNormal: fmt16(ack.checksumNormal),
        },
        modelDetails,
      });
    }
  }

  for (const st of Object.values(modelStats)) {
    if (st.minByteDiff === Infinity) st.minByteDiff = null;
  }

  const best = Object.entries(modelStats).map(([model, st]) => ({
    model,
    exactMatches: st.exactMatches,
    checksumMatchesOnly: st.checksumMatchesOnly,
    minByteDiff: st.minByteDiff,
    maxByteDiff: st.maxByteDiff,
  })).sort((a,b) => b.exactMatches-a.exactMatches || b.checksumMatchesOnly-a.checksumMatchesOnly || (a.minByteDiff??999)-(b.minByteDiff??999));

  const result = {
    safety: 'offline ACK reproduction analysis only; no UDP sent; no ACK sent',
    input,
    totalLines,
    parsedLines,
    counts: {
      rds30_1180d2ff: sources.length,
      ack24_1f00d2ff: observedAcks.length,
      pairedBySeq: paired,
    },
    modelStats,
    bestModels: best,
    samples,
    interpretation: [
      'If a model has exactMatches == pairedBySeq, the observed ACK construction is fully reproduced for this log.',
      'If only checksumMatchesOnly is high but byteDiff remains nonzero, header copying assumptions are incomplete.',
      'If no model matches exactly, keep checksum/ACK construction marked unresolved.',
      'Do not send any generated ACK online.'
    ],
  };

  fs.mkdirSync(path.dirname(outJson), { recursive: true });
  fs.writeFileSync(outJson, JSON.stringify(result, null, 2), 'utf8');

  const md = [];
  md.push('# D2FF ACK reproduction analysis');
  md.push('');
  md.push(`Input: \`${input}\``);
  md.push('');
  md.push('Safety: offline only; no UDP sent; no ACK sent.');
  md.push('');
  md.push('## Counts');
  md.push('');
  md.push(`- RDS 30 1180d2ff: ${sources.length}`);
  md.push(`- ACK 24 1f00d2ff: ${observedAcks.length}`);
  md.push(`- Paired by seq: ${paired}`);
  md.push('');
  md.push('## Best models');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(best, null, 2));
  md.push('```');
  md.push('');
  md.push('## Model stats');
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(modelStats, null, 2));
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
    bestModels: result.bestModels,
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
