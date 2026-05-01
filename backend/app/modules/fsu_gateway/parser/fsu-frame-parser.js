#!/usr/bin/env node
"use strict";

const {
  FRAME_CLASS_ANNOTATIONS,
  TYPE_A_ANNOTATIONS,
  getFrameClassAnnotation,
  getTypeAAnnotation,
} = require("./dsc-rds-annotations");

const EXPECTED_HEADER_HEX = "6d7e";
const CHECKSUM_OFFSET = 22;
const BODY_OFFSET = 24;

const KNOWN_MEANINGS = {
  DSC_SHORT_24_TYPE_1F00_D2FF:
    "DSC short periodic frame, likely status/heartbeat class; business meaning not confirmed",
  RDS_SHORT_30_TYPE_1180_D2FF:
    "RDS short periodic frame, likely status/heartbeat class; business meaning not confirmed",
  DSC_CONFIG_209_TYPE_1100_46FF:
    "DSC long frame carrying DHCP-based service URI strings; business meaning not confirmed",
  DSC_CONFIG_245_TYPE_1100_46FF:
    "DSC long frame carrying explicit IP-based service URI strings; business meaning not confirmed",
};

const DSC_CONFIG_FRAME_CLASSES = new Set([
  "DSC_CONFIG_209_TYPE_1100_46FF",
  "DSC_CONFIG_245_TYPE_1100_46FF",
]);

const SHORT_FRAME_CLASSES = new Set([
  "DSC_SHORT_24_TYPE_1F00_D2FF",
  "RDS_SHORT_30_TYPE_1180_D2FF",
]);

function cleanHex(rawHex) {
  return String(rawHex || "").replace(/[^0-9a-f]/gi, "").toLowerCase();
}

function toBuffer(input) {
  if (Buffer.isBuffer(input)) {
    return { ok: true, buf: input, error: null };
  }

  const hex = cleanHex(input);
  if (!hex) {
    return { ok: false, buf: Buffer.alloc(0), error: "empty rawHex" };
  }
  if (hex.length % 2 !== 0) {
    return { ok: false, buf: Buffer.alloc(0), error: "rawHex has odd hex length" };
  }

  return { ok: true, buf: Buffer.from(hex, "hex"), error: null };
}

function hexSlice(buf, start, end) {
  if (start >= buf.length) {
    return "";
  }
  return buf.subarray(start, Math.min(end, buf.length)).toString("hex");
}

function readUInt16(buf, offset, endian) {
  if (offset < 0 || offset + 1 >= buf.length) {
    return null;
  }
  return endian === "le" ? buf.readUInt16LE(offset) : buf.readUInt16BE(offset);
}

function readByte(buf, offset) {
  return offset >= 0 && offset < buf.length ? buf[offset] : null;
}

function computeFsuChecksum(buffer) {
  if (!Buffer.isBuffer(buffer) || buffer.length < 2) {
    return null;
  }
  const copy = Buffer.from(buffer);
  if (copy.length > CHECKSUM_OFFSET + 1) {
    copy[CHECKSUM_OFFSET] = 0;
    copy[CHECKSUM_OFFSET + 1] = 0;
  }
  let sum = 0;
  for (let i = 2; i < copy.length; i += 1) {
    sum = (sum + copy[i]) & 0xffff;
  }
  return sum;
}

function checksumInfo(buf) {
  const checksumStoredLE = readUInt16(buf, CHECKSUM_OFFSET, "le");
  const checksumStoredBE = readUInt16(buf, CHECKSUM_OFFSET, "be");
  const checksumCalculated = computeFsuChecksum(buf);
  const checksumValidLE = checksumStoredLE !== null && checksumCalculated !== null && checksumStoredLE === checksumCalculated;
  const checksumValidBE = checksumStoredBE !== null && checksumCalculated !== null && checksumStoredBE === checksumCalculated;
  return {
    checksumStored: checksumStoredLE,
    checksumStoredHex: hexSlice(buf, CHECKSUM_OFFSET, CHECKSUM_OFFSET + 2),
    checksumStoredLE,
    checksumStoredBE,
    checksumCalculated,
    checksumCalculatedLE: checksumCalculated,
    checksumCalculatedBE: checksumCalculated,
    checksumValidLE,
    checksumValidBE,
    checksumValid: checksumValidLE || checksumValidBE,
    checksumEndianGuess: checksumValidLE ? "LE" : checksumValidBE ? "BE" : "unknown",
  };
}

function classifyFrame({ protocol, totalLength, typeA }) {
  if (protocol === "UDP_DSC" && totalLength === 24 && typeA === "1f00d2ff") {
    return "DSC_SHORT_24_TYPE_1F00_D2FF";
  }
  if (protocol === "UDP_DSC" && totalLength === 209 && typeA === "110046ff") {
    return "DSC_CONFIG_209_TYPE_1100_46FF";
  }
  if (protocol === "UDP_DSC" && totalLength === 245 && typeA === "110046ff") {
    return "DSC_CONFIG_245_TYPE_1100_46FF";
  }
  if (protocol === "UDP_RDS" && totalLength === 30 && typeA === "1180d2ff") {
    return "RDS_SHORT_30_TYPE_1180_D2FF";
  }
  return "UNKNOWN";
}

function scanAsciiSpans(buf, minLen = 4, baseOffset = 0) {
  const spans = [];
  let start = -1;

  for (let i = 0; i <= buf.length; i += 1) {
    const byte = i < buf.length ? buf[i] : -1;
    const printable = byte >= 0x20 && byte <= 0x7e;

    if (printable && start < 0) {
      start = i;
    }

    if ((!printable || i === buf.length) && start >= 0) {
      if (i - start >= minLen) {
        spans.push({
          offsetStart: baseOffset + start,
          offsetEnd: baseOffset + i - 1,
          length: i - start,
          text: buf.subarray(start, i).toString("ascii"),
        });
      }
      start = -1;
    }
  }

  return spans;
}

function spanWithBodyOffsets(span) {
  return {
    offsetInFrame: span.offsetStart,
    offsetInBody: span.offsetStart - BODY_OFFSET,
    offsetEndInFrame: span.offsetEnd,
    offsetEndInBody: span.offsetEnd - BODY_OFFSET,
    length: span.length,
    text: span.text,
  };
}

function scanAsciiRegions(body, minLen = 3) {
  return scanAsciiSpans(body, minLen, BODY_OFFSET).map((span) => ({
    ...spanWithBodyOffsets(span),
    hex: hexSlice(body, span.offsetStart - BODY_OFFSET, span.offsetEnd - BODY_OFFSET + 1),
  }));
}

function scanZeroTerminatedStrings(body, minLen = 3) {
  const strings = [];
  let start = -1;

  for (let i = 0; i < body.length; i += 1) {
    const byte = body[i];
    const printable = byte >= 0x20 && byte <= 0x7e;

    if (printable && start < 0) {
      start = i;
    }

    if (byte === 0x00) {
      if (start >= 0 && i - start >= minLen) {
        strings.push({
          offsetInFrame: BODY_OFFSET + start,
          offsetInBody: start,
          offsetEndInFrame: BODY_OFFSET + i,
          offsetEndInBody: i,
          length: i - start,
          text: body.subarray(start, i).toString("ascii"),
          hex: body.subarray(start, i + 1).toString("hex"),
          terminatorHex: "00",
        });
      }
      start = -1;
      continue;
    }

    if (!printable) {
      start = -1;
    }
  }

  return strings;
}

function extractUris(asciiSpans) {
  const uriRegex = /\b(?:udp|ftp):\/\/[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]+/gi;
  const values = [];

  for (const span of asciiSpans) {
    const matches = span.text.match(uriRegex) || [];
    for (const match of matches) {
      values.push(match);
    }
  }

  return values;
}

function uriFieldsFromAsciiRegions(asciiRegions, body) {
  const uriFields = [];
  const uriRegex = /\b(?:udp|ftp):\/\/[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]+/gi;

  for (const region of asciiRegions) {
    let match;
    while ((match = uriRegex.exec(region.text)) !== null) {
      const uri = match[0];
      const offsetInFrame = region.offsetInFrame + match.index;
      const offsetInBody = region.offsetInBody + match.index;
      const length = uri.length;
      const before1Offset = offsetInBody - 1;
      const before2Offset = offsetInBody - 2;
      const prefixBytes = body.subarray(Math.max(0, offsetInBody - 2), offsetInBody);

      uriFields.push({
        offsetInFrame,
        offsetInBody,
        length,
        text: uri,
        scheme: uri.split(":", 1)[0].toLowerCase(),
        hex: Buffer.from(uri, "ascii").toString("hex"),
        precedingByteHex: before1Offset >= 0 ? hexSlice(body, before1Offset, before1Offset + 1) : "",
        precedingByteDecimal: before1Offset >= 0 ? body[before1Offset] : null,
        preceding2BytesHex: prefixBytes.toString("hex"),
        preceding2BytesDecimal: [...prefixBytes].map((byte) => byte),
      });
    }
  }

  return uriFields;
}

function extractIpAddresses(asciiSpans) {
  const ipRegex = /\b(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b/g;
  const values = [];

  for (const span of asciiSpans) {
    const matches = span.text.match(ipRegex) || [];
    for (const match of matches) {
      values.push(match);
    }
  }

  return values;
}

function extractIpAddressesFromTextValues(values) {
  return extractIpAddresses(values.map((text) => ({ text })));
}

function extractPorts(uris) {
  const ports = [];

  for (const uri of uris) {
    const match = uri.match(/:(\d{1,5})(?:[/?#]|$)/);
    if (!match) {
      continue;
    }

    const port = Number(match[1]);
    if (Number.isInteger(port) && port >= 0 && port <= 65535) {
      ports.push(port);
    }
  }

  return ports;
}

function extractCredentialCandidates(uris) {
  const usernameCandidates = [];
  const passwordCandidates = [];
  const credentialCandidates = [];

  for (const uri of uris) {
    const match = uri.match(/^[a-z]+:\/\/([^:@/\]]+):([^@/\]]+)@/i);
    if (!match) {
      continue;
    }
    usernameCandidates.push(match[1]);
    passwordCandidates.push(match[2]);
    credentialCandidates.push({
      uri,
      usernameCandidate: match[1],
      passwordCandidate: match[2],
    });
  }

  return { credentialCandidates, usernameCandidates, passwordCandidates };
}

function rawSummaryFor(buf, frame = {}) {
  const summary = {
    first16: hexSlice(buf, 0, 16),
    last16: buf.length > 16 ? hexSlice(buf, buf.length - 16, buf.length) : hexSlice(buf, 0, buf.length),
  };

  if (SHORT_FRAME_CLASSES.has(frame.frameClass)) {
    const body = buf.length > BODY_OFFSET ? buf.subarray(BODY_OFFSET) : Buffer.alloc(0);
    summary.shortFrame = {
      frameClass: frame.frameClass,
      seqLE: frame.seqLE,
      typeA: frame.typeA,
      payloadLengthCandidate: frame.payloadLengthCandidate,
      bodyHex: body.toString("hex"),
      tail2: buf.length >= 2 ? hexSlice(buf, buf.length - 2, buf.length) : "",
      tail4: buf.length >= 4 ? hexSlice(buf, buf.length - 4, buf.length) : "",
      note: "likely periodic/status class; not confirmed",
    };
  }

  return summary;
}

function rangeHex(buf, start, endExclusive) {
  if (start >= endExclusive || start >= buf.length) {
    return "";
  }
  return hexSlice(buf, Math.max(0, start), Math.min(endExclusive, buf.length));
}

function parseDscConfigPayload(buffer, frame = {}) {
  if (!Buffer.isBuffer(buffer) || !DSC_CONFIG_FRAME_CLASSES.has(frame.frameClass)) {
    return {
      isDscConfigFrame: false,
    };
  }

  const body = buffer.length > BODY_OFFSET ? buffer.subarray(BODY_OFFSET) : Buffer.alloc(0);
  const asciiRegions = scanAsciiRegions(body, 3);
  const zeroTerminatedStrings = scanZeroTerminatedStrings(body, 3);
  const uriFields = uriFieldsFromAsciiRegions(asciiRegions, body);
  const uris = uriFields.map((field) => field.text);
  const udpUris = uriFields.filter((field) => field.scheme === "udp").map((field) => field.text);
  const ftpUris = uriFields.filter((field) => field.scheme === "ftp").map((field) => field.text);
  const ipAddresses = extractIpAddressesFromTextValues(asciiRegions.map((region) => region.text));
  const ports = extractPorts(uris);
  const { credentialCandidates, usernameCandidates, passwordCandidates } = extractCredentialCandidates(ftpUris);
  const firstUri = uriFields.length ? uriFields[0] : null;
  const lastUri = uriFields.length ? uriFields[uriFields.length - 1] : null;
  const firstAscii = asciiRegions.length ? asciiRegions[0] : null;
  const lastAscii = asciiRegions.length ? asciiRegions[asciiRegions.length - 1] : null;

  return {
    isDscConfigFrame: true,
    configPayloadOffset: BODY_OFFSET,
    declaredPayloadLength: frame.payloadLengthCandidate,
    payloadHex: body.toString("hex"),
    asciiRegions,
    zeroTerminatedStrings,
    uriFields,
    udpUris,
    ftpUris,
    ipAddresses,
    ports,
    credentialCandidates,
    usernameCandidates,
    passwordCandidates,
    usesDhcpPlaceholder: uris.some((uri) => uri.includes("[dhcp]")),
    usesExplicitIp: ipAddresses.length > 0,
    fixedBinaryPrefix: {
      beforeFirstAsciiHex: firstAscii ? rangeHex(body, 0, firstAscii.offsetInBody) : body.toString("hex"),
      beforeFirstUriHex: firstUri ? rangeHex(body, 0, firstUri.offsetInBody) : body.toString("hex"),
    },
    variableFields: {
      uriPrefixBytes: uriFields.map((field) => ({
        offsetInFrame: field.offsetInFrame,
        offsetInBody: field.offsetInBody,
        precedingByteHex: field.precedingByteHex,
        precedingByteDecimal: field.precedingByteDecimal,
        preceding2BytesHex: field.preceding2BytesHex,
      })),
      zeroTerminatedStringCount: zeroTerminatedStrings.length,
      asciiRegionCount: asciiRegions.length,
      uriCount: uriFields.length,
    },
    stringLayout: {
      bodyAsciiStartOffset: firstAscii ? firstAscii.offsetInFrame : null,
      bodyAsciiEndOffset: lastAscii ? lastAscii.offsetEndInFrame : null,
      firstUriOffset: firstUri ? firstUri.offsetInFrame : null,
      lastUriOffset: lastUri ? lastUri.offsetInFrame : null,
      uriOffsets: uriFields.map((field) => ({
        scheme: field.scheme,
        offsetInFrame: field.offsetInFrame,
        offsetInBody: field.offsetInBody,
        length: field.length,
        text: field.text,
      })),
      zeroTerminatedStringOffsets: zeroTerminatedStrings.map((field) => ({
        offsetInFrame: field.offsetInFrame,
        offsetInBody: field.offsetInBody,
        length: field.length,
        text: field.text,
      })),
    },
  };
}

function parseFsuFrame(input, options = {}) {
  const inputResult = toBuffer(input);
  const buf = inputResult.buf;
  const protocol = options.protocol;
  const totalLength = buf.length;
  const headerHex = hexSlice(buf, 0, 2);
  const typeA = hexSlice(buf, 4, 8);
  const headerByte4 = readByte(buf, 4);
  const headerByte5 = readByte(buf, 5);
  const headerByte6 = readByte(buf, 6);
  const headerByte7 = readByte(buf, 7);
  const payloadLengthCandidate = readUInt16(buf, 20, "le");
  const payloadLengthBE = readUInt16(buf, 20, "be");
  const body = totalLength > BODY_OFFSET ? buf.subarray(BODY_OFFSET) : Buffer.alloc(0);
  const asciiSpans = options.includeAscii === false ? undefined : scanAsciiSpans(buf);
  const uris = asciiSpans ? extractUris(asciiSpans) : [];
  const ipAddresses = asciiSpans ? extractIpAddresses(asciiSpans) : [];
  const ports = extractPorts(uris);
  const frameClass = classifyFrame({ protocol, totalLength, typeA });
  const checksum = checksumInfo(buf);

  const parsed = {
    ok: inputResult.ok,
    protocol,
    frameClass,
    totalLength,
    headerHex,
    magicHex: headerHex,
    validHeader: headerHex === EXPECTED_HEADER_HEX,
    seqLE: readUInt16(buf, 2, "le"),
    seqBE: readUInt16(buf, 2, "be"),
    typeA,
    typeBytesSummary: typeA,
    headerByte4,
    headerByte5,
    headerByte6,
    headerByte7,
    typeByte: headerByte4,
    flagByte: headerByte5,
    classByte: headerByte6,
    tailByte: headerByte7,
    ackRequiredFlag: headerByte5 !== null ? (headerByte5 & 0x80) !== 0 : null,
    typeBytes: {
      headerByte4,
      headerByte5,
      headerByte6,
      headerByte7,
      typeByte: headerByte4,
      flagByte: headerByte5,
      classByte: headerByte6,
      tailByte: headerByte7,
      ackRequiredFlag: headerByte5 !== null ? (headerByte5 & 0x80) !== 0 : null,
    },
    payloadLengthCandidate,
    payloadLengthLE: payloadLengthCandidate,
    payloadLengthBE,
    payloadLengthMatchesTotalMinus24:
      payloadLengthCandidate !== null ? payloadLengthCandidate === totalLength - 24 : false,
    checksumOffset: CHECKSUM_OFFSET,
    checksumLE: readUInt16(buf, CHECKSUM_OFFSET, "le"),
    checksumStored: checksum.checksumStored,
    checksumStoredHex: checksum.checksumStoredHex,
    checksumStoredLE: checksum.checksumStoredLE,
    checksumStoredBE: checksum.checksumStoredBE,
    checksumCalculated: checksum.checksumCalculated,
    checksumCalculatedLE: checksum.checksumCalculatedLE,
    checksumCalculatedBE: checksum.checksumCalculatedBE,
    checksumValidLE: checksum.checksumValidLE,
    checksumValidBE: checksum.checksumValidBE,
    checksumValid: checksum.checksumValid,
    checksumEndianGuess: checksum.checksumEndianGuess,
    bodyOffset: BODY_OFFSET,
    bodyLength: body.length,
    bodyHex: options.includePayloadHex ? body.toString("hex") : undefined,
    bodyTail2: totalLength >= 2 ? hexSlice(buf, totalLength - 2, totalLength) : "",
    bodyTail4: totalLength >= 4 ? hexSlice(buf, totalLength - 4, totalLength) : "",
    asciiSpans,
    uris,
    ipAddresses,
    ports,
    knownMeaning: KNOWN_MEANINGS[frameClass] || "Unknown frame class; business meaning not confirmed",
    annotation: getFrameClassAnnotation(frameClass),
    typeAAnnotation: getTypeAAnnotation(typeA),
    rawSummary: null,
  };

  parsed.rawSummary = rawSummaryFor(buf, parsed);

  if (inputResult.error) {
    parsed.error = inputResult.error;
  }

  if (DSC_CONFIG_FRAME_CLASSES.has(frameClass)) {
    parsed.dscConfig = parseDscConfigPayload(buf, parsed);
  }

  return parsed;
}

module.exports = {
  BODY_OFFSET,
  CHECKSUM_OFFSET,
  EXPECTED_HEADER_HEX,
  FRAME_CLASS_ANNOTATIONS,
  KNOWN_MEANINGS,
  TYPE_A_ANNOTATIONS,
  cleanHex,
  computeFsuChecksum,
  getFrameClassAnnotation,
  getTypeAAnnotation,
  parseDscConfigPayload,
  parseFsuFrame,
};
