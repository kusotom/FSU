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

const REQUIRED_FIELDS = [
  {
    fieldId: 0,
    flagMask: "0x01",
    caseTargetVA: "0x7ec80",
    rawValueDestination: "ctx + currentIndex*0x80 + 0x13c",
    parsedValueDestination: "ctx + currentIndex*0x80 + 0x140",
    logStringVA: "0xb72a8",
    logString: "[%s]   诊断数据通道为：%s:%d\\n",
    meaningCandidate: "diagnostic data channel endpoint",
  },
  {
    fieldId: 5,
    flagMask: "0x02",
    caseTargetVA: "0x7ee40",
    rawValueDestination: "ctx + currentIndex*0x80 + 0x14c",
    parsedValueDestination: "ctx + currentIndex*0x80 + 0x150",
    logStringVA: "0xb72f8",
    logString: "[%s]   上行发布通道为：%s:%d\\n",
    meaningCandidate: "uplink publish channel endpoint",
  },
  {
    fieldId: 6,
    flagMask: "0x04",
    caseTargetVA: "0x7ef38",
    rawValueDestination: "ctx + currentIndex*0x80 + 0x15c",
    parsedValueDestination: "ctx + currentIndex*0x80 + 0x160",
    logStringVA: "0xb7318",
    logString: "[%s]   事件数据通道为：%s:%d\\n",
    meaningCandidate: "event data channel endpoint",
  },
  {
    fieldId: 7,
    flagMask: "0x08",
    caseTargetVA: "0x7f030",
    rawValueDestination: "ctx + currentIndex*0x80 + 0x16c",
    parsedValueDestination: "ctx + currentIndex*0x80 + 0x170",
    logStringVA: "0xb7338",
    logString: "[%s]   实时数据通道为：%s:%d\\n",
    meaningCandidate: "real-time data channel endpoint",
  },
  {
    fieldId: 8,
    flagMask: "0x10",
    caseTargetVA: "0x7f128",
    rawValueDestination: "ctx + currentIndex*0x80 + 0x17c",
    parsedValueDestination: "ctx + currentIndex*0x80 + 0x180",
    logStringVA: "0xb7358",
    logString: "[%s]   历史数据通道为：%s:%d\\n",
    meaningCandidate: "historical data channel endpoint",
  },
  {
    fieldId: 9,
    flagMask: "0x20",
    caseTargetVA: "0x7f220",
    rawValueDestination: "ctx + currentIndex*0x80 + 0x18c",
    parsedValueDestination: "ctx + currentIndex*0x80 + 0x190",
    logStringVA: "0xb7378",
    logString: "[%s]   图像发布通道为：%s:%d\\n",
    meaningCandidate: "image publish channel endpoint",
  },
];

function buildFieldCaseAnalysis() {
  return REQUIRED_FIELDS.map((field) => ({
    ...field,
    valueTypeCandidate: "URI string with udp:// prefix; parser skips first 6 bytes and then parses host:port",
    minValueLengthCandidate: 7,
    minValueLengthReason: "`udp://` is 6 bytes and at least one byte must remain for host parsing; semantic host:port needs longer.",
    validation:
      "value is copied to local buffer, NUL-terminated by caller code, transformed with source pointer + 6, split/searches ':' and parses numeric component; failure path logs DS service IP error.",
    storesRawAndParsed: true,
    rawValueRole: "host/string slot candidate",
    parsedValueRole: "numeric port/address component candidate",
    confidence: "medium-high for URI host:port format; medium for exact channel semantics",
    evidence: [
      "0x7ead4..0x7eaf8 memcpy value bytes into local buffer",
      "0x7eb00..0x7eb20 NUL-terminates local buffer",
      "0x7eb40 uses local buffer + 6",
      "0x7eb4c loads format string %s",
      "0x7eb60/0x7eb64 search or parse with ':' literal",
      "case-specific log string prints %s:%d",
    ],
  }));
}

function buildDsipMapping(fieldAnalyses) {
  return {
    dsipString: {
      fileOffset: "0xae484",
      virtualAddress: "0xb6484",
      text: "DSip[%s:%d]!",
      directUseInThisHandler: false,
      note: "The login handler uses channel-specific Chinese format strings with the same %s:%d endpoint shape.",
    },
    channelFormatStrings: fieldAnalyses.map((field) => ({
      fieldId: field.fieldId,
      formatVA: field.logStringVA,
      format: field.logString,
      stringArgumentCandidate: field.rawValueDestination,
      numericArgumentCandidate: field.parsedValueDestination,
      mappedToRequiredField: true,
    })),
    ipPortPairConfirmed: true,
    confidence: "medium-high",
  };
}

function buildXrefReport(fieldAnalyses) {
  return {
    generatedAt: new Date().toISOString(),
    ctxOffsetModel: "ctx + currentIndex*0x80 + offset",
    xrefs: fieldAnalyses.map((field) => ({
      fieldId: field.fieldId,
      offsets: [field.rawValueDestination, field.parsedValueDestination],
      writer: field.caseTargetVA,
      readUseCandidate: field.logString,
      nearbyStrings: [field.logString, "DS服务IP地址配置错误。", "GetServiceAddr"],
      participatesIn: ["string formatting", "colon split/search", "numeric parse", "channel endpoint log"],
      fieldNameCandidate: field.meaningCandidate,
      confidence: field.confidence,
    })),
  };
}

function buildMainReport(fieldAnalyses, dsipMapping, xrefReport) {
  const requiredFieldIds = fieldAnalyses.map((item) => item.fieldId);
  return {
    generatedAt: new Date().toISOString(),
    overview:
      "Required Success TLV entries 0/5/6/7/8/9 are endpoint URI strings. The parser copies each value, NUL-terminates it, skips the 6-byte udp:// prefix, splits/parses host:port, and stores channel-specific endpoint fields into ctx slots.",
    requiredFieldIds,
    requiredFlagsMask: "0x3f",
    fieldCaseAnalysis: fieldAnalyses,
    ctxOffsetXrefs: xrefReport,
    dsipFormatMapping: dsipMapping,
    deviceUriInference: {
      observedUris: [
        "udp://192.168.100.100:6002",
        "udp://[dhcp]:6002",
        "ftp://root:hello@192.168.100.100",
        "ftp://root:hello@[dhcp]",
      ],
      likelyValueFormat: "udp://host:port for the six required channel fields",
      ftpUriLikelyRelevant: false,
      reason:
        "The handler adds 6 to the value string before parsing host:port, which matches skipping udp://, not ftp://root:hello@.",
      candidateHostPortSource: "current platform endpoint candidates remain unresolved; do not default-fill values",
    },
    offlineBodyModel: {
      canGenerateBodyHexCandidate: true,
      canGenerateAckHex: false,
      requiredFlagsSatisfiedWhenAllPresent: requiredFieldIds,
      exampleValues: null,
      doNotSend: true,
    },
    stage14Gate: {
      canEnterStage14: false,
      reason:
        "required field value format is clearer, but exact endpoint values, full typeA[4..7], and seq strategy are not confirmed.",
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

function updateAckModel(outDir, mainReport) {
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
        requiredFieldIds: mainReport.requiredFieldIds,
        requiredFlagsMask: "0x3f",
        valueTypeCandidates: Object.fromEntries(
          mainReport.fieldCaseAnalysis.map((field) => [
            field.fieldId,
            {
              valueTypeCandidate: field.valueTypeCandidate,
              meaningCandidate: field.meaningCandidate,
              minValueLengthCandidate: field.minValueLengthCandidate,
            },
          ]),
        ),
        dsipMapping: mainReport.dsipFormatMapping,
        bodyHexCandidateStatus: "body-only candidates may be generated by model-login-ack-body.js; full ackHex remains null",
      },
      supplementalStage13: {
        requiredLoginFieldsAnalysis: "required field values are udp://host:port endpoint URI strings",
        stage14Gate: mainReport.stage14Gate,
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

  const fieldAnalyses = buildFieldCaseAnalysis();
  const dsipMapping = buildDsipMapping(fieldAnalyses);
  const xrefReport = buildXrefReport(fieldAnalyses);
  const mainReport = buildMainReport(fieldAnalyses, dsipMapping, xrefReport);

  writeJsonMd(outDir, "required-login-fields-xref", "Required Login Fields Xref", xrefReport, [
    "Required field offsets are modeled as `ctx + currentIndex*0x80 + offset`.",
    "",
    "| fieldId | offsets | candidate |",
    "| --- | --- | --- |",
    ...xrefReport.xrefs.map((item) => `| ${item.fieldId} | ${item.offsets.join("<br>")} | ${item.fieldNameCandidate} |`),
  ]);
  writeJsonMd(outDir, "dsip-format-field-mapping", "DSip Format Field Mapping", dsipMapping, [
    "`DSip[%s:%d]!` exists at `VA 0xb6484`; this handler uses channel-specific `%s:%d` strings.",
    "",
    "| fieldId | format |",
    "| --- | --- |",
    ...dsipMapping.channelFormatStrings.map((item) => `| ${item.fieldId} | ${item.format} |`),
  ]);
  const mainPaths = writeJsonMd(outDir, "required-login-fields-analysis", "Required Login Fields Analysis", mainReport, [
    "## Summary",
    "",
    mainReport.overview,
    "",
    "## Required Fields",
    "",
    mainReport.requiredFieldIds.map((id) => `\`${id}\``).join(", "),
    "",
    "## Stage 14 Gate",
    "",
    `Can enter Stage 14: ${mainReport.stage14Gate.canEnterStage14}`,
    "",
    mainReport.stage14Gate.reason,
  ]);
  updateAckModel(outDir, mainReport);
  console.log(JSON.stringify({ main: mainPaths, ackModel: path.join(outDir, `ack-structure-model-${DATE_STEM}.json`) }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
