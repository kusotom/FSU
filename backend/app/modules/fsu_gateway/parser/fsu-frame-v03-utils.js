/**
 * FSU DSC/RDS frame v0.3 helper utilities.
 *
 * This file is offline-safe: it does not open sockets and does not send UDP.
 * It only parses hex/buffer data, verifies checksum, and builds ACK candidates.
 */

function normalizeHex(input) {
  if (input == null) return "";
  if (Buffer.isBuffer(input)) return input.toString("hex");
  if (Array.isArray(input)) return Buffer.from(input).toString("hex");
  if (typeof input !== "string") return "";
  let s = input.trim();
  if (s.startsWith("0x") || s.startsWith("0X")) s = s.slice(2);
  s = s.replace(/[^0-9a-fA-F]/g, "");
  return s.length % 2 === 0 ? s.toLowerCase() : "";
}

function bufferFromHex(input) {
  const hex = normalizeHex(input);
  if (!hex) return null;
  return Buffer.from(hex, "hex");
}

function hex2(n) {
  return Number(n & 0xff).toString(16).padStart(2, "0");
}

function hex4(n) {
  return Number(n & 0xffff).toString(16).padStart(4, "0");
}

function readU16LE(buf, off) {
  if (!buf || buf.length < off + 2) return null;
  return buf[off] | (buf[off + 1] << 8);
}

function readU16BE(buf, off) {
  if (!buf || buf.length < off + 2) return null;
  return (buf[off] << 8) | buf[off + 1];
}

function calcFsuChecksum(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 24) return null;
  const tmp = Buffer.from(buf);
  tmp[22] = 0;
  tmp[23] = 0;
  let sum = 0;
  for (let i = 2; i < tmp.length; i += 1) {
    sum = (sum + tmp[i]) & 0xffff;
  }
  return sum;
}

function parseFsuFrame(input) {
  const buf = Buffer.isBuffer(input) ? Buffer.from(input) : bufferFromHex(input);
  if (!buf || buf.length < 8) {
    return { ok: false, error: "frame too short", totalLength: buf ? buf.length : 0 };
  }

  const totalLength = buf.length;
  const typeByte = totalLength > 4 ? buf[4] : null;
  const flagByte = totalLength > 5 ? buf[5] : null;
  const classByte = totalLength > 6 ? buf[6] : null;
  const tailByte = totalLength > 7 ? buf[7] : null;

  const payloadLengthLE = totalLength >= 22 ? readU16LE(buf, 20) : null;
  const payloadLengthBE = totalLength >= 22 ? readU16BE(buf, 20) : null;
  const checksumStoredLE = totalLength >= 24 ? readU16LE(buf, 22) : null;
  const checksumStoredBE = totalLength >= 24 ? readU16BE(buf, 22) : null;
  const checksumCalculated = totalLength >= 24 ? calcFsuChecksum(buf) : null;

  const checksumValidLE = checksumCalculated != null && checksumStoredLE === checksumCalculated;
  const checksumValidBE = checksumCalculated != null && checksumStoredBE === checksumCalculated;
  const checksumEndianGuess = checksumValidLE ? "LE" : (checksumValidBE ? "BE" : null);

  const payloadLengthMatches = payloadLengthLE != null && payloadLengthLE === Math.max(0, totalLength - 24);

  const typeBytesSummary = [typeByte, flagByte, classByte, tailByte]
    .map(v => v == null ? "??" : hex2(v))
    .join("");

  return {
    ok: true,
    totalLength,
    magicHex: totalLength >= 2 ? buf.slice(0, 2).toString("hex") : null,
    validMagic: totalLength >= 2 ? (buf[0] === 0x6d && buf[1] === 0x7e) : false,
    headerByte4: typeByte,
    headerByte5: flagByte,
    headerByte6: classByte,
    headerByte7: tailByte,
    typeByte,
    flagByte,
    classByte,
    tailByte,
    typeBytesSummary,
    typeA: `${hex2(typeByte || 0)}${hex2(flagByte || 0)}_${hex2(classByte || 0)}${hex2(tailByte || 0)}`,
    ackRequiredFlag: flagByte != null ? ((flagByte & 0x80) !== 0) : false,
    seqLE: totalLength >= 4 ? readU16LE(buf, 2) : null,
    seqBE: totalLength >= 4 ? readU16BE(buf, 2) : null,
    payloadLengthLE,
    payloadLengthBE,
    payloadLengthMatchesTotalMinus24: payloadLengthMatches,
    checksumStoredLE,
    checksumStoredBE,
    checksumStoredHex: totalLength >= 24 ? buf.slice(22, 24).toString("hex") : null,
    checksumCalculated,
    checksumCalculatedHex: checksumCalculated == null ? null : hex4(checksumCalculated),
    checksumValid: checksumValidLE || checksumValidBE,
    checksumValidLE,
    checksumValidBE,
    checksumEndianGuess,
    bodyOffset: 24,
    bodyLength: totalLength >= 24 ? totalLength - 24 : 0,
    bodyHex: totalLength >= 24 ? buf.slice(24).toString("hex") : ""
  };
}

function buildAckCandidate(input) {
  const buf = Buffer.isBuffer(input) ? Buffer.from(input) : bufferFromHex(input);
  if (!buf || buf.length < 24) {
    throw new Error("raw packet must be at least 24 bytes");
  }
  const original = parseFsuFrame(buf);
  const ack = Buffer.from(buf.slice(0, 24));
  ack[4] = 0x1f;
  ack[5] = 0x00;
  // Keep byte6 / byte7, seq, and other header fields.
  ack[20] = 0x00;
  ack[21] = 0x00;
  ack[22] = 0x00;
  ack[23] = 0x00;
  const checksum = calcFsuChecksum(ack);
  ack[22] = checksum & 0xff;
  ack[23] = (checksum >> 8) & 0xff;
  return {
    original,
    ack: parseFsuFrame(ack),
    ackHex: ack.toString("hex")
  };
}

function findHexCandidate(obj) {
  if (!obj || typeof obj !== "object") return null;
  const priority = [
    "rawHex", "packetHex", "frameHex", "dataHex", "hex", "payloadHex",
    "raw", "packet", "data", "message"
  ];
  for (const k of priority) {
    if (typeof obj[k] === "string") {
      const h = normalizeHex(obj[k]);
      if (h.length >= 48) return h;
    }
  }
  // Recursive fallback, restricted to reasonably packet-looking strings.
  const stack = [obj];
  const seen = new Set();
  while (stack.length) {
    const cur = stack.pop();
    if (!cur || typeof cur !== "object" || seen.has(cur)) continue;
    seen.add(cur);
    for (const [k, v] of Object.entries(cur)) {
      if (typeof v === "string") {
        const h = normalizeHex(v);
        if (h.length >= 48 && h.startsWith("6d7e")) return h;
      } else if (v && typeof v === "object") {
        stack.push(v);
      }
    }
  }
  return null;
}

module.exports = {
  normalizeHex,
  bufferFromHex,
  hex2,
  hex4,
  readU16LE,
  readU16BE,
  calcFsuChecksum,
  parseFsuFrame,
  buildAckCandidate,
  findHexCandidate
};
