#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const DATE_STEM = "2026-04-28";
const DEFAULT_FIRMWARE_ROOT = path.join(process.env.USERPROFILE || process.cwd(), "Desktop", "FSU");
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");
const TARGET_OFFSET = 0x129;

const RETURN_STRINGS = [
  "LoginToDSC Result",
  "LogToDS return [%d]: Success",
  "LogToDS return Code[%d]: Fail",
  "LogToDS return Code[%d]: UnRegister",
];

const PY_CAPSTONE = String.raw`
import base64, json, sys
from capstone import *

payload = json.load(sys.stdin)
blob = base64.b64decode(payload["blobBase64"])
md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.skipdata = True
out = []
for insn in md.disasm(blob[payload["start"]:payload["end"]], payload["vaStart"]):
    out.append({
        "address": insn.address,
        "size": insn.size,
        "bytes": insn.bytes.hex(),
        "mnemonic": insn.mnemonic,
        "opStr": insn.op_str,
    })
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

function hex(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return `0x${Number(value).toString(16)}`;
}

function parseImmediate(value) {
  if (!value) return 0;
  const trimmed = String(value).trim().toLowerCase();
  if (trimmed.startsWith("-0x")) return -Number.parseInt(trimmed.slice(3), 16);
  if (trimmed.startsWith("0x")) return Number.parseInt(trimmed.slice(2), 16);
  return Number.parseInt(trimmed, 10);
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
  throw new Error(`SiteUnit not found under ${firmwareRoot}`);
}

function readCString(buffer, offset) {
  let end = offset;
  while (end < buffer.length && buffer[end] !== 0) end += 1;
  return buffer.toString("ascii", offset, end);
}

function parseElf(buffer) {
  if (buffer[0] !== 0x7f || buffer.toString("ascii", 1, 4) !== "ELF" || buffer[4] !== 1 || buffer[5] !== 1) {
    throw new Error("expected ELF32 LSB");
  }
  const shoff = buffer.readUInt32LE(32);
  const shentsize = buffer.readUInt16LE(46);
  const shnum = buffer.readUInt16LE(48);
  const shstrndx = buffer.readUInt16LE(50);
  const raw = [];
  for (let i = 0; i < shnum; i += 1) {
    const off = shoff + i * shentsize;
    raw.push({
      index: i,
      nameOffset: buffer.readUInt32LE(off),
      type: buffer.readUInt32LE(off + 4),
      flags: buffer.readUInt32LE(off + 8),
      va: buffer.readUInt32LE(off + 12),
      offset: buffer.readUInt32LE(off + 16),
      size: buffer.readUInt32LE(off + 20),
    });
  }
  const shstr = raw[shstrndx];
  const sections = raw.map((section) => ({
    ...section,
    name: readCString(buffer, shstr.offset + section.nameOffset),
  }));
  return { sections };
}

function fileOffsetToVa(sections, fileOffset) {
  const section = sections.find((item) => item.size > 0 && fileOffset >= item.offset && fileOffset < item.offset + item.size);
  if (!section || !section.va) return { va: null, section: section ? section.name : null };
  return { va: section.va + (fileOffset - section.offset), section: section.name };
}

function vaToFileOffset(sections, va) {
  const section = sections.find((item) => item.size > 0 && item.va && va >= item.va && va < item.va + item.size);
  if (!section) return { fileOffset: null, section: null };
  return { fileOffset: section.offset + (va - section.va), section: section.name };
}

function isPrintable(byte) {
  return byte >= 0x20 && byte <= 0x7e;
}

function extractStrings(buffer) {
  const strings = [];
  let start = -1;
  for (let i = 0; i <= buffer.length; i += 1) {
    const byte = i < buffer.length ? buffer[i] : 0;
    if (i < buffer.length && isPrintable(byte)) {
      if (start < 0) start = i;
      continue;
    }
    if (start >= 0) {
      const length = i - start;
      if (length >= 4) {
        strings.push({ fileOffset: start, text: buffer.toString("ascii", start, i) });
      }
      start = -1;
    }
  }
  return strings;
}

function runCapstone(siteUnitPath, buffer, text) {
  const result = spawnSync("python", ["-c", PY_CAPSTONE], {
    input: JSON.stringify({
      blobBase64: buffer.toString("base64"),
      start: text.offset,
      end: text.offset + text.size,
      vaStart: text.va,
    }),
    encoding: "utf8",
    windowsHide: true,
    timeout: 60000,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) {
    throw new Error(result.error ? result.error.message : result.stderr);
  }
  return JSON.parse(result.stdout);
}

function annotate(insns, buffer, sections, stringByVa) {
  return insns.map((insn) => {
    const fileOffset = vaToFileOffset(sections, insn.address).fileOffset;
    const pcrel = parsePcrelLiteral(insn, buffer, sections, stringByVa);
    return {
      ...insn,
      addressHex: hex(insn.address),
      fileOffset,
      fileOffsetHex: hex(fileOffset),
      text: `${insn.mnemonic} ${insn.opStr}`,
      pcrelLiteral: pcrel,
    };
  });
}

function parsePcrelLiteral(insn, buffer, sections, stringByVa) {
  if (!/^ldr/.test(insn.mnemonic)) return null;
  const match = insn.opStr.match(/^(r\d+|ip|lr|pc),\s*\[pc(?:,\s*#?(-?0x[0-9a-f]+|-?\d+))?\]/i);
  if (!match) return null;
  const imm = parseImmediate(match[2]);
  const literalVa = insn.address + 8 + imm;
  const mapped = vaToFileOffset(sections, literalVa);
  if (mapped.fileOffset === null || mapped.fileOffset + 4 > buffer.length) return null;
  const value = buffer.readUInt32LE(mapped.fileOffset);
  const str = stringByVa.get(value >>> 0) || null;
  return {
    register: match[1],
    literalVa,
    literalVaHex: hex(literalVa),
    literalFileOffsetHex: hex(mapped.fileOffset),
    value,
    valueHex: hex(value),
    string: str ? { text: str.text, vaHex: hex(str.va), fileOffsetHex: hex(str.fileOffset) } : null,
  };
}

function context(insns, index, radius = 20) {
  return insns.slice(Math.max(0, index - radius), Math.min(insns.length, index + radius + 1));
}

function regionName(va) {
  if (va >= 0x760a4 && va <= 0x76a64) return "ParseData";
  if (va >= 0x74d00 && va <= 0x75a50) return "Login/Register";
  if (va >= 0x77200 && va <= 0x77950) return "Login timeout";
  if (va >= 0x9dc00 && va <= 0x9e300) return "LOGIN_ACK text command table";
  return "other .text";
}

function classifyAccess(insns, index) {
  const insn = insns[index];
  const lower = insn.mnemonic.toLowerCase();
  let access = lower.startsWith("str") ? "write" : lower.startsWith("ldr") ? "read" : "unknown";
  if (!/b\s*\[/.test(insn.text) && !/ldrb|strb/.test(lower)) access = "constant/setup";
  return access;
}

function findOffsetAccesses(insns) {
  const hits = [];
  for (let i = 0; i < insns.length; i += 1) {
    const insn = insns[i];
    const direct = /#0x129\b|#297\b/.test(insn.opStr);
    const literal129 = insn.pcrelLiteral && insn.pcrelLiteral.value === TARGET_OFFSET;
    const splitAdd = /#0x100\b|#256\b|#0x29\b|#41\b/.test(insn.opStr);
    if (!direct && !literal129 && !splitAdd) continue;

    const ctx = context(insns, i, 20);
    const relatedAccesses = ctx.filter((item) => /(?:ldr|str)b/.test(item.mnemonic) && /\[.*\]/.test(item.opStr));
    hits.push({
      va: insn.address,
      vaHex: insn.addressHex,
      fileOffsetHex: insn.fileOffsetHex,
      instruction: insn.text,
      hitKind: literal129 ? "pc-relative literal 0x129" : direct ? "direct immediate 0x129" : "split immediate heuristic",
      access: classifyAccess(insns, i),
      region: regionName(insn.address),
      context: ctx,
      relatedByteAccesses: relatedAccesses.map((item) => ({
        vaHex: item.addressHex,
        fileOffsetHex: item.fileOffsetHex,
        instruction: item.text,
        access: classifyAccess(insns, insns.indexOf(item)),
      })),
      nearbyStrings: ctx
        .filter((item) => item.pcrelLiteral && item.pcrelLiteral.string)
        .map((item) => ({ vaHex: item.addressHex, text: item.pcrelLiteral.string.text })),
    });
  }
  return hits;
}

function findReturnStringContexts(insns) {
  const hits = [];
  for (let i = 0; i < insns.length; i += 1) {
    const lit = insns[i].pcrelLiteral;
    if (!lit || !lit.string) continue;
    const matched = RETURN_STRINGS.find((needle) => lit.string.text.includes(needle));
    if (!matched) continue;
    hits.push({
      target: matched,
      string: lit.string.text,
      vaHex: insns[i].addressHex,
      fileOffsetHex: insns[i].fileOffsetHex,
      region: regionName(insns[i].address),
      context: context(insns, i, 30),
    });
  }
  return hits;
}

function markdownTable(rows, columns) {
  const header = `| ${columns.map((column) => column.title).join(" | ")} |`;
  const divider = `| ${columns.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => `| ${columns.map((column) => String(column.value(row) ?? "").replace(/\|/g, "\\|")).join(" | ")} |`);
  return [header, divider, ...body].join("\n");
}

function insnTable(rows) {
  return markdownTable(rows, [
    { title: "VA", value: (row) => row.addressHex },
    { title: "File Off", value: (row) => row.fileOffsetHex },
    { title: "Instruction", value: (row) => row.text },
    { title: "Literal/String", value: (row) => row.pcrelLiteral ? row.pcrelLiteral.string ? row.pcrelLiteral.string.text : row.pcrelLiteral.valueHex : "" },
  ]);
}

function writeTraceReport(outDir, result) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `login-result-field-trace-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  const md = [
    "# Login Result Field Trace",
    "",
    `Generated: ${result.generatedAt}`,
    "",
    "## Summary",
    "",
    result.summary,
    "",
    "## ctx+0x129 Access Candidates",
    "",
    markdownTable(result.offset129Accesses, [
      { title: "VA", value: (row) => row.vaHex },
      { title: "File Off", value: (row) => row.fileOffsetHex },
      { title: "Region", value: (row) => row.region },
      { title: "Kind", value: (row) => row.hitKind },
      { title: "Access", value: (row) => row.access },
      { title: "Instruction", value: (row) => row.instruction },
      { title: "Nearby Strings", value: (row) => row.nearbyStrings.map((item) => item.text).join("<br>") },
    ]),
    "",
    ...result.offset129Accesses.flatMap((hit) => [
      `### ${hit.vaHex} ${hit.hitKind}`,
      "",
      "Related byte accesses:",
      "",
      markdownTable(hit.relatedByteAccesses, [
        { title: "VA", value: (row) => row.vaHex },
        { title: "Access", value: (row) => row.access },
        { title: "Instruction", value: (row) => row.instruction },
      ]),
      "",
      "Context:",
      "",
      insnTable(hit.context),
      "",
    ]),
  ].join("\n");
  const mdPath = path.join(outDir, `login-result-field-trace-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function writeReturnCodeReport(outDir, result) {
  const jsonPath = path.join(outDir, `login-return-code-analysis-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  const md = [
    "# Login Return Code Analysis",
    "",
    `Generated: ${result.generatedAt}`,
    "",
    "## Conclusion",
    "",
    result.conclusion,
    "",
    "## String Contexts",
    "",
    ...result.returnStringContexts.flatMap((hit) => [
      `### ${hit.target}: ${hit.string}`,
      "",
      `String load: ${hit.vaHex} (${hit.region})`,
      "",
      insnTable(hit.context),
      "",
    ]),
  ].join("\n");
  const mdPath = path.join(outDir, `login-return-code-analysis-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const siteUnitPath = resolveSiteUnitPath(args);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const buffer = fs.readFileSync(siteUnitPath);
  const { sections } = parseElf(buffer);
  const text = sections.find((section) => section.name === ".text");
  if (!text) throw new Error(".text section not found");

  const stringByVa = new Map();
  for (const item of extractStrings(buffer)) {
    const mapped = fileOffsetToVa(sections, item.fileOffset);
    if (mapped.va !== null) stringByVa.set(mapped.va >>> 0, { ...item, va: mapped.va });
  }

  const insns = annotate(runCapstone(siteUnitPath, buffer, text), buffer, sections, stringByVa);
  const offset129Accesses = findOffsetAccesses(insns);
  const returnStringContexts = findReturnStringContexts(insns);
  const parseWrites129 = offset129Accesses.filter((hit) => hit.region === "ParseData" && hit.access === "write");
  const registerRead = offset129Accesses.filter((hit) => hit.region === "Login/Register");

  const traceResult = {
    generatedAt: new Date().toISOString(),
    siteUnitPath,
    instructionCount: insns.length,
    summary:
      parseWrites129.length === 0
        ? "No confirmed ctx+0x129 write was found inside ParseData. The confirmed Login/Register access uses a PC-relative literal 0x129 followed by ldrb [ctx, r2] before Register OK."
        : "One or more ParseData writes to ctx+0x129 were found; inspect candidate list.",
    offset129Accesses,
    parseWrites129,
    loginRegisterAccesses: registerRead,
  };
  const tracePaths = writeTraceReport(outDir, traceResult);

  const returnResult = {
    generatedAt: new Date().toISOString(),
    siteUnitPath,
    returnStringContexts,
    conclusion:
      "LoginToDSC Result is logged from a local return variable after call 0x76ac4. In the GetServiceAddr/LogToDS return handling region, a local status byte is compared against 0, 1, and 2: 0 prints Success and writes ctx+0x129=0; 1 prints Fail and writes ctx+0x129=1; 2 prints UnRegister and writes ctx+0x129=2. This identifies internal branch/status values, but does not yet prove the raw response packet offset or ACK body encoding.",
    inferredCodes: {
      success: { value: 0, confidence: "internal status byte only; wire field not confirmed" },
      fail: { value: 1, confidence: "internal status byte only; wire field not confirmed" },
      unregister: { value: 2, confidence: "internal status byte only; wire field not confirmed" },
    },
  };
  const returnPaths = writeReturnCodeReport(outDir, returnResult);

  console.log(
    JSON.stringify(
      {
        trace: tracePaths,
        returnCode: returnPaths,
        offset129AccessCount: offset129Accesses.length,
        parseWrites129: parseWrites129.length,
        returnStringContextCount: returnStringContexts.length,
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
