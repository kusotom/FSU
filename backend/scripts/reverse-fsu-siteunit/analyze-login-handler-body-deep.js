#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { modelAckStructure } = require("../fsu-ack-experiments/model-ack-structure");

const DATE_STEM = "2026-04-28";
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");
const DEFAULT_SITEUNIT = path.join(process.env.USERPROFILE || process.cwd(), "Desktop", "FSU", "home", "idu", "SiteUnit");
const TEXT_VA_DELTA = 0x8000;

const PY_DISASM = String.raw`
import json
import sys
from pathlib import Path
from capstone import *

siteunit, va_start_s, va_end_s = sys.argv[1:4]
va_start = int(va_start_s, 16)
va_end = int(va_end_s, 16)
blob = Path(siteunit).read_bytes()
off_start = va_start - 0x8000
off_end = va_end - 0x8000
md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
out = []
for insn in md.disasm(blob[off_start:off_end], va_start):
    out.append({
        "va": insn.address,
        "vaHex": hex(insn.address),
        "fileOffset": insn.address - 0x8000,
        "fileOffsetHex": hex(insn.address - 0x8000),
        "bytes": insn.bytes.hex(),
        "mnemonic": insn.mnemonic,
        "opStr": insn.op_str,
        "text": f"{insn.mnemonic} {insn.op_str}".strip(),
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
  if (value === null || value === undefined) return null;
  return `0x${Number(value).toString(16)}`;
}

function readJsonMaybe(filePath) {
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function runDisasm(siteUnitPath, vaStart, vaEnd) {
  const result = spawnSync("python", ["-c", PY_DISASM, siteUnitPath, hex(vaStart), hex(vaEnd)], {
    encoding: "utf8",
    windowsHide: true,
    timeout: 30000,
  });
  if (result.error || result.status !== 0) {
    throw new Error(result.error ? result.error.message : result.stderr);
  }
  return JSON.parse(result.stdout);
}

function contextAround(instructions, vaHex, count = 8) {
  const index = instructions.findIndex((insn) => insn.vaHex === vaHex);
  if (index < 0) return [];
  return instructions.slice(Math.max(0, index - count), Math.min(instructions.length, index + count + 1));
}

function makeBodyReadMap(instructions) {
  return [
    {
      field: "body[0]",
      frameOffset: 24,
      readWidth: "byte copied through helper 0xca5c",
      instructionVA: "0x7e91c/0x7e924",
      path: "common status decision",
      usage: "copied to localStatus fp-0x135, then compared with 0, 1, 2",
      confidence: "high",
      evidence: contextAround(instructions, "0x7e91c", 5),
    },
    {
      field: "body[1..2]",
      frameOffset: "25..26",
      readWidth: "2 bytes copied then read as uint16",
      instructionVA: "0x7ea24/0x7ea3c/0x7ea5c",
      path: "after status logging; success/unregister also reach this common parser",
      usage: "copied from body+cursor into local halfword; used as loop upper bound at 0x7ea64",
      confidence: "high for count/loop bound, medium for semantic meaning",
      evidence: contextAround(instructions, "0x7ea24", 10).concat(contextAround(instructions, "0x7ea5c", 6)),
    },
    {
      field: "body[3]",
      frameOffset: 27,
      readWidth: "byte",
      instructionVA: "0x7ea84/0x7ea8c",
      path: "per-entry loop",
      usage: "copied to local entry type/index byte; later drives a switch table at 0x7ec4c",
      confidence: "medium",
      evidence: contextAround(instructions, "0x7ea84", 8).concat(contextAround(instructions, "0x7ec4c", 5)),
    },
    {
      field: "body[4]",
      frameOffset: 28,
      readWidth: "byte",
      instructionVA: "0x7eab4/0x7eabc",
      path: "per-entry loop",
      usage: "copied to local length byte; used as copy length at 0x7eaf4 and for cursor advance at 0x7eb34",
      confidence: "high",
      evidence: contextAround(instructions, "0x7eab4", 8).concat(contextAround(instructions, "0x7eaf4", 8)),
    },
    {
      field: "body[5..5+len-1]",
      frameOffset: "29..",
      readWidth: "variable bytes",
      instructionVA: "0x7ead4/0x7eaf8",
      path: "per-entry loop",
      usage: "copied into local buffer fp-0xe8; null-terminated; formatted and then parsed into typed ctx fields",
      confidence: "medium-high",
      evidence: contextAround(instructions, "0x7ead4", 12).concat(contextAround(instructions, "0x7eb20", 8)),
    },
  ];
}

function makeVariableArea() {
  return {
    variableAreaOffset: 3,
    entryLayout: {
      typeOrFieldId: { offset: "cursor", width: 1, firstBodyOffset: 3 },
      length: { offset: "cursor + 1", width: 1, firstBodyOffset: 4 },
      data: { offset: "cursor + 2", width: "length", firstBodyOffset: 5 },
    },
    cursorRules: [
      "cursor starts at 1 after body[0] status is consumed",
      "body[cursor..cursor+1] is copied as a uint16 loop count; cursor += 2",
      "loopIndex starts at 0 and repeats while loopIndex < body[1..2]",
      "per entry: type = body[cursor]; cursor += 1",
      "per entry: len = body[cursor]; cursor += 1",
      "per entry: data = body[cursor..cursor+len-1]; cursor += len",
    ],
    destinations: [
      "entry data is copied to local string buffer fp-0xe8 and null-terminated",
      "the string is formatted into another local string buffer with format %s",
      "the field id selects one of up to 10 switch-table cases",
      "switch cases write parsed values into ctx fields around ctx + currentIndex*0x80 + 0x13c..0x190",
    ],
    possibleMeaning:
      "a typed list of service/config fields; the repeated ctx offsets and string-to-number conversions make service address/IP/port style data plausible, but exact field names are not closed",
    confidence: "medium",
  };
}

function makeFieldAnalyses() {
  return {
    body1to2: {
      field: "body[1..2]",
      readAs: "uint16LE on this ARM LSB target after 2-byte copy",
      usedFor: "entry count / loop upper bound",
      alternatives: [
        { meaning: "entry count", confidence: "high", reason: "compared against loopIndex fp-0x130 before each entry parse" },
        { meaning: "subsequent variable area length", confidence: "low", reason: "the code compares it to an entry counter, not to cursor" },
        { meaning: "sequence or error code", confidence: "low", reason: "not propagated as result code and not compared with constants" },
      ],
      evidence: ["0x7ea24..0x7ea3c copies two bytes", "0x7ea5c ldrh", "0x7ea64 cmp loopIndex, copiedHalfword"],
    },
    body3: {
      field: "body[3]",
      usedFor: "per-entry field id / type byte",
      confidence: "medium",
      evidence: ["0x7ea84..0x7ea94 reads one byte", "0x7ec4c bounds it with <= 9 and dispatches through a switch table"],
    },
    body4: {
      field: "body[4]",
      usedFor: "per-entry data length byte",
      confidence: "high",
      evidence: [
        "0x7eab4..0x7eac4 reads one byte",
        "0x7eae8 loads that byte as r2 for copy at 0x7eaf8",
        "0x7eb30..0x7eb38 adds that byte to cursor",
      ],
    },
  };
}

function makeCallMap(instructions) {
  const callCandidates = {
    "0xca5c": "memcpy-like copy helper",
    "0xcc84": "memset-like zero fill helper",
    "0xcdbc": "sprintf/format-like helper",
    "0xcd50": "string search/parse helper candidate",
    "0xc1f8": "string append/assign helper candidate",
    "0xcbc4": "numeric conversion candidate",
    "0xcb94": "string buffer reset/resize candidate",
    "0xcc3c": "uint16 endian/format conversion candidate",
    "0xc93c": "string-to-number conversion candidate",
    "0xc5ac": "string c_str/length accessor candidate",
    "0xc678": "local string destructor/reset helper",
    "0x18304": "logging helper",
  };
  return instructions
    .filter((insn) => insn.mnemonic === "bl" || insn.mnemonic === "blx")
    .map((insn) => {
      const target = (insn.opStr.match(/0x[0-9a-f]+/i) || [null])[0];
      return {
        callVA: insn.vaHex,
        target,
        targetCandidate: callCandidates[target] || "unknown",
        relatedToBodyCursor:
          ["0x7e924", "0x7ea3c", "0x7eaf8", "0x7eb54", "0x7eb64", "0x7ebf8"].includes(insn.vaHex) ||
          (insn.va >= 0x7ec80 && insn.va <= 0x7f304),
      };
    });
}

function makePseudoCode() {
  return [
    "int loginStatusHandler(ctx, body /* r1 */, unknown r2, unknown r3) {",
    "  cursor = 0;",
    "  localStatus = body[cursor];",
    "  cursor += 1;",
    "  if (localStatus == 0) {",
    "    ctx[0x129] = 0;",
    "    log(\"LogToDS return Success\");",
    "  } else if (localStatus == 1) {",
    "    ctx[0x129] = 1;",
    "    log(\"LogToDS return Fail\");",
    "    return 0;",
    "  } else if (localStatus == 2) {",
    "    ctx[0x129] = 2;",
    "    log(\"LogToDS return UnRegister\");",
    "  }",
    "  entryCount = uint16_unknown_endian(body + cursor);",
    "  cursor += 2;",
    "  for (i = 0; i < entryCount; i++) {",
    "    fieldId = body[cursor++];",
    "    copyLength = body[cursor++];",
    "    value = bytes_to_string(body + cursor, copyLength);",
    "    cursor += copyLength;",
    "    switch (fieldId) {",
    "      case 0..9:",
    "        parse/store value into ctx current service/config slot;",
    "        break;",
    "      default:",
    "        log unknown field;",
    "    }",
    "  }",
    "  return successFlagOrParsedStatus;",
    "}",
  ];
}

function updateAckModel(outDir, deepReport) {
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure({
      candidateFields: {
        typeA: [
          {
            candidate: "unknown unknown 47 unknown",
            evidence: "ParseData dispatch compares frame[6] with 0x47 and routes to 0x7e804.",
            confidence: "partial",
          },
        ],
        body: [
          { offset: 0, value: 0, meaning: "Success", confidence: "high" },
          { offset: "1..2", meaning: "entry count / loop upper bound", confidence: "high for structural role" },
          { offset: 3, meaning: "first entry field id / type", confidence: "medium" },
          { offset: 4, meaning: "first entry value length", confidence: "high" },
          { offset: "5..", meaning: "first entry value bytes; repeated typed length-value entries", confidence: "medium-high" },
        ],
        successCode: [
          {
            value: 0,
            meaning: "Success",
            location: "body[0] / frame[24]",
            confidence: "high for the frame[6]==0x47 handler path",
          },
        ],
        minimalSuccessBodyLengthCandidate: deepReport.minimalSuccessBodyLengthCandidate,
      },
      supplementalStage13: {
        bodyOffset: 24,
        checksumOffset: 22,
        handler: "0x7e804",
        bodyLayoutDeep: "body[0] status, body[1..2] entry count, body[3..] typed length-value entries",
        stage14Gate: deepReport.stage14Gate,
      },
    }),
  };
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.json`), `${JSON.stringify(model, null, 2)}\n`, "utf8");
  fs.writeFileSync(
    path.join(outDir, `ack-structure-model-${DATE_STEM}.md`),
    ["# ACK Structure Model", "", "```json", JSON.stringify(model, null, 2), "```", ""].join("\n"),
    "utf8",
  );
}

function writeReports(outDir, readMap, deepReport) {
  const readMapJson = path.join(outDir, `login-handler-body-read-map-${DATE_STEM}.json`);
  const readMapMd = path.join(outDir, `login-handler-body-read-map-${DATE_STEM}.md`);
  fs.writeFileSync(readMapJson, `${JSON.stringify(readMap, null, 2)}\n`, "utf8");
  fs.writeFileSync(
    readMapMd,
    [
      "# Login Handler Body Read Map",
      "",
      `Handler: ${readMap.handler.vaHex}`,
      "",
      "## Body Reads",
      "",
      "| Field | Frame Offset | Width | Usage | Confidence |",
      "| --- | --- | --- | --- | --- |",
      ...readMap.bodyReads.map((item) => `| ${item.field} | ${item.frameOffset} | ${item.readWidth} | ${item.usage} | ${item.confidence} |`),
      "",
    ].join("\n"),
    "utf8",
  );

  const mainJson = path.join(outDir, `login-handler-body-layout-deep-${DATE_STEM}.json`);
  const mainMd = path.join(outDir, `login-handler-body-layout-deep-${DATE_STEM}.md`);
  fs.writeFileSync(mainJson, `${JSON.stringify(deepReport, null, 2)}\n`, "utf8");
  fs.writeFileSync(
    mainMd,
    [
      "# Login Handler Body Layout Deep Analysis",
      "",
      "## Summary",
      "",
      deepReport.overview,
      "",
      "## Body Layout Candidate",
      "",
      "- `body[0]`: status byte (`0=Success`, `1=Fail`, `2=UnRegister`).",
      "- `body[1..2]`: entry count / loop upper bound candidate.",
      "- `body[3]`: first entry field id / type byte.",
      "- `body[4]`: first entry value length byte.",
      "- `body[5..]`: first entry value bytes; repeated cursor-driven typed length-value entries.",
      "",
      "## Stage 14 Gate",
      "",
      `Can enter Stage 14: ${deepReport.stage14Gate.canEnterStage14}`,
      "",
      deepReport.stage14Gate.reason,
      "",
    ].join("\n"),
    "utf8",
  );

  return { readMapJson, readMapMd, mainJson, mainMd };
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const siteUnitPath = path.resolve(args.siteunit || DEFAULT_SITEUNIT);
  fs.mkdirSync(outDir, { recursive: true });

  const instructions = runDisasm(siteUnitPath, 0x7e804, 0x7f404);
  const bodyReads = makeBodyReadMap(instructions);
  const fieldAnalyses = makeFieldAnalyses();
  const variableArea = makeVariableArea();
  const calls = makeCallMap(instructions);

  const readMap = {
    generatedAt: new Date().toISOString(),
    siteUnitPath,
    handler: {
      vaHex: "0x7e804",
      fileOffsetHex: hex(0x7e804 - TEXT_VA_DELTA),
      exitCandidates: ["0x7f400 ldmdb fp, {..., pc}", "early returns via 0x7f3f0 cleanup"],
    },
    parameters: {
      r0: "ctx pointer candidate; stored at [fp, #-0x2c]",
      r1: "body pointer; stored at [fp, #-0x30]",
      r2: "unknown",
      r3: "unknown",
    },
    locals: {
      localStatus: "fp-0x135",
      cursor: "fp-0x12c",
      loopIndex: "fp-0x130",
      entryCountCandidate: "2 bytes copied to fp-0x132 then read with ldrh",
      fieldId: "fp-0x134",
      copyLength: "fp-0x133",
      copyDestination: "local buffer fp-0xe8",
      ctxPointer: "fp-0x2c",
    },
    bodyReads,
    calls,
  };

  const deepReport = {
    generatedAt: new Date().toISOString(),
    overview:
      "Handler 0x7e804 consumes body[0] as login status, then parses body[1..] as a cursor-driven typed length-value list. The parser copies a uint16 entry count, then repeats fieldId/length/value parsing and dispatches fieldId through a switch table.",
    handlerBoundary: readMap.handler,
    parameters: readMap.parameters,
    locals: readMap.locals,
    bodyReadTable: bodyReads.map(({ evidence, ...rest }) => rest),
    fieldAnalyses,
    variableArea,
    copyAndStringCalls: calls,
    successPseudoCode: makePseudoCode(),
    failPath: {
      body0Value: 1,
      readsBody1Plus: false,
      conclusion: "Fail path writes ctx+0x129=1, logs Fail, destroys local string, and returns before the common body[1..] parser.",
      evidence: ["0x7e984 cmp status, #1", "0x7e99c writes ctx status 1", "0x7e9d4 branches to 0x7f3f0 return cleanup"],
    },
    unregisterPath: {
      body0Value: 2,
      readsBody1Plus: true,
      conclusion: "UnRegister path writes ctx+0x129=2 and then falls through to the common body[1..] parser.",
      evidence: ["0x7e9e0 cmp status, #2", "0x7e9f8 writes ctx status 2", "0x7ea1c enters common parser"],
    },
    minimalSuccessBodyLengthCandidate: {
      value: null,
      structuralLowerBound: 3,
      firstEntryLowerBound: "5 + valueLength",
      reason:
        "Success requires body[0] and body[1..2] entry count. The first fieldId/length pair is only read when entryCount > 0. Because it is not proven whether entryCount=0 is semantically valid, a closed minimum cannot be asserted. If entryCount=0 is accepted, the structural minimum is 3 bytes; if at least one entry is required, minimum is 5 bytes plus value length.",
      requiredFields: ["body[0]", "body[1..2]", "body[3] and body[4] only when entryCount > 0"],
    },
    ackModelUpdate: {
      status: "incomplete",
      ackHex: null,
      doNotSend: true,
    },
    stage14Gate: {
      canEnterStage14: false,
      reason:
        "full ACK typeA[4..7], exact success body contents, and seq strategy are still not confirmed. Body structure is clearer but not sufficient for sendable ACK construction.",
    },
    safety: {
      networkAckSent: false,
      sendOneShotAckRun: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      sendableAckHexGenerated: false,
    },
  };

  updateAckModel(outDir, deepReport);
  const paths = writeReports(outDir, readMap, deepReport);
  console.log(JSON.stringify(paths, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
