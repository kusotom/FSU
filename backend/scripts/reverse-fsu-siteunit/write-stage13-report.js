#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

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

function strongOffset129Hits(trace) {
  return trace.offset129Accesses
    .filter((hit) => hit.hitKind.includes("0x129"))
    .map((hit) => ({
      va: hit.vaHex,
      fileOffset: hit.fileOffsetHex,
      region: hit.region,
      instruction: hit.instruction,
      nearbyStrings: hit.nearbyStrings.map((item) => item.text),
    }));
}

function buildReport(outDir) {
  const tracePath = path.join(outDir, `login-result-field-trace-${DATE_STEM}.json`);
  const returnPath = path.join(outDir, `login-return-code-analysis-${DATE_STEM}.json`);
  const modelPath = path.join(outDir, `ack-structure-model-${DATE_STEM}.json`);
  const checksumPath = path.join(outDir, `checksum-verify-${DATE_STEM}.json`);

  const trace = readJson(tracePath);
  const returnCodes = readJson(returnPath);
  const ackModel = readJson(modelPath);
  const checksum = readJson(checksumPath);

  const registerOkRead = {
    va: "0x74ec0",
    fileOffset: "0x6cec0",
    literalInstruction: "ldr r2, [pc, #0x8a0] ; literal value 0x129",
    readInstruction: "0x74ec4 ldrb r3, [r3, r2]",
    branch: "cmp r3, #0; bne 0x74f38; only zero reaches Register OK",
    registerOkPrint: "0x74efc [StationName= %s]Register OK!",
  };

  const internalStatusMapping = [
    {
      status: "Success",
      localStatusByte: 0,
      condition: "local byte at fp-0x135 == 0",
      ctxWrite: "0x7e954 strb r3, [r1, r2] after mov r3,#0 and literal 0x129",
      print: "0x7e96c [%s] LogToDS return [%d]: Success",
    },
    {
      status: "Fail",
      localStatusByte: 1,
      condition: "local byte at fp-0x135 == 1",
      ctxWrite: "0x7e99c strb r3, [r1, r2] after mov r3,#1 and literal 0x129",
      print: "0x7e9b4 [%s] LogToDS return Code[%d]: Fail",
    },
    {
      status: "UnRegister",
      localStatusByte: 2,
      condition: "local byte at fp-0x135 == 2",
      ctxWrite: "0x7e9f8 strb r3, [r1, r2] after mov r3,#2 and literal 0x129",
      print: "0x7ea10 [%s] LogToDS return Code[%d]: UnRegister",
    },
  ];

  const report = {
    generatedAt: new Date().toISOString(),
    inputs: {
      tracePath,
      returnCodePath: returnPath,
      ackStructureModelPath: modelPath,
      checksumVerifyPath: checksumPath,
    },
    ctx129Trace: {
      instructionCount: trace.instructionCount,
      offset129AccessCandidates: trace.offset129Accesses.length,
      parseDataWrites129: trace.parseWrites129.length,
      confirmedLiteralHits: strongOffset129Hits(trace),
      registerOkRead,
      conclusion:
        "ctx+0x129 is read before Register OK and written by the LogToDS/GetServiceAddr return-status handler. No confirmed ParseData write to ctx+0x129 was found in this pass.",
    },
    parseDataOutput: {
      knownCallPath: "0x74e8c -> 0x76ac4; inside login flow 0x755bc -> 0x760a4 -> ParseData",
      parseDataWritesCtx129: false,
      outputCarrier:
        "ParseData return value participates in LoginToDSC Result, while ctx+0x129 is later consumed by Register OK. The raw response buffer field feeding the local status byte remains unresolved.",
      pseudocode: [
        "result = LoginToDSC_inner(ctx);",
        "log(\"LoginToDSC Result[%d]\", result);",
        "if (result != 0 && ctx[0x129] == 0) {",
        "  log(\"Register OK\");",
        "}",
      ],
    },
    loginReturnCodes: {
      internalStatusMapping,
      inferredCodes: returnCodes.inferredCodes,
      caveat:
        "0/1/2 are internal branch/status byte values. They are not yet confirmed as ACK body wire values or response-buffer offsets.",
    },
    checksumCalculator: {
      script: path.join(process.cwd(), "backend", "scripts", "fsu-ack-experiments", "fsu-checksum.js"),
      testScript: path.join(process.cwd(), "backend", "scripts", "fsu-ack-experiments", "test-fsu-checksum.js"),
      commandResult:
        "test-fsu-checksum.js passed: 20/20 DSC_CONFIG_209, 20/20 DSC_CONFIG_245, 20/20 RDS_SHORT_30; DSC_SHORT_24 intentionally 0/20 and not applicable.",
      formula: "uint16 byte sum over buffer[2..totalLen-1] with checksum bytes 22..23 zeroed",
      checksumVerifySummary: checksum.summary || null,
    },
    ackStructureModel: ackModel,
    stage14Gate: {
      canEnterSendableAckConstruction: false,
      reason:
        "ACK typeA, ACK body layout, and wire success-code location are still not confirmed. A checksum calculator exists, but it is not sufficient to build a sendable ACK.",
      unmetConditions: ["ACK typeA candidate source", "ACK body layout candidate source", "wire success code candidate source"],
    },
    safety: {
      udpAckSent: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      autoAckAdded: false,
      sendableAckHexGenerated: false,
    },
  };

  return report;
}

function markdownList(items) {
  return items.map((item) => `- ${item}`).join("\n");
}

function writeReports(outDir, report) {
  const jsonPath = path.join(outDir, `ack-field-modeling-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");

  const md = [
    "# ACK Field Modeling",
    "",
    `Generated: ${report.generatedAt}`,
    "",
    "## Summary",
    "",
    report.ctx129Trace.conclusion,
    "",
    "## ctx+0x129 Confirmed Literal Hits",
    "",
    markdownList(report.ctx129Trace.confirmedLiteralHits.map((hit) => `${hit.va} (${hit.fileOffset}, ${hit.region}) ${hit.instruction}`)),
    "",
    "## Register OK Condition",
    "",
    "```c",
    report.parseDataOutput.pseudocode.join("\n"),
    "```",
    "",
    "## Internal Return Status Mapping",
    "",
    markdownList(
      report.loginReturnCodes.internalStatusMapping.map(
        (item) => `${item.localStatusByte} => ${item.status}; ${item.condition}; ${item.ctxWrite}; ${item.print}`,
      ),
    ),
    "",
    "## Checksum Calculator",
    "",
    `Formula: ${report.checksumCalculator.formula}`,
    "",
    report.checksumCalculator.commandResult,
    "",
    "## ACK Structure Model",
    "",
    `Status: ${report.ackStructureModel.status}`,
    "",
    `Reason: ${report.ackStructureModel.reason}`,
    "",
    `ackHex: ${report.ackStructureModel.ackHex}`,
    "",
    "## Stage 14 Gate",
    "",
    `Can enter sendable ACK construction: ${report.stage14Gate.canEnterSendableAckConstruction}`,
    "",
    report.stage14Gate.reason,
    "",
    "Unmet conditions:",
    "",
    markdownList(report.stage14Gate.unmetConditions),
    "",
    "## Safety",
    "",
    "No UDP ACK was sent. No fsu-gateway main logic, database path, or auto-ACK runtime hook was modified.",
    "",
  ].join("\n");

  const mdPath = path.join(outDir, `ack-field-modeling-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const report = buildReport(outDir);
  const paths = writeReports(outDir, report);
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
