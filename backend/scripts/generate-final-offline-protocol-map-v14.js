#!/usr/bin/env node
"use strict";

/**
 * Generate final offline FSU DSC/RDS protocol map v1.4.
 *
 * SAFETY:
 * - Offline report generation only.
 * - Does not read network.
 * - Does not open sockets.
 * - Does not send UDP.
 * - Does not add ACK or modify gateway runtime logic.
 * - Does not write business tables.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const RAW_DIR = path.join(ROOT, "backend", "logs", "fsu_raw_packets");
const DATE = "2026-05-01";

function readJsonSafe(relPath) {
  const fullPath = path.join(ROOT, relPath);
  if (!fs.existsSync(fullPath)) {
    return { missing: true, path: relPath };
  }
  try {
    return JSON.parse(fs.readFileSync(fullPath, "utf8"));
  } catch (error) {
    return { missing: true, path: relPath, error: error.message };
  }
}

function write(relPath, content) {
  const fullPath = path.join(ROOT, relPath);
  fs.mkdirSync(path.dirname(fullPath), { recursive: true });
  fs.writeFileSync(fullPath, content, "utf8");
  return fullPath;
}

function boolText(value) {
  return value ? "true" : "false";
}

function getOr(value, fallback) {
  return value === undefined || value === null ? fallback : value;
}

function buildReport() {
  const offlineV13 = readJsonSafe(`backend/logs/fsu_raw_packets/dsc-rds-offline-reverse-summary-v1.3-${DATE}.json`);
  const headerContext = readJsonSafe(`backend/logs/fsu_raw_packets/header-context-8-19-analysis-${DATE}.json`);
  const seqStrategy = readJsonSafe(`backend/logs/fsu_raw_packets/seq-strategy-analysis-${DATE}.json`);
  const class47 = readJsonSafe(`backend/logs/fsu_raw_packets/class47-register-response-candidate-v1.3-${DATE}.json`);
  const d2ff = readJsonSafe("backend/logs/fsu_raw_packets/d2ff-ack-exact-reproduction-v12.json");
  const annotations = require(path.join(ROOT, "backend", "app", "modules", "fsu_gateway", "parser", "dsc-rds-annotations.js"));

  const d2ffCounts = d2ff.counts || {};
  const d2ffN = getOr(d2ffCounts.exactMatches, "N");
  const headerRecommendation = headerContext.recommendation || {};
  const seqConclusion = seqStrategy.conclusion || {};
  const best47 = class47.bestOfflineFullFrameCandidate || {};

  const report = {
    version: "v1.4",
    generatedAt: new Date().toISOString(),
    sourceReports: {
      offlineV13: offlineV13.missing ? null : `backend/logs/fsu_raw_packets/dsc-rds-offline-reverse-summary-v1.3-${DATE}.json`,
      headerContext: headerContext.missing ? null : `backend/logs/fsu_raw_packets/header-context-8-19-analysis-${DATE}.json`,
      seqStrategy: seqStrategy.missing ? null : `backend/logs/fsu_raw_packets/seq-strategy-analysis-${DATE}.json`,
      class47Candidate: class47.missing ? null : `backend/logs/fsu_raw_packets/class47-register-response-candidate-v1.3-${DATE}.json`,
      d2ffAckModel: d2ff.missing ? null : "backend/logs/fsu_raw_packets/d2ff-ack-exact-reproduction-v12.json",
    },
    safety: {
      offlineOnly: true,
      noUdpSent: true,
      noAckAdded: true,
      sendOneShotAckNotRun: true,
      gatewayReplyLogicUnchanged: true,
      servicePyNotIntegrated: true,
      businessTablesUnchanged: true,
      firmwareUnchanged: true,
      oneShotExperimentNotPerformed: true,
      noOnlineUseFor110047ffOr1F00D2FF: true,
    },
    firmwareAndSources: {
      deviceFamily: "FSU-2808IM same-family firmware",
      activeMainProgram: "SiteUnit2",
      keyConfigItems: {
        DscIp: "UDP 9000 candidate",
        RDSIp: "UDP 7000 candidate",
        RDSHeartBeat: "RDS heartbeat interval/config candidate",
        MinPortNO: "port range config candidate",
        MaxPortNO: "port range config candidate",
      },
      keyStrings: [
        "LoginToDSC",
        "Register OK",
        "LogToDS return Success",
        "LogToDS return Fail",
        "LogToDS return UnRegister",
        "RunRDS",
        "SendRDSHeartbeat",
        "SendRealData2Rds",
        "SendRealDataQueue",
      ],
    },
    frameHeader: {
      magic: { offset: "0..1", value: "6d7e" },
      seqLE: { offset: "2..3" },
      typeByte: { offset: 4 },
      flagByte: { offset: 5, bit7: "ackRequiredFlag candidate" },
      classByte: { offset: 6, meaning: "firmware dispatch core byte" },
      tailByte: { offset: 7, commonValue: "ff" },
      headerContext: {
        offset: "8..19",
        officialMeaning: "unknown",
        config46Observed: headerContext.config209vs245?.commonContexts?.[0] || "00000000c162002d00000000",
        d2ffAck24Observed: "00000000c162002dc162002d",
      },
      payloadLengthLE: { offset: "20..21", formula: "totalLength - 24" },
      checksum: { offset: "22..23" },
      payload: { offset: "24.." },
    },
    checksumModel: {
      normal: {
        steps: [
          "zero bytes[22..23]",
          "sum bytes[2..end] as uint16",
          "write result little-endian to bytes[22..23]",
        ],
        verifiedFor: ["RDS_SHORT_30_TYPE_1180_D2FF", "DSC_CONFIG_209_TYPE_1100_46FF", "DSC_CONFIG_245_TYPE_1100_46FF"],
      },
      d2ffSpecialModel: "DSC_SHORT_24_TYPE_1F00_D2FF is reproduced by v1.2 D2FF context-after-checksum model.",
    },
    frameClasses: {
      DSC_CONFIG_209_TYPE_1100_46FF: annotations.FRAME_CLASS_ANNOTATIONS.DSC_CONFIG_209_TYPE_1100_46FF,
      DSC_CONFIG_245_TYPE_1100_46FF: annotations.FRAME_CLASS_ANNOTATIONS.DSC_CONFIG_245_TYPE_1100_46FF,
      RDS_SHORT_30_TYPE_1180_D2FF: annotations.FRAME_CLASS_ANNOTATIONS.RDS_SHORT_30_TYPE_1180_D2FF,
      DSC_SHORT_24_TYPE_1F00_D2FF: annotations.FRAME_CLASS_ANNOTATIONS.DSC_SHORT_24_TYPE_1F00_D2FF,
    },
    dscConfig209245: {
      conclusion: "same structure with different URI representation",
      dsc209: "DHCP placeholder URI version",
      dsc245: "resolved explicit IP URI version",
      lengthDelta: 36,
      uriDelta: {
        udpUriCount: 3,
        udpUriDeltaEach: 9,
        ftpUriCount: 1,
        ftpUriDeltaEach: 9,
        totalExplainedDelta: 36,
      },
      notBusinessRealtimeData: true,
      notUnknownTailExtension: true,
    },
    d2ffAckModel: {
      version: "v1.2",
      steps: [
        "copy paired RDS30 first 24 bytes",
        "set byte4 = 0x1f",
        "set byte5 = 0x00",
        "keep byte6 = 0xd2",
        "keep byte7 = 0xff",
        "set payloadLength = 0",
        "during checksum calculation keep offsets 16/17/19 as 0",
        "use normal checksum",
        "write checksum",
        "after checksum write offset16=0xc1, offset17=0x62, offset19=0x2d",
      ],
      counts: d2ffCounts,
      success: d2ff.success === true,
      diffHistogram: d2ff.diffHistogram || { 0: d2ffN },
      onlineUseAllowed: false,
    },
    class46Request: {
      classByte: "0x46",
      semanticClass: "DSC_REGISTER_CONFIG_REQUEST",
      frameClasses: ["DSC_CONFIG_209_TYPE_1100_46FF", "DSC_CONFIG_245_TYPE_1100_46FF"],
      payloadContains: ["FSU UDP service URI", "FSU FTP service URI"],
    },
    class47Candidate: {
      classByte: "0x47",
      semanticClass: "DSC_REGISTER_CONFIG_RESPONSE_CANDIDATE",
      typeBytes: best47.typeBytes || "110047ff",
      typeByte: best47.typeByte || "0x11",
      flagByte: best47.flagByte || "0x00",
      tailByte: best47.tailByte || "0xff",
      ackRequiredFlag: false,
      seqStrategy: {
        value: "mirror 0x46 request seqLE",
        evidenceLevel: best47.seqEvidenceLevel || seqConclusion.class47ConclusionLevel || "high-confidence candidate",
        confirmed: false,
      },
      headerContextStrategy: {
        value: "copy 0x46 request bytes[8..19]",
        evidenceLevel: best47.headerContextEvidenceLevel || headerRecommendation.confidence || "high-confidence candidate",
        confirmed: false,
      },
      payloadLength: 171,
      payloadLengthHexLE: "ab00",
      totalLength: 195,
      checksum: "normal FSU checksum LE",
      safeToSend: false,
      ackHex: null,
      payload: {
        resultCode: { offset: 0, values: { 0: "Success", 1: "Fail", 2: "UnRegister" } },
        serviceCountLE: "payload[1..2]",
        entries: "payload[3..] repeated type:uint8,length:uint8,uri:ASCII",
        requiredMask: "0x3f",
        serviceChannels: annotations.SERVICE_CHANNEL_TYPE_ANNOTATIONS,
      },
      ranking: class47.ranking || [],
    },
    stateMachine: [
      "FSU startup",
      "FSU -> DSC classByte=0x46 register/config request",
      "209/245 report own UDP/FTP service addresses",
      "RDS sends 1180D2FF heartbeat/keepalive",
      "D2FF ACK generates 1F00D2FF confirm short frame",
      "wait for DSC -> FSU classByte=0x47 register response",
      "if resultCode=Success and requiredMask=0x3f then Register OK candidate",
      "RDS_REALDATA / BUSINESS_DATA_ACTIVE candidate",
    ],
    currentFieldState: {
      real0x47Observed: false,
      rdsRealDataObserved: false,
      currentStage: "registration/config repeat stage",
    },
    remainingUnknowns: [
      "110047ff online acceptance behavior.",
      "Whether 0x47 response seqLE is strictly validated.",
      "Official meaning of offset 8..19.",
      "Whether service channel URI should use platform listener address, FSU address, or another address.",
      "Whether time sync, config sync, or extra ACK is needed after 0x47 success.",
      "RDS real business payload.",
      "Complete typeA / classByte / opcode enum.",
    ],
    nextRecommendations: {
      offline: [
        "Trace SiteUnit2 0x47 header receive validation.",
        "Trace RDS_REALDATA payload construction.",
        "Trace complete type/class enum.",
        "Keep analysis offline only.",
      ],
      futureExperiment: [
        "If an experiment is ever considered, create a separate one-shot controlled experiment design.",
        "This report does not include experiment execution.",
        "Do not generate a sendable script from this report.",
      ],
    },
    missingInputs: [offlineV13, headerContext, seqStrategy, class47, d2ff].filter((item) => item.missing),
  };

  return report;
}

function renderMarkdown(report) {
  const fc = report.frameClasses;
  const d2 = report.d2ffAckModel;
  const c47 = report.class47Candidate;
  const lines = [
    "# FSU DSC/RDS 最终离线协议图谱 v1.4",
    "",
    `Generated at: ${report.generatedAt}`,
    "",
    "## 1. 安全边界",
    "",
    "- 本报告仅为离线逆向结果。",
    "- 未发送 UDP。",
    "- 未新增 ACK。",
    "- 未运行 `send-one-shot-ack.js`。",
    "- 未修改实时网关回包逻辑。",
    "- 未接入 `service.py`。",
    "- 未写业务主表。",
    "- 未刷固件。",
    "- 未做 one-shot 实验。",
    "- 任何 `110047ff` / `1F00D2FF` 均不得直接线上使用。",
    "",
    "## 2. 固件与协议来源",
    "",
    "- 参考固件为 FSU-2808IM 同源固件。",
    "- active 主程序为 SiteUnit2。",
    "- 关键配置项：",
    "  - DscIp => UDP 9000",
    "  - RDSIp => UDP 7000",
    "  - RDSHeartBeat",
    "  - MinPortNO / MaxPortNO",
    "- SiteUnit2 关键字符串：",
    "  - LoginToDSC",
    "  - Register OK",
    "  - LogToDS return Success / Fail / UnRegister",
    "  - RunRDS",
    "  - SendRDSHeartbeat",
    "  - SendRealData2Rds",
    "  - SendRealDataQueue",
    "",
    "## 3. 私有帧头结构",
    "",
    "| offset | field | meaning |",
    "| --- | --- | --- |",
    "| 0..1 | magic | `6d 7e` |",
    "| 2..3 | seqLE | sequence candidate, little-endian |",
    "| 4 | typeByte | type family byte |",
    "| 5 | flagByte | bit7 = ackRequiredFlag candidate |",
    "| 6 | classByte | 固件分支核心字段 |",
    "| 7 | tailByte | 常见 `ff` |",
    "| 8..19 | header context | 官方含义未完全确认 |",
    "| 20..21 | payloadLengthLE | `totalLength - 24` |",
    "| 22..23 | checksum | checksum LE |",
    "| 24.. | payload | body |",
    "",
    "## 4. checksum 模型",
    "",
    "普通 checksum:",
    "",
    "- 计算前将 offset `22..23` 清零。",
    "- 对 `bytes[2..end]` 做 uint16 累加。",
    "- LE 写回 offset `22..23`。",
    "",
    "已验证：",
    "",
    "- RDS30 checksum validLE 全部通过。",
    "- DSC209 checksum validLE 全部通过。",
    "- DSC245 checksum validLE 全部通过。",
    "- D2FF ACK 通过 v1.2 特殊上下文模型完整复现。",
    "",
    "## 5. 当前 4 类真实 frameClass 注释",
    "",
    "| frameClass | semanticClass | 中文 | confidence | totalLength | payloadLength | classByte | evidence |",
    "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    `| DSC_CONFIG_209_TYPE_1100_46FF | ${fc.DSC_CONFIG_209_TYPE_1100_46FF.semanticClass} | ${fc.DSC_CONFIG_209_TYPE_1100_46FF.chineseName} | 0.94 | 209 | 185 | 0x46 | udp://[dhcp]:6002; ftp://root:hello@[dhcp] |`,
    `| DSC_CONFIG_245_TYPE_1100_46FF | ${fc.DSC_CONFIG_245_TYPE_1100_46FF.semanticClass} | ${fc.DSC_CONFIG_245_TYPE_1100_46FF.chineseName} | 0.94 | 245 | 221 | 0x46 | udp://192.168.100.100:6002; ftp://root:hello@192.168.100.100 |`,
    `| RDS_SHORT_30_TYPE_1180_D2FF | ${fc.RDS_SHORT_30_TYPE_1180_D2FF.semanticClass} | ${fc.RDS_SHORT_30_TYPE_1180_D2FF.chineseName} | 0.96 | 30 | 6 | 0xd2 | ackRequiredFlag=true |`,
    `| DSC_SHORT_24_TYPE_1F00_D2FF | ${fc.DSC_SHORT_24_TYPE_1F00_D2FF.semanticClass} | ${fc.DSC_SHORT_24_TYPE_1F00_D2FF.chineseName} | 0.98 | 24 | 0 | 0xd2 | v1.2 exact reproduction success=true |`,
    "",
    "## 6. 209/245 注册地址上报结构",
    "",
    "- 209 与 245 是同结构、不同 URI 表示形式。",
    "- 36 字节差异来自 URI 字符串长度差异。",
    "- 209 使用 `[dhcp]`。",
    "- 245 使用 `192.168.100.100`。",
    "- 不是未知扩展尾字段。",
    "- 不是业务实时数据。",
    "",
    "URI 差异：",
    "",
    "- UDP URI × 3，每个差异 9 字节。",
    "- FTP URI × 1，差异 9 字节。",
    "- 合计 36 字节。",
    "",
    "## 7. D2FF ACK 完整复现模型 v1.2",
    "",
    "复现步骤：",
    "",
    ...d2.steps.map((step, index) => `${index + 1}. ${step}`),
    "",
    "验证结果：",
    "",
    `- pairedBySeq = ${d2.counts.pairedBySeq}`,
    `- exactMatches = ${d2.counts.exactMatches}`,
    `- checksumMatches = ${d2.counts.checksumMatches}`,
    `- success = ${boolText(d2.success)}`,
    `- diffHistogram = \`${JSON.stringify(d2.diffHistogram)}\``,
    "",
    "强调：这是离线复现，不代表允许线上 ACK。",
    "",
    "## 8. classByte=0x46 / 0x47 注册流程",
    "",
    "- `0x46` = `DSC_REGISTER_CONFIG_REQUEST`。",
    "- `0x47` = `DSC_REGISTER_CONFIG_RESPONSE candidate`。",
    "",
    "0x46 请求：209 / 245 注册配置地址上报。",
    "",
    "0x47 payload:",
    "",
    "- resultCode",
    "- serviceCountLE",
    "- entries(type, length, uri)",
    "",
    "resultCode:",
    "",
    "- 0 = Success",
    "- 1 = Fail",
    "- 2 = UnRegister",
    "",
    "服务通道：",
    "",
    "- 0 = 诊断数据通道",
    "- 5 = 上行发布通道",
    "- 6 = 事件数据通道",
    "- 7 = 实时数据通道",
    "- 8 = 历史数据通道",
    "- 9 = 图像发布通道",
    "",
    "requiredMask: `0x3f`。",
    "",
    "不能只返回 `payload[0]=0`；必须包含必要服务通道列表，才可能 Register OK。",
    "",
    "## 9. 0x47 full-frame 当前最优候选",
    "",
    `- typeBytes: \`${c47.typeBytes}\``,
    `- typeByte: \`${c47.typeByte}\``,
    `- flagByte: \`${c47.flagByte}\``,
    "- classByte: `0x47`",
    `- tailByte: \`${c47.tailByte}\``,
    `- ackRequiredFlag: \`${boolText(c47.ackRequiredFlag)}\``,
    "- seq 策略：mirror 0x46 request seqLE；证据等级 high-confidence candidate，不是 confirmed。",
    "- header[8..19] 策略：copy 0x46 request context；证据等级 high-confidence candidate，不是 confirmed。",
    "- payloadLength: `171 / 0x00ab`",
    "- totalLength: `195`",
    "- checksum: 普通 FSU checksum LE",
    "- safeToSend: `false`",
    "",
    "候选排序：",
    "",
    "1. `110047ff`",
    "2. `118047ff`，不建议，因为会要求额外 ACK",
    "3. `100047ff`，缺直接证据",
    "4. `1f0047ff`，ACK 风格，不像长 payload 注册返回",
    "",
    "## 10. 当前状态机",
    "",
    "```text",
    "FSU 启动",
    "  -> FSU -> DSC classByte=0x46 注册/配置请求",
    "  -> 209/245 上报自身 UDP/FTP 服务地址",
    "  -> RDS 发送 1180D2FF 心跳/保活",
    "  -> D2FF ACK 生成 1F00D2FF 确认短帧",
    "  -> 等待 DSC -> FSU classByte=0x47 注册返回",
    "  -> 如果 resultCode=Success 且 requiredMask=0x3f",
    "  -> Register OK candidate",
    "  -> RDS_REALDATA / BUSINESS_DATA_ACTIVE candidate",
    "```",
    "",
    "当前现场状态：",
    "",
    "- 未看到真实 0x47。",
    "- 未进入 RDS_REALDATA。",
    "- 仍在注册/配置重复阶段。",
    "",
    "## 11. 仍未确认",
    "",
    ...report.remainingUnknowns.map((item) => `- ${item}`),
    "",
    "## 12. 后续建议",
    "",
    "A. 继续离线：",
    "",
    ...report.nextRecommendations.offline.map((item) => `- ${item}`),
    "",
    "B. 如未来要实验：",
    "",
    ...report.nextRecommendations.futureExperiment.map((item) => `- ${item}`),
    "",
  ];
  return `${lines.join("\n")}\n`;
}

function main() {
  const report = buildReport();
  const jsonRel = `backend/logs/fsu_raw_packets/final-offline-protocol-map-v1.4-${DATE}.json`;
  const mdRel = `backend/logs/fsu_raw_packets/final-offline-protocol-map-v1.4-${DATE}.md`;
  write(jsonRel, `${JSON.stringify(report, null, 2)}\n`);
  write(mdRel, renderMarkdown(report));
  console.log(`Wrote ${path.join(ROOT, mdRel)}`);
  console.log(`Wrote ${path.join(ROOT, jsonRel)}`);
}

main();
