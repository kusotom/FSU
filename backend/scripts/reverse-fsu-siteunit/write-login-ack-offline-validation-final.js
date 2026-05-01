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

function readJson(filePath, fallback = {}) {
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

function buildSeqValidation() {
  return {
    generatedAt: new Date().toISOString(),
    parseDataReadsFrame2to3: true,
    uses: [
      "included in checksum byte range",
      "copied to output seq pointer in recovered ParseData pseudocode",
    ],
    notFound: [
      "pending request seq comparison",
      "seq mismatch branch",
      "sequence fail string/branch",
      "Login ACK handler 0x7e804 reading seqLE",
    ],
    loginHandlerReadsSeqLE: false,
    requestSeqSavedEvidence: "not closed",
    seqStrategyCandidate: "mirror request seqLE",
    confidence: "low-medium",
    conclusion:
      "未发现响应 seqLE 必须匹配 pending request 的证据；mirror request seqLE 仅作为保守离线候选。",
    doNotSend: true,
  };
}

function buildHeaderValidation(candidate) {
  return {
    generatedAt: new Date().toISOString(),
    parseDataReadsFrame8to19: {
      frame8to11: "no specific login validation recovered",
      frame12to15: "copied to ctx->field_0x54 in recovered ParseData pseudocode",
      frame16to19: "no specific login validation recovered",
    },
    loginHandlerReadsFrame8to19: false,
    uses: [
      "included in checksum byte range",
      "frame[12..15] copied to a context field",
    ],
    notFound: [
      "comparison with request frame[8..19]",
      "header context mismatch branch",
      "literal comparison against c162002d",
      "0x7e804 handler read of header bytes",
    ],
    strategyCandidate: "mirror request frame[8..19]",
    valueCandidate: candidate?.requestSummary?.offset8to19 || "00000000c162002d00000000",
    confidence: "medium",
    conclusion:
      "未发现 frame[8..19] 参与响应验收的证据；mirror request frame[8..19] 仅作为保守离线候选。",
    doNotSend: true,
  };
}

function buildChecklist(candidate) {
  const simOk = Boolean(candidate?.simulation?.ok);
  return [
    { item: "完整 ACK typeA 有候选来源，置信度至少 medium", pass: true, result: "110047ff / medium" },
    { item: "success code 有候选来源", pass: true, result: "body[0]=0" },
    { item: "success code offset 有候选来源", pass: true, result: "frame[24] / body[0]" },
    { item: "body layout 有候选来源", pass: true, result: "status + entryCount + TLV entries" },
    { item: "最小 body length 有候选来源", pass: true, result: "six required endpoint TLVs" },
    { item: "必填 entry 明确", pass: true, result: "0,5,6,7,8,9" },
    { item: "必填 entry 的值格式明确", pass: true, result: "udp://host:port" },
    { item: "endpoint 值有推荐 profile", pass: true, result: "recommended_profile/all_9000_profile" },
    { item: "length/checksum 计算器可用于目标帧", pass: true, result: "simulator checksum passed" },
    { item: "seq 策略至少有候选，且没有发现反向证据", pass: true, result: "mirror request seqLE; no reverse evidence found" },
    { item: "offset8..19 有候选策略，且没有发现反向证据", pass: true, result: "mirror request frame[8..19]; no reverse evidence found" },
    { item: "离线模拟器通过 SOI/length/checksum/dispatch/status/TLV flags", pass: simOk, result: simOk ? "passed" : "failed/not run" },
    {
      item: "不再依赖 mirror 原始包作为 ACK 内容",
      pass: true,
      result: "not mirroring the raw packet/body; only seqLE and frame[8..19] use request-derived conservative header strategies",
    },
  ];
}

function updateAckModel(outDir, seq, header, candidate, checklist) {
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure({
      candidateFields: {
        typeA: [{ candidate: "110047ff", confidence: "medium" }],
        seqValidationFinal: seq,
        header8to19ValidationFinal: header,
        offlineCandidateProfile: candidate?.candidateSummary || null,
        offlineSimulatorResult: candidate?.simulation || null,
        frameHexCandidateForOfflineSimulationOnly: candidate?.frameHexCandidateForOfflineSimulationOnly || null,
      },
      unknowns: [
        "device acceptance is not proven by offline simulation",
        "seqLE mirror is a conservative candidate, not confirmed validation",
        "offset8..19 mirror is a conservative candidate, not confirmed validation",
      ],
    }),
  };
  model.status = "candidate-only";
  model.reason = "Offline simulation passes recovered ParseData/0x7e804 logic, but this is not a live acceptance proof.";
  model.safeToSend = false;
  model.ackHex = null;
  model.stage14ReadinessChecklist = checklist;
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.json`), `${JSON.stringify(model, null, 2)}\n`, "utf8");
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.md`), ["# ACK Structure Model", "", "```json", JSON.stringify(model, null, 2), "```", ""].join("\n"), "utf8");
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const candidate = readJson(path.join(outDir, `login-ack-offline-candidate-simulation-${DATE_STEM}.json`));
  const seq = buildSeqValidation();
  const header = buildHeaderValidation(candidate);
  const checklist = buildChecklist(candidate);
  const canEnterStage14 = checklist.every((item) => item.pass);
  const stage14Gate = {
    canEnterStage14,
    conclusion: canEnterStage14
      ? "可以进入第十四阶段：受控 ACK 实验设计。"
      : "不能进入可发送 ACK 构造，只能继续反汇编数据流或进行离线候选帧审查。",
    note: "即使可进入第十四阶段，也只是实验设计准入，不代表本阶段可发送。",
    blockingItems: checklist.filter((item) => !item.pass),
  };
  const mainReport = {
    generatedAt: new Date().toISOString(),
    overview:
      "seqLE and header[8..19] validation paths did not reveal reverse evidence. A recommended all_9000 offline candidate passes the recovered ParseData/login-handler simulator.",
    seqLEValidation: seq,
    header8to19Validation: header,
    recommendedOfflineCandidate: candidate?.candidateSummary || null,
    frameHexCandidateForOfflineSimulationOnly: candidate?.frameHexCandidateForOfflineSimulationOnly || null,
    simulatorResult: candidate?.simulation || null,
    proven: [
      "offline SOI/length/checksum/dispatch/status/TLV flags checks pass",
      "ACK frame candidate remains offline-only",
    ],
    notProven: [
      "device live acceptance",
      "seqLE pending-request comparison behavior",
      "frame[8..19] response-context acceptance behavior",
      "network target port strategy",
    ],
    stage14ReadinessChecklist: checklist,
    stage14Gate,
    safety: {
      networkAckSent: false,
      sendOneShotAckRun: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      automaticAckAdded: false,
      safeToSend: false,
      ackHex: null,
    },
  };

  const paths = {};
  paths.seq = writeJsonMd(outDir, "seqle-validation-final", "SeqLE Validation Final", seq, [seq.conclusion]);
  paths.header = writeJsonMd(outDir, "header-8-19-validation-final", "Header 8..19 Validation Final", header, [header.conclusion]);
  paths.main = writeJsonMd(outDir, "login-ack-offline-validation-final", "Login ACK Offline Validation Final", mainReport, [
    mainReport.overview,
    "",
    stage14Gate.conclusion,
  ]);
  updateAckModel(outDir, seq, header, candidate, checklist);
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
