#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { modelAckStructure } = require("../fsu-ack-experiments/model-ack-structure");

const DATE_STEM = "2026-04-28";
const DEFAULT_FIRMWARE_ROOT = path.join(process.env.USERPROFILE || process.cwd(), "Desktop", "FSU");
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

const REGION = { name: "GetServiceAddr/LogToDS status handler", vaStart: 0x7e800, vaEnd: 0x7ea40 };
const WIDE_REGION = { name: "GetServiceAddr wider candidate", vaStart: 0x7e700, vaEnd: 0x7f420 };
const LOCAL_STATUS_NEG = -0x135;
const CTX_STATUS_OFFSET = 0x129;

const KEY_STRINGS = [
  "GetServiceAddr",
  "LogToDS",
  "LogToDS return",
  "Success",
  "Fail",
  "UnRegister",
  "DS busy happen",
  "FillCmd",
  "RealDataProcess",
  "ControlRequest",
  "SequenceId",
  "Code",
  "Result",
  "XML",
];

const PY_CAPSTONE = String.raw`
import base64, json, sys
from capstone import *

payload = json.load(sys.stdin)
blob = base64.b64decode(payload["blobBase64"])
md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.skipdata = True
out = []
for region in payload["regions"]:
    code = blob[region["fileStart"]:region["fileEnd"]]
    insns = []
    for insn in md.disasm(code, region["vaStart"]):
        insns.append({
            "address": insn.address,
            "size": insn.size,
            "bytes": insn.bytes.hex(),
            "mnemonic": insn.mnemonic,
            "opStr": insn.op_str,
        })
    out.append({"name": region["name"], "instructions": insns})
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
  const text = String(value).trim().toLowerCase();
  if (text.startsWith("-0x")) return -Number.parseInt(text.slice(3), 16);
  if (text.startsWith("0x")) return Number.parseInt(text.slice(2), 16);
  return Number.parseInt(text, 10);
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
  const root = path.resolve(args["firmware-root"] || DEFAULT_FIRMWARE_ROOT);
  const direct = path.join(root, "SiteUnit");
  if (fs.existsSync(direct)) return direct;
  const matches = walkFiles(root, "SiteUnit");
  if (matches.length) return matches.sort((a, b) => a.length - b.length || a.localeCompare(b))[0];
  throw new Error(`SiteUnit not found under ${root}`);
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
  const sections = raw.map((section) => ({ ...section, name: readCString(buffer, shstr.offset + section.nameOffset) }));
  return { sections };
}

function vaToFileOffset(sections, va) {
  const section = sections.find((item) => item.size > 0 && item.va && va >= item.va && va < item.va + item.size);
  if (!section) return { fileOffset: null, section: null };
  return { fileOffset: section.offset + (va - section.va), section: section.name };
}

function fileOffsetToVa(sections, fileOffset) {
  const section = sections.find((item) => item.size > 0 && fileOffset >= item.offset && fileOffset < item.offset + item.size);
  if (!section || !section.va) return { va: null, section: section ? section.name : null };
  return { va: section.va + (fileOffset - section.offset), section: section.name };
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
      if (length >= 4) strings.push({ fileOffset: start, text: buffer.toString("ascii", start, i) });
      start = -1;
    }
  }
  return strings;
}

function mapRegion(sections, region) {
  const start = vaToFileOffset(sections, region.vaStart);
  const end = vaToFileOffset(sections, region.vaEnd);
  if (start.fileOffset === null || end.fileOffset === null) throw new Error(`cannot map ${region.name}`);
  return { ...region, fileStart: start.fileOffset, fileEnd: end.fileOffset };
}

function runCapstone(buffer, regions) {
  const result = spawnSync("python", ["-c", PY_CAPSTONE], {
    input: JSON.stringify({
      blobBase64: buffer.toString("base64"),
      regions,
    }),
    encoding: "utf8",
    windowsHide: true,
    timeout: 60000,
    maxBuffer: 32 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) throw new Error(result.error ? result.error.message : result.stderr);
  return JSON.parse(result.stdout);
}

function parsePcrelLiteral(insn, buffer, sections, stringByVa) {
  if (!/^ldr/.test(insn.mnemonic)) return null;
  const match = insn.opStr.match(/^(r\d+|ip|lr|pc),\s*\[pc(?:,\s*#?(-?0x[0-9a-f]+|-?\d+))?\]/i);
  if (!match) return null;
  const literalVa = insn.address + 8 + parseImmediate(match[2]);
  const mapped = vaToFileOffset(sections, literalVa);
  if (mapped.fileOffset === null || mapped.fileOffset + 4 > buffer.length) return null;
  const value = buffer.readUInt32LE(mapped.fileOffset);
  const string = stringByVa.get(value >>> 0) || null;
  return {
    register: match[1],
    literalVa,
    literalVaHex: hex(literalVa),
    literalFileOffsetHex: hex(mapped.fileOffset),
    value,
    valueHex: hex(value),
    string: string ? { text: string.text, vaHex: hex(string.va), fileOffsetHex: hex(string.fileOffset) } : null,
  };
}

function annotate(insns, buffer, sections, stringByVa) {
  return insns.map((insn) => {
    const mapped = vaToFileOffset(sections, insn.address);
    const pcrelLiteral = parsePcrelLiteral(insn, buffer, sections, stringByVa);
    return {
      ...insn,
      addressHex: hex(insn.address),
      fileOffset: mapped.fileOffset,
      fileOffsetHex: hex(mapped.fileOffset),
      text: `${insn.mnemonic} ${insn.opStr}`,
      pcrelLiteral,
    };
  });
}

function context(insns, index, radius = 30) {
  return insns.slice(Math.max(0, index - radius), Math.min(insns.length, index + radius + 1));
}

function accessKind(mnemonic) {
  const lower = mnemonic.toLowerCase();
  if (lower.startsWith("str")) return "write";
  if (lower.startsWith("ldr")) return "read";
  return "other";
}

function findLocalStatusAccesses(insns) {
  const direct = [];
  for (let i = 0; i < insns.length; i += 1) {
    const insn = insns[i];
    const op = insn.opStr.toLowerCase();
    const isDirect = /\[(?:fp|r11),\s*#-0x135\]/.test(op) || /\[(?:fp|r11),\s*#-309\]/.test(op);
    const isEquivalent = /mvn\s+r\d+,\s*#0x10c/i.test(insn.text) || /mvn\s+r\d+,\s*#268/i.test(insn.text);
    if (!isDirect && !isEquivalent) continue;
    direct.push({
      va: insn.address,
      vaHex: insn.addressHex,
      fileOffsetHex: insn.fileOffsetHex,
      instruction: insn.text,
      access: isDirect ? accessKind(insn.mnemonic) : "offset setup",
      matchKind: isDirect ? "direct fp-0x135" : "equivalent offset via mvn #0x10c (-0x10d) with base fp-0x28 => fp-0x135",
      functionCandidate: WIDE_REGION.name,
      context: context(insns, i, 30),
      nearbyStrings: context(insns, i, 30)
        .filter((item) => item.pcrelLiteral && item.pcrelLiteral.string)
        .map((item) => ({ vaHex: item.addressHex, text: item.pcrelLiteral.string.text })),
    });
  }
  return direct;
}

function findCtx129Writes(insns) {
  const writes = [];
  for (let i = 0; i < insns.length; i += 1) {
    const insn = insns[i];
    if (!insn.pcrelLiteral || insn.pcrelLiteral.value !== CTX_STATUS_OFFSET) continue;
    const ctx = context(insns, i, 16);
    const strb = ctx.filter((item) => item.mnemonic.toLowerCase().startsWith("strb") && /\[r1,\s*r2\]/i.test(item.opStr));
    writes.push({
      vaHex: insn.addressHex,
      fileOffsetHex: insn.fileOffsetHex,
      literalInstruction: insn.text,
      stores: strb.map((item) => ({ vaHex: item.addressHex, fileOffsetHex: item.fileOffsetHex, instruction: item.text })),
      context: ctx,
    });
  }
  return writes;
}

function findCallsAndStringParsing(insns) {
  const calls = insns
    .filter((insn) => /^blx?$/.test(insn.mnemonic))
    .map((insn) => ({ vaHex: insn.addressHex, fileOffsetHex: insn.fileOffsetHex, instruction: insn.text }));
  const stringRefs = insns
    .filter((insn) => insn.pcrelLiteral && insn.pcrelLiteral.string)
    .map((insn) => ({ vaHex: insn.addressHex, fileOffsetHex: insn.fileOffsetHex, text: insn.pcrelLiteral.string.text }));
  const keyStringRefs = stringRefs.filter((item) => KEY_STRINGS.some((needle) => item.text.includes(needle)));
  return { calls, stringRefs, keyStringRefs };
}

function findBufferReads(insns) {
  const reads = [];
  for (const insn of insns) {
    const lower = insn.mnemonic.toLowerCase();
    if (!["ldrb", "ldrh", "ldr"].includes(lower)) continue;
    const op = insn.opStr.toLowerCase();
    if (!/\[/.test(op)) continue;
    if (/\[(?:fp|r11|sp|pc)/.test(op)) continue;
    reads.push({
      vaHex: insn.addressHex,
      fileOffsetHex: insn.fileOffsetHex,
      width: lower === "ldrb" ? "byte" : lower === "ldrh" ? "halfword" : "word",
      instruction: insn.text,
      note: "base register is not fp/sp/pc; may be buffer/context/global. Needs manual data-flow confirmation.",
    });
  }
  return reads;
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
    { title: "Literal/String", value: (row) => (row.pcrelLiteral ? (row.pcrelLiteral.string ? row.pcrelLiteral.string.text : row.pcrelLiteral.valueHex) : "") },
  ]);
}

function buildAnalysis(annotatedRegions, siteUnitPath) {
  const wide = annotatedRegions.find((item) => item.name === WIDE_REGION.name).instructions;
  const focused = wide.filter((insn) => insn.address >= REGION.vaStart && insn.address < REGION.vaEnd);
  const localStatusAccesses = findLocalStatusAccesses(wide);
  const ctx129Writes = findCtx129Writes(focused);
  const callsAndStrings = findCallsAndStringParsing(wide);
  const bufferReadCandidates = findBufferReads(focused);
  const localStatusSource = {
    initialization: [
      "0x7e900 mvn r2, #0x10c ; r2 = -0x10d",
      "0x7e904 mov r3, #0",
      "0x7e908 sub r1, fp, #0x28",
      "0x7e90c strb r3, [r1, r2] ; *(fp-0x135)=0",
    ],
    copyFromInputPointer: [
      "0x7e910 sub r3, fp, #0x134",
      "0x7e914 sub r3, r3, #1 ; r3 = fp-0x135",
      "0x7e918 mov r0, r3 ; destination",
      "0x7e91c ldr r1, [fp, #-0x30] ; source pointer candidate",
      "0x7e920 mov r2, #1 ; byte count",
      "0x7e924 bl #0xca5c ; likely memcpy/memmove-style helper",
      "0x7e928..0x7e930 increments fp-0x12c cursor by 1",
    ],
    conclusion:
      "localStatus is initialized to 0 and then overwritten by one byte copied from the pointer saved at fp-0x30. fp-0x30 is therefore the strongest response/input buffer pointer candidate for the status byte, but its absolute wire offset relative to the original frame is not recovered in this focused pass.",
  };

  return {
    generatedAt: new Date().toISOString(),
    siteUnitPath,
    regions: { focused: REGION, wide: WIDE_REGION },
    localStatusAccesses,
    ctx129Writes,
    writeConditions: [
      {
        status: "Success",
        localStatusValue: 0,
        ctxWriteVa: "0x7e954",
        conditionInstructions: [
          "0x7e934 mvn r3, #0x10c",
          "0x7e938 sub r2, fp, #0x28",
          "0x7e93c ldrb r3, [r2, r3] ; reads *(fp-0x135)",
          "0x7e940 cmp r3, #0",
          "0x7e944 bne 0x7e97c",
        ],
        upstream: "The branch is driven by localStatus byte at fp-0x135. This pass does not prove the original source of that byte.",
      },
      {
        status: "Fail",
        localStatusValue: 1,
        ctxWriteVa: "0x7e99c",
        conditionInstructions: [
          "0x7e97c mvn r3, #0x10c",
          "0x7e980 sub r1, fp, #0x28",
          "0x7e984 ldrb r3, [r1, r3] ; reads *(fp-0x135)",
          "0x7e988 cmp r3, #1",
          "0x7e98c bne 0x7e9d8",
        ],
        upstream: "The branch is driven by localStatus byte at fp-0x135. This pass does not prove the original source of that byte.",
      },
      {
        status: "UnRegister",
        localStatusValue: 2,
        ctxWriteVa: "0x7e9f8",
        conditionInstructions: [
          "0x7e9d8 mvn r3, #0x10c",
          "0x7e9dc sub r2, fp, #0x28",
          "0x7e9e0 ldrb r3, [r2, r3] ; reads *(fp-0x135)",
          "0x7e9e4 cmp r3, #2",
          "0x7e9e8 bne 0x7ea1c",
        ],
        upstream: "The branch is driven by localStatus byte at fp-0x135. This pass does not prove the original source of that byte.",
      },
    ],
    callRelationship: {
      functionBoundaryCandidate: {
        startVa: "0x7e7d0",
        endVa: "0x7f410",
        basis: "wider GetServiceAddr region around LogToDS return strings; exact symbol boundary still inferred from prologue/epilogue context.",
      },
      parseDataPath: "Previously confirmed Login flow includes 0x755bc -> 0x760a4 -> ParseData. The 0x7e800-0x7ea40 status handler itself does not call ParseData directly in this focused slice.",
      callsInWideRegion: callsAndStrings.calls,
      keyStringRefs: callsAndStrings.keyStringRefs,
    },
    responseBufferReads: {
      candidates: bufferReadCandidates,
      conclusion:
        "The focused status branch reads local stack byte fp-0x135. The byte is copied from the pointer saved at fp-0x30 with length 1, so fp-0x30 is a strong response/input buffer pointer candidate. The absolute wire offset inside the original frame is still unresolved.",
    },
    localStatusSource,
    stringReturnPath: {
      evidence: callsAndStrings.keyStringRefs,
      conclusion:
        "The region uses textual log strings and helper calls, but no confirmed strcmp/atoi/strtol/sscanf-style string return-code parser was identified in the focused slice. This remains more likely local binary/state handling than a proven SOAP/XML ACK body parser.",
    },
    ackGate: {
      canEnterStage14: false,
      reason:
        "ACK typeA, ACK body layout, and wire response success-code offset remain unconfirmed. localStatus 0/1/2 is internal state only.",
    },
  };
}

function writeLocalStatusReport(outDir, analysis) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `local-login-status-trace-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(analysis, null, 2)}\n`, "utf8");

  const md = [
    "# Local Login Status Trace",
    "",
    `Generated: ${analysis.generatedAt}`,
    "",
    "## Summary",
    "",
    analysis.responseBufferReads.conclusion,
    "",
    "## fp-0x135 Accesses",
    "",
    markdownTable(analysis.localStatusAccesses, [
      { title: "VA", value: (row) => row.vaHex },
      { title: "File Off", value: (row) => row.fileOffsetHex },
      { title: "Access", value: (row) => row.access },
      { title: "Match", value: (row) => row.matchKind },
      { title: "Instruction", value: (row) => row.instruction },
      { title: "Nearby Strings", value: (row) => row.nearbyStrings.map((item) => item.text).join("<br>") },
    ]),
    "",
    ...analysis.localStatusAccesses.flatMap((hit) => [
      `### ${hit.vaHex}`,
      "",
      insnTable(hit.context),
      "",
    ]),
    "## Write Conditions",
    "",
    ...analysis.writeConditions.flatMap((item) => [
      `### ${item.status} (${item.localStatusValue})`,
      "",
      `ctx+0x129 write: ${item.ctxWriteVa}`,
      "",
      item.conditionInstructions.map((line) => `- ${line}`).join("\n"),
      "",
      item.upstream,
      "",
    ]),
    "## Response Buffer Reads",
    "",
    "Local status source:",
    "",
    analysis.localStatusSource.initialization.map((line) => `- ${line}`).join("\n"),
    "",
    analysis.localStatusSource.copyFromInputPointer.map((line) => `- ${line}`).join("\n"),
    "",
    analysis.localStatusSource.conclusion,
    "",
    markdownTable(analysis.responseBufferReads.candidates, [
      { title: "VA", value: (row) => row.vaHex },
      { title: "Width", value: (row) => row.width },
      { title: "Instruction", value: (row) => row.instruction },
      { title: "Note", value: (row) => row.note },
    ]),
    "",
  ].join("\n");
  const mdPath = path.join(outDir, `local-login-status-trace-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function writeMainReport(outDir, analysis) {
  const report = {
    generatedAt: new Date().toISOString(),
    overview:
      "Supplemental Stage 13 analysis traced ctx+0x129 writes back to localStatus byte fp-0x135 comparisons, but did not recover the wire response field that sets localStatus.",
    localStatus: {
      exists: true,
      isLikelyLocalStatus: true,
      accessPattern: "mvn #0x10c produces -0x10d; with base fp-0x28, the effective address is fp-0x135.",
      accesses: analysis.localStatusAccesses.map((item) => ({
        vaHex: item.vaHex,
        fileOffsetHex: item.fileOffsetHex,
        instruction: item.instruction,
        access: item.access,
        matchKind: item.matchKind,
      })),
    },
    ctx129Writes: analysis.ctx129Writes,
    writeConditions: analysis.writeConditions,
    getServiceAddrLogToDs: analysis.callRelationship,
    parseDataPropagation: {
      conclusion:
        "The focused GetServiceAddr/LogToDS status handler does not directly call ParseData. Earlier Login flow still has confirmed 0x755bc -> 0x760a4 -> ParseData. The bridge from parsed response to fp-0x135 remains unresolved.",
    },
    responseBufferFieldCandidates: analysis.responseBufferReads,
    localStatusSource: analysis.localStatusSource,
    stringReturnCodePath: analysis.stringReturnPath,
    wireSuccessCodeOffset: null,
    ackBodyLayoutClues: [],
    stage14Gate: analysis.ackGate,
    safety: {
      udpAckSent: false,
      sendOneShotAckRun: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      autoAckAdded: false,
      sendableAckHexGenerated: false,
    },
  };

  const jsonPath = path.join(outDir, `login-status-source-analysis-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");

  const md = [
    "# Login Status Source Analysis",
    "",
    `Generated: ${report.generatedAt}`,
    "",
    "## Overview",
    "",
    report.overview,
    "",
    "## fp-0x135 / localStatus",
    "",
    `Exists: ${report.localStatus.exists}`,
    "",
    `Likely localStatus: ${report.localStatus.isLikelyLocalStatus}`,
    "",
    report.localStatus.accessPattern,
    "",
    "## Write 0 / 1 / 2 Conditions",
    "",
    ...report.writeConditions.flatMap((item) => [
      `### ${item.status}`,
      "",
      `localStatus value: ${item.localStatusValue}`,
      "",
      `ctx+0x129 write: ${item.ctxWriteVa}`,
      "",
      item.conditionInstructions.map((line) => `- ${line}`).join("\n"),
      "",
    ]),
    "## Response Buffer Field",
    "",
    report.responseBufferFieldCandidates.conclusion,
    "",
    "```text",
    report.localStatusSource.copyFromInputPointer.join("\n"),
    "```",
    "",
    "## ACK Body Layout",
    "",
    "No ACK typeA or body layout clue was confirmed in this supplement.",
    "",
    "## Stage 14 Gate",
    "",
    `Can enter Stage 14: ${report.stage14Gate.canEnterStage14}`,
    "",
    report.stage14Gate.reason,
    "",
    "不能进入可发送 ACK 构造，只能继续反汇编数据流。",
    "",
  ].join("\n");
  const mdPath = path.join(outDir, `login-status-source-analysis-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function updateAckModel(outDir, analysis) {
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure({
      unknowns: [
        "source of fp-0x135 localStatus from wire response",
        "wire response offset for internal success/fail/unregister status",
      ],
    }),
    supplementalStage13: {
      localStatus: "fp-0x135",
      localStatusSourceCandidate: "one byte copied from pointer saved at fp-0x30 via call 0xca5c; original frame offset not confirmed",
      internalStatusValues: { success: 0, fail: 1, unregister: 2 },
      ctx129Writes: {
        success: "0x7e954 writes 0",
        fail: "0x7e99c writes 1",
        unregister: "0x7e9f8 writes 2",
      },
      caveat: "Internal status values are copied from an input pointer candidate, but the original wire offset, ACK typeA, and ACK body layout are not confirmed.",
      stage14Gate: analysis.ackGate,
    },
  };
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `ack-structure-model-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(model, null, 2)}\n`, "utf8");
  const mdPath = path.join(outDir, `ack-structure-model-${DATE_STEM}.md`);
  fs.writeFileSync(
    mdPath,
    [
      "# ACK Structure Model",
      "",
      `Generated: ${model.generatedAt}`,
      "",
      `Status: ${model.status}`,
      "",
      `Reason: ${model.reason}`,
      "",
      `ackHex: ${model.ackHex}`,
      "",
      "## Confirmed Fields",
      "",
      "```json",
      JSON.stringify(model.confirmedFields, null, 2),
      "```",
      "",
      "## Supplemental Stage 13",
      "",
      "```json",
      JSON.stringify(model.supplementalStage13, null, 2),
      "```",
      "",
    ].join("\n"),
    "utf8",
  );
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const siteUnitPath = resolveSiteUnitPath(args);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const buffer = fs.readFileSync(siteUnitPath);
  const { sections } = parseElf(buffer);

  const stringByVa = new Map();
  for (const item of extractStrings(buffer)) {
    const mapped = fileOffsetToVa(sections, item.fileOffset);
    if (mapped.va !== null) stringByVa.set(mapped.va >>> 0, { ...item, va: mapped.va });
  }

  const mappedRegions = [mapRegion(sections, REGION), mapRegion(sections, WIDE_REGION)];
  const disasmRegions = runCapstone(buffer, mappedRegions).map((region) => ({
    name: region.name,
    instructions: annotate(region.instructions, buffer, sections, stringByVa),
  }));
  const analysis = buildAnalysis(disasmRegions, siteUnitPath);
  const localStatusPaths = writeLocalStatusReport(outDir, analysis);
  const mainPaths = writeMainReport(outDir, analysis);
  const ackModelPaths = updateAckModel(outDir, analysis);
  console.log(JSON.stringify({ localStatus: localStatusPaths, main: mainPaths, ackModel: ackModelPaths }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
