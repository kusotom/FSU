#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { modelAckStructure } = require("../fsu-ack-experiments/model-ack-structure");

const DATE_STEM = "2026-04-28";
const DEFAULT_FIRMWARE_ROOT = path.join(process.env.USERPROFILE || process.cwd(), "Desktop", "FSU");
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

const REGIONS = [
  { name: "GetServiceAddr/LogToDS wide", vaStart: 0x7e000, vaEnd: 0x7f420 },
  { name: "Status handler focused", vaStart: 0x7e800, vaEnd: 0x7ea40 },
  { name: "ParseData caller/Login inner", vaStart: 0x75500, vaEnd: 0x76100 },
  { name: "ParseData", vaStart: 0x760a4, vaEnd: 0x76a64 },
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
    input: JSON.stringify({ blobBase64: buffer.toString("base64"), regions }),
    encoding: "utf8",
    windowsHide: true,
    timeout: 60000,
    maxBuffer: 64 * 1024 * 1024,
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
    literalVaHex: hex(literalVa),
    literalFileOffsetHex: hex(mapped.fileOffset),
    value,
    valueHex: hex(value),
    string: string ? { text: string.text, vaHex: hex(string.va), fileOffsetHex: hex(string.fileOffset) } : null,
  };
}

function annotate(region, buffer, sections, stringByVa) {
  return {
    ...region,
    instructions: region.instructions.map((insn) => {
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
    }),
  };
}

function context(insns, index, radius = 40) {
  return insns.slice(Math.max(0, index - radius), Math.min(insns.length, index + radius + 1));
}

function accessKind(mnemonic) {
  const lower = mnemonic.toLowerCase();
  if (lower.startsWith("str")) return "write";
  if (lower.startsWith("ldr")) return "read";
  return "other";
}

function findFp30Accesses(insns, regionName) {
  const hits = [];
  for (let i = 0; i < insns.length; i += 1) {
    const insn = insns[i];
    const op = insn.opStr.toLowerCase();
    if (!/\[(?:fp|r11),\s*#-0x30\]/.test(op) && !/\[(?:fp|r11),\s*#-48\]/.test(op)) continue;
    const ctx = context(insns, i, 40);
    hits.push({
      va: insn.address,
      vaHex: insn.addressHex,
      fileOffsetHex: insn.fileOffsetHex,
      instruction: insn.text,
      access: accessKind(insn.mnemonic),
      region: regionName,
      context: ctx,
      nearbyStrings: ctx
        .filter((item) => item.pcrelLiteral && item.pcrelLiteral.string)
        .map((item) => ({ vaHex: item.addressHex, text: item.pcrelLiteral.string.text })),
    });
  }
  return hits;
}

function findRegisterSourceBefore(insns, index, register) {
  const writes = [];
  const escaped = register.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const destRegex = new RegExp(`^(?:${escaped})\\b`, "i");
  for (let i = index - 1; i >= 0 && i >= index - 80; i -= 1) {
    const insn = insns[i];
    const firstOp = insn.opStr.split(",")[0].trim();
    if (destRegex.test(firstOp) && /^(mov|ldr|add|sub|rsb|mvn)/i.test(insn.mnemonic)) {
      writes.push({
        vaHex: insn.addressHex,
        fileOffsetHex: insn.fileOffsetHex,
        instruction: insn.text,
      });
      if (writes.length >= 8) break;
    }
  }
  return writes;
}

function analyzeFirstWrite(fp30Accesses, wideInsns) {
  const writes = fp30Accesses.filter((hit) => hit.access === "write").sort((a, b) => a.va - b.va);
  const first = writes[0] || null;
  if (!first) return { firstWrite: null, conclusion: "No fp-0x30 write found in searched regions." };
  const index = wideInsns.findIndex((insn) => insn.addressHex === first.vaHex);
  const sourceMatch = first.instruction.match(/^str\s+(r\d+|ip|lr),\s*\[fp,\s*#-0x30\]/i);
  const sourceRegister = sourceMatch ? sourceMatch[1] : null;
  return {
    firstWrite: {
      ...first,
      sourceRegister,
      sourceTrace: sourceRegister && index >= 0 ? findRegisterSourceBefore(wideInsns, index, sourceRegister) : [],
    },
    conclusion:
      sourceRegister === "r1"
        ? "The first fp-0x30 write stores r1. In ARM calling convention this strongly suggests fp-0x30 is the function's second argument, unless r1 was reassigned before the prologue store."
        : "The first fp-0x30 write source is not proven to be an original argument.",
  };
}

function findCalls(insns) {
  return insns
    .filter((insn) => /^blx?$/.test(insn.mnemonic))
    .map((insn) => ({ vaHex: insn.addressHex, fileOffsetHex: insn.fileOffsetHex, instruction: insn.text }));
}

function findPotentialBodyOffsets(insns) {
  const patterns = [];
  for (const insn of insns) {
    if (!/^(add|sub|ldr|ldrb|ldrh|str|strb|strh)$/i.test(insn.mnemonic)) continue;
    const op = insn.opStr.toLowerCase();
    if (/#0x18\b|#24\b|#0x16\b|#22\b|#0x14\b|#20\b|#0x22\b|#34\b|#0x24\b|#36\b/.test(op)) {
      patterns.push({
        vaHex: insn.addressHex,
        fileOffsetHex: insn.fileOffsetHex,
        instruction: insn.text,
      });
    }
  }
  return patterns;
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

function buildAnalysis(regions, siteUnitPath) {
  const wide = regions.find((item) => item.name === "GetServiceAddr/LogToDS wide").instructions;
  const focused = regions.find((item) => item.name === "Status handler focused").instructions;
  const parseCaller = regions.find((item) => item.name === "ParseData caller/Login inner").instructions;
  const parseData = regions.find((item) => item.name === "ParseData").instructions;
  const fp30Accesses = [
    ...findFp30Accesses(wide, "GetServiceAddr/LogToDS wide"),
    ...findFp30Accesses(parseCaller, "ParseData caller/Login inner"),
  ];
  const firstWrite = analyzeFirstWrite(fp30Accesses, wide);
  const statusHandlerFp30Accesses = fp30Accesses.filter((hit) => hit.va >= 0x7e804 && hit.va < 0x7f420);
  const statusHandlerFirstWrite = analyzeFirstWrite(statusHandlerFp30Accesses, wide);
  const localStatusRead = {
    sourcePointerRead: "0x7e91c ldr r1, [fp, #-0x30]",
    copy: "0x7e918 r0=fp-0x135; 0x7e920 r2=1; 0x7e924 bl 0xca5c",
    pseudoCode: "localStatus = responsePtr[0];",
  };
  const parseDataDispatchToStatusHandler = {
    dispatchByte: {
      source: "0x76358 ldr r3, [fp, #-0x30]; 0x7635c ldrb r3, [r3, #6]",
      frameOffset: 6,
      matchedValue: 0x47,
      branch: "0x763c4 cmp r3, #0x47; 0x763c8 beq 0x76410",
    },
    call: [
      "0x76410 ldr r3, [fp, #0x18] ; original frame buffer parameter",
      "0x76414 add r2, r3, #0x18 ; responsePtr = frame + 0x18",
      "0x76420 ldr r0, [fp, #-0x2c] ; ctx",
      "0x76424 mov r1, r2",
      "0x76428 bl #0x7e804 ; status handler",
    ],
    conclusion:
      "For dispatch byte frame[6] == 0x47, ParseData calls the status handler with r1 = frame + 0x18. Therefore localStatus in that handler is frame[0x18], equivalently body[0] under the confirmed length/header model.",
  };
  return {
    generatedAt: new Date().toISOString(),
    siteUnitPath,
    fp30Accesses,
    firstWrite,
    statusHandlerFirstWrite,
    localStatusRead,
    functionCandidate: {
      region: "0x7e000-0x7f420",
      likelyName: "GetServiceAddr / LogToDS return handler",
      callingConventionInference:
        "In status handler 0x7e804, fp-0x2c and fp-0x30 are saved immediately from r0/r1. fp-0x30 behaves as the source pointer consumed one byte at a time.",
    },
    parseDataAssociation: {
      parseDataDirectReturnPointer: false,
      dispatchToStatusHandler: parseDataDispatchToStatusHandler,
      evidence:
        "ParseData does not return the pointer directly; it passes frame+0x18 as r1 into status handler 0x7e804 when frame[6] == 0x47.",
      parseCallerBodyOffsetPatterns: findPotentialBodyOffsets(parseCaller),
      parseDataBodyOffsetPatterns: findPotentialBodyOffsets(parseData),
    },
    getServiceAddrPseudoCode: [
      "getServiceAddrOrLogToDs(ctx, responsePtr, unknown...) {",
      "  localStatus = 0;",
      "  localStatus = responsePtr[0]; // responsePtr is fp-0x30; absolute frame/body offset unknown",
      "  cursor += 1;",
      "  if (localStatus == 0) { ctx[0x129] = 0; log Success; }",
      "  else if (localStatus == 1) { ctx[0x129] = 1; log Fail; }",
      "  else if (localStatus == 2) { ctx[0x129] = 2; log UnRegister; }",
      "  ...",
      "}",
    ],
    calls: findCalls(wide),
    ackCandidates: {
      successCode: [
        {
          value: 0,
          meaning: "Success",
          location: "frame[0x18] / body[0] on ParseData dispatch byte frame[6] == 0x47",
          confidence: "medium-high for this handler path; full ACK frame type/body still incomplete",
        },
      ],
      typeA: [
        {
          field: "frame[6]",
          value: "0x47",
          meaning: "ParseData dispatches to status handler 0x7e804",
          confidence: "partial only; full typeA bytes[4..7] are not recovered",
        },
      ],
      bodyLayout: [
        {
          field: "body[0]",
          frameOffset: "0x18",
          meaning: "internal login status byte: 0 Success, 1 Fail, 2 UnRegister",
          confidence: "medium-high for handler path; remaining body fields unknown",
        },
      ],
    },
    stage14Gate: {
      canEnterStage14: false,
      reason:
        "success code offset is now tied to frame[0x18]/body[0] for dispatch byte frame[6]==0x47, but full ACK typeA bytes[4..7], complete body layout, and sequence strategy are not confirmed.",
    },
  };
}

function writePointerTrace(outDir, analysis) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `response-buffer-pointer-trace-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(analysis, null, 2)}\n`, "utf8");

  const md = [
    "# Response Buffer Pointer Trace",
    "",
    `Generated: ${analysis.generatedAt}`,
    "",
    "## Summary",
    "",
    analysis.firstWrite.conclusion,
    "",
    "## fp-0x30 Accesses",
    "",
    markdownTable(analysis.fp30Accesses, [
      { title: "VA", value: (row) => row.vaHex },
      { title: "File Off", value: (row) => row.fileOffsetHex },
      { title: "Region", value: (row) => row.region },
      { title: "Access", value: (row) => row.access },
      { title: "Instruction", value: (row) => row.instruction },
      { title: "Nearby Strings", value: (row) => row.nearbyStrings.map((item) => item.text).join("<br>") },
    ]),
    "",
    ...analysis.fp30Accesses.flatMap((hit) => [
      `### ${hit.vaHex}`,
      "",
      insnTable(hit.context),
      "",
    ]),
  ].join("\n");
  const mdPath = path.join(outDir, `response-buffer-pointer-trace-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function writeMainReport(outDir, analysis) {
  const report = {
    generatedAt: new Date().toISOString(),
    overview:
      "fp-0x30 is traced as the response pointer argument consumed by the GetServiceAddr/LogToDS status handler. localStatus is responsePtr[0], but responsePtr's absolute relation to the raw frame/body remains unresolved.",
    fp30Accesses: analysis.fp30Accesses.map((hit) => ({
      vaHex: hit.vaHex,
      fileOffsetHex: hit.fileOffsetHex,
      access: hit.access,
      region: hit.region,
      instruction: hit.instruction,
    })),
    firstWrite: analysis.firstWrite,
    statusHandlerFirstWrite: analysis.statusHandlerFirstWrite,
    localStatusConfirmation: analysis.localStatusRead,
    responsePtrOffsetInference: {
      responsePtrRelativeStatusOffset: 0,
      originalFrameOffset: 0x18,
      bodyOffset: 0,
      confidence: "supported for ParseData dispatch byte frame[6] == 0x47",
    },
    parseDataAssociation: analysis.parseDataAssociation,
    getServiceAddrPseudoCode: analysis.getServiceAddrPseudoCode,
    ackSuccessCodeOffsetCandidate: analysis.ackCandidates.successCode,
    ackTypeBodyClues: {
      typeA: analysis.ackCandidates.typeA,
      bodyLayout: analysis.ackCandidates.bodyLayout,
      conclusion:
        "A partial type clue was found: frame[6] == 0x47 dispatches to the login status handler. A minimal body clue was found: body[0] carries the internal status byte. Full typeA bytes[4..7] and remaining body layout are still unresolved.",
    },
    stage14Gate: analysis.stage14Gate,
    safety: {
      udpAckSent: false,
      sendOneShotAckRun: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      autoAckAdded: false,
      sendableAckHexGenerated: false,
    },
  };
  const jsonPath = path.join(outDir, `response-status-offset-analysis-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  const md = [
    "# Response Status Offset Analysis",
    "",
    `Generated: ${report.generatedAt}`,
    "",
    "## Overview",
    "",
    report.overview,
    "",
    "## fp-0x30 First Write",
    "",
    report.firstWrite.conclusion,
    "",
    "## Status Handler fp-0x30 First Write",
    "",
    report.statusHandlerFirstWrite.conclusion,
    "",
    "## localStatus Offset",
    "",
    `localStatus = responsePtr[0] is supported. original frame offset: ${report.responsePtrOffsetInference.originalFrameOffset}`,
    "",
    "## Pseudocode",
    "",
    "```c",
    report.getServiceAddrPseudoCode.join("\n"),
    "```",
    "",
    "## ACK Gate",
    "",
    `Can enter Stage 14: ${report.stage14Gate.canEnterStage14}`,
    "",
    report.stage14Gate.reason,
    "",
    "不能进入可发送 ACK 构造，只能继续反汇编数据流。",
    "",
  ].join("\n");
  const mdPath = path.join(outDir, `response-status-offset-analysis-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function updateAckModel(outDir, analysis) {
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure({
      candidateFields: {
        typeA: analysis.ackCandidates.typeA,
        body: analysis.ackCandidates.bodyLayout,
        successCode: analysis.ackCandidates.successCode,
      },
      unknowns: ["absolute frame/body offset for responsePtr", "ACK typeA", "ACK body layout"],
      supplementalStage13: {
        responsePtr: "fp-0x30",
        responsePtrSource: analysis.statusHandlerFirstWrite.conclusion,
        localStatusLocation: "responsePtr[0]",
        originalFrameOffset: "0x18",
        bodyOffset: 0,
        dispatchByte: "frame[6] == 0x47",
        stage14Gate: analysis.stage14Gate,
      },
    }),
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
      "## Candidate Fields",
      "",
      "```json",
      JSON.stringify(model.candidateFields, null, 2),
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
  const mappedRegions = REGIONS.map((region) => mapRegion(sections, region));
  const regions = runCapstone(buffer, mappedRegions).map((region) => annotate(region, buffer, sections, stringByVa));
  const analysis = buildAnalysis(regions, siteUnitPath);
  const tracePaths = writePointerTrace(outDir, analysis);
  const mainPaths = writeMainReport(outDir, analysis);
  const ackModelPaths = updateAckModel(outDir, analysis);
  console.log(JSON.stringify({ trace: tracePaths, main: mainPaths, ackModel: ackModelPaths }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
