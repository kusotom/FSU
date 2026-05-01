#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { modelAckStructure } = require("../fsu-ack-experiments/model-ack-structure");

const DATE_STEM = "2026-04-28";
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

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

function writeReport(outDir, stem, title, data, summaryLines) {
  const jsonPath = path.join(outDir, `${stem}-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  const mdPath = path.join(outDir, `${stem}-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, [`# ${title}`, "", ...summaryLines, ""].join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function loadInputs(outDir) {
  return {
    dispatch: readJson(path.join(outDir, `parse-data-command-dispatch-${DATE_STEM}.json`)),
    body: readJson(path.join(outDir, `login-status-handler-body-layout-${DATE_STEM}.json`)),
    pointer: readJson(path.join(outDir, `response-buffer-pointer-trace-${DATE_STEM}.json`)),
    ackTypeBody: readJson(path.join(outDir, `login-ack-type-body-analysis-${DATE_STEM}.json`)),
  };
}

function buildParseDataCommandTable(dispatch) {
  return {
    generatedAt: new Date().toISOString(),
    dispatchByte: {
      frame6: "0x47",
      handler: "0x7e804",
      bodyOffset: 24,
      notes: "login status handler path",
    },
    otherDispatches: dispatch.dispatch.comparisons.map((item) => ({
      frameCompareVA: item.vaHex,
      constant: item.constantHex,
      branchTarget: item.branch ? item.branch.vaHex : null,
    })),
    fixedReads: dispatch.fixedReads,
  };
}

function buildTypeASource(dispatch) {
  return {
    generatedAt: new Date().toISOString(),
    fullTypeARecovered: false,
    candidateTypeA: [
      {
        candidate: "unknown unknown 47 unknown",
        evidence: "ParseData dispatch compares frame[6] with 0x47 and routes to 0x7e804.",
        confidence: "partial",
      },
    ],
    requestResponseRelation: {
      requestSideCandidate: "0x46 in DSC_CONFIG typeA seen in raw frames, not directly closed in SiteUnit",
      responseSideCandidate: "0x47 in ParseData dispatch",
      confidence: "low",
    },
    evidence: {
      parseDataFrame6: "0x763c4 cmp r3, #0x47",
      statusHandler: "0x76414 frame + 0x18 -> 0x7e804",
      protocolSamples: [
        "DSC_CONFIG_209_TYPE_1100_46FF",
        "DSC_CONFIG_245_TYPE_1100_46FF",
      ],
    },
    conclusions: [
      "frame[6] == 0x47 is confirmed for the login status handler path.",
      "No evidence closes frame[4], frame[5], or frame[7] into a full typeA.",
      "The request-side 0x46 / response-side 0x47 relationship is plausible but not proven directly in SiteUnit.",
    ],
  };
}

function buildSuccessPath(body, pointer) {
  return {
    generatedAt: new Date().toISOString(),
    statusByteOffset: 24,
    statusValues: { 0: "Success", 1: "Fail", 2: "UnRegister" },
    reads: body.bodyLayout.additionalFieldCandidates,
    minimumStatusBodyLength: { value: 1, confidence: "high" },
    minimumSuccessfulBodyLengthLowerBound: { value: 3, confidence: "medium" },
    body1to2Evidence: [
      "0x7ea24..0x7ea3c copies 2 bytes after status byte",
      "0x7ea54..0x7ea68 compares a copied halfword against a cursor/length value",
      "0x7ea84..0x7eaf8 continues cursor-based parsing and variable-length copy",
    ],
    pseudoCode: [
      "status = body[0];",
      "if (status == 0) {",
      "  // body[1..] is read on success",
      "}",
      "else if (status == 1) {",
      "  // fail path",
      "}",
      "else if (status == 2) {",
      "  // unregister path",
      "}",
    ],
    conclusions: [
      "Success path must read body[0] and continues into body[1..].",
      "Minimal successful body length lower bound is 3 bytes.",
      "Exact successful body length remains unresolved because the handler keeps parsing beyond body[2].",
    ],
    evidence: {
      statusPtr: pointer.statusHandlerFirstWrite ? pointer.statusHandlerFirstWrite.firstWrite.instruction : "0x7e818 str r1, [fp, #-0x30]",
      body0: "0x7e91c / 0x7e93c",
    },
  };
}

function buildMain(dispatch, body, typeA, successPath, seqStrategy) {
  const report = {
    generatedAt: new Date().toISOString(),
    overview:
      "ParseData login-status dispatch uses frame[6] == 0x47 and passes frame+0x18 to handler 0x7e804. body[0] is the status byte, but the handler also parses later body fields on success/unregister paths.",
    parseDataCommandTable: dispatch,
    frame47Branch: {
      condition: "frame[6] == 0x47",
      handler: "0x7e804",
      responsePtr: "frame + 0x18",
      bodyOffset: 24,
    },
    typeA,
    bodyLayout: body.bodyLayout,
    successPath,
    seqStrategy,
    bodyOffsetCorrection: {
      checksumOffset: 22,
      bodyOffset: 24,
      lengthLE: "totalLength - 24",
      bodyLength: "lengthLE",
    },
    ackModel: null,
    stage14Gate: {
      canEnterStage14: false,
      reason:
        "full ACK typeA[4..7], full body layout, and seq strategy are not confirmed. The handler path is partially recovered but not enough to construct a sendable ACK.",
    },
  };
  return report;
}

function updateAckModel(outDir, dispatch, body, typeA, successPath, seqStrategy) {
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure({
      candidateFields: {
        typeA: typeA.candidateTypeA,
        body: [
          {
            offset: 0,
            value: 0,
            meaning: "Success",
            confidence: "high",
          },
        ],
        successCode: [
          {
            value: 0,
            meaning: "Success",
            location: "body[0] / frame[24]",
            confidence: "high for the frame[6]==0x47 handler path",
          },
        ],
        minimalBodyLength: successPath.minimumSuccessfulBodyLengthLowerBound,
        minimalTotalLength: { value: 27, confidence: "low", reason: "lower bound only; handler still parses more fields" },
      },
      supplementalStage13: {
        dispatchByte: "frame[6] == 0x47",
        checksumOffset: 22,
        bodyOffset: 24,
        statusByte: "frame[24] / body[0]",
        requestResponseRelation: typeA.requestResponseRelation,
        seqStrategy,
        stage14Gate: {
          canEnterStage14: false,
          reason: "complete typeA and body layout are not closed.",
        },
      },
    }),
  };
  const jsonPath = path.join(outDir, `ack-structure-model-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(model, null, 2)}\n`, "utf8");
  const mdPath = path.join(outDir, `ack-structure-model-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, [`# ACK Structure Model`, "", "```json", JSON.stringify(model, null, 2), "```", ""].join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  fs.mkdirSync(outDir, { recursive: true });
  const inputs = loadInputs(outDir);

  const dispatch = buildParseDataCommandTable(inputs.dispatch);
  const typeA = buildTypeASource(inputs.dispatch);
  const successPath = buildSuccessPath(inputs.body, inputs.pointer);
  const seqStrategy = inputs.dispatch.seq ? inputs.dispatch.seq.strategy : "unknown";
  const mainReport = buildMain(dispatch, inputs.body, typeA, successPath, seqStrategy);
  const ackModelPaths = updateAckModel(outDir, inputs.dispatch, inputs.body, typeA, successPath, seqStrategy);

  const dispatchPaths = writeReport(outDir, "parse-data-command-table", "Parse Data Command Table", dispatch, [
    "ParseData uses `frame[6] == 0x47` to route to `0x7e804` with `frame + 0x18`.",
  ]);
  const typeAPaths = writeReport(outDir, "login-ack-typea-source", "Login ACK TypeA Source", typeA, [
    "Only `frame[6] == 0x47` is directly recovered from SiteUnit in this pass.",
    "The request/response `0x46 -> 0x47` relation remains a partial inference.",
  ]);
  const successPaths = writeReport(outDir, "login-status-handler-success-path", "Login Status Handler Success Path", successPath, [
    "Success path reads `body[0]` and continues with `body[1..]`.",
    "The lower bound for a successful body is 3 bytes; the exact layout remains open.",
  ]);
  const mainPaths = writeReport(outDir, "login-ack-layout-deep-analysis", "Login ACK Layout Deep Analysis", mainReport, [
    "## Summary",
    "",
    mainReport.overview,
    "",
    "## Stage 14 Gate",
    "",
    `Can enter Stage 14: ${mainReport.stage14Gate.canEnterStage14}`,
    "",
    mainReport.stage14Gate.reason,
    "",
    "不能进入可发送 ACK 构造，只能继续反汇编数据流。",
  ]);

  console.log(JSON.stringify({ dispatch: dispatchPaths, typeA: typeAPaths, success: successPaths, main: mainPaths, ackModel: ackModelPaths }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
