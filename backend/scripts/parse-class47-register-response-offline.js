#!/usr/bin/env node
'use strict';

/**
 * Offline parser for FSU/Emerson SiteUnit2 classByte=0x47 register/config response payload.
 * Safety: parses payload hex only. It does not open sockets and does not send UDP.
 */

const REQUIRED_MASK_BY_TYPE = new Map([
  [0, 0x01], // diagnostic data channel
  [5, 0x02], // uplink publish channel
  [6, 0x04], // event data channel
  [7, 0x08], // real-time data channel
  [8, 0x10], // history data channel
  [9, 0x20], // image publish channel
]);

const RESULT_MEANING = {
  0: 'Success',
  1: 'Fail',
  2: 'UnRegister',
};

const CHANNEL_MEANING = {
  0: 'diagnostic data channel / 诊断数据通道',
  1: 'signal/config data channel / 信号数据通道（全文配置数据等）',
  5: 'uplink publish channel / 上行发布通道',
  6: 'event data channel / 事件数据通道',
  7: 'real-time data channel / 实时数据通道',
  8: 'history data channel / 历史数据通道',
  9: 'image publish channel / 图像发布通道',
};

function usage() {
  console.error('Usage: node backend/scripts/parse-class47-register-response-offline.js --payload-hex <hex>');
  process.exit(2);
}

function argValue(name) {
  const idx = process.argv.indexOf(name);
  if (idx === -1 || idx + 1 >= process.argv.length) return null;
  return process.argv[idx + 1];
}

function cleanHex(hex) {
  return String(hex || '').replace(/[^0-9a-fA-F]/g, '').toLowerCase();
}

function parseUri(uri) {
  const match = uri.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):\/\/(.*)$/);
  if (!match) {
    return { scheme: null, host: null, port: null, rawAddress: uri, parseWarning: 'URI does not contain scheme:// prefix' };
  }
  const scheme = match[1].toLowerCase();
  const rest = match[2];
  let hostPort = rest;
  let userInfo = null;
  if (hostPort.includes('@')) {
    const parts = hostPort.split('@');
    userInfo = parts.slice(0, -1).join('@');
    hostPort = parts[parts.length - 1];
  }
  let host = hostPort;
  let port = null;
  const lastColon = hostPort.lastIndexOf(':');
  if (lastColon > -1 && lastColon !== hostPort.length - 1) {
    host = hostPort.slice(0, lastColon);
    const portStr = hostPort.slice(lastColon + 1);
    const n = Number.parseInt(portStr, 10);
    if (Number.isFinite(n)) port = n;
  }
  return { scheme, host, port, userInfo, rawAddress: rest };
}

function parsePayload(buf) {
  const warnings = [];
  if (buf.length < 3) {
    throw new Error(`payload too short: ${buf.length}; expected at least 3 bytes`);
  }
  const resultCode = buf[0];
  const serviceCountCandidate = buf.readUInt16LE(1);
  let offset = 3;
  let observedMask = 0;
  const entries = [];

  for (let i = 0; i < serviceCountCandidate; i++) {
    if (offset + 2 > buf.length) {
      warnings.push(`entry ${i}: truncated before channelType/uriLength at offset ${offset}`);
      break;
    }
    const channelType = buf[offset++];
    const uriLength = buf[offset++];
    if (offset + uriLength > buf.length) {
      warnings.push(`entry ${i}: uriLength=${uriLength} exceeds payload boundary at offset ${offset}`);
      break;
    }
    const uriBytes = buf.slice(offset, offset + uriLength);
    offset += uriLength;
    const uri = uriBytes.toString('ascii').replace(/\x00+$/g, '');
    if (REQUIRED_MASK_BY_TYPE.has(channelType)) {
      observedMask |= REQUIRED_MASK_BY_TYPE.get(channelType);
    }
    entries.push({
      index: i,
      channelType,
      channelMeaning: CHANNEL_MEANING[channelType] || 'other/unknown channel',
      uriLength,
      uri,
      uriHex: uriBytes.toString('hex'),
      parsedUri: parseUri(uri),
      requiredMaskContribution: REQUIRED_MASK_BY_TYPE.has(channelType)
        ? `0x${REQUIRED_MASK_BY_TYPE.get(channelType).toString(16).padStart(2, '0')}`
        : '0x00',
    });
  }

  if (offset < buf.length) {
    warnings.push(`${buf.length - offset} trailing byte(s) remain after parsing serviceCountCandidate entries`);
  }

  const requiredMask = 0x3f;
  return {
    safety: 'offline parser only; no UDP sent; no ACK sent',
    payloadLength: buf.length,
    resultCode,
    resultMeaning: RESULT_MEANING[resultCode] || 'unknown',
    serviceCountCandidate,
    parsedEntryCount: entries.length,
    entries,
    observedMask: `0x${observedMask.toString(16).padStart(2, '0')}`,
    requiredMask: `0x${requiredMask.toString(16).padStart(2, '0')}`,
    requiredChannelsComplete: observedMask === requiredMask,
    successConditionCandidateMet: resultCode === 0 && observedMask === requiredMask,
    remainingUncertainty: [
      'This parser uses the current SiteUnit2-derived candidate format: resultCode + uint16LE count + entries(type,len,uri).',
      'It does not prove the complete 0x47 frame header, checksum, or safe online response behavior.',
    ],
    warnings,
  };
}

const hex = cleanHex(argValue('--payload-hex'));
if (!hex || hex.length % 2 !== 0) usage();
try {
  const result = parsePayload(Buffer.from(hex, 'hex'));
  console.log(JSON.stringify(result, null, 2));
} catch (err) {
  console.error(`Error: ${err.message}`);
  process.exit(1);
}
