#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { buildCandidateProfiles } = require("../fsu-ack-experiments/model-login-ack-body");
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

function readJsonSafe(filePath, fallback = {}) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJsonMd(outDir, stem, title, data, mdLines) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `${stem}-${DATE_STEM}.json`);
  const mdPath = path.join(outDir, `${stem}-${DATE_STEM}.md`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  fs.writeFileSync(mdPath, [`# ${title}`, "", ...mdLines, ""].join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function buildEndpointMap() {
  const common = {
    evidence: [
      "required TLV value is copied and NUL-terminated",
      "handler skips udp:// prefix and parses host:port",
      "case-specific log strings identify business channel names",
      "downstream socket/sendto target for each stored ctx slot was not fully closed",
    ],
  };
  return [
    {
      fieldId: 0,
      meaningCandidate: "diagnostic data channel endpoint",
      endpointCandidates: [
        { value: "udp://192.168.100.123:9000", portCandidate: 9000, confidence: "medium", reason: "diagnostic/DSC service path" },
        { value: "udp://192.168.100.123:7000", portCandidate: 7000, confidence: "low", reason: "alternate data listener candidate" },
        { value: "udp://192.168.100.100:6002", portCandidate: 6002, confidence: "low", reason: "device-declared endpoint appears in requests but is less likely as returned service endpoint" },
      ],
      ...common,
    },
    ...[
      [5, "uplink publish channel endpoint"],
      [6, "event data channel endpoint"],
      [7, "real-time data channel endpoint"],
      [8, "historical data channel endpoint"],
      [9, "image publish channel endpoint"],
    ].map(([fieldId, meaningCandidate]) => ({
      fieldId,
      meaningCandidate,
      endpointCandidates: [
        { value: "udp://192.168.100.123:7000", portCandidate: 7000, confidence: "low-medium", reason: "business/data channel label may map to data listener" },
        { value: "udp://192.168.100.123:9000", portCandidate: 9000, confidence: "low-medium", reason: "could share the DSC platform listener" },
        { value: "unknown", portCandidate: null, confidence: "medium", reason: "exact downstream endpoint port is not statically closed" },
      ],
      ...common,
    })),
  ];
}

function buildReports(frameReport) {
  const typeA = {
    generatedAt: new Date().toISOString(),
    finalCandidate: "110047ff",
    confidence: "medium",
    confidenceChange: "raised from low-medium to medium, not medium-high",
    evidence: [
      "raw log has 10587 SOI frames with request typeA 110046ff for DSC_CONFIG_209/245",
      "ParseData login status dispatch checks frame[6] == 0x47 and calls handler 0x7e804",
      "frame[5] bit 0x40 is DS busy flag, so 0x00 in observed request remains plausible for non-busy response",
      "frame[7] is consistently 0xff in observed DSC request/short type signatures",
      "nearby SiteUnit code includes request-side 0x46 constant at VA 0x76c30",
    ],
    notClosed: [
      "no direct store sequence proving response frame[4]=0x11",
      "no direct store sequence proving response frame[5]=0x00",
      "no direct store sequence proving response frame[7]=0xff",
      "no recovered command table entry explicitly pairing full 110046ff -> 110047ff",
    ],
    requestResponseRelation: {
      relation: "0x46 -> 0x47 command-byte relation",
      confidence: "medium",
      evidence: "request typeA byte[6] is 0x46 in long DSC frames; response dispatch byte[6] is 0x47",
    },
    doNotSend: true,
    previousFrameReportSummary: frameReport.typeA?.conclusion || null,
  };

  const seq = {
    generatedAt: new Date().toISOString(),
    seqStrategyCandidate: "mirror",
    confidence: "low-medium",
    evidence: [
      "ParseData reads frame[2..3] and copies seqLE to an output pointer",
      "no recovered branch compares response seqLE against a pending request seqLE in the frame[6]==0x47 path",
      "raw request seqLE increments over time and is used as a packet identifier",
      "no mismatch/timeout branch tied to seq mismatch was recovered",
    ],
    alternatives: [
      { strategy: "plus1", confidence: "low", reason: "no evidence for +1 relation" },
      { strategy: "independent", confidence: "low", reason: "ParseData preserves seqLE, so ignoring it entirely is less conservative" },
    ],
    conclusion: "mirror request seqLE is the best offline candidate, but not confirmed.",
    previousFrameReportSummary: frameReport.seqLE?.conclusion || null,
  };

  const stats = frameReport.offset8to19?.rawLogStats || {};
  const header = {
    generatedAt: new Date().toISOString(),
    finalCandidate: "00000000c162002d00000000",
    strategyCandidate: "mirror DSC_CONFIG request frame[8..19], which is also a stable constant in observed long DSC requests",
    confidence: "medium",
    evidence: [
      "DSC_CONFIG_209 offset8..19 unique value is 00000000c162002d00000000",
      "DSC_CONFIG_245 offset8..19 unique value is 00000000c162002d00000000",
      "RDS_SHORT_30 shares the same value",
      "DSC_SHORT_24 differs and is not the login ACK model source",
      "ParseData copies frame[12..15] into ctx->field_0x54 but no login-status validation against bytes[8..19] was recovered",
      "0x7e804 receives only frame+0x18 body pointer and does not read header bytes 8..19",
    ],
    rawStats: { total: stats.total, byClass: stats.byClass },
    notClosed: ["request construction source for bytes 8..19", "response construction source for bytes 8..19"],
    doNotSend: true,
  };

  const endpoints = {
    generatedAt: new Date().toISOString(),
    fieldMappings: buildEndpointMap(),
    finalPortConclusion: "No single port mapping is closed. all_9000_profile and mixed_9000_7000_profile are offline candidates only.",
    doNotSend: true,
  };

  const bodyCandidates = {
    generatedAt: new Date().toISOString(),
    profiles: buildCandidateProfiles("192.168.100.123"),
    note: "body-only candidates; not complete frame; cannot send",
    doNotSend: true,
  };

  const checklist = [
    { item: "完整 ACK typeA 有候选来源，且置信度至少 medium", pass: true, result: `${typeA.finalCandidate} / ${typeA.confidence}` },
    { item: "success code 有候选来源", pass: true, result: "body[0]=0" },
    { item: "success code offset 有候选来源", pass: true, result: "frame[24] / body[0]" },
    { item: "body layout 有候选来源", pass: true, result: "status + entryCount + TLV entries" },
    { item: "最小 body length 有候选来源", pass: true, result: "requires six endpoint TLVs; exact bytes depend on endpoint strings" },
    { item: "必填 entry 是否明确", pass: true, result: "0,5,6,7,8,9" },
    { item: "必填 entry 的值格式是否明确", pass: true, result: "udp://host:port" },
    { item: "endpoint 值有候选来源", pass: false, result: endpoints.finalPortConclusion },
    { item: "length/checksum 计算器可用于目标帧", pass: true, result: "confirmed offline formula" },
    { item: "seq 策略至少有候选，置信度至少 low-medium", pass: true, result: `${seq.seqStrategyCandidate} / ${seq.confidence}` },
    { item: "offset8..19 有候选策略", pass: true, result: `${header.strategyCandidate} / ${header.confidence}` },
    { item: "不再依赖 mirror 原始包", pass: false, result: "seq/header remain mirror-style candidates" },
  ];
  return { typeA, seq, header, endpoints, bodyCandidates, checklist };
}

function updateAckModel(outDir, reports) {
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure({
      candidateFields: {
        typeA: [{ candidate: reports.typeA.finalCandidate, confidence: reports.typeA.confidence, evidence: reports.typeA.evidence }],
        seqStrategy: [{ strategy: reports.seq.seqStrategyCandidate, confidence: reports.seq.confidence, evidence: reports.seq.evidence }],
        offset8to19Strategy: [{ value: reports.header.finalCandidate, strategy: reports.header.strategyCandidate, confidence: reports.header.confidence }],
        endpointFieldIdMapping: reports.endpoints.fieldMappings,
        bodyCandidateProfiles: reports.bodyCandidates.profiles,
        fullFrameCandidateStatus: {
          status: "incomplete",
          ackHex: null,
          safeToSend: false,
          reason: "endpoint values are not closed and seq/header still use mirror-style candidates",
        },
      },
      unknowns: ["confirmed endpoint value/port mapping", "direct full typeA response construction evidence", "direct seqLE validation/generation rule"],
    }),
  };
  model.reason = "Final Stage 13 gap analysis has medium typeA/header candidates and low-medium seq candidate, but endpoint values remain unclosed.";
  model.stage14ReadinessChecklist = reports.checklist;
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.json`), `${JSON.stringify(model, null, 2)}\n`, "utf8");
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.md`), ["# ACK Structure Model", "", "```json", JSON.stringify(model, null, 2), "```", ""].join("\n"), "utf8");
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const frameReport = readJsonSafe(path.join(outDir, `login-ack-frame-model-analysis-${DATE_STEM}.json`));
  const reports = buildReports(frameReport);
  const gate = {
    canEnterStage14: reports.checklist.every((item) => item.pass),
    conclusion: "不能进入可发送 ACK 构造，只能继续反汇编数据流。",
    blockingItems: reports.checklist.filter((item) => !item.pass),
  };
  const mainReport = {
    generatedAt: new Date().toISOString(),
    overview: "Stage 13 final gap analysis closes several candidates but still leaves endpoint values and direct full-frame evidence unresolved.",
    typeA: reports.typeA,
    seqLE: reports.seq,
    offset8to19: reports.header,
    endpointFieldIdMapping: reports.endpoints,
    bodyOnlyCandidates: reports.bodyCandidates,
    fullFrameCandidateStatus: { status: "incomplete", ackHex: null, safeToSend: false, doNotSend: true },
    stage14ReadinessChecklist: reports.checklist,
    stage14Gate: gate,
    safety: {
      networkAckSent: false,
      sendOneShotAckRun: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      automaticAckAdded: false,
      sendableAckHexGenerated: false,
    },
  };

  const paths = {};
  paths.typeA = writeJsonMd(outDir, "typea-110047-evidence", "TypeA 110047 Evidence", reports.typeA, [
    `Final candidate: \`${reports.typeA.finalCandidate}\``,
    `Confidence: ${reports.typeA.confidence}`,
    "",
    ...reports.typeA.evidence.map((item) => `- ${item}`),
  ]);
  paths.seq = writeJsonMd(outDir, "login-ack-seq-strategy-final", "Login ACK Seq Strategy Final", reports.seq, [
    `Candidate: ${reports.seq.seqStrategyCandidate}`,
    `Confidence: ${reports.seq.confidence}`,
    "",
    reports.seq.conclusion,
  ]);
  paths.header = writeJsonMd(outDir, "login-ack-header-8-19-final", "Login ACK Header 8..19 Final", reports.header, [
    `Candidate: \`${reports.header.finalCandidate}\``,
    `Confidence: ${reports.header.confidence}`,
  ]);
  paths.endpoints = writeJsonMd(outDir, "login-ack-endpoint-fieldid-final", "Login ACK Endpoint FieldId Final", reports.endpoints, [
    reports.endpoints.finalPortConclusion,
  ]);
  paths.bodyCandidates = writeJsonMd(outDir, "login-ack-body-candidates", "Login ACK Body Candidates", reports.bodyCandidates, [
    "Body-only candidates. These are not complete frames and must not be sent.",
  ]);
  paths.main = writeJsonMd(outDir, "login-ack-final-gap-analysis", "Login ACK Final Gap Analysis", mainReport, [
    "## Summary",
    "",
    mainReport.overview,
    "",
    "## Stage 14 Gate",
    "",
    gate.conclusion,
  ]);
  updateAckModel(outDir, reports);
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
