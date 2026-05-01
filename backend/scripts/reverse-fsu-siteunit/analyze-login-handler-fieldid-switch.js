#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { modelAckStructure } = require("../fsu-ack-experiments/model-ack-structure");

const DATE_STEM = "2026-04-28";
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

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

function writeJsonMd(outDir, stem, title, data, mdLines) {
  const jsonPath = path.join(outDir, `${stem}-${DATE_STEM}.json`);
  const mdPath = path.join(outDir, `${stem}-${DATE_STEM}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  fs.writeFileSync(mdPath, [`# ${title}`, "", ...mdLines, ""].join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function buildCaseTable() {
  const common = {
    copyLength: "valueLength from body[cursor + 1]",
    valueType: "ASCII numeric/string candidate; parsed through string helpers",
    possibleMeaning: "unknown",
    confidence: "medium for ctx offset, low for semantic name",
  };
  return [
    {
      fieldId: 0,
      caseTargetVA: "0x7ec80",
      destination: "ctx + currentIndex*0x80 + 0x13c, value stored at +0x140",
      ctxBaseOffset: "0x13c",
      parsedValueOffset: "0x140",
      flagBit: "0x01",
      ...common,
      evidence: ["0x7ec94 add +0x13c", "0x7ecfc strh at +2", "0x7ed3c str parsed numeric at +0x140", "0x7ed6c OR flag 0x01"],
    },
    {
      fieldId: 1,
      caseTargetVA: "0x7ed78",
      destination: "ctx + currentIndex*0x80 + 0x19c, value stored at +0x1a0",
      ctxBaseOffset: "0x19c",
      parsedValueOffset: "0x1a0",
      flagBit: null,
      ...common,
      evidence: ["0x7ed84 mov +0x19c", "0x7edd0 strh at +2", "0x7ee10 str parsed numeric at +0x1a0"],
    },
    {
      fieldId: 2,
      caseTargetVA: "0x7f318",
      destination: "no typed ctx field write observed; default/log path",
      ctxBaseOffset: null,
      parsedValueOffset: null,
      flagBit: null,
      copyLength: "not used for ctx store in this case",
      valueType: "unknown",
      possibleMeaning: "unsupported/reserved/default",
      confidence: "medium",
      evidence: ["switch table entry 2 -> 0x7f318", "0x7f318 logs field/value but does not follow the typed store pattern"],
    },
    {
      fieldId: 3,
      caseTargetVA: "0x7f318",
      destination: "no typed ctx field write observed; default/log path",
      ctxBaseOffset: null,
      parsedValueOffset: null,
      flagBit: null,
      copyLength: "not used for ctx store in this case",
      valueType: "unknown",
      possibleMeaning: "unsupported/reserved/default",
      confidence: "medium",
      evidence: ["switch table entry 3 -> 0x7f318"],
    },
    {
      fieldId: 4,
      caseTargetVA: "0x7f318",
      destination: "no typed ctx field write observed; default/log path",
      ctxBaseOffset: null,
      parsedValueOffset: null,
      flagBit: null,
      copyLength: "not used for ctx store in this case",
      valueType: "unknown",
      possibleMeaning: "unsupported/reserved/default",
      confidence: "medium",
      evidence: ["switch table entry 4 -> 0x7f318"],
    },
    {
      fieldId: 5,
      caseTargetVA: "0x7ee40",
      destination: "ctx + currentIndex*0x80 + 0x14c, value stored at +0x150",
      ctxBaseOffset: "0x14c",
      parsedValueOffset: "0x150",
      flagBit: "0x02",
      ...common,
      evidence: ["0x7ee54 add +0x14c", "0x7eebc strh at +2", "0x7eefc str parsed numeric at +0x150", "0x7ef2c OR flag 0x02"],
    },
    {
      fieldId: 6,
      caseTargetVA: "0x7ef38",
      destination: "ctx + currentIndex*0x80 + 0x15c, value stored at +0x160",
      ctxBaseOffset: "0x15c",
      parsedValueOffset: "0x160",
      flagBit: "0x04",
      ...common,
      evidence: ["0x7ef4c add +0x15c", "0x7efb4 strh at +2", "0x7eff4 str parsed numeric at +0x160", "0x7f024 OR flag 0x04"],
    },
    {
      fieldId: 7,
      caseTargetVA: "0x7f030",
      destination: "ctx + currentIndex*0x80 + 0x16c, value stored at +0x170",
      ctxBaseOffset: "0x16c",
      parsedValueOffset: "0x170",
      flagBit: "0x08",
      ...common,
      evidence: ["0x7f044 add +0x16c", "0x7f0ac strh at +2", "0x7f0ec str parsed numeric at +0x170", "0x7f11c OR flag 0x08"],
    },
    {
      fieldId: 8,
      caseTargetVA: "0x7f128",
      destination: "ctx + currentIndex*0x80 + 0x17c, value stored at +0x180",
      ctxBaseOffset: "0x17c",
      parsedValueOffset: "0x180",
      flagBit: "0x10",
      ...common,
      evidence: ["0x7f13c add +0x17c", "0x7f1a4 strh at +2", "0x7f1e4 str parsed numeric at +0x180", "0x7f214 OR flag 0x10"],
    },
    {
      fieldId: 9,
      caseTargetVA: "0x7f220",
      destination: "ctx + currentIndex*0x80 + 0x18c, value stored at +0x190",
      ctxBaseOffset: "0x18c",
      parsedValueOffset: "0x190",
      flagBit: "0x20",
      ...common,
      evidence: ["0x7f234 add +0x18c", "0x7f29c strh at +2", "0x7f2dc str parsed numeric at +0x190", "0x7f30c OR flag 0x20"],
    },
  ];
}

function buildCopyAnalysis() {
  return {
    functionVA: "0xca5c",
    symbol: "memcpy",
    evidence: [
      "pyelftools .rel.plt mapping: PLT entry 0xca5c -> memcpy",
      "call sites use r0 as destination, r1 as source, r2 as length",
      "0x7eaf8 copies body value bytes into local buffer fp-0xe8",
    ],
    parameters: { r0: "destination", r1: "source", r2: "length", r3: "not part of memcpy ABI" },
    appendsNullTerminator: false,
    nullTerminationEvidence: "0x7eb00..0x7eb20 writes a zero byte into the local buffer after memcpy",
    lengthLimit: "memcpy itself has no maximum; local destination size appears 0x40 bytes, but no strong valueLength upper-bound check was found before the copy",
    returnValue: "standard memcpy returns destination pointer in r0; return not used in the relevant copy sites",
  };
}

function buildCtxXrefs(caseTable) {
  return caseTable
    .filter((item) => item.ctxBaseOffset)
    .map((item) => ({
      ctxOffset: item.ctxBaseOffset,
      writtenByFieldIds: [item.fieldId],
      otherXrefs: [
        {
          pattern: `ctx + currentIndex*0x80 + ${item.ctxBaseOffset}`,
          note: "same slot-family pattern in this handler; broader whole-binary xref names remain unresolved",
        },
      ],
      nearbyStrings: ["LogToDS return", "DSip[%s:%d]!", "configuration of DS[%d] port is error, using 9000!"],
      fieldNameCandidate: "unknown; service-address/config slot candidate",
      confidence: "low-medium",
    }));
}

function buildReport() {
  const caseTable = buildCaseTable();
  const copyFunction = buildCopyAnalysis();
  const ctxXrefs = buildCtxXrefs(caseTable);
  const switchTable = {
    fieldIdCheckVA: "0x7ec4c",
    condition: "fieldId <= 9",
    tableBaseVA: "0x7ec58",
    defaultTargetVA: "0x7f318",
    entries: caseTable.map(({ fieldId, caseTargetVA }) => ({ fieldId, caseTargetVA })),
  };
  const entryCountZero = {
    entryCountZeroAllowed: "unknown",
    evidence: [
      "0x7ea5c loads entryCount",
      "0x7ea64 compares loopIndex with entryCount",
      "0x7ea68 branches into loop only when loopIndex < entryCount",
      "0x7ea6c skips to 0x7f364 when loopIndex >= entryCount",
      "0x7f364 checks accumulated field flags, so entryCount=0 reaches post-loop validation but may fail depending on required flags",
    ],
    minimalSuccessBodyLengthIfZeroAllowed: 3,
    minimalSuccessBodyLengthIfOneEntryRequired: "5 + valueLength",
  };
  const cursorRules = {
    confirmed: true,
    cursorInitial: 0,
    afterStatus: 1,
    entryCountOffset: 1,
    entriesStartOffset: 3,
    rules: [
      "cursor = 0",
      "status = body[cursor]; cursor += 1",
      "entryCount = uint16LE(body + cursor); cursor += 2",
      "for each entry: fieldId = body[cursor]; cursor += 1",
      "valueLength = body[cursor]; cursor += 1",
      "valueBytes = body[cursor..cursor+valueLength-1]",
      "cursor += valueLength",
    ],
    valueLengthLimit: "no strong pre-copy bounds check found; local buffer is about 0x40 bytes",
    bodyLengthBoundsCheck: "not found in 0x7e804 handler; ParseData validates frame-level length before dispatch",
  };
  const bodyLayoutCandidate = {
    status: { offset: 0, values: { 0: "Success", 1: "Fail", 2: "UnRegister" } },
    entryCount: { offset: 1, size: 2, endian: "little" },
    entries: {
      startOffset: 3,
      format: ["fieldId:uint8", "valueLength:uint8", "valueBytes:valueLength"],
      fieldIdCases: Object.fromEntries(caseTable.map((item) => [String(item.fieldId), item.destination])),
    },
  };
  return {
    generatedAt: new Date().toISOString(),
    overview:
      "The 0x7e804 handler parses Success/UnRegister response body as a TLV-like list. fieldId is checked against <=9 and dispatched through a jump table at 0x7ec58.",
    switchTable,
    caseTable,
    copyFunction,
    ctxXrefs,
    entryCountZero,
    cursorRules,
    bodyLayoutCandidate,
    stage14Gate: {
      canEnterStage14: false,
      reason:
        "full typeA[4..7], required TLV entries, exact semantic field names, and seq strategy are still not confirmed.",
    },
    safety: {
      networkAckSent: false,
      sendOneShotAckRun: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      sendableAckHexGenerated: false,
    },
  };
}

function updateAckModel(outDir, report) {
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
        bodyLayoutCandidate: report.bodyLayoutCandidate,
        successCode: [
          { value: 0, meaning: "Success", location: "body[0] / frame[24]", confidence: "high" },
        ],
        requiredEntries: {
          value: null,
          reason: "field flags are checked after loop, but the exact required TLV set is not closed",
        },
      },
      supplementalStage13: {
        handler: "0x7e804",
        switchTable: report.switchTable,
        copyFunction: report.copyFunction,
        stage14Gate: report.stage14Gate,
      },
    }),
  };
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.json`), `${JSON.stringify(model, null, 2)}\n`, "utf8");
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.md`), ["# ACK Structure Model", "", "```json", JSON.stringify(model, null, 2), "```", ""].join("\n"), "utf8");
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  fs.mkdirSync(outDir, { recursive: true });
  const report = buildReport();

  writeJsonMd(outDir, "copy-func-ca5c-analysis", "Copy Function 0xca5c Analysis", report.copyFunction, [
    "`0xca5c` maps to PLT symbol `memcpy`.",
    "",
    `- r0: ${report.copyFunction.parameters.r0}`,
    `- r1: ${report.copyFunction.parameters.r1}`,
    `- r2: ${report.copyFunction.parameters.r2}`,
    `- Null termination: ${report.copyFunction.appendsNullTerminator}`,
  ]);

  writeJsonMd(outDir, "login-handler-fieldid-switch-analysis", "Login Handler FieldId Switch Analysis", report, [
    "## Summary",
    "",
    report.overview,
    "",
    "## Switch Table",
    "",
    `- fieldId check: ${report.switchTable.fieldIdCheckVA}`,
    `- table base: ${report.switchTable.tableBaseVA}`,
    `- default target: ${report.switchTable.defaultTargetVA}`,
    "",
    "| fieldId | target | destination | possible meaning |",
    "| --- | --- | --- | --- |",
    ...report.caseTable.map((item) => `| ${item.fieldId} | ${item.caseTargetVA} | ${item.destination} | ${item.possibleMeaning} |`),
    "",
    "## Stage 14 Gate",
    "",
    `Can enter Stage 14: ${report.stage14Gate.canEnterStage14}`,
    "",
    report.stage14Gate.reason,
  ]);

  updateAckModel(outDir, report);
  console.log(JSON.stringify({
    main: path.join(outDir, `login-handler-fieldid-switch-analysis-${DATE_STEM}.json`),
    copy: path.join(outDir, `copy-func-ca5c-analysis-${DATE_STEM}.json`),
    ackModel: path.join(outDir, `ack-structure-model-${DATE_STEM}.json`),
  }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
