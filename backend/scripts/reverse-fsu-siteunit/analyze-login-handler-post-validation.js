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

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJsonMd(outDir, stem, title, data, mdLines) {
  const jsonPath = path.join(outDir, `${stem}-${DATE_STEM}.json`);
  const mdPath = path.join(outDir, `${stem}-${DATE_STEM}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  fs.writeFileSync(mdPath, [`# ${title}`, "", ...mdLines, ""].join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function buildReport(outDir) {
  const switchReport = readJson(path.join(outDir, `login-handler-fieldid-switch-analysis-${DATE_STEM}.json`));
  const flagSetters = [
    { fieldId: 0, flagMask: "0x01", setAtVA: "0x7ed6c", caseTargetVA: "0x7ec80", valueLengthMin: 1, destinationCtxOffset: "0x13c / parsed +0x140" },
    { fieldId: 5, flagMask: "0x02", setAtVA: "0x7ef2c", caseTargetVA: "0x7ee40", valueLengthMin: 1, destinationCtxOffset: "0x14c / parsed +0x150" },
    { fieldId: 6, flagMask: "0x04", setAtVA: "0x7f024", caseTargetVA: "0x7ef38", valueLengthMin: 1, destinationCtxOffset: "0x15c / parsed +0x160" },
    { fieldId: 7, flagMask: "0x08", setAtVA: "0x7f11c", caseTargetVA: "0x7f030", valueLengthMin: 1, destinationCtxOffset: "0x16c / parsed +0x170" },
    { fieldId: 8, flagMask: "0x10", setAtVA: "0x7f214", caseTargetVA: "0x7f128", valueLengthMin: 1, destinationCtxOffset: "0x17c / parsed +0x180" },
    { fieldId: 9, flagMask: "0x20", setAtVA: "0x7f30c", caseTargetVA: "0x7f220", valueLengthMin: 1, destinationCtxOffset: "0x18c / parsed +0x190" },
  ];
  const ignoredOrOptional = [
    { fieldId: 1, caseTargetVA: "0x7ed78", setsFlag: false, note: "writes ctx slot but does not OR fp-0x35" },
    { fieldId: 2, caseTargetVA: "0x7f318", setsFlag: false, note: "default/log path" },
    { fieldId: 3, caseTargetVA: "0x7f318", setsFlag: false, note: "default/log path" },
    { fieldId: 4, caseTargetVA: "0x7f318", setsFlag: false, note: "default/log path" },
  ];
  const requiredEntries = flagSetters.map((item) => ({
    fieldId: item.fieldId,
    minValueLength: item.valueLengthMin,
    valueCandidate: null,
    reason: `sets required flag bit ${item.flagMask} before fp-0x35 == 0x3f check`,
  }));
  const report = {
    generatedAt: new Date().toISOString(),
    overview:
      "Post-loop validation at 0x7f364 is a local bitmask equality check. It requires fp-0x35 == 0x3f, which is satisfied only when fieldIds 0,5,6,7,8,9 have all been parsed and set their corresponding bits.",
    postSuccessValidation: {
      checkVA: "0x7f364",
      checkType: "bitmask equality",
      variable: {
        kind: "local",
        stackOffset: "fp-0x35",
        initializedAt: "0x7e864",
        initialValue: "0x00",
      },
      requiredMaskOrValues: "fp-0x35 == 0x3f",
      evidence: [
        "0x7f364 ldrb r3, [fp, #-0x35]",
        "0x7f368 cmp r3, #0x3f",
        "0x7f36c bne 0x7f388 failure path",
        "0x7f384 branches to 0x7f3a0 success return path when mask is 0x3f and ctx[0x129] != 2",
      ],
      secondaryCheck: {
        va: "0x7f370..0x7f384",
        condition: "ctx[0x129] == 2 forces failure-like return path; otherwise success return",
        ctxOffset: "0x129",
      },
    },
    fieldIdFlagTable: flagSetters.concat(ignoredOrOptional).sort((a, b) => a.fieldId - b.fieldId),
    requiredFieldIds: flagSetters.map((item) => item.fieldId),
    optionalOrIgnoredFieldIds: ignoredOrOptional.map((item) => item.fieldId),
    entryCountZero: {
      entryCountZeroCanPass: false,
      evidence: [
        "entryCount=0 skips the loop and reaches 0x7f364",
        "fp-0x35 is initialized to 0 at 0x7e864",
        "no loop means no fieldId case executes, so fp-0x35 remains 0",
        "0x7f368 requires fp-0x35 == 0x3f",
      ],
      missingFlagsIfFalse: flagSetters.map((item) => ({ fieldId: item.fieldId, flagMask: item.flagMask })),
    },
    minimalSuccessBodyCandidate: {
      status: 0,
      entryCount: 6,
      requiredEntries,
      minimalBodyLengthCandidate: "3 + sum(2 + minValueLength for fieldIds 0,5,6,7,8,9) = 21 bytes if minValueLength=1 is accepted",
      bodyHexCandidate: null,
      doNotSend: true,
      caveat:
        "The parser permits valueLength=0 mechanically, but each case parses the value string numerically and stores it. A semantic minimum below 1 byte is not safe to assert without validating conversion behavior.",
    },
    cursorRules: switchReport.cursorRules,
    fieldSemantics: flagSetters.map((item) => ({
      fieldId: item.fieldId,
      destinationCtxOffset: item.destinationCtxOffset,
      possibleMeaning: "unknown; service-address/config-slot candidate",
      confidence: "low-medium",
    })),
    stage14Gate: {
      canEnterStage14: false,
      reason:
        "required fieldIds are now known, but full typeA[4..7], exact field semantics/values, seq strategy, and safe minimal values are not confirmed.",
    },
    safety: {
      networkAckSent: false,
      sendOneShotAckRun: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      sendableAckHexGenerated: false,
    },
  };
  return report;
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
        successCode: [{ value: 0, meaning: "Success", location: "body[0] / frame[24]", confidence: "high" }],
        bodyLayoutCandidate: {
          status: { offset: 0, values: { 0: "Success", 1: "Fail", 2: "UnRegister" } },
          entryCount: { offset: 1, size: 2, endian: "little" },
          entries: {
            startOffset: 3,
            format: ["fieldId:uint8", "valueLength:uint8", "valueBytes:valueLength"],
            requiredFieldIds: report.requiredFieldIds,
          },
        },
        postSuccessValidation: report.postSuccessValidation,
        requiredFieldIds: report.requiredFieldIds,
        entryCountZeroCanPass: report.entryCountZero.entryCountZeroCanPass,
        minimalSuccessBodyCandidate: report.minimalSuccessBodyCandidate,
      },
      supplementalStage13: {
        handler: "0x7e804",
        postValidation: "0x7f364 fp-0x35 == 0x3f",
        requiredFieldIds: report.requiredFieldIds,
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
  const report = buildReport(outDir);
  updateAckModel(outDir, report);
  const paths = writeJsonMd(outDir, "login-handler-post-validation-analysis", "Login Handler Post Validation Analysis", report, [
    "## Summary",
    "",
    report.overview,
    "",
    "## Required FieldIds",
    "",
    report.requiredFieldIds.map((id) => `\`${id}\``).join(", "),
    "",
    "## EntryCount Zero",
    "",
    `Can pass: ${report.entryCountZero.entryCountZeroCanPass}`,
    "",
    "## Stage 14 Gate",
    "",
    `Can enter Stage 14: ${report.stage14Gate.canEnterStage14}`,
    "",
    report.stage14Gate.reason,
  ]);
  console.log(JSON.stringify({ ...paths, ackModel: path.join(outDir, `ack-structure-model-${DATE_STEM}.json`) }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
