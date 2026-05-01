"use strict";

const FRAME_CLASS_ANNOTATIONS = {
  DSC_CONFIG_209_TYPE_1100_46FF: {
    frameClass: "DSC_CONFIG_209_TYPE_1100_46FF",
    semanticClass: "DSC_REGISTER_CONFIG_RETRY",
    chineseName: "DSC注册/配置重试帧A",
    confidence: 0.75,
    channel: "UDP_DSC",
    totalLength: 209,
    typeA: "1100_46FF",
    businessDataConfirmed: false,
    notes: [
      "DSC 通道",
      "totalLength=209",
      "typeA=1100_46FF",
      "当前约 3.031 秒周期重复",
      "当前没有收到能使其停止的确认",
      "暂不判定为业务数据帧",
      "只读逆向注释，未由厂商协议文档确认",
    ],
  },
  DSC_CONFIG_245_TYPE_1100_46FF: {
    frameClass: "DSC_CONFIG_245_TYPE_1100_46FF",
    semanticClass: "DSC_REGISTER_CONFIG_RETRY_EXT",
    chineseName: "DSC注册/配置重试帧B/扩展帧",
    confidence: 0.75,
    channel: "UDP_DSC",
    totalLength: 245,
    typeA: "1100_46FF",
    businessDataConfirmed: false,
    notes: [
      "DSC 通道",
      "totalLength=245",
      "typeA=1100_46FF",
      "与 209 帧同 typeA 但长度不同",
      "245 与 209 的 36 字节长度差异需要优先验证是否由 URI 字符串长度差异解释",
      "可能属于注册/配置阶段的显式 IP 版本配置帧",
      "暂不判定为业务数据帧",
      "只读逆向注释，未由厂商协议文档确认",
    ],
  },
  DSC_SHORT_24_TYPE_1F00_D2FF: {
    frameClass: "DSC_SHORT_24_TYPE_1F00_D2FF",
    semanticClass: "DSC_KEEPALIVE_OR_ACK_WAIT",
    chineseName: "DSC短心跳/等待确认候选帧",
    confidence: 0.7,
    channel: "UDP_DSC",
    totalLength: 24,
    typeA: "1F00_D2FF",
    businessDataConfirmed: false,
    notes: [
      "DSC 通道",
      "totalLength=24",
      "typeA=1F00_D2FF",
      "当前约 1.063 秒周期重复",
      "与 RDS_SHORT_30 成对出现",
      "当前不判定为业务数据帧",
      "ACK_WAIT 仅为推断，不代表已确认 ACK 语义",
      "只读逆向注释，未由厂商协议文档确认",
    ],
  },
  RDS_SHORT_30_TYPE_1180_D2FF: {
    frameClass: "RDS_SHORT_30_TYPE_1180_D2FF",
    semanticClass: "RDS_HEARTBEAT_OR_KEEPALIVE",
    chineseName: "RDS实时通道心跳/保活候选帧",
    confidence: 0.85,
    channel: "UDP_RDS",
    totalLength: 30,
    typeA: "1180_D2FF",
    businessDataConfirmed: false,
    notes: [
      "RDS 通道",
      "totalLength=30",
      "typeA=1180_D2FF",
      "当前约 1.063 秒周期重复",
      "当前 RDS 通道尚未出现非 30 字节业务数据帧",
      "暂不判定为实时业务数据帧",
      "只读逆向注释，未由厂商协议文档确认",
    ],
  },
};

const TYPE_A_ANNOTATIONS = {
  "110046ff": {
    typeA: "1100_46FF",
    semanticClass: "DSC_REGISTER_CONFIG_RETRY_CANDIDATE",
    chineseName: "DSC注册/配置重试候选",
    confidence: 0.75,
    notes: ["只读逆向注释，未由厂商协议文档确认"],
  },
  "1f00d2ff": {
    typeA: "1F00_D2FF",
    semanticClass: "DSC_KEEPALIVE_OR_ACK_WAIT_CANDIDATE",
    chineseName: "DSC短心跳/等待确认候选",
    confidence: 0.7,
    notes: ["ACK_WAIT_INFERRED 不是确认 ACK 状态，只是推断"],
  },
  "1180d2ff": {
    typeA: "1180_D2FF",
    semanticClass: "RDS_HEARTBEAT_OR_KEEPALIVE_CANDIDATE",
    chineseName: "RDS心跳/保活候选",
    confidence: 0.85,
    notes: ["暂不判定为实时业务数据帧"],
  },
};

function getFrameClassAnnotation(frameClass) {
  return FRAME_CLASS_ANNOTATIONS[frameClass] || null;
}

function getTypeAAnnotation(typeA) {
  return TYPE_A_ANNOTATIONS[String(typeA || "").toLowerCase()] || null;
}

module.exports = {
  FRAME_CLASS_ANNOTATIONS,
  TYPE_A_ANNOTATIONS,
  getFrameClassAnnotation,
  getTypeAAnnotation,
};
