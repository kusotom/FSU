#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const DATE_STEM = "2026-04-28";
const DEFAULT_FIRMWARE_ROOT = path.join(process.env.USERPROFILE || process.cwd(), "Desktop", "FSU");
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

const REGIONS = [
  { name: "ParseData", vaStart: 0x76000, vaEnd: 0x76ac4, fileStart: 0x6e000, fileEnd: 0x6eac4 },
  { name: "ParseData original candidate / next function", vaStart: 0x76878, vaEnd: 0x76e84, fileStart: 0x6e878, fileEnd: 0x6ee84 },
  { name: "Login/Register", vaStart: 0x74d00, vaEnd: 0x75a50 },
  { name: "Login timeout", vaStart: 0x77200, vaEnd: 0x77950 },
  { name: "LOGIN_ACK text command table", vaStart: 0x9dc00, vaEnd: 0x9e300 },
  { name: "Checksum candidate 0x7f98c", vaStart: 0x7f98c, vaEnd: 0x7faa0 },
];

const CONSTANTS = new Map([
  [0x00007e6d, "SOI literal 0x00007e6d (bytes 6d 7e)"],
  [0x00006d7e, "SOI literal 0x00006d7e"],
  [0x0000d2ff, "type suffix 0xd2ff"],
  [0x000046ff, "type suffix 0x46ff"],
  [0x00001f00, "type prefix 0x1f00"],
  [0x00001100, "type prefix 0x1100"],
  [0x00001180, "type prefix 0x1180"],
  [0, "zero"],
  [24, "length 24"],
  [30, "length 30"],
  [209, "length 209"],
  [245, "length 245"],
  [185, "payload length 185"],
  [221, "payload length 221"],
]);

const PY_CAPSTONE = String.raw`
import base64, json, sys
from capstone import *

payload = json.load(sys.stdin)
blob = base64.b64decode(payload["blobBase64"])
mode = CS_MODE_THUMB if payload.get("thumb") else CS_MODE_ARM
md = Cs(CS_ARCH_ARM, mode)
md.detail = False
out = []
for region in payload["regions"]:
    start = region["fileStart"]
    end = region["fileEnd"]
    va = region["vaStart"]
    code = blob[start:end]
    insns = []
    for insn in md.disasm(code, va):
        insns.append({
            "address": insn.address,
            "size": insn.size,
            "bytes": insn.bytes.hex(),
            "mnemonic": insn.mnemonic,
            "opStr": insn.op_str,
        })
    out.append({"name": region["name"], "mode": "thumb" if payload.get("thumb") else "arm", "instructions": insns})
print(json.dumps(out))
`;

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) continue;
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
  if (!fs.existsSync(root)) return results;
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) walkFiles(fullPath, basename, results);
    else if (entry.isFile() && entry.name === basename) results.push(fullPath);
  }
  return results;
}

function resolveSiteUnitPath(args) {
  if (args.siteunit) return path.resolve(args.siteunit);
  const firmwareRoot = path.resolve(args["firmware-root"] || DEFAULT_FIRMWARE_ROOT);
  const direct = path.join(firmwareRoot, "SiteUnit");
  if (fs.existsSync(direct)) return direct;
  const matches = walkFiles(firmwareRoot, "SiteUnit");
  if (matches.length === 1) return matches[0];
  if (matches.length > 1) return matches.sort((a, b) => a.length - b.length || a.localeCompare(b))[0];
  throw new Error(`SiteUnit not found under firmware root: ${firmwareRoot}`);
}

function hex(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return `0x${Number(value).toString(16)}`;
}

function readCString(buffer, offset) {
  let end = offset;
  while (end < buffer.length && buffer[end] !== 0) end += 1;
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
      if (start === -1) start = i;
      continue;
    }
    if (start !== -1) {
      const length = i - start;
      if (length >= minLength) {
        strings.push({ fileOffset: start, fileOffsetHex: hex(start), length, text: buffer.toString("ascii", start, i) });
      }
      start = -1;
    }
  }
  return strings;
}

function parseElf(buffer) {
  if (buffer.length < 52 || buffer[0] !== 0x7f || buffer.toString("ascii", 1, 4) !== "ELF") {
    throw new Error("not an ELF file");
  }
  if (buffer[4] !== 1 || buffer[5] !== 1) throw new Error("expected ELF32 LSB");
  const header = {
    elfClass: "ELF32",
    endian: "LSB",
    machine: buffer.readUInt16LE(18),
    architecture: buffer.readUInt16LE(18) === 40 ? "ARM" : `e_machine_${buffer.readUInt16LE(18)}`,
    entryPoint: buffer.readUInt32LE(24),
    programHeaderOffset: buffer.readUInt32LE(28),
    sectionHeaderOffset: buffer.readUInt32LE(32),
    programHeaderEntrySize: buffer.readUInt16LE(42),
    programHeaderCount: buffer.readUInt16LE(44),
    sectionHeaderEntrySize: buffer.readUInt16LE(46),
    sectionHeaderCount: buffer.readUInt16LE(48),
    sectionNameStringIndex: buffer.readUInt16LE(50),
  };
  const sectionsRaw = [];
  for (let i = 0; i < header.sectionHeaderCount; i += 1) {
    const off = header.sectionHeaderOffset + i * header.sectionHeaderEntrySize;
    sectionsRaw.push({
      index: i,
      nameOffset: buffer.readUInt32LE(off),
      type: buffer.readUInt32LE(off + 4),
      flags: buffer.readUInt32LE(off + 8),
      virtualAddress: buffer.readUInt32LE(off + 12),
      offset: buffer.readUInt32LE(off + 16),
      size: buffer.readUInt32LE(off + 20),
      link: buffer.readUInt32LE(off + 24),
      info: buffer.readUInt32LE(off + 28),
      align: buffer.readUInt32LE(off + 32),
      entrySize: buffer.readUInt32LE(off + 36),
    });
  }
  const shstr = sectionsRaw[header.sectionNameStringIndex];
  const sections = sectionsRaw.map((section) => ({
    ...section,
    name: readCString(buffer, shstr.offset + section.nameOffset),
  }));
  return { header, sections };
}

function fileOffsetToVirtualAddress(sections, fileOffset) {
  const section = sections.find((item) => item.size > 0 && fileOffset >= item.offset && fileOffset < item.offset + item.size);
  if (!section || !section.virtualAddress) return { virtualAddress: null, section: section ? section.name : null };
  return { virtualAddress: section.virtualAddress + (fileOffset - section.offset), section: section.name };
}

function virtualAddressToFileOffset(sections, virtualAddress) {
  const section = sections.find(
    (item) => item.size > 0 && item.virtualAddress && virtualAddress >= item.virtualAddress && virtualAddress < item.virtualAddress + item.size,
  );
  if (!section) return { fileOffset: null, section: null };
  return { fileOffset: section.offset + (virtualAddress - section.virtualAddress), section: section.name };
}

function makeStringLookup(strings, sections) {
  const byVirtualAddress = new Map();
  const enriched = strings.map((item) => {
    const mapped = fileOffsetToVirtualAddress(sections, item.fileOffset);
    const record = {
      ...item,
      virtualAddress: mapped.virtualAddress,
      virtualAddressHex: hex(mapped.virtualAddress),
      section: mapped.section,
    };
    if (mapped.virtualAddress !== null) byVirtualAddress.set(mapped.virtualAddress >>> 0, record);
    return record;
  });
  return { strings: enriched, byVirtualAddress };
}

function normalizeRegions(sections) {
  return REGIONS.map((region) => {
    const start = region.fileStart !== undefined ? region.fileStart : virtualAddressToFileOffset(sections, region.vaStart).fileOffset;
    const end = region.fileEnd !== undefined ? region.fileEnd : virtualAddressToFileOffset(sections, region.vaEnd - 1).fileOffset + 1;
    return { ...region, fileStart: start, fileEnd: end };
  });
}

function runCapstone(siteUnitPath, regions, thumb = false) {
  const blobBase64 = fs.readFileSync(siteUnitPath).toString("base64");
  const result = spawnSync("python", ["-c", PY_CAPSTONE], {
    input: JSON.stringify({ blobBase64, regions, thumb }),
    encoding: "utf8",
    windowsHide: true,
    timeout: 30000,
  });
  if (result.error || result.status !== 0) {
    return {
      ok: false,
      error: result.error ? result.error.message : result.stderr,
      regions: [],
    };
  }
  return { ok: true, error: null, regions: JSON.parse(result.stdout) };
}

function parseImmediate(value) {
  if (!value) return null;
  const cleaned = value.replace(/^#/, "");
  if (/^-?0x[0-9a-f]+$/i.test(cleaned)) return Number.parseInt(cleaned, 16);
  if (/^-?\d+$/.test(cleaned)) return Number.parseInt(cleaned, 10);
  return null;
}

function parseBranchTarget(insn) {
  if (!/^b(lx|l)?/.test(insn.mnemonic)) return null;
  const match = insn.opStr.match(/#?(0x[0-9a-f]+)/i);
  return match ? Number.parseInt(match[1], 16) : null;
}

function annotatePcrelLdr(insn, buffer, sections, stringsByVa) {
  if (!/^ldr/.test(insn.mnemonic)) return null;
  const match = insn.opStr.match(/^(r\d+|ip|lr|pc),\s*\[pc(?:,\s*#?(-?0x[0-9a-f]+|-?\d+))?\]/i);
  if (!match) return null;
  const imm = parseImmediate(match[2] || "0") || 0;
  const literalVa = insn.address + 8 + imm;
  const mapped = virtualAddressToFileOffset(sections, literalVa);
  if (mapped.fileOffset === null || mapped.fileOffset + 4 > buffer.length) {
    return { register: match[1], literalVirtualAddress: literalVa, literalVirtualAddressHex: hex(literalVa), error: "literal outside mapped file" };
  }
  const value = buffer.readUInt32LE(mapped.fileOffset);
  const string = stringsByVa.get(value >>> 0);
  return {
    register: match[1],
    literalVirtualAddress: literalVa,
    literalVirtualAddressHex: hex(literalVa),
    literalFileOffset: mapped.fileOffset,
    literalFileOffsetHex: hex(mapped.fileOffset),
    literalSection: mapped.section,
    value,
    valueHex: hex(value),
    constant: CONSTANTS.get(value) || null,
    string: string
      ? {
          text: string.text,
          fileOffsetHex: string.fileOffsetHex,
          virtualAddressHex: string.virtualAddressHex,
          section: string.section,
        }
      : null,
  };
}

function annotateInstructions(region, buffer, sections, stringsByVa) {
  const instructions = region.instructions.map((insn) => {
    const pcrelLiteral = annotatePcrelLdr(insn, buffer, sections, stringsByVa);
    const branchTarget = parseBranchTarget(insn);
    return {
      ...insn,
      addressHex: hex(insn.address),
      fileOffsetHex: hex(virtualAddressToFileOffset(sections, insn.address).fileOffset),
      pcrelLiteral,
      branchTarget,
      branchTargetHex: hex(branchTarget),
      branchTargetSection: branchTarget === null ? null : virtualAddressToFileOffset(sections, branchTarget).section,
    };
  });
  return { ...region, instructions };
}

function literalPool(region, buffer, sections, stringsByVa) {
  const rows = [];
  const alignedStart = region.fileStart + ((4 - (region.fileStart % 4)) % 4);
  for (let off = alignedStart; off <= region.fileEnd - 4; off += 4) {
    const value = buffer.readUInt32LE(off);
    const string = stringsByVa.get(value >>> 0);
    const constant = CONSTANTS.get(value) || null;
    const va = fileOffsetToVirtualAddress(sections, off).virtualAddress;
    if (!string && !constant) continue;
    rows.push({
      fileOffset: off,
      fileOffsetHex: hex(off),
      virtualAddress: va,
      virtualAddressHex: hex(va),
      value,
      valueHex: hex(value),
      constant,
      string: string
        ? {
            text: string.text,
            fileOffsetHex: string.fileOffsetHex,
            virtualAddressHex: string.virtualAddressHex,
            section: string.section,
          }
        : null,
    });
  }
  return rows;
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

function findPrologues(instructions) {
  return instructions.filter((insn) => {
    const text = `${insn.mnemonic} ${insn.opStr}`;
    return (
      (/stm(db|fd)?\s+sp!/i.test(text) && /lr/i.test(text)) ||
      (/push/i.test(insn.mnemonic) && /lr/i.test(insn.opStr)) ||
      (/str\s+lr,\s*\[sp/i.test(text))
    );
  });
}

function findExits(instructions) {
  return instructions.filter((insn) => {
    const text = `${insn.mnemonic} ${insn.opStr}`;
    return (
      (/ldm(ia|fd)?\s+sp!/i.test(text) && /pc/i.test(text)) ||
      (/ldm(db|ia|fd)?\s+fp/i.test(text) && /pc/i.test(text)) ||
      (/pop/i.test(insn.mnemonic) && /pc/i.test(insn.opStr)) ||
      (/bx\s+lr/i.test(text)) ||
      (/mov\s+pc,\s+lr/i.test(text))
    );
  });
}

function targetStringLoads(region, pattern) {
  const re = new RegExp(pattern, "i");
  return region.instructions.filter((insn) => insn.pcrelLiteral && insn.pcrelLiteral.string && re.test(insn.pcrelLiteral.string.text));
}

function nearbyInstructions(region, address, before = 8, after = 8) {
  const index = region.instructions.findIndex((insn) => insn.address === address);
  if (index === -1) return [];
  return region.instructions.slice(Math.max(0, index - before), Math.min(region.instructions.length, index + after + 1));
}

function analyzeParseData(region) {
  const prologues = findPrologues(region.instructions);
  const exits = findExits(region.instructions);
  const failSoiLoads = targetStringLoads(region, "fail SOI");
  const failChecksumLoads = targetStringLoads(region, "fail checksum");
  const failLengthLoads = targetStringLoads(region, "fail length");
  const parseDataLoads = targetStringLoads(region, "^ParseData$");
  const soiLiteralLoads = region.instructions.filter((insn) => insn.pcrelLiteral && insn.pcrelLiteral.value === 0x7e6d);
  const blCalls = region.instructions.filter((insn) => /^blx?$/.test(insn.mnemonic)).map((insn) => ({
    addressHex: insn.addressHex,
    fileOffsetHex: insn.fileOffsetHex,
    mnemonic: insn.mnemonic,
    opStr: insn.opStr,
    targetHex: insn.branchTargetHex,
    targetSection: insn.branchTargetSection,
  }));
  return {
    entryCandidates: prologues.map((insn) => ({ addressHex: insn.addressHex, fileOffsetHex: insn.fileOffsetHex, text: `${insn.mnemonic} ${insn.opStr}` })),
    exitCandidates: exits.map((insn) => ({ addressHex: insn.addressHex, fileOffsetHex: insn.fileOffsetHex, text: `${insn.mnemonic} ${insn.opStr}` })),
    parseDataStringLoads: parseDataLoads.map((insn) => ({ addressHex: insn.addressHex, text: `${insn.mnemonic} ${insn.opStr}` })),
    failSoiLoads: failSoiLoads.map((insn) => ({ addressHex: insn.addressHex, text: `${insn.mnemonic} ${insn.opStr}`, context: nearbyInstructions(region, insn.address, 10, 6) })),
    failChecksumLoads: failChecksumLoads.map((insn) => ({ addressHex: insn.addressHex, text: `${insn.mnemonic} ${insn.opStr}`, context: nearbyInstructions(region, insn.address, 10, 6) })),
    failLengthLoads: failLengthLoads.map((insn) => ({ addressHex: insn.addressHex, text: `${insn.mnemonic} ${insn.opStr}`, context: nearbyInstructions(region, insn.address, 10, 6) })),
    soiLiteralLoads: soiLiteralLoads.map((insn) => ({ addressHex: insn.addressHex, text: `${insn.mnemonic} ${insn.opStr}`, literal: insn.pcrelLiteral })),
    blCalls,
    cmpInstructions: region.instructions
      .filter((insn) => /^cmp|^cmn|^tst/.test(insn.mnemonic))
      .map((insn) => ({ addressHex: insn.addressHex, fileOffsetHex: insn.fileOffsetHex, text: `${insn.mnemonic} ${insn.opStr}` })),
    pseudocode: [
      "parseDataCandidate(ctx, /* r1-r3 unknown */, totalLen, buffer, outSeq) {",
      "  // Parameter names are inferred from use sites in this function.",
      "  if (*(uint16_le *)(buffer + 0x00) != 0x7e6d) return fail(\"fail SOI\");",
      "  savedChecksum = *(uint16_le *)(buffer + 0x16);",
      "  *(uint16_le *)(buffer + 0x16) = 0;",
      "  computed = additiveChecksum16(buffer, totalLen); // sums bytes [2, totalLen)",
      "  if (computed != savedChecksum) return fail(\"fail checksum\");",
      "  if (*(uint16_le *)(buffer + 0x14) != totalLen - 0x18) return fail(\"fail length\");",
      "  ctx->field_0x54 = *(uint32 *)(buffer + 0x0c);",
      "  command = buffer[0x06];",
      "  switch (command) {",
      "    // cases observed: 0x0a, 0x0c, 0x14, 0x16, 0x32, 0x3c, 0x3f, 0x47, 0xd3, 0xd6",
      "    // handlers include FillCmd / RealDataProcess / related processing functions.",
      "  }",
      "  *outSeq = *(uint16_le *)(buffer + 0x02);",
      "  return status;",
      "}",
    ].join("\n"),
  };
}

function analyzeLoginRegion(region) {
  const prologues = findPrologues(region.instructions);
  const exits = findExits(region.instructions);
  const blCalls = region.instructions.filter((insn) => /^blx?$/.test(insn.mnemonic)).map((insn) => ({
    addressHex: insn.addressHex,
    fileOffsetHex: insn.fileOffsetHex,
    mnemonic: insn.mnemonic,
    opStr: insn.opStr,
    targetHex: insn.branchTargetHex,
    targetSection: insn.branchTargetSection,
  }));
  const stringLoads = region.instructions
    .filter((insn) => insn.pcrelLiteral && insn.pcrelLiteral.string)
    .map((insn) => ({
      addressHex: insn.addressHex,
      fileOffsetHex: insn.fileOffsetHex,
      text: `${insn.mnemonic} ${insn.opStr}`,
      string: insn.pcrelLiteral.string.text,
    }));
  return {
    entryCandidates: prologues.map((insn) => ({ addressHex: insn.addressHex, fileOffsetHex: insn.fileOffsetHex, text: `${insn.mnemonic} ${insn.opStr}` })),
    exitCandidates: exits.map((insn) => ({ addressHex: insn.addressHex, fileOffsetHex: insn.fileOffsetHex, text: `${insn.mnemonic} ${insn.opStr}` })),
    blCalls,
    stringLoads,
    returnCodeBranchCandidates: region.instructions
      .filter((insn) => /^cmp|^cmn|^tst/.test(insn.mnemonic))
      .map((insn) => ({ addressHex: insn.addressHex, fileOffsetHex: insn.fileOffsetHex, text: `${insn.mnemonic} ${insn.opStr}` })),
  };
}

function analyzeChecksumCandidates(regions) {
  const parse = regions.find((region) => region.name === "ParseData");
  if (!parse) return [];
  return parse.instructions
    .filter((insn) => /^blx?$/.test(insn.mnemonic) && insn.branchTarget !== null)
    .map((insn) => ({
      functionVirtualAddress: insn.branchTarget,
      functionVirtualAddressHex: insn.branchTargetHex,
      callSiteVirtualAddressHex: insn.addressHex,
      callSiteFileOffsetHex: insn.fileOffsetHex,
      inputRegisters:
        insn.branchTarget === 0x7f98c
          ? "r0=buffer pointer, r1=total length at validation call 0x76170"
          : "unconfirmed; inspect r0-r3 setup before call",
      returnRegister: insn.branchTarget === 0x7f98c ? "r0 = uint16 additive checksum" : "r0 by ARM ABI, unconfirmed",
      quickFeatures:
        insn.branchTarget === 0x7f98c
          ? "Loop initializes index=2, reads one byte at buffer[index], adds into uint16 accumulator, increments until index >= length."
          : "Target not recursively classified in this pass.",
      possibleChecksumCandidate: insn.branchTarget === 0x7f98c ? "confirmed additive uint16 byte-sum over bytes [2, length)" : "unknown",
    }));
}

function markdownTable(rows, columns) {
  const header = `| ${columns.map((column) => column.title).join(" | ")} |`;
  const divider = `| ${columns.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => `| ${columns.map((column) => String(column.value(row) ?? "").replace(/\|/g, "\\|")).join(" | ")} |`);
  return [header, divider, ...body].join("\n");
}

function instructionLine(insn) {
  const annotation = [];
  if (insn.pcrelLiteral) {
    if (insn.pcrelLiteral.string) annotation.push(`literal ${insn.pcrelLiteral.valueHex} -> "${insn.pcrelLiteral.string.text}"`);
    else if (insn.pcrelLiteral.constant) annotation.push(`literal ${insn.pcrelLiteral.valueHex} -> ${insn.pcrelLiteral.constant}`);
    else annotation.push(`literal ${insn.pcrelLiteral.valueHex}`);
  }
  if (insn.branchTargetHex) annotation.push(`branch ${insn.branchTargetHex}`);
  return `${insn.addressHex.padEnd(10)}  ${(insn.bytes || "").padEnd(8)}  ${insn.mnemonic.padEnd(8)} ${insn.opStr}${annotation.length ? `  ; ${annotation.join("; ")}` : ""}`;
}

function writeRegionReports(outDir, result) {
  const jsonPath = path.join(outDir, `siteunit-disasm-regions-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  const md = [
    "# SiteUnit Disassembly Regions",
    "",
    `Generated: ${result.generatedAt}`,
    `Disassembler: ${result.disassembler.name}`,
    "",
    ...result.regions.flatMap((region) => [
      `## ${region.name}`,
      "",
      `VA: ${hex(region.vaStart)} - ${hex(region.vaEnd)}`,
      `File offsets: ${hex(region.fileStart)} - ${hex(region.fileEnd)}`,
      "",
      "### Instructions",
      "",
      "```asm",
      region.instructions.map(instructionLine).join("\n") || region.hexDump,
      "```",
      "",
      "### Literal Pool / Annotated Words",
      "",
      region.literalPool.length
        ? markdownTable(region.literalPool, [
            { title: "VA", value: (row) => row.virtualAddressHex },
            { title: "File Off", value: (row) => row.fileOffsetHex },
            { title: "Value", value: (row) => row.valueHex },
            { title: "Meaning", value: (row) => row.string ? `string: \`${row.string.text}\`` : row.constant },
          ])
        : "No annotated literal words.",
      "",
    ]),
  ].join("\n");
  const mdPath = path.join(outDir, `siteunit-disasm-regions-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function writeAnalysisReport(outDir, result) {
  const jsonPath = path.join(outDir, `ack-disasm-analysis-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  const md = [
    "# ACK Disassembly Analysis",
    "",
    `Generated: ${result.generatedAt}`,
    "",
    "## 1. Tool Detection Result",
    "",
    `Selected: ${result.toolResult.selectedTool ? result.toolResult.selectedTool.name : "none"}`,
    "",
    "## 2. ELF Mapping",
    "",
    `Architecture: ${result.elf.header.architecture}`,
    `Endian: ${result.elf.header.endian}`,
    `Entry point: ${hex(result.elf.header.entryPoint)}`,
    `Mapping verification: ${result.elf.verification.every((item) => item.ok) ? "confirmed" : "not fully confirmed"}`,
    "",
    "## 3. ParseData Disassembly",
    "",
    `Region: ${hex(result.parseData.region.vaStart)} - ${hex(result.parseData.region.vaEnd)}`,
    `Entry candidates: ${result.parseData.analysis.entryCandidates.map((item) => `${item.addressHex} ${item.text}`).join(", ") || "none in region"}`,
    `Exit candidates: ${result.parseData.analysis.exitCandidates.map((item) => `${item.addressHex} ${item.text}`).join(", ") || "none in region"}`,
    "",
    "## 4. ParseData Pseudocode",
    "",
    "```c",
    result.parseData.analysis.pseudocode,
    "```",
    "",
    "## 5. SOI Judgement",
    "",
    result.conclusions.soi,
    "",
    "## 6. Length Judgement",
    "",
    result.conclusions.length,
    "",
    "## 7. Checksum Judgement",
    "",
    result.conclusions.checksum,
    "",
    "## 8. Checksum Function Candidates",
    "",
    result.checksumCandidates.length
      ? markdownTable(result.checksumCandidates, [
          { title: "Function VA", value: (row) => row.functionVirtualAddressHex },
          { title: "Call Site", value: (row) => row.callSiteVirtualAddressHex },
          { title: "Input Regs", value: (row) => row.inputRegisters },
          { title: "Return", value: (row) => row.returnRegister },
          { title: "Type", value: (row) => row.possibleChecksumCandidate },
        ])
      : "No BL/BLX calls in ParseData region.",
    "",
    "## 9. LoginToDSC / Register OK Path",
    "",
    result.conclusions.loginPath,
    "",
    "## 10. LOGIN_ACK Text Command Table",
    "",
    result.conclusions.loginAck,
    "",
    "## 11. Can Construct Real ACK",
    "",
    result.conclusions.realAck,
    "",
    "## 12. Next Steps",
    "",
    result.nextSteps.map((item) => `- ${item}`).join("\n"),
    "",
  ].join("\n");
  const mdPath = path.join(outDir, `ack-disasm-analysis-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function runToolDetection() {
  const commandTools = ["arm-linux-gnueabi-objdump", "arm-none-eabi-objdump", "llvm-objdump", "objdump", "readelf", "llvm-readelf"];
  const tools = commandTools.map((name) => {
    const result = spawnSync(name, ["--version"], { encoding: "utf8", windowsHide: true, timeout: 10000 });
    return { name, available: !result.error && result.status === 0, version: (result.stdout || result.stderr || "").split(/\r?\n/)[0] || null };
  });
  const py = spawnSync("python", ["-c", "import capstone; print(capstone.__version__)"], { encoding: "utf8", windowsHide: true, timeout: 10000 });
  tools.push({ name: "python capstone", available: !py.error && py.status === 0, version: (py.stdout || "").trim() || null });
  const selectedTool = tools.find((tool) => tool.available && /objdump/.test(tool.name)) || tools.find((tool) => tool.available && tool.name === "python capstone") || null;
  return { tools, selectedTool };
}

function main() {
  const args = parseArgs(process.argv);
  const siteUnitPath = resolveSiteUnitPath(args);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  fs.mkdirSync(outDir, { recursive: true });

  const buffer = fs.readFileSync(siteUnitPath);
  const elf = parseElf(buffer);
  const regions = normalizeRegions(elf.sections);
  const strings = makeStringLookup(extractAsciiStrings(buffer), elf.sections);
  const toolResult = runToolDetection();

  const armDisasm = toolResult.selectedTool && toolResult.selectedTool.name === "python capstone"
    ? runCapstone(siteUnitPath, regions, false)
    : runCapstone(siteUnitPath, regions, false);
  const rawRegions = armDisasm.ok ? armDisasm.regions : regions.map((region) => ({ name: region.name, mode: "none", instructions: [] }));
  const annotated = rawRegions.map((raw) => {
    const region = regions.find((item) => item.name === raw.name);
    const withMeta = { ...region, mode: raw.mode, instructions: raw.instructions, hexDump: hexdump(buffer, region.fileStart, region.fileEnd - region.fileStart) };
    const annotatedRegion = annotateInstructions(withMeta, buffer, elf.sections, strings.byVirtualAddress);
    return { ...annotatedRegion, literalPool: literalPool(region, buffer, elf.sections, strings.byVirtualAddress) };
  });

  const parseRegion = annotated.find((region) => region.name === "ParseData");
  const loginRegisterRegion = annotated.find((region) => region.name === "Login/Register");
  const loginTimeoutRegion = annotated.find((region) => region.name === "Login timeout");
  const loginAckRegion = annotated.find((region) => region.name === "LOGIN_ACK text command table");
  const parseAnalysis = analyzeParseData(parseRegion);
  const loginRegisterAnalysis = analyzeLoginRegion(loginRegisterRegion);
  const loginTimeoutAnalysis = analyzeLoginRegion(loginTimeoutRegion);
  const loginAckAnalysis = analyzeLoginRegion(loginAckRegion);
  const checksumCandidates = analyzeChecksumCandidates(annotated);

  const verification = [
    { fileOffset: 0x6e878, expectedVa: 0x76878 },
    { fileOffset: 0x6d77c, expectedVa: 0x7577c },
    { fileOffset: 0x6f634, expectedVa: 0x77634 },
  ].map((item) => {
    const mapped = fileOffsetToVirtualAddress(elf.sections, item.fileOffset);
    return {
      fileOffsetHex: hex(item.fileOffset),
      expectedVirtualAddressHex: hex(item.expectedVa),
      virtualAddressHex: hex(mapped.virtualAddress),
      section: mapped.section,
      ok: mapped.virtualAddress === item.expectedVa,
    };
  });

  const regionReport = {
    generatedAt: new Date().toISOString(),
    fileInfo: {
      path: siteUnitPath,
      size: buffer.length,
      sha256: crypto.createHash("sha256").update(buffer).digest("hex"),
    },
    disassembler: {
      name: toolResult.selectedTool ? toolResult.selectedTool.name : "none",
      capstoneOk: armDisasm.ok,
      capstoneError: armDisasm.error,
      mode: "ARM",
    },
    regions: annotated,
  };
  const regionPaths = writeRegionReports(outDir, regionReport);

  const analysisReport = {
    generatedAt: new Date().toISOString(),
    fileInfo: regionReport.fileInfo,
    toolResult,
    elf: {
      header: {
        ...elf.header,
        entryPointHex: hex(elf.header.entryPoint),
      },
      verification,
    },
    regionReports: regionPaths,
    parseData: { region: parseRegion, analysis: parseAnalysis },
    loginRegister: { region: loginRegisterRegion, analysis: loginRegisterAnalysis },
    loginTimeout: { region: loginTimeoutRegion, analysis: loginTimeoutAnalysis },
    loginAckTextCommandTable: { region: loginAckRegion, analysis: loginAckAnalysis },
    checksumCandidates,
    conclusions: {
      soi:
        parseAnalysis.soiLiteralLoads.length && parseAnalysis.failSoiLoads.length
          ? "Confirmed in the ParseData candidate: ldrh r2, [buffer+0x00], load literal 0x00007e6d, cmp r2,r3, beq success; otherwise logs fail SOI. In bytes this is SOI 6d 7e."
          : "SOI was not confirmed by instruction-level data flow.",
      length:
        parseAnalysis.failLengthLoads.length
          ? "Confirmed in ParseData: expected length is totalLen - 0x18 and is compared against uint16_le(buffer+0x14). The field at bytes[20..21] is the payload/body length candidate."
          : "No fail length branch was recovered.",
      checksum:
        parseAnalysis.failChecksumLoads.length
          ? "Confirmed in ParseData: saved checksum is uint16_le(buffer+0x16), the field is zeroed before BL 0x7f98c, and the returned uint16 is compared to the saved value. Function 0x7f98c is a simple additive uint16 sum of bytes buffer[2] through buffer[length-1]."
          : "No fail checksum branch was recovered.",
      loginPath:
        "Login/Register path is partially recovered. The region logs LogToDS, calls 0x76ac4, logs LoginToDSC Result, then receives data and calls ParseData at 0x755bc -> 0x760a4. Register OK is printed after LoginToDSC Result != 0 and byte *(ctx + 0x129) == 0. The exact semantic name of ctx+0x129 and the Success/Fail/UnRegister return-code field still need deeper data-flow.",
      loginAck:
        "The LOGIN_ACK region still looks like a text command table: LOGIN, LOGOUT, LOGIN_ACK, GET_DATA, GET_DATA_ACK, SEND_ALARM_ACK, TIME_CHECK_ACK and XML.log are co-located. No evidence ties it to the UDP DSC binary ACK path.",
      realAck:
        "No. The true ACK frame format is still not safe to construct. Do not send or mirror; continue offline disassembly/data-flow.",
    },
    nextSteps: [
      "Manually inspect PC-relative LDR setup before fail SOI/fail length/fail checksum loads and recover the controlling compare/branch.",
      "Disassemble BL/BLX targets from ParseData and classify which target, if any, computes checksum.",
      "Extend disassembly around function starts before 0x76878 if the prologue is outside the current candidate range.",
      "Resolve PLT symbols/imports so recv/send/select/socket and logging calls are named.",
      "Only after buffer field offsets and checksum are proven should a one-shot candidate be designed offline.",
    ],
  };
  const analysisPaths = writeAnalysisReport(outDir, analysisReport);

  console.log(
    JSON.stringify(
      {
        siteUnitPath,
        disassembler: regionReport.disassembler,
        regionReports: regionPaths,
        analysisReports: analysisPaths,
        elfVerification: verification,
        parseSummary: {
          entryCandidates: parseAnalysis.entryCandidates,
          exitCandidates: parseAnalysis.exitCandidates,
          failSoiLoads: parseAnalysis.failSoiLoads.map((item) => item.addressHex),
          failChecksumLoads: parseAnalysis.failChecksumLoads.map((item) => item.addressHex),
          failLengthLoads: parseAnalysis.failLengthLoads.map((item) => item.addressHex),
          soiLiteralLoads: parseAnalysis.soiLiteralLoads.map((item) => item.addressHex),
          blCalls: parseAnalysis.blCalls,
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
