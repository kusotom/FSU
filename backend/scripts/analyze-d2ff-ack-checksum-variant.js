#!/usr/bin/env node
'use strict';

/**
 * analyze-d2ff-ack-checksum-variant.js
 *
 * OFFLINE ONLY. This script never opens sockets and never sends UDP.
 *
 * Purpose:
 *   Investigate why FSU_LEN_24_TYPE_1F00_D2FF does not validate under the
 *   normal SiteUnit2 checksum model, while 30/209/245 frames do.
 *
 * It extracts:
 *   - request/heartbeat frames: len=30, typeBytes=1180d2ff
 *   - ack/confirm frames:      len=24, typeBytes=1f00d2ff
 *
 * Then it:
 *   1) pairs by seq when possible
 *   2) tests several checksum hypotheses on the 24-byte frame
 *   3) compares ack checksum with paired 30-byte frame fields
 *   4) reports repeated deltas/xors and other patterns
 *
 * Usage:
 *   node backend/scripts/analyze-d2ff-ack-checksum-variant.js --input backend/logs/fsu_raw_packets/2026-05-01.jsonl
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

function le16(buf, off) { return buf[off] | (buf[off+1] << 8); }
function be16(buf, off) { return (buf[off] << 8) | buf[off+1]; }

function sumRange(buf, start, endExclusive, zeroChecksum=false) {
  const tmp = Buffer.from(buf);
  if (zeroChecksum && tmp.length >= 24) { tmp[22] = 0; tmp[23] = 0; }
  let s = 0;
  for (let i = start; i < Math.min(endExclusive, tmp.length); i++) s = (s + tmp[i]) & 0xffff;
  return s;
}

function onesComplement16(x) { return (~x) & 0xffff; }
function neg16(x) { return (-x) & 0xffff; }
function fmt16(x) { return '0x' + (x & 0xffff).toString(16).padStart(4, '0'); }

function frameInfo(h, lineNo, ts, sourceField) {
  const b = bytesFromHex(h);
  return {
    lineNo, timestamp: ts, sourceField,
    rawHex: h,
    buf: b,
    totalLength: b.length,
    magic: hex(b.slice(0,2)),
    seqLE: le16(b,2),
    seqBytes: hex(b.slice(2,4)),
    typeBytes: hex(b.slice(4,8)),
    typeByte: b[4],
    flagByte: b[5],
    classByte: b[6],
    tailByte: b[7],
    payloadLengthLE: b.length >= 22 ? le16(b,20) : null,
    checksumStoredLE: b.length >= 24 ? le16(b,22) : null,
    checksumStoredBE: b.length >= 24 ? be16(b,22) : null,
  };
}

function inc(map, key, n=1) {
  map[key] = (map[key] || 0) + n;
}

function topMap(map, limit=20) {
  return Object.entries(map).sort((a,b) => b[1]-a[1] || a[0].localeCompare(b[0])).slice(0, limit).map(([k,v]) => ({ value:k, count:v }));
}

function checksumHypotheses(frame) {
  const b = frame.buf;
  const storedLE = frame.checksumStoredLE;
  const storedBE = frame.checksumStoredBE;

  const variants = [];
  function add(name, calc) {
    variants.push({
      name,
      calculated: fmt16(calc),
      matchesLE: storedLE === calc,
      matchesBE: storedBE === calc,
      deltaLE: fmt16((storedLE - calc) & 0xffff),
      xorLE: fmt16((storedLE ^ calc) & 0xffff),
    });
  }

  add('normal_sum_bytes_2_to_end_zero_22_23', sumRange(b, 2, b.length, true));
  add('sum_bytes_0_to_end_zero_22_23', sumRange(b, 0, b.length, true));
  add('sum_bytes_4_to_end_zero_22_23', sumRange(b, 4, b.length, true));
  add('sum_bytes_2_to_22_exclusive', sumRange(b, 2, 22, false));
  add('sum_bytes_0_to_22_exclusive', sumRange(b, 0, 22, false));
  add('sum_bytes_4_to_22_exclusive', sumRange(b, 4, 22, false));
  add('sum_header_2_to_20_exclusive', sumRange(b, 2, 20, false));
  add('sum_typebytes_4_to_8', sumRange(b, 4, 8, false));
  add('ones_complement_normal', onesComplement16(sumRange(b, 2, b.length, true)));
  add('negative_normal', neg16(sumRange(b, 2, b.length, true)));

  return variants;
}

function main() {
  const input = argValue('--input') || 'backend/logs/fsu_raw_packets/2026-05-01.jsonl';
  const outJson = argValue('--out-json') || input.replace(/\.jsonl$/i, '').replace(/[\\\/][^\\\/]*$/, '/d2ff-ack-checksum-variant-analysis.json');
  const outMd = argValue('--out-md') || input.replace(/\.jsonl$/i, '').replace(/[\\\/][^\\\/]*$/, '/d2ff-ack-checksum-variant-analysis.md');

  if (!fs.existsSync(input)) throw new Error(`input not found: ${input}`);

  const lines = fs.readFileSync(input, 'utf8').split(/\r?\n/);
  const rds30 = [];
  const ack24 = [];
  let totalLines=0, parsedLines=0, framesSeen=0;

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
      if ((b.length === 30 && typeBytes === '1180d2ff') || (b.length === 24 && typeBytes === '1f00d2ff')) {
        const info = frameInfo(c.hex, i+1, ts, c.keyPath);
        framesSeen++;
        if (b.length === 30) rds30.push(info);
        else ack24.push(info);
        break;
      }
    }
  }

  const rdsBySeq = new Map();
  for (const f of rds30) {
    const key = f.seqLE;
    if (!rdsBySeq.has(key)) rdsBySeq.set(key, []);
    rdsBySeq.get(key).push(f);
  }

  const hypothesisStats = {};
  const deltaNormal = {};
  const xorNormal = {};
  const ackStoredValues = {};
  const relationToRds = {
    pairedCount: 0,
    ackStoredEqualsRdsStoredLE: 0,
    ackStoredEqualsRdsStoredBE: 0,
    ackStoredEqualsRdsNormalCalc: 0,
    ackSeqMatchesRdsSeq: 0,
    rdsStoredLE_minus_ackStoredLE: {},
    ackStoredLE_minus_rdsStoredLE: {},
    ackStoredLE_xor_rdsStoredLE: {},
  };

  const samples = [];
  for (const ack of ack24) {
    inc(ackStoredValues, fmt16(ack.checksumStoredLE));
    const vars = checksumHypotheses(ack);
    const normal = vars.find(v=>v.name==='normal_sum_bytes_2_to_end_zero_22_23');
    inc(deltaNormal, normal.deltaLE);
    inc(xorNormal, normal.xorLE);
    for (const v of vars) {
      if (!hypothesisStats[v.name]) hypothesisStats[v.name] = { matchesLE:0, matchesBE:0, examples:[] };
      if (v.matchesLE) hypothesisStats[v.name].matchesLE++;
      if (v.matchesBE) hypothesisStats[v.name].matchesBE++;
      if ((v.matchesLE || v.matchesBE) && hypothesisStats[v.name].examples.length < 3) {
        hypothesisStats[v.name].examples.push({ lineNo: ack.lineNo, seqLE: ack.seqLE, storedLE: fmt16(ack.checksumStoredLE), calculated: v.calculated });
      }
    }

    const pairList = rdsBySeq.get(ack.seqLE) || [];
    if (pairList.length) {
      const rds = pairList[pairList.length - 1];
      relationToRds.pairedCount++;
      relationToRds.ackSeqMatchesRdsSeq++;
      const rdsNormal = sumRange(rds.buf, 2, rds.buf.length, true);
      if (ack.checksumStoredLE === rds.checksumStoredLE) relationToRds.ackStoredEqualsRdsStoredLE++;
      if (ack.checksumStoredLE === rds.checksumStoredBE) relationToRds.ackStoredEqualsRdsStoredBE++;
      if (ack.checksumStoredLE === rdsNormal) relationToRds.ackStoredEqualsRdsNormalCalc++;
      inc(relationToRds.rdsStoredLE_minus_ackStoredLE, fmt16((rds.checksumStoredLE - ack.checksumStoredLE) & 0xffff));
      inc(relationToRds.ackStoredLE_minus_rdsStoredLE, fmt16((ack.checksumStoredLE - rds.checksumStoredLE) & 0xffff));
      inc(relationToRds.ackStoredLE_xor_rdsStoredLE, fmt16((ack.checksumStoredLE ^ rds.checksumStoredLE) & 0xffff));

      if (samples.length < 5) {
        samples.push({
          ack: {
            lineNo: ack.lineNo, timestamp: ack.timestamp, seqLE: ack.seqLE, typeBytes: ack.typeBytes,
            checksumStoredLE: fmt16(ack.checksumStoredLE),
            normalChecksum: normal.calculated,
            deltaNormal: normal.deltaLE,
            rawHex: ack.rawHex,
          },
          pairedRds30: {
            lineNo: rds.lineNo, timestamp: rds.timestamp, seqLE: rds.seqLE, typeBytes: rds.typeBytes,
            checksumStoredLE: fmt16(rds.checksumStoredLE),
            normalChecksum: fmt16(rdsNormal),
            rawHex: rds.rawHex,
          }
        });
      }
    }
  }

  const result = {
    safety: 'offline checksum analysis only; no UDP sent; no ACK sent',
    input,
    totalLines,
    parsedLines,
    framesSeen,
    counts: {
      rds30_1180d2ff: rds30.length,
      ack24_1f00d2ff: ack24.length,
    },
    pairing: {
      pairedBySeq: relationToRds.pairedCount,
      ackSeqMatchesRdsSeq: relationToRds.ackSeqMatchesRdsSeq,
    },
    hypothesisStats,
    topPatterns: {
      ackStoredValues: topMap(ackStoredValues, 20),
      normalDeltaLE: topMap(deltaNormal, 20),
      normalXorLE: topMap(xorNormal, 20),
      rdsStoredLE_minus_ackStoredLE: topMap(relationToRds.rdsStoredLE_minus_ackStoredLE, 20),
      ackStoredLE_minus_rdsStoredLE: topMap(relationToRds.ackStoredLE_minus_rdsStoredLE, 20),
      ackStoredLE_xor_rdsStoredLE: topMap(relationToRds.ackStoredLE_xor_rdsStoredLE, 20),
    },
    relationToRds: {
      pairedCount: relationToRds.pairedCount,
      ackStoredEqualsRdsStoredLE: relationToRds.ackStoredEqualsRdsStoredLE,
      ackStoredEqualsRdsStoredBE: relationToRds.ackStoredEqualsRdsStoredBE,
      ackStoredEqualsRdsNormalCalc: relationToRds.ackStoredEqualsRdsNormalCalc,
    },
    samples,
    interpretationHints: [
      'If no tested hypothesis matches 1F00_D2FF, it may use a special ACK checksum path, non-checksum field, or be generated by another component.',
      'If ackStored has a stable delta/xor to normal checksum, derive a candidate transform but do not use online.',
      'If ack pairs 1:1 by seq with RDS 30, semantic ACK relation remains strong even if checksum differs.',
      'Do not send any ACK while this anomaly is unresolved.',
    ],
  };

  fs.mkdirSync(path.dirname(outJson), { recursive: true });
  fs.writeFileSync(outJson, JSON.stringify(result, null, 2), 'utf8');

  const md = [];
  md.push(`# D2FF ACK checksum variant analysis`);
  md.push('');
  md.push(`Input: \`${input}\``);
  md.push('');
  md.push(`Safety: offline only; no UDP sent; no ACK sent.`);
  md.push('');
  md.push(`## Counts`);
  md.push('');
  md.push(`- RDS 30 1180d2ff: ${rds30.length}`);
  md.push(`- ACK 24 1f00d2ff: ${ack24.length}`);
  md.push(`- Paired by seq: ${relationToRds.pairedCount}`);
  md.push('');
  md.push(`## Hypothesis stats`);
  md.push('');
  md.push('| hypothesis | matchesLE | matchesBE |');
  md.push('|---|---:|---:|');
  for (const [name, st] of Object.entries(hypothesisStats)) {
    md.push(`| ${name} | ${st.matchesLE} | ${st.matchesBE} |`);
  }
  md.push('');
  md.push(`## Top normal checksum deltas`);
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(result.topPatterns.normalDeltaLE, null, 2));
  md.push('```');
  md.push('');
  md.push(`## Relation to paired RDS 30`);
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(result.relationToRds, null, 2));
  md.push('```');
  md.push('');
  md.push(`## Samples`);
  md.push('');
  md.push('```json');
  md.push(JSON.stringify(samples, null, 2));
  md.push('```');
  md.push('');
  md.push(`## Interpretation`);
  md.push('');
  md.push('- If all hypotheses remain zero-match, keep 1F00_D2FF as ACK/confirm semantic candidate but checksum variant unresolved.');
  md.push('- Do not send ACK while unresolved.');
  fs.writeFileSync(outMd, md.join('\n'), 'utf8');

  console.log(JSON.stringify({
    safety: result.safety,
    input,
    counts: result.counts,
    pairing: result.pairing,
    hypothesisSummary: Object.fromEntries(Object.entries(hypothesisStats).map(([k,v])=>[k,{matchesLE:v.matchesLE,matchesBE:v.matchesBE}])),
    topNormalDeltaLE: result.topPatterns.normalDeltaLE.slice(0, 5),
    relationToRds: result.relationToRds,
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
