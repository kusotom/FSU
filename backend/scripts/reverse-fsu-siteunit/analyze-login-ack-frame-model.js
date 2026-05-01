#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { modelAckStructure } = require("../fsu-ack-experiments/model-ack-structure");

const DATE_STEM = "2026-04-28";
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");
const DEFAULT_RAW_LOG = path.join(process.cwd(), "backend", "logs", "fsu_raw_packets", `${DATE_STEM}.jsonl`);

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
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `${stem}-${DATE_STEM}.json`);
  const mdPath = path.join(outDir, `${stem}-${DATE_STEM}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  fs.writeFileSync(mdPath, [`# ${title}`, "", ...mdLines, ""].join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function inc(map, key, n = 1) {
  map.set(key, (map.get(key) || 0) + n);
}

function topEntries(map, limit = 20) {
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .slice(0, limit)
    .map(([value, count]) => ({ value, count }));
}

function classifyFrame(protocol, length, typeA) {
  if (protocol === "UDP_DSC" && length === 24 && typeA === "1f00d2ff") return "DSC_SHORT_24";
  if (protocol === "UDP_RDS" && length === 30 && typeA === "1180d2ff") return "RDS_SHORT_30";
  if (protocol === "UDP_DSC" && length === 209 && typeA === "110046ff") return "DSC_CONFIG_209";
  if (protocol === "UDP_DSC" && length === 245 && typeA === "110046ff") return "DSC_CONFIG_245";
  return `${protocol || "UNKNOWN"}_${length || "unknown"}_${typeA || "notype"}`;
}

function readRawLogStats(rawLogPath) {
  const byFrameClass = new Map();
  const byTypeA = new Map();
  const byOffset8to19 = new Map();
  const samples = [];
  let total = 0;
  let parseErrors = 0;

  if (!fs.existsSync(rawLogPath)) {
    return { exists: false, path: rawLogPath, total: 0, parseErrors: 0, byFrameClass: [], byTypeA: [], byOffset8to19: [], samples: [] };
  }

  const lines = fs.readFileSync(rawLogPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    if (!line.trim()) continue;
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      parseErrors += 1;
      continue;
    }
    const rawHex = String(row.rawHex || "").toLowerCase();
    if (!/^[0-9a-f]+$/.test(rawHex) || rawHex.length < 48) continue;
    const buf = Buffer.from(rawHex, "hex");
    if (buf.length < 24) continue;
    if (buf[0] !== 0x6d || buf[1] !== 0x7e) continue;
    const typeA = buf.subarray(4, 8).toString("hex");
    const offset8to19 = buf.subarray(8, 20).toString("hex");
    const frameClass = row.frameClass || classifyFrame(row.protocol, row.length || buf.length, typeA);
    total += 1;
    inc(byFrameClass, frameClass);
    inc(byTypeA, typeA);
    inc(byOffset8to19, `${frameClass}|${offset8to19}`);
    if (samples.length < 12) {
      samples.push({
        receivedAt: row.receivedAt,
        protocol: row.protocol,
        remotePort: row.remotePort,
        localPort: row.localPort,
        length: row.length || buf.length,
        frameClass,
        seqLE: buf.subarray(2, 4).toString("hex"),
        typeA,
        offset8to19,
        lengthLE: buf.readUInt16LE(20),
        rawHexPrefix: rawHex.slice(0, 96),
      });
    }
  }

  const byClass = {};
  for (const [key, count] of byFrameClass.entries()) {
    const dist = new Map();
    for (const [compound, c] of byOffset8to19.entries()) {
      const [klass, value] = compound.split("|");
      if (klass === key) dist.set(value, c);
    }
    byClass[key] = {
      count,
      offset8to19UniqueCount: dist.size,
      topOffset8to19: topEntries(dist, 12),
    };
  }

  return {
    exists: true,
    path: rawLogPath,
    total,
    parseErrors,
    byFrameClass: Object.fromEntries([...byFrameClass.entries()].sort()),
    byTypeA: topEntries(byTypeA, 20),
    byClass,
    samples,
  };
}

function buildFillCmdTypeASeqAnalysis() {
  return {
    generatedAt: new Date().toISOString(),
    recoveredRequestTypeEvidence: {
      observedRawFrames: {
        typeA: "110046ff",
        classes: ["DSC_CONFIG_209", "DSC_CONFIG_245"],
        evidence: "raw packet log contains long UDP_DSC config/login frames with typeA bytes 11 00 46 ff",
      },
      siteUnitConstant: {
        va: "0x76c30",
        instruction: "mov r3, #0x46",
        confidence: "low-medium",
        caveat: "Nearby SiteUnit code contains a 0x46 constant, but this pass did not close the full FillCmd write path for bytes[4..7].",
      },
    },
    responseDispatchEvidence: {
      va: "0x763c4",
      instruction: "cmp r3, #0x47",
      branch: "beq 0x76410",
      handler: "0x7e804",
      bodyPointer: "frame + 0x18",
      confidence: "high for frame[6] dispatch only",
    },
    typeACandidates: [
      {
        candidate: "110047ff",
        basis: "Observed request typeA is 11 00 46 ff and ParseData login status response dispatch checks command byte frame[6] == 0x47.",
        confidence: "low-medium",
        caveat: "No recovered comparison or construction directly proves frame[4]=0x11, frame[5]=0x00, or frame[7]=0xff for the response.",
        doNotSend: true,
      },
      {
        candidate: "unknown unknown 47 unknown",
        basis: "Only frame[6] == 0x47 is directly proven in ParseData.",
        confidence: "high for byte 6 only",
        doNotSend: true,
      },
    ],
    requestResponseRelation: {
      relation: "0x46 request / 0x47 response is plausible but not fully proven",
      confidence: "medium for command byte relation, low for full typeA",
    },
    conclusion: "Complete typeA[4..7] is not closed. 11 00 47 ff is a candidate, not a sendable fact.",
  };
}

function buildSeqStrategyAnalysis() {
  return {
    generatedAt: new Date().toISOString(),
    parseDataReads: [
      {
        field: "frame[2..3]",
        meaning: "seqLE",
        evidence: "ParseData pseudocode/report copies read_u16_le(buffer+0x02) to an output seq pointer.",
      },
    ],
    compareAgainstRequestSeq: {
      found: false,
      evidence: "No branch in the recovered frame[6] == 0x47 path compares seqLE with a saved request sequence.",
    },
    requestSeqGeneration: {
      found: "partial",
      evidence: "SequenceId strings and raw frames show changing seqLE, but exact generator/storage path was not closed in this pass.",
    },
    candidates: [
      { strategy: "mirror request seqLE", confidence: "low-medium", reason: "Common response convention; no disassembly proof." },
      { strategy: "request seqLE + 1", confidence: "low", reason: "No proof; retained only as an offline candidate." },
      { strategy: "independent platform seq", confidence: "low", reason: "No proof that ParseData requires mirroring." },
    ],
    conclusion: "seqLE strategy remains unknown; mirror request seqLE is the most conservative offline candidate but is not confirmed.",
  };
}

function buildHeader8to19Analysis(rawStats) {
  return {
    generatedAt: new Date().toISOString(),
    rawLogStats: rawStats,
    disassemblyUse: {
      parseDataReadsOffset12to15: {
        field: "frame[12..15]",
        pseudocode: "ctx->field_0x54 = *(uint32 *)(buffer + 0x0c)",
        confidence: "medium-high",
      },
      loginStatusHandlerReads8to19: false,
      validationFound: false,
    },
    strategyCandidates: [
      {
        strategy: "mirror request frame[8..19]",
        confidence: "low-medium",
        reason: "ParseData copies frame[12..15] into ctx; observed requests have stable context-looking bytes. No response validation proof.",
      },
      {
        strategy: "fixed zero/constant",
        confidence: "low",
        reason: "No firmware evidence confirms fixed values for login response bytes 8..19.",
      },
    ],
    conclusion:
      "offset 8..19 is not closed. ParseData appears to consume frame[12..15] as a context field, but no login-status validation or response construction source was recovered.",
  };
}

function buildEndpointValuesAnalysis() {
  return {
    generatedAt: new Date().toISOString(),
    requiredEndpointFields: {
      0: "diagnostic data channel endpoint",
      5: "uplink publish channel endpoint",
      6: "event data channel endpoint",
      7: "real-time data channel endpoint",
      8: "historical data channel endpoint",
      9: "image publish channel endpoint",
    },
    valueFormat: {
      format: "udp://host:port",
      confidence: "medium-high",
      evidence: "handler skips six bytes before parsing host:port, matching udp://",
    },
    candidates: [
      {
        name: "platform service endpoints",
        example: "udp://192.168.100.123:9000",
        confidence: "medium",
        reason: "These TLVs are returned by the platform and stored by the device as service/channel endpoints.",
      },
      {
        name: "per-channel platform ports",
        example: "fieldId 0 -> 9000, fieldId 5/6/7/8/9 -> possibly 7000 or other service ports",
        confidence: "low-medium",
        reason: "Channel names differ, but exact port mapping is not closed by this static pass.",
      },
      {
        name: "device-declared endpoints",
        example: "udp://192.168.100.100:6002",
        confidence: "low",
        reason: "Observed in device-originated frames, but login ACK TLVs look like service endpoints delivered to the device.",
      },
      {
        name: "configured DscIp/RDSIp service endpoints",
        example: "values from firmware/runtime DS/RDS configuration",
        confidence: "medium",
        reason: "Field semantics align with service-address configuration, but exact source and values are not recovered.",
      },
    ],
    conclusion:
      "Endpoint values have a clear udp://host:port format but not a single confirmed value source. Do not default-fill all six endpoints.",
  };
}

function buildOfflineFrameModel(typeAAnalysis, seqAnalysis, headerAnalysis, endpointAnalysis) {
  return {
    status: "incomplete",
    doNotSend: true,
    frameTemplate: {
      soi: { offset: "0..1", value: "6d7e", confidence: "high" },
      seqLE: { offset: "2..3", strategy: "unknown; mirror request seqLE is a low-medium offline candidate" },
      typeA: {
        offset: "4..7",
        candidate: "110047ff",
        confidence: "low-medium",
        confirmedBytes: { 6: "0x47" },
      },
      unknown8to19: {
        offset: "8..19",
        strategy: "unknown; mirror request frame[8..19] is a low-medium offline candidate",
      },
      bodyLengthLE: { offset: "20..21", formula: "body.length" },
      checksumLE: { offset: "22..23", formula: "uint16 sum(frame[2..end]) with checksum bytes zeroed" },
      body: {
        offset: 24,
        layout: "status + entryCountLE + required TLV endpoint entries",
        requiredFieldIds: [0, 5, 6, 7, 8, 9],
      },
      frameHexCandidate: null,
    },
    modelScript: "backend/scripts/fsu-ack-experiments/model-login-ack-frame.js",
    reasonFrameHexNull:
      "full typeA, seq strategy, offset8to19 strategy, and endpoint values are not independently confirmed for live use.",
    supportingAnalyses: {
      typeA: typeAAnalysis.conclusion,
      seq: seqAnalysis.conclusion,
      offset8to19: headerAnalysis.conclusion,
      endpoints: endpointAnalysis.conclusion,
    },
  };
}

function updateAckModel(outDir, reports) {
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure({
      candidateFields: {
        typeA: reports.typeA.typeACandidates,
        seqStrategy: reports.seq.candidates,
        offset8to19Strategy: reports.header.strategyCandidates,
        endpointValues: reports.endpoints.candidates,
        fullFrameCandidateStatus: reports.frameModel,
        successCode: [{ value: 0, meaning: "Success", location: "body[0] / frame[24]", confidence: "high" }],
        requiredFieldIds: [0, 5, 6, 7, 8, 9],
        bodyLayoutCandidate: {
          status: { offset: 0, values: { 0: "Success", 1: "Fail", 2: "UnRegister" } },
          entryCount: { offset: 1, size: 2, endian: "little" },
          entries: {
            startOffset: 3,
            format: ["fieldId:uint8", "valueLength:uint8", "valueBytes:ASCII udp://host:port"],
            requiredFieldIds: [0, 5, 6, 7, 8, 9],
          },
        },
      },
      unknowns: [
        "complete typeA proof",
        "seqLE response strategy",
        "offset 8..19 response strategy",
        "exact endpoint values for six required TLVs",
      ],
      supplementalStage13: {
        loginAckFrameModel: reports.frameModel,
        stage14Gate: reports.stage14Gate,
      },
    }),
  };
  model.reason =
    "body layout and required endpoint fields are modeled, but full typeA/seq/offset8to19/endpoint values are not closed.";
  model.unknowns = [
    "complete typeA proof",
    "seqLE response strategy",
    "offset 8..19 response strategy",
    "exact endpoint values for six required TLVs",
    "whether response target should be current UDP_DSC source port or configured service port",
  ];
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.json`), `${JSON.stringify(model, null, 2)}\n`, "utf8");
  fs.writeFileSync(
    path.join(outDir, `ack-structure-model-${DATE_STEM}.md`),
    ["# ACK Structure Model", "", "```json", JSON.stringify(model, null, 2), "```", ""].join("\n"),
    "utf8",
  );
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const rawLog = path.resolve(args.log || DEFAULT_RAW_LOG);

  const typeA = buildFillCmdTypeASeqAnalysis();
  const seq = buildSeqStrategyAnalysis();
  const header = buildHeader8to19Analysis(readRawLogStats(rawLog));
  const endpoints = buildEndpointValuesAnalysis();
  const frameModel = buildOfflineFrameModel(typeA, seq, header, endpoints);
  const stage14Gate = {
    canEnterStage14: false,
    reason:
      "不能进入可发送 ACK 构造，只能继续反汇编数据流。complete typeA, seqLE strategy, offset8to19 strategy, and endpoint values are not all confirmed.",
    missing: ["complete typeA proof", "seqLE strategy", "offset 8..19 strategy", "confirmed endpoint values"],
  };

  const paths = {};
  paths.typeA = writeJsonMd(outDir, "fillcmd-typea-seq-analysis", "FillCmd TypeA Seq Analysis", typeA, [
    "## Conclusion",
    "",
    typeA.conclusion,
    "",
    "## Candidates",
    "",
    ...typeA.typeACandidates.map((item) => `- ${item.candidate}: ${item.confidence}; ${item.basis}`),
  ]);
  paths.seq = writeJsonMd(outDir, "seq-strategy-analysis", "Seq Strategy Analysis", seq, [
    "## Conclusion",
    "",
    seq.conclusion,
  ]);
  paths.header = writeJsonMd(outDir, "header-unknown-8-19-analysis", "Header Unknown 8..19 Analysis", header, [
    "## Conclusion",
    "",
    header.conclusion,
    "",
    "## Raw Counts",
    "",
    `Total parsed frames: ${header.rawLogStats.total}`,
  ]);
  paths.endpoints = writeJsonMd(outDir, "login-ack-endpoint-values-analysis", "Login ACK Endpoint Values Analysis", endpoints, [
    "## Conclusion",
    "",
    endpoints.conclusion,
  ]);

  const mainReport = {
    generatedAt: new Date().toISOString(),
    overview:
      "This pass models the login ACK frame header offline. Body/TLV layout is usable as a model, but complete typeA, seqLE, offset8to19, and concrete endpoint values remain unclosed.",
    typeA,
    fillCmdRequestPath: typeA.recoveredRequestTypeEvidence,
    requestResponseRelation: typeA.requestResponseRelation,
    seqLE: seq,
    offset8to19: header,
    endpointValues: endpoints,
    offlineFrameModel: frameModel,
    ackModelUpdate: "backend/logs/fsu_reverse/ack-structure-model-2026-04-28.json",
    stage14Gate,
    safety: {
      networkAckSent: false,
      sendOneShotAckRun: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      automaticAckAdded: false,
      sendableAckHexGenerated: false,
      doNotSend: true,
    },
  };
  paths.main = writeJsonMd(outDir, "login-ack-frame-model-analysis", "Login ACK Frame Model Analysis", mainReport, [
    "## Summary",
    "",
    mainReport.overview,
    "",
    "## Stage 14 Gate",
    "",
    stage14Gate.reason,
  ]);

  updateAckModel(outDir, { typeA, seq, header, endpoints, frameModel, stage14Gate });
  paths.ackModel = {
    jsonPath: path.join(outDir, `ack-structure-model-${DATE_STEM}.json`),
    mdPath: path.join(outDir, `ack-structure-model-${DATE_STEM}.md`),
  };

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
