#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { buildCandidateProfiles } = require("../fsu-ack-experiments/model-login-ack-body");
const { modelAckStructure } = require("../fsu-ack-experiments/model-ack-structure");

const DATE_STEM = "2026-04-28";
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");
const DEFAULT_SITEUNIT = path.join(process.env.USERPROFILE || "C:\\Users\\测试", "Desktop", "FSU", "home", "idu", "SiteUnit");

const PY_CAPSTONE = String.raw`
import base64, json, sys
from capstone import *

payload = json.load(sys.stdin)
blob = base64.b64decode(payload["blobBase64"])
start = payload["fileStart"]
end = payload["fileEnd"]
va = payload["vaStart"]
md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.detail = False
md.skipdata = True
insns = []
for insn in md.disasm(blob[start:end], va):
    insns.append({
        "address": insn.address,
        "size": insn.size,
        "bytes": insn.bytes.hex(),
        "mnemonic": insn.mnemonic,
        "opStr": insn.op_str,
    })
offset_pairs = payload.get("offsets", [])
hits = []
for i, insn in enumerate(insns):
    op = insn["opStr"].lower()
    matched = []
    for pair in offset_pairs:
        canonical = pair["canonical"]
        for token in pair["tokens"]:
            if ("#" + token) in op or (", " + token) in op:
                matched.append(canonical)
                break
    if not matched:
        continue
    hits.append({
        "index": i,
        "instruction": insn,
        "matchedOffsets": matched,
        "context": insns[max(0, i - 40):min(len(insns), i + 41)],
    })
print(json.dumps({"instructionCount": len(insns), "hits": hits}))
`;

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

function readJsonSafe(filePath, fallback = {}) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function hex(value) {
  return `0x${Number(value).toString(16)}`;
}

function readCString(buffer, offset) {
  let end = offset;
  while (end < buffer.length && buffer[end] !== 0) end += 1;
  return buffer.toString("ascii", offset, end);
}

function parseElfSections(buffer) {
  if (buffer.length < 52 || buffer[0] !== 0x7f || buffer.toString("ascii", 1, 4) !== "ELF") {
    throw new Error("SiteUnit is not an ELF file");
  }
  const shoff = buffer.readUInt32LE(32);
  const shentsize = buffer.readUInt16LE(46);
  const shnum = buffer.readUInt16LE(48);
  const shstrndx = buffer.readUInt16LE(50);
  const raw = [];
  for (let i = 0; i < shnum; i += 1) {
    const off = shoff + i * shentsize;
    raw.push({
      index: i,
      nameOffset: buffer.readUInt32LE(off),
      virtualAddress: buffer.readUInt32LE(off + 12),
      offset: buffer.readUInt32LE(off + 16),
      size: buffer.readUInt32LE(off + 20),
    });
  }
  const shstr = raw[shstrndx];
  return raw.map((section) => ({
    ...section,
    name: readCString(buffer, shstr.offset + section.nameOffset),
  }));
}

function disassembleText(siteunitPath) {
  if (!fs.existsSync(siteunitPath)) {
    return { ok: false, error: `SiteUnit not found: ${siteunitPath}`, instructions: [] };
  }
  const buffer = fs.readFileSync(siteunitPath);
  const sections = parseElfSections(buffer);
  const text = sections.find((section) => section.name === ".text");
  if (!text) return { ok: false, error: ".text section not found", instructions: [] };
  const child = spawnSync("python", ["-c", PY_CAPSTONE], {
    input: JSON.stringify({
      blobBase64: buffer.toString("base64"),
      fileStart: text.offset,
      fileEnd: text.offset + text.size,
      vaStart: text.virtualAddress,
      offsets: [
        0x13c, 0x140, 0x14c, 0x150, 0x15c, 0x160, 0x16c, 0x170, 0x17c, 0x180, 0x18c, 0x190,
        0x3c, 0x40, 0x4c, 0x50, 0x5c, 0x60, 0x6c, 0x70, 0x7c, 0x80, 0x8c, 0x90, 0x100,
      ].map((value) => ({ canonical: hex(value), tokens: [hex(value), String(value)] })),
    }),
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (child.status !== 0) {
    return { ok: false, error: child.error ? child.error.message : child.stderr || child.stdout || "capstone disasm failed", instructions: [], hits: [] };
  }
  const parsed = JSON.parse(child.stdout);
  return {
    ok: true,
    section: {
      fileOffset: text.offset,
      fileOffsetHex: hex(text.offset),
      virtualAddress: text.virtualAddress,
      virtualAddressHex: hex(text.virtualAddress),
      size: text.size,
      sizeHex: hex(text.size),
    },
    instructionCount: parsed.instructionCount,
    hits: parsed.hits || [],
  };
}

function findFunctionStart(instructions, index) {
  for (let i = index; i >= 0; i -= 1) {
    const insn = instructions[i];
    if (insn.mnemonic === "push" || (insn.mnemonic === "stmdb" && insn.opStr.includes("lr"))) return insn.address;
    if (index - i > 500) break;
  }
  return null;
}

function literalStringsNear(strings, va, radius = 0x600) {
  const rows = [];
  for (const entry of strings) {
    const entryVa = Number.parseInt(String(entry.virtualAddressHex || entry.virtualAddress || "0").replace(/^0x/, ""), 16);
    if (Number.isFinite(entryVa) && Math.abs(entryVa - va) <= radius) {
      rows.push({ virtualAddressHex: entry.virtualAddressHex || hex(entryVa), text: entry.text });
    }
  }
  return rows.slice(0, 12);
}

function scanEndpointOffsetUses(disasm, stringsReport) {
  if (!disasm.ok) return { disasmOk: false, error: disasm.error, hits: [] };
  const interesting = ["sendto", "socket", "connect", "bind", "recvfrom", "SendRealDataQueue", "SendEventData", "RunRDS", "RDSREALDATA", "REALDATA", "EVENT", "Image", "Pic", "FTP", "Card", "Battery", "Stat", "CommState"];
  const stringItems = Array.isArray(stringsReport.strings) ? stringsReport.strings : [];
  const hits = [];
  for (const pyHit of disasm.hits || []) {
    const insn = pyHit.instruction;
    const matched = pyHit.matchedOffsets || [];
    const opLower = String(insn.opStr || "").toLowerCase();
    const mnemonic = String(insn.mnemonic || "").toLowerCase();
    const isBranchOrCompare = /^(b|bl|blx|bx|cmp|cmn|tst|mov|mvn)$/i.test(mnemonic);
    const isPcSpFpLocal = /\b(pc|sp|fp)\b/.test(opLower);
    if (isBranchOrCompare || isPcSpFpLocal) continue;
    const context = (pyHit.context || []).map((item) => ({
      vaHex: hex(item.address),
      fileOffsetHex: hex(item.address - 0x8000),
      instruction: `${item.mnemonic} ${item.opStr}`,
    }));
    const contextText = context.map((item) => item.instruction).join(" ");
    const matchedFullOffsets = matched.filter((offset) => /^0x1[3456789]/.test(offset));
    const matchedSplitOffsets = matched.filter((offset) => !matchedFullOffsets.includes(offset));
    const splitLikelyEndpoint =
      matchedFullOffsets.length > 0 ||
      (matchedSplitOffsets.length > 0 &&
        contextText.includes("#0x100") &&
        (contextText.includes("#0x80") || contextText.includes("lsl #7") || contextText.includes("lsl #0x7")));
    if (!splitLikelyEndpoint) continue;
    const nearbyStrings = literalStringsNear(stringItems, insn.address, 0x900);
    const nearbyStringText = nearbyStrings.map((item) => item.text).join(" ");
    hits.push({
      va: insn.address,
      vaHex: hex(insn.address),
      fileOffsetHex: hex(insn.address - 0x8000),
      instruction: `${insn.mnemonic} ${insn.opStr}`,
      matchedOffsets: matched,
      matchedFullOffsets,
      matchedSplitOffsets,
      readWidth:
        insn.mnemonic.startsWith("ldr") ? (insn.mnemonic.includes("h") ? "halfword" : insn.mnemonic.includes("b") ? "byte" : "word") : "not-load",
      accessKind: insn.mnemonic.startsWith("ldr") ? "read" : insn.mnemonic.startsWith("str") ? "write" : "address/calc",
      functionStartVAHex: null,
      nearbyStrings,
      networkCallNearby: interesting.filter((needle) => `${contextText} ${nearbyStringText}`.toLowerCase().includes(needle.toLowerCase())),
      participatesInNetworkCall: interesting.some((needle) => `${contextText} ${nearbyStringText}`.toLowerCase().includes(needle.toLowerCase())),
      context,
    });
  }
  return { disasmOk: true, section: disasm.section, instructionCount: disasm.instructionCount, hitCount: hits.length, hits };
}

const fields = [
  { fieldId: 0, rawOffset: "0x13c", parsedOffset: "0x140", writer: "0x7ec80", meaning: "diagnostic data channel endpoint", recommendedPort: 9000, confidence: "medium" },
  { fieldId: 5, rawOffset: "0x14c", parsedOffset: "0x150", writer: "0x7ee40", meaning: "uplink publish channel endpoint", recommendedPort: 9000, confidence: "low-medium" },
  { fieldId: 6, rawOffset: "0x15c", parsedOffset: "0x160", writer: "0x7ef38", meaning: "event data channel endpoint", recommendedPort: 9000, confidence: "low-medium" },
  { fieldId: 7, rawOffset: "0x16c", parsedOffset: "0x170", writer: "0x7f030", meaning: "real-time data channel endpoint", recommendedPort: 9000, confidence: "low-medium" },
  { fieldId: 8, rawOffset: "0x17c", parsedOffset: "0x180", writer: "0x7f128", meaning: "historical data channel endpoint", recommendedPort: 9000, confidence: "low-medium" },
  { fieldId: 9, rawOffset: "0x18c", parsedOffset: "0x190", writer: "0x7f220", meaning: "image publish channel endpoint", recommendedPort: 9000, confidence: "low-medium" },
];

function buildUsageAnalysis(slotScan) {
  const scanByOffset = new Map();
  for (const hit of slotScan.hits || []) {
    for (const offset of hit.matchedOffsets || []) {
      if (!scanByOffset.has(offset)) scanByOffset.set(offset, []);
      scanByOffset.get(offset).push(hit);
    }
  }
  const splitOffsetMap = {
    "0x13c": ["0x3c"],
    "0x140": ["0x40"],
    "0x14c": ["0x4c"],
    "0x150": ["0x50"],
    "0x15c": ["0x5c"],
    "0x160": ["0x60"],
    "0x16c": ["0x6c"],
    "0x170": ["0x70"],
    "0x17c": ["0x7c"],
    "0x180": ["0x80"],
    "0x18c": ["0x8c"],
    "0x190": ["0x90"],
  };
  const hitsFor = (offset) => [
    ...(scanByOffset.get(offset) || []),
    ...((splitOffsetMap[offset] || []).flatMap((item) => scanByOffset.get(item) || [])),
  ];
  return {
    generatedAt: new Date().toISOString(),
    method:
      "Full .text ARM disassembly scan plus existing report/string evidence. Searched endpoint ctx offsets and nearby network/queue strings.",
    fullTextScan: {
      disasmOk: slotScan.disasmOk,
      error: slotScan.error || null,
      section: slotScan.section,
      hitCount: slotScan.hitCount || 0,
      note: "Hits include writes in the login status handler and any later reads/address calculations with the same immediate offsets.",
    },
    slotUsage: fields.map((field) => ({
      fieldId: field.fieldId,
      meaningCandidate: field.meaning,
      ctxOffsets: [field.rawOffset, field.parsedOffset],
      writer: field.writer,
      confirmedUseInLoginHandler: [
        "value copied from TLV valueBytes",
        "value NUL-terminated in local buffer",
        "udp:// prefix skipped",
        "host:port parsed",
        "case-specific endpoint log printed",
      ],
      fullTextHits: [
        ...hitsFor(field.rawOffset),
        ...hitsFor(field.parsedOffset),
      ].map((hit) => ({
        vaHex: hit.vaHex,
        fileOffsetHex: hit.fileOffsetHex,
        instruction: hit.instruction,
        accessKind: hit.accessKind,
        readWidth: hit.readWidth,
        functionStartVAHex: hit.functionStartVAHex,
        networkCallNearby: hit.networkCallNearby,
        participatesInNetworkCall: hit.participatesInNetworkCall,
        nearbyStrings: hit.nearbyStrings,
      })),
      downstreamReadsRecovered: [
        ...hitsFor(field.rawOffset),
        ...hitsFor(field.parsedOffset),
      ].some((hit) => hit.accessKind === "read" && hit.participatesInNetworkCall),
      usedByFunctions: ["GetServiceAddr/Login status handler 0x7e804"],
      nearbyStrings: [
        field.meaning,
        "DS service IP configuration error",
        "GetServiceAddr",
        "LogToDS return",
      ],
      networkCallEvidence: [
        ...hitsFor(field.rawOffset),
        ...hitsFor(field.parsedOffset),
      ].filter((hit) => hit.participatesInNetworkCall),
      queueFunctionEvidence: [
        ...hitsFor(field.rawOffset),
        ...hitsFor(field.parsedOffset),
      ].filter((hit) => (hit.networkCallNearby || []).some((item) => /Send|REALDATA|EVENT|Image|Card|Battery|Stat|CommState/i.test(item))),
      recommendedEndpoint: `udp://192.168.100.123:${field.recommendedPort}`,
      portCandidate: field.recommendedPort,
      confidence: field.confidence,
      reason:
        field.fieldId === 0
          ? "diagnostic/DS service channel is closest to UDP_DSC platform listener 9000"
          : "field is returned by DSC login service as a DS endpoint; no static evidence ties it to RDS 7000, so keep 9000 as preferred offline profile",
    })),
    conclusion:
      "Endpoint slot parsing is recovered. Full .text scan did not recover a clean downstream socket/sendto consumer chain for the six slots; recommended profile remains all_9000 by protocol context, not by direct socket xref closure.",
    doNotSend: true,
  };
}

function buildPortProfileAnalysis(rawStats) {
  const profiles = buildCandidateProfiles("192.168.100.123");
  return {
    generatedAt: new Date().toISOString(),
    platformListeners: { UDP_DSC: 9000, UDP_RDS: 7000 },
    rawLogComparison: {
      dscTo9000: "DSC_CONFIG_209/245 and DSC_SHORT_24 are observed on localPort 9000",
      rdsTo7000: "RDS_SHORT_30 is observed on localPort 7000",
      note: "The six login ACK endpoint TLVs are parsed by DSC Login/GetServiceAddr code, not by the observed RDS short-frame handler.",
      stats: rawStats,
    },
    profileRanking: [
      {
        profileName: "recommended_profile",
        basedOn: "all_9000_profile",
        confidence: "low-medium",
        reason: "all six endpoints are DS service endpoints delivered by DSC login response; no fieldId-specific RDS socket consumer was recovered.",
      },
      {
        profileName: "mixed_9000_7000_profile",
        confidence: "low",
        reason: "kept as alternate because some field labels are data/publish channels, but no direct evidence maps them to RDS UDP 7000.",
      },
      {
        profileName: "all_7000_profile",
        confidence: "low",
        reason: "control/diagnostic fieldId 0 does not fit RDS-only listener; kept only as contrast.",
      },
    ],
    profiles,
    recommendedProfile: profiles.find((item) => item.name === "recommended_profile"),
    conclusion: "Recommend all_9000_profile for offline review only. This does not make the frame safe to send.",
    doNotSend: true,
  };
}

function buildStage14Checklist() {
  return [
    { item: "完整 ACK typeA 有候选来源，置信度至少 medium", pass: true, result: "110047ff / medium" },
    { item: "success code 有候选来源", pass: true, result: "body[0]=0" },
    { item: "success code offset 有候选来源", pass: true, result: "frame[24] / body[0]" },
    { item: "body layout 有候选来源", pass: true, result: "status + entryCount + TLV entries" },
    { item: "最小 body length 有候选来源", pass: true, result: "six required endpoint TLVs" },
    { item: "必填 entry 明确", pass: true, result: "0,5,6,7,8,9" },
    { item: "必填 entry 的值格式明确", pass: true, result: "udp://host:port" },
    { item: "endpoint 值有推荐 profile", pass: true, result: "recommended_profile = all_9000_profile, low-medium confidence" },
    { item: "length/checksum 计算器可用于目标帧", pass: true, result: "confirmed offline formula" },
    { item: "seq 策略至少有候选，置信度至少 low-medium", pass: true, result: "mirror / low-medium" },
    { item: "offset 8..19 有候选策略", pass: true, result: "00000000c162002d00000000 / medium" },
    { item: "不再依赖 mirror 原始包", pass: false, result: "seq and header still use mirror-style candidates; live send remains blocked" },
  ];
}

function updateAckModel(outDir, usage, portProfiles, checklist) {
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure({
      candidateFields: {
        endpointSlotUsage: usage.slotUsage,
        endpointPortProfiles: portProfiles.profiles,
        recommendedProfile: portProfiles.recommendedProfile,
        typeA: [{ candidate: "110047ff", confidence: "medium" }],
        seqStrategy: [{ strategy: "mirror request seqLE", confidence: "low-medium" }],
        offset8to19Strategy: [{ value: "00000000c162002d00000000", confidence: "medium" }],
      },
      unknowns: ["direct endpoint slot to socket/sendto xref", "direct proof that all six endpoints should use UDP 9000", "non-mirror seq/header proof"],
    }),
  };
  model.status = "candidate-only";
  model.reason = "Endpoint profile recommended for offline review, but live send is still blocked by missing direct socket xrefs and mirror-style seq/header assumptions.";
  model.safeToSend = false;
  model.stage14ReadinessChecklist = checklist;
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.json`), `${JSON.stringify(model, null, 2)}\n`, "utf8");
  fs.writeFileSync(path.join(outDir, `ack-structure-model-${DATE_STEM}.md`), ["# ACK Structure Model", "", "```json", JSON.stringify(model, null, 2), "```", ""].join("\n"), "utf8");
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const siteunit = path.resolve(args.siteunit || DEFAULT_SITEUNIT);
  const header = readJsonSafe(path.join(outDir, `header-unknown-8-19-analysis-${DATE_STEM}.json`));
  const strings = readJsonSafe(path.join(outDir, `siteunit-strings-${DATE_STEM}.json`), {});
  const disasm = disassembleText(siteunit);
  const slotScan = scanEndpointOffsetUses(disasm, strings);
  const usage = buildUsageAnalysis(slotScan);
  const portProfiles = buildPortProfileAnalysis(header.rawLogStats || {});
  const checklist = buildStage14Checklist();
  const gate = {
    canEnterStage14: false,
    conclusion: "不能进入可发送 ACK 构造，只能继续反汇编数据流或进行离线候选帧审查。",
    blockingItems: checklist.filter((item) => !item.pass),
  };
  const mainReport = {
    generatedAt: new Date().toISOString(),
    overview: "Endpoint slots are parsed and logged per channel, but direct downstream socket/sendto consumers remain unresolved. The offline recommendation is all_9000_profile.",
    endpointSlotUsage: usage,
    endpointPortProfileAnalysis: portProfiles,
    recommendedProfile: portProfiles.recommendedProfile,
    all9000Profile: portProfiles.profiles.find((item) => item.name === "all_9000_profile"),
    mixed90007000Profile: portProfiles.profiles.find((item) => item.name === "mixed_9000_7000_profile"),
    all7000Profile: portProfiles.profiles.find((item) => item.name === "all_7000_profile"),
    stage14ReadinessChecklist: checklist,
    stage14Gate: gate,
    safety: {
      networkAckSent: false,
      sendOneShotAckRun: false,
      fsuGatewayMainLogicModified: false,
      databaseWrites: false,
      automaticAckAdded: false,
      sendableAckHexGenerated: false,
      safeToSend: false,
    },
  };

  const paths = {};
  paths.usage = writeJsonMd(outDir, "endpoint-slot-usage-analysis", "Endpoint Slot Usage Analysis", usage, [
    usage.conclusion,
  ]);
  paths.portProfiles = writeJsonMd(outDir, "endpoint-port-profile-analysis", "Endpoint Port Profile Analysis", portProfiles, [
    portProfiles.conclusion,
  ]);
  paths.main = writeJsonMd(outDir, "login-ack-endpoint-slot-usage-final", "Login ACK Endpoint Slot Usage Final", mainReport, [
    mainReport.overview,
    "",
    `Recommended profile: ${portProfiles.recommendedProfile.name}`,
    "",
    gate.conclusion,
  ]);
  updateAckModel(outDir, usage, portProfiles, checklist);
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
