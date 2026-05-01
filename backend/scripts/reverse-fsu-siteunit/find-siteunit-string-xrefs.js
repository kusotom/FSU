#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DATE_STEM = "2026-04-28";
const DEFAULT_FIRMWARE_ROOT = path.join(process.env.USERPROFILE || process.cwd(), "Desktop", "FSU");
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

const TARGET_STRINGS = [
  "LOGIN_ACK",
  "LOGIN",
  "Register OK",
  "LoginToDSC",
  "Login to Dsc timeout",
  "ParseData",
  "fail SOI",
  "fail checksum",
  "fail length",
  "LogToDS return",
  "SendHeartbeat",
];

const LOGIN_REGION_STRINGS = [
  "LoginToDSC",
  "LoginToDSC Result",
  "Register OK",
  "Login to Dsc timeout",
  "LogToDS return",
  "GetServiceAddr",
];

const PARSE_REGION_STRINGS = [
  "ParseData",
  "fail SOI",
  "fail checksum",
  "fail length",
  "DS busy",
  "ControlRequest",
  "SequenceId",
  "FillCmd",
  "RealDataProcess",
];

const COMMAND_TABLE_STRINGS = [
  "LOGIN",
  "LOGIN_ACK",
  "GET_DATA",
  "GET_DATA_ACK",
  "SEND_ALARM",
  "SEND_ALARM_ACK",
  "TIME_CHECK",
  "TIME_CHECK_ACK",
];

const BYTE_PATTERNS = [
  { name: "6d 7e", hex: "6d7e" },
  { name: "7e", hex: "7e" },
  { name: "1f 00 d2 ff", hex: "1f00d2ff" },
  { name: "11 00 46 ff", hex: "110046ff" },
  { name: "11 80 d2 ff", hex: "1180d2ff" },
  { name: "d2 ff", hex: "d2ff" },
  { name: "46 ff", hex: "46ff" },
];

const CRC_CONSTANTS = [
  { name: "CRC16_CCITT_POLY_0x1021_LE16", hex: "2110" },
  { name: "CRC16_MODBUS_POLY_0xA001_LE16", hex: "01a0" },
  { name: "CRC16_KERMIT_POLY_0x8408_LE16", hex: "0884" },
  { name: "CRC16_IBM_POLY_0x8005_LE16", hex: "0580" },
  { name: "CRC16_CCITT_TABLE_PREFIX_LE", hex: "00002110422063308440a550c660e770" },
  { name: "CRC16_MODBUS_TABLE_PREFIX_LE", hex: "0000c1c081c1400101c0c00080814140" },
];

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) {
      continue;
    }
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      args[key] = next;
      i += 1;
    } else {
      args[key] = true;
    }
  }
  return args;
}

function walkFiles(root, basename, results = []) {
  if (!fs.existsSync(root)) {
    return results;
  }
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      walkFiles(fullPath, basename, results);
    } else if (entry.isFile() && entry.name === basename) {
      results.push(fullPath);
    }
  }
  return results;
}

function resolveSiteUnitPath(args) {
  if (args.siteunit) {
    return path.resolve(args.siteunit);
  }
  const firmwareRoot = path.resolve(args["firmware-root"] || DEFAULT_FIRMWARE_ROOT);
  const direct = path.join(firmwareRoot, "SiteUnit");
  if (fs.existsSync(direct)) {
    return direct;
  }
  const matches = walkFiles(firmwareRoot, "SiteUnit");
  if (matches.length === 1) {
    return matches[0];
  }
  if (matches.length > 1) {
    return matches.sort((a, b) => a.length - b.length || a.localeCompare(b))[0];
  }
  throw new Error(`SiteUnit not found under firmware root: ${firmwareRoot}`);
}

function hex(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return null;
  }
  return `0x${Number(value).toString(16)}`;
}

function readCString(buffer, offset) {
  let end = offset;
  while (end < buffer.length && buffer[end] !== 0) {
    end += 1;
  }
  return buffer.toString("ascii", offset, end);
}

function isAsciiPrintable(byte) {
  return byte >= 0x20 && byte <= 0x7e;
}

function extractAsciiStrings(buffer, minLength = 4) {
  const strings = [];
  let start = -1;
  for (let i = 0; i <= buffer.length; i += 1) {
    const byte = i < buffer.length ? buffer[i] : 0;
    if (i < buffer.length && isAsciiPrintable(byte)) {
      if (start === -1) {
        start = i;
      }
      continue;
    }
    if (start !== -1) {
      const length = i - start;
      if (length >= minLength) {
        strings.push({
          fileOffset: start,
          fileOffsetHex: hex(start),
          length,
          text: buffer.toString("ascii", start, i),
        });
      }
      start = -1;
    }
  }
  return strings;
}

function parseElfSections(buffer) {
  if (buffer.length < 52 || buffer[0] !== 0x7f || buffer.toString("ascii", 1, 4) !== "ELF") {
    throw new Error("SiteUnit is not an ELF file");
  }
  if (buffer[4] !== 1 || buffer[5] !== 1) {
    throw new Error("expected ARM 32-bit little-endian ELF");
  }

  const eMachine = buffer.readUInt16LE(18);
  const eShoff = buffer.readUInt32LE(32);
  const eShentsize = buffer.readUInt16LE(46);
  const eShnum = buffer.readUInt16LE(48);
  const eShstrndx = buffer.readUInt16LE(50);
  if (!eShoff || !eShentsize || !eShnum || eShstrndx >= eShnum) {
    throw new Error("invalid or stripped section header table");
  }

  const raw = [];
  for (let i = 0; i < eShnum; i += 1) {
    const off = eShoff + i * eShentsize;
    raw.push({
      index: i,
      nameOffset: buffer.readUInt32LE(off),
      type: buffer.readUInt32LE(off + 4),
      flags: buffer.readUInt32LE(off + 8),
      addr: buffer.readUInt32LE(off + 12),
      offset: buffer.readUInt32LE(off + 16),
      size: buffer.readUInt32LE(off + 20),
      link: buffer.readUInt32LE(off + 24),
      info: buffer.readUInt32LE(off + 28),
      addralign: buffer.readUInt32LE(off + 32),
      entsize: buffer.readUInt32LE(off + 36),
    });
  }

  const shstr = raw[eShstrndx];
  const sections = raw.map((section) => ({
    ...section,
    name: readCString(buffer, shstr.offset + section.nameOffset),
  }));

  return {
    elfClass: "ELF32",
    endian: "LSB",
    eMachine,
    sections,
  };
}

function fileOffsetToVirtualAddress(sections, fileOffset) {
  const section = sections.find(
    (item) => item.size > 0 && fileOffset >= item.offset && fileOffset < item.offset + item.size,
  );
  if (!section || !section.addr) {
    return { virtualAddress: null, section: section ? section.name : null };
  }
  return {
    virtualAddress: section.addr + (fileOffset - section.offset),
    section: section.name,
  };
}

function virtualAddressToFileOffset(sections, virtualAddress) {
  const section = sections.find(
    (item) => item.size > 0 && item.addr && virtualAddress >= item.addr && virtualAddress < item.addr + item.size,
  );
  if (!section) {
    return { fileOffset: null, section: null };
  }
  return {
    fileOffset: section.offset + (virtualAddress - section.addr),
    section: section.name,
  };
}

function sectionForFileOffset(sections, fileOffset) {
  const found = sections.find((item) => item.size > 0 && fileOffset >= item.offset && fileOffset < item.offset + item.size);
  return found ? found.name : null;
}

function sectionForVirtualAddress(sections, virtualAddress) {
  const found = sections.find(
    (item) => item.size > 0 && item.addr && virtualAddress >= item.addr && virtualAddress < item.addr + item.size,
  );
  return found ? found.name : null;
}

function searchBuffer(buffer, pattern, start = 0, end = buffer.length, limit = Infinity) {
  const hits = [];
  let pos = start;
  while (pos <= end - pattern.length && hits.length < limit) {
    const hit = buffer.indexOf(pattern, pos);
    if (hit === -1 || hit >= end) {
      break;
    }
    hits.push(hit);
    pos = hit + 1;
  }
  return hits;
}

function packUInt32LE(value) {
  const bytes = Buffer.alloc(4);
  bytes.writeUInt32LE(value >>> 0, 0);
  return bytes;
}

function makeStringLookup(strings, sections) {
  const byFileOffset = new Map();
  const byVirtualAddress = new Map();
  const rangesByVirtualAddress = strings.map((item) => {
    const { virtualAddress, section } = fileOffsetToVirtualAddress(sections, item.fileOffset);
    const enriched = {
      ...item,
      virtualAddress,
      virtualAddressHex: hex(virtualAddress),
      section,
    };
    byFileOffset.set(item.fileOffset, enriched);
    if (virtualAddress !== null) {
      byVirtualAddress.set(virtualAddress >>> 0, enriched);
    }
    return enriched;
  });
  return { byFileOffset, byVirtualAddress, rangesByVirtualAddress };
}

function resolveStringTargets(strings, target) {
  const exact = strings.filter((item) => item.text === target);
  if (exact.length) {
    return exact;
  }
  const lower = target.toLowerCase();
  return strings.filter((item) => item.text.toLowerCase().includes(lower));
}

function hexdump(buffer, start, length) {
  const safeStart = Math.max(0, start);
  const safeEnd = Math.min(buffer.length, safeStart + length);
  const lines = [];
  for (let off = safeStart; off < safeEnd; off += 16) {
    const chunk = buffer.subarray(off, Math.min(off + 16, safeEnd));
    const hexBytes = [...chunk].map((byte) => byte.toString(16).padStart(2, "0")).join(" ");
    const ascii = [...chunk].map((byte) => (isAsciiPrintable(byte) ? String.fromCharCode(byte) : ".")).join("");
    lines.push(`${hex(off).padStart(10, " ")}  ${hexBytes.padEnd(47, " ")}  ${ascii}`);
  }
  return lines.join("\n");
}

function findLiteralStringAddresses({ buffer, sections, stringsByVirtualAddress, start, length }) {
  const literals = [];
  const begin = Math.max(0, start);
  const end = Math.min(buffer.length, start + length);
  for (let off = begin; off <= end - 4; off += 1) {
    const value = buffer.readUInt32LE(off);
    const exact = stringsByVirtualAddress.get(value >>> 0);
    if (exact) {
      const { virtualAddress, section } = fileOffsetToVirtualAddress(sections, off);
      literals.push({
        literalFileOffset: off,
        literalFileOffsetHex: hex(off),
        literalVirtualAddress: virtualAddress,
        literalVirtualAddressHex: hex(virtualAddress),
        literalSection: section,
        targetStringFileOffset: exact.fileOffset,
        targetStringFileOffsetHex: exact.fileOffsetHex,
        targetStringVirtualAddress: exact.virtualAddress,
        targetStringVirtualAddressHex: exact.virtualAddressHex,
        targetStringSection: exact.section,
        text: exact.text,
      });
    }
  }
  return literals;
}

function executableSections(sections) {
  return sections.filter((section) => section.size > 0 && section.offset > 0 && (section.flags & 0x4 || section.name === ".text"));
}

function analyzeXrefs({ buffer, sections, strings }) {
  const { byVirtualAddress, rangesByVirtualAddress } = makeStringLookup(strings, sections);
  const textSections = executableSections(sections);
  const results = [];

  for (const target of TARGET_STRINGS) {
    const matches = resolveStringTargets(rangesByVirtualAddress, target);
    const stringResults = [];

    for (const match of matches) {
      if (match.virtualAddress === null) {
        stringResults.push({ ...match, xrefs: [] });
        continue;
      }

      const pattern = packUInt32LE(match.virtualAddress);
      const xrefs = [];
      for (const textSection of textSections) {
        const hits = searchBuffer(buffer, pattern, textSection.offset, textSection.offset + textSection.size);
        for (const hit of hits) {
          const { virtualAddress, section } = fileOffsetToVirtualAddress(sections, hit);
          const dumpStart = Math.max(0, hit - 128);
          xrefs.push({
            xrefFileOffset: hit,
            xrefFileOffsetHex: hex(hit),
            xrefVirtualAddress: virtualAddress,
            xrefVirtualAddressHex: hex(virtualAddress),
            xrefSection: section,
            contextHexDump: hexdump(buffer, dumpStart, 256),
            nearbyStringAddressLiterals: findLiteralStringAddresses({
              buffer,
              sections,
              stringsByVirtualAddress: byVirtualAddress,
              start: dumpStart,
              length: 256,
            }),
          });
        }
      }
      stringResults.push({
        text: match.text,
        stringFileOffset: match.fileOffset,
        stringFileOffsetHex: match.fileOffsetHex,
        stringVirtualAddress: match.virtualAddress,
        stringVirtualAddressHex: match.virtualAddressHex,
        stringSection: match.section,
        xrefs,
      });
    }

    results.push({ target, matchCount: matches.length, matches: stringResults });
  }

  return results;
}

function collectStringRefsForTerms(xrefs, terms) {
  const termSet = terms.map((term) => term.toLowerCase());
  const refs = [];
  for (const group of xrefs) {
    for (const match of group.matches) {
      const lower = match.text.toLowerCase();
      if (!termSet.some((term) => lower.includes(term))) {
        continue;
      }
      refs.push(match);
    }
  }
  return refs;
}

function regionFromRefs(refs, before = 512, after = 1024) {
  const offsets = refs.flatMap((ref) => ref.xrefs.map((xref) => xref.xrefFileOffset));
  if (!offsets.length) {
    return null;
  }
  const min = Math.max(0, Math.min(...offsets) - before);
  const max = Math.max(...offsets) + after;
  return {
    fileOffsetStart: min,
    fileOffsetStartHex: hex(min),
    fileOffsetEnd: max,
    fileOffsetEndHex: hex(max),
  };
}

function littleEndianIntegers(buffer, start, end) {
  const ints = [];
  for (let off = Math.max(0, start); off <= Math.min(buffer.length, end) - 4; off += 4) {
    const value = buffer.readUInt32LE(off);
    if (
      value === 0 ||
      value === 1 ||
      value === 2 ||
      value === 3 ||
      value === 4 ||
      value === 24 ||
      value === 30 ||
      value === 209 ||
      value === 245 ||
      value === 6001 ||
      value === 6002 ||
      value === 6003 ||
      value === 7000 ||
      value === 9000 ||
      value === 0x6d7e ||
      value === 0xffd2001f ||
      value === 0xff460011 ||
      value === 0xffd28011
    ) {
      ints.push({ fileOffset: off, fileOffsetHex: hex(off), value, valueHex: hex(value) });
    }
  }
  return ints;
}

function analyzeCandidateRegion({ name, terms, xrefs, buffer, sections, stringsByVirtualAddress }) {
  const refs = collectStringRefsForTerms(xrefs, terms);
  const region = regionFromRefs(refs);
  const referencedStrings = [];
  for (const ref of refs) {
    referencedStrings.push({
      text: ref.text,
      stringFileOffsetHex: ref.stringFileOffsetHex,
      stringVirtualAddressHex: ref.stringVirtualAddressHex,
      xrefFileOffsets: ref.xrefs.map((xref) => xref.xrefFileOffsetHex),
      xrefVirtualAddresses: ref.xrefs.map((xref) => xref.xrefVirtualAddressHex),
    });
  }
  if (!region) {
    return { name, found: false, referencedStrings };
  }

  const literals = findLiteralStringAddresses({
    buffer,
    sections,
    stringsByVirtualAddress,
    start: region.fileOffsetStart,
    length: region.fileOffsetEnd - region.fileOffsetStart,
  });
  const literalTexts = [...new Set(literals.map((item) => item.text))];
  const integerConstants = littleEndianIntegers(buffer, region.fileOffsetStart, region.fileOffsetEnd);
  const lowerTexts = literalTexts.map((text) => text.toLowerCase());

  return {
    name,
    found: true,
    ...region,
    virtualAddressStartHex: hex(fileOffsetToVirtualAddress(sections, region.fileOffsetStart).virtualAddress),
    virtualAddressEndHex: hex(fileOffsetToVirtualAddress(sections, region.fileOffsetEnd).virtualAddress),
    referencedStrings,
    nearbyStringLiterals: literals,
    nearbyStringList: literalTexts,
    integerConstants,
    hasRecvSendSelectSocketTrace: lowerTexts.some((text) =>
      ["recv", "recvfrom", "sendto", "select", "socket"].some((needle) => text.includes(needle)),
    ),
    hasReturnCodeBranchTrace: lowerTexts.some((text) =>
      ["success", "fail", "unregister", "result", "return code"].some((needle) => text.includes(needle)),
    ),
    contextHexDump: hexdump(buffer, region.fileOffsetStart, Math.min(512, region.fileOffsetEnd - region.fileOffsetStart)),
  };
}

function searchPatterns({ buffer, sections, stringsByVirtualAddress }) {
  return BYTE_PATTERNS.map((pattern) => {
    const bytes = Buffer.from(pattern.hex, "hex");
    const hits = searchBuffer(buffer, bytes, 0, buffer.length, pattern.name === "7e" ? 200 : 1000).map((fileOffset) => {
      const { virtualAddress } = fileOffsetToVirtualAddress(sections, fileOffset);
      const section = sectionForFileOffset(sections, fileOffset);
      const dumpStart = Math.max(0, fileOffset - 128);
      return {
        fileOffset,
        fileOffsetHex: hex(fileOffset),
        virtualAddress,
        virtualAddressHex: hex(virtualAddress),
        section,
        contextHexDump: hexdump(buffer, dumpStart, 256),
        nearbyStringAddressLiterals: findLiteralStringAddresses({
          buffer,
          sections,
          stringsByVirtualAddress,
          start: dumpStart,
          length: 256,
        }),
      };
    });
    return { pattern: pattern.name, hex: pattern.hex, hitCount: hits.length, hits };
  });
}

function commandTableAnalysis(strings, sections) {
  const matches = COMMAND_TABLE_STRINGS.map((term) => ({
    term,
    matches: resolveStringTargets(strings, term).map((item) => ({
      text: item.text,
      fileOffset: item.fileOffset,
      fileOffsetHex: item.fileOffsetHex,
      virtualAddress: fileOffsetToVirtualAddress(sections, item.fileOffset).virtualAddress,
      virtualAddressHex: hex(fileOffsetToVirtualAddress(sections, item.fileOffset).virtualAddress),
      section: fileOffsetToVirtualAddress(sections, item.fileOffset).section,
    })),
  }));
  const offsets = matches.flatMap((group) => group.matches.map((item) => item.fileOffset));
  const span =
    offsets.length > 0
      ? {
          fileOffsetStart: Math.min(...offsets),
          fileOffsetStartHex: hex(Math.min(...offsets)),
          fileOffsetEnd: Math.max(...offsets),
          fileOffsetEndHex: hex(Math.max(...offsets)),
          byteSpan: Math.max(...offsets) - Math.min(...offsets),
        }
      : null;
  const nearby = span
    ? strings.filter((item) => item.fileOffset >= span.fileOffsetStart - 512 && item.fileOffset <= span.fileOffsetEnd + 512)
    : [];

  const soapHints = nearby.filter((item) => /soap|xml|http|service|cmd|request|response/i.test(item.text));
  const binaryHints = nearby.filter((item) => /udp|dsc|rds|soi|checksum|parse|frame/i.test(item.text));
  return {
    matches,
    span,
    nearbyStrings: nearby,
    soapOrIecProtocolHints: soapHints,
    binaryDscHints: binaryHints,
    inference:
      soapHints.length >= binaryHints.length
        ? "LOGIN_ACK is currently closer to a textual command/protocol string table than to the observed UDP DSC binary frame templates."
        : "LOGIN_ACK has nearby binary/DSC hints, but xrefs must still be reviewed before treating it as the UDP DSC ACK.",
  };
}

function checksumAnalysis({ buffer, sections, strings, xrefs }) {
  const constantHits = CRC_CONSTANTS.map((constant) => {
    const pattern = Buffer.from(constant.hex, "hex");
    return {
      name: constant.name,
      hex: constant.hex,
      hits: searchBuffer(buffer, pattern, 0, buffer.length, 100).map((fileOffset) => ({
        fileOffset,
        fileOffsetHex: hex(fileOffset),
        section: sectionForFileOffset(sections, fileOffset),
        virtualAddressHex: hex(fileOffsetToVirtualAddress(sections, fileOffset).virtualAddress),
      })),
    };
  });

  const checksumStrings = strings.filter((item) => /check|checksum|crc/i.test(item.text)).map((item) => ({
    text: item.text,
    fileOffsetHex: item.fileOffsetHex,
    virtualAddressHex: hex(fileOffsetToVirtualAddress(sections, item.fileOffset).virtualAddress),
    section: fileOffsetToVirtualAddress(sections, item.fileOffset).section,
  }));

  const failChecksumRefs = collectStringRefsForTerms(xrefs, ["fail checksum"]);
  return {
    crcConstantHits: constantHits,
    checksumRelatedStrings: checksumStrings,
    failChecksumXrefs: failChecksumRefs.map((ref) => ({
      text: ref.text,
      stringFileOffsetHex: ref.stringFileOffsetHex,
      stringVirtualAddressHex: ref.stringVirtualAddressHex,
      xrefFileOffsets: ref.xrefs.map((xref) => xref.xrefFileOffsetHex),
      xrefVirtualAddresses: ref.xrefs.map((xref) => xref.xrefVirtualAddressHex),
    })),
    crc16TableFound: constantHits.some((item) => item.name.includes("TABLE_PREFIX") && item.hits.length > 0),
    polyConstantFound: constantHits.some((item) => !item.name.includes("TABLE_PREFIX") && item.hits.length > 0),
    inference:
      "No ARM disassembly is performed by this script; checksum classification is based on static constants, tables, strings, and fail-checksum xref context.",
  };
}

function markdownTable(rows, columns) {
  const header = `| ${columns.map((column) => column.title).join(" | ")} |`;
  const divider = `| ${columns.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => {
    const values = columns.map((column) => String(column.value(row)).replace(/\|/g, "\\|"));
    return `| ${values.join(" | ")} |`;
  });
  return [header, divider, ...body].join("\n");
}

function writeXrefReport({ outDir, result }) {
  const jsonPath = path.join(outDir, `siteunit-string-xrefs-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const rows = result.xrefs.flatMap((group) =>
    group.matches.map((match) => ({
      target: group.target,
      text: match.text,
      stringFileOffsetHex: match.stringFileOffsetHex,
      stringVirtualAddressHex: match.stringVirtualAddressHex,
      xrefCount: match.xrefs.length,
      xrefVirtualAddresses: match.xrefs.map((xref) => xref.xrefVirtualAddressHex).join(", "),
    })),
  );

  const md = [
    "# SiteUnit String Xrefs",
    "",
    `Generated: ${result.generatedAt}`,
    `SiteUnit: ${result.fileInfo.path}`,
    "",
    "## ELF Sections",
    "",
    markdownTable(result.sections, [
      { title: "Name", value: (row) => row.name },
      { title: "File Offset", value: (row) => row.offsetHex },
      { title: "VA", value: (row) => row.addrHex },
      { title: "Size", value: (row) => row.sizeHex },
      { title: "Flags", value: (row) => row.flagsHex },
    ]),
    "",
    "## Xref Summary",
    "",
    rows.length
      ? markdownTable(rows, [
          { title: "Target", value: (row) => row.target },
          { title: "String", value: (row) => `\`${row.text}\`` },
          { title: "String Offset", value: (row) => row.stringFileOffsetHex },
          { title: "String VA", value: (row) => row.stringVirtualAddressHex },
          { title: "Xrefs", value: (row) => row.xrefCount },
          { title: "Xref VAs", value: (row) => row.xrefVirtualAddresses },
        ])
      : "No xrefs found.",
    "",
    "## Detailed Xrefs",
    "",
    ...result.xrefs.flatMap((group) =>
      group.matches.flatMap((match) => [
        `### ${group.target}: ${match.text}`,
        "",
        `String file offset: ${match.stringFileOffsetHex}`,
        `String virtual address: ${match.stringVirtualAddressHex}`,
        `Xref count: ${match.xrefs.length}`,
        "",
        ...match.xrefs.flatMap((xref) => [
          `#### Xref ${xref.xrefFileOffsetHex} / ${xref.xrefVirtualAddressHex}`,
          "",
          "Nearby string address literals:",
          "",
          xref.nearbyStringAddressLiterals.length
            ? markdownTable(xref.nearbyStringAddressLiterals, [
                { title: "Literal Off", value: (row) => row.literalFileOffsetHex },
                { title: "Literal VA", value: (row) => row.literalVirtualAddressHex },
                { title: "String VA", value: (row) => row.targetStringVirtualAddressHex },
                { title: "String", value: (row) => `\`${row.text}\`` },
              ])
            : "None.",
          "",
          "```text",
          xref.contextHexDump,
          "```",
          "",
        ]),
      ]),
    ),
    "",
  ].join("\n");

  const mdPath = path.join(outDir, `siteunit-string-xrefs-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function summarizeXrefGroup(xrefs, target) {
  const group = xrefs.find((item) => item.target === target);
  if (!group) {
    return [];
  }
  return group.matches.map((match) => ({
    text: match.text,
    stringFileOffsetHex: match.stringFileOffsetHex,
    stringVirtualAddressHex: match.stringVirtualAddressHex,
    xrefFileOffsets: match.xrefs.map((xref) => xref.xrefFileOffsetHex),
    xrefVirtualAddresses: match.xrefs.map((xref) => xref.xrefVirtualAddressHex),
  }));
}

function writeStaticReport({ outDir, result }) {
  const jsonPath = path.join(outDir, `ack-static-reverse-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const xrefRows = TARGET_STRINGS.flatMap((target) =>
    summarizeXrefGroup(result.keyStringXrefs, target).map((item) => ({ target, ...item })),
  );
  const patternRows = result.patternAnalysis.map((item) => ({
    pattern: item.pattern,
    hitCount: item.hitCount,
    firstHits: item.hits.slice(0, 10).map((hit) => `${hit.fileOffsetHex}/${hit.section}`).join(", "),
  }));
  const crcRows = result.checksumAnalysis.crcConstantHits.map((item) => ({
    name: item.name,
    hitCount: item.hits.length,
    firstHits: item.hits.slice(0, 10).map((hit) => `${hit.fileOffsetHex}/${hit.section}`).join(", "),
  }));

  const md = [
    "# ACK Static Reverse Report",
    "",
    `Generated: ${result.generatedAt}`,
    "",
    "## 1. Overview",
    "",
    result.overview,
    "",
    "## 2. SiteUnit File Info",
    "",
    `Path: ${result.fileInfo.path}`,
    `Size: ${result.fileInfo.size}`,
    `SHA256: ${result.fileInfo.sha256}`,
    `ELF: ${result.elf.elfClass} ${result.elf.endian}, e_machine=${result.elf.eMachine}`,
    "",
    "## 3. Key String Index",
    "",
    markdownTable(result.keyStringIndex, [
      { title: "Term", value: (row) => row.term },
      { title: "Count", value: (row) => row.matches.length },
      { title: "Matches", value: (row) => row.matches.map((match) => `${match.fileOffsetHex}/${match.virtualAddressHex} \`${match.text}\``).join("<br>") },
    ]),
    "",
    "## 4. Key String Xrefs",
    "",
    xrefRows.length
      ? markdownTable(xrefRows, [
          { title: "Target", value: (row) => row.target },
          { title: "String", value: (row) => `\`${row.text}\`` },
          { title: "String Off", value: (row) => row.stringFileOffsetHex },
          { title: "String VA", value: (row) => row.stringVirtualAddressHex },
          { title: "Xref Offsets", value: (row) => row.xrefFileOffsets.join(", ") || "none" },
          { title: "Xref VAs", value: (row) => row.xrefVirtualAddresses.join(", ") || "none" },
        ])
      : "No xrefs found.",
    "",
    "## 5. LoginToDSC / Register OK Region",
    "",
    `Found: ${result.loginRegion.found}`,
    result.loginRegion.found
      ? [
          `File offset range: ${result.loginRegion.fileOffsetStartHex} - ${result.loginRegion.fileOffsetEndHex}`,
          `Virtual address range: ${result.loginRegion.virtualAddressStartHex} - ${result.loginRegion.virtualAddressEndHex}`,
          `recv/send/select/socket trace: ${result.loginRegion.hasRecvSendSelectSocketTrace}`,
          `return-code branch trace: ${result.loginRegion.hasReturnCodeBranchTrace}`,
          `Nearby strings: ${result.loginRegion.nearbyStringList.map((item) => `\`${item}\``).join(", ")}`,
          `Integer constants: ${result.loginRegion.integerConstants.map((item) => `${item.fileOffsetHex}=${item.valueHex}`).join(", ") || "none"}`,
        ].join("\n")
      : "No candidate region from xrefs.",
    "",
    "## 6. ParseData Region",
    "",
    `Found: ${result.parseRegion.found}`,
    result.parseRegion.found
      ? [
          `File offset range: ${result.parseRegion.fileOffsetStartHex} - ${result.parseRegion.fileOffsetEndHex}`,
          `Virtual address range: ${result.parseRegion.virtualAddressStartHex} - ${result.parseRegion.virtualAddressEndHex}`,
          `SOI judgement: ${result.parseRegionInference.soiJudgement}`,
          `length judgement: ${result.parseRegionInference.lengthJudgement}`,
          `checksum judgement: ${result.parseRegionInference.checksumJudgement}`,
          `Response field-boundary inference: ${result.parseRegionInference.fieldBoundaryInference}`,
        ].join("\n")
      : "No candidate region from xrefs.",
    "",
    "## 7. LOGIN_ACK Command Table",
    "",
    `Inference: ${result.commandTableAnalysis.inference}`,
    result.commandTableAnalysis.span
      ? `String span: ${result.commandTableAnalysis.span.fileOffsetStartHex} - ${result.commandTableAnalysis.span.fileOffsetEndHex} (${result.commandTableAnalysis.span.byteSpan} bytes)`
      : "No command-table span found.",
    "",
    "## 8. 6d7e / typeA Pattern Analysis",
    "",
    markdownTable(patternRows, [
      { title: "Pattern", value: (row) => row.pattern },
      { title: "Hit Count", value: (row) => row.hitCount },
      { title: "First Hits", value: (row) => row.firstHits || "none" },
    ]),
    "",
    "## 9. Checksum Clues",
    "",
    markdownTable(crcRows, [
      { title: "Constant", value: (row) => row.name },
      { title: "Hit Count", value: (row) => row.hitCount },
      { title: "First Hits", value: (row) => row.firstHits || "none" },
    ]),
    "",
    `CRC16 table found: ${result.checksumAnalysis.crc16TableFound}`,
    `CRC polynomial constant found: ${result.checksumAnalysis.polyConstantFound}`,
    `Checksum inference: ${result.checksumInference}`,
    "",
    "## 10. Can ACK Format Be Inferred",
    "",
    result.ackFormatInference,
    "",
    "## 11. Next Steps",
    "",
    result.nextSteps.map((item) => `- ${item}`).join("\n"),
    "",
  ].join("\n");

  const mdPath = path.join(outDir, `ack-static-reverse-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const siteUnitPath = resolveSiteUnitPath(args);
  if (!fs.existsSync(siteUnitPath)) {
    throw new Error(`SiteUnit path does not exist: ${siteUnitPath}`);
  }
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  fs.mkdirSync(outDir, { recursive: true });

  const buffer = fs.readFileSync(siteUnitPath);
  const strings = extractAsciiStrings(buffer, 4);
  const elf = parseElfSections(buffer);
  const { byVirtualAddress, rangesByVirtualAddress } = makeStringLookup(strings, elf.sections);
  const xrefs = analyzeXrefs({ buffer, sections: elf.sections, strings });
  const patternAnalysis = searchPatterns({ buffer, sections: elf.sections, stringsByVirtualAddress: byVirtualAddress });
  const loginRegion = analyzeCandidateRegion({
    name: "LoginToDSC / Register OK",
    terms: LOGIN_REGION_STRINGS,
    xrefs,
    buffer,
    sections: elf.sections,
    stringsByVirtualAddress: byVirtualAddress,
  });
  const parseRegion = analyzeCandidateRegion({
    name: "ParseData",
    terms: PARSE_REGION_STRINGS,
    xrefs,
    buffer,
    sections: elf.sections,
    stringsByVirtualAddress: byVirtualAddress,
  });
  const commandAnalysis = commandTableAnalysis(rangesByVirtualAddress, elf.sections);
  const checksum = checksumAnalysis({ buffer, sections: elf.sections, strings: rangesByVirtualAddress, xrefs });

  const sectionsForReport = elf.sections.map((section) => ({
    name: section.name,
    offset: section.offset,
    offsetHex: hex(section.offset),
    addr: section.addr,
    addrHex: hex(section.addr),
    size: section.size,
    sizeHex: hex(section.size),
    flags: section.flags,
    flagsHex: hex(section.flags),
  }));
  const fileInfo = {
    path: siteUnitPath,
    size: buffer.length,
    sha256: crypto.createHash("sha256").update(buffer).digest("hex"),
  };
  const keyStringIndex = [...new Set([...TARGET_STRINGS, ...LOGIN_REGION_STRINGS, ...PARSE_REGION_STRINGS, ...COMMAND_TABLE_STRINGS])].map(
    (term) => ({
      term,
      matches: resolveStringTargets(rangesByVirtualAddress, term).map((item) => ({
        text: item.text,
        fileOffset: item.fileOffset,
        fileOffsetHex: item.fileOffsetHex,
        virtualAddress: item.virtualAddress,
        virtualAddressHex: item.virtualAddressHex,
        section: item.section,
      })),
    }),
  );

  const xrefReport = {
    generatedAt: new Date().toISOString(),
    fileInfo,
    elf: {
      elfClass: elf.elfClass,
      endian: elf.endian,
      eMachine: elf.eMachine,
    },
    sections: sectionsForReport,
    xrefs,
  };
  const xrefPaths = writeXrefReport({ outDir, result: xrefReport });

  const parseStrings = parseRegion.found ? parseRegion.nearbyStringList.join("\n") : "";
  const staticReport = {
    generatedAt: new Date().toISOString(),
    overview:
      "Offline static reverse pass for SiteUnit. It builds string xrefs by resolving ELF section file offsets to virtual addresses, then finding those VA literals in executable sections. No UDP packets were sent and no runtime gateway logic was modified.",
    fileInfo,
    elf: {
      elfClass: elf.elfClass,
      endian: elf.endian,
      eMachine: elf.eMachine,
    },
    sections: sectionsForReport,
    keyStringIndex,
    keyStringXrefs: xrefs,
    loginRegion,
    parseRegion,
    parseRegionInference: {
      soiJudgement: /fail SOI/i.test(parseStrings)
        ? "ParseData candidate references fail SOI; SOI validation exists, but exact byte requires disassembly of the candidate region."
        : "No direct SOI failure string in candidate region.",
      lengthJudgement: /fail length/i.test(parseStrings)
        ? "ParseData candidate references fail length; length validation exists, but field offsets are not proven from literal xrefs alone."
        : "No direct length failure string in candidate region.",
      checksumJudgement: /fail checksum/i.test(parseStrings)
        ? "ParseData candidate references fail checksum; checksum validation exists, but algorithm is not proven from constants alone."
        : "No direct checksum failure string in candidate region.",
      fieldBoundaryInference:
        "Observed UDP packets begin with 6d7e, but this static literal pass does not prove the firmware's response field boundaries. ARM disassembly/data-flow is needed.",
    },
    commandTableAnalysis: commandAnalysis,
    patternAnalysis,
    checksumAnalysis: checksum,
    checksumInference:
      checksum.crc16TableFound || checksum.polyConstantFound
        ? "CRC-related constants/tables were found somewhere in SiteUnit; correlation to ParseData must be proven by disassembly."
        : "No known CRC16 table prefix or common CRC polynomial constant was found by byte-pattern search. A simple additive checksum remains possible but is not proven.",
    ackFormatInference:
      "The true DSC LOGIN/Register ACK frame format cannot be safely inferred from this pass alone. LOGIN_ACK should not be treated as the UDP DSC binary ACK unless a handler xref/data-flow path ties it to the DSC socket parser or response builder.",
    nextSteps: [
      "Disassemble the candidate xref regions with ARM/Thumb awareness and recover function boundaries.",
      "Follow calls around LoginToDSC, LogToDS return, and Register OK to identify send/recv buffers and return-code parsing.",
      "Follow ParseData branches for fail SOI, fail length, and fail checksum to prove SOI byte, length fields, and checksum algorithm.",
      "Resolve PLT/import calls for recvfrom/sendto/select/socket and map them to the candidate functions.",
      "Only after the binary response format is proven offline should a one-shot ACK candidate be considered.",
    ],
  };
  const staticPaths = writeStaticReport({ outDir, result: staticReport });

  console.log(
    JSON.stringify(
      {
        siteUnitPath,
        stringCount: strings.length,
        xrefReport: xrefPaths,
        staticReport: staticPaths,
        summary: {
          loginAck: summarizeXrefGroup(xrefs, "LOGIN_ACK"),
          registerOk: summarizeXrefGroup(xrefs, "Register OK"),
          loginTimeout: summarizeXrefGroup(xrefs, "Login to Dsc timeout"),
          parseData: summarizeXrefGroup(xrefs, "ParseData"),
          failSoi: summarizeXrefGroup(xrefs, "fail SOI"),
          failChecksum: summarizeXrefGroup(xrefs, "fail checksum"),
          failLength: summarizeXrefGroup(xrefs, "fail length"),
        },
      },
      null,
      2,
    ),
  );
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
