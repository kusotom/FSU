#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { modelAckStructure } = require("../fsu-ack-experiments/model-ack-structure");

const DATE_STEM = "2026-04-28";
const DEFAULT_REVERSE_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

const INTERESTING_FRAME_OFFSETS = new Set([4, 5, 6, 7, 8, 20, 21, 22, 23, 24]);

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

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function hex(value) {
  if (value === null || value === undefined) return null;
  return `0x${Number(value).toString(16)}`;
}

function parseImmediate(text) {
  if (!text) return null;
  const value = String(text).trim().toLowerCase();
  if (value.startsWith("-0x")) return -Number.parseInt(value.slice(3), 16);
  if (value.startsWith("0x")) return Number.parseInt(value.slice(2), 16);
  return Number.parseInt(value, 10);
}

function loadRegions(reverseDir) {
  const disasm = readJson(path.join(reverseDir, `siteunit-disasm-regions-${DATE_STEM}.json`));
  const pointer = readJson(path.join(reverseDir, `response-buffer-pointer-trace-${DATE_STEM}.json`));
  const parseData = disasm.regions.find((region) => region.name === "ParseData");
  if (!parseData) throw new Error("ParseData region missing");
  return { parseData: parseData.instructions, pointer };
}

function formatInsn(insn) {
  return {
    vaHex: insn.addressHex,
    fileOffsetHex: insn.fileOffsetHex,
    instruction: `${insn.mnemonic} ${insn.opStr}`,
    literal: insn.pcrelLiteral ? (insn.pcrelLiteral.string ? insn.pcrelLiteral.string.text : insn.pcrelLiteral.valueHex) : null,
  };
}

function context(insns, index, radius = 8) {
  return insns.slice(Math.max(0, index - radius), Math.min(insns.length, index + radius + 1)).map(formatInsn);
}

function findNextCompareAndBranch(insns, index) {
  const result = { compare: null, branch: null };
  for (let i = index + 1; i < Math.min(insns.length, index + 8); i += 1) {
    const insn = insns[i];
    if (!result.compare && /^cmp$/i.test(insn.mnemonic)) {
      const imm = insn.opStr.match(/#(-?0x[0-9a-f]+|-?\d+)/i);
      result.compare = {
        ...formatInsn(insn),
        constant: imm ? parseImmediate(imm[1]) : null,
        constantHex: imm ? hex(parseImmediate(imm[1])) : null,
      };
      continue;
    }
    if (result.compare && /^b[a-z]*$/i.test(insn.mnemonic)) {
      result.branch = formatInsn(insn);
      break;
    }
  }
  return result;
}

function findFrameFixedOffsetReads(parseData) {
  const reads = [];
  for (let i = 0; i < parseData.length; i += 1) {
    const insn = parseData[i];
    const text = `${insn.mnemonic} ${insn.opStr}`;
    const match = text.match(/^(ldr|ldrb|ldrh)\s+[^,]+,\s*\[r\d+,\s*#(0x[0-9a-f]+|\d+)\]/i);
    if (!match) continue;
    const offset = parseImmediate(match[2]);
    if (!INTERESTING_FRAME_OFFSETS.has(offset)) continue;

    const prev = parseData.slice(Math.max(0, i - 4), i);
    const baseLooksFrame = prev.some((item) => /\[fp,\s*#0x18\]|\[fp,\s*#-0x30\]/i.test(item.opStr));
    if (!baseLooksFrame) continue;

    const cmpBranch = findNextCompareAndBranch(parseData, i);
    reads.push({
      vaHex: insn.addressHex,
      fileOffsetHex: insn.fileOffsetHex,
      width: match[1].toLowerCase() === "ldrb" ? "byte" : match[1].toLowerCase() === "ldrh" ? "halfword" : "word",
      frameOffset: offset,
      frameOffsetHex: hex(offset),
      instruction: text,
      compare: cmpBranch.compare,
      branch: cmpBranch.branch,
      context: context(parseData, i, 8),
      possibleMeaning: offset === 6 ? "command dispatch byte" : offset === 20 ? "lengthLE low/halfword region" : offset === 22 ? "checksumLE region" : "fixed header/type/body field candidate",
    });
  }
  return reads;
}

function parseDataDispatch(parseData) {
  const idx = parseData.findIndex((insn) => insn.addressHex === "0x7635c");
  const dispatchComparisons = [];
  for (let i = idx; i >= 0 && i < parseData.length && parseData[i].address < 0x76410; i += 1) {
    const insn = parseData[i];
    if (/^cmp$/i.test(insn.mnemonic)) {
      const imm = insn.opStr.match(/#(-?0x[0-9a-f]+|-?\d+)/i);
      const nextBranch = parseData.slice(i + 1, i + 4).find((item) => /^b[a-z]*$/i.test(item.mnemonic));
      dispatchComparisons.push({
        ...formatInsn(insn),
        constant: imm ? parseImmediate(imm[1]) : null,
        constantHex: imm ? hex(parseImmediate(imm[1])) : null,
        branch: nextBranch ? formatInsn(nextBranch) : null,
      });
    }
  }
  return {
    sourceRead: {
      vaHex: "0x7635c",
      instruction: "ldrb r3, [frame, #6]",
      frameOffset: 6,
    },
    comparisons: dispatchComparisons,
    loginStatusBranch: {
      condition: "frame[6] == 0x47",
      target: "0x76410",
      callSequence: [
        "0x76410 ldr r3, [fp, #0x18] ; frame",
        "0x76414 add r2, r3, #0x18 ; responsePtr = frame + 24",
        "0x76420 ldr r0, [fp, #-0x2c] ; ctx",
        "0x76424 mov r1, r2",
        "0x76428 bl #0x7e804",
      ],
    },
  };
}

function bodyLayout(pointerReport) {
  const focused = pointerReport.fp30Accesses.filter((hit) => hit.vaHex === "0x7e818" || hit.vaHex === "0x7e91c" || hit.vaHex === "0x7ea24" || hit.vaHex === "0x7ea84" || hit.vaHex === "0x7eab4" || hit.vaHex === "0x7ead4");
  const statusContext = pointerReport.fp30Accesses.find((hit) => hit.vaHex === "0x7e91c");
  return {
    handlerVa: "0x7e804",
    responsePtrArgument: "r1 saved at [fp, #-0x30] by 0x7e818",
    reads: focused.map((hit) => ({
      vaHex: hit.vaHex,
      fileOffsetHex: hit.fileOffsetHex,
      access: hit.access,
      instruction: hit.instruction,
      note:
        hit.vaHex === "0x7e91c"
          ? "source pointer for one-byte copy into fp-0x135; establishes body[0] status"
          : "later responsePtr read; used for cursor-based parsing/copying, exact field role not fully recovered",
    })),
    confirmedFields: [
      {
        field: "body[0]",
        frameOffset: 24,
        valueMeanings: { 0: "Success", 1: "Fail", 2: "UnRegister" },
        evidence: [
          "0x76414 passes frame+0x18 to 0x7e804",
          "0x7e91c loads responsePtr",
          "0x7e918/0x7e920/0x7e924 copies one byte to fp-0x135",
          "0x7e93c/0x7e984/0x7e9e0 compare fp-0x135 with 0/1/2",
        ],
      },
    ],
    additionalFieldCandidates: [
      {
        field: "body[1..2]",
        evidence: "0x7ea24..0x7ea3c copies 2 bytes from responsePtr + cursor after cursor is incremented past body[0]",
        possibleMeaning: "count/length field used by following loop",
        confidence: "medium",
      },
      {
        field: "body[3]",
        evidence: "0x7ea84..0x7ea94 reads responsePtr[cursor] after body[1..2]",
        possibleMeaning: "per-entry field, possibly type/id",
        confidence: "low-medium",
      },
      {
        field: "body[4]",
        evidence: "0x7eab4..0x7eac4 reads next responsePtr[cursor] and later uses it as memcpy length at 0x7eaf4",
        possibleMeaning: "string/field length",
        confidence: "medium",
      },
      {
        field: "body[5..]",
        evidence: "0x7ead4..0x7eaf8 copies variable bytes from responsePtr + cursor into a local buffer",
        possibleMeaning: "variable string/payload, likely service address related",
        confidence: "medium",
      },
    ],
    statusDecisionMinBodyLength: {
      value: 1,
      confidence: "high for deciding ctx+0x129 status",
    },
    completeSuccessBodyLength: {
      value: null,
      confidence: "not closed; success/unregister paths parse fields beyond body[0]",
    },
    handlerOnlyReadsBody0: false,
  };
}

function sequenceUsage(parseData) {
  const seqReads = [];
  for (let i = 0; i < parseData.length; i += 1) {
    const text = `${parseData[i].mnemonic} ${parseData[i].opStr}`;
    if (/\[(r\d+),\s*#2\]|\[(r\d+),\s*#3\]/i.test(text)) {
      seqReads.push({ ...formatInsn(parseData[i]), context: context(parseData, i, 5) });
    }
  }
  return {
    reads: seqReads,
    conclusion:
      seqReads.length === 0
        ? "No frame[2..3] seqLE read was identified in the ParseData dispatch/status path. There is no evidence yet that seqLE participates in login ACK validation."
        : "ParseData reads frame[2..3] in other dispatch branches and copies seqLE to an output argument at function exit. No compare against an expected request sequence was identified for the frame[6] == 0x47 login-status branch.",
    strategy: "unknown",
  };
}

function writeJsonMd(outDir, stem, title, data, lines) {
  const jsonPath = path.join(outDir, `${stem}-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  const mdPath = path.join(outDir, `${stem}-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, [`# ${title}`, "", ...lines, ""].join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function writeBodyOffsetCorrection(outDir) {
  const lines = [
    "ParseData confirms checksum and body are distinct:",
    "",
    "- `checksumOffset = 22` (`frame[0x16..0x17]`)",
    "- `bodyOffset = 24` (`frame + 0x18`)",
    "- `lengthLE = frame[20..21] = totalLength - 24`",
    "- `bodyLength = lengthLE`",
    "",
    "Earlier `bodyOffset=22` included checksum bytes in the body view. This has been corrected for offline parsing/modeling.",
  ];
  const mdPath = path.join(outDir, `body-offset-correction-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, [`# Body Offset Correction`, "", ...lines, ""].join("\n"), "utf8");
  return { mdPath };
}

function updateAckModel(outDir, analysis) {
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure({
      candidateFields: {
        typeA: analysis.typeA.candidates,
        body: analysis.bodyLayout.confirmedFields,
        successCode: [
          {
            value: 0,
            meaning: "Success",
            location: "frame[24] / body[0]",
            confidence: "confirmed for frame[6] == 0x47 handler path",
          },
        ],
        statusDecisionMinBodyLength: analysis.bodyLayout.statusDecisionMinBodyLength,
        completeSuccessBodyLength: analysis.bodyLayout.completeSuccessBodyLength,
        minimalTotalLength: null,
      },
      supplementalStage13: {
        checksumOffset: 22,
        bodyOffset: 24,
        bodyLengthFormula: "lengthLE",
        dispatchByte: "frame[6] == 0x47",
        statusByte: "frame[24] / body[0]",
        success: 0,
        fail: 1,
        unregister: 2,
        seqStrategy: analysis.seq.strategy,
        stage14Gate: analysis.stage14Gate,
      },
    }),
  };
  model.confirmedFields.checksumOffset = { offset: 22 };
  model.confirmedFields.bodyOffset = { offset: 24 };
  model.confirmedFields.statusByte = { offset: 24, bodyOffset: 0, meanings: { 0: "Success", 1: "Fail", 2: "UnRegister" } };
  model.confirmedFields.dispatchByte = { offset: 6, value: "0x47", caveat: "only one dispatch byte, not full typeA" };
  const jsonPath = path.join(outDir, `ack-structure-model-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(model, null, 2)}\n`, "utf8");
  const mdPath = path.join(outDir, `ack-structure-model-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, ["# ACK Structure Model", "", "```json", JSON.stringify(model, null, 2), "```", ""].join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_REVERSE_DIR);
  fs.mkdirSync(outDir, { recursive: true });
  const { parseData, pointer } = loadRegions(outDir);

  const fixedReads = findFrameFixedOffsetReads(parseData);
  const dispatch = parseDataDispatch(parseData);
  const body = bodyLayout(pointer);
  const seq = sequenceUsage(parseData);
  const typeA = {
    fullTypeARecovered: false,
    frame4Compared: fixedReads.some((read) => read.frameOffset === 4 && read.compare),
    frame5Compared: fixedReads.some((read) => read.frameOffset === 5 && read.compare),
    frame6Compared: true,
    frame7Compared: fixedReads.some((read) => read.frameOffset === 7 && read.compare),
    candidates: [
      {
        value: "unknown unknown 47 unknown",
        evidence: "ParseData dispatch reads and compares frame[6] with 0x47; no full bytes[4..7] comparison recovered.",
        confidence: "partial",
      },
    ],
  };

  const stage14Gate = {
    canEnterStage14: false,
    reason:
      "bodyOffset/status byte are confirmed for the handler path, but full ACK typeA[4..7], full body layout, and seq strategy are not confirmed.",
  };

  const commandDispatchReport = { generatedAt: new Date().toISOString(), fixedReads, dispatch, typeA, seq };
  const bodyReport = { generatedAt: new Date().toISOString(), bodyLayout: body };
  const mainReport = {
    generatedAt: new Date().toISOString(),
    overview:
      "ParseData dispatch for login status uses frame[6] == 0x47 and passes frame+0x18 to handler 0x7e804. body[0] is the login status byte. Full typeA and full body layout remain incomplete.",
    commandDispatch: commandDispatchReport,
    typeA,
    bodyLayout: body,
    bodyOffsetCorrection: { checksumOffset: 22, bodyOffset: 24, lengthLE: "totalLength - 24", bodyLength: "lengthLE" },
    seq,
    ackModel: updateAckModel(outDir, { typeA, bodyLayout: body, seq, stage14Gate }),
    stage14Gate,
  };

  const dispatchPaths = writeJsonMd(outDir, "parse-data-command-dispatch", "ParseData Command Dispatch", commandDispatchReport, [
    "## Summary",
    "",
    "ParseData reads `frame[6]` and dispatches `0x47` to handler `0x7e804` with `r1 = frame + 0x18`.",
    "",
    "Full `typeA[4..7]` was not recovered; only `frame[6] == 0x47` is confirmed for this branch.",
  ]);
  const bodyPaths = writeJsonMd(outDir, "login-status-handler-body-layout", "Login Status Handler Body Layout", bodyReport, [
    "## Summary",
    "",
    "`0x7e804` reads `responsePtr[0]` into `fp-0x135`; since ParseData passes `frame+0x18`, this is `frame[24] / body[0]`.",
    "",
    "The handler does not only read body[0]. Status decision needs body[0], but Success/UnRegister paths parse additional fields beginning at body[1].",
  ]);
  const correctionPath = writeBodyOffsetCorrection(outDir);
  const mainPaths = writeJsonMd(outDir, "login-ack-type-body-analysis", "Login ACK Type Body Analysis", mainReport, [
    "## Summary",
    "",
    mainReport.overview,
    "",
    "## Stage 14 Gate",
    "",
    `Can enter Stage 14: ${stage14Gate.canEnterStage14}`,
    "",
    stage14Gate.reason,
    "",
    "不能进入可发送 ACK 构造，只能继续反汇编数据流。",
  ]);
  console.log(JSON.stringify({ dispatch: dispatchPaths, body: bodyPaths, correction: correctionPath, main: mainPaths, ackModel: mainReport.ackModel }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
