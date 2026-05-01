"use strict";

const SAFETY_NOTE = "只读逆向注释，未由厂商协议文档确认；不代表线上 ACK/回包已启用。";
const OFFLINE_PROTOCOL_MAP_VERSION = "v1.4";
const FINAL_OFFLINE_SUMMARY_PATH = "backend/logs/fsu_raw_packets/final-offline-protocol-map-v1.4-2026-05-01.md";

const HEADER_FIELD_ANNOTATIONS = {
  magic: {
    offset: "0..1",
    name: "magic_or_protocol_header",
    value: "6d7e",
    confidence: 0.95,
    notes: [SAFETY_NOTE],
  },
  seqLE: {
    offset: "2..3",
    name: "seqLE",
    meaning: "little-endian sequence candidate",
    confidence: 0.75,
    notes: [
      "离线候选 ACK 使用 mirror request seqLE 作为保守策略，但线上验收行为未确认。",
      SAFETY_NOTE,
    ],
  },
  typeByte: {
    offset: 4,
    name: "typeByte",
    confidence: 0.85,
    notes: [SAFETY_NOTE],
  },
  flagByte: {
    offset: 5,
    name: "flagByte",
    confidence: 0.75,
    notes: [
      "0x80 高位被标注为 ackRequiredFlag 候选；官方含义未确认。",
      SAFETY_NOTE,
    ],
  },
  classByte: {
    offset: 6,
    name: "classByte / opcode branch byte",
    confidence: 0.9,
    notes: [
      "SiteUnit 离线反汇编显示该字节参与 ParseData 分发，例如 0x47 进入登录状态处理分支。",
      SAFETY_NOTE,
    ],
  },
  tailByte: {
    offset: 7,
    name: "tailByte",
    commonValue: "ff",
    confidence: 0.8,
    notes: [SAFETY_NOTE],
  },
  payloadLengthLE: {
    offset: "20..21",
    name: "payloadLengthLE",
    endian: "little",
    formula: "totalLength - 24",
    confidence: 0.95,
    notes: [SAFETY_NOTE],
  },
  checksum: {
    offset: "22..23",
    name: "checksumLE",
    formula: "uint16 sum(bytes[2..end]) with bytes[22..23] zeroed before calculation",
    confidence: 0.95,
    notes: [
      "该通用 checksum 公式对 RDS_SHORT_30、DSC_CONFIG_209、DSC_CONFIG_245 命中；DSC_SHORT_24 属于特殊 D2FF 确认短帧复现模型。",
      SAFETY_NOTE,
    ],
  },
  body: {
    offset: "24..",
    name: "payload/body",
    confidence: 0.95,
    notes: [SAFETY_NOTE],
  },
};

const CHANNEL_ANNOTATIONS = {
  UDP_DSC: {
    channel: "UDP_DSC",
    semanticClass: "DSC_CONTROL_REGISTER_CONFIG_CANDIDATE",
    chineseName: "DSC主控/注册/配置/心跳/命令候选通道",
    confidence: 0.9,
    evidence: [
      "真实设备 UDP_DSC 持续向平台 9000 端口上报 24/209/245 字节帧。",
      "DSC_CONFIG_209/245 payload 包含 udp:// 与 ftp:// 服务地址 URI 字符串。",
      "SiteUnit 离线证据包含 LoginToDSC、Register OK、LogToDS return Success/Fail/UnRegister、SendHeartbeat 等字符串与控制流。",
    ],
    notes: [SAFETY_NOTE],
    sourceHints: ["raw_packet", "siteunit_static_reverse", "dsc_config_uri_diff"],
    towerWebEvidence: [],
  },
  UDP_RDS: {
    channel: "UDP_RDS",
    semanticClass: "RDS_REALTIME_KEEPALIVE_CANDIDATE",
    chineseName: "RDS实时数据/心跳/保活候选通道",
    confidence: 0.92,
    evidence: [
      "真实设备 UDP_RDS 持续向平台 7000 端口上报 30 字节短帧。",
      "SiteUnit 离线证据包含 RunRDS、SendRDSHeartbeat、SendRealData2Rds、SendRealDataQueue 等字符串。",
      "当前抓包尚未出现 RDS 非 30 字节业务帧。",
    ],
    notes: [SAFETY_NOTE],
    sourceHints: ["raw_packet", "siteunit_static_reverse", "siteunit_config"],
    towerWebEvidence: [],
  },
};

const FRAME_CLASS_ANNOTATIONS = {
  DSC_CONFIG_209_TYPE_1100_46FF: {
    frameClass: "DSC_CONFIG_209_TYPE_1100_46FF",
    semanticClass: "DSC_REGISTER_CONFIG_DHCP_PLACEHOLDER",
    chineseName: "DSC注册/配置帧（DHCP占位地址版本）",
    confidence: 0.94,
    channel: "UDP_DSC",
    totalLength: 209,
    payloadLengthLE: 185,
    typeA: "1100_46FF",
    typeBytes: { typeByte: 0x11, flagByte: 0x00, classByte: 0x46, tailByte: 0xff },
    businessDataConfirmed: false,
    evidence: [
      "真实设备周期性重复发送 totalLength=209、typeA=1100_46FF 的 UDP_DSC 长帧。",
      "payload 中可提取 udp://[dhcp]:6002 与 ftp://root:hello@[dhcp] 等 URI。",
      "209/245 长度差异可由 [dhcp] 与 192.168.100.100 的 URI 字符串长度差异解释。",
      "SiteUnit 离线证据将 0x46 请求与 LoginToDSC / Register OK 流程关联。",
    ],
    notes: [
      "暂不判定为业务数据帧。",
      "payload 每个 offset 的官方字段语义仍未完全确认。",
      SAFETY_NOTE,
    ],
    confidenceNotes: [
      "置信度来自 raw log 周期性、URI 内容、209/245 diff、SiteUnit 静态逆向的交叉证据。",
      "不证明平台成功 ACK 的完整二进制格式或线上接受行为。",
    ],
    sourceHints: ["raw_packet", "dsc_config_uri_diff", "siteunit_static_reverse"],
    towerWebEvidence: [],
  },
  DSC_CONFIG_245_TYPE_1100_46FF: {
    frameClass: "DSC_CONFIG_245_TYPE_1100_46FF",
    semanticClass: "DSC_REGISTER_CONFIG_RESOLVED_IP",
    chineseName: "DSC注册/配置帧（实际IP地址版本）",
    confidence: 0.94,
    channel: "UDP_DSC",
    totalLength: 245,
    payloadLengthLE: 221,
    typeA: "1100_46FF",
    typeBytes: { typeByte: 0x11, flagByte: 0x00, classByte: 0x46, tailByte: 0xff },
    businessDataConfirmed: false,
    evidence: [
      "真实设备周期性重复发送 totalLength=245、typeA=1100_46FF 的 UDP_DSC 长帧。",
      "payload 中可提取 udp://192.168.100.100:6002 与 ftp://root:hello@192.168.100.100 等 URI。",
      "与 209 帧同 type bytes，36 字节长度差异由 3 个 udp URI 与 1 个 ftp URI 的地址字符串长度差异解释。",
      "SiteUnit 离线证据将 0x46 请求与 LoginToDSC / Register OK 流程关联。",
    ],
    notes: [
      "更像同结构不同 URI 表示形式，而不是 245 额外尾部字段。",
      "暂不判定为业务数据帧。",
      "payload 每个 offset 的官方字段语义仍未完全确认。",
      SAFETY_NOTE,
    ],
    confidenceNotes: [
      "置信度来自 raw log 周期性、URI 内容、209/245 diff、SiteUnit 静态逆向的交叉证据。",
      "不证明平台成功 ACK 的完整二进制格式或线上接受行为。",
    ],
    sourceHints: ["raw_packet", "dsc_config_uri_diff", "siteunit_static_reverse"],
    towerWebEvidence: [],
  },
  DSC_SHORT_24_TYPE_1F00_D2FF: {
    frameClass: "DSC_SHORT_24_TYPE_1F00_D2FF",
    semanticClass: "D2FF_ACK_CONFIRM_SHORT_REPRODUCED",
    chineseName: "D2FF类确认短帧，已由RDS 30帧完整复现",
    confidence: 0.98,
    channel: "UDP_DSC",
    totalLength: 24,
    payloadLengthLE: 0,
    typeA: "1F00_D2FF",
    typeBytes: { typeByte: 0x1f, flagByte: 0x00, classByte: 0xd2, tailByte: 0xff },
    businessDataConfirmed: false,
    evidence: [
      "真实设备周期性重复发送 totalLength=24、typeA=1F00_D2FF 的 UDP_DSC 短帧。",
      "离线 D2FF 复现模型可将 paired RDS_SHORT_30 复现为该 24 字节短帧。",
      "v13 离线结论记录 pairedBySeq、exactMatches、checksumMatches 均为 48556。",
    ],
    notes: [
      "该帧不能直接等同于 LoginToDSC 成功 ACK。",
      "该帧不能证明可让设备进入 Register OK。",
      "通用 checksum 公式不直接解释 DSC_SHORT_24；D2FF 确认短帧存在特殊构造/覆盖模型。",
      "暂不判定为业务数据帧。",
      SAFETY_NOTE,
    ],
    confidenceNotes: [
      "置信度来自 RDS30 -> DSC24 的离线精确复现统计。",
      "线上回发 mirror 原始包实验无明显效果，因此不能转化为自动 ACK 逻辑。",
    ],
    sourceHints: ["raw_packet", "periodicity", "d2ff_exact_reproduction", "siteunit_static_reverse"],
    towerWebEvidence: [],
  },
  RDS_SHORT_30_TYPE_1180_D2FF: {
    frameClass: "RDS_SHORT_30_TYPE_1180_D2FF",
    semanticClass: "RDS_HEARTBEAT_KEEPALIVE_ACK_REQUIRED",
    chineseName: "RDS心跳/保活帧，需要确认",
    confidence: 0.96,
    channel: "UDP_RDS",
    totalLength: 30,
    payloadLengthLE: 6,
    typeA: "1180_D2FF",
    typeBytes: { typeByte: 0x11, flagByte: 0x80, classByte: 0xd2, tailByte: 0xff },
    ackRequiredFlag: true,
    businessDataConfirmed: false,
    evidence: [
      "真实设备周期性重复发送 totalLength=30、typeA=1180_D2FF 的 UDP_RDS 短帧。",
      "flagByte=0x80，对应 ackRequiredFlag 候选。",
      "SiteUnit 离线证据包含 RunRDS、SendRDSHeartbeat、RDSIp、RDSHeartBeat。",
      "离线 D2FF 模型显示其可派生 paired DSC_SHORT_24 确认短帧。",
    ],
    notes: [
      "当前 RDS 通道尚未出现非 30 字节业务数据帧。",
      "不能标注为实时业务数据 payload；只标注为心跳/保活/需要确认候选帧。",
      SAFETY_NOTE,
    ],
    confidenceNotes: [
      "置信度来自 raw log 周期性、SiteUnit RDS 相关字符串和 D2FF paired ACK 复现证据。",
      "当前仍不能确认 RDS 实时业务 payload 结构。",
    ],
    sourceHints: ["raw_packet", "periodicity", "siteunit_static_reverse", "d2ff_exact_reproduction"],
    towerWebEvidence: [],
  },
};

const TYPE_A_ANNOTATIONS = {
  "110046ff": {
    typeA: "1100_46FF",
    semanticClass: "DSC_REGISTER_CONFIG_REQUEST",
    chineseName: "DSC注册/配置请求候选",
    confidence: 0.94,
    notes: [
      "classByte=0x46，与 DSC_CONFIG_209/245 注册/配置重试候选帧关联。",
      SAFETY_NOTE,
    ],
    sourceHints: ["raw_packet", "dsc_config_uri_diff", "siteunit_static_reverse"],
  },
  "1f00d2ff": {
    typeA: "1F00_D2FF",
    semanticClass: "D2FF_ACK_CONFIRM_SHORT_REPRODUCED",
    chineseName: "D2FF类确认短帧候选",
    confidence: 0.98,
    notes: [
      "不能直接等同于 LoginToDSC 成功 ACK。",
      SAFETY_NOTE,
    ],
    sourceHints: ["raw_packet", "d2ff_exact_reproduction", "siteunit_static_reverse"],
  },
  "1180d2ff": {
    typeA: "1180_D2FF",
    semanticClass: "RDS_HEARTBEAT_KEEPALIVE_ACK_REQUIRED",
    chineseName: "RDS心跳/保活且需要确认候选",
    confidence: 0.96,
    notes: [
      "flagByte=0x80 为 ackRequiredFlag 候选；官方语义未确认。",
      SAFETY_NOTE,
    ],
    sourceHints: ["raw_packet", "periodicity", "siteunit_static_reverse"],
  },
  "110047ff": {
    typeA: "1100_47FF",
    semanticClass: "DSC_REGISTER_CONFIG_RESPONSE_CANDIDATE",
    chineseName: "DSC注册/配置响应候选",
    confidence: 0.78,
    notes: [
      "SiteUnit ParseData 中 frame[6] == 0x47 进入登录状态 handler。",
      "该 typeA 仅为离线候选，线上接受行为未确认。",
      SAFETY_NOTE,
    ],
    sourceHints: ["siteunit_static_reverse", "class47_offline_model"],
  },
};

const CLASS_BYTE_ANNOTATIONS = {
  "0x46": {
    classByte: 0x46,
    semanticClass: "DSC_REGISTER_CONFIG_REQUEST",
    chineseName: "DSC注册/配置请求类候选",
    confidence: 0.9,
    notes: [SAFETY_NOTE],
  },
  "0x47": {
    classByte: 0x47,
    semanticClass: "DSC_REGISTER_CONFIG_RESPONSE_CANDIDATE",
    chineseName: "DSC注册/配置响应类候选",
    confidence: 0.85,
    notes: [
      "SiteUnit ParseData frame[6] == 0x47 分发到登录状态 handler 0x7e804。",
      "仅离线确认分支，不代表线上 ACK 已验证。",
      SAFETY_NOTE,
    ],
  },
  "0xd2": {
    classByte: 0xd2,
    semanticClass: "HEARTBEAT_KEEPALIVE_ACK_CLASS",
    chineseName: "心跳/保活/确认类候选",
    confidence: 0.92,
    notes: [SAFETY_NOTE],
  },
};

const REGISTER_RESULT_CODE_ANNOTATIONS = {
  0: { value: 0, meaning: "Success", chineseName: "成功", confidence: 0.95 },
  1: { value: 1, meaning: "Fail", chineseName: "失败", confidence: 0.95 },
  2: { value: 2, meaning: "UnRegister", chineseName: "未注册", confidence: 0.95 },
};

const SERVICE_CHANNEL_TYPE_ANNOTATIONS = {
  0: { fieldId: 0, chineseName: "诊断数据通道", valueFormat: "udp://host:port", requiredMask: "0x01", confidence: 0.9 },
  5: { fieldId: 5, chineseName: "上行发布通道", valueFormat: "udp://host:port", requiredMask: "0x02", confidence: 0.88 },
  6: { fieldId: 6, chineseName: "事件数据通道", valueFormat: "udp://host:port", requiredMask: "0x04", confidence: 0.88 },
  7: { fieldId: 7, chineseName: "实时数据通道", valueFormat: "udp://host:port", requiredMask: "0x08", confidence: 0.88 },
  8: { fieldId: 8, chineseName: "历史数据通道", valueFormat: "udp://host:port", requiredMask: "0x10", confidence: 0.88 },
  9: { fieldId: 9, chineseName: "图像发布通道", valueFormat: "udp://host:port", requiredMask: "0x20", confidence: 0.88 },
};

const ACK_CONSTRUCTION_MODELS = {
  class47RegisterResponse: {
    status: "offline_candidate_only",
    safeToSend: false,
    ackHex: null,
    typeA: "110047ff",
    confidence: 0.78,
    payloadLayout: {
      resultCode: "payload[0], 0=Success, 1=Fail, 2=UnRegister",
      serviceCount: "payload[1..2] uint16LE",
      entries: "payload[3..] repeated TLV: fieldId:uint8, valueLength:uint8, valueBytes:ASCII",
      requiredMask: "0x3f",
      requiredFieldIds: [0, 5, 6, 7, 8, 9],
      payloadLengthCandidate: 171,
    },
    notes: [
      "离线模型已通过已恢复的 ParseData/handler 模拟检查。",
      "线上接受行为未验证；不允许自动发送或接入 fsu-gateway 回包逻辑。",
      SAFETY_NOTE,
    ],
  },
};

const HEADER_CONTEXT_NOTES = {
  range: "frame bytes[8..19]",
  status: "analyzed_offline_only",
  currentConclusion: "copy exact 0x46 request bytes[8..19] for offline 0x47 candidate",
  confidence: "high-confidence candidate",
  evidence: [
    "DSC_CONFIG_209 and DSC_CONFIG_245 use the same observed 0x46 header context pattern, so the context is independent of DHCP placeholder vs explicit IP URI payload variant.",
    "D2FF RDS30 -> DSC24 pairs show context bytes can be class/direction specific; offset 16/17/19 differ in the ACK short frame family.",
    "No real 0x47 response frame has been captured, so bytes[8..19] official semantics remain unknown.",
  ],
  offset161719Notes: [
    "For D2FF short confirmation reproduction, offsets 16,17,19 are set after checksum as c1,62,2d in the reproduced ACK24 model.",
    "This D2FF behavior should not be generalized blindly to classByte=0x47 long register response.",
  ],
  safety: SAFETY_NOTE,
};

const SEQ_STRATEGY_NOTES = {
  status: "offline_candidate_only",
  d2ffEvidence: "RDS_SHORT_30 and paired DSC_SHORT_24 use the same seqLE throughout observed raw logs.",
  class47Candidate: "mirror 0x46 request seqLE",
  confidence: "high-confidence candidate",
  caveats: [
    "No live 0x47 response frame has been observed.",
    "D2FF same-seq behavior is strong evidence for confirmation-style frames but does not by itself prove class47 behavior.",
  ],
  safety: SAFETY_NOTE,
};

const CLASS47_CANDIDATE_NOTES = {
  bestCandidate: "110047ff",
  payloadLength: 171,
  totalLength: 195,
  requiredMask: "0x3f",
  ackRequiredFlag: false,
  seqStrategy: "mirror 0x46 request seqLE",
  headerContextStrategy: "copy 0x46 request bytes[8..19]",
  safeToSend: false,
  noOnlineUse: true,
  notes: [
    "Offline model only; online acceptance is not verified.",
    "Do not send.",
    "Do not integrate into service.py or fsu-gateway runtime reply logic.",
  ],
};

function getFrameClassAnnotation(frameClass) {
  return FRAME_CLASS_ANNOTATIONS[frameClass] || null;
}

function getTypeAAnnotation(typeA) {
  return TYPE_A_ANNOTATIONS[String(typeA || "").toLowerCase()] || null;
}

function getChannelAnnotation(channel) {
  return CHANNEL_ANNOTATIONS[channel] || null;
}

function getClassByteAnnotation(classByte) {
  if (classByte === null || classByte === undefined) {
    return null;
  }
  const key = `0x${Number(classByte).toString(16).padStart(2, "0")}`;
  return CLASS_BYTE_ANNOTATIONS[key] || null;
}

module.exports = {
  ACK_CONSTRUCTION_MODELS,
  CHANNEL_ANNOTATIONS,
  CLASS_BYTE_ANNOTATIONS,
  CLASS47_CANDIDATE_NOTES,
  FRAME_CLASS_ANNOTATIONS,
  FINAL_OFFLINE_SUMMARY_PATH,
  HEADER_CONTEXT_NOTES,
  HEADER_FIELD_ANNOTATIONS,
  OFFLINE_PROTOCOL_MAP_VERSION,
  REGISTER_RESULT_CODE_ANNOTATIONS,
  SERVICE_CHANNEL_TYPE_ANNOTATIONS,
  SEQ_STRATEGY_NOTES,
  TYPE_A_ANNOTATIONS,
  getChannelAnnotation,
  getClassByteAnnotation,
  getFrameClassAnnotation,
  getTypeAAnnotation,
};
